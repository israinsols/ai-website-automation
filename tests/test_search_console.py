import json
import os
import sqlite3
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

import app
import automation
import search_console


class SearchConsoleTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database_path = app.DATABASE_PATH
        self.articles_path = app.ARTICLES_PATH
        app.DATABASE_PATH = Path(self.temp_dir.name) / "site.sqlite3"
        app.ARTICLES_PATH = Path(self.temp_dir.name) / "legacy.json"
        app.initialize_database()
        self.client = app.app.test_client()
        with self.client.session_transaction() as state:
            state["admin_authenticated"] = True
            state["admin_username"] = "site-editor"
            state["_csrf_token"] = "search-console-test-token"

    def tearDown(self):
        app.DATABASE_PATH = self.database_path
        app.ARTICLES_PATH = self.articles_path
        self.temp_dir.cleanup()

    def test_reporting_period_uses_latest_complete_days(self):
        self.assertEqual(
            search_console.reporting_period(date(2026, 10, 14)),
            ("2026-09-14", "2026-10-11"),
        )

    def test_sync_stores_metrics_and_latest_sync_metadata(self):
        credentials_file = Path(self.temp_dir.name) / "service-account.json"
        credentials_file.write_text("{}", encoding="utf-8")
        rows = [
            {
                "keys": ["small room ideas", "https://example.test/blog/small-room-ideas"],
                "clicks": 1,
                "impressions": 100,
                "ctr": 0.01,
                "position": 8.4,
            }
        ]
        with patch.object(search_console, "fetch_search_console_rows", return_value=(rows, False)):
            result = search_console.sync_search_console(
                app.DATABASE_PATH,
                "https://example.test/",
                credentials_file,
                today=date(2026, 10, 14),
            )
        self.assertEqual(result["status"], "synced")
        self.assertEqual(result["rows"], 1)
        self.assertEqual(result["start_date"], "2026-09-14")
        self.assertEqual(result["end_date"], "2026-10-11")
        connection = sqlite3.connect(app.DATABASE_PATH)
        try:
            stored = connection.execute(
                "SELECT query, clicks, impressions FROM search_console_rows"
            ).fetchone()
            metadata = dict(connection.execute(
                "SELECT key, value FROM app_meta WHERE key LIKE 'search_console_%'"
            ).fetchall())
        finally:
            connection.close()
        self.assertEqual(stored, ("small room ideas", 1.0, 100.0))
        self.assertEqual(metadata["search_console_property"], "https://example.test/")
        self.assertEqual(metadata["search_console_truncated"], "0")

    def test_api_fetch_uses_service_account_and_pages_through_search_data(self):
        from google.auth.transport import requests as google_requests
        from google.oauth2 import service_account

        response = unittest.mock.Mock()
        response.json.return_value = {"rows": [{
            "keys": ["storage ideas", "https://example.test/blog/storage"],
            "clicks": 2,
            "impressions": 50,
            "ctr": 0.04,
            "position": 6,
        }]}
        session = unittest.mock.Mock()
        session.post.return_value = response
        with patch.object(service_account.Credentials, "from_service_account_file", return_value=object()) as load_credentials, \
                patch.object(google_requests, "AuthorizedSession", return_value=session):
            rows, truncated = search_console.fetch_search_console_rows(
                "sc-domain:example.test",
                Path(self.temp_dir.name) / "service-account.json",
                "2026-09-14",
                "2026-10-11",
            )
        self.assertEqual(len(rows), 1)
        self.assertFalse(truncated)
        load_credentials.assert_called_once()
        session.post.assert_called_once()
        self.assertIn("sc-domain%3Aexample.test", session.post.call_args.args[0])
        self.assertEqual(session.post.call_args.kwargs["json"]["dimensions"], ["query", "page"])
        session.close.assert_called_once()

    def test_api_fetch_accepts_service_account_json_for_railway_secret(self):
        from google.auth.transport import requests as google_requests
        from google.oauth2 import service_account

        credentials_info = {
            "type": "service_account",
            "client_email": "search-console@example.test",
            "private_key": "test-private-key",
        }
        response = unittest.mock.Mock()
        response.json.return_value = {"rows": []}
        session = unittest.mock.Mock()
        session.post.return_value = response
        with patch.object(
            service_account.Credentials, "from_service_account_info", return_value=object()
        ) as load_credentials, patch.object(
            google_requests, "AuthorizedSession", return_value=session
        ):
            rows, truncated = search_console.fetch_search_console_rows(
                "https://example.test/",
                None,
                "2026-09-14",
                "2026-10-11",
                credentials_info=credentials_info,
            )
        self.assertEqual(rows, [])
        self.assertFalse(truncated)
        load_credentials.assert_called_once_with(
            credentials_info,
            scopes=[search_console.SEARCH_CONSOLE_SCOPE],
        )
        session.close.assert_called_once()

    def test_report_requires_public_https_site_and_private_service_account_file(self):
        with patch.dict(os.environ, {
            "PUBLIC_SITE_URL": "http://127.0.0.1:5000",
            "GOOGLE_SEARCH_CONSOLE_PROPERTY": "sc-domain:example.test",
            "GOOGLE_SEARCH_CONSOLE_CREDENTIALS_FILE": "missing.json",
        }, clear=False):
            response = self.client.get("/reports/search-console")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Set PUBLIC_SITE_URL", response.data)
        self.assertIn(b"0", response.data)
        self.assertNotIn(b"ORGANIC CLICKS", response.data)

    def test_report_summarizes_metrics_and_links_opportunities_to_published_article(self):
        article = {
            "id": "opportunity-article",
            "slug": "small-room-ideas",
            "status": "Published",
            "niche": "home-decor",
            "article_title": "Small room ideas",
            "article_html": "<p>Useful ideas for a small room.</p>",
        }
        app.save_article(article)
        connection = sqlite3.connect(app.DATABASE_PATH)
        try:
            connection.execute(
                "INSERT INTO search_console_rows "
                "(query, page, clicks, impressions, ctr, position) VALUES (?, ?, ?, ?, ?, ?)",
                ("small room ideas", "https://example.test/blog/small-room-ideas", 1, 100, 0.01, 7.5),
            )
            connection.executemany(
                "INSERT INTO app_meta (key, value) VALUES (?, ?)",
                (
                    ("search_console_synced_at", "2026-10-14T10:00:00+00:00"),
                    ("search_console_start_date", "2026-09-14"),
                    ("search_console_end_date", "2026-10-11"),
                ),
            )
            connection.commit()
        finally:
            connection.close()
        credentials_file = Path(self.temp_dir.name) / "service-account.json"
        credentials_file.write_text("{}", encoding="utf-8")
        with patch.dict(os.environ, {
            "PUBLIC_SITE_URL": "https://example.test",
            "GOOGLE_SEARCH_CONSOLE_PROPERTY": "sc-domain:example.test",
            "GOOGLE_SEARCH_CONSOLE_CREDENTIALS_FILE": str(credentials_file),
        }, clear=False):
            response = self.client.get("/reports/search-console")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"ORGANIC CLICKS", response.data)
        self.assertIn(b"Click-through opportunity", response.data)
        self.assertIn(b"small room ideas", response.data)
        self.assertIn(b"Review article SEO", response.data)
        self.assertIn(b"3", response.data)

    def test_manual_sync_reports_an_unconfigured_site_without_calling_google(self):
        with patch.dict(os.environ, {
            "PUBLIC_SITE_URL": "http://127.0.0.1:5000",
            "GOOGLE_SEARCH_CONSOLE_PROPERTY": "",
            "GOOGLE_SEARCH_CONSOLE_CREDENTIALS_FILE": "",
        }, clear=False), patch.object(search_console, "sync_search_console") as sync:
            response = self.client.post("/reports/search-console/sync", data={
                "_csrf_token": "search-console-test-token",
            })
        self.assertEqual(response.status_code, 302)
        sync.assert_not_called()
        self.assertEqual(response.location, "/reports/search-console")

    def test_search_console_report_accepts_railway_json_secret(self):
        credentials_info = {
            "type": "service_account",
            "client_email": "search-console@example.test",
            "private_key": "test-private-key",
        }
        with patch.dict(os.environ, {
            "PUBLIC_SITE_URL": "https://example.test",
            "GOOGLE_SEARCH_CONSOLE_PROPERTY": "https://example.test/",
            "GOOGLE_SEARCH_CONSOLE_CREDENTIALS_FILE": "",
            "GOOGLE_SEARCH_CONSOLE_CREDENTIALS_JSON": json.dumps(credentials_info),
        }, clear=False):
            response = self.client.get("/reports/search-console")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"https://example.test/", response.data)
        self.assertIn(b"Sync Search Console now", response.data)

    def test_daily_automation_syncs_search_console_before_content_run(self):
        with patch.object(automation, "sync_search_console_data", return_value={"status": "synced"}) as sync, \
                patch.object(automation, "run_due_scheduled_publications", return_value={"failed": 0}) as scheduled, \
                patch.object(automation, "run_autopilot_once", return_value={"status": "disabled"}) as autopilot, \
                patch("sys.argv", ["automation.py"]), patch("builtins.print"):
            result = automation.main()
        self.assertEqual(result, 0)
        sync.assert_called_once()
        scheduled.assert_called_once()
        autopilot.assert_called_once()

    def test_five_minute_scheduled_publication_mode_does_not_sync_search_console(self):
        with patch.object(automation, "sync_search_console_data") as sync, \
                patch.object(automation, "run_due_scheduled_publications", return_value={"failed": 0}) as scheduled, \
                patch("sys.argv", ["automation.py", "--scheduled-publications"]), \
                patch("builtins.print"):
            result = automation.main()
        self.assertEqual(result, 0)
        sync.assert_not_called()
        scheduled.assert_called_once()


if __name__ == "__main__":
    unittest.main()
