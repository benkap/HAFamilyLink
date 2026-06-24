"""Tests for Family Link time-limit override actions."""
from __future__ import annotations

from datetime import datetime
import json
from unittest.mock import AsyncMock, call

import pytest

from custom_components.familylink.client import api
from custom_components.familylink.client.api import FamilyLinkClient
from custom_components.familylink.const import CONF_SCHEDULE_TIMEZONE
from custom_components.familylink.exceptions import AuthenticationError


def _authenticated_client(hass) -> FamilyLinkClient:
	"""Return an authenticated client configured for offline override tests."""
	client = FamilyLinkClient(hass, {CONF_SCHEDULE_TIMEZONE: "UTC"})
	client._cookies = [{"name": "SAPISID", "value": "cookie", "domain": ".google.com"}]
	return client


class FakeResponse:
	"""Async response context manager for override requests."""

	def __init__(
		self,
		status: int = 200,
		payload: object | None = None,
		text: str = "response text",
	) -> None:
		self.status = status
		self._payload = payload if payload is not None else {"ok": True}
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
	"""HTTP session fake that records queued GET, PUT, and POST calls."""

	def __init__(
		self,
		*,
		get: list[FakeResponse] | None = None,
		put: list[FakeResponse] | None = None,
		post: list[FakeResponse] | None = None,
	) -> None:
		self._responses = {
			"GET": list(get or [FakeResponse()]),
			"PUT": list(put or [FakeResponse()]),
			"POST": list(post or [FakeResponse()]),
		}
		self.calls: list[dict[str, object]] = []

	def _next_response(self, method: str) -> FakeResponse:
		responses = self._responses[method]
		if responses:
			return responses.pop(0)
		return FakeResponse()

	def get(self, url, **kwargs):
		self.calls.append({"method": "GET", "url": url, **kwargs})
		return self._next_response("GET")

	def put(self, url, **kwargs):
		self.calls.append({"method": "PUT", "url": url, **kwargs})
		return self._next_response("PUT")

	def post(self, url, **kwargs):
		self.calls.append({"method": "POST", "url": url, **kwargs})
		return self._next_response("POST")


def _action_session(client: FamilyLinkClient, **responses):
	"""Attach and return a fake action session."""
	session = FakeSession(**responses)
	client._get_session = AsyncMock(return_value=session)
	return session


def _schooltime_override(
	override_id: str,
	weekday: int,
	rule_id: str,
) -> list[object]:
	"""Build a time-limit override row for schooltime cleanup parsing."""
	return [
		override_id,
		"1000",
		9,
		None,
		None,
		None,
		None,
		None,
		"child-1",
		None,
		None,
		None,
		[2, [8, 0], [23, 59], None, [weekday, rule_id]],
	]


@pytest.mark.parametrize(
	("method_name", "rule_id"),
	[
		("async_enable_bedtime", "bedtime-rule"),
		("async_enable_school_time", "school-rule"),
	],
)
async def test_time_limit_override_actions_require_authentication(
	hass, method_name, rule_id
):
	"""Time-limit override actions reject unauthenticated calls."""
	client = FamilyLinkClient(hass, {CONF_SCHEDULE_TIMEZONE: "UTC"})

	with pytest.raises(AuthenticationError, match="Not authenticated"):
		await getattr(client, method_name)("child-1", rule_id)


