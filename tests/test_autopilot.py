import json
import os
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
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

    def post_client_submission(self, client, data):
        client.get("/client/signup")
        with client.session_transaction() as state:
            data["_csrf_token"] = state["_csrf_token"]
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

    def test_calendar_scheduling_requires_explicit_approval_and_can_be_cancelled(self):
        draft = {
            "id": "scheduled-calendar-test", "article_title": "Scheduled calendar story",
            "keyword": "calendar story", "niche": "home-decor", "status": "Draft",
            "created_at": "2026-10-14T09:00:00+00:00", "article_html": "<p>Story.</p>",
        }
        app.save_article(draft)
        client = app.app.test_client()
        with client.session_transaction() as state:
            state["admin_authenticated"] = True
            state["admin_username"] = "site-editor"
            state["_csrf_token"] = "test-token"
        scheduled_at = (datetime.now().astimezone() + timedelta(days=1)).replace(second=0, microsecond=0)
        schedule_value = scheduled_at.strftime("%Y-%m-%dT%H:%M")
        form = {
            "_csrf_token": "test-token",
            "article_id": draft["id"],
            "action": "schedule_publication",
            "scheduled_publish_at": schedule_value,
        }

        unapproved_response = client.post("/calendar", data=form)
        self.assertEqual(unapproved_response.status_code, 302)
        self.assertNotIn("scheduled_publish_at", app.load_articles()[0])

        approved_response = client.post(
            "/calendar",
            data={**form, "approve_scheduled_publication": "on"},
        )
        self.assertEqual(approved_response.status_code, 302)
        scheduled = app.load_articles()[0]
        self.assertEqual(scheduled["status"], "Draft")
        self.assertTrue(scheduled["scheduled_publish_approved"])
        self.assertEqual(scheduled["scheduled_publish_approved_by"], "site-editor")
        self.assertEqual(datetime.fromisoformat(scheduled["scheduled_publish_at"]), scheduled_at)

        cancel_response = client.post("/calendar", data={
            "_csrf_token": "test-token",
            "article_id": draft["id"],
            "action": "cancel_publication",
        })
        self.assertEqual(cancel_response.status_code, 302)
        cancelled = app.load_articles()[0]
        self.assertEqual(cancelled["status"], "Draft")
        self.assertNotIn("scheduled_publish_at", cancelled)
        self.assertNotIn("scheduled_publish_approved", cancelled)

    def test_calendar_month_view_shows_review_and_approved_publish_events(self):
        client = app.app.test_client()
        with client.session_transaction() as state:
            state["admin_authenticated"] = True
        app.save_article({
            "id": "month-calendar-review", "slug": "month-calendar-review",
            "article_title": "December review reminder", "keyword": "december review",
            "niche": "home-decor", "status": "Draft",
            "created_at": "2026-10-14T09:00:00+00:00",
            "scheduled_for": "2026-12-15", "article_html": "<p>Draft.</p>",
        })
        app.save_article({
            "id": "month-calendar-publication", "slug": "month-calendar-publication",
            "article_title": "December approved publication", "keyword": "december publication",
            "niche": "home-decor", "status": "Pending Review",
            "created_at": "2026-10-14T10:00:00+00:00",
            "scheduled_publish_at": "2026-12-15T14:30:00+05:00",
            "scheduled_publish_approved": True,
            "article_html": "<p>Approved draft.</p>",
        })

        response = client.get("/calendar?month=2026-12&day=2026-12-15")

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"December 2026", response.data)
        self.assertIn(b"Review reminder", response.data)
        self.assertIn(b"Approved publication", response.data)
        self.assertIn(b"14:30", response.data)
        self.assertIn(b"Tuesday, December 15, 2026", response.data)
        self.assertIn(b"month=2026-11", response.data)
        self.assertIn(b"month=2027-01", response.data)
        self.assertIn(b"day=2026-12-15", response.data)
        self.assertEqual(response.data.count(b'class="editorial-calendar-day'), 42)

    def test_calendar_month_view_uses_safe_defaults_for_invalid_month_and_day(self):
        client = app.app.test_client()
        with client.session_transaction() as state:
            state["admin_authenticated"] = True

        response = client.get("/calendar?month=2026-99&day=not-a-date")

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"October 2026", response.data)
        self.assertIn(b"Wednesday, October 14, 2026", response.data)

    def test_due_scheduled_publications_publish_once_without_autopilot(self):
        now = datetime(2026, 10, 14, 18, 0, tzinfo=timezone(timedelta(hours=5)))
        scheduled = {
            "id": "due-schedule", "article_title": "Approved scheduled story",
            "keyword": "scheduled story", "niche": "home-decor", "status": "Draft",
            "created_at": "2026-10-13T09:00:00+05:00", "article_html": "<p>Approved story.</p>",
            "scheduled_publish_at": "2026-10-14T17:30:00+05:00",
            "scheduled_publish_approved": True,
            "scheduled_publish_approved_by": "site-editor",
        }
        not_approved = {
            **scheduled,
            "id": "not-approved",
            "article_title": "Unapproved scheduled story",
            "scheduled_publish_approved": False,
        }
        future = {
            **scheduled,
            "id": "future-scheduled",
            "article_title": "Future scheduled story",
            "scheduled_publish_at": "2026-10-14T18:30:00+05:00",
        }
        client_draft = {
            **scheduled,
            "id": "client-draft-scheduled",
            "article_title": "Unsubmitted client article",
            "client_id": "client-123",
            "status": "Draft",
        }
        for article in (scheduled, not_approved, future, client_draft):
            app.save_article(article)

        with patch("app.send_published_article_newsletter", return_value=(0, 0)) as newsletter:
            first_result = app.run_due_scheduled_publications(now)
            second_result = app.run_due_scheduled_publications(now)

        self.assertEqual(first_result, {"status": "complete", "published": 1, "failed": 0})
        self.assertEqual(second_result, {"status": "complete", "published": 0, "failed": 0})
        self.assertEqual(newsletter.call_count, 1)
        articles = {item["id"]: item for item in app.load_articles()}
        self.assertEqual(articles["due-schedule"]["status"], "Published")
        self.assertEqual(articles["due-schedule"]["editorial_reviewed_by"], "site-editor")
        self.assertEqual(articles["due-schedule"]["published_at"], now.isoformat(timespec="minutes"))
        self.assertNotIn("scheduled_publish_at", articles["due-schedule"])
        self.assertEqual(articles["not-approved"]["status"], "Draft")
        self.assertEqual(articles["future-scheduled"]["status"], "Draft")
        self.assertEqual(articles["client-draft-scheduled"]["status"], "Draft")

    def test_editing_scheduled_article_revokes_approval_and_schedule(self):
        article = {
            "id": "edited-schedule", "article_title": "Before scheduled edit",
            "meta_title": "Before scheduled edit", "meta_description": "An article before editing.",
            "keyword": "scheduled edit", "niche": "home-decor",
            "status": "Draft", "created_at": "2026-10-14T09:00:00+00:00",
            "article_html": "<p>Article body.</p>",
            "scheduled_publish_at": "2026-10-15T10:00:00+05:00",
            "scheduled_publish_approved": True,
            "scheduled_publish_approved_by": "site-editor",
        }
        app.save_article(article)
        client = app.app.test_client()
        with client.session_transaction() as state:
            state["admin_authenticated"] = True
            state["_csrf_token"] = "test-token"

        response = client.post("/articles/edited-schedule", data={
            "_csrf_token": "test-token",
            "article_title": "Updated scheduled article",
            "meta_title": "Updated scheduled article",
            "meta_description": "An updated article description.",
            "keyword": "scheduled edit",
            "original_url": "",
        })

        self.assertEqual(response.status_code, 302)
        updated = next(item for item in app.load_articles() if item["id"] == "edited-schedule")
        self.assertEqual(updated["article_title"], "Updated scheduled article")
        self.assertNotIn("scheduled_publish_at", updated)
        self.assertNotIn("scheduled_publish_approved", updated)

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

    def test_submit_route_sends_visitors_to_write_for_us(self):
        client = app.app.test_client()
        self.assertEqual(client.post("/submit", data={}).status_code, 400)
        response = self.post_client_submission(client, {
            "title": "Licensed client article",
            "contributor_email": "writer@example.com",
            "content": "<p>Article text for editorial review.</p>",
        })
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.location, "/write-for-us")
        self.assertEqual(app.load_articles(), [])

    def test_legacy_submit_post_cannot_create_guest_article(self):
        client = app.app.test_client()
        response = self.post_client_submission(client, {
            "title": "Anonymous article",
            "contributor_email": "anonymous@example.com",
            "content": "<p>This must not be stored as a guest submission.</p>",
            "rights_confirmed": "on",
        })
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.location, "/write-for-us")
        self.assertEqual(app.load_articles(), [])

    def test_client_submission_email_limit_blocks_spam(self):
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

    def test_signed_in_client_submission_waits_for_review_before_publication(self):
        client = app.app.test_client()
        client.get("/client/signup")
        with client.session_transaction() as state:
            csrf_token = state["_csrf_token"]
        signup = client.post("/client/signup", data={
            "_csrf_token": csrf_token,
            "display_name": "Client Writer",
            "email": "owner@example.com",
            "password": "secure-client-password",
            "confirm_password": "secure-client-password",
        })
        self.assertEqual(signup.status_code, 302)
        client.get("/client/articles/new")
        with client.session_transaction() as state:
            csrf_token = state["_csrf_token"]
        with patch("app.send_editorial_submission_notification", return_value=True), \
                patch("app.send_client_submission_confirmation", return_value=True):
            response = client.post("/client/articles/new", data={
                "_csrf_token": csrf_token,
                "title": "Syndicated storage guide",
                "author": "Client Writer",
                "keyword": "storage guide",
                "content": "Useful original storage advice.",
                "client_website_url": "https://client.example.com",
                "original_url": "https://client.example.com/storage-guide",
                "canonical_to_original": "on",
                "rights_confirmed": "on",
                "action": "submit_for_review",
            })
        self.assertEqual(response.status_code, 302)
        article = app.load_articles()[0]
        self.assertEqual(article["status"], "Pending Review")
        self.assertEqual(article["contributor_email"], "owner@example.com")
        self.assertEqual(article["reprint_terms_version"], app.REPRINT_TERMS_VERSION)
        self.assertTrue(article["reprint_permission_at"])
        self.assertTrue(article["canonical_to_original"])
        self.assertEqual(article["client_website_url"], "https://client.example.com")
        self.assertEqual(article["source"], "Client account")
        self.assertNotIn("slug", article)

        admin_client = app.app.test_client()
        with admin_client.session_transaction() as state:
            state["admin_authenticated"] = True
            state["admin_username"] = "site-editor"
            state["_csrf_token"] = "admin-token"
        with patch("app.send_client_publication_notification", return_value=True):
            response = admin_client.post(
                f"/articles/{article['id']}/publish",
                data={"_csrf_token": "admin-token"},
            )
        self.assertEqual(response.status_code, 302)
        article = app.load_articles()[0]
        self.assertEqual(article["status"], "Published")
        self.assertEqual(article["editorial_reviewed_by"], "site-editor")
        public_page = client.get(f"/blog/{article['slug']}")
        self.assertIn(b'<link rel="canonical" href="https://client.example.com/storage-guide">', public_page.data)
        self.assertIn(b'href="https://client.example.com" target="_blank" rel="sponsored nofollow noopener noreferrer"', public_page.data)
        self.assertIn(b"Visit Client Writer", public_page.data)
        self.assertIn(b"Visit Client Writer\xe2\x80\x99s website: https://client.example.com", public_page.data)
        self.assertIn(b"Originally published at", public_page.data)
        self.assertNotIn(article["slug"].encode(), app.app.test_client().get("/sitemap.xml").data)
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

    def test_signed_in_client_submit_link_opens_private_article_editor(self):
        client = app.app.test_client()
        client.get("/client/signup")
        with client.session_transaction() as state:
            csrf_token = state["_csrf_token"]
        client.post("/client/signup", data={
            "_csrf_token": csrf_token,
            "display_name": "Client Writer",
            "email": "writer@example.com",
            "password": "secure-client-password",
            "confirm_password": "secure-client-password",
        })
        response = client.get("/submit")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.location, "/write-for-us")
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
        self.assertIn(b"Reader analytics", report.data)
        self.assertIn(b">1</td>", report.data)
        self.assertIn(b"/", report.data)

    def test_reader_analytics_summarizes_article_views_and_compares_periods(self):
        today = app.datetime.now().astimezone().date()
        published = {
            "id": "reader-favorite", "slug": "reader-favorite", "status": "Published",
            "created_at": today.isoformat(), "published_at": today.isoformat(),
            "article_title": "Reader favorite story", "meta_title": "Reader favorite story",
            "meta_description": "A popular published story.", "article_html": "<p>Story body.</p>",
            "keyword": "reader favorite", "niche": "home-decor",
        }
        app.save_article(published)
        app.save_article({
            **published, "id": "hidden-story", "slug": "hidden-story", "status": "Draft",
            "article_title": "Unpublished draft",
        })

        current_start = today - app.timedelta(days=6)
        previous_start = current_start - app.timedelta(days=7)
        connection = sqlite3.connect(app.DATABASE_PATH)
        try:
            with connection:
                connection.executemany(
                    "INSERT INTO page_view_daily (view_date, page_key, view_count) VALUES (?, ?, ?)",
                    [
                        (today.isoformat(), "/blog/reader-favorite", 6),
                        ((today - app.timedelta(days=2)).isoformat(), "/blog/reader-favorite", 4),
                        (today.isoformat(), "/", 2),
                        (today.isoformat(), "/blog/hidden-story", 9),
                        (previous_start.isoformat(), "/blog/reader-favorite", 3),
                        (previous_start.isoformat(), "/about", 1),
                    ],
                )
        finally:
            connection.close()

        client = app.app.test_client()
        with client.session_transaction() as state:
            state["admin_authenticated"] = True
        with patch.object(app, "APP_ENV", "production"):
            report = client.get("/reports/traffic?days=7")

        self.assertEqual(report.status_code, 200)
        self.assertIn(b"Reader favorite story", report.data)
        self.assertIn(b"/blog/reader-favorite", report.data)
        self.assertIn(b"+425%", report.data)
        self.assertIn(b"ARTICLES WITH VIEWS", report.data)
        self.assertIn(b"Daily page views over the last 7 days", report.data)
        self.assertNotIn(b"Unpublished draft", report.data)
        self.assertIn(b"aria-current=\"page\"", report.data)

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
