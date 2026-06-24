"""Tests for Family Link API client action endpoints."""
from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import aiohttp
import pytest

from custom_components.familylink.client.api import FamilyLinkClient
from custom_components.familylink.const import (
	CONF_SCHEDULE_TIMEZONE,
	DEVICE_LOCK_ACTION,
	DEVICE_RING_ACTION_CODE,
	DEVICE_UNLOCK_ACTION,
)
from custom_components.familylink.exceptions import (
	AuthenticationError,
	DeviceControlError,
	SessionExpiredError,
)


def _authenticated_client(hass) -> FamilyLinkClient:
	"""Return an authenticated client configured for offline action tests."""
	client = FamilyLinkClient(hass, {CONF_SCHEDULE_TIMEZONE: "UTC"})
	client._cookies = [{"name": "SAPISID", "value": "cookie", "domain": ".google.com"}]
	return client


class FakeResponse:
	"""Async response context manager for action requests."""

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
	"""HTTP session fake that records mutation calls."""

	def __init__(self, response: FakeResponse) -> None:
		self.response = response
		self.calls: list[dict[str, object]] = []

	def post(self, url, **kwargs):
		self.calls.append({"method": "POST", "url": url, **kwargs})
		return self.response

	def put(self, url, **kwargs):
		self.calls.append({"method": "PUT", "url": url, **kwargs})
		return self.response


def _action_session(client: FamilyLinkClient, response: FakeResponse | None = None):
	"""Attach and return a fake session."""
	session = FakeSession(response or FakeResponse())
	client._get_session = AsyncMock(return_value=session)
	return session


@pytest.mark.parametrize(
	("method_name", "args", "expected_payload"),
	[
		(
			"async_block_app",
			("com.example.game", "child-1"),
			["child-1", [[["com.example.game"], [1]]]],
		),
		(
			"async_unblock_app",
			("com.example.game", "child-1"),
			["child-1", [[["com.example.game"], []]]],
		),
		(
			"async_set_app_daily_limit",
			("com.example.game", 30, "child-1"),
			["child-1", [[["com.example.game"], None, [30, 1]]]],
		),
		(
			"async_set_app_daily_limit",
			("com.example.game", -1, "child-1"),
			["child-1", [[["com.example.game"]]]],
		),
		(
			"async_set_app_daily_limit",
			("com.example.game", -2, "child-1"),
			["child-1", [[["com.example.game"], None, None, [1]]]],
		),
	],
)
async def test_app_restriction_actions_post_expected_payloads(
	hass, method_name, args, expected_payload
):
	"""App restriction helpers post the payload shape Google expects."""
	client = _authenticated_client(hass)
	session = _action_session(client)

	assert await getattr(client, method_name)(*args) is True

	assert session.calls == [
		{
			"method": "POST",
			"url": f"{FamilyLinkClient.BASE_URL}/people/child-1/apps:updateRestrictions",
			"headers": {
				"Content-Type": "application/json+protobuf",
				"Cookie": "SAPISID=cookie",
			},
			"data": json.dumps(expected_payload),
		}
	]


async def test_app_restriction_actions_use_first_child_when_not_provided(hass):
	"""App restriction helpers resolve the first supervised child when needed."""
	client = _authenticated_client(hass)
	session = _action_session(client)
	client.async_get_supervised_child_id = AsyncMock(return_value="child-1")

	assert await client.async_block_app("com.example.game") is True

	client.async_get_supervised_child_id.assert_awaited_once()
	assert session.calls[0]["url"].endswith("/people/child-1/apps:updateRestrictions")


async def test_app_restriction_actions_require_authentication(hass):
	"""App restriction helpers reject unauthenticated calls."""
	client = FamilyLinkClient(hass, {CONF_SCHEDULE_TIMEZONE: "UTC"})

	with pytest.raises(AuthenticationError, match="Not authenticated"):
		await client.async_block_app("com.example.game", "child-1")


async def test_app_restriction_action_raises_session_expired_on_401(hass):
	"""A 401 app restriction response is surfaced as a session-expired error."""
	client = _authenticated_client(hass)
	_action_session(client, FakeResponse(status=401))

	with pytest.raises(SessionExpiredError, match="Session expired"):
		await client.async_block_app("com.example.game", "child-1")


