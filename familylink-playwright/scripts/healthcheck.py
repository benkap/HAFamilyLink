#!/usr/bin/env python3
"""Container healthcheck for the Family Link auth service."""

import sys
from http.client import HTTPConnection


HEALTH_HOST = "127.0.0.1"
HEALTH_PORT = 8099
HEALTH_PATH = "/api/health"


def main() -> int:
    connection: HTTPConnection | None = None
    try:
        connection = HTTPConnection(HEALTH_HOST, HEALTH_PORT, timeout=5)
        connection.request("GET", HEALTH_PATH)
        response = connection.getresponse()
        return 0 if 200 <= response.status < 300 else 1
    except Exception as err:
        print(f"Healthcheck failed: {err}", file=sys.stderr)
        return 1
    finally:
        if connection is not None:
            connection.close()


if __name__ == "__main__":
    raise SystemExit(main())
