import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import app


class WriteForUsTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database_path = app.DATABASE_PATH
        self.articles_path = app.ARTICLES_PATH
        app.DATABASE_PATH = Path(self.temp_dir.name) / "site.sqlite3"
        app.ARTICLES_PATH = Path(self.temp_dir.name) / "legacy.json"
        app.initialize_database()
        self.client = app.app.test_client()
        self.profile_paths_patch = patch("app.profile_article_database_paths", return_value=[])
        self.profile_paths_patch.start()

    def tearDown(self):
        self.profile_paths_patch.stop()
        app.DATABASE_PATH = self.database_path
        app.ARTICLES_PATH = self.articles_path
        self.temp_dir.cleanup()

    def render_write_for_us(self, niche, contact_email="editor@example.com"):
        settings = {**app.DEFAULT_SITE_SETTINGS, "site_name": "Example Journal"}
        with patch("app.current_niche", return_value=niche), \
                patch("app.load_site_settings", return_value=settings), \
                patch.dict(os.environ, {"CONTACT_EMAIL": contact_email}):
            return self.client.get("/write-for-us")

    def test_write_for_us_uses_site_topic_guidelines_and_email_address(self):
        cases = (
            ("home-decor", b"Room decor, styling, and small-space design", b"public-profile-home-decor"),
            ("tech", b"Useful software, apps, and digital tools", b"public-profile-tech"),
        )
        for niche, expected_topic, expected_profile in cases:
            with self.subTest(niche=niche):
                response = self.render_write_for_us(niche)
                self.assertEqual(response.status_code, 200)
                self.assertIn(expected_topic, response.data)
                self.assertIn(expected_profile, response.data)
                self.assertIn(b"mailto:editor@example.com", response.data)
                self.assertIn(b"Guest%20Post%20Submission", response.data)
                self.assertIn(b"No account or signup is needed", response.data)
                self.assertIn(b"publishes an article only after it has been approved", response.data)

    def test_submission_route_sends_visitors_to_write_for_us(self):
        response = self.client.get("/submit")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers["Location"], "/write-for-us")

    def test_write_for_us_does_not_link_to_signup_or_login(self):
        response = self.render_write_for_us("home-decor")
        self.assertNotIn(b"/client/signup", response.data)
        self.assertNotIn(b"/client/login", response.data)

    def test_write_for_us_explains_when_submission_email_is_not_configured(self):
        response = self.render_write_for_us("tech", contact_email="")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"submission email address has not been configured", response.data)
        self.assertNotIn(b"mailto:", response.data)

    def test_write_for_us_is_linked_and_listed_in_sitemap(self):
        settings = {**app.DEFAULT_SITE_SETTINGS, "site_name": "Example Journal"}
        with patch("app.load_site_settings", return_value=settings):
            for path in ("/", "/blog"):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 200)
                self.assertIn(b'href="/write-for-us">Write for Us</a>', response.data)
            sitemap = self.client.get("/sitemap.xml")
        self.assertEqual(sitemap.status_code, 200)
        self.assertIn(b"/write-for-us", sitemap.data)


if __name__ == "__main__":
    unittest.main()
