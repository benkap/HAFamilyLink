"""Tests for applied time-limit parsing in the Family Link API client."""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest

from custom_components.familylink.client import api
from custom_components.familylink.client.api import FamilyLinkClient
from custom_components.familylink.const import CONF_SCHEDULE_TIMEZONE
from custom_components.familylink.exceptions import (
	AuthenticationError,
	NetworkError,
	SessionExpiredError,
)


def _authenticated_client(hass) -> FamilyLinkClient:
	"""Return an authenticated client configured for offline parser tests."""
	client = FamilyLinkClient(hass, {CONF_SCHEDULE_TIMEZONE: "UTC"})
	client._cookies = [{"name": "SAPISID", "value": "cookie", "domain": ".google.com"}]
	return client


class FakeResponse:
	"""Async response context manager for applied time-limit requests."""

	def __init__(
		self,
		status: int = 200,
		payload: object | None = None,
		text: str = "response text",
	) -> None:
		self.status = status
		self._payload = payload if payload is not None else [None, []]
		self._text = text

	async def __aenter__(self):
		return self

	async def __aexit__(self, exc_type, exc, tb) -> None:
		return None

	async def json(self):
		return self._payload

	async def text(self):
		return self._text


class FakeSession:
	"""HTTP session fake that records applied time-limit GET calls."""

	def __init__(self, response: FakeResponse) -> None:
		self.response = response
		self.calls: list[dict[str, object]] = []

	def get(self, url, **kwargs):
		self.calls.append({"method": "GET", "url": url, **kwargs})
		return self.response


def _get_session(client: FamilyLinkClient, response: FakeResponse | None = None):
	"""Attach and return a fake GET session."""
	session = FakeSession(response or FakeResponse())
	client._get_session = AsyncMock(return_value=session)
	return session


def _device_row(
	*items,
	device_id: str = "device-1",
	override: list[object] | None = None,
	used_ms: str | None = None,
) -> list[object]:
	"""Build the sparse appliedTimeLimits row shape used by the client parser."""
	row: list[object] = [None] * 26
	row[0] = override
	for index, item in enumerate(items, start=1):
		row[index] = item
	if used_ms is not None:
		row[20] = used_ms
	row[25] = device_id
	return row


async def test_applied_time_limits_fetches_expected_endpoint_with_default_child(
	hass,
):
	"""Applied time-limit fetches resolve the first child and send capability params."""
	client = _authenticated_client(hass)
	client.async_get_supervised_child_id = AsyncMock(return_value="child-1")
	session = _get_session(client)

	assert await client.async_get_applied_time_limits() == {
		"device_lock_states": {},
		"devices": {},
		"bedtime_enabled_today": False,
		"schooltime_enabled_today": False,
	}

	client.async_get_supervised_child_id.assert_awaited_once()
	assert session.calls == [
		{
			"method": "GET",
			"url": f"{FamilyLinkClient.BASE_URL}/people/child-1/appliedTimeLimits",
			"params": [("capabilities", "TIME_LIMIT_CLIENT_CAPABILITY_SCHOOLTIME")],
			"headers": {
				"Content-Type": "application/json+protobuf",
				"Cookie": "SAPISID=cookie",
			},
		}
	]


async def test_applied_time_limits_parse_daily_limit_bonus_and_windows(
	hass, monkeypatch
):
	"""Parser extracts daily limits, bonus replacement time, and today windows."""
	monkeypatch.setattr(
		api.dt_util,
		"now",
		lambda time_zone=None: datetime(2026, 6, 22, 22, 0, tzinfo=timezone.utc),
	)
	client = _authenticated_client(hass)
	client.schedule_today = lambda account_id: 1
	bonus_override = [
		"bonus-override-1",
		"1000",
		10,
		"device-1",
		None,
		None,
		None,
		None,
		None,
		None,
		None,
		None,
		None,
		[["900", 0]],
	]
	_get_session(
		client,
		FakeResponse(
			payload=[
				None,
				[
					_device_row(
						["CAEQAQ", 1, 2, 120, "created", "updated"],
						["CAEQ-bed", 1, 2, [21, 0], [6, 30], "created", "updated", "bed"],
						["CAMQ-school", 1, 2, [8, 30], [15, 0], "created", "updated", "school"],
						device_id="device-1",
						override=bonus_override,
						used_ms="3600000",
					)
				],
			]
		),
	)

	result = await client.async_get_applied_time_limits("child-1")

	assert result["device_lock_states"] == {"device-1": False}
	assert result["bedtime_enabled_today"] is True
	assert result["schooltime_enabled_today"] is True
	device = result["devices"]["device-1"]
	assert device["daily_limit_enabled"] is True
	assert device["daily_limit_minutes"] == 120
	assert device["used_minutes"] == 60
	assert device["daily_limit_remaining"] == 60
	assert device["bonus_override_id"] == "bonus-override-1"
	assert device["bonus_minutes"] == 15
	assert device["total_allowed_minutes"] == 15
	assert device["remaining_minutes"] == 15
	assert device["bedtime_window_start"] == "21:00"
	assert device["bedtime_window_end"] == "06:30"
	assert device["bedtime_active"] is True
	assert device["schooltime_window"] is not None
	assert device["schooltime_active"] is False


async def test_applied_time_limits_parse_lock_state_and_non_bonus_remaining(
	hass,
):
	"""Lock state and regular remaining time are parsed when no bonus exists."""
	client = _authenticated_client(hass)
	client.schedule_today = lambda account_id: 1
	lock_override = ["lock-override-1", "1000", 1, "device-1"]
	_get_session(
		client,
		FakeResponse(
			payload=[
				None,
				[
					_device_row(
						["CAEQAQ", 1, 2, 90, "created", "updated"],
						device_id="device-1",
						override=lock_override,
						used_ms="1800000",
					)
				],
			]
		),
	)

	result = await client.async_get_applied_time_limits("child-1")

	assert result["device_lock_states"] == {"device-1": True}
	device = result["devices"]["device-1"]
	assert device["daily_limit_enabled"] is True
	assert device["daily_limit_minutes"] == 90
	assert device["used_minutes"] == 30
	assert device["daily_limit_remaining"] == 60
	assert device["total_allowed_minutes"] == 90
	assert device["remaining_minutes"] == 60
	assert device["bonus_minutes"] == 0
	assert device["bonus_override_id"] is None


@pytest.mark.parametrize(
	("status", "expected_error"),
	[
		(401, SessionExpiredError),
		(500, NetworkError),
	],
)
async def test_applied_time_limits_raise_for_http_failures(
	hass, status, expected_error
):
	"""HTTP failures surface as session-expired or network errors."""
	client = _authenticated_client(hass)
	_get_session(client, FakeResponse(status=status))

	with pytest.raises(expected_error):
		await client.async_get_applied_time_limits("child-1")


async def test_applied_time_limits_require_authentication(hass):
	"""Applied time-limit fetches reject unauthenticated calls."""
	client = FamilyLinkClient(hass, {CONF_SCHEDULE_TIMEZONE: "UTC"})

	with pytest.raises(AuthenticationError, match="Not authenticated"):
		await client.async_get_applied_time_limits("child-1")
