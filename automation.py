import argparse
import json
import sys

from app import run_autopilot_once, run_due_scheduled_publications, sync_search_console_data


def main():
    try:
        parser = argparse.ArgumentParser()
        parser.add_argument(
            "--scheduled-publications",
            action="store_true",
            help="Publish individually approved articles whose local publication time is due.",
        )
        parser.add_argument(
            "--search-console-sync",
            action="store_true",
            help="Sync Google Search Console metrics without running the daily publishing flow.",
        )
        args = parser.parse_args()
        if args.search_console_sync:
            result = sync_search_console_data()
            print(json.dumps({"search_console": result}, ensure_ascii=False))
            return 0
        if args.scheduled_publications:
            scheduled = run_due_scheduled_publications()
            print(json.dumps({"scheduled_publications": scheduled}, ensure_ascii=False))
            return 1 if scheduled["failed"] else 0
        try:
            search_console = sync_search_console_data()
        except (RuntimeError, OSError, ValueError) as exc:
            print(f"SEARCH CONSOLE SYNC ERROR: {exc}", file=sys.stderr)
            search_console = {"status": "failed", "error": str(exc)}
        scheduled = run_due_scheduled_publications()
        autopilot = run_autopilot_once()
    except Exception as exc:
        print(f"AUTOPILOT ERROR: {exc}", file=sys.stderr)
        return 1
    print(json.dumps({
        "search_console": search_console,
        "scheduled_publications": scheduled,
        "autopilot": autopilot,
    }, ensure_ascii=False))
    return 1 if scheduled["failed"] or search_console["status"] == "failed" else 0


if __name__ == "__main__":
    raise SystemExit(main())