async def test_app_restriction_action_returns_false_for_non_401_failure(hass):
	"""Non-auth app restriction failures return False for service callers."""
	client = _authenticated_client(hass)
	_action_session(client, FakeResponse(status=500))

	assert await client.async_set_app_daily_limit("com.example.game", 30, "child-1") is False


async def test_app_restriction_action_returns_false_for_unexpected_error(hass):
	"""Unexpected app restriction failures return False."""
	client = _authenticated_client(hass)
	client._get_session = AsyncMock(side_effect=RuntimeError("offline"))

	assert await client.async_unblock_app("com.example.game", "child-1") is False


async def test_block_device_for_school_blocks_and_unblocks_expected_apps(
	hass, monkeypatch
):
	"""School mode blocks non-whitelisted apps and unblocks whitelisted apps."""
	client = _authenticated_client(hass)
	client.async_get_apps_and_usage = AsyncMock(
		return_value={
			"apps": [
				{
					"title": "Settings",
					"packageName": "com.android.settings",
					"supervisionSetting": {"hidden": True},
				},
				{
					"title": "Game",
					"packageName": "com.example.game",
					"supervisionSetting": {"hidden": False},
				},
				{
					"title": "Already Blocked",
					"packageName": "com.example.blocked",
					"supervisionSetting": {"hidden": True},
				},
			]
		}
	)
	client.async_block_app = AsyncMock(return_value=True)
	client.async_unblock_app = AsyncMock(return_value=True)
	sleep = AsyncMock()
	monkeypatch.setattr("custom_components.familylink.client.api.asyncio.sleep", sleep)

	result = await client.async_block_device_for_school("child-1")

	assert result["blocked_apps"] == [{"name": "Game", "package": "com.example.game"}]
	assert result["unblocked_apps"] == [
		{"name": "Settings", "package": "com.android.settings"}
	]
	assert result["failed_count"] == 0
	client.async_block_app.assert_awaited_once_with("com.example.game", "child-1")
	client.async_unblock_app.assert_awaited_once_with(
		"com.android.settings", "child-1"
	)
	assert sleep.await_count == 2


async def test_unblock_all_apps_only_unblocks_hidden_apps(hass, monkeypatch):
	"""Unlock-all skips apps that are already visible."""
	client = _authenticated_client(hass)
	client.async_get_apps_and_usage = AsyncMock(
		return_value={
			"apps": [
				{
					"title": "Hidden",
					"packageName": "com.example.hidden",
					"supervisionSetting": {"hidden": True},
				},
				{
					"title": "Visible",
					"packageName": "com.example.visible",
					"supervisionSetting": {"hidden": False},
				},
			]
		}
	)
	client.async_unblock_app = AsyncMock(return_value=True)
	sleep = AsyncMock()
	monkeypatch.setattr("custom_components.familylink.client.api.asyncio.sleep", sleep)

	result = await client.async_unblock_all_apps("child-1")

	assert result == {
		"unblocked_count": 1,
		"unblocked_apps": [{"name": "Hidden", "package": "com.example.hidden"}],
		"failed_count": 0,
		"failed_apps": [],
	}
	client.async_unblock_app.assert_awaited_once_with("com.example.hidden", "child-1")
	sleep.assert_awaited_once_with(0.1)


@pytest.mark.parametrize(
	("action", "action_code"),
	[
		(DEVICE_LOCK_ACTION, 1),
		(DEVICE_UNLOCK_ACTION, 4),
	],
)
async def test_control_device_posts_lock_and_unlock_payloads(hass, action, action_code):
	"""Device lock/unlock actions post time-limit override payloads."""
	client = _authenticated_client(hass)
	session = _action_session(client)

	assert await client.async_control_device("device-1", action, "child-1") is True

	assert session.calls == [
		{
			"method": "POST",
			"url": f"{FamilyLinkClient.BASE_URL}/people/child-1/timeLimitOverrides:batchCreate",
			"headers": {
				"Content-Type": "application/json+protobuf",
				"Cookie": "SAPISID=cookie",
			},
			"data": json.dumps(
				[None, "child-1", [[None, None, action_code, "device-1"]], [1]]
			),
		}
	]


