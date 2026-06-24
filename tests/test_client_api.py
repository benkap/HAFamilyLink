"""Tests for the Family Link API client core behavior."""
from __future__ import annotations

import asyncio
from datetime import datetime
import hashlib
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import aiohttp
import pytest

from custom_components.familylink.client.api import FamilyLinkClient
from custom_components.familylink.const import CONF_SCHEDULE_TIMEZONE
from custom_components.familylink.exceptions import (
	AuthenticationError,
	NetworkError,
	SessionExpiredError,
)


def _client(hass, *, timezone: str = "UTC") -> FamilyLinkClient:
	"""Return a client configured for offline unit tests."""
	return FamilyLinkClient(hass, {CONF_SCHEDULE_TIMEZONE: timezone})


def _authenticated_client(hass, *, timezone: str = "UTC") -> FamilyLinkClient:
	"""Return an authenticated client with test cookies."""
	client = _client(hass, timezone=timezone)
	client._cookies = [{"name": "SAPISID", "value": "cookie", "domain": ".google.com"}]
	return client


class FakeResponse:
	"""Async response context manager for API calls."""

	def __init__(
		self,
		status: int = 200,
		payload: object | None = None,
		text: str = "response text",
	) -> None:
		self.status = status
		self._payload = payload if payload is not None else {}
		self._text = text

	async def __aenter__(self):
		return self

	async def __aexit__(self, exc_type, exc, tb) -> None:
		return None

	async def json(self):
		return self._payload

	async def text(self):
		return self._text

	def raise_for_status(self) -> None:
		if self.status >= 400:
			raise aiohttp.ClientResponseError(
				request_info=SimpleNamespace(real_url="https://example.test/request"),
				history=(),
				status=self.status,
				message="error",
				headers={},
			)


class FakeSession:
	"""HTTP session fake that records GET calls."""

	def __init__(self, response: FakeResponse) -> None:
		self.response = response
		self.calls: list[dict[str, object]] = []

	def get(self, url, **kwargs):
		self.calls.append({"method": "GET", "url": url, **kwargs})
		return self.response


def test_people_url_validates_account_id_before_interpolation(hass):
	"""Account IDs used in URLs reject path separators and shell-ish input."""
	client = _client(hass)

	assert (
		client._people_url("child-123_ok", "devices")
		== f"{FamilyLinkClient.BASE_URL}/people/child-123_ok/devices"
	)

	for unsafe_id in ("", "../child", "child/other", "child?x=1", "child space"):
		with pytest.raises(ValueError, match="Invalid account_id"):
			client._people_url(unsafe_id, "devices")


def test_cookie_dict_prioritizes_google_domain_and_strips_quotes(hass):
	"""Cookie handling prefers google.com and keeps raw unquoted header values."""
	client = _client(hass)
	client._cookies = [
		{"name": "SAPISID", "value": '"regional/value"', "domain": ".google.com.au"},
		{"name": "OTHER", "value": '"other/value"', "domain": ".example.test"},
		{"name": "SAPISID", "value": '"primary/value"', "domain": ".google.com"},
		{"name": "IGNORED_EMPTY", "value": "", "domain": ".google.com"},
		{"name": "", "value": "ignored", "domain": ".google.com"},
	]

	assert client._get_cookies_dict() == {
		"SAPISID": "primary/value",
		"OTHER": "other/value",
	}
	assert client._get_cookie_header() == "SAPISID=primary/value; OTHER=other/value"


def test_generate_sapisidhash_uses_current_timestamp(monkeypatch, hass):
	"""SAPISIDHASH uses the current timestamp, SAPISID, and origin."""
	monkeypatch.setattr("custom_components.familylink.client.api.time.time", lambda: 1234)
	client = _client(hass)

	result = client._generate_sapisidhash("cookie-value", "https://familylink.google.com")

	expected_hash = hashlib.sha1(
		b"1234 cookie-value https://familylink.google.com"
	).hexdigest()
	assert result == f"1234_{expected_hash}"


