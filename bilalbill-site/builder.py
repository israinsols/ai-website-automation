"""Build a fast, static, review-gated website from Markdown content."""

from __future__ import annotations

import json
import math
import os
import re
from datetime import date, datetime
from html import escape
from pathlib import Path
from typing import Any

import frontmatter
from jinja2 import Environment, FileSystemLoader, select_autoescape
from markdown_it import MarkdownIt

from config import SiteConfig
from generator import slugify, word_count
from images import make_cover_images
from seo import (
    article_json_ld,
    canonical_url,
    robots_txt,
    rss_xml,
    sitemap_xml,
    website_json_ld,
)

POSTS_PER_PAGE = 10
MANIFEST_NAME = ".bilalbill-generated-files.json"


def _markdown_engine() -> MarkdownIt:
    return MarkdownIt("commonmark", {"html": False}).enable(
        ["table", "strikethrough"]
    )


def _render_markdown(text: str) -> tuple[str, list[dict[str, Any]]]:
    engine = _markdown_engine()
    tokens = engine.parse(text)
    toc: list[dict[str, Any]] = []
    for index, token in enumerate(tokens):
        if token.type != "heading_open" or index + 1 >= len(tokens):
            continue
        inline = tokens[index + 1]
        if inline.type != "inline":
            continue
        title = inline.content.strip()
        identifier = slugify(title)
        if not identifier:
            continue
        token.attrSet("id", identifier)
        toc.append({"title": title, "id": identifier, "level": int(token.tag[1])})
    rendered = engine.renderer.render(tokens, engine.options, {})
    rendered = re.sub(r"<img\b[^>]*>", "", rendered, flags=re.IGNORECASE)
    return rendered, toc


def _read_posts(config: SiteConfig) -> tuple[list[dict[str, Any]], list[str]]:
    published: list[dict[str, Any]] = []
    drafts: list[str] = []
    seen_slugs: set[str] = set()
    config.posts_dir.mkdir(parents=True, exist_ok=True)
    for path in sorted(config.posts_dir.glob("*.md")):
        post = frontmatter.load(path)
        slug = slugify(str(post.get("slug", path.stem)))
        status = str(post.get("status", "draft")).lower()
        if status != "published":
            drafts.append(str(post.get("title", path.stem)))
            continue
        if not slug or not post.get("title"):
            raise ValueError(f"Published post has missing/invalid title or slug: {path.name}")
        if slug in seen_slugs:
            raise ValueError(f"Multiple published posts use the same slug: {slug}")
        seen_slugs.add(slug)
        title = str(post["title"]).strip()
        description = str(post.get("meta_description", "")).strip()
        category = str(post.get("category", "General")).strip()
        published_date = str(post.get("date", date.today().isoformat()))
        canonical = canonical_url(config, f"/{slug}/")
        cover, thumbnail = make_cover_images(title, config.site_name)
        published.append(
            {
                "title": title,
                "slug": slug,
                "keyword": str(post.get("keyword", "")),
                "meta_description": description or title,
                "category": category,
                "category_slug": slugify(category) or "general",
                "tags": [str(tag).strip() for tag in post.get("tags", []) if str(tag).strip()],
                "author": str(post.get("author", config.author)),
                "date": published_date,
                "status": status,
                "canonical": canonical,
                "social_image": canonical_url(config, f"/images/{slug}.png"),
                "thumbnail": f"/images/{slug}-thumb.webp",
                "cover_bytes": cover,
                "thumbnail_bytes": thumbnail,
                "reading_time": max(1, math.ceil(word_count(post.content) / 220)),
                "content": post.content,
                "source": path,
            }
        )
    published.sort(key=lambda item: (item["date"], item["slug"]), reverse=True)
    return published, drafts


