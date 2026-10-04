import json
import os
import sqlite3
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import app


class AutopilotTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database_path = app.DATABASE_PATH
        self.articles_path = app.ARTICLES_PATH
        app.DATABASE_PATH = Path(self.temp_dir.name) / "test.sqlite3"
        app.ARTICLES_PATH = Path(self.temp_dir.name) / "legacy.json"
        app.initialize_database()

    def tearDown(self):
        app.DATABASE_PATH = self.database_path
        app.ARTICLES_PATH = self.articles_path
        self.temp_dir.cleanup()

    def post_client_submission(self, client, data, elapsed_seconds=5):
        client.get("/submit")
        with client.session_transaction() as state:
            data["_csrf_token"] = state["_csrf_token"]
            state["submission_started_at"] = datetime.now().timestamp() - elapsed_seconds
        return client.post("/submit", data=data)

    def test_autopilot_requires_acknowledgement(self):
        client = app.app.test_client()
        with client.session_transaction() as state:
            state["admin_authenticated"] = True
            state["_csrf_token"] = "test-token"
        response = client.post(
            "/autopilot",
            data={"_csrf_token": "test-token", "enabled": "on", "schedule_time": "09:00"},
        )
        self.assertEqual(response.status_code, 302)
        self.assertFalse(app.load_autopilot_config()["enabled"])

    def test_scheduled_run_is_a_noop_when_autopilot_is_off(self):
        result = app.run_autopilot_once()
        self.assertEqual(result, {"status": "disabled"})
        self.assertEqual(app.load_articles(), [])

    def test_generated_keyword_ideas_are_isolated_by_selected_niche(self):
        client = app.app.test_client()
        with client.session_transaction() as state:
            state["niche"] = "tech"
            state["admin_authenticated"] = True
            state["keyword_ideas_by_niche"] = {
                "tech": ["remote work apps"],
                "home-decor": ["small living room decor ideas"],
            }
        tech_page = client.get("/keywords")
        self.assertIn(b"remote work apps", tech_page.data)
        self.assertNotIn(b"small living room decor ideas", tech_page.data)
        with client.session_transaction() as state:
            state["niche"] = "home-decor"
        home_page = client.get("/keywords")
        self.assertIn(b"small living room decor ideas", home_page.data)
        self.assertNotIn(b"remote work apps", home_page.data)

    def test_manual_publish_records_editorial_review(self):
        draft = {
            "id": "review-test", "article_title": "Storage for compact entryways",
            "keyword": "entryway storage ideas", "niche": "home-decor",
            "status": "Draft", "created_at": "2026-09-29T09:00:00+00:00",
            "article_html": "<p>Practical storage ideas.</p>",
        }
        app.save_article(draft)
        client = app.app.test_client()
        with client.session_transaction() as state:
            state["admin_authenticated"] = True
            state["admin_username"] = "site-editor"
            state["_csrf_token"] = "test-token"
        response = client.post("/articles/review-test/publish", data={"_csrf_token": "test-token"})
        self.assertEqual(response.status_code, 302)
        published = app.load_articles()[0]
        self.assertEqual(published["editorial_reviewed_by"], "site-editor")
        self.assertEqual(published["editorial_reviewed_at"], published["published_at"])

    def test_independent_article_saves_preserve_writes_from_stale_snapshots(self):
        original = {
            "id": "original", "article_title": "Existing article", "status": "Draft",
            "created_at": "2026-09-29T08:00:00+00:00",
        }
        app.save_article(original)
        first_snapshot = app.load_articles()
        second_snapshot = app.load_articles()
        first_snapshot.append({
            "id": "first-write", "article_title": "First new article", "status": "Draft",
            "created_at": "2026-09-29T09:00:00+00:00",
        })
        second_snapshot.append({
            "id": "second-write", "article_title": "Second new article", "status": "Draft",
            "created_at": "2026-09-29T10:00:00+00:00",
        })
        app.save_article(first_snapshot[-1])
        app.save_article(second_snapshot[-1])
        self.assertEqual(
            {article["id"] for article in app.load_articles()},
            {"original", "first-write", "second-write"},
        )

    def test_autopilot_settings_require_keys_and_explicit_acknowledgement(self):
        client = app.app.test_client()
        with client.session_transaction() as state:
            state["admin_authenticated"] = True
            state["_csrf_token"] = "test-token"
        with patch.dict(os.environ, {"GROQ_API_KEY": ""}):
            response = client.post("/autopilot", data={
                "_csrf_token": "test-token",
                "enabled": "on",
                "schedule_time": "09:00",
                "ack_auto_publish": "on",
            })
        self.assertEqual(response.status_code, 302)
        self.assertFalse(app.load_autopilot_config()["enabled"])

    def test_autopilot_can_only_be_enabled_with_keys_and_acknowledgement(self):
        client = app.app.test_client()
        with client.session_transaction() as state:
            state["admin_authenticated"] = True
            state["_csrf_token"] = "test-token"
        with patch.dict(os.environ, {"GROQ_API_KEY": "test-groq"}):
            response = client.post("/autopilot", data={
                "_csrf_token": "test-token",
                "enabled": "on",
                "schedule_time": "09:00",
                "ack_auto_publish": "on",
            })
        self.assertEqual(response.status_code, 302)
        self.assertTrue(app.load_autopilot_config()["enabled"])
        self.assertEqual(app.load_autopilot_config()["schedule_time"], "09:00")
        self.assertTrue(app.load_autopilot_config()["ack_auto_publish"])

    def test_keyword_discovery_returns_new_phrase_in_known_cluster(self):
        search_response = type("Response", (), {
            "raise_for_status": lambda self: None,
            "json": lambda self: {"results": [
                {
                    "title": f"Current source {index}",
                    "url": f"https://example.com/source-{index}",
                    "content": "Recent practical home-decor questions.",
                }
                for index in range(4)
            ]},
        })()
        completion = type("Completion", (), {
            "choices": [type("Choice", (), {
                "message": type("Message", (), {
                    "content": json.dumps({
                        "keyword": "small apartment entryway storage ideas",
                        "search_intent": "informational",
                        "topic_cluster": "Small-space living",
                        "rationale": "Related to current compact-home questions.",
                    })
                })(),
            })()],
        })()
        groq_messages = []

        def create_completion(self, **kwargs):
            groq_messages.extend(kwargs["messages"])
            return completion

        client = type("Client", (), {
            "chat": type("Chat", (), {
                "completions": type("Completions", (), {"create": create_completion})(),
            })(),
        })()
        search_env = {"GROQ_API_KEY": "test-groq", "TAVILY_API_KEY": "test-tavily", "RSS_FEED_URLS": ""}
        with patch.dict(os.environ, search_env), \
                patch.object(app.requests, "post", return_value=search_response) as tavily_search, \
                patch.object(app, "Groq", return_value=client):
            idea = app.discover_researched_keyword("home-decor", app.seed_keywords("home-decor"))
            self.assertEqual(idea["topic_cluster"], "Small-space living")
            self.assertNotIn(idea["keyword"].casefold(), {word.casefold() for word in app.seed_keywords("home-decor")})
            tavily_search.assert_called_once()
            self.assertEqual(tavily_search.call_args.kwargs["json"]["api_key"], "test-tavily")
            self.assertIn("untrusted reference data", groq_messages[0]["content"])
            self.assertIn("Current source 0", groq_messages[-1]["content"])

        with patch.dict(os.environ, search_env), \
                patch.object(app.requests, "post", return_value=search_response), \
                patch.object(app, "Groq", return_value=client):
            with self.assertRaisesRegex(RuntimeError, "repeated"):
                app.discover_researched_keyword("home-decor", ["small apartment entryway storage ideas"])

    def test_local_rss_fallback_works_without_tavily(self):
        feed_xml = b"""<?xml version=\"1.0\" encoding=\"UTF-8\"?>
        <rss version=\"2.0\">
          <channel>
            <title>Home Decor Journal</title>
            <item>
              <title>Storage ideas for compact entryways</title>
              <link>https://example.com/entryway-storage</link>
              <description>Practical advice for solving entryway clutter.</description>
            </item>
          </channel>
        </rss>
        """
        fake_response = type("Response", (), {
            "raise_for_status": lambda self: None,
            "content": feed_xml,
        })()
        with patch.dict(os.environ, {
            "GROQ_API_KEY": "test-groq",
            "TAVILY_API_KEY": "",
            "RSS_FEED_URLS": "https://example.com/feed.xml",
        }), \
                patch.object(app.requests, "get", return_value=fake_response):
            idea = app.discover_researched_keyword("home-decor", app.seed_keywords("home-decor"))
            self.assertIn("storage", idea["keyword"].casefold())
            self.assertNotIn(idea["keyword"].casefold(), {word.casefold() for word in app.seed_keywords("home-decor")})

    def test_rss_ingestion_rejects_non_http_source_urls(self):
        feed_xml = b"""<rss version="2.0"><channel>
          <item><title>Unsafe</title><link>javascript:alert(1)</link><description>Unsafe source</description></item>
          <item><title>Safe</title><link>https://example.com/source</link><description>Safe source</description></item>
        </channel></rss>"""
        response = type("Response", (), {
            "raise_for_status": lambda self: None,
            "content": feed_xml,
        })()
        with patch.dict(os.environ, {"RSS_FEED_URLS": "https://example.com/feed.xml"}), \
                patch.object(app.requests, "get", return_value=response):
            sources = app.fetch_rss_sources()
        self.assertEqual([source["url"] for source in sources], ["https://example.com/source"])

    def test_public_article_does_not_render_unsafe_saved_source_urls(self):
        article = {
            "id": "source-url-test", "slug": "source-url-test", "status": "Published",
            "created_at": "2026-09-29T09:00:00+00:00",
            "article_title": "A safe article", "meta_title": "A safe article",
            "meta_description": "A safe article description.", "article_html": "<p>Article body.</p>",
            "keyword": "safe article", "niche": "home-decor", "sources": [
                {"title": "Unsafe source", "url": "javascript:alert(1)"},
                {"title": "Safe source", "url": "https://example.com/source"},
            ],
        }
        with patch.object(app, "load_articles", return_value=[article]):
            response = app.app.test_client().get("/blog/source-url-test")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'href="https://example.com/source"', response.data)
        self.assertNotIn(b"javascript:alert(1)", response.data)

    def test_public_submission_requires_csrf_and_reprint_permission(self):
        client = app.app.test_client()
        self.assertEqual(client.post("/submit", data={}).status_code, 400)
        response = self.post_client_submission(client, {
            "title": "Licensed client article",
            "contributor_email": "writer@example.com",
            "content": "<p>Article text for editorial review.</p>",
        })
        self.assertEqual(response.status_code, 302)
        self.assertEqual(app.load_articles(), [])

    def test_honeypot_and_submission_email_limit_block_spam(self):
        client = app.app.test_client()
        response = self.post_client_submission(client, {"company_website": "filled-by-bot"})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(app.load_articles(), [])
        self.assertTrue(app.reserve_submission_slot("repeat@example.com"))
        self.assertTrue(app.reserve_submission_slot("repeat@example.com"))
        self.assertTrue(app.reserve_submission_slot("repeat@example.com"))
        self.assertFalse(app.reserve_submission_slot("repeat@example.com"))
        connection = sqlite3.connect(app.DATABASE_PATH)
        try:
            rows = connection.execute("SELECT email_hash FROM submission_rate_limits").fetchall()
        finally:
            connection.close()
        self.assertTrue(rows)
        self.assertNotIn("repeat@example.com", rows[0][0])

    def test_client_submission_records_reprint_permission_and_original_canonical(self):
        client = app.app.test_client()
        response = self.post_client_submission(client, {
            "title": "Syndicated storage guide",
            "contributor_email": "owner@example.com",
            "content": "<p>Useful original storage advice.</p>",
            "original_url": "https://client.example.com/storage-guide",
            "canonical_to_original": "on",
            "rights_confirmed": "on",
        })
        self.assertEqual(response.status_code, 302)
        article = app.load_articles()[0]
        self.assertEqual(article["status"], "Pending Review")
        self.assertEqual(article["contributor_email"], "owner@example.com")
        self.assertEqual(article["reprint_terms_version"], app.REPRINT_TERMS_VERSION)
        self.assertTrue(article["reprint_permission_at"])
        self.assertTrue(article["canonical_to_original"])

        with client.session_transaction() as state:
            state["admin_authenticated"] = True
            state["admin_username"] = "site-editor"
        publish_response = client.post(
            f"/articles/{article['id']}/publish",
            data={"_csrf_token": state["_csrf_token"]},
        )
        self.assertEqual(publish_response.status_code, 302)
        published = app.load_articles()[0]
        public_page = client.get(f"/blog/{published['slug']}")
        self.assertIn(b'<link rel="canonical" href="https://client.example.com/storage-guide">', public_page.data)
        self.assertIn(b"Originally published at", public_page.data)
        self.assertNotIn(published["slug"].encode(), app.app.test_client().get("/sitemap.xml").data)
        self.assertIn(b"https://client.example.com/storage-guide", client.get("/feed.xml").data)

    def test_admin_can_decline_external_canonical_request(self):
        article = {
            "id": "canonical-review", "article_title": "Review canonical",
            "meta_title": "Review canonical", "meta_description": "Canonical review article.",
            "keyword": "canonical review", "article_html": "<p>Article body.</p>",
            "niche": "home-decor", "created_at": "2026-09-29T09:00:00+00:00",
            "status": "Pending Review", "original_url": "https://client.example.com/original",
            "canonical_to_original": True,
        }
        app.save_article(article)
        client = app.app.test_client()
        with client.session_transaction() as state:
            state["admin_authenticated"] = True
            state["_csrf_token"] = "review-token"
        response = client.post("/articles/canonical-review", data={
            "_csrf_token": "review-token",
            "article_title": article["article_title"],
            "meta_title": article["meta_title"],
            "meta_description": article["meta_description"],
            "keyword": article["keyword"],
            "original_url": article["original_url"],
        })
        self.assertEqual(response.status_code, 302)
        updated = app.load_articles()[0]
        self.assertFalse(updated["canonical_to_original"])
        self.assertEqual(updated["original_url"], article["original_url"])

    def test_submission_minimum_completion_time_is_enforced(self):
        client = app.app.test_client()
        response = self.post_client_submission(client, {
            "title": "Fast bot submission",
            "contributor_email": "fast@example.com",
            "content": "<p>Readable article content.</p>",
            "rights_confirmed": "on",
        }, elapsed_seconds=0)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(app.load_articles(), [])

    def test_traffic_report_counts_production_human_views_but_not_bots(self):
        with patch.object(app, "APP_ENV", "production"):
            client = app.app.test_client()
            self.assertEqual(client.get("/").status_code, 200)
            self.assertEqual(client.get("/about", headers={"User-Agent": "Googlebot"}).status_code, 200)
            with client.session_transaction() as state:
                state["admin_authenticated"] = True
            self.assertEqual(client.get("/").status_code, 200)
            report = client.get("/reports/traffic?days=7")
        self.assertEqual(report.status_code, 200)
        self.assertIn(b"Public page views", report.data)
        self.assertIn(b">1</td>", report.data)
        self.assertIn(b"/", report.data)

    def test_daily_autopilot_publishes_once_with_sources(self):
        app.set_app_setting("autopilot_config", json.dumps({"enabled": True, "schedule_time": "09:00"}))
        fake_article = {
            "article_title": "Small Entryway Storage Ideas",
            "meta_title": "Small Entryway Storage Ideas",
            "meta_description": "Helpful ways to organize a compact entryway.",
            "article_html": "<h1>Small Entryway Storage Ideas</h1><p>Small entryway storage ideas help.</p>",
        }
        sources = [
            {"title": "Source One", "url": "https://example.org/one", "content": "Supported details."},
            {"title": "Source Two", "url": "https://example.net/two", "content": "More supported details."},
        ]
        environment = {"TAVILY_API_KEY": "test-tavily", "GROQ_API_KEY": "test-groq", "SITE_NICHE": "home-decor"}
        with patch.dict(os.environ, environment), \
                patch.object(app, "discover_researched_keyword", return_value={
                    "keyword": "small home entryway storage solutions",
                    "search_intent": "informational",
                       "topic_cluster": "Small-space living",
                    "rationale": "Supported by current search topics.",
                }), \
                patch.object(app, "research_web_sources", return_value=sources), \
                patch.object(app, "Groq", return_value=object()), \
                patch.object(app.engine, "generate_article", return_value=fake_article):
            result = app.run_autopilot_once()
            self.assertEqual(result["status"], "published")
            article = app.load_articles()[0]
            self.assertEqual(article["status"], "Published")
            self.assertEqual(article["source"], "Daily web-researched autopilot")
            self.assertEqual(article["sources"], sources)
            self.assertTrue(article["slug"])
            public_page = app.app.test_client().get(f"/blog/{article['slug']}")
            self.assertIn(b"Source One", public_page.data)
            self.assertEqual(app.run_autopilot_once()["status"], "already-ran-or-running")


if __name__ == "__main__":
    unittest.main()
