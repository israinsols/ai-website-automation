import unittest
from unittest.mock import patch

import app


class ContentQualityEnhancementsTests(unittest.TestCase):
    def test_article_quality_checks_report_structure_and_reference_coverage(self):
        article = {
            "keyword": "careful research",
            "meta_title": "Careful research in practice",
            "meta_description": "A useful guide to careful research.",
            "article_html": (
                "<h2>First section</h2><p>Opening details.</p>"
                "<h2>Second section</h2><p>Further details.</p>"
                "<h2>Third section</h2><p>Final details.</p>"
            ),
            "sources": [{"title": "Reference", "url": "https://example.com/reference"}],
        }
        checks = app.article_seo_checks(article)

        self.assertTrue(checks["headings_ok"])
        self.assertEqual(checks["heading_count"], 3)
        self.assertTrue(checks["paragraphs_ok"])
        self.assertEqual(checks["paragraph_count"], 3)
        self.assertTrue(checks["sources_available"])
        self.assertEqual(checks["source_count"], 1)

    def test_article_quality_checks_flag_missing_structure_and_sources(self):
        checks = app.article_seo_checks({
            "keyword": "",
            "meta_title": "",
            "meta_description": "",
            "article_html": "<p>One short paragraph.</p>",
        })

        self.assertFalse(checks["headings_ok"])
        self.assertFalse(checks["paragraphs_ok"])
        self.assertFalse(checks["sources_available"])
        self.assertEqual(checks["source_count"], 0)

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

    def test_exact_topic_keyword_beats_an_earlier_partial_cluster_match(self):
        self.assertEqual(
            app.topic_cluster_for_keyword("home-decor", "interior design trends for 2026"),
            "Budget styling",
        )
        self.assertEqual(
            app.topic_cluster_for_keyword("tech", "best budget laptops for students"),
            "Devices and smart home",
        )

    def test_related_articles_rank_shared_keywords_ahead_of_stale_topic_labels(self):
        source = {
            "id": "source", "status": "Published", "slug": "source",
            "niche": "tech", "topic_cluster": "Productivity and work",
            "keyword": "beginner guide to password managers",
            "article_title": "How to choose a password manager",
            "meta_description": "Protect passwords for work accounts and secure access.",
        }
        recent_unrelated = {
            "id": "unrelated", "status": "Published", "slug": "unrelated",
            "niche": "tech", "topic_cluster": "Productivity and work",
            "keyword": "remote work setup ideas", "article_title": "Remote work setup ideas",
            "meta_description": "Create a more comfortable home office.",
            "published_at": "2026-10-10",
        }
        relevant_but_mislabeled = {
            "id": "relevant", "status": "Published", "slug": "relevant",
            "niche": "tech", "topic_cluster": "Productivity and work",
            "keyword": "password manager tools for teams",
            "article_title": "Password manager tools for work",
            "meta_description": "Protect passwords for work accounts with safer access tools.",
            "published_at": "2026-10-01",
        }
        security_topic = {
            "id": "security-topic", "status": "Published", "slug": "security-topic",
            "niche": "tech", "topic_cluster": "Productivity and work",
            "keyword": "beginner guide to password managers",
            "article_title": "Password managers compared",
            "meta_description": "Compare secure password tools.",
            "published_at": "2026-09-29",
        }
        description_only_match = {
            "id": "description-only", "status": "Published", "slug": "description-only",
            "niche": "tech", "topic_cluster": "Productivity and work",
            "keyword": "remote work setup ideas", "article_title": "A practical remote setup",
            "meta_description": "Protect passwords for work accounts with safer access tools.",
            "published_at": "2026-10-11",
        }

        related = app.related_articles(
            source, [
                source, recent_unrelated, relevant_but_mislabeled,
                security_topic, description_only_match,
            ]
        )

        self.assertEqual([item["id"] for item in related], ["security-topic", "relevant"])
        self.assertEqual(related[0]["related_reason"], "Same topic: Digital security")
        self.assertIn("password", related[1]["related_reason"])


if __name__ == "__main__":
    unittest.main()
