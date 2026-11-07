import frontmatter

import social
from config import SiteConfig


class MockResponse:
    def raise_for_status(self):
        return None

    def json(self):
        return {"ok": True, "result": {"message_id": 42}}


class MockSession:
    def __init__(self):
        self.posts = []

    def post(self, url, **kwargs):
        self.posts.append((url, kwargs))
        return MockResponse()


def test_social_posts_are_sent_once_per_published_slug(tmp_path, monkeypatch):
    config = SiteConfig(
        root=tmp_path,
        site_name="bilalbill",
        domain="bilalbill.com",
        base_path="",
        niche="technology",
        posts_per_day=1,
        language="en-PK",
        author="Bilal",
        auto_publish=False,
        social_telegram=True,
        social_facebook=False,
        social_pinterest=False,
        keyword_seeds=("bilalbill",),
        contact_email="hello@bilalbill.com",
        gsc_site_url="sc-domain:bilalbill.com",
    )
    config.posts_dir.mkdir(parents=True)
    post = frontmatter.Post(
        "Helpful article.",
        title="Published article",
        slug="published-article",
        meta_description="A useful summary.",
        status="published",
    )
    (config.posts_dir / "published-article.md").write_text(
        frontmatter.dumps(post), encoding="utf-8"
    )
    monkeypatch.setattr(social, "_caption", lambda *args: "A useful caption.")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-token")
    monkeypatch.setenv("TELEGRAM_CHANNEL_ID", "@test-channel")
    session = MockSession()

    first = social.share_published(config, session=session)
    second = social.share_published(config, session=session)

    assert first["telegram"] == 1
    assert second["telegram"] == 0
    assert len(session.posts) == 1
    assert "sendMessage" in session.posts[0][0]