async def test_control_device_rejects_invalid_action(hass):
	"""Device control validates the requested action before posting."""
	client = _authenticated_client(hass)

	with pytest.raises(DeviceControlError, match="Invalid action"):
		await client.async_control_device("device-1", "pause", "child-1")


async def test_control_device_returns_false_on_http_failure(hass):
	"""Device control HTTP failures return False."""
	client = _authenticated_client(hass)
	_action_session(client, FakeResponse(status=500))

	assert await client.async_control_device("device-1", DEVICE_LOCK_ACTION, "child-1") is False


@pytest.mark.parametrize(
	("method_name", "args"),
	[
		("async_control_device", ("device-1", DEVICE_LOCK_ACTION, "child-1")),
		("async_ring_device", ("device-1", "child-1")),
		("async_add_time_bonus", (15, "device-1", "child-1")),
		("async_cancel_time_bonus", ("override-1", "child-1")),
	],
)
async def test_device_actions_require_authentication(hass, method_name, args):
	"""Device mutation helpers reject unauthenticated calls."""
	client = FamilyLinkClient(hass, {CONF_SCHEDULE_TIMEZONE: "UTC"})

	with pytest.raises(AuthenticationError, match="Not authenticated"):
		await getattr(client, method_name)(*args)


@pytest.mark.parametrize(
	("method_name", "args", "expected_url"),
	[
		(
			"async_control_device",
			("device-1", DEVICE_LOCK_ACTION),
			f"{FamilyLinkClient.BASE_URL}/people/child-1/timeLimitOverrides:batchCreate",
		),
		(
			"async_ring_device",
			("device-1",),
			f"{FamilyLinkClient.BASE_URL}/people/child-1/devices/device-1:executeRemoteAction",
		),
		(
			"async_add_time_bonus",
			(15, "device-1"),
			f"{FamilyLinkClient.BASE_URL}/people/child-1/timeLimitOverrides:batchCreate",
		),
		(
			"async_cancel_time_bonus",
			("override-1",),
			f"{FamilyLinkClient.BASE_URL}/people/child-1/timeLimitOverride/override-1?$httpMethod=DELETE",
		),
	],
)
async def test_device_actions_use_first_child_when_not_provided(
	hass, method_name, args, expected_url
):
	"""Device mutation helpers resolve the first supervised child when needed."""
	client = _authenticated_client(hass)
	session = _action_session(client)
	client.async_get_supervised_child_id = AsyncMock(return_value="child-1")

	assert await getattr(client, method_name)(*args) is True

	client.async_get_supervised_child_id.assert_awaited_once()
	assert session.calls[0]["url"] == expected_url


async def test_ring_device_posts_remote_action_payload(hass):
	"""Device ring posts the executeRemoteAction payload."""
	client = _authenticated_client(hass)
	session = _action_session(client)

	assert await client.async_ring_device("device-1", "child-1") is True

	assert session.calls == [
		{
			"method": "POST",
			"url": f"{FamilyLinkClient.BASE_URL}/people/child-1/devices/device-1:executeRemoteAction",
			"headers": {
				"Content-Type": "application/json+protobuf",
				"Cookie": "SAPISID=cookie",
			},
			"data": json.dumps(
				[None, "child-1", "device-1", [DEVICE_RING_ACTION_CODE, None, "device-1", 0]]
			),
		}
	]


async def test_ring_device_validates_device_id(hass):
	"""Device ring rejects unsafe device IDs before URL interpolation."""
	client = _authenticated_client(hass)

	with pytest.raises(ValueError, match="Invalid device_id"):
		await client.async_ring_device("device/1", "child-1")


@pytest.mark.parametrize(
	("method_name", "args"),
	[
		("async_ring_device", ("device-1", "child-1")),
		("async_add_time_bonus", (15, "device-1", "child-1")),
		("async_cancel_time_bonus", ("override-1", "child-1")),
	],
)
async def test_device_actions_return_false_on_http_failure(
	hass, method_name, args
):
	"""Non-control device action HTTP failures return False."""
	client = _authenticated_client(hass)
	_action_session(client, FakeResponse(status=500))

	assert await getattr(client, method_name)(*args) is False


