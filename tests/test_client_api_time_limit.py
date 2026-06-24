"""Tests for Family Link time-limit endpoint parsing."""
from __future__ import annotations

from datetime import datetime
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
	"""Return an authenticated client configured for offline time-limit tests."""
	client = FamilyLinkClient(hass, {CONF_SCHEDULE_TIMEZONE: "UTC"})
	client._cookies = [{"name": "SAPISID", "value": "cookie", "domain": ".google.com"}]
	return client


class FakeResponse:
	"""Async response context manager for time-limit GET requests."""

	def __init__(
		self,
		status: int = 200,
		payload: object | None = None,
		text: str = "response text",
		json_error: Exception | None = None,
	) -> None:
		self.status = status
		self._payload = payload if payload is not None else [None, []]
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


class FakeSession:
	"""HTTP session fake that records time-limit GET calls."""

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


def _empty_time_limit_result() -> dict[str, object]:
	"""Return the empty result used for non-fatal time-limit failures."""
	return {
		"bedtime_enabled": False,
		"school_time_enabled": False,
		"bedtime_enabled_today": None,
		"bedtime_schedule": [],
		"school_time_schedule": [],
		"daily_limit_schedule": [],
		"bedtime_rule_id": None,
		"schooltime_rule_id": None,
	}


async def test_time_limit_requires_authentication(hass):
	"""Time-limit fetches reject unauthenticated calls."""
	client = FamilyLinkClient(hass, {CONF_SCHEDULE_TIMEZONE: "UTC"})

	with pytest.raises(AuthenticationError, match="Not authenticated"):
		await client.async_get_time_limit("child-1")


async def test_time_limit_fetches_default_child_and_parses_schedules(
	hass, monkeypatch
):
	"""Time-limit fetches parse schedules, revisions, and today's override."""
	monkeypatch.setattr(
		api.dt_util,
		"now",
		lambda time_zone=None: datetime(2026, 6, 22, 12, 0, tzinfo=time_zone),
	)
	bedtime_rule_id = "b" * 32
	schooltime_rule_id = "s" * 32
	response_data = [
		["metadata"],
		[
			[
				2,
				[
					["CAEQAQ", 1, 2, [21, 0], [6, 30], "1", "2", "bed"],
					["CAMQAQ", 1, 2, [8, 15], [13, 45], "1", "2", "school"],
					["CAEQAg", 2, 1, [22, 0], [7, 0], "1", "2", "bed"],
				],
				"created",
				"updated",
				1,
			],
			[[
				2,
				[6, 0],
				[
					["CAEQAQ", 1, 2, 120, "1", "2"],
					["CAEQAg", 2, 1, 45, "1", "2"],
				],
				"created",
				"updated",
			]],
			[
				[
					"older",
					"1000",
					9,
					None,
					None,
					None,
					[1, [21, 0], [6, 30], "CAEQAQ"],
				],
				[
					"newer",
					"2000",
					9,
					None,
					None,
					None,
					[2, [21, 0], [6, 30], "CAEQAQ"],
				],
				[
					"other-day",
					"3000",
					9,
					None,
					None,
					None,
					[1, [21, 0], [6, 30], "CAEQAg"],
				],
			],
			None,
			[1],
			[
				[bedtime_rule_id, 1, 2, [123, 0]],
				[schooltime_rule_id, 2, 1, [124, 0]],
			],
		],
	]
	client = _authenticated_client(hass)
	client.async_get_supervised_child_id = AsyncMock(return_value="child-1")
	session = _get_session(client, FakeResponse(payload=response_data))

	result = await client.async_get_time_limit()

	client.async_get_supervised_child_id.assert_awaited_once()
	assert session.calls == [
		{
			"method": "GET",
			"url": f"{FamilyLinkClient.BASE_URL}/people/child-1/timeLimit",
			"params": [
				("capabilities", "TIME_LIMIT_CLIENT_CAPABILITY_SCHOOLTIME"),
				("timeLimitKey.type", "SUPERVISED_DEVICES"),
			],
			"headers": {
				"Content-Type": "application/json+protobuf",
				"Cookie": "SAPISID=cookie",
			},
		}
	]
	assert result["bedtime_enabled"] is True
	assert result["school_time_enabled"] is False
	assert result["bedtime_enabled_today"] is True
	assert result["bedtime_today_source"] == "today_override"
	assert result["bedtime_today_override_action"] == 2
	assert result["schedule_today"] == 1
	assert result["schedule_timezone"] == "UTC"
	assert result["schedule_timezone_source"] == "config"
	assert result["google_schedule_timezone"] is None
	assert result["bedtime_rule_id"] == bedtime_rule_id
	assert result["schooltime_rule_id"] == schooltime_rule_id
	assert result["bedtime_schedule"] == [
		{
			"day": 1,
			"day_name": "Monday",
			"enabled": True,
			"start": [21, 0],
			"end": [6, 30],
			"state_flag": 2,
		},
		{
			"day": 2,
			"day_name": "Tuesday",
			"enabled": False,
			"start": [22, 0],
			"end": [7, 0],
			"state_flag": 1,
		},
	]
	assert result["school_time_schedule"] == [
		{
			"day": 1,
			"day_name": "Monday",
			"enabled": True,
			"start": [8, 15],
			"end": [13, 45],
			"state_flag": 2,
		}
	]
	assert result["daily_limit_schedule"] == [
		{
			"day": 1,
			"day_name": "Monday",
			"enabled": True,
			"minutes": 120,
			"state_flag": 2,
		},
		{
			"day": 2,
			"day_name": "Tuesday",
			"enabled": False,
			"minutes": 45,
			"state_flag": 1,
		},
	]


