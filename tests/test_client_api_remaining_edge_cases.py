"""Remaining edge-case tests for the Family Link API client."""
from __future__ import annotations

import hashlib
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import aiohttp
import pytest

from custom_components.familylink.client import api as api_module
from custom_components.familylink.client.api import FamilyLinkClient
from custom_components.familylink.const import CONF_SCHEDULE_TIMEZONE, DEVICE_LOCK_ACTION
from custom_components.familylink.exceptions import (
	AuthenticationError,
	DeviceControlError,
	NetworkError,
)


def _client(hass) -> FamilyLinkClient:
	"""Return a client configured for offline edge-case tests."""
	return FamilyLinkClient(hass, {CONF_SCHEDULE_TIMEZONE: "UTC"})


def _authenticated_client(hass) -> FamilyLinkClient:
	"""Return an authenticated client with test cookies."""
	client = _client(hass)
	client._cookies = [{"name": "SAPISID", "value": "cookie", "domain": ".google.com"}]
	return client


class FakeResponse:
	"""Async response context manager for client API requests."""

	def __init__(
		self,
		status: int = 200,
		payload: object | None = None,
		text: str = "response text",
		json_error: Exception | None = None,
	) -> None:
		self.status = status
		self._payload = payload if payload is not None else {}
		self._text = text
		self._json_error = json_error

	async def __aenter__(self):
		return self

	async def __aexit__(self, exc_type, exc, tb) -> None:
		return None

	async def json(self):
		if self._json_error is not None:
			raise self._json_error
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
	"""HTTP session fake that records GET and POST calls."""

	def __init__(
		self,
		response: FakeResponse | None = None,
		*,
		get_error: Exception | None = None,
		post_error: Exception | None = None,
	) -> None:
		self.response = response or FakeResponse()
		self.get_error = get_error
		self.post_error = post_error
		self.calls: list[dict[str, object]] = []

	def get(self, url, **kwargs):
		if self.get_error is not None:
			raise self.get_error
		self.calls.append({"method": "GET", "url": url, **kwargs})
		return self.response

	def post(self, url, **kwargs):
		if self.post_error is not None:
			raise self.post_error
		self.calls.append({"method": "POST", "url": url, **kwargs})
		return self.response


async def test_get_session_prefers_google_service_domain_over_regional_sapisid(
	monkeypatch, hass
):
	"""Session auth prefers a Google service host over a regional SAPISID."""
	created_sessions = []

	class FakeClientSession:
		def __init__(self, *, headers, timeout):
			self.headers = headers
			self.timeout = timeout
			self.close = AsyncMock()
			created_sessions.append(self)

	monkeypatch.setattr(
		"custom_components.familylink.client.api.aiohttp.ClientSession",
		FakeClientSession,
	)
	monkeypatch.setattr(
		"custom_components.familylink.client.api.time.time",
		lambda: 1234,
	)
	client = _client(hass)
	client._cookies = [
		{"name": "SAPISID", "value": "regional", "domain": ".google.co.uk"},
		{"name": "SAPISID", "value": '"service"', "domain": ".accounts.google.com"},
	]

	session = await client._get_session()

	expected_hash = hashlib.sha1(
		b"1234 service https://familylink.google.com"
	).hexdigest()
	assert session is created_sessions[0]
	assert session.headers["Authorization"] == f"SAPISIDHASH 1234_{expected_hash}"


@pytest.mark.parametrize("cookies", [None, []])
async def test_get_session_requires_sapisid_when_cookie_data_is_empty(hass, cookies):
	"""Session creation rejects empty auth data before building headers."""
	client = _client(hass)
	client._cookies = cookies

	with pytest.raises(AuthenticationError, match="SAPISID cookie not found"):
		await client._get_session()


async def test_get_family_members_wraps_unexpected_session_errors(hass):
	"""Unexpected family-member failures become NetworkError."""
	client = _authenticated_client(hass)
	client._get_session = AsyncMock(side_effect=RuntimeError("offline"))

	with pytest.raises(NetworkError, match="Failed to fetch family members"):
		await client.async_get_family_members()


