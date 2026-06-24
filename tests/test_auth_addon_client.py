"""Tests for the Family Link auth add-on cookie client."""
from __future__ import annotations

import json

from cryptography.fernet import Fernet
import pytest

from custom_components.familylink.auth.addon_client import AddonCookieClient


class FakeResponse:
	"""Async response context manager for aiohttp calls."""

	def __init__(self, status: int, payload: dict[str, object] | None = None) -> None:
		self.status = status
		self._payload = payload or {}

	async def __aenter__(self):
		return self

	async def __aexit__(self, exc_type, exc, tb) -> None:
		return None

	async def json(self):
		return self._payload


class FakeSession:
	"""Async session context manager that records GET calls."""

	calls: list[dict[str, object]] = []
	status = 200
	payload: dict[str, object] = {"cookies": [{"name": "SAPISID", "value": "cookie"}]}

	async def __aenter__(self):
		return self

	async def __aexit__(self, exc_type, exc, tb) -> None:
		return None

	def get(self, url, **kwargs):
		self.calls.append({"url": url, **kwargs})
		return FakeResponse(self.status, self.payload)


def _patch_client_session(monkeypatch, status=200, payload=None):
	FakeSession.calls = []
	FakeSession.status = status
	FakeSession.payload = payload or {"cookies": [{"name": "SAPISID", "value": "cookie"}]}
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


async def test_load_cookies_falls_back_to_encrypted_file(hass, monkeypatch, tmp_path):
	"""File cookies are loaded when the API path has no cookies."""
	monkeypatch.delenv("SUPERVISOR_TOKEN", raising=False)
	monkeypatch.setattr(AddonCookieClient, "SHARE_DIR", tmp_path)
	cookies = [{"name": "SAPISID", "value": "from-file"}]
	_write_encrypted_cookies(tmp_path, cookies)
	_patch_client_session(monkeypatch, status=404, payload={})
	client = AddonCookieClient(hass)

	assert await client.load_cookies() == cookies


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


async def test_encrypted_storage_returns_none_for_invalid_payload(
	hass, monkeypatch, tmp_path
):
	"""Broken encrypted storage is treated as unavailable."""
	monkeypatch.setattr(AddonCookieClient, "SHARE_DIR", tmp_path)
	(tmp_path / AddonCookieClient.KEY_FILE).write_bytes(Fernet.generate_key())
	(tmp_path / AddonCookieClient.COOKIE_FILE).write_text("not encrypted")
	client = AddonCookieClient(hass)

	assert await client._load_cookies_from_file() is None
