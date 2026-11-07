"""Gemini-backed article generation with strict output validation."""

from __future__ import annotations

import json
import os
import re
import unicodedata
from datetime import date
from pathlib import Path
from typing import Any

import frontmatter
import requests

import db
from config import SiteConfig
from db import initialize, mark_keyword_used, next_keyword, save_article

GEMINI_MODEL = "gemini-2.0-flash"
GEMINI_URL = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"
WORD_RE = re.compile(r"\b[\w'-]+\b", re.UNICODE)
PLACEHOLDER_RE = re.compile(
    r"\b(?:lorem ipsum|insert (?:text|content|keyword|link)|your (?:brand|company) here|"
    r"todo|tbd|placeholder|as an ai language model)\b",
    re.IGNORECASE,
)


class QualityError(ValueError):
    """Raised when generated content does not meet the publishing quality gates."""


def slugify(value: str) -> str:
    ascii_value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", ascii_value.lower())).strip("-")


def word_count(text: str) -> int:
    without_links = re.sub(r"!\[[^\]]*]\([^)]*\)|\[[^\]]*]\([^)]*\)", " ", text)
    without_markup = re.sub(r"[#>*_`~]", " ", without_links)
    return len(WORD_RE.findall(without_markup))


def _normalized_paragraph(text: str) -> str:
    return " ".join(re.sub(r"[^\w\s]", " ", text.casefold()).split())


def _paragraphs(text: str) -> list[str]:
    return [
        _normalized_paragraph(part)
        for part in re.split(r"\n\s*\n", text)
        if _normalized_paragraph(part)
    ]


def jaccard_similarity(left: str, right: str) -> float:
    left_words = set(WORD_RE.findall(left.casefold()))
    right_words = set(WORD_RE.findall(right.casefold()))
    if not left_words or not right_words:
        return 0.0
    return len(left_words & right_words) / len(left_words | right_words)


def validate_article(
    article: dict[str, Any],
    keyword: str,
    existing_bodies: list[str] | None = None,
) -> None:
    required = {
        "title",
        "slug",
        "meta_description",
        "markdown",
        "tags",
        "category",
        "verify_before_publish",
    }
    if set(article) != required:
        raise QualityError(f"JSON keys must be exactly: {', '.join(sorted(required))}.")
    title = article["title"]
    body = article["markdown"]
    description = article["meta_description"]
    if not all(isinstance(item, str) for item in (title, body, description)):
        raise QualityError("title, markdown, and meta_description must be strings.")
    if not title.strip():
        raise QualityError("Article title is empty.")
    if normalize(keyword) not in normalize(title):
        raise QualityError("Target keyword must appear in the title.")
    if len(description.strip()) > 155 or not description.strip():
        raise QualityError("meta_description must contain 1-155 characters.")
    if not isinstance(article["slug"], str) or not re.fullmatch(
        r"[a-z0-9]+(?:-[a-z0-9]+)*", article["slug"]
    ):
        raise QualityError("slug must contain lowercase letters, digits, and hyphens.")
    if not 900 <= word_count(body) <= 1300:
        raise QualityError(f"Article body must be 900-1300 words (got {word_count(body)}).")
    if not re.search(r"^##\s+.+", body, re.MULTILINE):
        raise QualityError("Article must include at least one H2 heading.")
    if not re.search(r"^###\s+.+", body, re.MULTILINE):
        raise QualityError("Article must include at least one H3 heading.")
    faq_header = re.search(r"^##\s+(?:faq|frequently asked questions)\b.*$", body, re.I | re.M)
    if not faq_header:
        raise QualityError("Article must include a Frequently Asked Questions section.")
    faq_body = body[faq_header.end() :]
    questions = re.findall(r"^###\s+.+\?\s*$", faq_body, re.MULTILINE)
    if len(questions) != 4:
        raise QualityError("FAQ must have exactly four question headings.")
    if not isinstance(article["tags"], list) or not article["tags"] or not all(
        isinstance(tag, str) and tag.strip() for tag in article["tags"]
    ):
        raise QualityError("tags must be a non-empty JSON array.")
    if not isinstance(article["category"], str) or not article["category"].strip():
        raise QualityError("category must be a non-empty string.")
    checks = article["verify_before_publish"]
    if not isinstance(checks, list) or len(checks) != 3 or not all(
        isinstance(note, str) and note.strip() for note in checks
    ):
        raise QualityError("verify_before_publish must contain exactly three fact-check notes.")
    if PLACEHOLDER_RE.search(body):
        raise QualityError("Article contains placeholder text.")
    paragraphs = _paragraphs(body)
    if len(paragraphs) != len(set(paragraphs)):
        raise QualityError("Article contains duplicate paragraphs.")
    for existing in existing_bodies or []:
        if jaccard_similarity(body, existing) >= 0.72:
            raise QualityError("Article is too similar to existing content.")


def normalize(value: str) -> str:
    return " ".join(value.casefold().split())