def test_google_schedule_timezone_is_cached_from_devices_payload(hass):
	"""Google device timezone is cached unless config pins a timezone."""
	client = _client(hass, timezone="")
	devices_payload = [None, [[None] * 11 + [["Asia/Jerusalem"]]]]

	client.update_google_schedule_timezone("child-1", devices_payload)

	assert client._google_schedule_timezones == {"child-1": "Asia/Jerusalem"}
	assert client._schedule_time_zone_context("child-1")[1:] == (
		"Asia/Jerusalem",
		"google",
	)

	configured_client = _client(hass, timezone="UTC")
	configured_client.update_google_schedule_timezone("child-1", devices_payload)
	assert configured_client._google_schedule_timezones == {}


def test_schedule_timezone_context_falls_back_to_single_google_timezone(hass):
	"""Schedule timezone lookup uses the only Google timezone when child ID differs."""
	client = _client(hass, timezone="")
	client._google_schedule_timezones = {"child-1": "Asia/Jerusalem"}

	assert client._schedule_time_zone_context("child-2")[1:] == (
		"Asia/Jerusalem",
		"google",
	)


def test_schedule_timezone_context_ignores_invalid_configured_timezone(hass):
	"""Invalid configured timezone values fall back to Home Assistant settings."""
	hass.config.time_zone = "America/New_York"
	client = _client(hass, timezone="Not/AZone")

	assert client._schedule_time_zone_context("child-1")[1:] == (
		"America/New_York",
		"home_assistant",
	)


def test_schedule_today_uses_effective_timezone(monkeypatch, hass):
	"""schedule_today reads the current date in the effective timezone."""
	client = _client(hass, timezone="UTC")
	seen_timezones = []

	def fake_now(time_zone=None):
		seen_timezones.append(time_zone)
		return datetime(2026, 6, 24, 12, 0, tzinfo=time_zone)

	monkeypatch.setattr("custom_components.familylink.client.api.dt_util.now", fake_now)

	assert client.schedule_today("child-1") == 3
	assert seen_timezones[0] is not None


def test_cookie_dict_keeps_existing_higher_priority_cookie(hass):
	"""Cookie handling keeps an existing higher-priority duplicate cookie."""
	client = _client(hass)
	client._cookies = [
		{"name": "SAPISID", "value": "preferred", "domain": ".example.test"},
		{"name": "SAPISID", "value": "regional", "domain": ".google.com.au"},
	]

	assert client._get_cookies_dict() == {"SAPISID": "preferred"}


async def test_authenticate_loads_cookies_from_addon(hass):
	"""Authentication stores cookies returned by the add-on client."""
	client = _client(hass)
	cookies = [{"name": "SAPISID", "value": "cookie"}]
	client.addon_client = SimpleNamespace(load_cookies=AsyncMock(return_value=cookies))

	await client.async_authenticate()

	assert client.is_authenticated()
	assert client._cookies == cookies
	client.addon_client.load_cookies.assert_awaited_once()


@pytest.mark.parametrize(
	("last_fetch_status", "message"),
	[
		(403, "requires an API key"),
		(None, "No cookies found"),
	],
)
async def test_authenticate_reports_missing_cookies(
	hass, last_fetch_status, message
):
	"""Authentication errors distinguish invalid API keys from missing cookies."""
	client = _client(hass)
	client.addon_client = SimpleNamespace(
		load_cookies=AsyncMock(return_value=None),
		last_fetch_status=last_fetch_status,
	)

	with pytest.raises(AuthenticationError, match=message):
		await client.async_authenticate()


async def test_refresh_session_clears_cached_cookies_and_closes_session(hass):
	"""Refreshing auth drops stale cookie caches and closes the old session."""
	client = _client(hass)
	old_session = SimpleNamespace(close=AsyncMock())
	cookies = [{"name": "SAPISID", "value": "fresh"}]
	client._session = old_session
	client._cookies = [{"name": "SAPISID", "value": "stale"}]
	client._cookie_dict = {"SAPISID": "stale"}
	client._cookie_header = "SAPISID=stale"
	client.addon_client = SimpleNamespace(load_cookies=AsyncMock(return_value=cookies))

	await client.async_refresh_session()

	old_session.close.assert_awaited_once()
	assert client._session is None
	assert client._cookies == cookies
	assert not hasattr(client, "_cookie_dict")
	assert not hasattr(client, "_cookie_header")


