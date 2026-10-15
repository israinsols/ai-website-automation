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

    def test_client_can_sign_up_save_private_draft_and_publish_immediately(self):
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
        response = self.client.post(edit_url, data={
            "_csrf_token": self.csrf_token(),
            "title": article["article_title"],
            "content": "This article is now ready to publish immediately.",
            "keyword": article["keyword"],
            "client_website_url": article["client_website_url"],
            "rights_confirmed": "on",
            "action": "publish_now",
        })
        self.assertEqual(response.status_code, 302)
        submitted = app.load_articles()[0]
        self.assertEqual(submitted["status"], "Published")
        self.assertTrue(submitted["slug"])
        self.assertTrue(submitted["published_at"])
        self.assertEqual(submitted["source"], "Client account auto-published")
        self.assertNotIn("editorial_reviewed_at", submitted)
        self.assertNotIn("editorial_reviewed_by", submitted)
        self.assertTrue(submitted["reprint_permission_at"])
        self.assertEqual(submitted["client_website_url"], "https://client.example.com")
        self.assertIn(b"published articles", self.client.get("/client").data)
        self.assertIn(b"A thoughtful client draft", self.client.get("/blog").data)
        public_article = self.client.get(f"/blog/{submitted['slug']}")
        self.assertEqual(public_article.status_code, 200)
        self.assertIn(b"not recorded", public_article.data)

    def test_client_must_confirm_rights_before_immediate_publication(self):
        self.sign_up()
        self.client.get("/client/articles/new")
        response = self.client.post("/client/articles/new", data={
            "_csrf_token": self.csrf_token(),
            "title": "Rights confirmation required",
            "content": "This article must remain private without permission confirmation.",
            "action": "publish_now",
        })
        self.assertEqual(response.status_code, 302)
        self.assertEqual(app.load_articles(), [])
        self.assertNotIn(b"Rights confirmation required", self.client.get("/blog").data)

    def test_ai_generated_draft_can_be_published_immediately_after_reviewing(self):
        self.sign_up()
        self.client.get("/client/articles/new")
        generated = {
            "article_title": "AI generated living room ideas",
            "meta_title": "AI generated living room ideas",
            "meta_description": "Useful ideas for a comfortable small living room.",
            "article_html": "<h1>AI generated living room ideas</h1><p>Generated article text.</p>",
        }
        with patch.dict(os.environ, {"GROQ_API_KEY": "test-groq-key"}), \
                patch("app.Groq"), \
                patch("app.engine.generate_article", return_value=generated):
            generated_response = self.client.post("/client/articles/generate", data={
                "_csrf_token": self.csrf_token(),
                "keyword": "small living room ideas",
            })
        self.assertEqual(generated_response.status_code, 302)
        article = app.load_articles()[0]
        self.assertEqual(article["status"], "Draft")
        self.assertNotIn(b"AI generated living room ideas", self.client.get("/blog").data)

        detail_url = f"/client/articles/{article['id']}"
        self.client.get(detail_url)
        with patch("app.send_published_article_newsletter", return_value=(1, 0)) as newsletter:
            response = self.client.post(detail_url, data={
                "_csrf_token": self.csrf_token(),
                "title": article["article_title"],
                "content": article["article_html"],
                "keyword": article["keyword"],
                "rights_confirmed": "on",
                "action": "publish_now",
            })
        self.assertEqual(response.status_code, 302)
        published = app.load_articles()[0]
        self.assertEqual(published["status"], "Published")
        self.assertEqual(published["source"], "Client account auto-published")
        self.assertEqual(published["reprint_terms_version"], app.REPRINT_TERMS_VERSION)
        self.assertNotIn("editorial_reviewed_at", published)
        newsletter.assert_called_once()
        self.assertEqual(newsletter.call_args.args[0]["status"], "Published")
        dashboard = self.client.get("/client")
        self.assertIn(b"Newsletter sent", dashboard.data)
        self.assertIn(b"AI generated living room ideas", self.client.get("/blog").data)

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
        with patch.dict(os.environ, {"GROQ_API_KEY": "test-groq-key"}), \
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
        self.assertTrue(all(article["status"] == "Draft" for article in articles))
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
