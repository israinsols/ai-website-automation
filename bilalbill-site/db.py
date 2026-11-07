"""SQLite persistence for keyword research, articles, social posts, and runs."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator


@contextmanager
def connect(path: Path) -> Iterator[sqlite3.Connection]:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=30)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA foreign_keys=ON")
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def initialize(path: Path) -> None:
    with connect(path) as db:
        db.executescript(
            """
            CREATE TABLE IF NOT EXISTS keywords (
                id INTEGER PRIMARY KEY,
                keyword TEXT NOT NULL UNIQUE,
                normalized TEXT NOT NULL UNIQUE,
                source TEXT NOT NULL,
                score REAL NOT NULL DEFAULT 0,
                priority INTEGER NOT NULL DEFAULT 0,
                used_at TEXT,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS articles (
                slug TEXT PRIMARY KEY,
                keyword TEXT NOT NULL,
                title TEXT NOT NULL,
                status TEXT NOT NULL CHECK(status IN ('draft', 'published')),
                file_path TEXT NOT NULL,
                published_at TEXT,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS social_posts (
                slug TEXT NOT NULL,
                platform TEXT NOT NULL,
                status TEXT NOT NULL CHECK(status IN ('sending', 'published', 'failed')),
                remote_id TEXT,
                error TEXT,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (slug, platform)
            );
            CREATE TABLE IF NOT EXISTS runs (
                id INTEGER PRIMARY KEY,
                command TEXT NOT NULL,
                status TEXT NOT NULL,
                details TEXT NOT NULL DEFAULT '',
                started_at TEXT NOT NULL,
                finished_at TEXT
            );
            """
        )


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def save_keyword(
    path: Path,
    keyword: str,
    normalized: str,
    source: str,
    score: float,
    priority: int = 0,
) -> None:
    with connect(path) as db:
        db.execute(
            """
            INSERT INTO keywords(keyword, normalized, source, score, priority, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(normalized) DO UPDATE SET
                score = MAX(keywords.score, excluded.score),
                priority = MAX(keywords.priority, excluded.priority)
            """,
            (keyword, normalized, source, score, priority, now_iso()),
        )


def next_keyword(path: Path) -> sqlite3.Row | None:
    with connect(path) as db:
        return db.execute(
            """
            SELECT * FROM keywords
            ORDER BY priority DESC, score DESC, used_at ASC, id ASC
            LIMIT 1
            """
        ).fetchone()


def mark_keyword_used(path: Path, keyword_id: int) -> None:
    with connect(path) as db:
        db.execute(
            "UPDATE keywords SET used_at = ? WHERE id = ?", (now_iso(), keyword_id)
        )


def save_article(
    path: Path,
    slug: str,
    keyword: str,
    title: str,
    status: str,
    file_path: str,
    published_at: str | None = None,
) -> None:
    with connect(path) as db:
        db.execute(
            """
            INSERT INTO articles(slug, keyword, title, status, file_path, published_at, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(slug) DO UPDATE SET
                keyword = excluded.keyword, title = excluded.title,
                status = excluded.status, file_path = excluded.file_path,
                published_at = excluded.published_at
            """,
            (slug, keyword, title, status, file_path, published_at, now_iso()),
        )


def get_published_articles(path: Path) -> list[sqlite3.Row]:
    with connect(path) as db:
        return list(
            db.execute(
                "SELECT * FROM articles WHERE status = 'published' ORDER BY published_at DESC"
            )
        )


def reserve_social_post(path: Path, slug: str, platform: str) -> bool:
    """Atomically reserve a post; already-sent or in-flight posts are not duplicated."""
    with connect(path) as db:
        cursor = db.execute(
            """
            INSERT INTO social_posts(slug, platform, status, updated_at)
            VALUES (?, ?, 'sending', ?)
            ON CONFLICT(slug, platform) DO UPDATE SET
                status = 'sending', error = NULL, updated_at = excluded.updated_at
            WHERE social_posts.status = 'failed'
            """,
            (slug, platform, now_iso()),
        )
        return cursor.rowcount == 1


def finish_social_post(
    path: Path,
    slug: str,
    platform: str,
    status: str,
    remote_id: str | None = None,
    error: str | None = None,
) -> None:
    if status not in {"published", "failed"}:
        raise ValueError(f"Unsupported social post status: {status}")
    with connect(path) as db:
        db.execute(
            """
            UPDATE social_posts SET status = ?, remote_id = ?, error = ?, updated_at = ?
            WHERE slug = ? AND platform = ?
            """,
            (status, remote_id, error, now_iso(), slug, platform),
        )
