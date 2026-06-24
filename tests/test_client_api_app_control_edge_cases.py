"""Focused edge-case tests for app-control Family Link API helpers."""
from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, call

import aiohttp
import pytest

from custom_components.familylink.client.api import FamilyLinkClient
from custom_components.familylink.const import CONF_SCHEDULE_TIMEZONE
from custom_components.familylink.exceptions import (
	AuthenticationError,
	SessionExpiredError,
)


def _authenticated_client(hass) -> FamilyLinkClient:
	"""Return an authenticated client configured for offline app-control tests."""
	client = FamilyLinkClient(hass, {CONF_SCHEDULE_TIMEZONE: "UTC"})
	client._cookies = [{"name": "SAPISID", "value": "cookie", "domain": ".google.com"}]
	return client


class FakeResponse:
	"""Async response context manager for app-control requests."""

	def __init__(self, status: int = 200, payload: object | None = None) -> None:
		self.status = status
		self._payload = payload if payload is not None else {"ok": True}

	async def __aenter__(self):
		return self

	async def __aexit__(self, exc_type, exc, tb) -> None:
		return None

	async def json(self):
		return self._payload

	async def text(self):
		return "response text"

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
	"""HTTP session fake that records POST calls."""

	def __init__(
		self,
		response: FakeResponse | None = None,
		*,
		post_error: Exception | None = None,
	) -> None:
		self.response = response or FakeResponse()
		self.post_error = post_error
		self.calls: list[dict[str, object]] = []

	def post(self, url, **kwargs):
		if self.post_error is not None:
			raise self.post_error
		self.calls.append({"method": "POST", "url": url, **kwargs})
		return self.response


def _attach_session(client: FamilyLinkClient, response: FakeResponse | None = None):
	"""Attach and return a fake HTTP session."""
	session = FakeSession(response)
	client._get_session = AsyncMock(return_value=session)
	return session


APP_CONTROL_CASES = [
	("async_block_app", ("com.example.game",), ["child-1", [[["com.example.game"], [1]]]]),
	(
		"async_unblock_app",
		("com.example.game",),
		["child-1", [[["com.example.game"], []]]],
	),
	(
		"async_set_app_daily_limit",
		("com.example.game", 45),
		["child-1", [[["com.example.game"], None, [45, 1]]]],
	),
]


@pytest.mark.parametrize(("method_name", "args", "_expected_payload"), APP_CONTROL_CASES)
async def test_app_control_actions_require_authentication(
	hass,
	method_name,
	args,
	_expected_payload,
):
	"""App-control helpers reject unauthenticated calls before building requests."""
	client = FamilyLinkClient(hass, {CONF_SCHEDULE_TIMEZONE: "UTC"})

	with pytest.raises(AuthenticationError, match="Not authenticated"):
		await getattr(client, method_name)(*args)


@pytest.mark.parametrize(("method_name", "args", "expected_payload"), APP_CONTROL_CASES)
async def test_app_control_actions_resolve_default_child(
	hass,
	method_name,
	args,
	expected_payload,
):
	"""App-control helpers use the supervised child when account_id is omitted."""
	client = _authenticated_client(hass)
	session = _attach_session(client)
	client.async_get_supervised_child_id = AsyncMock(return_value="child-1")

	assert await getattr(client, method_name)(*args) is True

	client.async_get_supervised_child_id.assert_awaited_once()
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


@pytest.mark.parametrize(("method_name", "args", "_expected_payload"), APP_CONTROL_CASES)
async def test_app_control_actions_raise_session_expired_on_401(
	hass,
	method_name,
	args,
	_expected_payload,
):
	"""401 app-control responses force re-authentication."""
	client = _authenticated_client(hass)
	_attach_session(client, FakeResponse(status=401))

	with pytest.raises(SessionExpiredError, match="Session expired"):
		await getattr(client, method_name)(*args, "child-1")