def _read_pages(config: SiteConfig) -> list[dict[str, Any]]:
    pages = []
    config.pages_dir.mkdir(parents=True, exist_ok=True)
    for path in sorted(config.pages_dir.glob("*.md")):
        post = frontmatter.load(path)
        if str(post.get("status", "published")).lower() != "published":
            continue
        slug = slugify(str(post.get("slug", path.stem)))
        if not slug or not post.get("title"):
            raise ValueError(f"Static page has missing/invalid title or slug: {path.name}")
        content_html, _ = _render_markdown(post.content)
        pages.append(
            {
                "slug": slug,
                "title": str(post["title"]),
                "meta_description": str(post.get("meta_description", post["title"])),
                "content_html": content_html,
                "canonical": canonical_url(config, f"/{slug}/"),
            }
        )
    return pages


def _json_ld_page(config: SiteConfig, title: str, url: str, description: str) -> dict[str, Any]:
    return {
        "@context": "https://schema.org",
        "@type": "WebPage",
        "name": title,
        "description": description,
        "url": url,
        "isPartOf": {"@type": "WebSite", "name": config.site_name, "url": config.base_url + "/"},
    }


def _write_generated(public: Path, relative: str, content: bytes | str, generated: set[str]) -> None:
    target = public / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, str):
        target.write_text(content, encoding="utf-8")
    else:
        target.write_bytes(content)
    generated.add(relative.replace("\\", "/"))


def _render_context(config: SiteConfig, template: str, **context: Any) -> str:
    environment = Environment(
        loader=FileSystemLoader(config.root / "templates"),
        autoescape=select_autoescape(("html", "xml")),
    )
    values = {
        "site_name": config.site_name,
        "language": config.language,
        "base_url": config.base_url,
        "base_path": config.base_path,
        "current_year": date.today().year,
        "social_image": canonical_url(config, "/static/og-default.png"),
        "og_type": "website",
        "json_ld": website_json_ld(config),
        **context,
    }
    html = environment.get_template(template).render(**values)
    if config.base_path:
        route_prefix = config.base_path + "/"
        html = re.sub(
            r'\b(href|src|action)="/(?=[^/])',
            lambda match: f'{match.group(1)}="{route_prefix}',
            html,
        )
        html = html.replace('href="/"', f'href="{route_prefix}"')
    return html


def _taxonomy_pages(
    config: SiteConfig,
    public: Path,
    generated: set[str],
    taxonomy: str,
    groups: dict[str, tuple[str, list[dict[str, Any]]]],
) -> list[dict[str, Any]]:
    urls: list[dict[str, Any]] = []
    environment = Environment(
        loader=FileSystemLoader(config.root / "templates"),
        autoescape=select_autoescape(("html", "xml")),
    )
    template = environment.get_template("category.html")
    for slug, (name, grouped_posts) in groups.items():
        pages = max(1, math.ceil(len(grouped_posts) / POSTS_PER_PAGE))
        for number in range(1, pages + 1):
            base_path = f"{taxonomy}/{slug}"
            route = f"/{base_path}/" if number == 1 else f"/{base_path}/page/{number}/"
            page_title = f"{name} articles | {config.site_name}"
            canonical = canonical_url(config, route)
            page_posts = grouped_posts[(number - 1) * POSTS_PER_PAGE : number * POSTS_PER_PAGE]
            html = template.render(
                site_name=config.site_name,
                language=config.language,
                base_path=config.base_path,
                current_year=date.today().year,
                page_title=page_title,
                description=f"Browse published articles about {name}.",
                canonical=canonical,
                social_image=canonical_url(config, "/static/og-default.png"),
                og_type="website",
                json_ld=_json_ld_page(config, page_title, canonical, f"Articles about {name}"),
                heading=name,
                taxonomy="Category" if taxonomy == "category" else "Tag",
                posts=page_posts,
                pages=pages,
                page_number=number,
                previous_url=(
                    f"/{base_path}/" if number == 2 else f"/{base_path}/page/{number - 1}/"
                ),
                next_url=f"/{base_path}/page/{number + 1}/",
            )
            if config.base_path:
                route_prefix = config.base_path + "/"
                html = re.sub(
                    r'\b(href|src|action)="/(?=[^/])',
                    lambda match: f'{match.group(1)}="{route_prefix}',
                    html,
                )
                html = html.replace('href="/"', f'href="{route_prefix}"')
            relative = f"{base_path}/index.html" if number == 1 else f"{base_path}/page/{number}/index.html"
            _write_generated(public, relative, html, generated)
            urls.append({"loc": canonical, "lastmod": date.today().isoformat()})
    return urls


