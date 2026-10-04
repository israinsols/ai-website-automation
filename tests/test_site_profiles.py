import unittest

import app


class SiteProfileTests(unittest.TestCase):
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
