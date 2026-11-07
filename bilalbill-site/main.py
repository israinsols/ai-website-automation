"""Command-line orchestration for the bilalbill static blog."""

from __future__ import annotations

import argparse
import logging
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Callable

import frontmatter

import db
from builder import build_site
from config import SiteConfig, load_config
from db import connect, initialize, now_iso, save_article
from generator import generate_article
from indexing import run_indexing
from keywords import research_keywords
from report import report_summary, run_weekly_report
from social import share_published

LOGGER = logging.getLogger("bilalbill")


def _record_run(config: SiteConfig, command: str, action: Callable[[], object]) -> bool:
    initialize(config.database_path)
    with connect(config.database_path) as connection:
        cursor = connection.execute(
            "INSERT INTO runs(command, status, started_at) VALUES (?, 'running', ?)",
            (command, now_iso()),
        )
        run_id = int(cursor.lastrowid)
    try:
        result = action()
        details = str(result)[:2000]
        with connect(config.database_path) as connection:
            connection.execute(
                "UPDATE runs SET status = 'success', details = ?, finished_at = ? WHERE id = ?",
                (details, now_iso(), run_id),
            )
        LOGGER.info("%s completed: %s", command, details)
        return True
    except Exception as exc:
        LOGGER.exception("%s failed: %s", command, exc)
        with connect(config.database_path) as connection:
            connection.execute(
                "UPDATE runs SET status = 'failed', details = ?, finished_at = ? WHERE id = ?",
                (str(exc)[:2000], now_iso(), run_id),
            )
        return False


def _generate(config: SiteConfig) -> list[str]:
    created = []
    failures = []
    for _ in range(config.posts_per_day):
        try:
            created.append(str(generate_article(config).relative_to(config.root)))
        except Exception as exc:
            failures.append(str(exc))
            LOGGER.exception("Article generation failed.")
    if failures:
        raise RuntimeError(
            f"Created {len(created)} draft(s); {len(failures)} generation attempt(s) failed: "
            + "; ".join(failures)
        )
    return created


def _reviewed_posts(config: SiteConfig) -> list[tuple[Path, frontmatter.Post]]:
    result = []
    for path in sorted(config.posts_dir.glob("*.md")):
        post = frontmatter.load(path)
        if post.get("status") == "draft" and post.get("reviewed") is True:
            result.append((path, post))
    return result


def _publish(config: SiteConfig, slug: str | None, all_reviewed: bool) -> list[str]:
    if bool(slug) == all_reviewed:
        raise ValueError("Use `publish <slug>` or `publish --all-reviewed`, but not both.")
    if all_reviewed:
        candidates = _reviewed_posts(config)
    else:
        target_slug = slug or ""
        if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", target_slug):
            raise ValueError("Slug may contain only letters, digits, and hyphens.")
        path = config.posts_dir / f"{target_slug}.md"
        if not path.is_file():
            raise FileNotFoundError(f"Draft not found: {path}")
        candidates = [(path, frontmatter.load(path))]
    if not candidates:
        raise ValueError("No matching reviewed drafts were found.")

    published = []
    for path, post in candidates:
        if post.get("status") != "draft":
            raise ValueError(f"Refusing to publish non-draft article: {path.name}")
        if all_reviewed and post.get("reviewed") is not True:
            continue
        post["status"] = "published"
        post["reviewed"] = True
        post["date"] = str(post.get("date") or now_iso()[:10])
        path.write_text(frontmatter.dumps(post), encoding="utf-8")
        post_slug = str(post.get("slug", path.stem))
        db.save_article(
            config.database_path,
            post_slug,
            str(post.get("keyword", "")),
            str(post["title"]),
            "published",
            str(path.relative_to(config.root)),
            str(post["date"]),
        )
        published.append(post_slug)
    return published


def _deploy(config: SiteConfig) -> str:
    gh = shutil.which("gh")
    if not gh:
        raise RuntimeError("GitHub CLI `gh` is required. Deploy with the GitHub Actions tab instead.")
    workflow_path = config.root.parent / ".github" / "workflows" / "daily.yml"
    if not workflow_path.is_file():
        raise FileNotFoundError(f"GitHub Actions workflow not found: {workflow_path}")
    result = subprocess.run(
        [gh, "workflow", "run", "daily.yml"],
        cwd=config.root,
        check=True,
        capture_output=True,
        text=True,
        timeout=60,
    )
    return result.stdout.strip() or "Workflow dispatch requested."


