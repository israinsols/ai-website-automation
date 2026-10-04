import json
import sys

from app import run_autopilot_once


def main():
    try:
        result = run_autopilot_once()
    except Exception as exc:
        print(f"AUTOPILOT ERROR: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
