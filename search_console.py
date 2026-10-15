import json
import math
from datetime import date, timedelta
from pathlib import Path
from urllib.parse import quote

import requests


SEARCH_CONSOLE_API = "https://www.googleapis.com/webmasters/v3/sites"
SEARCH_CONSOLE_SCOPE = "https://www.googleapis.com/auth/webmasters.readonly"
ROW_LIMIT = 25_000
MAX_ROWS = 100_000


def reporting_period(today=None, days=28):
    today = today or date.today()
    end_date = today - timedelta(days=3)
    start_date = end_date - timedelta(days=days - 1)
    return start_date.isoformat(), end_date.isoformat()


def fetch_search_console_rows(property_url, credentials_path, start_date, end_date):
    try:
        from google.auth.transport.requests import AuthorizedSession
        from google.auth import exceptions as google_auth_exceptions
        from google.oauth2 import service_account
    except ImportError as exc:
        raise RuntimeError(
            "Search Console sync needs google-auth. Install the project requirements."
        ) from exc

    try:
        credentials = service_account.Credentials.from_service_account_file(
            str(credentials_path),
            scopes=[SEARCH_CONSOLE_SCOPE],
        )
    except (OSError, ValueError, google_auth_exceptions.GoogleAuthError) as exc:
        raise RuntimeError(f"Could not load the Search Console service-account credentials: {exc}") from exc
    session = AuthorizedSession(credentials)
    endpoint = f"{SEARCH_CONSOLE_API}/{quote(property_url, safe='')}/searchAnalytics/query"
    rows = []
    try:
        for start_row in range(0, MAX_ROWS, ROW_LIMIT):
            response = session.post(
                endpoint,
                json={
                    "startDate": start_date,
                    "endDate": end_date,
                    "dimensions": ["query", "page"],
                    "type": "web",
                    "dataState": "final",
                    "rowLimit": ROW_LIMIT,
                    "startRow": start_row,
                },
                timeout=30,
            )
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict):
                raise RuntimeError("Google Search Console returned an invalid response.")
            page_rows = payload.get("rows", [])
            if not isinstance(page_rows, list):
                raise RuntimeError("Google Search Console returned an invalid rows value.")
            rows.extend(page_rows)
            if len(page_rows) < ROW_LIMIT:
                return rows, False
        return rows, True
    except requests.RequestException as exc:
        response = getattr(exc, "response", None)
        detail = response.text[:1000] if response is not None else str(exc)
        raise RuntimeError(f"Google Search Console request failed: {detail}") from exc
    except (ValueError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Could not parse the Search Console response: {exc}") from exc
    finally:
        session.close()


def store_search_console_rows(database_path, rows, property_url, start_date, end_date, truncated):
    import sqlite3
    from datetime import datetime, timezone

    synced_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    normalized_rows = []
    for row in rows:
        keys = row.get("keys")
        if not isinstance(keys, list) or len(keys) != 2:
            raise RuntimeError("Google Search Console returned a row without query and page keys.")
        try:
            metrics = tuple(float(row.get(name, 0)) for name in ("clicks", "impressions", "ctr", "position"))
            if (not all(math.isfinite(value) for value in metrics)
                    or metrics[0] < 0 or metrics[1] < 0
                    or not 0 <= metrics[2] <= 1 or metrics[3] < 0):
                raise ValueError("Search metrics are outside their valid ranges.")
            normalized_rows.append((
                str(keys[0])[:500],
                str(keys[1])[:2048],
                *metrics,
            ))
        except (TypeError, ValueError) as exc:
            raise RuntimeError("Google Search Console returned invalid search metrics.") from exc

    connection = sqlite3.connect(database_path, timeout=10)
    try:
        with connection:
            connection.execute("DELETE FROM search_console_rows")
            connection.executemany(
                "INSERT INTO search_console_rows "
                "(query, page, clicks, impressions, ctr, position) VALUES (?, ?, ?, ?, ?, ?)",
                normalized_rows,
            )
            connection.executemany(
                "INSERT INTO app_meta (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (
                    ("search_console_property", property_url),
                    ("search_console_start_date", start_date),
                    ("search_console_end_date", end_date),
                    ("search_console_synced_at", synced_at),
                    ("search_console_truncated", "1" if truncated else "0"),
                ),
            )
    finally:
        connection.close()
    return {
        "status": "synced",
        "rows": len(normalized_rows),
        "start_date": start_date,
        "end_date": end_date,
        "truncated": truncated,
        "synced_at": synced_at,
    }


def sync_search_console(database_path, property_url, credentials_path, today=None):
    if not property_url or not credentials_path:
        return {"status": "not-configured"}
    credentials_file = Path(credentials_path)
    if not credentials_file.is_file():
        raise RuntimeError(f"Search Console service-account file not found: {credentials_file}")
    start_date, end_date = reporting_period(today=today)
    rows, truncated = fetch_search_console_rows(
        property_url, credentials_file, start_date, end_date
    )
    return store_search_console_rows(
        database_path, rows, property_url, start_date, end_date, truncated
    )
