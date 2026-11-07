"""SEO metadata, canonical URLs, sitemaps, robots, and RSS generation."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import format_datetime
from typing import Any
from urllib.parse import urljoin

from config import SiteConfig

ET.register_namespace("", "http://www.sitemaps.org/schemas/sitemap/0.9")
ET.register_namespace("atom", "http://www.w3.org/2005/Atom")


def canonical_url(config: SiteConfig, path: str) -> str:
    return urljoin(config.base_url + "/", path.lstrip("/"))


def sitemap_xml(urls: list[dict[str, str]]) -> bytes:
    namespace = "http://www.sitemaps.org/schemas/sitemap/0.9"
    root = ET.Element(f"{{{namespace}}}urlset")
    for item in urls:
        entry = ET.SubElement(root, f"{{{namespace}}}url")
        ET.SubElement(entry, f"{{{namespace}}}loc").text = item["loc"]
        if item.get("lastmod"):
            ET.SubElement(entry, f"{{{namespace}}}lastmod").text = item["lastmod"]
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def robots_txt(config: SiteConfig) -> str:
    return f"User-agent: *\nAllow: /\nSitemap: {config.base_url}/sitemap.xml\n"


def rss_xml(config: SiteConfig, posts: list[dict[str, Any]]) -> bytes:
    root = ET.Element("rss", {"version": "2.0"})
    channel = ET.SubElement(root, "channel")
    ET.SubElement(channel, "title").text = config.site_name
    ET.SubElement(channel, "link").text = config.base_url + "/"
    ET.SubElement(channel, "description").text = f"{config.niche} articles from {config.site_name}"
    ET.SubElement(
        channel,
        "{http://www.w3.org/2005/Atom}link",
        {"href": config.base_url + "/rss.xml", "rel": "self", "type": "application/rss+xml"},
    )
    for post in posts[:50]:
        item = ET.SubElement(channel, "item")
        ET.SubElement(item, "title").text = post["title"]
        ET.SubElement(item, "link").text = post["canonical"]
        ET.SubElement(item, "guid", {"isPermaLink": "true"}).text = post["canonical"]
        ET.SubElement(item, "description").text = post["meta_description"]
        published = post.get("date")
        if published:
            try:
                date = datetime.fromisoformat(str(published)).replace(tzinfo=timezone.utc)
                ET.SubElement(item, "pubDate").text = format_datetime(date)
            except ValueError:
                pass
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def article_json_ld(config: SiteConfig, post: dict[str, Any]) -> dict[str, Any]:
    return {
        "@context": "https://schema.org",
        "@type": "BlogPosting",
        "headline": post["title"],
        "description": post["meta_description"],
        "datePublished": post["date"],
        "author": {"@type": "Person", "name": post["author"]},
        "publisher": {"@type": "Organization", "name": config.site_name},
        "mainEntityOfPage": post["canonical"],
        "image": post["social_image"],
        "keywords": post["keyword"],
    }


def website_json_ld(config: SiteConfig) -> dict[str, Any]:
    return {
        "@context": "https://schema.org",
        "@type": "WebSite",
        "name": config.site_name,
        "url": config.base_url + "/",
    }
