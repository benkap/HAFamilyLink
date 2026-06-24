"""Tests for the Family Link auth add-on cookie client."""
from __future__ import annotations

import json

from cryptography.fernet import Fernet
import pytest

from custom_components.familylink.auth.addon_client import AddonCookieClient


class FakeResponse:
	"""Async response context manager for aiohttp calls."""

	def __init__(
		self,
		status: int,
		payload: object | None = None,
		json_error: Exception | None = None,
	) -> None:
		self.status = status
		self._payload = payload if payload is not None else {}
		self._json_error = json_error

	async def __aenter__(self):
		return self

	async def __aexit__(self, exc_type, exc, tb) -> None:
		return None

	async def json(self):
		if self._json_error:
			raise self._json_error
		return self._payload


class FakeSession:
	"""Async session context manager that records GET calls."""

	calls: list[dict[str, object]] = []
	status = 200
	payload: object = {"cookies": [{"name": "SAPISID", "value": "cookie"}]}
	json_error: Exception | None = None
	responses: list[FakeResponse | Exception] = []

	async def __aenter__(self):
		return self

	async def __aexit__(self, exc_type, exc, tb) -> None:
		return None

	def get(self, url, **kwargs):
		self.calls.append({"url": url, **kwargs})
		if self.responses:
			response = self.responses.pop(0)
			if isinstance(response, Exception):
				raise response
			return response
		return FakeResponse(self.status, self.payload, self.json_error)


def _patch_client_session(monkeypatch, status=200, payload=None, json_error=None):
	FakeSession.calls = []
	FakeSession.status = status
	FakeSession.payload = (
		payload
		if payload is not None
		else {"cookies": [{"name": "SAPISID", "value": "cookie"}]}
	)
	FakeSession.json_error = json_error
	FakeSession.responses = []
	monkeypatch.setattr(
		"custom_components.familylink.auth.addon_client.aiohttp.ClientSession",
		FakeSession,
	)


def _patch_client_session_sequence(monkeypatch, responses):
	FakeSession.calls = []
	FakeSession.status = 200
	FakeSession.payload = {}
	FakeSession.json_error = None
	FakeSession.responses = list(responses)
	monkeypatch.setattr(
		"custom_components.familylink.auth.addon_client.aiohttp.ClientSession",
		FakeSession,
	)


def _write_encrypted_cookies(tmp_path, cookies):
	key = Fernet.generate_key()
	(tmp_path / AddonCookieClient.KEY_FILE).write_bytes(key)
	(tmp_path / AddonCookieClient.COOKIE_FILE).write_bytes(
		Fernet(key).encrypt(json.dumps({"cookies": cookies}).encode())
	)
	return key


async def test_auth_url_strips_api_key_and_uses_it_for_cookie_fetch(hass, monkeypatch):
	"""Auth URLs may carry ?api_key, but API calls use the stripped base URL."""
	_patch_client_session(monkeypatch)
	client = AddonCookieClient(
		hass,
		auth_url="http://familylink-auth.local:8099?api_key=test-key",
	)

	cookies = await client._fetch_cookies_from_url(client.auth_url)

	assert client.auth_url == "http://familylink-auth.local:8099"
	assert cookies == [{"name": "SAPISID", "value": "cookie"}]
	assert FakeSession.calls == [
		{
			"url": "http://familylink-auth.local:8099/api/cookies",
			"headers": {"X-API-Key": "test-key"},
			"timeout": FakeSession.calls[0]["timeout"],
		}
	]


async def test_cookie_fetch_records_403_invalid_api_key(hass, monkeypatch):
	"""A 403 response returns no cookies and leaves last_fetch_status for callers."""
	_patch_client_session(monkeypatch, status=403, payload={})
	client = AddonCookieClient(hass, auth_url="http://familylink-auth.local:8099")

	assert await client._fetch_cookies_from_url(client.auth_url) is None
	assert client.last_fetch_status == 403


@pytest.mark.parametrize("status", [401, 500])
async def test_cookie_fetch_returns_none_for_non_success_statuses(
	hass, monkeypatch, status
):
	"""Unexpected API statuses are treated as unavailable cookie responses."""
	_patch_client_session(monkeypatch, status=status)
	client = AddonCookieClient(hass, auth_url="http://familylink-auth.local:8099")

	assert await client._fetch_cookies_from_url(client.auth_url) is None
	assert client.last_fetch_status == status


