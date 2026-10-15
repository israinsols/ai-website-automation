import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import os

import app


class ClientPortalTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database_path = app.DATABASE_PATH
        self.articles_path = app.ARTICLES_PATH
        app.DATABASE_PATH = Path(self.temp_dir.name) / "site.sqlite3"
        app.ARTICLES_PATH = Path(self.temp_dir.name) / "legacy.json"
        app.initialize_database()
        self.client = app.app.test_client()

    def tearDown(self):
        app.DATABASE_PATH = self.database_path
        app.ARTICLES_PATH = self.articles_path
        self.temp_dir.cleanup()

    def csrf_token(self):
        with self.client.session_transaction() as state:
            return state["_csrf_token"]

    def sign_up(self, email="client@example.com"):
        self.client.get("/client/signup")
        return self.client.post("/client/signup", data={
            "_csrf_token": self.csrf_token(),
            "display_name": "Client Writer",
            "email": email,
            "password": "secure-client-password",
            "confirm_password": "secure-client-password",
        })

    def test_editorial_submission_notification_is_sent_to_configured_team(self):
        article = {
            "id": "submitted-article",
            "article_title": "A client submission",
            "author": "Client Writer",
            "contributor_email": "client@example.com",
            "keyword": "sample client keyword",
            "client_website_url": "https://client.example.com",
            "created_at": "2026-10-15T12:30:00+05:00",
        }
        with patch.dict(os.environ, {"EDITORIAL_NOTIFICATION_EMAIL": "editor@example.com"}), \
                patch("app.send_newsletter_email") as send_email:
            self.assertTrue(app.send_editorial_submission_notification(article))
        self.assertEqual(send_email.call_args.args[0], "editor@example.com")
        self.assertIn("A client submission", send_email.call_args.args[1])
        self.assertIn("Urban Nest Interiors", send_email.call_args.args[1])
        self.assertIn("Oct 15, 2026", send_email.call_args.args[2])
        self.assertIn("sample client keyword", send_email.call_args.args[2])
        self.assertIn("client@example.com", send_email.call_args.args[2])
        html_body = send_email.call_args.kwargs["html_body"]
        self.assertIn("Urban Nest Interiors", html_body)
        self.assertIn("Oct 15, 2026", html_body)
        self.assertIn("https://client.example.com", html_body)
        self.assertIn("sample client keyword", html_body)

    def test_client_publication_notification_is_sent_to_contributor(self):
        article = {
            "id": "published-article",
            "article_title": "A published client article",
            "author": "Client Writer",
            "contributor_email": "client@example.com",
            "keyword": "sample published keyword",
            "slug": "published-client-article",
            "published_at": "2026-10-15T13:45:00+05:00",
        }
        with patch("app.send_newsletter_email") as send_email:
            self.assertTrue(app.send_client_publication_notification(article))
        self.assertEqual(send_email.call_args.args[0], "client@example.com")
        self.assertIn("published", send_email.call_args.args[1].lower())
        self.assertIn("published-client-article", send_email.call_args.args[2])
        self.assertIn("Client Writer", send_email.call_args.kwargs["html_body"])
        self.assertIn("Published", send_email.call_args.kwargs["html_body"])
        self.assertIn("Urban Nest Interiors", send_email.call_args.kwargs["html_body"])
        self.assertIn("Oct 15, 2026", send_email.call_args.kwargs["html_body"])
        self.assertIn("sample published keyword", send_email.call_args.kwargs["html_body"])

    def test_client_submission_confirmation_contains_review_status_and_branded_details(self):
        article = {
            "id": "submitted-client-article",
            "article_title": "A submitted client article",
            "author": "Client Writer",
            "contributor_email": "client@example.com",
            "created_at": "2026-10-15T12:30:00+05:00",
        }
        with patch("app.send_newsletter_email") as send_email:
            self.assertTrue(app.send_client_submission_confirmation(article))
        self.assertEqual(send_email.call_args.args[0], "client@example.com")
        self.assertIn("received", send_email.call_args.args[1].lower())
        self.assertIn("Pending Review", send_email.call_args.args[2])
        self.assertIn("published", send_email.call_args.args[2].lower())
        email_html = send_email.call_args.kwargs["html_body"]
        self.assertIn("Client Writer", email_html)
        self.assertIn("client@example.com", email_html)
        self.assertIn("Urban Nest Interiors", email_html)
        self.assertIn("Pending Review", email_html)
        self.assertIn("submitted-client-article", email_html)
        self.assertIn("Oct 15, 2026", email_html)

    def test_client_can_save_draft_and_submit_for_admin_review(self):
        response = self.sign_up()
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.location, "/client")

        dashboard = self.client.get("/client")
        self.assertEqual(dashboard.status_code, 200)
        self.assertIn(b"Welcome, Client Writer", dashboard.data)
        self.assertIn(b"Create an article", dashboard.data)

        self.client.get("/client/articles/new")
        token = self.csrf_token()
        draft_data = {
            "_csrf_token": token,
            "title": "A thoughtful client draft",
            "content": "This article is private while it is a draft.",
            "keyword": "thoughtful client draft",
            "client_website_url": "https://client.example.com",
            "action": "save_draft",
        }
        response = self.client.post("/client/articles/new", data=draft_data)
        self.assertEqual(response.status_code, 302)
        article = app.load_articles()[0]
        self.assertEqual(article["status"], "Draft")
        with self.client.session_transaction() as state:
            client_id = state["client_id"]
        self.assertEqual(article["client_id"], client_id)
        self.assertEqual(article["contributor_email"], "client@example.com")
        self.assertEqual(article["client_website_url"], "https://client.example.com")

        public_blog = self.client.get("/blog")
        self.assertNotIn(b"A thoughtful client draft", public_blog.data)
        edit_url = f"/client/articles/{article['id']}"
        self.client.get(edit_url)
        with patch("app.send_editorial_submission_notification", return_value=True) as notification, \
                patch("app.send_client_submission_confirmation", return_value=True) as client_confirmation:
            response = self.client.post(edit_url, data={
                "_csrf_token": self.csrf_token(),
                "title": article["article_title"],
                "content": "This article is now ready for editorial review.",
                "keyword": article["keyword"],
                "client_website_url": article["client_website_url"],
                "rights_confirmed": "on",
                "action": "submit_for_review",
            })
        self.assertEqual(response.status_code, 302)
        submitted = app.load_articles()[0]
        self.assertEqual(submitted["status"], "Pending Review")
        self.assertNotIn("published_at", submitted)
        self.assertEqual(submitted["source"], "Client account")
        self.assertTrue(submitted["reprint_permission_at"])
        self.assertEqual(submitted["reprint_terms_version"], app.REPRINT_TERMS_VERSION)
        self.assertEqual(submitted["client_website_url"], "https://client.example.com")
        notification.assert_called_once_with(submitted)
        client_confirmation.assert_called_once_with(submitted)
        self.assertNotIn(b"A thoughtful client draft", self.client.get("/blog").data)

        admin_client = app.app.test_client()
        with admin_client.session_transaction() as state:
            state["admin_authenticated"] = True
            state["admin_username"] = "site-editor"
            state["_csrf_token"] = "admin-token"
        with patch("app.send_published_article_newsletter", return_value=(1, 0)) as newsletter, \
                patch("app.send_client_publication_notification", return_value=True) as client_notification:
            response = admin_client.post(
                f"/articles/{submitted['id']}/publish",
                data={"_csrf_token": "admin-token"},
            )
        self.assertEqual(response.status_code, 302)
        published = app.load_articles()[0]
        self.assertEqual(published["status"], "Published")
        self.assertTrue(published["slug"])
        self.assertTrue(published["published_at"])
        self.assertEqual(published["editorial_reviewed_by"], "site-editor")
        newsletter.assert_called_once()
        client_notification.assert_called_once()
        self.assertIn(b"published articles", self.client.get("/client").data)
        self.assertIn(b"A thoughtful client draft", self.client.get("/blog").data)

    def test_client_must_confirm_rights_before_review_submission(self):
        self.sign_up()
        self.client.get("/client/articles/new")
        response = self.client.post("/client/articles/new", data={
            "_csrf_token": self.csrf_token(),
            "title": "Rights confirmation required",
            "content": "This article must remain private without permission confirmation.",
            "action": "submit_for_review",
        })
        self.assertEqual(response.status_code, 302)
        self.assertEqual(app.load_articles(), [])
        self.assertNotIn(b"Rights confirmation required", self.client.get("/blog").data)

    def test_failed_editorial_email_does_not_undo_pending_submission(self):
        self.sign_up()
        self.client.get("/client/articles/new")
        with patch("app.send_editorial_submission_notification", return_value=False), \
                patch("app.send_client_submission_confirmation", return_value=True):
            response = self.client.post("/client/articles/new", data={
                "_csrf_token": self.csrf_token(),
                "title": "Submission email failed",
                "content": "This submission should remain in the review queue.",
                "rights_confirmed": "on",
                "action": "submit_for_review",
            })
        self.assertEqual(response.status_code, 302)
        self.assertEqual(app.load_articles()[0]["status"], "Pending Review")
        dashboard = self.client.get("/client")
        self.assertIn(b"one or more confirmation emails could not be sent", dashboard.data)

    def test_client_cannot_publish_a_draft_directly(self):
        self.sign_up()
        self.client.get("/client/articles/new")
        response = self.client.post("/client/articles/new", data={
            "_csrf_token": self.csrf_token(),
            "title": "Client cannot publish",
            "content": "This article must be reviewed before publication.",
            "rights_confirmed": "on",
            "action": "publish_now",
        })
        self.assertEqual(response.status_code, 302)
        self.assertEqual(app.load_articles(), [])

        self.client.post("/client/articles/new", data={
            "_csrf_token": self.csrf_token(),
            "title": "Private client draft",
            "content": "The client should not be able to publish this draft.",
            "action": "save_draft",
        })
        draft = app.load_articles()[0]
        edit_url = f"/client/articles/{draft['id']}"
        self.client.get(edit_url)
        response = self.client.post(edit_url, data={
            "_csrf_token": self.csrf_token(),
            "title": draft["article_title"],
            "content": draft["article_html"],
            "rights_confirmed": "on",
            "action": "publish_now",
        })
        self.assertEqual(response.status_code, 302)
        self.assertEqual(app.load_articles()[0]["status"], "Draft")

        admin_client = app.app.test_client()
        with admin_client.session_transaction() as state:
            state["admin_authenticated"] = True
            state["admin_username"] = "site-editor"
            state["_csrf_token"] = "admin-token"
        response = admin_client.post(
            f"/articles/{draft['id']}/publish",
            data={"_csrf_token": "admin-token"},
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(app.load_articles()[0]["status"], "Draft")

    def test_admin_publication_is_kept_when_client_notification_fails(self):
        article = {
            "id": "client-notification-failure",
            "article_title": "Approved client article",
            "niche": "home-decor",
            "status": "Pending Review",
            "client_id": "client-123",
            "contributor_email": "client@example.com",
            "created_at": "2026-10-15T10:00:00+00:00",
            "article_html": "<p>Approved article text.</p>",
        }
        app.save_article(article)
        admin_client = app.app.test_client()
        with admin_client.session_transaction() as state:
            state["admin_authenticated"] = True
            state["admin_username"] = "site-editor"
            state["_csrf_token"] = "admin-token"
        with patch("app.send_published_article_newsletter", return_value=(0, 0)), \
                patch("app.send_client_publication_notification", return_value=False):
            response = admin_client.post(
                f"/articles/{article['id']}/publish",
                data={"_csrf_token": "admin-token"},
            )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(app.load_articles()[0]["status"], "Published")
        detail = admin_client.get(response.location)
        self.assertIn(b"client notification email failed", detail.data)

    def test_ai_generated_article_is_submitted_for_review(self):
        self.sign_up()
        self.client.get("/client/articles/new")
        generated = {
            "article_title": "AI generated living room ideas",
            "meta_title": "AI generated living room ideas",
            "meta_description": "Useful ideas for a comfortable small living room.",
            "article_html": "<h1>AI generated living room ideas</h1><p>Generated article text.</p>",
        }
        with patch("app.send_editorial_submission_notification", return_value=True) as notification, \
                patch("app.send_client_submission_confirmation", return_value=True) as client_confirmation, \
                patch.dict(os.environ, {"GROQ_API_KEY": "test-groq-key"}), \
                patch("app.Groq"), \
                patch("app.engine.generate_article", return_value=generated):
            generated_response = self.client.post("/client/articles/generate", data={
                "_csrf_token": self.csrf_token(),
                "keyword": "small living room ideas",
            })
        self.assertEqual(generated_response.status_code, 302)
        article = app.load_articles()[0]
        self.assertEqual(article["status"], "Pending Review")
        notification.assert_called_once_with(article)
        client_confirmation.assert_called_once_with(article)
        self.assertNotIn(b"AI generated living room ideas", self.client.get("/blog").data)
        dashboard = self.client.get("/client")
        self.assertIn(b"Pending Review", dashboard.data)

    def test_client_website_url_must_use_http_or_https(self):
        self.sign_up()
        self.client.get("/client/articles/new")
        response = self.client.post("/client/articles/new", data={
            "_csrf_token": self.csrf_token(),
            "title": "Invalid backlink draft",
            "content": "Some article body.",
            "client_website_url": "javascript:alert(1)",
            "action": "save_draft",
        })
        self.assertEqual(response.status_code, 302)
        self.assertEqual(app.load_articles(), [])

    def test_clients_can_only_view_and_edit_their_own_unsubmitted_drafts(self):
        self.sign_up("owner@example.com")
        self.client.get("/client/articles/new")
        response = self.client.post("/client/articles/new", data={
            "_csrf_token": self.csrf_token(),
            "title": "Owner-only draft",
            "content": "Only the account owner should see this.",
            "action": "save_draft",
        })
        self.assertEqual(response.status_code, 302)
        article = app.load_articles()[0]

        other_client = app.app.test_client()
        other_client.get("/client/signup")
        with other_client.session_transaction() as state:
            token = state["_csrf_token"]
        other_client.post("/client/signup", data={
            "_csrf_token": token,
            "display_name": "Other Writer",
            "email": "other@example.com",
            "password": "another-secure-password",
            "confirm_password": "another-secure-password",
        })
        self.assertEqual(other_client.get(f"/client/articles/{article['id']}").status_code, 404)

    def test_client_session_cannot_access_admin_workspace_routes(self):
        self.sign_up()
        self.assertEqual(self.client.get("/submit").location, "/client/articles/new")
        home_page = self.client.get("/")
        self.assertIn(b'href="/submit">Submit Article</a>', home_page.data)
        self.assertIn(b"href=\"/client\" class=\"btn btn-primary\">My client dashboard</a>", home_page.data)
        self.assertNotIn(b"Client sign in", home_page.data)
        self.assertNotIn(b"Client sign up", home_page.data)
        for path in ("/dashboard", "/articles", "/site-manager", "/admin/backup", "/reports/traffic"):
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 302)
                self.assertEqual(response.location, "/client")

        dashboard = self.client.get("/")
        self.assertIn(b"My client dashboard", dashboard.data)
        self.assertNotIn(b"Admin sign in", dashboard.data)
        self.assertNotIn(b"href=\"/dashboard\"", dashboard.data)

        response = self.client.post("/articles", data={
            "_csrf_token": self.csrf_token(),
            "keyword": "private admin article",
        })
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.location, "/client")
        self.assertEqual(app.load_articles(), [])

    def test_admin_can_view_registered_client_list_but_client_cannot(self):
        self.sign_up()
        with self.client.session_transaction() as state:
            client_id = state["client_id"]
        app.save_article({
            "id": "listed-client-article",
            "article_title": "Client review submission",
            "client_id": client_id,
            "status": "Pending Review",
            "created_at": "2026-10-15T12:00:00+05:00",
            "niche": "home-decor",
            "article_html": "<p>Private pending article.</p>",
        })

        denied = self.client.get("/admin/clients")
        self.assertEqual(denied.status_code, 302)
        self.assertEqual(denied.location, "/client")

        admin_client = app.app.test_client()
        with admin_client.session_transaction() as state:
            state["admin_authenticated"] = True
        response = admin_client.get("/admin/clients")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Client accounts for this site", response.data)
        self.assertIn(b"Client Writer", response.data)
        self.assertIn(b"client@example.com", response.data)
        self.assertIn(b"1 article", response.data)
        self.assertIn(b"1 pending", response.data)
        self.assertNotIn(b"password_hash", response.data)
        self.assertNotIn(b"secure-client-password", response.data)

    def test_anonymous_submit_article_link_never_renders_admin_workspace(self):
        response = self.client.get("/submit")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.location, "/client/signup")
        signup = self.client.get(response.location)
        self.assertEqual(signup.status_code, 200)
        self.assertNotIn(b"Admin sign in", signup.data)
        self.assertNotIn(b"WORKSPACE / SUBMIT", signup.data)
        home_page = self.client.get("/")
        self.assertIn(b'href="/submit">Submit Article</a>', home_page.data)
        self.assertIn(b'href="/submit" class="btn btn-primary">Submit an article</a>', home_page.data)
        self.assertNotIn(b"Client sign in", home_page.data)
        self.assertNotIn(b"Client sign up", home_page.data)

    def test_client_sign_in_and_duplicate_email_feedback(self):
        self.sign_up()
        self.client.get("/client")
        self.client.post("/client/logout", data={"_csrf_token": self.csrf_token()})
        self.client.get("/client/login")
        response = self.client.post("/client/login", data={
            "_csrf_token": self.csrf_token(),
            "email": "CLIENT@example.com",
            "password": "secure-client-password",
        })
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.location, "/client")

        duplicate_client = app.app.test_client()
        duplicate_client.get("/client/signup")
        with duplicate_client.session_transaction() as state:
            token = state["_csrf_token"]
        response = duplicate_client.post("/client/signup", data={
            "_csrf_token": token,
            "display_name": "Duplicate Writer",
            "email": "client@example.com",
            "password": "another-secure-password",
            "confirm_password": "another-secure-password",
        })
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"already exists", response.data)

    def test_ai_generation_saves_private_draft_and_enforces_daily_limit(self):
        self.sign_up()
        self.client.get("/client/articles/new")
        generated = {
            "article_title": "AI generated living room ideas",
            "meta_title": "AI generated living room ideas",
            "meta_description": "Useful ideas for a comfortable small living room.",
            "article_html": "<h1>AI generated living room ideas</h1><p>Generated article text.</p>",
        }
        with patch("app.send_editorial_submission_notification", return_value=True), \
                patch("app.send_client_submission_confirmation", return_value=True), \
                patch.dict(os.environ, {"GROQ_API_KEY": "test-groq-key"}), \
                patch("app.Groq"), \
                patch("app.engine.generate_article", return_value=generated) as generate:
            for _ in range(app.CLIENT_DAILY_GENERATION_LIMIT):
                response = self.client.post("/client/articles/generate", data={
                    "_csrf_token": self.csrf_token(),
                    "keyword": "small living room ideas",
                })
                self.assertEqual(response.status_code, 302)
                self.assertIn("/client/articles/", response.location)
            self.assertEqual(generate.call_count, app.CLIENT_DAILY_GENERATION_LIMIT)

            response = self.client.post("/client/articles/generate", data={
                "_csrf_token": self.csrf_token(),
                "keyword": "one more living room idea",
            })
            self.assertEqual(response.status_code, 302)
            self.assertEqual(response.location, "/client/articles/new")
            self.assertEqual(generate.call_count, app.CLIENT_DAILY_GENERATION_LIMIT)

        articles = app.load_articles()
        self.assertEqual(len(articles), app.CLIENT_DAILY_GENERATION_LIMIT)
        self.assertTrue(all(article["status"] == "Pending Review" for article in articles))
        self.assertTrue(all(article["source"] == "Client AI-generated draft" for article in articles))
        self.assertTrue(all(article["client_id"] for article in articles))
        self.assertTrue(all("<h1>" not in article["article_html"] for article in articles))
        editor = self.client.get("/client/articles/new")
        self.assertIn(b"0 generations left today", editor.data)
        self.assertIn(b"disabled", editor.data)

    def test_failed_ai_generation_does_not_consume_daily_quota(self):
        self.sign_up()
        self.client.get("/client/articles/new")
        with patch.dict(os.environ, {"GROQ_API_KEY": "test-groq-key"}), \
                patch("app.Groq"), \
                patch("app.engine.generate_article", side_effect=RuntimeError("Temporary generation error")):
            response = self.client.post("/client/articles/generate", data={
                "_csrf_token": self.csrf_token(),
                "keyword": "small living room ideas",
            })
        self.assertEqual(response.status_code, 302)
        self.assertEqual(app.load_articles(), [])
        self.assertEqual(app.client_generations_remaining(self.client_id()), app.CLIENT_DAILY_GENERATION_LIMIT)

    def client_id(self):
        with self.client.session_transaction() as state:
            return state["client_id"]


if __name__ == "__main__":
    unittest.main()
