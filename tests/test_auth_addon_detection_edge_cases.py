"""Focused edge tests for auth add-on detection and cookie loading."""
from __future__ import annotations

import pytest

from custom_components.familylink.auth.addon_client import (
	DEFAULT_AUTH_URL,
	AddonCookieClient,
)


class RaisingSession:
	"""Async session context manager whose GET call fails unexpectedly."""

	async def __aenter__(self):
		return self

	async def __aexit__(self, exc_type, exc, tb) -> None:
		return None

	def get(self, url, **kwargs):
		raise RuntimeError("network stack exploded")


async def test_check_url_available_returns_false_for_unexpected_exception(
	hass, monkeypatch
):
	"""Unexpected health-check errors make the URL unavailable."""
	monkeypatch.setattr(
		"custom_components.familylink.auth.addon_client.aiohttp.ClientSession",
		RaisingSession,
	)
	client = AddonCookieClient(hass)

	assert await client._check_url_available("http://familylink-auth.local:8099") is False


async def test_detect_auth_source_returns_available_custom_url(hass, monkeypatch):
	"""A reachable configured URL wins immediately."""
	client = AddonCookieClient(hass, auth_url="http://familylink-auth.local:8099")
	checked_urls: list[str] = []

	async def fake_check_url_available(url: str) -> bool:
		checked_urls.append(url)
		return True

	async def unexpected_call():
		raise AssertionError("custom URL should skip fallback discovery")

	monkeypatch.setattr(client, "_check_url_available", fake_check_url_available)
	monkeypatch.setattr(client, "_get_addon_url", unexpected_call)
	monkeypatch.setattr(client, "_file_available", unexpected_call)

	assert await client.detect_auth_source() == (
		"api",
		"http://familylink-auth.local:8099",
	)
	assert client._detected_url == "http://familylink-auth.local:8099"
	assert checked_urls == ["http://familylink-auth.local:8099"]


async def test_detect_auth_source_returns_detected_supervisor_url(hass, monkeypatch):
	"""A reachable Supervisor-resolved add-on URL is selected before localhost."""
	client = AddonCookieClient(hass)
	supervisor_url = "http://def-familylink-playwright:8099"
	checked_urls: list[str] = []

	async def fake_get_addon_url() -> str:
		return supervisor_url

	async def fake_check_url_available(url: str) -> bool:
		checked_urls.append(url)
		return url == supervisor_url

	async def unexpected_file_available():
		raise AssertionError("reachable Supervisor URL should skip file fallback")

	monkeypatch.setattr(client, "_get_addon_url", fake_get_addon_url)
	monkeypatch.setattr(client, "_check_url_available", fake_check_url_available)
	monkeypatch.setattr(client, "_file_available", unexpected_file_available)

	assert await client.detect_auth_source() == ("api", supervisor_url)
	assert client._detected_url == supervisor_url
	assert checked_urls == [supervisor_url]


async def test_detect_auth_source_returns_available_default_url(hass, monkeypatch):
	"""The default localhost URL is used when Supervisor discovery has no URL."""
	client = AddonCookieClient(hass)
	checked_urls: list[str] = []

	async def fake_get_addon_url() -> None:
		return None

	async def fake_check_url_available(url: str) -> bool:
		checked_urls.append(url)
		return url == DEFAULT_AUTH_URL

	async def unexpected_file_available():
		raise AssertionError("reachable default URL should skip file fallback")

	monkeypatch.setattr(client, "_get_addon_url", fake_get_addon_url)
	monkeypatch.setattr(client, "_check_url_available", fake_check_url_available)
	monkeypatch.setattr(client, "_file_available", unexpected_file_available)

	assert await client.detect_auth_source() == ("api", DEFAULT_AUTH_URL)
	assert client._detected_url == DEFAULT_AUTH_URL
	assert checked_urls == [DEFAULT_AUTH_URL]


async def test_detect_auth_source_returns_file_fallback(hass, monkeypatch):
	"""Encrypted file storage is selected when no API health check succeeds."""
	client = AddonCookieClient(hass)
	checked_urls: list[str] = []

	async def fake_get_addon_url() -> None:
		return None

	async def fake_check_url_available(url: str) -> bool:
		checked_urls.append(url)
		return False

	async def fake_file_available() -> bool:
		return True

	monkeypatch.setattr(client, "_get_addon_url", fake_get_addon_url)
	monkeypatch.setattr(client, "_check_url_available", fake_check_url_available)
	monkeypatch.setattr(client, "_file_available", fake_file_available)

	assert await client.detect_auth_source() == ("file", None)
	assert checked_urls == [DEFAULT_AUTH_URL]


