"""Weekly Search Console query report and low-risk content optimization hints."""

from __future__ import annotations

import csv
from datetime import date, timedelta
from pathlib import Path
from urllib.parse import quote

import requests
from config import SiteConfig
from db import initialize, save_keyword
from google_api import access_token
from keywords import normalize_keyword, score_keyword


def fetch_search_console_report(
    config: SiteConfig, session: requests.Session | None = None
) -> list[dict[str, str | float | int]]:
    token = access_token()
    endpoint = (
        "https://www.googleapis.com/webmasters/v3/sites/"
        f"{quote(config.gsc_site_url, safe='')}/searchAnalytics/query"
    )
    client = session or requests.Session()
    try:
        yesterday = date.today() - timedelta(days=1)
        start = yesterday - timedelta(days=6)
        response = client.post(
            endpoint,
            headers={"Authorization": f"Bearer {token}"},
            json={
                "startDate": start.isoformat(),
                "endDate": yesterday.isoformat(),
                "dimensions": ["query"],
                "rowLimit": 25000,
                "dataState": "final",
            },
            timeout=45,
        )
        response.raise_for_status()
        payload = response.json()
        rows = payload.get("rows", [])
        if not isinstance(rows, list):
            raise ValueError("Search Console returned an invalid rows field.")
        return [
            {
                "query": str(row["keys"][0]),
                "clicks": int(row.get("clicks", 0)),
                "impressions": int(row.get("impressions", 0)),
                "ctr": float(row.get("ctr", 0)),
                "position": float(row.get("position", 0)),
            }
            for row in rows
            if isinstance(row, dict) and row.get("keys")
        ]
    finally:
        if session is None:
            client.close()


def save_report(
    config: SiteConfig,
    rows: list[dict[str, str | float | int]],
    output_path: Path | None = None,
) -> Path:
    destination = output_path or config.root / "reports" / "search-console-weekly.csv"
    destination.parent.mkdir(parents=True, exist_ok=True)
    optimize: list[dict[str, str | float | int]] = []
    with destination.open("w", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(
            file, fieldnames=["query", "clicks", "impressions", "ctr", "position", "action"]
        )
        writer.writeheader()
        for row in sorted(rows, key=lambda item: (-int(item["impressions"]), float(item["position"]))):
            action = "optimize" if 8 <= float(row["position"]) <= 20 else ""
            writer.writerow({**row, "action": action})
            if action and row["query"].strip():
                optimize.append(row)
    initialize(config.database_path)
    for row in optimize:
        query = str(row["query"]).strip()
        save_keyword(
            config.database_path,
            query,
            normalize_keyword(query),
            "search-console-optimize",
            score_keyword(query),
            priority=100,
        )
    return destination


def run_weekly_report(
    config: SiteConfig, session: requests.Session | None = None
) -> tuple[Path, list[dict[str, str | float | int]]]:
    rows = fetch_search_console_report(config, session)
    destination = save_report(config, rows)
    return destination, rows


def report_summary(destination: Path, rows: list[dict[str, str | float | int]]) -> str:
    top = sorted(rows, key=lambda row: int(row["impressions"]), reverse=True)[:5]
    optimize = [
        row for row in rows if 8 <= float(row["position"]) <= 20
    ]
    top_lines = ", ".join(
        f"{row['query']} ({row['clicks']} clicks, {row['impressions']} impressions)"
        for row in top
    )
    optimize_lines = ", ".join(
        f"{row['query']} (position {float(row['position']):.1f})"
        for row in sorted(optimize, key=lambda row: float(row["position"]))[:5]
    )
    return (
        f"CSV: {destination}; queries: {len(rows)}; optimize candidates: {len(optimize)}. "
        f"Top queries: {top_lines or 'none'}. "
        f"Position 8-20: {optimize_lines or 'none'}."
    )