async def test_get_session_uses_prioritized_sapisid_cookie(monkeypatch, hass):
	"""Session creation uses the highest-priority SAPISID cookie domain."""
	created_sessions = []

	class FakeSession:
		def __init__(self, *, headers, timeout):
			self.headers = headers
			self.timeout = timeout
			self.close = AsyncMock()
			created_sessions.append(self)

	monkeypatch.setattr(
		"custom_components.familylink.client.api.aiohttp.ClientSession",
		FakeSession,
	)
	monkeypatch.setattr(
		"custom_components.familylink.client.api.time.time",
		lambda: 1234,
	)
	client = _client(hass)
	client._cookies = [
		{"name": "SAPISID", "value": "regional", "domain": ".google.com.au"},
		{"name": "SAPISID", "value": '"primary"', "domain": ".google.com"},
	]

	session = await client._get_session()

	expected_hash = hashlib.sha1(
		b"1234 primary https://familylink.google.com"
	).hexdigest()
	assert session is created_sessions[0]
	assert session.headers["Authorization"] == f"SAPISIDHASH 1234_{expected_hash}"
	assert session.headers["Origin"] == FamilyLinkClient.ORIGIN


async def test_get_session_requires_sapisid_cookie(hass):
	"""Session creation fails loudly when auth data lacks SAPISID."""
	client = _client(hass)
	client._cookies = [{"name": "SID", "value": "cookie", "domain": ".google.com"}]

	with pytest.raises(AuthenticationError, match="SAPISID cookie not found"):
		await client._get_session()


async def test_get_session_recreates_stale_session(monkeypatch, hass):
	"""Session creation closes and replaces stale SAPISIDHASH sessions."""
	created_sessions = []

	class FakeSession:
		def __init__(self, *, headers, timeout):
			self.headers = headers
			self.timeout = timeout
			self.close = AsyncMock()
			created_sessions.append(self)

	monkeypatch.setattr(
		"custom_components.familylink.client.api.aiohttp.ClientSession",
		FakeSession,
	)
	monkeypatch.setattr(
		"custom_components.familylink.client.api.time.time",
		lambda: FamilyLinkClient.SESSION_MAX_AGE + 10,
	)
	old_session = SimpleNamespace(close=AsyncMock())
	client = _authenticated_client(hass)
	client._session = old_session
	client._session_created_at = 0

	session = await client._get_session()

	old_session.close.assert_awaited_once()
	assert session is created_sessions[0]
	assert client._session is session
	assert client._session_created_at == FamilyLinkClient.SESSION_MAX_AGE + 10


async def test_get_session_rejects_sapisid_from_non_google_domain(hass):
	"""SAPISID cookies from unrelated domains are ignored for session auth."""
	client = _client(hass)
	client._cookies = [
		{"name": "SAPISID", "value": "cookie", "domain": ".example.test"},
	]

	with pytest.raises(AuthenticationError, match="SAPISID cookie not found"):
		await client._get_session()


async def test_get_session_surfaces_lock_timeout(hass):
	"""Session acquisition timeout is surfaced to callers."""
	client = _authenticated_client(hass)
	client._session_lock = SimpleNamespace(
		acquire=AsyncMock(side_effect=asyncio.TimeoutError),
		release=Mock(),
	)

	with pytest.raises(asyncio.TimeoutError):
		await client._get_session()

	client._session_lock.release.assert_not_called()


async def test_supervised_child_helpers_parse_family_members(hass):
	"""Family member helpers find supervised children and cache the first ID."""
	client = _client(hass)
	client.async_get_family_members = AsyncMock(
		return_value={
			"members": [
				{
					"userId": "parent-1",
					"profile": {"displayName": "Parent"},
				},
				{
					"userId": "child-1",
					"profile": {"displayName": "Alex"},
					"memberSupervisionInfo": {"isSupervisedMember": True},
				},
				{
					"userId": "child-2",
					"profile": {"displayName": "Sam"},
					"memberSupervisionInfo": {"isSupervisedMember": True},
				},
			]
		}
	)

	assert await client.async_get_supervised_child_id() == "child-1"
	assert client._account_id == "child-1"
	assert await client.async_get_supervised_child_id() == "child-1"
	assert client.async_get_family_members.await_count == 1

	assert await client.async_get_all_supervised_children() == [
		{"id": "child-1", "name": "Alex"},
		{"id": "child-2", "name": "Sam"},
	]