async def test_detect_auth_source_returns_none_when_no_source_is_available(
	hass, monkeypatch
):
	"""Detection returns none when API and file sources are unavailable."""
	client = AddonCookieClient(hass)
	checked_urls: list[str] = []

	async def fake_get_addon_url() -> None:
		return None

	async def fake_check_url_available(url: str) -> bool:
		checked_urls.append(url)
		return False

	async def fake_file_available() -> bool:
		return False

	monkeypatch.setattr(client, "_get_addon_url", fake_get_addon_url)
	monkeypatch.setattr(client, "_check_url_available", fake_check_url_available)
	monkeypatch.setattr(client, "_file_available", fake_file_available)

	assert await client.detect_auth_source() == ("none", None)
	assert checked_urls == [DEFAULT_AUTH_URL]


async def test_load_cookies_returns_resolved_supervisor_url_cookies(
	hass, monkeypatch
):
	"""Supervisor API cookies are returned without trying default or file paths."""
	client = AddonCookieClient(hass)
	supervisor_url = "http://def-familylink-playwright:8099"
	cookies = [{"name": "SAPISID", "value": "from-supervisor"}]
	fetched_urls: list[str] = []

	async def fake_get_addon_url() -> str:
		return supervisor_url

	async def fake_fetch_cookies_from_url(url: str):
		fetched_urls.append(url)
		if url == supervisor_url:
			return cookies
		raise AssertionError(f"unexpected cookie fetch from {url}")

	async def unexpected_file_load():
		raise AssertionError("Supervisor cookies should skip file fallback")

	monkeypatch.setattr(client, "_get_addon_url", fake_get_addon_url)
	monkeypatch.setattr(client, "_fetch_cookies_from_url", fake_fetch_cookies_from_url)
	monkeypatch.setattr(client, "_load_cookies_from_file", unexpected_file_load)

	assert await client.load_cookies() == cookies
	assert fetched_urls == [supervisor_url]


async def test_load_cookies_returns_default_url_cookies_after_supervisor_miss(
	hass, monkeypatch
):
	"""Default localhost cookies are returned after a Supervisor API miss."""
	client = AddonCookieClient(hass)
	supervisor_url = "http://def-familylink-playwright:8099"
	cookies = [{"name": "SAPISID", "value": "from-default"}]
	fetched_urls: list[str] = []

	async def fake_get_addon_url() -> str:
		return supervisor_url

	async def fake_fetch_cookies_from_url(url: str):
		fetched_urls.append(url)
		return cookies if url == DEFAULT_AUTH_URL else None

	async def unexpected_file_load():
		raise AssertionError("default API cookies should skip file fallback")

	monkeypatch.setattr(client, "_get_addon_url", fake_get_addon_url)
	monkeypatch.setattr(client, "_fetch_cookies_from_url", fake_fetch_cookies_from_url)
	monkeypatch.setattr(client, "_load_cookies_from_file", unexpected_file_load)

	assert await client.load_cookies() == cookies
	assert fetched_urls == [supervisor_url, DEFAULT_AUTH_URL]


async def test_load_cookies_falls_back_to_file_after_api_misses(hass, monkeypatch):
	"""File cookies are loaded after Supervisor and default API calls miss."""
	client = AddonCookieClient(hass)
	supervisor_url = "http://def-familylink-playwright:8099"
	cookies = [{"name": "SAPISID", "value": "from-file"}]
	fetched_urls: list[str] = []

	async def fake_get_addon_url() -> str:
		return supervisor_url

	async def fake_fetch_cookies_from_url(url: str) -> None:
		fetched_urls.append(url)
		return None

	async def fake_load_cookies_from_file():
		return cookies

	monkeypatch.setattr(client, "_get_addon_url", fake_get_addon_url)
	monkeypatch.setattr(client, "_fetch_cookies_from_url", fake_fetch_cookies_from_url)
	monkeypatch.setattr(client, "_load_cookies_from_file", fake_load_cookies_from_file)

	assert await client.load_cookies() == cookies
	assert fetched_urls == [supervisor_url, DEFAULT_AUTH_URL]


async def test_cookies_available_returns_false_for_none_source(hass, monkeypatch):
	"""No detected source means cookie loading is skipped."""
	client = AddonCookieClient(hass)

	async def fake_detect_auth_source():
		return ("none", None)

	async def unexpected_load_cookies():
		raise AssertionError("no source should skip cookie loading")

	monkeypatch.setattr(client, "detect_auth_source", fake_detect_auth_source)
	monkeypatch.setattr(client, "load_cookies", unexpected_load_cookies)

	assert await client.cookies_available() is False


@pytest.mark.parametrize("cookies", [None, []], ids=["missing", "empty"])
async def test_cookies_available_returns_false_when_load_finds_no_cookies(
	hass, monkeypatch, cookies
):
	"""A detected source still needs at least one loaded cookie."""
	client = AddonCookieClient(hass)

	async def fake_detect_auth_source():
		return ("api", DEFAULT_AUTH_URL)

	async def fake_load_cookies():
		return cookies

	monkeypatch.setattr(client, "detect_auth_source", fake_detect_auth_source)
	monkeypatch.setattr(client, "load_cookies", fake_load_cookies)

	assert await client.cookies_available() is False
