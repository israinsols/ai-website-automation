import json
import sqlite3
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import app


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
        self.assertIn(b'class="home-footer-main"', home_page.data)
        self.assertIn("© 2026".encode(), home_page.data)

        journal = self.client.get("/blog")
        self.assertEqual(journal.status_code, 200)
        self.assertIn(b"class=\"journal-masthead\"", journal.data)
        self.assertIn(b"Urban Nest Interiors Journal", journal.data)
        self.assertIn(b"class=\"magazine-opening\"", journal.data)
        self.assertIn(b"blog-feature-grid", journal.data)
        self.assertIn(b"blog-feature-count-1", journal.data)
        self.assertNotIn(b"FEATURED STORY", journal.data)
        self.assertIn(b'src="https://images.unsplash.com/photo-', journal.data)

        article_page = self.client.get("/blog/image-post")
        self.assertEqual(article_page.status_code, 200)
        self.assertIn(b'class="article-magazine"', article_page.data)
        self.assertIn(b"NEW POST", article_page.data)
        self.assertIn(b"On the blog", article_page.data)
        self.assertIn(b'class="article-photo-collage"', article_page.data)
        self.assertGreaterEqual(article_page.data.count(b'<img src="https://images.unsplash.com/photo-'), 4)
        self.assertEqual(article_page.data.count(b'loading="eager"'), 4)
        self.assertIn(b"Article body.", article_page.data)
        self.assertIn(b'property="og:image"', article_page.data)
        self.assertIn(b'name="twitter:card" content="summary_large_image"', article_page.data)

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
            data=self.csrf(action="update_cover_image", cover_image_url=image_url),
        )
        self.assertEqual(response.status_code, 302)
        saved_article = next(item for item in app.load_articles() if item["id"] == "cover-edit")
        self.assertEqual(saved_article["cover_image_url"], image_url)
        public_page = self.client.get("/blog/cover-edit")
        self.assertEqual(public_page.status_code, 200)
        self.assertIn(image_url.encode(), public_page.data)

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

        response = self.client.post("/newsletter/subscribe", data=self.csrf(
            email="reader@example.com", consent="on",
        ))
        self.assertEqual(response.status_code, 302)
        connection = sqlite3.connect(app.DATABASE_PATH)
        try:
            subscribers = connection.execute(
                "SELECT email, subscribed_at FROM newsletter_subscribers"
            ).fetchall()
        finally:
            connection.close()
        self.assertEqual(subscribers[0][0], "reader@example.com")
        datetime.fromisoformat(subscribers[0][1])
        self.assertIn(b"reader@example.com", self.client.get("/admin/newsletter").data)

        removed = self.client.post("/admin/newsletter/remove", data=self.csrf(email="reader@example.com"))
        self.assertEqual(removed.status_code, 302)
        connection = sqlite3.connect(app.DATABASE_PATH)
        try:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM newsletter_subscribers").fetchone()[0], 0)
        finally:
            connection.close()

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