async def test_supervised_child_helpers_raise_without_children(hass):
	"""Family member helpers raise clear errors when no supervised child exists."""
	client = _client(hass)
	client.async_get_family_members = AsyncMock(return_value={"members": []})

	with pytest.raises(ValueError, match="No supervised child"):
		await client.async_get_supervised_child_id()

	with pytest.raises(ValueError, match="No supervised children"):
		await client.async_get_all_supervised_children()


async def test_get_family_members_fetches_json_with_cookie_header(hass):
	"""Family member requests send the manually built Cookie header."""
	client = _authenticated_client(hass)
	payload = {"members": [{"userId": "child-1"}]}
	session = FakeSession(FakeResponse(payload=payload))
	client._get_session = AsyncMock(return_value=session)

	assert await client.async_get_family_members() == payload
	assert session.calls == [
		{
			"method": "GET",
			"url": f"{FamilyLinkClient.BASE_URL}/families/mine/members",
			"headers": {
				"Content-Type": "application/json",
				"Cookie": "SAPISID=cookie",
			},
		}
	]


async def test_get_family_members_raises_session_expired_on_401(hass):
	"""A 401 family-member response is surfaced as a session-expired error."""
	client = _authenticated_client(hass)
	client._get_session = AsyncMock(return_value=FakeSession(FakeResponse(status=401)))

	with pytest.raises(SessionExpiredError, match="Session expired"):
		await client.async_get_family_members()


async def test_get_family_members_requires_authentication(hass):
	"""Family member requests fail before I/O when cookies are missing."""
	client = _client(hass)

	with pytest.raises(AuthenticationError, match="Not authenticated"):
		await client.async_get_family_members()


async def test_get_family_members_wraps_http_errors(hass):
	"""Non-auth HTTP errors from family-member requests become NetworkError."""
	client = _authenticated_client(hass)
	client._get_session = AsyncMock(
		return_value=FakeSession(FakeResponse(status=500, text="server error"))
	)

	with pytest.raises(NetworkError, match="Failed to fetch family members"):
		await client.async_get_family_members()


async def test_get_apps_and_usage_uses_expected_capability_params(hass):
	"""Apps and usage calls request both required capabilities."""
	client = _authenticated_client(hass)
	payload = {"apps": [], "deviceInfo": [], "appUsageSessions": []}
	session = FakeSession(FakeResponse(payload=payload))
	client._get_session = AsyncMock(return_value=session)

	assert await client.async_get_apps_and_usage("child-1") == payload
	assert session.calls == [
		{
			"method": "GET",
			"url": f"{FamilyLinkClient.BASE_URL}/people/child-1/appsandusage",
			"headers": {
				"Content-Type": "application/json",
				"Cookie": "SAPISID=cookie",
			},
			"params": [
				("capabilities", "CAPABILITY_APP_USAGE_SESSION"),
				("capabilities", "CAPABILITY_SUPERVISION_CAPABILITIES"),
			],
		}
	]


async def test_get_apps_and_usage_requires_authentication(hass):
	"""Apps and usage requests fail before I/O when cookies are missing."""
	client = _client(hass)

	with pytest.raises(AuthenticationError, match="Not authenticated"):
		await client.async_get_apps_and_usage("child-1")


async def test_get_apps_and_usage_uses_first_child_when_account_is_missing(hass):
	"""Apps and usage requests resolve the first supervised child by default."""
	client = _authenticated_client(hass)
	payload = {"apps": [], "deviceInfo": [], "appUsageSessions": []}
	session = FakeSession(FakeResponse(payload=payload))
	client._get_session = AsyncMock(return_value=session)
	client.async_get_supervised_child_id = AsyncMock(return_value="child-1")

	assert await client.async_get_apps_and_usage() == payload
	client.async_get_supervised_child_id.assert_awaited_once()
	assert session.calls[0]["url"] == (
		f"{FamilyLinkClient.BASE_URL}/people/child-1/appsandusage"
	)


