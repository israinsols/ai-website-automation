import unittest
from unittest.mock import patch

import app


class ContentQualityEnhancementsTests(unittest.TestCase):
    def test_topic_clusters_include_pillar_and_supporting_topics(self):
        clusters = app.build_topic_clusters("home-decor", [])
        self.assertTrue(clusters)
        pillar_cluster = next(cluster for cluster in clusters if cluster["name"] == "Small-space living")
        self.assertIn("small apartment interior design", [item["keyword"] for item in pillar_cluster["items"]])
        self.assertTrue(any(item["keyword"] for item in pillar_cluster["items"]))

    def test_article_schema_contains_breadcrumb_and_organization(self):
        article = {
            "article_title": "Small apartment interior design ideas",
            "meta_description": "Practical design ideas for compact homes.",
            "keyword": "small apartment interior design",
            "niche": "home-decor",
            "topic_cluster": "Small-space living",
            "author": "Maya Patel",
            "published_at": "2026-09-29T12:00:00+00:00",
        }
        schema = app.build_article_schema(article, "https://example.com/blog/small-apartment-interior-design")
        self.assertEqual(schema["@type"], "BlogPosting")
        self.assertIn("breadcrumb", schema)
        self.assertIn("publisher", schema)
        self.assertIn("author", schema)

    def test_article_schema_uses_organization_when_no_person_author_is_recorded(self):
        schema = app.build_article_schema(
            {"article_title": "Storage ideas", "meta_description": "Useful storage ideas."},
            "https://example.com/blog/storage-ideas",
        )
        self.assertEqual(schema["author"]["@type"], "Organization")
        self.assertEqual(schema["author"]["name"], "Urban Nest Interiors Editorial Team")

    def test_article_schema_only_uses_configured_http_logo_url(self):
        article = {"article_title": "Storage ideas", "meta_description": "Useful storage ideas."}
        canonical = "https://example.com/blog/storage-ideas"
        with patch.dict("os.environ", {"PUBLISHER_LOGO_URL": "javascript:alert(1)"}):
            unsafe_schema = app.build_article_schema(article, canonical)
        self.assertNotIn("logo", unsafe_schema["publisher"])
        with patch.dict("os.environ", {"PUBLISHER_LOGO_URL": "https://example.com/logo.png"}):
            safe_schema = app.build_article_schema(article, canonical)
        self.assertEqual(safe_schema["publisher"]["logo"]["url"], "https://example.com/logo.png")

    def test_related_articles_prioritize_keyword_relevance_and_skip_invalid_targets(self):
        source = {
            "id": "source", "status": "Published", "slug": "small-entryway",
            "niche": "home-decor", "topic_cluster": "Small-space living",
            "keyword": "small apartment entryway storage", "article_title": "Entryway storage ideas",
        }
        recent_match = {
            "id": "match", "status": "Published", "slug": "apartment-entryway-storage",
            "niche": "home-decor", "topic_cluster": "Small-space living",
            "keyword": "small apartment entryway storage ideas", "article_title": "Apartment entryway storage",
            "published_at": "2026-09-20",
        }
        recent_unrelated = {
            "id": "unrelated", "status": "Published", "slug": "small-living-room",
            "niche": "home-decor", "topic_cluster": "Small-space living",
            "keyword": "small living room decor", "article_title": "Living room decor",
            "published_at": "2026-09-29",
        }
        missing_slug = dict(recent_match, id="missing-slug", slug="")
        self.assertEqual(
            [item["id"] for item in app.related_articles(source, [source, recent_unrelated, recent_match, missing_slug])],
            ["match", "unrelated"],
        )


if __name__ == "__main__":
    unittest.main()