async def test_enable_bedtime_posts_weekly_update_and_today_override(hass):
	"""Enabling bedtime sends the weekly update and today's override payload."""
	client = _authenticated_client(hass)
	client.schedule_today = lambda account_id: 1
	client.async_get_time_limit = AsyncMock(
		return_value={
			"bedtime_rule_id": "bedtime-rule",
			"bedtime_schedule": [
				{"day": 1, "start": [20, 45], "end": [6, 15]},
				{"day": 2, "start": [21, 0], "end": [7, 0]},
			],
		}
	)
	session = _action_session(client, put=[FakeResponse()], post=[FakeResponse()])

	assert await client.async_enable_bedtime("child-1") is True

	client.async_get_time_limit.assert_awaited_once_with("child-1")
	assert [request["method"] for request in session.calls] == ["PUT", "POST"]
	weekly_call, override_call = session.calls
	assert weekly_call["url"] == (
		f"{FamilyLinkClient.BASE_URL}/people/child-1/timeLimit:update"
	)
	assert weekly_call["params"] == {"$httpMethod": "PUT"}
	weekly_payload = json.loads(weekly_call["data"])
	assert weekly_payload[1] == "child-1"
	assert weekly_payload[2][4][1] == [["bedtime-rule", 2]]

	assert override_call["url"] == (
		f"{FamilyLinkClient.BASE_URL}/people/child-1/timeLimitOverrides:batchCreate"
	)
	override_payload = json.loads(override_call["data"])
	assert override_payload[1] == "child-1"
	assert override_payload[2][0][2] == 9
	assert override_payload[2][0][12] == [2, [20, 45], [6, 15], "CAEQAQ"]


async def test_disable_bedtime_uses_default_window_when_today_slot_is_missing(hass):
	"""Disabling bedtime falls back to a sane today window when no slot matches."""
	client = _authenticated_client(hass)
	client.schedule_today = lambda account_id: 3
	client.async_get_time_limit = AsyncMock(
		return_value={
			"bedtime_rule_id": "bedtime-rule",
			"bedtime_schedule": [{"day": 1, "start": [20, 45], "end": [6, 15]}],
		}
	)
	session = _action_session(client, put=[FakeResponse()], post=[FakeResponse()])

	assert await client.async_disable_bedtime("child-1") is True

	weekly_payload = json.loads(session.calls[0]["data"])
	override_payload = json.loads(session.calls[1]["data"])
	assert weekly_payload[2][4][1] == [["bedtime-rule", 1]]
	assert override_payload[2][0][12] == [1, [21, 30], [7, 0], "CAEQAw"]


async def test_bedtime_override_returns_false_when_rule_id_is_missing(hass):
	"""Bedtime overrides fail before posting when no rule ID is available."""
	client = _authenticated_client(hass)
	client.async_get_time_limit = AsyncMock(return_value={"bedtime_schedule": []})
	client._get_session = AsyncMock()

	assert await client.async_enable_bedtime("child-1") is False

	client._get_session.assert_not_awaited()


async def test_bedtime_override_returns_false_when_weekly_update_fails(hass):
	"""Bedtime override posting is skipped if the weekly update fails."""
	client = _authenticated_client(hass)
	client.schedule_today = lambda account_id: 1
	client.async_get_time_limit = AsyncMock(
		return_value={"bedtime_rule_id": "bedtime-rule", "bedtime_schedule": []}
	)
	session = _action_session(client, put=[FakeResponse(status=500)])

	assert await client.async_enable_bedtime("child-1") is False
	assert [request["method"] for request in session.calls] == ["PUT"]


async def test_enable_school_time_posts_today_override_from_current_time(
	hass, monkeypatch
):
	"""Enabling school time posts a today override from now until 23:59."""
	monkeypatch.setattr(
		api.dt_util,
		"now",
		lambda time_zone=None: datetime(2026, 6, 22, 10, 5, tzinfo=time_zone),
	)
	client = _authenticated_client(hass)
	client.async_get_time_limit = AsyncMock(return_value={"schooltime_rule_id": "school-rule"})
	session = _action_session(client, post=[FakeResponse()])

	assert await client.async_enable_school_time("child-1") is True

	client.async_get_time_limit.assert_awaited_once_with("child-1")
	assert session.calls == [
		{
			"method": "POST",
			"url": f"{FamilyLinkClient.BASE_URL}/people/child-1/timeLimitOverrides:batchCreate",
			"headers": {
				"Content-Type": "application/json+protobuf",
				"Cookie": "SAPISID=cookie",
			},
			"data": json.dumps([
				None,
				"child-1",
				[[
					None,
					None,
					9,
					None,
					None,
					None,
					None,
					None,
					None,
					None,
					None,
					None,
					[2, [10, 5], [23, 59], None, [1, "school-rule"]],
				]],
				[1],
			]),
		}
	]