@pytest.mark.parametrize(
	("status", "expected_error"),
	[
		(401, SessionExpiredError),
		(500, NetworkError),
	],
)
async def test_get_apps_and_usage_http_failures(hass, status, expected_error):
	"""Apps and usage requests keep auth failures distinct from other HTTP errors."""
	client = _authenticated_client(hass)
	client._get_session = AsyncMock(return_value=FakeSession(FakeResponse(status=status)))

	with pytest.raises(expected_error):
		await client.async_get_apps_and_usage("child-1")


async def test_get_devices_payload_uses_include_unmanaged_devices(hass):
	"""Device payload requests include unmanaged devices for timezone discovery."""
	client = _authenticated_client(hass)
	payload = [None, []]
	session = FakeSession(FakeResponse(payload=payload))
	client._get_session = AsyncMock(return_value=session)

	assert await client.async_get_devices_payload("child-1") == payload
	assert session.calls == [
		{
			"method": "GET",
			"url": f"{FamilyLinkClient.BASE_URL}/people/child-1/devices",
			"headers": {
				"Content-Type": "application/json+protobuf",
				"Cookie": "SAPISID=cookie",
			},
			"params": {"includeUnmanagedDevices": "true"},
		}
	]


async def test_get_devices_payload_requires_authentication(hass):
	"""Device payload requests fail before I/O when cookies are missing."""
	client = _client(hass)

	with pytest.raises(AuthenticationError, match="Not authenticated"):
		await client.async_get_devices_payload("child-1")


async def test_get_devices_payload_uses_first_child_when_account_is_missing(hass):
	"""Device payload requests resolve the first supervised child by default."""
	client = _authenticated_client(hass)
	payload = [None, []]
	session = FakeSession(FakeResponse(payload=payload))
	client._get_session = AsyncMock(return_value=session)
	client.async_get_supervised_child_id = AsyncMock(return_value="child-1")

	assert await client.async_get_devices_payload() == payload
	client.async_get_supervised_child_id.assert_awaited_once()
	assert session.calls[0]["url"] == (
		f"{FamilyLinkClient.BASE_URL}/people/child-1/devices"
	)


@pytest.mark.parametrize(
	("status", "expected_error"),
	[
		(401, SessionExpiredError),
		(500, NetworkError),
	],
)
async def test_get_devices_payload_http_failures(hass, status, expected_error):
	"""Device payload requests keep auth failures distinct from other HTTP errors."""
	client = _authenticated_client(hass)
	client._get_session = AsyncMock(
		return_value=FakeSession(FakeResponse(status=status, text="server error"))
	)

	with pytest.raises(expected_error):
		await client.async_get_devices_payload("child-1")


async def test_update_google_schedule_timezone_marks_child_checked_on_failure(hass):
	"""Best-effort timezone discovery does not repeatedly retry failed children."""
	client = _client(hass, timezone="")
	client.async_get_devices_payload = AsyncMock(side_effect=NetworkError("boom"))

	await client.async_update_google_schedule_timezone_from_devices("child-1")

	assert client._google_schedule_timezone_checked == {"child-1"}
	assert client._google_schedule_timezones == {}


@pytest.mark.parametrize(
	("timezone", "cached_timezones", "checked_children"),
	[
		("UTC", {}, ()),
		("", {"child-1": "Asia/Jerusalem"}, ()),
		("", {}, ("child-1",)),
	],
	ids=["configured-timezone", "cached-timezone", "already-checked"],
)
async def test_update_google_schedule_timezone_skips_when_unneeded(
	hass, timezone, cached_timezones, checked_children
):
	"""Timezone discovery skips configured, cached, or already checked children."""
	client = _client(hass, timezone=timezone)
	client._google_schedule_timezones.update(cached_timezones)
	client._google_schedule_timezone_checked.update(checked_children)
	client.async_get_devices_payload = AsyncMock()

	await client.async_update_google_schedule_timezone_from_devices("child-1")

	client.async_get_devices_payload.assert_not_awaited()