@pytest.mark.parametrize(("method_name", "args", "_expected_payload"), APP_CONTROL_CASES)
async def test_app_control_actions_return_false_for_non_401_response(
	hass,
	method_name,
	args,
	_expected_payload,
):
	"""Non-auth app-control response failures are reported as False."""
	client = _authenticated_client(hass)
	_attach_session(client, FakeResponse(status=503))

	assert await getattr(client, method_name)(*args, "child-1") is False


@pytest.mark.parametrize(("method_name", "args", "_expected_payload"), APP_CONTROL_CASES)
async def test_app_control_actions_return_false_for_unexpected_errors(
	hass,
	method_name,
	args,
	_expected_payload,
):
	"""Unexpected app-control request failures are swallowed as False."""
	client = _authenticated_client(hass)
	client._get_session = AsyncMock(side_effect=RuntimeError("offline"))

	assert await getattr(client, method_name)(*args, "child-1") is False


async def test_block_device_for_school_tracks_unblocked_blocked_failed_and_skipped_apps(
	hass,
	monkeypatch,
):
	"""School mode updates only needed apps and records failed writes."""
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
					"title": "Contacts",
					"packageName": "com.android.contacts",
					"supervisionSetting": {"hidden": True},
				},
				{
					"title": "Dialer",
					"packageName": "com.android.dialer",
					"supervisionSetting": {"hidden": False},
				},
				{
					"title": "Already Blocked",
					"packageName": "com.example.already_blocked",
					"supervisionSetting": {"hidden": True},
				},
				{
					"title": "Game",
					"packageName": "com.example.game",
					"supervisionSetting": {"hidden": False},
				},
				{
					"title": "Video",
					"packageName": "com.example.video",
					"supervisionSetting": {"hidden": False},
				},
			]
		}
	)
	client.async_unblock_app = AsyncMock(
		side_effect=lambda package_name, _account_id: package_name == "com.android.settings"
	)
	client.async_block_app = AsyncMock(
		side_effect=lambda package_name, _account_id: package_name == "com.example.game"
	)
	sleep = AsyncMock()
	monkeypatch.setattr("custom_components.familylink.client.api.asyncio.sleep", sleep)

	result = await client.async_block_device_for_school("child-1")

	assert result["blocked_apps"] == [{"name": "Game", "package": "com.example.game"}]
	assert result["unblocked_apps"] == [
		{"name": "Settings", "package": "com.android.settings"}
	]
	assert result["failed_apps"] == ["com.android.contacts", "com.example.video"]
	assert result["blocked_count"] == 1
	assert result["unblocked_count"] == 1
	assert result["failed_count"] == 2
	client.async_unblock_app.assert_has_awaits(
		[
			call("com.android.settings", "child-1"),
			call("com.android.contacts", "child-1"),
		]
	)
	client.async_block_app.assert_has_awaits(
		[
			call("com.example.game", "child-1"),
			call("com.example.video", "child-1"),
		]
	)
	assert sleep.await_count == 4


async def test_unblock_all_apps_records_hidden_app_failures(hass, monkeypatch):
	"""Unlock-all reports hidden apps that fail to unblock."""
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
	client.async_unblock_app = AsyncMock(return_value=False)
	sleep = AsyncMock()
	monkeypatch.setattr("custom_components.familylink.client.api.asyncio.sleep", sleep)

	result = await client.async_unblock_all_apps("child-1")

	assert result == {
		"unblocked_count": 0,
		"unblocked_apps": [],
		"failed_count": 1,
		"failed_apps": ["com.example.hidden"],
	}
	client.async_unblock_app.assert_awaited_once_with("com.example.hidden", "child-1")
	sleep.assert_awaited_once_with(0.1)


async def test_set_bedtime_returns_false_for_invalid_default_day_without_posting(hass):
	"""Bedtime writes reject an invalid schedule_today value before posting."""
	client = _authenticated_client(hass)
	session = _attach_session(client)
	client.schedule_today = lambda account_id: 8

	assert await client.async_set_bedtime("21:15", "06:30", account_id="child-1") is False
	assert session.calls == []
