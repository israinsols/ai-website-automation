import json
import sqlite3
import tempfile
import unittest
from datetime import datetime
from io import BytesIO
from pathlib import Path
from urllib.parse import urlparse
from unittest.mock import Mock, patch
import xml.etree.ElementTree as ET

import app
from PIL import Image


class SiteManagementTests(unittest.TestCase):
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
        with self.client.session_transaction() as state:
            state["admin_authenticated"] = True
            state["admin_username"] = "site-editor"
            state["_csrf_token"] = "test-token"

    def tearDown(self):
        app.DATABASE_PATH = self.database_path
        app.ARTICLES_PATH = self.articles_path
        self.profile_paths_patch.stop()
        self.temp_dir.cleanup()

    def csrf(self, **values):
        return {"_csrf_token": "test-token", **values}

    def test_site_manager_updates_brand_theme_navigation_and_newsletter(self):
        response = self.client.post("/site-manager", data=self.csrf(
            site_name="Studio North",
            site_description="A custom site description",
            site_tagline="Thoughtful publishing",
            site_eyebrow="STUDIO NORTH",
            category="interior design",
            headline="Ideas for calmer rooms",
            hero_image_url="https://example.com/hero.jpg",
            theme_primary="#123456",
            theme_background="#f0f0f0",
            navigation="Home | /\nCustom page | /pages/our-story",
            newsletter_enabled="on",
            newsletter_title="Monthly notes",
            newsletter_description="Useful ideas, once a month.",
        ))
        self.assertEqual(response.status_code, 302)
        settings = app.load_site_settings()
        self.assertEqual(settings["site_name"], "Studio North")
        self.assertEqual(settings["theme_primary"], "#123456")
        self.assertTrue(settings["newsletter_enabled"])
        self.assertEqual(settings["navigation"][1]["url"], "/pages/our-story")

        home = self.client.get("/")
        self.assertIn(b"Ideas for calmer rooms", home.data)
        self.assertIn(b"Monthly notes", home.data)
        self.assertIn(b"--primary: #123456", home.data)
        self.assertIn(b'src="https://example.com/hero.jpg"', home.data)
        self.assertIn(b'>Blogs</a>', home.data)

    def test_blog_link_remains_in_public_navigation_after_menu_customization(self):
        app.set_app_setting("site_settings", json.dumps({
            **app.DEFAULT_SITE_SETTINGS,
            "navigation": [{"label": "Home", "url": "/"}],
        }))
        for path in ("/", "/blog", "/about"):
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 200)
                self.assertIn(b'>Blogs</a>', response.data)
                self.assertIn(b'href="/blog"', response.data)

    def test_public_profiles_have_distinct_niche_specific_visual_themes(self):
        home = self.client.get("/")
        self.assertIn(b"public-profile-home-decor", home.data)
        self.assertIn(b"--primary: #8b7350", home.data)
        self.assertIn(b"--bg: #f5f1e8", home.data)
        self.assertIn(b'class="hero-image"', home.data)
        self.assertIn(b"1616486338812-3dadae4b4ace", home.data)
        self.assertIn(b"SPACES THAT FEEL LIKE YOU", home.data)
        self.assertIn(b"class=\"visual-gallery\"", home.data)
        self.assertEqual(home.data.count(b'class="visual-card visual-card-'), 5)
        self.assertIn(b"1600607687939-ce8a6c25118c", home.data)

        app.set_app_setting("site_settings", json.dumps({
            **app.DEFAULT_SITE_SETTINGS,
            "category": "tech",
        }))
        for path in ("/", "/blog"):
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 200)
                self.assertIn(b"public-profile-tech", response.data)
                self.assertIn(b"--primary: #5ee1f2", response.data)
                self.assertIn(b"--bg: #0a1220", response.data)
                if path == "/":
                    self.assertIn(b"class=\"visual-gallery\"", response.data)
                    self.assertIn(b"1498050108023-c5249f4df085", response.data)
                    self.assertIn(b"MADE FOR THE WAY YOU WORK", response.data)
                    self.assertEqual(response.data.count(b'class="visual-card visual-card-'), 5)
                    self.assertIn(b"1531297484001-80022131f5a1", response.data)

    def test_custom_blog_menu_label_is_normalized_to_blogs(self):
        app.set_app_setting("site_settings", json.dumps({
            **app.DEFAULT_SITE_SETTINGS,
            "navigation": [{"label": "Journal", "url": "/blog"}],
        }))
        self.assertEqual(app.load_site_settings()["navigation"], [{"label": "Blogs", "url": "/blog"}])

    def test_blog_gallery_and_article_page_render_cover_images(self):
        article = {
            "id": "image-post", "slug": "image-post", "status": "Published",
            "created_at": "2026-10-01T09:00:00+00:00",
            "published_at": "2026-10-01T09:00:00+00:00",
            "article_title": "Small Room Lighting Ideas", "meta_title": "Small Room Lighting",
            "meta_description": "Ideas for lighting small rooms.",
            "article_html": "<p>Article body.</p>", "keyword": "small room lighting",
            "niche": "home-decor",
        }
        app.save_article(article)

        home_page = self.client.get("/")
        self.assertEqual(home_page.status_code, 200)
        self.assertIn(b'aria-label="Main navigation"', home_page.data)
        self.assertIn(b'class="home-journal-grid"', home_page.data)
        self.assertIn(b'data-story-search', home_page.data)
        self.assertIn(b"Small Room Lighting Ideas", home_page.data)
        self.assertIn(b'href="/blog/image-post"', home_page.data)
        self.assertIn(b"1 MIN READ", home_page.data)
        self.assertIn(b'class="home-footer-main"', home_page.data)
        self.assertIn(b'property="og:image"', home_page.data)
        self.assertIn(b'property="og:image:alt"', home_page.data)
        self.assertIn(b'name="twitter:card" content="summary_large_image"', home_page.data)
        self.assertIn("© 2026".encode(), home_page.data)

        journal = self.client.get("/blog")
        self.assertEqual(journal.status_code, 200)
        self.assertIn(b"class=\"journal-masthead\"", journal.data)
        self.assertIn(b"Urban Nest Interiors Journal", journal.data)
        self.assertIn(b"class=\"magazine-opening\"", journal.data)
        self.assertIn(b"blog-feature-grid", journal.data)
        self.assertIn(b"blog-feature-count-1", journal.data)
        self.assertNotIn(b"FEATURED STORY", journal.data)
        self.assertIn(b"1 min read", journal.data)
        self.assertIn(b'src="https://images.unsplash.com/photo-', journal.data)
        self.assertIn(b'property="og:site_name"', journal.data)
        self.assertIn(b'name="twitter:description"', journal.data)
        self.assertIn(b'name="twitter:url"', journal.data)

        article_page = self.client.get("/blog/image-post")
        self.assertEqual(article_page.status_code, 200)
        self.assertIn(b'class="article-magazine"', article_page.data)
        self.assertIn(b"NEW POST", article_page.data)
        self.assertIn(b"On the blog", article_page.data)
        self.assertIn(b'class="article-photo-collage"', article_page.data)
        self.assertGreaterEqual(article_page.data.count(b'<img src="https://images.unsplash.com/photo-'), 4)
        self.assertEqual(article_page.data.count(b'loading="eager"'), 4)
        self.assertIn(b"Article body.", article_page.data)
        self.assertIn(b"1 min read", article_page.data)
        self.assertIn(b'data-save-article', article_page.data)
        self.assertIn(b'href="/saved"', article_page.data)
        self.assertIn(b'href="https://wa.me/?text=', article_page.data)
        self.assertIn(b'href="https://www.facebook.com/sharer/sharer.php?u=', article_page.data)
        self.assertIn(b'href="https://twitter.com/intent/tweet?text=', article_page.data)
        self.assertIn(b'rel="noopener noreferrer">WhatsApp</a>', article_page.data)
        self.assertIn(b'rel="noopener noreferrer">Facebook</a>', article_page.data)
        self.assertIn(b'rel="noopener noreferrer">X</a>', article_page.data)
        self.assertIn(b'property="og:image"', article_page.data)
        self.assertIn(b'property="og:site_name"', article_page.data)
        self.assertIn(b'property="article:published_time"', article_page.data)
        self.assertIn(b'name="twitter:title"', article_page.data)
        self.assertIn(b'name="twitter:description"', article_page.data)
        self.assertIn(b'name="twitter:card" content="summary_large_image"', article_page.data)

    def test_saved_stories_page_lists_published_articles_for_browser_bookmarks(self):
        app.set_app_setting("site_settings", json.dumps({
            **app.DEFAULT_SITE_SETTINGS, "category": "tech",
        }))
        for slug, status in (("saved-tech-story", "Published"), ("draft-tech-story", "Draft")):
            app.save_article({
                "id": slug,
                "slug": slug,
                "status": status,
                "created_at": "2026-10-03T09:00:00+00:00",
                "article_title": f"Article {slug}",
                "meta_title": f"Article {slug}",
                "meta_description": "A useful technology article.",
                "article_html": "<p>Helpful advice.</p>",
                "keyword": "technology article",
                "niche": "tech",
            })

        response = self.client.get("/saved")

        self.assertEqual(response.status_code, 200)
        self.assertIn(b'<meta name="robots" content="noindex, nofollow">', response.data)
        self.assertIn(b'data-saved-page', response.data)
        self.assertIn(b'data-saved-slug="saved-tech-story"', response.data)
        self.assertNotIn(b'data-saved-slug="draft-tech-story"', response.data)
        self.assertIn(b'href="/saved"', response.data)

    def test_unpublished_duplicate_article_redirects_to_its_published_copy(self):
        app.set_app_setting("site_settings", json.dumps({
            **app.DEFAULT_SITE_SETTINGS, "category": "tech",
        }))
        shared = {
            "article_title": "Best Note Taking Apps for Teams",
            "meta_title": "Best Note Taking Apps for Teams",
            "meta_description": "A practical team note-taking guide.",
            "article_html": "<p>Helpful advice.</p>",
            "keyword": "best note taking apps for teams",
            "niche": "tech",
        }
        app.save_article({
            **shared,
            "id": "note-taking-original",
            "slug": "best-note-taking-apps-for-teams",
            "status": "Published",
            "created_at": "2026-10-03T09:00:00+00:00",
        })
        app.save_article({
            **shared,
            "id": "note-taking-duplicate",
            "slug": "best-note-taking-apps-for-teams-2",
            "status": "Draft",
            "created_at": "2026-10-05T09:00:00+00:00",
        })

        response = self.client.get("/blog/best-note-taking-apps-for-teams-2")

        self.assertEqual(response.status_code, 301)
        self.assertEqual(response.headers["Location"], "/blog/best-note-taking-apps-for-teams")
        self.assertEqual(self.client.get(response.headers["Location"]).status_code, 200)

    def test_most_read_articles_use_aggregate_views_and_show_reading_times(self):
        article_html = "<p>" + " ".join(["useful"] * 401) + "</p>"
        for slug in ("popular-one", "popular-two", "popular-three"):
            app.save_article({
                "id": slug,
                "slug": slug,
                "status": "Published",
                "created_at": "2026-10-01T09:00:00+00:00",
                "published_at": "2026-10-01T09:00:00+00:00",
                "article_title": slug.replace("-", " ").title(),
                "meta_title": slug.replace("-", " ").title(),
                "meta_description": "Useful ideas for a thoughtful home.",
                "article_html": article_html,
                "keyword": "small living room decor ideas",
                "niche": "home-decor",
            })

        connection = sqlite3.connect(app.DATABASE_PATH)
        try:
            with connection:
                for slug, count in (("popular-one", 4), ("popular-two", 12), ("popular-three", 0)):
                    if count:
                        connection.execute(
                            "INSERT INTO page_view_daily (view_date, page_key, view_count) VALUES (?, ?, ?)",
                            (datetime.now().astimezone().date().isoformat(), f"/blog/{slug}", count),
                        )
        finally:
            connection.close()

        home_page = self.client.get("/")
        self.assertEqual(home_page.status_code, 200)
        self.assertIn(b"Most-read stories", home_page.data)
        self.assertLess(home_page.data.index(b"/blog/popular-two"), home_page.data.index(b"/blog/popular-one"))
        self.assertIn(b"12 reads", home_page.data)
        self.assertIn(b"3 min read", home_page.data)

        journal = self.client.get("/blog")
        self.assertEqual(journal.status_code, 200)
        self.assertIn(b"Most-read stories", journal.data)
        self.assertLess(journal.data.index(b"/blog/popular-two"), journal.data.index(b"/blog/popular-one"))

        article_page = self.client.get("/blog/popular-one")
        self.assertEqual(article_page.status_code, 200)
        self.assertIn(b"3 min read", article_page.data)
        self.assertIn(b"RELATED STORIES IN Small-space living", article_page.data)
        self.assertIn(b"/blog/popular-two", article_page.data)
        self.assertIn(b"Same topic: Small-space living", article_page.data)

    def test_homepage_has_a_separate_section_for_additional_published_articles(self):
        for index in range(7):
            created_at = f"2026-10-{index + 1:02d}T09:00:00+00:00"
            app.save_article({
                "id": f"homepage-story-{index}",
                "slug": f"homepage-story-{index}",
                "status": "Published",
                "created_at": created_at,
                "published_at": created_at,
                "article_title": f"Homepage story {index}",
                "meta_title": f"Homepage story {index}",
                "meta_description": f"Useful ideas number {index}.",
                "article_html": "<p>Article body.</p>",
                "keyword": f"homepage ideas {index}",
                "niche": "home-decor",
            })

        response = self.client.get("/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data.count(b'data-story-card'), 7)
        self.assertIn(b'data-home-more-section', response.data)
        self.assertIn(b'More inspiration for your home.', response.data)
        self.assertIn(b'Homepage story 3', response.data)
        self.assertIn(b'Homepage story 6', response.data)

    def test_homepage_editor_pick_filters_load_more_topics_and_newsletter(self):
        app.set_app_setting("site_settings", json.dumps({
            **app.DEFAULT_SITE_SETTINGS, "category": "tech",
        }))
        for index in range(10):
            created_at = f"2026-10-{index + 1:02d}T09:00:00+00:00"
            keyword = (
                "best productivity apps for remote work"
                if index % 2 == 0 else "how to secure your home wifi network"
            )
            app.save_article({
                "id": f"tech-home-story-{index}",
                "slug": f"tech-home-story-{index}",
                "status": "Published",
                "created_at": created_at,
                "published_at": created_at,
                "article_title": f"Tech homepage story {index}",
                "meta_title": f"Tech homepage story {index}",
                "meta_description": f"Useful tech ideas number {index}.",
                "article_html": "<p>Article body.</p>",
                "keyword": keyword,
                "niche": "tech",
            })

        with patch.dict("os.environ", {
            "NEWSLETTER_SMTP_HOST": "smtp.example.test",
            "NEWSLETTER_FROM_EMAIL": "newsletter@example.test",
            "PUBLIC_SITE_URL": "https://home.example.test",
        }):
            response = self.client.get("/")

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"EDITOR", response.data)
        self.assertIn(b'data-category-filter="Productivity and work"', response.data)
        self.assertIn(b'data-category-filter="Digital security"', response.data)
        self.assertIn(b'data-topic-filter="best productivity apps for remote work"', response.data)
        self.assertIn(b'data-load-more', response.data)
        self.assertIn(b'data-load-more-card', response.data)
        self.assertIn(b'id="newsletter"', response.data)
        self.assertIn(b'action="/newsletter/subscribe"', response.data)

    def test_editor_can_change_cover_on_draft_or_published_article(self):
        app.set_app_setting("site_settings", json.dumps({
            **app.DEFAULT_SITE_SETTINGS, "category": "tech",
        }))
        article = {
            "id": "cover-edit", "slug": "cover-edit", "status": "Published",
            "created_at": "2026-10-01T09:00:00+00:00",
            "article_title": "Published article", "meta_title": "Published article",
            "meta_description": "A published article.",
            "article_html": "<p>Article body.</p>", "keyword": "published article",
            "niche": "tech",
        }
        app.save_article(article)
        image_url = "https://images.unsplash.com/photo-1498050108023-c5249f4df085"
        response = self.client.post(
            "/articles/cover-edit",
            data=self.csrf(
                action="update_cover_image",
                cover_image_url=image_url,
                cover_image_alt="A laptop on a desk beside a plant",
            ),
        )
        self.assertEqual(response.status_code, 302)
        saved_article = next(item for item in app.load_articles() if item["id"] == "cover-edit")
        self.assertEqual(saved_article["cover_image_url"], image_url)
        self.assertEqual(saved_article["cover_image_alt"], "A laptop on a desk beside a plant")
        public_page = self.client.get("/blog/cover-edit")
        self.assertEqual(public_page.status_code, 200)
        self.assertIn(image_url.encode(), public_page.data)
        self.assertIn(b'alt="A laptop on a desk beside a plant"', public_page.data)

    def test_image_library_reports_cover_alt_text_status(self):
        app.set_app_setting("site_settings", json.dumps({
            **app.DEFAULT_SITE_SETTINGS, "category": "tech",
        }))
        base_article = {
            "slug": "image-audit", "status": "Draft",
            "created_at": "2026-10-01T09:00:00+00:00",
            "meta_title": "Image audit", "meta_description": "An image audit article.",
            "article_html": "<p>Article body.</p>", "keyword": "image audit", "niche": "tech",
        }
        app.save_article({**base_article, "id": "needs-alt", "article_title": "Needs alt text"})
        app.save_article({
            **base_article, "id": "has-alt", "slug": "has-alt",
            "article_title": "Has alt text", "cover_image_alt": "A close-up of a circuit board",
        })

        response = self.client.get("/images")

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"of 2 article covers need alt text", response.data)
        self.assertIn(b"Custom alt text missing", response.data)
        self.assertIn(b"Custom alt text added", response.data)

    def test_image_link_checker_reports_broken_local_and_external_references_without_changes(self):
        app.set_app_setting("site_settings", json.dumps({
            **app.DEFAULT_SITE_SETTINGS, "category": "tech",
        }))
        article = {
            "id": "link-check", "slug": "link-check", "status": "Published",
            "created_at": "2026-10-01T09:00:00+00:00",
            "article_title": "Link check article", "meta_title": "Link check article",
            "meta_description": "An article with good and bad links.",
            "article_html": (
                '<p><img src="/static/missing-check-image.png">'
                '<a href="/blog/removed-story">Removed story</a>'
                '<a href="https://broken.example/story">Broken external story</a>'
                '<img src="https://good.example/inline.webp"></p>'
            ),
            "keyword": "link checker", "niche": "tech",
            "cover_image_url": "https://good.example/cover.webp",
        }
        app.save_article(article)
        external_probe = lambda url: (
            {"status": "Broken", "detail": "HTTP 404"}
            if "broken.example" in url else {"status": "OK", "detail": "HTTP 200"}
        )

        with patch("app.probe_public_url", side_effect=external_probe):
            response = self.client.post(
                "/images/check",
                data=self.csrf(),
            )

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"LATEST SCAN", response.data)
        self.assertIn(b"removed-story", response.data)
        self.assertIn(b"Local file not found", response.data)
        self.assertIn(b"broken.example/story", response.data)
        self.assertIn(b"HTTP 404", response.data)
        self.assertIn(b"3 item(s) to review", response.data)
        saved_article = next(item for item in app.load_articles() if item["id"] == "link-check")
        self.assertEqual(saved_article["article_html"], article["article_html"])
        self.assertEqual(saved_article["cover_image_url"], article["cover_image_url"])

    def test_public_url_checker_never_connects_to_private_hosts(self):
        result = app.probe_public_url("http://127.0.0.1:5000/admin")
        self.assertEqual(result["status"], "Skipped")
        self.assertIn("Private and local", result["detail"])

    def test_cover_upload_is_resized_and_saved_as_webp(self):
        app.set_app_setting("site_settings", json.dumps({
            **app.DEFAULT_SITE_SETTINGS, "category": "tech",
        }))
        app.save_article({
            "id": "webp-cover", "slug": "webp-cover", "status": "Published",
            "created_at": "2026-10-01T09:00:00+00:00",
            "article_title": "WebP cover article", "meta_title": "WebP cover article",
            "meta_description": "An article with a compressed local cover.",
            "article_html": "<p>Article body.</p>", "keyword": "webp cover", "niche": "tech",
        })
        original = BytesIO()
        Image.new("RGB", (2400, 1200), "#38566d").save(original, format="PNG")
        upload_directory = Path(self.temp_dir.name) / "optimized"

        with patch("app.local_image_storage", return_value=("site", upload_directory)):
            response = self.client.post(
                "/articles/webp-cover",
                data={
                    **self.csrf(
                        action="update_cover_image",
                        cover_image_url="",
                        cover_image_alt="A blue laptop beside a window",
                    ),
                    "cover_image": (BytesIO(original.getvalue()), "cover.png"),
                },
                content_type="multipart/form-data",
            )

        self.assertEqual(response.status_code, 302)
        saved_article = next(item for item in app.load_articles() if item["id"] == "webp-cover")
        self.assertTrue(app.is_safe_local_image_url(saved_article["cover_image_url"]))
        self.assertEqual(saved_article["cover_image_alt"], "A blue laptop beside a window")
        image_path = upload_directory / f"{saved_article['cover_image_url'].rsplit('/', 1)[-1]}"
        with Image.open(image_path) as optimized:
            self.assertEqual(optimized.format, "WEBP")
            self.assertEqual(optimized.size, (1800, 900))
        self.assertLess(image_path.stat().st_size, len(original.getvalue()))
        with patch("app.local_image_storage", return_value=("site", upload_directory)):
            uploaded_response = self.client.get(saved_article["cover_image_url"])
            self.assertEqual(uploaded_response.status_code, 200)
            self.assertEqual(uploaded_response.mimetype, "image/webp")
            uploaded_payload = uploaded_response.data
            uploaded_response.close()
            self.assertEqual(uploaded_payload, image_path.read_bytes())
            self.assertEqual(self.client.get("/uploads/site/../secret.webp").status_code, 404)
        public_page = self.client.get("/blog/webp-cover")
        self.assertEqual(public_page.status_code, 200)
        self.assertIn(saved_article["cover_image_url"].encode(), public_page.data)
        self.assertIn(b'alt="A blue laptop beside a window"', public_page.data)

    def test_invalid_cover_upload_is_rejected(self):
        app.set_app_setting("site_settings", json.dumps({
            **app.DEFAULT_SITE_SETTINGS, "category": "tech",
        }))
        app.save_article({
            "id": "invalid-cover", "status": "Draft", "created_at": "2026-10-01T09:00:00+00:00",
            "article_title": "Invalid upload article", "meta_title": "Invalid upload article",
            "meta_description": "An article.", "article_html": "<p>Article body.</p>",
            "keyword": "invalid upload", "niche": "tech",
        })
        original_url = "https://images.unsplash.com/photo-1498050108023-c5249f4df085"
        app.save_article({
            **next(item for item in app.load_articles() if item["id"] == "invalid-cover"),
            "cover_image_url": original_url,
        })

        with patch("app.local_image_storage") as storage:
            response = self.client.post(
                "/articles/invalid-cover",
                data={
                    **self.csrf(action="update_cover_image", cover_image_alt="A desk"),
                    "cover_image": (BytesIO(b"not an image"), "broken.png"),
                },
                content_type="multipart/form-data",
            )

        self.assertEqual(response.status_code, 302)
        self.assertFalse(storage.called)
        saved_article = next(item for item in app.load_articles() if item["id"] == "invalid-cover")
        self.assertEqual(saved_article["cover_image_url"], original_url)

    def test_unsafe_custom_article_cover_falls_back_to_stock_image(self):
        image = app.article_cover_image({
            "niche": "tech", "cover_image_url": "javascript:alert(1)",
        })
        self.assertIn("images.unsplash.com/", image)
        self.assertTrue(image.startswith("https://"))

    def test_default_cover_photo_matches_the_article_niche(self):
        technology_cover = app.article_cover_image({"niche": "tech"})
        interiors_cover = app.article_cover_image({"niche": "home-decor"})
        self.assertIn("photo-1498050108023-c5249f4df085", technology_cover)
        self.assertIn("photo-1616486338812-3dadae4b4ace", interiors_cover)

    def test_public_blog_and_article_routes_are_isolated_by_site_profile(self):
        app.set_app_setting("site_settings", json.dumps({
            **app.DEFAULT_SITE_SETTINGS, "category": "tech",
        }))
        articles = [
            {
                "id": "tech-post", "slug": "tech-post", "status": "Published",
                "created_at": "2026-10-02T09:00:00+00:00",
                "article_title": "Practical laptop buying guide",
                "meta_title": "Practical laptop buying guide",
                "meta_description": "Technology advice for your next laptop.",
                "article_html": "<p>Technology article.</p>",
                "keyword": "laptop buying guide", "niche": "tech",
            },
            {
                "id": "second-tech-post", "slug": "second-tech-post", "status": "Published",
                "created_at": "2026-10-03T09:00:00+00:00",
                "article_title": "Small business cybersecurity basics",
                "meta_title": "Small business cybersecurity basics",
                "meta_description": "Technology advice for small businesses.",
                "article_html": "<p>Technology article.</p>",
                "keyword": "small business cybersecurity", "niche": "tech",
            },
            {
                "id": "home-post", "slug": "home-post", "status": "Published",
                "created_at": "2026-10-01T09:00:00+00:00",
                "article_title": "Small living room ideas",
                "meta_title": "Small living room ideas",
                "meta_description": "Interior ideas for small living rooms.",
                "article_html": "<p>Home decor article.</p>",
                "keyword": "small living room ideas", "niche": "home-decor",
            },
        ]
        for article in articles:
            app.save_article(article)

        journal = self.client.get("/blog")
        self.assertEqual(journal.status_code, 200)
        self.assertIn(b"Practical laptop buying guide", journal.data)
        self.assertNotIn(b"Small living room ideas", journal.data)
        self.assertIn(b"blog-feature-count-2", journal.data)
        self.assertIn(b"photo-1498050108023-c5249f4df085", journal.data)

        self.assertEqual(self.client.get("/blog/tech-post").status_code, 200)
        self.assertEqual(self.client.get("/blog/home-post").status_code, 404)
        self.assertIn(b"/blog/tech-post", self.client.get("/sitemap.xml").data)
        self.assertNotIn(b"/blog/home-post", self.client.get("/sitemap.xml").data)
        self.assertIn(b"Practical laptop buying guide", self.client.get("/feed.xml").data)
        self.assertNotIn(b"Small living room ideas", self.client.get("/feed.xml").data)

        dashboard = self.client.get("/dashboard")
        self.assertIn(b"Practical laptop buying guide", dashboard.data)
        self.assertNotIn(b"Small living room ideas", dashboard.data)

    def test_tech_blog_includes_published_tech_articles_from_the_other_workspace_database(self):
        app.set_app_setting("site_settings", json.dumps({
            **app.DEFAULT_SITE_SETTINGS, "category": "tech",
        }))
        app.save_article({
            "id": "local-tech", "slug": "local-tech", "status": "Published",
            "created_at": "2026-10-02T09:00:00+00:00",
            "article_title": "Existing tech story", "meta_title": "Existing tech story",
            "meta_description": "An existing tech story.", "article_html": "<p>Tech.</p>",
            "keyword": "existing tech story", "niche": "tech",
        })

        other_database = Path(self.temp_dir.name) / "other-profile.sqlite3"
        other_article = {
            "id": "workspace-tech", "slug": "new-tech-story", "status": "Published",
            "created_at": "2026-10-03T18:37:00+05:00",
            "published_at": "2026-10-03T18:37:00+05:00",
            "article_title": "New tech story published from the workspace",
            "meta_title": "New tech story published from the workspace",
            "meta_description": "A technology article published from the shared workspace.",
            "article_html": "<p>New tech article.</p>",
            "keyword": "new tech story", "niche": "tech",
        }
        other_connection = sqlite3.connect(other_database)
        try:
            other_connection.execute(
                "CREATE TABLE articles (id TEXT PRIMARY KEY, slug TEXT, status TEXT NOT NULL, "
                "created_at TEXT NOT NULL, payload TEXT NOT NULL)"
            )
            other_connection.execute(
                "INSERT INTO articles (id, slug, status, created_at, payload) VALUES (?, ?, ?, ?, ?)",
                (
                    other_article["id"], other_article["slug"], other_article["status"],
                    other_article["created_at"], json.dumps(other_article),
                ),
            )
            other_connection.commit()
        finally:
            other_connection.close()

        self.profile_paths_patch.stop()
        self.profile_paths_patch = patch(
            "app.profile_article_database_paths", return_value=[other_database],
        )
        self.profile_paths_patch.start()

        journal = self.client.get("/blog")
        self.assertEqual(journal.status_code, 200)
        self.assertIn(b"New tech story published from the workspace", journal.data)
        self.assertEqual(self.client.get("/blog/new-tech-story").status_code, 200)
        self.assertIn(b"/blog/new-tech-story", self.client.get("/sitemap.xml").data)
        self.assertIn(b"New tech story published from the workspace", self.client.get("/feed.xml").data)

    def test_site_manager_rejects_unsafe_navigation_targets(self):
        response = self.client.post("/site-manager", data=self.csrf(
            site_name="Studio North",
            site_description="A custom site description",
            site_tagline="Thoughtful publishing",
            site_eyebrow="STUDIO NORTH",
            category="interior design",
            headline="Ideas for calmer rooms",
            hero_image_url="",
            theme_primary="#123456",
            theme_background="#f0f0f0",
            navigation="Unsafe | javascript:alert(1)",
            newsletter_title="Monthly notes",
            newsletter_description="Useful ideas, once a month.",
        ))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(app.load_site_settings()["site_name"], app.SITE_NAME)

    def test_site_settings_are_separate_for_each_database(self):
        app.set_app_setting("site_settings", json.dumps({
            **app.DEFAULT_SITE_SETTINGS, "site_name": "Home profile",
        }))
        home_database = app.DATABASE_PATH
        app.DATABASE_PATH = Path(self.temp_dir.name) / "tech.sqlite3"
        app.initialize_database()
        self.assertEqual(app.load_site_settings()["site_name"], app.SITE_NAME)
        app.set_app_setting("site_settings", json.dumps({
            **app.DEFAULT_SITE_SETTINGS, "site_name": "Tech profile",
        }))
        app.DATABASE_PATH = home_database
        self.assertEqual(app.load_site_settings()["site_name"], "Home profile")

    def test_custom_pages_can_be_drafted_published_and_listed_in_sitemap(self):
        response = self.client.post("/admin/pages", data=self.csrf(
            title="Our Story",
            description="Meet our team and editorial mission.",
            content="A short story.\n<script>alert(1)</script>",
            status="Draft",
        ))
        self.assertEqual(response.status_code, 302)
        page = app.list_site_pages(include_drafts=True)[0]
        self.assertEqual(page["slug"], "our-story")
        self.assertEqual(self.client.get("/pages/our-story").status_code, 404)

        response = self.client.post(
            f"/admin/pages/{page['id']}",
            data=self.csrf(
                title="Our Story",
                description="Meet our team and editorial mission.",
                content="A short story.\n<script>alert(1)</script>",
                status="Published",
            ),
        )
        self.assertEqual(response.status_code, 302)
        public_page = self.client.get("/pages/our-story")
        self.assertEqual(public_page.status_code, 200)
        self.assertIn(b"Meet our team and editorial mission.", public_page.data)
        self.assertIn(b"&lt;script&gt;", public_page.data)
        self.assertIn(b"public-profile-home-decor", public_page.data)
        sitemap = self.client.get("/sitemap.xml")
        self.assertIn(b"/pages/our-story", sitemap.data)
        self.assertIn(b"<lastmod>", sitemap.data)

    def test_sitemap_adds_valid_article_lastmod_and_skips_bad_dates(self):
        for slug, updated_at in (
            ("dated-story", "2026-10-12T15:30:00+05:00"),
            ("invalid-date-story", "not-a-date"),
        ):
            app.save_article({
                "id": slug, "slug": slug, "status": "Published",
                "created_at": "2026-10-01T09:00:00+00:00",
                "updated_at": updated_at,
                "article_title": slug.replace("-", " ").title(),
                "meta_title": slug.replace("-", " ").title(),
                "meta_description": "A sitemap test article.",
                "article_html": "<p>Sitemap article body.</p>",
                "keyword": "sitemap test", "niche": "home-decor",
            })
        sitemap = self.client.get("/sitemap.xml")
        self.assertEqual(sitemap.status_code, 200)
        namespace = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
        root = ET.fromstring(sitemap.data)
        locations = {
            element.findtext("sm:loc", namespaces=namespace):
            element.findtext("sm:lastmod", namespaces=namespace)
            for element in root.findall("sm:url", namespace)
        }
        self.assertEqual(locations["http://127.0.0.1:5000/blog/dated-story"], "2026-10-12")
        self.assertIsNone(locations["http://127.0.0.1:5000/blog/invalid-date-story"])

    def test_newsletter_requires_consent_and_allows_removal(self):
        app.set_app_setting("site_settings", json.dumps({
            **app.DEFAULT_SITE_SETTINGS, "newsletter_enabled": True,
        }))
        rejected = self.client.post("/newsletter/subscribe", data=self.csrf(email="reader@example.com"))
        self.assertEqual(rejected.status_code, 302)
        connection = sqlite3.connect(app.DATABASE_PATH)
        try:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM newsletter_subscribers").fetchone()[0], 0)
        finally:
            connection.close()

        with patch.dict("os.environ", {
            "NEWSLETTER_SMTP_HOST": "smtp.example.test",
            "NEWSLETTER_FROM_EMAIL": "newsletter@example.test",
            "PUBLIC_SITE_URL": "https://home.example.test",
        }), patch("app.send_newsletter_email") as send_email:
            response = self.client.post("/newsletter/subscribe", data=self.csrf(
                email="reader@example.com", consent="on",
            ))
        self.assertEqual(response.status_code, 302)
        send_email.assert_called_once()
        connection = sqlite3.connect(app.DATABASE_PATH)
        try:
            subscriber = connection.execute(
                "SELECT email, subscribed_at, confirmed_at FROM newsletter_subscribers"
            ).fetchone()
        finally:
            connection.close()
        self.assertEqual(subscriber[0], "reader@example.com")
        self.assertIsNone(subscriber[2])
        datetime.fromisoformat(subscriber[1])
        self.assertIn(b"reader@example.com", self.client.get("/admin/newsletter").data)

        removed = self.client.post("/admin/newsletter/remove", data=self.csrf(email="reader@example.com"))
        self.assertEqual(removed.status_code, 302)
        connection = sqlite3.connect(app.DATABASE_PATH)
        try:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM newsletter_subscribers").fetchone()[0], 0)
        finally:
            connection.close()

    def test_newsletter_signup_is_available_on_journal_and_article_pages(self):
        app.set_app_setting("site_settings", json.dumps({
            **app.DEFAULT_SITE_SETTINGS, "newsletter_enabled": True,
        }))
        app.save_article({
            "id": "newsletter-article", "slug": "newsletter-article", "status": "Published",
            "created_at": "2026-10-01T09:00:00+00:00", "published_at": "2026-10-01T09:00:00+00:00",
            "article_title": "Newsletter story", "meta_title": "Newsletter story",
            "meta_description": "A story with newsletter signup.",
            "article_html": "<p>Article body.</p>", "keyword": "newsletter", "niche": "home-decor",
        })

        smtp_environment = {
            "NEWSLETTER_SMTP_HOST": "smtp.example.test",
            "NEWSLETTER_FROM_EMAIL": "newsletter@example.test",
            "PUBLIC_SITE_URL": "https://home.example.test",
        }
        with patch.dict("os.environ", smtp_environment):
            for path, return_to in (("/", "/"), ("/blog", "/blog"), (
                "/blog/newsletter-article", "/blog/newsletter-article",
            )):
                with self.subTest(path=path):
                    response = self.client.get(path)
                    self.assertEqual(response.status_code, 200)
                    self.assertIn(b'id="newsletter"', response.data)
                    self.assertIn(f'name="return_to" value="{return_to}"'.encode(), response.data)
                    self.assertIn(b"Confirm your email to receive", response.data)

        with patch.dict("os.environ", smtp_environment), patch("app.send_newsletter_email") as send_email:
            response = self.client.post("/newsletter/subscribe", data=self.csrf(
                email="reader@example.com", consent="on", return_to="/blog/newsletter-article",
            ))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers["Location"], "/blog/newsletter-article#newsletter")
        subscribed_page = self.client.get(response.headers["Location"])
        self.assertIn(b"Check your inbox for a confirmation link", subscribed_page.data)

        body = send_email.call_args.args[2]
        confirmation_url = body.split("within 24 hours by opening this link:\n\n", 1)[1].splitlines()[0]
        token = confirmation_url.rsplit("/", 1)[-1]
        confirmation_page = self.client.get(f"/newsletter/confirm/{token}")
        self.assertEqual(confirmation_page.status_code, 200)
        self.assertIn(b"Confirm your subscription", confirmation_page.data)
        confirmed = self.client.post(f"/newsletter/confirm/{token}", data=self.csrf())
        self.assertEqual(confirmed.status_code, 302)
        self.assertIn(b"Your subscription is confirmed", self.client.get(confirmed.headers["Location"]).data)

        connection = sqlite3.connect(app.DATABASE_PATH)
        try:
            confirmed_at = connection.execute(
                "SELECT confirmed_at FROM newsletter_subscribers WHERE email = ?",
                ("reader@example.com",),
            ).fetchone()[0]
        finally:
            connection.close()
        self.assertIsNotNone(confirmed_at)

        unsafe_redirect = self.client.post("/newsletter/subscribe", data=self.csrf(
            email="another@example.com", consent="on", return_to="//example.com",
        ))
        self.assertEqual(unsafe_redirect.headers["Location"], "/#newsletter")

    def test_newsletter_email_uses_configured_starttls_smtp(self):
        smtp_environment = {
            "NEWSLETTER_SMTP_HOST": "smtp.example.test",
            "NEWSLETTER_SMTP_PORT": "587",
            "NEWSLETTER_SMTP_SECURITY": "starttls",
            "NEWSLETTER_SMTP_USERNAME": "mailer@example.test",
            "NEWSLETTER_SMTP_PASSWORD": "test-password",
            "NEWSLETTER_FROM_EMAIL": "newsletter@example.test",
            "PUBLIC_SITE_URL": "https://home.example.test",
        }
        with patch.dict("os.environ", smtp_environment), patch("app.smtplib.SMTP") as smtp:
            server = smtp.return_value.__enter__.return_value
            app.send_newsletter_email(
                "reader@example.test", "New story", "Read the new story.",
                html_body="<p>Read the <strong>new story</strong>.</p>",
            )

        smtp.assert_called_once_with("smtp.example.test", 587, timeout=20)
        server.starttls.assert_called_once()
        server.login.assert_called_once_with("mailer@example.test", "test-password")
        message = server.send_message.call_args.args[0]
        self.assertEqual(message["To"], "reader@example.test")
        self.assertEqual(message["Subject"], "New story")
        self.assertIn("Read the new story.", message.get_body(preferencelist=("plain",)).get_content())
        self.assertIn(
            "new story",
            message.get_body(preferencelist=("html",)).get_content(),
        )

    def test_newsletter_email_uses_resend_api_when_configured(self):
        resend_environment = {
            "RESEND_API_KEY": "re_test_api_key",
            "NEWSLETTER_FROM_EMAIL": "newsletter@example.test",
            "PUBLIC_SITE_URL": "https://home.example.test",
            "NEWSLETTER_SMTP_HOST": "",
        }
        response = Mock()
        with patch.dict("os.environ", resend_environment), \
                patch("app.requests.post", return_value=response) as resend_request, \
                patch("app.smtplib.SMTP") as smtp:
            app.send_newsletter_email(
                "reader@example.test", "New story", "Read the new story.",
                html_body="<p>Read the <strong>new story</strong>.</p>",
            )

        resend_request.assert_called_once_with(
            "https://api.resend.com/emails",
            headers={"Authorization": "Bearer re_test_api_key"},
            json={
                "from": "Urban Nest Interiors <newsletter@example.test>",
                "to": ["reader@example.test"],
                "subject": "New story",
                "text": "Read the new story.",
                "html": "<p>Read the <strong>new story</strong>.</p>",
            },
            timeout=20,
        )
        response.raise_for_status.assert_called_once()
        smtp.assert_not_called()

    def test_resend_configuration_requires_sender_and_public_https_url(self):
        with patch.dict("os.environ", {
            "RESEND_API_KEY": "re_test_api_key",
            "NEWSLETTER_FROM_EMAIL": "newsletter@example.test",
            "PUBLIC_SITE_URL": "http://home.example.test",
            "NEWSLETTER_SMTP_HOST": "",
        }):
            self.assertFalse(app.newsletter_email_configured())

    def test_newsletter_signup_is_hidden_without_a_valid_mail_configuration(self):
        app.set_app_setting("site_settings", json.dumps({
            **app.DEFAULT_SITE_SETTINGS, "newsletter_enabled": True,
        }))
        with patch.dict("os.environ", {
            "NEWSLETTER_SMTP_HOST": "",
            "NEWSLETTER_FROM_EMAIL": "",
            "PUBLIC_SITE_URL": "",
        }):
            response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Email signup is temporarily unavailable", response.data)
        self.assertNotIn(b'action="/newsletter/subscribe"', response.data)

    def test_newsletter_confirmation_rate_limit_is_separate_from_article_submissions(self):
        email = "limited@example.test"
        self.assertTrue(app.reserve_submission_slot(email, purpose="newsletter"))
        self.assertTrue(app.reserve_submission_slot(email, purpose="newsletter"))
        self.assertTrue(app.reserve_submission_slot(email, purpose="newsletter"))
        self.assertFalse(app.reserve_submission_slot(email, purpose="newsletter"))
        self.assertTrue(app.reserve_submission_slot(email))

    def test_publishing_sends_one_email_to_confirmed_subscribers_with_unsubscribe(self):
        app.set_app_setting("site_settings", json.dumps({
            **app.DEFAULT_SITE_SETTINGS, "newsletter_enabled": True,
        }))
        app.save_article({
            "id": "publish-newsletter", "slug": "publish-newsletter", "status": "Draft",
            "created_at": "2026-10-01T09:00:00+00:00", "article_title": "A new article",
            "meta_title": "A new article", "meta_description": "New article description.",
            "article_html": "<p>New article body.</p>", "keyword": "new article", "niche": "home-decor",
        })
        connection = sqlite3.connect(app.DATABASE_PATH)
        try:
            connection.execute(
                "INSERT INTO newsletter_subscribers (email, subscribed_at, confirmed_at) VALUES (?, ?, ?)",
                ("confirmed@example.test", "2026-10-01T09:00+00:00", "2026-10-01T09:01+00:00"),
            )
            connection.execute(
                "INSERT INTO newsletter_subscribers (email, subscribed_at) VALUES (?, ?)",
                ("pending@example.test", "2026-10-01T09:00+00:00"),
            )
            connection.commit()
        finally:
            connection.close()

        with patch.dict("os.environ", {
            "NEWSLETTER_SMTP_HOST": "smtp.example.test",
            "NEWSLETTER_FROM_EMAIL": "newsletter@example.test",
            "PUBLIC_SITE_URL": "https://home.example.test",
        }), patch("app.send_newsletter_email") as send_email:
            response = self.client.post("/articles/publish-newsletter/publish", data=self.csrf())
            self.assertEqual(response.status_code, 302)
            self.assertIn(b"Newsletter sent to 1 confirmed subscriber", self.client.get(response.headers["Location"]).data)
            second_attempt = self.client.post("/articles/publish-newsletter/publish", data=self.csrf())
            self.assertEqual(second_attempt.status_code, 302)

        send_email.assert_called_once()
        email_body = send_email.call_args.args[2]
        self.assertIn("Read the article: https://home.example.test/blog/a-new-article", email_body)
        unsubscribe_line = next(line for line in email_body.splitlines() if "/newsletter/unsubscribe/" in line)
        unsubscribe_url = unsubscribe_line.split(": ", 1)[1]
        unsubscribe_path = urlparse(unsubscribe_url).path
        page = self.client.get(unsubscribe_path)
        self.assertEqual(page.status_code, 200)
        removed = self.client.post(unsubscribe_path, data=self.csrf())
        self.assertEqual(removed.status_code, 200)
        self.assertIn(b"You are unsubscribed", removed.data)

    def test_keyword_queue_persists_and_is_available_to_article_studio(self):
        response = self.client.post("/keywords", data=self.csrf(
            action="add", keyword="small entryway storage",
        ))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(app.queued_keywords(app.DEFAULT_SITE_SETTINGS["category"])[0]["keyword"], "small entryway storage")
        self.assertIn(b"small entryway storage", self.client.get("/keywords").data)
        self.assertIn(b"small entryway storage", self.client.get("/articles").data)


if __name__ == "__main__":
    unittest.main()