@pytest.mark.parametrize(
	("payload", "json_error"),
	[
		(["not-a-mapping"], None),
		(None, ValueError("bad json")),
	],
)
async def test_cookie_fetch_returns_none_for_malformed_payloads(
	hass, monkeypatch, payload, json_error
):
	"""Malformed success responses do not leak exceptions to callers."""
	_patch_client_session(monkeypatch, payload=payload, json_error=json_error)
	client = AddonCookieClient(hass, auth_url="http://familylink-auth.local:8099")

	assert await client._fetch_cookies_from_url(client.auth_url) is None
	assert client.last_fetch_status == 200


async def test_api_key_file_is_used_when_url_has_no_query_key(
	hass, monkeypatch, tmp_path
):
	"""The shared api_key file protects add-on API requests."""
	monkeypatch.setattr(AddonCookieClient, "SHARE_DIR", tmp_path)
	(tmp_path / AddonCookieClient.API_KEY_FILE).write_text("file-key\n")
	client = AddonCookieClient(hass, auth_url="http://familylink-auth.local:8099")

	assert await client._get_api_key() == "file-key"


async def test_auth_url_api_key_takes_priority_over_file_key(
	hass, monkeypatch, tmp_path
):
	"""A configured URL API key wins over the shared api_key file."""
	monkeypatch.setattr(AddonCookieClient, "SHARE_DIR", tmp_path)
	(tmp_path / AddonCookieClient.API_KEY_FILE).write_text("file-key\n")
	client = AddonCookieClient(
		hass,
		auth_url="http://familylink-auth.local:8099?api_key=url-key",
	)

	assert await client._get_api_key() == "url-key"


async def test_auth_url_query_is_removed_and_first_query_key_wins(
	hass, monkeypatch, tmp_path
):
	"""Extra query values are dropped from the base URL, but the URL key wins."""
	monkeypatch.setattr(AddonCookieClient, "SHARE_DIR", tmp_path)
	(tmp_path / AddonCookieClient.API_KEY_FILE).write_text("file-key\n")
	_patch_client_session(monkeypatch)
	client = AddonCookieClient(
		hass,
		auth_url="http://familylink-auth.local:8099/?unused=1&api_key=url-key&api_key=second",
	)

	assert client.auth_url == "http://familylink-auth.local:8099/"
	assert await client._get_api_key() == "url-key"
	assert await client._fetch_cookies_from_url(client.auth_url) == [
		{"name": "SAPISID", "value": "cookie"}
	]
	assert FakeSession.calls == [
		{
			"url": "http://familylink-auth.local:8099/api/cookies",
			"headers": {"X-API-Key": "url-key"},
			"timeout": FakeSession.calls[0]["timeout"],
		}
	]


async def test_auth_url_query_without_api_key_uses_file_key(
	hass, monkeypatch, tmp_path
):
	"""Query strings without api_key are still stripped before API calls."""
	monkeypatch.setattr(AddonCookieClient, "SHARE_DIR", tmp_path)
	(tmp_path / AddonCookieClient.API_KEY_FILE).write_text("file-key\n")
	client = AddonCookieClient(
		hass,
		auth_url="http://familylink-auth.local:8099?unused=1",
	)

	assert client.auth_url == "http://familylink-auth.local:8099"
	assert await client._get_api_key() == "file-key"


async def test_blank_api_key_file_is_ignored(hass, monkeypatch, tmp_path):
	"""Blank shared api_key files do not send empty API key headers."""
	monkeypatch.setattr(AddonCookieClient, "SHARE_DIR", tmp_path)
	(tmp_path / AddonCookieClient.API_KEY_FILE).write_text("  \n")
	client = AddonCookieClient(hass, auth_url="http://familylink-auth.local:8099")

	assert await client._get_api_key() is None


@pytest.mark.parametrize(
	("status", "expected"),
	[
		(200, True),
		(404, False),
		(500, False),
	],
)
async def test_check_url_available_uses_health_endpoint(
	hass, monkeypatch, status, expected
):
	"""Health checks only accept a 200 response."""
	_patch_client_session(monkeypatch, status=status)
	client = AddonCookieClient(hass)

	assert await client._check_url_available("http://familylink-auth.local:8099") is expected
	assert FakeSession.calls == [
		{
			"url": "http://familylink-auth.local:8099/api/health",
			"timeout": FakeSession.calls[0]["timeout"],
		}
	]