def _extract_json(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", cleaned, flags=re.I)
    parsed = json.loads(cleaned)
    if not isinstance(parsed, dict):
        raise QualityError("Gemini response must be a JSON object.")
    return parsed


def _published_posts(config: SiteConfig) -> list[frontmatter.Post]:
    posts: list[frontmatter.Post] = []
    for path in sorted(config.posts_dir.glob("*.md")):
        post = frontmatter.load(path)
        if post.get("status") == "published":
            posts.append(post)
    posts.sort(key=lambda post: str(post.get("date", "")))
    return posts


def _existing_bodies(config: SiteConfig) -> list[str]:
    return [
        frontmatter.load(path).content
        for path in sorted(config.posts_dir.glob("*.md"))
    ]


def _prompt(config: SiteConfig, keyword: str) -> str:
    return f"""Create an original, useful, fact-conscious solo-blog article for {config.site_name}.
Niche: {config.niche}. Audience/language: {config.language}. Author: {config.author}.
Target keyword: {keyword}

Return ONLY one strict JSON object with exactly these keys:
title, slug, meta_description, markdown, tags, category, verify_before_publish.
Requirements:
- title naturally contains the exact target keyword; do not keyword-stuff.
- meta_description is 155 characters or fewer.
- markdown body is 900-1300 words, with useful H2 and H3 headings, practical bullets,
  and a final "## Frequently Asked Questions" section with exactly four H3 question headings
  ending in question marks and concise answers.
- Give original, specific guidance. Do not invent statistics, citations, pricing, or guarantees.
- Add exactly three concrete claims/facts the editor must verify in verify_before_publish.
- tags is an array of 2-5 short strings; category is one useful category.
- Do not include frontmatter, HTML, citations you cannot substantiate, or placeholder text.
"""


def _gemini_request(prompt: str, api_key: str, session: requests.Session) -> str:
    response = session.post(
        GEMINI_URL,
        headers={"x-goog-api-key": api_key},
        json={
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"responseMimeType": "application/json", "temperature": 0.6},
        },
        timeout=90,
    )
    response.raise_for_status()
    payload = response.json()
    try:
        return payload["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError, TypeError) as exc:
        raise ValueError("Gemini response did not contain generated text.") from exc


def _add_internal_links(body: str, config: SiteConfig) -> str:
    published = _published_posts(config)
    links = []
    for post in published[-3:]:
        slug = str(post.get("slug", ""))
        title = str(post.get("title", "")).strip()
        if slug and title:
            escaped_title = title.replace("\\", "\\\\").replace("[", "\\[").replace("]", "\\]")
            links.append(f"- [{escaped_title}](/{slug}/)")
    section = "\n\n---\n\n"
    if links:
        section += "## Further reading\n\n" + "\n".join(links) + "\n\n"
    section += "Learn more at the [bilalbill](/) homepage."
    faq = re.search(r"^##\s+(?:faq|frequently asked questions)\b", body, re.I | re.M)
    if faq:
        return body[: faq.start()].rstrip() + section + "\n\n" + body[faq.start() :]
    return body.rstrip() + section


def generate_article(
    config: SiteConfig,
    session: requests.Session | None = None,
    api_key: str | None = None,
) -> Path:
    """Generate a validated draft, retrying failed quality gates at most twice."""
    initialize(config.database_path)
    keyword_row = next_keyword(config.database_path)
    if keyword_row is None:
        raise ValueError("No unused keywords are available. Run --research first.")
    key = api_key or os.getenv("GEMINI_API_KEY")
    if not key:
        raise RuntimeError("GEMINI_API_KEY is missing; set it in .env.")
    client = session or requests.Session()
    try:
        previous_error = ""
        for attempt in range(3):
            prompt = _prompt(config, keyword_row["keyword"])
            if previous_error:
                prompt += f"\nFix this validation error from the previous draft: {previous_error}\n"
            text = _gemini_request(prompt, key, client)
            article = _extract_json(text)
            try:
                validate_article(article, keyword_row["keyword"], _existing_bodies(config))
            except QualityError as exc:
                previous_error = str(exc)
                if attempt < 2:
                    continue
                raise
            slug = slugify(article["slug"])
            if not slug:
                raise QualityError("Generated slug is empty after normalization.")
            path = config.posts_dir / f"{slug}.md"
            if path.exists():
                raise QualityError(f"Generated slug already exists: {slug}")
            content = _add_internal_links(article["markdown"], config)
            metadata = {
                "title": article["title"].strip(),
                "slug": slug,
                "keyword": keyword_row["keyword"],
                "meta_description": article["meta_description"].strip(),
                "category": article["category"].strip(),
                "tags": [str(tag).strip() for tag in article["tags"]],
                "author": config.author,
                "date": date.today().isoformat(),
                "status": "published" if config.auto_publish else "draft",
                "reviewed": False,
                "verify_before_publish": article["verify_before_publish"],
            }
            post = frontmatter.Post(content, **metadata)
            config.posts_dir.mkdir(parents=True, exist_ok=True)
            path.write_text(frontmatter.dumps(post), encoding="utf-8")
            save_article(
                config.database_path,
                slug,
                keyword_row["keyword"],
                article["title"],
                metadata["status"],
                str(path.relative_to(config.root)),
                metadata["date"] if metadata["status"] == "published" else None,
            )
            mark_keyword_used(config.database_path, int(keyword_row["id"]))
            return path
        raise QualityError("Generation failed after three attempts.")
    finally:
        if session is None:
            client.close()
