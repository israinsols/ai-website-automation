import json
import re
import shutil
import xml.etree.ElementTree as ET
from pathlib import Path

import frontmatter

from builder import build_site
from config import SiteConfig


def config_at(root: Path, base_path: str = "") -> SiteConfig:
    return SiteConfig(
        root=root,
        site_name="bilalbill",
        domain="bilalbill.com",
        base_path=base_path,
        niche="technology",
        posts_per_day=1,
        language="en-PK",
        author="Bilal",
        auto_publish=False,
        social_telegram=False,
        social_facebook=False,
        social_pinterest=False,
        keyword_seeds=("bilalbill",),
        contact_email="hello@bilalbill.com",
        gsc_site_url="sc-domain:bilalbill.com",
    )


def test_build_contains_only_published_posts_and_valid_seo(tmp_path):
    config = config_at(tmp_path)
    project_root = Path(__file__).resolve().parents[1]
    shutil.copytree(project_root / "templates", config.root / "templates")
    shutil.copytree(project_root / "static", config.root / "static")
    config.posts_dir.mkdir(parents=True)
    config.pages_dir.mkdir(parents=True)
    article = frontmatter.Post(
        "## A useful guide\n\nSome clear, helpful information for readers.\n\n"
        "![remote tracker](https://tracker.example/pixel.png)",
        title="bilalbill sample guide",
        slug="bilalbill-sample-guide",
        keyword="bilalbill",
        meta_description="A helpful bilalbill guide.",
        category="Technology",
        tags=["Guides"],
        author="Bilal",
        date="2026-11-07",
        status="published",
    )
    (config.posts_dir / "bilalbill-sample-guide.md").write_text(
        frontmatter.dumps(article), encoding="utf-8"
    )
    for number in range(10):
        extra = frontmatter.Post(
            f"## Guide {number}\n\nA short technology guide for the test site.",
            title=f"Technology guide {number}",
            slug=f"technology-guide-{number}",
            meta_description=f"Technology guide number {number}.",
            category="Technology",
            tags=["Guides"],
            author="Bilal",
            date=f"2026-10-{number + 1:02d}",
            status="published",
        )
        (config.posts_dir / f"technology-guide-{number}.md").write_text(
            frontmatter.dumps(extra), encoding="utf-8"
        )
    draft = frontmatter.Post(
        "This draft is not public.",
        title="Unpublished secret draft",
        slug="unpublished-secret",
        status="draft",
    )
    (config.posts_dir / "unpublished-secret.md").write_text(
        frontmatter.dumps(draft), encoding="utf-8"
    )

    result = build_site(config)
    public = config.public_dir
    post_html = (public / "bilalbill-sample-guide" / "index.html").read_text(
        encoding="utf-8"
    )
    home_html = (public / "index.html").read_text(encoding="utf-8")
    sitemap = ET.fromstring((public / "sitemap.xml").read_bytes())
    ET.fromstring((public / "rss.xml").read_bytes())
    namespace = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
    locations = [
        item.text
        for item in sitemap.findall("sm:url/sm:loc", namespace)
    ]
    canonical = "https://bilalbill.com/bilalbill-sample-guide/"
    assert canonical in locations
    assert not any("unpublished-secret" in item for item in locations)
    assert f'<link rel="canonical" href="{canonical}">' in post_html
    assert '<img class="cover" src="/images/bilalbill-sample-guide.png"' in post_html
    assert (public / "images" / "bilalbill-sample-guide.png").is_file()
    assert (
        '<meta property="og:image" content="https://bilalbill.com/images/bilalbill-sample-guide.png">'
        in post_html
    )
    assert "tracker.example" not in post_html
    assert "<title>bilalbill | Practical technology guides</title>" in home_html
    assert (public / "category" / "technology" / "page" / "2" / "index.html").is_file()
    assert (public / "tag" / "guides" / "page" / "2" / "index.html").is_file()

    json_ld = re.search(
        r'<script type="application/ld\+json">(.*?)</script>', post_html, re.DOTALL
    )
    assert json_ld
    structured = json.loads(json_ld.group(1))
    assert structured["@type"] == "BlogPosting"
    assert structured["headline"] == "bilalbill sample guide"
    assert "unpublished-secret" not in home_html
    assert not (public / "unpublished-secret" / "index.html").exists()
    assert "Unpublished secret draft" in result["draft_report"].read_text(encoding="utf-8")
    assert (public / "robots.txt").is_file()
    assert (public / "rss.xml").is_file()


def test_real_editorial_article_has_publishable_length_and_four_faqs():
    project_root = Path(__file__).resolve().parents[1]
    article = frontmatter.load(
        project_root / "content" / "posts" / "android-phone-security-backup-guide.md"
    )
    text = article.content
    faq = text.split("## Frequently Asked Questions", 1)[1]
    questions = re.findall(r"^### .+\?\s*$", faq, re.MULTILINE)

    assert article["status"] == "published"
    assert "bilalbill" in article["title"].casefold()
    assert 900 <= len(re.findall(r"\b[\w'-]+\b", text)) <= 1300
    assert len(questions) == 4
    assert len(article["verify_before_publish"]) == 3


def test_github_pages_project_path_prefixes_local_links(tmp_path):
    config = config_at(tmp_path, "/ai-website-automation")
    shutil.copytree(Path(__file__).resolve().parents[1] / "templates", config.root / "templates")
    shutil.copytree(Path(__file__).resolve().parents[1] / "static", config.root / "static")
    config.posts_dir.mkdir(parents=True)
    config.pages_dir.mkdir(parents=True)
    article = frontmatter.Post(
        "A guide for this test.",
        title="Pages image test",
        slug="pages-image-test",
        meta_description="A test cover image.",
        category="Technology",
        tags=[],
        author="Bilal",
        date="2026-11-07",
        status="published",
    )
    (config.posts_dir / "pages-image-test.md").write_text(
        frontmatter.dumps(article), encoding="utf-8"
    )

    build_site(config)
    home_html = (config.public_dir / "index.html").read_text(encoding="utf-8")
    post_html = (
        config.public_dir / "pages-image-test" / "index.html"
    ).read_text(encoding="utf-8")

    assert 'href="/ai-website-automation/about/"' in home_html
    assert 'href="/ai-website-automation/static/site.css"' in home_html
    assert 'src="/ai-website-automation/images/pages-image-test.png"' in post_html
    assert (config.public_dir / "images" / "pages-image-test.png").is_file()
    assert not (config.public_dir / "CNAME").exists()