@pytest.mark.parametrize("status", [403, 503, 500])
async def test_time_limit_returns_empty_result_for_non_200_statuses(hass, status):
	"""Non-auth HTTP failures return an empty time-limit snapshot."""
	client = _authenticated_client(hass)
	_get_session(client, FakeResponse(status=status))

	assert await client.async_get_time_limit("child-1") == _empty_time_limit_result()


async def test_time_limit_raises_session_expired_on_401(hass):
	"""A 401 response is surfaced as a session-expired error."""
	client = _authenticated_client(hass)
	_get_session(client, FakeResponse(status=401))

	with pytest.raises(SessionExpiredError, match="Session expired"):
		await client.async_get_time_limit("child-1")


async def test_time_limit_returns_empty_result_for_malformed_payload(hass):
	"""Malformed successful payloads return an empty time-limit snapshot."""
	client = _authenticated_client(hass)
	_get_session(client, FakeResponse(payload={"unexpected": True}))

	assert await client.async_get_time_limit("child-1") == _empty_time_limit_result()


@pytest.mark.parametrize(
	"payload",
	[
		[["metadata"], []],
		[["metadata"], [[], [], [], None, [], []]],
		[
			["metadata"],
			[
				[2],
				[[2, [6, 0], []]],
				["ignore"],
				None,
				[1],
				[["too-short"], ["not-a-uuid", 1, 2, [123, 0]]],
			],
		],
	],
)
async def test_time_limit_returns_default_structure_for_sparse_payloads(
	hass, monkeypatch, payload
):
	"""Sparse successful payloads return defaults without crashing."""
	monkeypatch.setattr(
		api.dt_util,
		"now",
		lambda time_zone=None: datetime(2026, 6, 22, 12, 0, tzinfo=time_zone),
	)
	client = _authenticated_client(hass)
	_get_session(client, FakeResponse(payload=payload))

	assert await client.async_get_time_limit("child-1") == {
		"bedtime_enabled": False,
		"school_time_enabled": False,
		"bedtime_enabled_today": False,
		"bedtime_today_source": "weekly",
		"bedtime_today_override_action": None,
		"schedule_today": 1,
		"schedule_timezone": "UTC",
		"schedule_timezone_source": "config",
		"google_schedule_timezone": None,
		"bedtime_schedule": [],
		"school_time_schedule": [],
		"daily_limit_schedule": [],
		"bedtime_rule_id": None,
		"schooltime_rule_id": None,
	}


async def test_time_limit_wraps_unexpected_errors_as_network_error(hass):
	"""Unexpected response parsing errors are wrapped for callers."""
	client = _authenticated_client(hass)
	_get_session(client, FakeResponse(json_error=RuntimeError("bad json")))

	with pytest.raises(NetworkError, match="bad json"):
		await client.async_get_time_limit("child-1")