async def test_supervisor_url_resolution_success_is_cached(hass, monkeypatch):
	"""A started Supervisor add-on resolves to its Docker host and is cached."""
	monkeypatch.setenv("SUPERVISOR_TOKEN", "supervisor-token")
	_patch_client_session(
		monkeypatch,
		payload={
			"data": {
				"addons": [
					{
						"slug": "abc_familylink-playwright",
						"state": "stopped",
					},
					{
						"slug": "def_familylink-playwright",
						"state": "started",
					},
				]
			}
		},
	)
	client = AddonCookieClient(hass)

	assert await client._get_addon_url() == "http://def-familylink-playwright:8099"
	assert await client._get_addon_url() == "http://def-familylink-playwright:8099"
	assert FakeSession.calls == [
		{
			"url": "http://supervisor/addons",
			"headers": {"Authorization": "Bearer supervisor-token"},
			"timeout": FakeSession.calls[0]["timeout"],
		}
	]


async def test_supervisor_url_resolution_skips_without_token(hass, monkeypatch):
	"""Supervisor discovery is skipped outside HAOS/Supervised environments."""
	monkeypatch.delenv("SUPERVISOR_TOKEN", raising=False)
	_patch_client_session_sequence(
		monkeypatch,
		[
			FakeResponse(
				200,
				{
					"data": {
						"addons": [
							{
								"slug": "def_familylink-playwright",
								"state": "started",
							}
						]
					}
				},
			)
		],
	)
	client = AddonCookieClient(hass)

	assert await client._get_addon_url() is None
	assert FakeSession.calls == []


@pytest.mark.parametrize(
	"response",
	[
		pytest.param(FakeResponse(503, {}), id="non-200"),
		pytest.param(
			FakeResponse(
				200,
				{
					"data": {
						"addons": [
							{
								"slug": "abc_familylink-playwright",
								"state": "stopped",
							},
							{
								"slug": "unrelated-addon",
								"state": "started",
							},
						]
					}
				},
			),
			id="unavailable",
		),
		pytest.param(RuntimeError("supervisor unavailable"), id="error"),
	],
)
async def test_supervisor_url_resolution_none_is_cached_for_unavailable_response(
	hass, monkeypatch, response
):
	"""Supervisor discovery failures resolve to None and are cached."""
	monkeypatch.setenv("SUPERVISOR_TOKEN", "supervisor-token")
	_patch_client_session_sequence(monkeypatch, [response])
	client = AddonCookieClient(hass)

	assert await client._get_addon_url() is None
	assert await client._get_addon_url() is None
	assert [call["url"] for call in FakeSession.calls] == [
		"http://supervisor/addons"
	]


async def test_detect_auth_source_prefers_configured_api_url(hass, monkeypatch):
	"""A reachable configured URL is selected before other auth sources."""
	_patch_client_session(monkeypatch, status=200)
	client = AddonCookieClient(
		hass,
		auth_url="http://familylink-auth.local:8099?api_key=test-key",
	)

	assert await client.detect_auth_source() == (
		"api",
		"http://familylink-auth.local:8099",
	)
	assert FakeSession.calls == [
		{
			"url": "http://familylink-auth.local:8099/api/health",
			"timeout": FakeSession.calls[0]["timeout"],
		}
	]


async def test_detect_auth_source_uses_file_when_configured_url_unavailable(
	hass, monkeypatch, tmp_path
):
	"""An unavailable configured URL falls back to encrypted storage."""
	monkeypatch.delenv("SUPERVISOR_TOKEN", raising=False)
	monkeypatch.setattr(AddonCookieClient, "SHARE_DIR", tmp_path)
	_write_encrypted_cookies(
		tmp_path,
		[{"name": "SAPISID", "value": "from-file"}],
	)
	_patch_client_session(monkeypatch, status=503)
	client = AddonCookieClient(
		hass,
		auth_url="http://familylink-auth.local:8099?api_key=test-key",
	)

	assert await client.detect_auth_source() == ("file", None)
	assert FakeSession.calls == [
		{
			"url": "http://familylink-auth.local:8099/api/health",
			"timeout": FakeSession.calls[0]["timeout"],
		},
		{
			"url": "http://localhost:8099/api/health",
			"timeout": FakeSession.calls[1]["timeout"],
		},
	]


