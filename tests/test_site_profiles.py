import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import app


class SiteProfileTests(unittest.TestCase):
    def test_site_overview_summarizes_configured_profiles_without_exposing_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            data = root / "data"
            data.mkdir()
            home_database = data / "home.sqlite3"
            tech_database = data / "tech.sqlite3"
            self.create_profile_database(home_database, "Home Publication", {"Draft": 2, "Published": 1})
            self.create_profile_database(tech_database, "Tech Publication", {"Pending Review": 1})
            (root / ".env").write_text(
                "DATABASE_PATH=data/home.sqlite3\nSITE_NAME=Home profile\nPORT=5000\n",
                encoding="utf-8",
            )
            (root / ".env.tech").write_text(
                "DATABASE_PATH=data/tech.sqlite3\nSITE_NAME=Tech profile\nPORT=5001\n",
                encoding="utf-8",
            )

            with patch.object(app, "ROOT", root), \
                    patch.object(app, "DATABASE_PATH", home_database), \
                    patch.object(app, "APP_PORT", 5000):
                profiles = app.configured_site_profiles()
                self.assertEqual([profile["site_name"] for profile in profiles], [
                    "Home Publication",
                    "Tech Publication",
                ])
                self.assertEqual(profiles[0]["article_count"], 3)
                self.assertEqual(profiles[0]["draft_count"], 2)
                self.assertEqual(profiles[0]["published_count"], 1)
                self.assertEqual(profiles[1]["pending_count"], 1)
                self.assertTrue(all(profile["initialized"] for profile in profiles))

                client = app.app.test_client()
                with client.session_transaction() as session:
                    session["admin_authenticated"] = True
                    session["admin_username"] = "admin"
                with patch.object(app, "current_admin_account", return_value=None):
                    response = client.get("/sites")

            self.assertEqual(response.status_code, 200)
            self.assertIn(b"Home Publication", response.data)
            self.assertIn(b"Tech Publication", response.data)
            self.assertIn(b"http://127.0.0.1:5001/", response.data)
            self.assertNotIn(b"home.sqlite3", response.data)

    @staticmethod
    def create_profile_database(database_path, site_name, statuses):
        connection = sqlite3.connect(database_path)
        try:
            with connection:
                connection.execute(
                    "CREATE TABLE articles (id TEXT PRIMARY KEY, slug TEXT, status TEXT, created_at TEXT, payload TEXT)"
                )
                connection.execute("CREATE TABLE app_meta (key TEXT PRIMARY KEY, value TEXT)")
                connection.execute(
                    "INSERT INTO app_meta (key, value) VALUES ('site_settings', ?)",
                    (json.dumps({"site_name": site_name}),),
                )
                for index, (status, count) in enumerate(statuses.items()):
                    for item_index in range(count):
                        connection.execute(
                            "INSERT INTO articles (id, status, payload) VALUES (?, ?, '{}')",
                            (f"{index}-{item_index}", status),
                        )
        finally:
            connection.close()

    def test_home_decor_and_tech_keyword_banks_are_separate(self):
        home_decor = app.seed_keywords("home-decor")
        tech = app.seed_keywords("tech")
        self.assertTrue(home_decor)
        self.assertTrue(tech)
        self.assertIn("small living room decor ideas", home_decor)
        self.assertIn("best productivity apps for remote work", tech)
        self.assertNotEqual(set(home_decor), set(tech))

    def test_tech_topic_clusters_are_niche_specific(self):
        clusters = app.build_topic_clusters("tech", [])
        names = {cluster["name"] for cluster in clusters}
        self.assertIn("Productivity and work", names)
        self.assertIn("Digital security", names)
        self.assertNotIn("Small-space living", names)


if __name__ == "__main__":
    unittest.main()