async def test_update_google_schedule_timezone_caches_devices_timezone(hass):
	"""Timezone discovery caches the Google timezone from device data."""
	client = _client(hass, timezone="")
	devices_payload = [None, [[None] * 11 + [["Asia/Jerusalem"]]]]
	client.async_get_devices_payload = AsyncMock(return_value=devices_payload)

	await client.async_update_google_schedule_timezone_from_devices("child-1")

	client.async_get_devices_payload.assert_awaited_once_with("child-1")
	assert client._google_schedule_timezone_checked == {"child-1"}
	assert client._google_schedule_timezones == {"child-1": "Asia/Jerusalem"}


async def test_get_location_parses_location_payload(hass):
	"""Location responses are converted into Home Assistant friendly fields."""
	client = _authenticated_client(hass)
	session = FakeSession(
		FakeResponse(
			payload=[
				[None, 1710000000000],
				[
					"child-1",
					"status",
					[
						[32.0853, 34.7818],
						1710000000000,
						25,
						None,
						["place-1", "Home", "1 Test Street"],
						None,
						"device-1",
						None,
						["84", "charging"],
					],
				],
			]
		)
	)
	client._get_session = AsyncMock(return_value=session)

	result = await client.async_get_location("child-1", refresh=True)

	assert result == {
		"latitude": 32.0853,
		"longitude": 34.7818,
		"accuracy": 25,
		"timestamp": 1710000000000,
		"timestamp_iso": datetime.fromtimestamp(1710000000000 / 1000).isoformat(),
		"place_id": "place-1",
		"place_name": "Home",
		"place_address": "1 Test Street",
		"source_device_id": "device-1",
		"battery_level": 84,
	}
	assert session.calls[0]["params"] == [
		("locationRefreshMode", "REFRESH"),
		("supportedConsents", "SUPERVISED_LOCATION_SHARING"),
	]


async def test_get_location_requires_authentication(hass):
	"""Location requests fail before I/O when cookies are missing."""
	client = _client(hass)

	with pytest.raises(AuthenticationError, match="Not authenticated"):
		await client.async_get_location("child-1")


async def test_get_location_uses_first_child_when_account_is_missing(hass):
	"""Location requests resolve the first supervised child by default."""
	client = _authenticated_client(hass)
	session = FakeSession(
		FakeResponse(
			payload=[
				[None, 1710000000000],
				["child-1", "status", [[32.0853, 34.7818], 1710000000000]],
			]
		)
	)
	client._get_session = AsyncMock(return_value=session)
	client.async_get_supervised_child_id = AsyncMock(return_value="child-1")

	result = await client.async_get_location()

	client.async_get_supervised_child_id.assert_awaited_once()
	assert result is not None
	assert result["latitude"] == 32.0853
	assert session.calls[0]["url"] == (
		f"{FamilyLinkClient.BASE_URL}/families/mine/location/child-1"
	)


async def test_get_location_raises_session_expired_on_401(hass):
	"""A 401 location response is surfaced as a session-expired error."""
	client = _authenticated_client(hass)
	client._get_session = AsyncMock(return_value=FakeSession(FakeResponse(status=401)))

	with pytest.raises(SessionExpiredError, match="Session expired"):
		await client.async_get_location("child-1")


@pytest.mark.parametrize("status", [404, 500])
async def test_get_location_returns_none_when_unavailable(hass, status):
	"""Unavailable location responses do not fail coordinator refreshes."""
	client = _authenticated_client(hass)
	client._get_session = AsyncMock(return_value=FakeSession(FakeResponse(status=status)))

	assert await client.async_get_location("child-1") is None


@pytest.mark.parametrize(
	"payload",
	[
		{},
		[],
		[None],
		[None, "bad"],
		[None, ["child-1"]],
		[None, ["child-1", "status", "bad"]],
		[None, ["child-1", "status", [["only-latitude"], 1710000000000]]],
	],
)
async def test_get_location_returns_none_for_malformed_payloads(hass, payload):
	"""Malformed location payloads are ignored instead of bubbling errors."""
	client = _authenticated_client(hass)
	client._get_session = AsyncMock(
		return_value=FakeSession(FakeResponse(payload=payload))
	)

	assert await client.async_get_location("child-1") is None


