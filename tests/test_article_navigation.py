import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import app


class ArticleNavigationTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database_path = app.DATABASE_PATH
        self.articles_path = app.ARTICLES_PATH
        app.DATABASE_PATH = Path(self.temp_dir.name) / "site.sqlite3"
        app.ARTICLES_PATH = Path(self.temp_dir.name) / "legacy.json"
        app.initialize_database()

    def tearDown(self):
        app.DATABASE_PATH = self.database_path
        app.ARTICLES_PATH = self.articles_path
        self.temp_dir.cleanup()

    def test_table_of_contents_adds_unique_heading_anchors(self):
        article_html = (
            "<h2>Choose a router</h2><p>First section.</p>"
            "<h2>Choose a router</h2><p>Second section.</p>"
            "<h2>Secure your devices</h2><p>Third section.</p>"
        )

        updated_html, table_of_contents = app.add_article_table_of_contents(article_html)

        self.assertEqual(
            table_of_contents,
            [
                {"id": "choose-a-router", "title": "Choose a router"},
                {"id": "choose-a-router-2", "title": "Choose a router"},
                {"id": "secure-your-devices", "title": "Secure your devices"},
            ],
        )
        self.assertIn('<h2 id="choose-a-router">', updated_html)
        self.assertIn('<h2 id="choose-a-router-2">', updated_html)
        self.assertIn('<h2 id="secure-your-devices">', updated_html)

    def test_table_of_contents_is_omitted_for_short_articles(self):
        article_html = "<h2>One</h2><p>First.</p><h2>Two</h2><p>Second.</p>"

        updated_html, table_of_contents = app.add_article_table_of_contents(article_html)

        self.assertEqual(updated_html, article_html)
        self.assertEqual(table_of_contents, [])

    def test_public_article_renders_table_of_contents_and_reading_progress(self):
        article = {
            "id": "table-of-contents-test",
            "slug": "table-of-contents-test",
            "status": "Published",
            "created_at": "2026-09-29T09:00:00+00:00",
            "article_title": "A useful article",
            "meta_title": "A useful article",
            "meta_description": "A useful article description.",
            "article_html": (
                "<h2>First useful section</h2><p>Section one.</p>"
                "<h2>Second useful section</h2><p>Section two.</p>"
                "<h2>Third useful section</h2><p>Section three.</p>"
            ),
            "keyword": "useful article",
            "niche": "home-decor",
        }
        with patch.object(app, "load_articles", return_value=[article]):
            response = app.app.test_client().get("/blog/table-of-contents-test")

        self.assertEqual(response.status_code, 200)
        self.assertIn(b'aria-label="Table of contents"', response.data)
        self.assertIn(b'href="#first-useful-section"', response.data)
        self.assertIn(b'<h2 id="first-useful-section">First useful section</h2>', response.data)
        self.assertIn(b'data-reading-progress', response.data)
        self.assertIn(b'data-reading-content', response.data)


if __name__ == "__main__":
    unittest.main()
