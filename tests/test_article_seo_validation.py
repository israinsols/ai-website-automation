import json
import os
import re
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import main


class ArticleSeoValidationTests(unittest.TestCase):
    def test_missing_keyword_metadata_is_repaired_without_duplicating_body(self):
        keyword = "small home entryway storage solutions"
        segments = [
            "<h1>A Useful Guide</h1><h2>Plan the area</h2><p>" + " ".join(["practical"] * 330) + "</p>",
            "<h2>Choose useful pieces</h2><p>" + " ".join(["storage"] * 330) + "</p>",
            "<h2>Keep it comfortable</h2><p>" + keyword + " " + " ".join(["ideas"] * 329) + "</p>",
        ]

        class Completions:
            def __init__(self):
                self.index = 0

            def create(self, **kwargs):
                fields = {
                    "article_title": "A Useful Guide",
                    "meta_title": "Comfortable Entryway Ideas",
                    "meta_description": "A practical guide to organizing your home.",
                } if self.index == 0 else {}
                fields["article_html"] = segments[self.index]
                self.index += 1
                message = type("Message", (), {"content": json.dumps(fields)})()
                return type("Result", (), {"choices": [type("Choice", (), {"message": message})()]})()

        class Client:
            def __init__(self):
                self.chat = type("Chat", (), {"completions": Completions()})()

        article = main.generate_article(Client(), keyword, "home-decor")
        self.assertIn(keyword.casefold(), article["article_title"].casefold())
        self.assertIn(keyword.casefold(), article["meta_title"].casefold())
        self.assertIn(keyword.casefold(), article["meta_description"].casefold())
        self.assertEqual(len(re.findall(r"<h1>", article["article_html"])), 1)
        word_count = len(re.findall(r"\b[\w’'-]+\b", main.article_text(article["article_html"])))
        self.assertGreaterEqual(word_count, 900)
        self.assertLessEqual(word_count, 1300)

    def test_keyword_over_meta_title_limit_fails_with_actionable_message(self):
        keyword = "a focus keyword phrase that cannot fit inside the maximum sixty character seo title"
        with self.assertRaisesRegex(RuntimeError, "too long for the 60-character SEO title limit"):
            main.ensure_keyword_seo_fields({"article_title": "Example", "article_html": "<h1>Example</h1>"}, keyword)

    def test_wordpress_failure_retries_saved_article_without_consuming_keyword(self):
        article = {
            "article_title": "A saved article",
            "meta_title": "A saved article",
            "meta_description": "A practical article description.",
            "article_html": "<h1>A saved article</h1><p>Article body.</p>",
        }
        environment = {
            "GROQ_API_KEY": "test-groq",
            "TEST_MODE": "0",
            "WP_SITE_URL": "https://wordpress.example",
            "WP_AUTH_TOKEN": "test-token",
            "INDEXNOW_KEY": "test-indexnow",
            "SITE_NICHE": "home-decor",
        }
        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "used_keywords.json"
            pending_path = Path(directory) / "pending_wordpress_article.json"
            with patch.dict(os.environ, environment), \
                    patch.object(main, "STATE_PATH", state_path), \
                    patch.object(main, "PENDING_ARTICLE_PATH", pending_path), \
                    patch.object(main, "Groq", return_value=object()), \
                    patch.object(main, "generate_article", return_value=article) as generate_mock, \
                    patch.object(main, "publish_article", side_effect=RuntimeError("WordPress is unavailable")):
                with self.assertRaisesRegex(RuntimeError, "unavailable"):
                    main.run_once()

            self.assertTrue(pending_path.exists())
            pending = json.loads(pending_path.read_text(encoding="utf-8"))
            self.assertFalse(state_path.exists())

            with patch.dict(os.environ, environment), \
                    patch.object(main, "STATE_PATH", state_path), \
                    patch.object(main, "PENDING_ARTICLE_PATH", pending_path), \
                    patch.object(main, "generate_article", side_effect=AssertionError("must reuse pending article")) as retry_generate, \
                    patch.object(main, "publish_article", return_value="https://wordpress.example/post") as publish_mock, \
                    patch.object(main, "ping_indexnow"):
                main.run_once()

            generate_mock.assert_called_once()
            retry_generate.assert_not_called()
            publish_mock.assert_called_once_with(
                "https://wordpress.example", "test-token", article
            )
            self.assertFalse(pending_path.exists())
            saved_state = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertIn(pending["keyword"], saved_state["used_keywords"])


if __name__ == "__main__":
    unittest.main()
