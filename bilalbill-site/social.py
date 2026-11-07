"""Optional, API-based sharing of published posts with duplicate protection."""

from __future__ import annotations

import logging
import os
from typing import Any

import frontmatter
import requests

import db
from config import SiteConfig
from generator import GEMINI_URL

LOGGER = logging.getLogger(__name__)
PLATFORM_FLAGS = {
    "telegram": "social_telegram",
    "facebook": "social_facebook",
    "pinterest": "social_pinterest",
}


def _caption(title: str, description: str, platform: str, session: requests.Session) -> str:
    key = os.getenv("GEMINI_API_KEY")
    if not key:
        raise RuntimeError("GEMINI_API_KEY is required to write social captions.")
    prompt = (
        f"Write one truthful, helpful {platform} caption (under 450 characters) "
        f"for this article. No fabricated claims or clickbait. Title: {title}. "
        f"Summary: {description}"
    )
    response = session.post(
        GEMINI_URL,
        headers={"x-goog-api-key": key},
        json={"contents": [{"parts": [{"text": prompt}]}]},
        timeout=45,
    )
    response.raise_for_status()
    try:
        caption = response.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
    except (KeyError, IndexError, TypeError) as exc:
        raise ValueError("Gemini did not return a social caption.") from exc
    if not caption:
        raise ValueError("Gemini returned an empty social caption.")
    return caption[:450]


def _share_telegram(
    session: requests.Session, caption: str, url: str, slug: str
) -> str | None:
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    channel = os.getenv("TELEGRAM_CHANNEL_ID")
    if not token or not channel:
        raise RuntimeError("TELEGRAM_BOT_TOKEN and TELEGRAM_CHANNEL_ID are required.")
    try:
        response = session.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={
                "chat_id": channel,
                "text": f"{caption}\n\n{url}",
                "link_preview_options": {"is_disabled": False},
            },
            timeout=30,
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        raise RuntimeError(
            f"Telegram API request failed with HTTP {getattr(exc.response, 'status_code', 'unknown')}."
        ) from exc
    payload: dict[str, Any] = response.json()
    if not payload.get("ok"):
        raise RuntimeError(f"Telegram API rejected the post for {slug}.")
    result = payload.get("result", {})
    return str(result.get("message_id")) if result.get("message_id") is not None else None


def _share_facebook(
    session: requests.Session, caption: str, url: str, slug: str
) -> str | None:
    page_id = os.getenv("FACEBOOK_PAGE_ID")
    token = os.getenv("FACEBOOK_PAGE_ACCESS_TOKEN")
    version = os.getenv("FACEBOOK_GRAPH_API_VERSION", "v23.0")
    if not page_id or not token:
        raise RuntimeError("FACEBOOK_PAGE_ID and FACEBOOK_PAGE_ACCESS_TOKEN are required.")
    response = session.post(
        f"https://graph.facebook.com/{version}/{page_id}/feed",
        data={"message": caption, "link": url, "access_token": token},
        timeout=30,
    )
    response.raise_for_status()
    payload: dict[str, Any] = response.json()
    if not payload.get("id"):
        raise RuntimeError(f"Facebook API did not return a post ID for {slug}.")
    return str(payload["id"])


def _share_pinterest(
    session: requests.Session, caption: str, url: str, image_url: str, slug: str
) -> str | None:
    token = os.getenv("PINTEREST_ACCESS_TOKEN")
    board_id = os.getenv("PINTEREST_BOARD_ID")
    if not token or not board_id:
        raise RuntimeError("PINTEREST_ACCESS_TOKEN and PINTEREST_BOARD_ID are required.")
    response = session.post(
        "https://api.pinterest.com/v5/pins",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "board_id": board_id,
            "title": caption[:100],
            "description": caption,
            "link": url,
            "media_source": {"source_type": "image_url", "url": image_url},
        },
        timeout=30,
    )
    response.raise_for_status()
    payload: dict[str, Any] = response.json()
    if not payload.get("id"):
        raise RuntimeError(f"Pinterest API did not return a pin ID for {slug}.")
    return str(payload["id"])


def _published_files(config: SiteConfig) -> list[tuple[Path, frontmatter.Post]]:
    found = []
    for path in sorted(config.posts_dir.glob("*.md")):
        post = frontmatter.load(path)
        if post.get("status") == "published":
            found.append((path, post))
    return found


def share_published(
    config: SiteConfig, session: requests.Session | None = None
) -> dict[str, int]:
    """Share each published slug once per enabled platform, recording failures for retry."""
    db.initialize(config.database_path)
    client = session or requests.Session()
    shared = {platform: 0 for platform in PLATFORM_FLAGS}
    platform_share = {
        "telegram": lambda caption, url, image, slug: _share_telegram(
            client, caption, url, slug
        ),
        "facebook": lambda caption, url, image, slug: _share_facebook(
            client, caption, url, slug
        ),
        "pinterest": lambda caption, url, image, slug: _share_pinterest(
            client, caption, url, image, slug
        ),
    }
    try:
        for path, post in _published_files(config):
            slug = str(post.get("slug", path.stem))
            url = f"{config.base_url}/{slug}/"
            image = f"{config.base_url}/images/{slug}.png"
            for platform, flag in PLATFORM_FLAGS.items():
                if not getattr(config, flag):
                    continue
                if not db.reserve_social_post(config.database_path, slug, platform):
                    continue
                try:
                    caption = _caption(
                        str(post["title"]),
                        str(post.get("meta_description", post["title"])),
                        platform,
                        client,
                    )
                    remote_id = platform_share[platform](caption, url, image, slug)
                except (requests.RequestException, RuntimeError, ValueError) as exc:
                    db.finish_social_post(
                        config.database_path, slug, platform, "failed", error=str(exc)[:1000]
                    )
                    LOGGER.error("Could not share %s to %s: %s", slug, platform, exc)
                    continue
                db.finish_social_post(
                    config.database_path, slug, platform, "published", remote_id=remote_id
                )
                shared[platform] += 1
    finally:
        if session is None:
            client.close()
    return shared