async def test_add_time_bonus_posts_seconds_payload(hass):
	"""Time bonuses convert minutes to seconds in the override payload."""
	client = _authenticated_client(hass)
	session = _action_session(client)

	assert await client.async_add_time_bonus(15, "device-1", "child-1") is True

	payload = json.loads(session.calls[0]["data"])
	assert session.calls[0]["url"] == (
		f"{FamilyLinkClient.BASE_URL}/people/child-1/timeLimitOverrides:batchCreate"
	)
	assert payload[1] == "child-1"
	assert payload[2][0][2] == 10
	assert payload[2][0][3] == "device-1"
	assert payload[2][0][13] == [["900", 0]]


async def test_cancel_time_bonus_posts_delete_override_url(hass):
	"""Cancelling a bonus uses Google's POST-with-method-override URL."""
	client = _authenticated_client(hass)
	session = _action_session(client)

	assert await client.async_cancel_time_bonus("override-1", "child-1") is True

	assert session.calls == [
		{
			"method": "POST",
			"url": f"{FamilyLinkClient.BASE_URL}/people/child-1/timeLimitOverride/override-1?$httpMethod=DELETE",
			"headers": {
				"Content-Type": "application/json+protobuf",
				"Cookie": "SAPISID=cookie",
			},
		}
	]


async def test_cancel_time_bonus_rejects_unsafe_override_id_without_posting(hass):
	"""Cancelling a bonus validates the override ID before posting."""
	client = _authenticated_client(hass)
	session = _action_session(client)

	assert await client.async_cancel_time_bonus("override/1", "child-1") is False
	assert session.calls == []


@pytest.mark.parametrize(
	("method_name", "status_code"),
	[
		("async_enable_daily_limit", 2),
		("async_disable_daily_limit", 1),
	],
)
async def test_daily_limit_toggle_posts_time_limit_update(
	hass, method_name, status_code
):
	"""Daily limit toggles send PUT updates with method override params."""
	client = _authenticated_client(hass)
	session = _action_session(client)

	assert await getattr(client, method_name)("child-1") is True

	assert session.calls == [
		{
			"method": "PUT",
			"url": f"{FamilyLinkClient.BASE_URL}/people/child-1/timeLimit:update",
			"headers": {
				"Content-Type": "application/json+protobuf",
				"Cookie": "SAPISID=cookie",
			},
			"data": json.dumps(
				[None, "child-1", [None, [[status_code, None, None, None]]], None, [1]]
			),
			"params": {"$httpMethod": "PUT"},
		}
	]


async def test_set_daily_limit_posts_today_override(hass):
	"""Setting today's daily limit posts a type-8 override for today's day code."""
	client = _authenticated_client(hass)
	client.schedule_today = lambda account_id: 1
	session = _action_session(client)

	assert await client.async_set_daily_limit(90, "device-1", "child-1") is True

	payload = json.loads(session.calls[0]["data"])
	assert session.calls[0]["url"] == (
		f"{FamilyLinkClient.BASE_URL}/people/child-1/timeLimitOverrides:batchCreate"
	)
	assert payload[1] == "child-1"
	assert payload[2][0][2] == 8
	assert payload[2][0][3] == "device-1"
	assert payload[2][0][11] == [2, 90, "CAEQAQ"]


async def test_set_bedtime_posts_today_override(hass):
	"""Setting bedtime posts a type-9 override with parsed times and day code."""
	client = _authenticated_client(hass)
	session = _action_session(client)

	assert await client.async_set_bedtime("21:15", "06:30", 1, "child-1") is True

	payload = json.loads(session.calls[0]["data"])
	assert session.calls[0]["url"] == (
		f"{FamilyLinkClient.BASE_URL}/people/child-1/timeLimitOverrides:batchCreate"
	)
	assert payload[1] == "child-1"
	assert payload[2][0][2] == 9
	assert payload[2][0][12] == [2, [21, 15], [6, 30], "CAEQAQ"]


@pytest.mark.parametrize(
	("start_time", "end_time", "day"),
	[
		("bad", "06:30", 1),
		("21:15", "06:30", 8),
	],
)
async def test_set_bedtime_returns_false_for_invalid_input(
	hass, start_time, end_time, day
):
	"""Invalid bedtime inputs return False without posting."""
	client = _authenticated_client(hass)
	session = _action_session(client)

	assert await client.async_set_bedtime(start_time, end_time, day, "child-1") is False
	assert session.calls == []
