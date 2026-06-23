# Security Policy

## Supported Versions

Security fixes are provided for the latest released version of HAFamilyLink and the current `main` branch.

Older releases are not actively maintained. If you find a vulnerability in an older release, please first verify whether it still exists in the latest version.

## Reporting a Vulnerability

Please report security vulnerabilities privately using GitHub's private vulnerability reporting for this repository.

Do not open a public issue for security-sensitive reports.

Please include:

- A clear description of the issue.
- Steps to reproduce the problem.
- The affected component, such as the Home Assistant integration, the Family Link auth service, Docker image, or GitHub Actions workflow.
- The impact you believe the issue has.
- Any relevant logs with secrets removed.

Do not include Google account credentials, Family Link cookies, Home Assistant tokens, API keys, session files, or other secrets.

## Scope

In scope:

- Authentication service vulnerabilities.
- Cookie, session, API key, or token handling issues.
- Home Assistant integration security issues.
- Docker image or dependency vulnerabilities that are exploitable in normal use.
- GitHub Actions or release workflow issues that could affect published artifacts.

Out of scope:

- Vulnerabilities in Google Family Link itself.
- Vulnerabilities in Home Assistant Core.
- Issues caused by publishing your own credentials, cookies, tokens, or API keys.
- Reports requiring physical access to the host.
- Reports against modified forks or unsupported deployments.

## Response Expectations

I will try to acknowledge valid reports within 14 days.

If confirmed, I will work on a fix or mitigation and coordinate disclosure through GitHub Security Advisories when appropriate.

## Security Updates

Users should update to the latest release when security fixes are published.

If credentials, cookies, Home Assistant tokens, or API keys may have been exposed, rotate or revoke them immediately.
