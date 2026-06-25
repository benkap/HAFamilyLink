#!/usr/bin/env python3
"""Container healthcheck for the Family Link auth service."""

import sys
from urllib.request import urlopen


HEALTH_URL = "http://127.0.0.1:8099/api/health"


def main() -> int:
    try:
        with urlopen(HEALTH_URL, timeout=5) as response:
            return 0 if 200 <= response.status < 300 else 1
    except Exception as err:
        print(f"Healthcheck failed: {err}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