async def test_disable_school_time_deletes_existing_overrides_before_posting(
	hass, monkeypatch
):
	"""Disabling school time clears matching overrides before posting action 1."""
	monkeypatch.setattr(
		api.dt_util,
		"now",
		lambda time_zone=None: datetime(2026, 6, 22, 16, 45, tzinfo=time_zone),
	)
	client = _authenticated_client(hass)
	client._async_list_schooltime_overrides_today = AsyncMock(
		return_value=["override-a", "override-b"]
	)
	client._async_delete_time_limit_override = AsyncMock(return_value=True)
	session = _action_session(client, post=[FakeResponse()])

	assert await client.async_disable_school_time("child-1", "school-rule") is True

	client._async_list_schooltime_overrides_today.assert_awaited_once_with(
		"child-1", "school-rule", 1
	)
	client._async_delete_time_limit_override.assert_has_awaits(
		[call("child-1", "override-a"), call("child-1", "override-b")]
	)
	payload = json.loads(session.calls[0]["data"])
	assert payload[2][0][12] == [1, [16, 45], [23, 59], None, [1, "school-rule"]]


async def test_school_time_override_returns_false_when_rule_id_is_missing(hass):
	"""School-time overrides fail before posting when no rule ID is available."""
	client = _authenticated_client(hass)
	client.async_get_time_limit = AsyncMock(return_value={})
	client._get_session = AsyncMock()

	assert await client.async_enable_school_time("child-1") is False

	client._get_session.assert_not_awaited()


async def test_school_time_override_returns_false_on_http_failure(hass, monkeypatch):
	"""School-time override actions return False on non-200 responses."""
	monkeypatch.setattr(
		api.dt_util,
		"now",
		lambda time_zone=None: datetime(2026, 6, 22, 10, 5, tzinfo=time_zone),
	)
	client = _authenticated_client(hass)
	session = _action_session(client, post=[FakeResponse(status=500)])

	assert await client.async_enable_school_time("child-1", "school-rule") is False
	assert len(session.calls) == 1


async def test_list_schooltime_overrides_returns_matching_today_entries(hass):
	"""School-time cleanup lists only overrides for the requested weekday/rule."""
	client = _authenticated_client(hass)
	session = _action_session(
		client,
		get=[
			FakeResponse(
				payload=[
					None,
					[
						[
							_schooltime_override("match-1", 1, "school-rule"),
							_schooltime_override("wrong-day", 2, "school-rule"),
							_schooltime_override("wrong-rule", 1, "other-rule"),
						],
						"ignored",
					],
				]
			)
		],
	)

	result = await client._async_list_schooltime_overrides_today(
		"child-1", "school-rule", 1
	)

	assert result == ["match-1"]
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


async def test_delete_time_limit_override_posts_delete_method_override(hass):
	"""Deleting a time-limit override posts with Google's DELETE override param."""
	client = _authenticated_client(hass)
	session = _action_session(client, post=[FakeResponse()])

	assert await client._async_delete_time_limit_override("child-1", "override-1") is True

	assert session.calls == [
		{
			"method": "POST",
			"url": f"{FamilyLinkClient.BASE_URL}/people/child-1/timeLimitOverride/override-1",
			"headers": {
				"Content-Type": "application/json+protobuf",
				"Cookie": "SAPISID=cookie",
			},
			"params": {"$httpMethod": "DELETE"},
		}
	]


async def test_delete_time_limit_override_rejects_unsafe_override_id(hass):
	"""Deleting an override rejects unsafe IDs before URL interpolation."""
	client = _authenticated_client(hass)
	session = _action_session(client)

	assert await client._async_delete_time_limit_override("child-1", "bad/id") is False
	assert session.calls == []