async def test_get_location_ignores_invalid_battery_level(hass):
	"""Location parsing keeps coordinates when battery metadata is malformed."""
	client = _authenticated_client(hass)
	client._get_session = AsyncMock(
		return_value=FakeSession(
			FakeResponse(
				payload=[
					[None, 1710000000000],
					[
						"child-1",
						"status",
						[
							[32.0853, 34.7818],
							1710000000000,
							25,
							None,
							None,
							None,
							"device-1",
							None,
							["full", "charging"],
						],
					],
				]
			)
		)
	)

	result = await client.async_get_location("child-1")

	assert result is not None
	assert result["latitude"] == 32.0853
	assert result["battery_level"] is None


async def test_daily_screen_time_aggregates_matching_day_sessions(hass):
	"""Daily screen time sums only sessions from the requested date."""
	client = _client(hass)

	result = await client.async_get_daily_screen_time(
		account_id="child-1",
		target_date=datetime(2026, 6, 24),
		data={
			"appUsageSessions": [
				{
					"date": {"year": 2026, "month": 6, "day": 24},
					"usage": "1800.5s",
					"appId": {"androidAppPackageName": "com.video"},
				},
				{
					"date": {"year": 2026, "month": 6, "day": 24},
					"usage": "bad",
					"appId": {"androidAppPackageName": "com.video"},
				},
				{
					"date": {"year": 2026, "month": 6, "day": 24},
					"usage": "60s",
					"appId": {"androidAppPackageName": "com.music"},
				},
				{
					"date": {"year": 2026, "month": 6, "day": 23},
					"usage": "999s",
					"appId": {"androidAppPackageName": "com.old"},
				},
			]
		},
	)

	assert result["total_seconds"] == 1860.5
	assert result["formatted"] == "00:31:00"
	assert result["hours"] == 0
	assert result["minutes"] == 31
	assert result["seconds"] == 0
	assert result["app_breakdown"] == {
		"com.video": 1800.5,
		"com.music": 60.0,
	}


async def test_daily_screen_time_uses_current_date_when_target_missing(
	monkeypatch, hass
):
	"""Daily screen time defaults to today's Home Assistant date."""
	monkeypatch.setattr(
		"custom_components.familylink.client.api.dt_util.now",
		lambda time_zone=None: datetime(2026, 6, 24),
	)
	client = _client(hass)
	client.async_get_apps_and_usage = AsyncMock(
		return_value={
			"appUsageSessions": [
				{
					"date": {"year": 2026, "month": 6, "day": 24},
					"usage": "120s",
					"appId": {"androidAppPackageName": "com.video"},
				},
				{
					"date": {"year": 2026, "month": 6, "day": 23},
					"usage": "999s",
					"appId": {"androidAppPackageName": "com.old"},
				},
			]
		}
	)

	result = await client.async_get_daily_screen_time(account_id="child-1")

	client.async_get_apps_and_usage.assert_awaited_once_with("child-1")
	assert result["date"] == datetime(2026, 6, 24).date()
	assert result["total_seconds"] == 120


async def test_daily_screen_time_reraises_session_expired(hass):
	"""Daily screen time preserves session-expired errors for reauth handling."""
	client = _client(hass)
	client.async_get_apps_and_usage = AsyncMock(
		side_effect=SessionExpiredError("expired")
	)

	with pytest.raises(SessionExpiredError, match="expired"):
		await client.async_get_daily_screen_time(account_id="child-1")


async def test_daily_screen_time_wraps_unexpected_errors(hass):
	"""Unexpected usage fetch errors are surfaced as NetworkError."""
	client = _client(hass)
	client.async_get_apps_and_usage = AsyncMock(side_effect=RuntimeError("boom"))

	with pytest.raises(NetworkError, match="Failed to fetch daily screen time"):
		await client.async_get_daily_screen_time(account_id="child-1")


async def test_cleanup_closes_session_and_clears_cookie_caches(hass):
	"""Cleanup closes the active session and drops cached cookie helpers."""
	client = _client(hass)
	session = SimpleNamespace(close=AsyncMock())
	client._session = session
	client._cookie_dict = {"SAPISID": "cookie"}
	client._cookie_header = "SAPISID=cookie"

	await client.async_cleanup()

	session.close.assert_awaited_once()
	assert client._session is None
	assert not hasattr(client, "_cookie_dict")
	assert not hasattr(client, "_cookie_header")
