# Contributing

Thanks for helping improve HAFamilyLink. This project uses unofficial Google Family Link endpoints, so small, focused changes are easier to review and safer for users.

## Before You Start

- Search existing issues and pull requests first.
- Do not post Google credentials, Family Link cookies, Home Assistant tokens, API keys, session files, or other secrets.
- Report security issues privately. See `SECURITY.md`.
- Keep changes focused. Avoid mixing behavior changes, formatting, dependency bumps, and documentation cleanup in one pull request.

## Local Development

Create a virtual environment and install the development dependencies:

```bash
python -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
```

Run the test suite:

```bash
.venv/bin/python -m pytest
```

Useful checks before opening a pull request:

```bash
.venv/bin/python -m pytest --cov=custom_components.familylink --cov-report=term-missing --cov-report=xml
.venv/bin/python -m ruff check .
.venv/bin/python -m compileall -q custom_components/familylink familylink-playwright/app tests
git diff --check
```

If you use pre-commit:

```bash
PRE_COMMIT_HOME=/private/tmp/hafamilylink-pre-commit-cache .venv/bin/python -m pre_commit run --all-files
```

## Pull Requests

Please include:

- A short summary of the change.
- The validation you ran.
- Screenshots or entity examples for user-facing changes when useful.
- Notes about compatibility, migration, or follow-up work.

Keep pull requests reviewable. Prefer one clear change over a grab bag.

## Bug Reports

Good bug reports include:

- Home Assistant version.
- Integration version or commit.
- Installation method.
- Authentication setup, such as add-on or standalone auth container.
- Steps to reproduce.
- Relevant logs with secrets removed.

## Feature Requests

Describe the real use case first, then the requested behavior. For Family Link behavior, note whether you have confirmed it in the Google Family Link app or web UI.
