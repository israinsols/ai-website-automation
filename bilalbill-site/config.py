"""Site configuration loaded from environment variables and an optional .env file."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent


def _bool_env(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name} must be a boolean value (true/false).")


@dataclass(frozen=True)
class SiteConfig:
    root: Path
    site_name: str
    domain: str
    base_path: str
    niche: str
    posts_per_day: int
    language: str
    author: str
    auto_publish: bool
    social_telegram: bool
    social_facebook: bool
    social_pinterest: bool
    keyword_seeds: tuple[str, ...]
    contact_email: str
    gsc_site_url: str

    @property
    def base_url(self) -> str:
        return f"https://{self.domain.strip().strip('/')}"

    @property
    def database_path(self) -> Path:
        return self.root / "data" / "bilalbill.sqlite3"

    @property
    def posts_dir(self) -> Path:
        return self.root / "content" / "posts"

    @property
    def pages_dir(self) -> Path:
        return self.root / "content" / "pages"

    @property
    def public_dir(self) -> Path:
        return self.root / "public"


def load_config(root: Path | None = None) -> SiteConfig:
    """Load configuration without exposing secrets in source-controlled files."""
    project_root = (root or ROOT).resolve()
    load_dotenv(project_root / ".env")
    domain = os.getenv("SITE_DOMAIN", "bilalbill.com").strip().lower().rstrip(".")
    if not re.fullmatch(
        r"(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}",
        domain,
    ):
        raise ValueError("SITE_DOMAIN must be a hostname such as bilalbill.com, without a scheme.")
    seeds = tuple(
        item.strip()
        for item in os.getenv(
            "KEYWORD_SEEDS", "bilalbill,technology Pakistan,tech guides Pakistan"
        ).split(",")
        if item.strip()
    )
    try:
        posts_per_day = int(os.getenv("POSTS_PER_DAY", "1"))
    except ValueError as exc:
        raise ValueError("POSTS_PER_DAY must be an integer from 1 to 5.") from exc
    if not 1 <= posts_per_day <= 5:
        raise ValueError("POSTS_PER_DAY must be an integer from 1 to 5.")
    if not seeds:
        raise ValueError("KEYWORD_SEEDS must contain at least one comma-separated seed.")

    base_path = os.getenv("SITE_BASE_PATH", "").strip()
    if base_path and (
        not base_path.startswith("/")
        or base_path.startswith("//")
        or "?" in base_path
        or "#" in base_path
        or "\\" in base_path
    ):
        raise ValueError("SITE_BASE_PATH must be an absolute URL path such as /repo-name.")
    base_path = base_path.rstrip("/")
    if base_path and any(part in {".", ".."} for part in base_path.split("/")):
        raise ValueError("SITE_BASE_PATH cannot contain dot path segments.")

    return SiteConfig(
        root=project_root,
        site_name=os.getenv("SITE_NAME", "bilalbill").strip(),
        domain=domain,
        base_path=base_path,
        niche=os.getenv("SITE_NICHE", "technology").strip(),
        posts_per_day=posts_per_day,
        language=os.getenv("SITE_LANGUAGE", "en-PK").strip(),
        author=os.getenv("SITE_AUTHOR", "Bilal").strip(),
        auto_publish=_bool_env("AUTO_PUBLISH", False),
        social_telegram=_bool_env("SOCIAL_TELEGRAM", False),
        social_facebook=_bool_env("SOCIAL_FACEBOOK", False),
        social_pinterest=_bool_env("SOCIAL_PINTEREST", False),
        keyword_seeds=seeds,
        contact_email=os.getenv("CONTACT_EMAIL", f"hello@{domain}").strip(),
        gsc_site_url=os.getenv("GSC_SITE_URL", f"sc-domain:{domain}").strip(),
    )