async def test_get_apps_and_usage_wraps_unexpected_response_errors(hass):
	"""Unexpected apps-and-usage response failures become NetworkError."""
	client = _authenticated_client(hass)
	client._get_session = AsyncMock(
		return_value=FakeSession(FakeResponse(json_error=ValueError("bad json")))
	)

	with pytest.raises(NetworkError, match="Failed to fetch apps and usage"):
		await client.async_get_apps_and_usage("child-1")


async def test_get_devices_payload_wraps_unexpected_response_errors(hass):
	"""Unexpected device-payload response failures become NetworkError."""
	client = _authenticated_client(hass)
	client._get_session = AsyncMock(
		return_value=FakeSession(FakeResponse(json_error=ValueError("bad json")))
	)

	with pytest.raises(NetworkError, match="Failed to fetch devices"):
		await client.async_get_devices_payload("child-1")


async def test_daily_screen_time_returns_empty_result_without_usage_sessions(hass):
	"""Missing app usage data returns a zeroed screen-time snapshot."""
	client = _client(hass)

	result = await client.async_get_daily_screen_time(
		account_id="child-1",
		target_date=datetime(2026, 6, 24),
		data={},
	)

	assert result == {
		"total_seconds": 0,
		"formatted": "00:00:00",
		"hours": 0,
		"minutes": 0,
		"seconds": 0,
		"app_breakdown": {},
		"date": datetime(2026, 6, 24).date(),
	}


async def test_get_location_keeps_payload_when_timestamp_and_battery_are_invalid(
	monkeypatch, hass
):
	"""Location parsing keeps coordinates when optional metadata is malformed."""

	def raise_bad_timestamp(_value):
		raise ValueError("timestamp out of range")

	monkeypatch.setattr(
		api_module,
		"datetime",
		SimpleNamespace(fromtimestamp=raise_bad_timestamp),
	)
	client = _authenticated_client(hass)
	client._get_session = AsyncMock(
		return_value=FakeSession(
			FakeResponse(
				payload=[
					[None, 999999999999999999],
					[
						"child-1",
						"status",
						[
							[32.0853, 34.7818],
							999999999999999999,
							"25",
							None,
							None,
							None,
							"device-1",
							None,
							["not-a-number", "charging"],
						],
					],
				]
			)
		)
	)

	result = await client.async_get_location("child-1")

	assert result is not None
	assert result["latitude"] == 32.0853
	assert result["longitude"] == 34.7818
	assert result["accuracy"] == 25
	assert result["timestamp"] == 999999999999999999
	assert result["timestamp_iso"] is None
	assert result["battery_level"] is None


async def test_get_location_returns_none_for_unexpected_response_errors(hass):
	"""Unexpected location response errors are swallowed as unavailable location."""
	client = _authenticated_client(hass)
	client._get_session = AsyncMock(
		return_value=FakeSession(FakeResponse(json_error=RuntimeError("bad json")))
	)

	assert await client.async_get_location("child-1") is None


async def test_control_device_raises_device_control_error_when_session_fails(hass):
	"""Device lock/unlock wraps unexpected session errors."""
	client = _authenticated_client(hass)
	client._get_session = AsyncMock(side_effect=RuntimeError("offline"))

	with pytest.raises(DeviceControlError, match="Failed to control device"):
		await client.async_control_device("device-1", DEVICE_LOCK_ACTION, "child-1")


async def test_ring_device_raises_device_control_error_when_write_fails(hass):
	"""Device ring wraps unexpected write errors."""
	client = _authenticated_client(hass)
	client._get_session = AsyncMock(
		return_value=FakeSession(post_error=RuntimeError("write failed"))
	)

	with pytest.raises(DeviceControlError, match="Failed to ring device"):
		await client.async_ring_device("device-1", "child-1")


async def test_add_time_bonus_returns_false_when_session_fails(hass):
	"""Time bonus writes return False on unexpected session errors."""
	client = _authenticated_client(hass)
	client._get_session = AsyncMock(side_effect=RuntimeError("offline"))

	assert await client.async_add_time_bonus(15, "device-1", "child-1") is False
