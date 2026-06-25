#!/usr/bin/env python3
"""Check that generated version strings match their source files."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SEMVER = re.compile(r"^\d+\.\d+\.\d+$")

INTEGRATION_MANIFEST = "custom_components/familylink/manifest.json"
AUTH_CONFIG = "familylink-playwright/config.json"
AUTH_PACKAGE = "familylink-playwright/app/__init__.py"
AUTH_APP = "familylink-playwright/app/main.py"
ADDON_DOCKERFILE = "familylink-playwright/Dockerfile"
STANDALONE_DOCKERFILE = "familylink-playwright/Dockerfile.standalone"
AUTH_README = "familylink-playwright/README.md"


def read_text(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def read_json(path: str) -> dict[str, object]:
    return json.loads(read_text(path))


def match(path: str, pattern: str) -> str | None:
    found = re.search(pattern, read_text(path), flags=re.MULTILINE)
    return found.group(1) if found else None


def main() -> int:
    errors: list[str] = []

    integration_version = read_json(INTEGRATION_MANIFEST).get("version")
    auth_version = read_json(AUTH_CONFIG).get("version")

    for name, version in (
        ("integration manifest", integration_version),
        ("auth add-on config", auth_version),
    ):
        if not isinstance(version, str) or not SEMVER.fullmatch(version):
            errors.append(f"{name} version is not semantic X.Y.Z: {version!r}")

    auth_checks = {
        "auth package __version__": match(
            AUTH_PACKAGE,
            r'^__version__ = "([^"]+)"$',
        ),
        "add-on Docker label": match(
            ADDON_DOCKERFILE,
            r'io\.hass\.version="([^"]+)"',
        ),
        "standalone Docker label": match(
            STANDALONE_DOCKERFILE,
            r'org\.opencontainers\.image\.version="([^"]+)"',
        ),
        "auth README badge": match(
            AUTH_README,
            r"badge/version-(\d+\.\d+\.\d+)-blue",
        ),
    }

    for label, version in auth_checks.items():
        if version != auth_version:
            errors.append(f"{label} is {version!r}; expected {auth_version!r}")

    app_main = read_text(AUTH_APP)
    for expected in (
        "version=__version__",
        '"version": __version__',
        "Starting Family Link Auth Service v%s",
    ):
        if expected not in app_main:
            errors.append(f"{AUTH_APP} is not using __version__: {expected}")

    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1

    print(f"Integration version: {integration_version}")
    print(f"Auth service version: {auth_version}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
