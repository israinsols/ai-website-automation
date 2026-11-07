"""After-deployment IndexNow notifications and Search Console sitemap submission."""

from __future__ import annotations

import logging
import os
import re
import xml.etree.ElementTree as ET
from urllib.parse import quote

import requests

from config import SiteConfig
from google_api import access_token

LOGGER = logging.getLogger(__name__)
INDEXNOW_ENDPOINT = "https://api.indexnow.org/indexnow"


def _published_urls(config: SiteConfig, session: requests.Session) -> list[str]:
    sitemap_url = f"{config.base_url}/sitemap.xml"
    response = session.get(sitemap_url, timeout=20)
    response.raise_for_status()
    root = ET.fromstring(response.content)
    namespace = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
    return [
        item.text.strip()
        for item in root.findall("sm:url/sm:loc", namespace)
        if item.text and item.text.strip()
    ]


def notify_indexnow(
    config: SiteConfig, session: requests.Session | None = None
) -> int:
    key = os.getenv("INDEXNOW_KEY", "").strip()
    if not key:
        raise RuntimeError("INDEXNOW_KEY is missing; configure it in .env or GitHub Actions.")
    if not re.fullmatch(r"[A-Za-z0-9-]{8,128}", key):
        raise ValueError("INDEXNOW_KEY must be 8-128 letters, digits, or hyphens.")
    client = session or requests.Session()
    try:
        urls = _published_urls(config, client)
        if not urls:
            LOGGER.info("Sitemap contains no published URLs; IndexNow notification skipped.")
            return 0
        response = client.post(
            INDEXNOW_ENDPOINT,
            json={
                "host": config.domain,
                "key": key,
                "keyLocation": f"{config.base_url}/{key}.txt",
                "urlList": urls[:10000],
            },
            headers={"Content-Type": "application/json; charset=utf-8"},
            timeout=30,
        )
        if response.status_code not in {200, 202}:
            response.raise_for_status()
            raise RuntimeError(f"IndexNow rejected notification: HTTP {response.status_code}")
        return min(len(urls), 10000)
    finally:
        if session is None:
            client.close()


def submit_sitemap_to_search_console(
    config: SiteConfig, session: requests.Session | None = None
) -> bool:
    if not os.getenv("GSC_SERVICE_ACCOUNT_JSON"):
        LOGGER.warning(
            "Search Console sitemap submission skipped: GSC_SERVICE_ACCOUNT_JSON is not set. "
            "Submit %s/sitemap.xml manually in Search Console.",
            config.base_url,
        )
        return False
    token = access_token()
    sitemap_url = f"{config.base_url}/sitemap.xml"
    endpoint = (
        "https://www.googleapis.com/webmasters/v3/sites/"
        f"{quote(config.gsc_site_url, safe='')}/sitemaps/{quote(sitemap_url, safe='')}"
    )
    client = session or requests.Session()
    try:
        response = client.put(
            endpoint,
            headers={"Authorization": f"Bearer {token}"},
            timeout=30,
        )
        response.raise_for_status()
        return True
    finally:
        if session is None:
            client.close()


def run_indexing(config: SiteConfig, session: requests.Session | None = None) -> int:
    """Notify IndexNow and submit the live sitemap to Search Console when configured."""
    sent = notify_indexnow(config, session=session)
    submit_sitemap_to_search_console(config, session=session)
    return sent