async def test_detect_auth_source_falls_back_to_file(hass, monkeypatch, tmp_path):
	"""When API health checks fail, encrypted storage is the fallback source."""
	monkeypatch.delenv("SUPERVISOR_TOKEN", raising=False)
	monkeypatch.setattr(AddonCookieClient, "SHARE_DIR", tmp_path)
	(tmp_path / AddonCookieClient.KEY_FILE).write_text("key")
	(tmp_path / AddonCookieClient.COOKIE_FILE).write_text("cookies")
	_patch_client_session(monkeypatch, status=500)
	client = AddonCookieClient(hass)

	assert await client.detect_auth_source() == ("file", None)


async def test_load_cookies_from_configured_url(hass, monkeypatch):
	"""Configured auth URLs load cookies directly from the API."""
	cookies = [{"name": "SAPISID", "value": "cookie"}]
	_patch_client_session(monkeypatch, payload={"cookies": cookies})
	client = AddonCookieClient(hass, auth_url="http://familylink-auth.local:8099")

	assert await client.load_cookies() == cookies
	assert FakeSession.calls == [
		{
			"url": "http://familylink-auth.local:8099/api/cookies",
			"headers": {},
			"timeout": FakeSession.calls[0]["timeout"],
		}
	]


async def test_load_cookies_tries_supervisor_url_then_default_then_file(
	hass, monkeypatch, tmp_path
):
	"""Without a configured URL, cookies try Supervisor, localhost, then file."""
	monkeypatch.setenv("SUPERVISOR_TOKEN", "supervisor-token")
	monkeypatch.setattr(AddonCookieClient, "SHARE_DIR", tmp_path)
	cookies = [{"name": "SAPISID", "value": "from-file"}]
	_write_encrypted_cookies(tmp_path, cookies)
	_patch_client_session_sequence(
		monkeypatch,
		[
			FakeResponse(
				200,
				{
					"data": {
						"addons": [
							{
								"slug": "def_familylink-playwright",
								"state": "started",
							}
						]
					}
				},
			),
			FakeResponse(404, {}),
			FakeResponse(404, {}),
		],
	)
	client = AddonCookieClient(hass)

	assert await client.load_cookies() == cookies
	assert [call["url"] for call in FakeSession.calls] == [
		"http://supervisor/addons",
		"http://def-familylink-playwright:8099/api/cookies",
		"http://localhost:8099/api/cookies",
	]


@pytest.mark.parametrize(
	"supervisor_response",
	[
		pytest.param(FakeResponse(503, {}), id="non-200"),
		pytest.param(RuntimeError("supervisor unavailable"), id="error"),
	],
)
async def test_load_cookies_falls_back_to_default_and_file_when_supervisor_fails(
	hass, monkeypatch, tmp_path, supervisor_response
):
	"""Supervisor lookup failure still allows localhost and file fallback."""
	monkeypatch.setenv("SUPERVISOR_TOKEN", "supervisor-token")
	monkeypatch.setattr(AddonCookieClient, "SHARE_DIR", tmp_path)
	cookies = [{"name": "SAPISID", "value": "from-file"}]
	_write_encrypted_cookies(tmp_path, cookies)
	_patch_client_session_sequence(
		monkeypatch,
		[
			supervisor_response,
			FakeResponse(404, {}),
		],
	)
	client = AddonCookieClient(hass)

	assert await client.load_cookies() == cookies
	assert [call["url"] for call in FakeSession.calls] == [
		"http://supervisor/addons",
		"http://localhost:8099/api/cookies",
	]


async def test_load_cookies_falls_back_to_encrypted_file(hass, monkeypatch, tmp_path):
	"""File cookies are loaded when the API path has no cookies."""
	monkeypatch.delenv("SUPERVISOR_TOKEN", raising=False)
	monkeypatch.setattr(AddonCookieClient, "SHARE_DIR", tmp_path)
	cookies = [{"name": "SAPISID", "value": "from-file"}]
	_write_encrypted_cookies(tmp_path, cookies)
	_patch_client_session(monkeypatch, status=404, payload={})
	client = AddonCookieClient(hass)

	assert await client.load_cookies() == cookies