def _write_drafts_report(config: SiteConfig, drafts: list[str]) -> Path:
    report_dir = config.root / "build"
    report_dir.mkdir(parents=True, exist_ok=True)
    items = "".join(f"<li>{escape(title)}</li>" for title in drafts)
    report = (
        "<!doctype html><meta charset=\"utf-8\"><title>Local drafts report</title>"
        "<h1>Local drafts report (not deployed)</h1>"
        f"<p>{len(drafts)} unpublished draft(s).</p><ul>{items}</ul>"
    )
    target = report_dir / "drafts-report.html"
    target.write_text(report, encoding="utf-8")
    return target


def _clean_previous_output(public: Path) -> set[str]:
    manifest = public / MANIFEST_NAME
    if not manifest.is_file():
        return set()
    try:
        previous = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Cannot read generated-file manifest: {manifest}") from exc
    if not isinstance(previous, list) or not all(isinstance(item, str) for item in previous):
        raise ValueError(f"Generated-file manifest is invalid: {manifest}")
    root = public.resolve()
    for relative in previous:
        candidate = public / relative
        if candidate.is_symlink():
            raise ValueError(f"Refusing to remove a symlink listed in the manifest: {relative}")
        target = candidate.resolve()
        if root not in target.parents or target == root:
            raise ValueError(f"Refusing to remove a path outside public/: {relative}")
        if target.is_file():
            target.unlink()
    return set()