def _report(config: SiteConfig) -> str:
    destination, rows = run_weekly_report(config)
    return report_summary(destination, rows)


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Research keywords, create reviewed drafts, and build bilalbill as static HTML."
    )
    parser.add_argument("command", nargs="?", choices=["publish"])
    parser.add_argument("slug", nargs="?")
    parser.add_argument("--all-reviewed", action="store_true", help="Publish drafts marked reviewed: true.")
    parser.add_argument("--research", action="store_true", help="Discover keyword ideas.")
    parser.add_argument("--generate", action="store_true", help="Generate article draft(s) with Gemini.")
    parser.add_argument("--build", action="store_true", help="Build public/ from published content only.")
    parser.add_argument("--deploy", action="store_true", help="Trigger the GitHub Pages workflow with gh.")
    parser.add_argument("--share", action="store_true", help="Share published posts on enabled social platforms.")
    parser.add_argument("--report", action="store_true", help="Create a Search Console report and keyword priorities.")
    parser.add_argument("--index", action="store_true", help="Notify IndexNow and submit the live sitemap.")
    parser.add_argument("--all", action="store_true", help="Run research, generation, and build.")
    parser.add_argument("--dry-run", action="store_true", help="Print intended work without network calls or writes.")
    return parser.parse_args(argv)


def _dry_run(config: SiteConfig, args: argparse.Namespace) -> int:
    actions = []
    if args.all:
        actions.extend(
            [
                f"research {len(config.keyword_seeds)} seed(s) with polite Autosuggest requests",
                f"generate up to {config.posts_per_day} Gemini draft(s) "
                f"(AUTO_PUBLISH={config.auto_publish})",
                "build static pages from published content only",
            ]
        )
    else:
        actions.extend(
            name
            for enabled, name in (
                (args.research, "research keyword suggestions"),
                (args.generate, f"generate up to {config.posts_per_day} article draft(s)"),
                (args.build, "build static site"),
                (args.deploy, "dispatch GitHub Pages workflow"),
                (args.share, "share published posts on enabled social platforms"),
                (args.report, "fetch and save Search Console report"),
                (args.index, "notify IndexNow and submit sitemap"),
            )
            if enabled
        )
    if args.command == "publish":
        actions.append(
            "publish drafts marked reviewed: true"
            if args.all_reviewed
            else f"publish draft slug {args.slug!r}"
        )
    if not actions:
        print("No action selected. Try --all --dry-run or `publish <slug>`.")
        return 0
    print("DRY RUN — no network calls or files/database changes.")
    for action in actions:
        print(f"- Would {action}.")
    published_count = sum(
        1
        for path in config.posts_dir.glob("*.md")
        if frontmatter.load(path).get("status") == "published"
    )
    print(f"- Published markdown files available: {published_count}.")
    return 0


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    args = _parse_args(argv)
    config = load_config()
    if args.all_reviewed and args.command != "publish":
        raise ValueError("--all-reviewed is only valid with the publish command.")
    if args.command == "publish" and not args.slug and not args.all_reviewed:
        raise ValueError("Use `publish <slug>` or `publish --all-reviewed`.")
    if args.command == "publish" and any(
        (args.research, args.generate, args.build, args.deploy, args.share, args.report, args.index, args.all)
    ):
        raise ValueError("The publish command cannot be combined with pipeline flags.")
    if args.dry_run:
        return _dry_run(config, args)
    if args.command == "publish":
        return 0 if _record_run(
            config, "publish", lambda: _publish(config, args.slug, args.all_reviewed)
        ) else 1
    if args.command and not any(
        (args.research, args.generate, args.build, args.deploy, args.share, args.report, args.index, args.all)
    ):
        raise ValueError(f"Unexpected command: {args.command}")
    if args.all:
        steps = [
            ("research", lambda: research_keywords(config)),
            ("generate", lambda: _generate(config)),
            ("build", lambda: build_site(config)),
        ]
    else:
        steps = []
        if args.research:
            steps.append(("research", lambda: research_keywords(config)))
        if args.generate:
            steps.append(("generate", lambda: _generate(config)))
        if args.build:
            steps.append(("build", lambda: build_site(config)))
        if args.deploy:
            steps.append(("deploy", lambda: _deploy(config)))
        if args.share:
            steps.append(("share", lambda: share_published(config)))
        if args.report:
            steps.append(("report", lambda: _report(config)))
        if args.index:
            steps.append(("index", lambda: run_indexing(config)))
    if not steps:
        _parse_args(["--help"])
        return 0
    success = True
    for name, action in steps:
        success = _record_run(config, name, action) and success
    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