@pytest.mark.parametrize(
	("source", "cookies", "expected", "expected_load_called"),
	[
		pytest.param(
			("api", "http://familylink-auth.local:8099"),
			[{"name": "SAPISID", "value": "cookie"}],
			True,
			True,
			id="api-cookies",
		),
		pytest.param(("file", None), [], False, True, id="empty-cookies"),
		pytest.param(("file", None), None, False, True, id="missing-cookies"),
		pytest.param(
			("none", None),
			[{"name": "SAPISID", "value": "ignored"}],
			False,
			False,
			id="no-source",
		),
	],
)
async def test_cookies_available_requires_detected_source_and_non_empty_cookies(
	hass, monkeypatch, source, cookies, expected, expected_load_called
):
	"""Cookie availability requires a detected source and at least one cookie."""
	client = AddonCookieClient(hass)
	load_called = False

	async def fake_detect_auth_source():
		return source

	async def fake_load_cookies():
		nonlocal load_called
		load_called = True
		return cookies

	monkeypatch.setattr(client, "detect_auth_source", fake_detect_auth_source)
	monkeypatch.setattr(client, "load_cookies", fake_load_cookies)

	assert await client.cookies_available() is expected
	assert load_called is expected_load_called


async def test_clear_cookies_deletes_existing_storage(hass, monkeypatch, tmp_path):
	"""Clearing cookies removes the encrypted cookie file when it exists."""
	monkeypatch.setattr(AddonCookieClient, "SHARE_DIR", tmp_path)
	storage_path = tmp_path / AddonCookieClient.COOKIE_FILE
	storage_path.write_text("encrypted cookies")
	client = AddonCookieClient(hass)

	await client.clear_cookies()

	assert not storage_path.exists()


async def test_encrypted_storage_path_uses_configured_share_dir(
	hass, monkeypatch, tmp_path
):
	"""Encrypted cookie fallback reads from the patched share directory only."""
	monkeypatch.setattr(AddonCookieClient, "SHARE_DIR", tmp_path)
	cookies = [{"name": "SAPISID", "value": "cookie"}]
	_write_encrypted_cookies(tmp_path, cookies)
	client = AddonCookieClient(hass)

	assert client.storage_path == tmp_path / AddonCookieClient.COOKIE_FILE
	assert await client._load_cookies_from_file() == cookies


@pytest.mark.parametrize(
	("write_cookie", "write_key"),
	[
		(False, True),
		(True, False),
	],
)
async def test_encrypted_storage_returns_none_when_required_file_is_missing(
	hass, monkeypatch, tmp_path, write_cookie, write_key
):
	"""Encrypted storage is unavailable unless the cookie and key files exist."""
	monkeypatch.setattr(AddonCookieClient, "SHARE_DIR", tmp_path)
	if write_key:
		(tmp_path / AddonCookieClient.KEY_FILE).write_bytes(Fernet.generate_key())
	if write_cookie:
		(tmp_path / AddonCookieClient.COOKIE_FILE).write_bytes(b"encrypted")
	client = AddonCookieClient(hass)

	assert await client._load_cookies_from_file() is None


async def test_encrypted_storage_returns_none_for_invalid_payload(
	hass, monkeypatch, tmp_path
):
	"""Broken encrypted storage is treated as unavailable."""
	monkeypatch.setattr(AddonCookieClient, "SHARE_DIR", tmp_path)
	(tmp_path / AddonCookieClient.KEY_FILE).write_bytes(Fernet.generate_key())
	(tmp_path / AddonCookieClient.COOKIE_FILE).write_text("not encrypted")
	client = AddonCookieClient(hass)

	assert await client._load_cookies_from_file() is None


async def test_encrypted_storage_returns_none_when_key_cannot_decrypt_cookie(
	hass, monkeypatch, tmp_path
):
	"""Cookie data encrypted with a different key is treated as unavailable."""
	monkeypatch.setattr(AddonCookieClient, "SHARE_DIR", tmp_path)
	cookie_key = Fernet.generate_key()
	(tmp_path / AddonCookieClient.KEY_FILE).write_bytes(Fernet.generate_key())
	(tmp_path / AddonCookieClient.COOKIE_FILE).write_bytes(
		Fernet(cookie_key).encrypt(
			json.dumps({"cookies": [{"name": "SAPISID", "value": "cookie"}]}).encode()
		)
	)
	client = AddonCookieClient(hass)

	assert await client._load_cookies_from_file() is None