def build_site(config: SiteConfig) -> dict[str, Any]:
    """Render published content only and save a separate local report of drafts."""
    public = config.public_dir
    public.mkdir(parents=True, exist_ok=True)
    generated = _clean_previous_output(public)
    posts, drafts = _read_posts(config)
    pages = _read_pages(config)
    post_slugs = {post["slug"] for post in posts}
    page_slugs = {page["slug"] for page in pages}
    duplicates = post_slugs & page_slugs
    if duplicates:
        raise ValueError(
            "Published posts and static pages share route slug(s): "
            + ", ".join(sorted(duplicates))
        )

    for asset in (config.root / "static").rglob("*"):
        if asset.is_file():
            relative = asset.relative_to(config.root / "static")
            _write_generated(public, f"static/{relative.as_posix()}", asset.read_bytes(), generated)

    static_default_cover, _ = make_cover_images(config.site_name, config.site_name)
    _write_generated(public, "static/og-default.png", static_default_cover, generated)

    category_groups: dict[str, tuple[str, list[dict[str, Any]]]] = {}
    tag_groups: dict[str, tuple[str, list[dict[str, Any]]]] = {}
    for post in posts:
        key = post["category_slug"]
        category_groups.setdefault(key, (post["category"], []))[1].append(post)
        _write_generated(public, f"images/{post['slug']}.png", post["cover_bytes"], generated)
        _write_generated(public, f"images/{post['slug']}-thumb.webp", post["thumbnail_bytes"], generated)
        for tag in post["tags"]:
            tag_slug = slugify(tag)
            if tag_slug:
                tag_groups.setdefault(tag_slug, (tag, []))[1].append(post)

    categories = [
        {"name": name, "slug": slug, "count": len(grouped_posts)}
        for slug, (name, grouped_posts) in sorted(category_groups.items())
    ]
    home_url = canonical_url(config, "/")
    home_html = _render_context(
        config,
        "home.html",
        page_title=f"{config.site_name} | Practical {config.niche} guides",
        description=f"Helpful, carefully reviewed {config.niche} articles from {config.site_name}.",
        canonical=home_url,
        og_type="website",
        json_ld=website_json_ld(config),
        posts=posts[:POSTS_PER_PAGE],
        categories=categories,
        niche=config.niche,
    )
    _write_generated(public, "index.html", home_html, generated)

    sitemap_urls = [{"loc": home_url, "lastmod": date.today().isoformat()}]
    for post in posts:
        body_html, toc = _render_markdown(post["content"])
        rendered_post = dict(post)
        rendered_post.pop("cover_bytes")
        rendered_post.pop("thumbnail_bytes")
        rendered_post.pop("content")
        tag_slugs = [slugify(tag) for tag in post["tags"]]
        related = [
            item
            for item in posts
            if item["slug"] != post["slug"] and item["category_slug"] == post["category_slug"]
        ][:3]
        html = _render_context(
            config,
            "post.html",
            page_title=f"{post['title']} | {config.site_name}",
            description=post["meta_description"],
            canonical=post["canonical"],
            social_image=post["social_image"],
            og_type="article",
            json_ld=article_json_ld(config, post),
            post=rendered_post,
            body_html=body_html,
            toc=toc,
            related=related,
            tag_slugs=tag_slugs,
        )
        _write_generated(public, f"{post['slug']}/index.html", html, generated)
        sitemap_urls.append({"loc": post["canonical"], "lastmod": post["date"]})

    sitemap_urls.extend(_taxonomy_pages(config, public, generated, "category", category_groups))
    sitemap_urls.extend(_taxonomy_pages(config, public, generated, "tag", tag_groups))
    for page in pages:
        canonical = page["canonical"]
        html = _render_context(
            config,
            "page.html",
            page_title=f"{page['title']} | {config.site_name}",
            description=page["meta_description"],
            canonical=canonical,
            json_ld=_json_ld_page(config, page["title"], canonical, page["meta_description"]),
            page=page,
        )
        _write_generated(public, f"{page['slug']}/index.html", html, generated)
        sitemap_urls.append({"loc": canonical, "lastmod": date.today().isoformat()})

    error_html = _render_context(
        config,
        "page.html",
        page_title=f"Page not found | {config.site_name}",
        description="The requested page could not be found.",
        canonical=home_url,
        page={
            "title": "404 - Page not found",
            "content_html": '<p>Sorry, this page is not available. <a href="/">Return to the homepage</a>.</p>',
        },
        json_ld=_json_ld_page(config, "Page not found", home_url, "Page not found"),
    )
    _write_generated(public, "404.html", error_html, generated)
    _write_generated(public, "robots.txt", robots_txt(config), generated)
    _write_generated(public, "sitemap.xml", sitemap_xml(sitemap_urls), generated)
    _write_generated(public, "rss.xml", rss_xml(config, posts), generated)
    if not config.base_path:
        _write_generated(public, "CNAME", config.domain + "\n", generated)

    indexnow_key = os.getenv("INDEXNOW_KEY", "").strip()
    if indexnow_key:
        if not re.fullmatch(r"[A-Za-z0-9-]{8,128}", indexnow_key):
            raise ValueError("INDEXNOW_KEY must be 8-128 letters, digits, or hyphens.")
        _write_generated(public, f"{indexnow_key}.txt", indexnow_key, generated)

    (public / MANIFEST_NAME).write_text(
        json.dumps(sorted(generated), indent=2) + "\n", encoding="utf-8"
    )
    report = _write_drafts_report(config, drafts)
    return {
        "posts": len(posts),
        "drafts": len(drafts),
        "pages": len(pages),
        "files": len(generated),
        "draft_report": report,
        "public_dir": public,
    }
