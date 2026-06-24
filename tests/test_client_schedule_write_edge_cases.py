"""Edge-case tests for Family Link schedule-write API helpers."""
from __future__ import annotations

import json
import logging
from unittest.mock import AsyncMock

import pytest

from custom_components.familylink.client.api import FamilyLinkClient
from custom_components.familylink.const import CONF_SCHEDULE_TIMEZONE
from custom_components.familylink.exceptions import ScheduleUpdatePartialError


def _authenticated_client(hass) -> FamilyLinkClient:
	"""Return an authenticated client configured for offline write tests."""
	client = FamilyLinkClient(hass, {CONF_SCHEDULE_TIMEZONE: "UTC"})
	client._cookies = [{"name": "SAPISID", "value": "cookie", "domain": ".google.com"}]
	return client


class FakeResponse:
	"""Async response context manager for schedule-write requests."""

	def __init__(
		self,
		status: int = 200,
		payload: object | None = None,
		text: str = "response text",
		json_error: Exception | None = None,
	) -> None:
		self.status = status
		self._payload = payload if payload is not None else {"ok": True}
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
	"""HTTP session fake that records queued GET, PUT, and POST calls."""

	def __init__(
		self,
		*,
		get: list[FakeResponse] | None = None,
		put: list[FakeResponse] | None = None,
		post: list[FakeResponse] | None = None,
		put_error: Exception | None = None,
		post_error: Exception | None = None,
	) -> None:
		self._responses = {
			"GET": list(get or [FakeResponse()]),
			"PUT": list(put or [FakeResponse()]),
			"POST": list(post or [FakeResponse()]),
		}
		self._errors = {"PUT": put_error, "POST": post_error}
		self.calls: list[dict[str, object]] = []

	def _next_response(self, method: str) -> FakeResponse:
		error = self._errors.get(method)
		if error is not None:
			raise error
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


class RaisingCloseSession:
	"""Session fake whose close raises after recording the call."""

	def __init__(self) -> None:
		self.close_count = 0

	async def close(self) -> None:
		self.close_count += 1
		raise RuntimeError("close failed")


def _attach_session(client: FamilyLinkClient, session: FakeSession) -> FakeSession:
	"""Attach and return a fake HTTP session."""
	client._get_session = AsyncMock(return_value=session)
	return session


def _schooltime_override_row(
	override_id: object = "override-1",
	payload: object | None = None,
) -> list[object]:
	"""Build a sparse school-time override row."""
	row: list[object] = [None] * 13
	row[0] = override_id
	row[12] = payload if payload is not None else [
		2,
		[8, 0],
		[23, 59],
		None,
		[1, "school-rule"],
	]
	return row


@pytest.mark.parametrize(
	"kwargs",
	[
		{"start_time": "21:00"},
		{"end_time": "06:30"},
		{},
	],
)
async def test_bedtime_schedule_rejects_incomplete_or_missing_update(hass, kwargs):
	"""Bedtime schedule writes require a complete window or enabled state."""
	client = _authenticated_client(hass)
	client._async_update_time_limit = AsyncMock()

	assert await client.async_set_bedtime_schedule(
		1,
		account_id="child-1",
		**kwargs,
	) is False
	client._async_update_time_limit.assert_not_awaited()


@pytest.mark.parametrize(
	("day", "kwargs"),
	[
		(0, {"start_time": "21:00", "end_time": "06:30"}),
		(8, {"enabled": True}),
		(1, {"start_time": "bad", "end_time": "06:30"}),
		(1, {"start_time": "21:00", "end_time": "24:00"}),
		(1, {"enabled": "yes"}),
	],
)
async def test_bedtime_schedule_returns_false_for_invalid_values(hass, day, kwargs):
	"""Invalid bedtime schedule values fail before posting a write."""
	client = _authenticated_client(hass)
	client._async_update_time_limit = AsyncMock()

	assert await client.async_set_bedtime_schedule(
		day,
		account_id="child-1",
		**kwargs,
	) is False
	client._async_update_time_limit.assert_not_awaited()


async def test_daily_limit_schedule_requires_a_requested_change(hass):
	"""Daily limit schedule writes reject calls that request no change."""
	client = _authenticated_client(hass)
	client._async_update_time_limit = AsyncMock()

	assert await client.async_set_daily_limit_schedule(
		1,
		account_id="child-1",
	) is False
	client._async_update_time_limit.assert_not_awaited()


@pytest.mark.parametrize(
	("day", "kwargs"),
	[
		(0, {"daily_minutes": 90}),
		(8, {"enabled": True}),
		(1, {"daily_minutes": -1}),
		(1, {"daily_minutes": 1441}),
		(1, {"daily_minutes": True}),
		(1, {"enabled": "yes"}),
	],
)
async def test_daily_limit_schedule_returns_false_for_invalid_values(hass, day, kwargs):
	"""Invalid daily limit schedule values fail before posting a write."""
	client = _authenticated_client(hass)
	client._async_update_time_limit = AsyncMock()

	assert await client.async_set_daily_limit_schedule(
		day,
		account_id="child-1",
		**kwargs,
	) is False
	client._async_update_time_limit.assert_not_awaited()


async def test_daily_limit_schedule_enabled_only_updates_one_field(hass):
	"""Enabled-only daily limit writes post only the enabled-state payload."""
	client = _authenticated_client(hass)
	client._async_update_time_limit = AsyncMock(return_value=True)

	assert await client.async_set_daily_limit_schedule(
		5,
		enabled=False,
		account_id="child-1",
	) is True

	client._async_update_time_limit.assert_awaited_once_with(
		"child-1",
		[
			None,
			"child-1",
			[None, [[2, None, [["CAEQBQ", 1]], None]]],
			None,
			[1],
		],
		"daily limit schedule enabled state for day 5",
	)


async def test_daily_limit_schedule_raises_partial_when_second_write_fails(hass):
	"""A failed enabled-state write raises after daily minutes were updated."""
	client = _authenticated_client(hass)
	client._async_update_time_limit = AsyncMock(side_effect=[True, False])

	with pytest.raises(ScheduleUpdatePartialError) as exc:
		await client.async_set_daily_limit_schedule(
			1,
			daily_minutes=90,
			enabled=True,
			account_id="child-1",
		)

	assert exc.value.successful_updates == ["daily limit schedule for day 1"]
	assert exc.value.failed_update == "daily limit schedule enabled state for day 1"
	assert client._async_update_time_limit.await_count == 2


def test_raise_partial_schedule_update_logs_first_failure(hass, caplog):
	"""A first failed sub-write is logged without raising a partial error."""
	client = _authenticated_client(hass)

	with caplog.at_level(logging.ERROR):
		assert client._raise_partial_schedule_update([], "daily limit") is None

	assert "Failed to update daily limit" in caplog.text


def test_raise_partial_schedule_update_raises_after_success(hass):
	"""A failure after any successful sub-write is surfaced as partial."""
	client = _authenticated_client(hass)

	with pytest.raises(ScheduleUpdatePartialError) as exc:
		client._raise_partial_schedule_update(["window"], "enabled state")

	assert exc.value.successful_updates == ["window"]
	assert exc.value.failed_update == "enabled state"


async def test_update_time_limit_returns_false_for_non_200_response(hass):
	"""Recurring schedule writes return False for non-200 Google responses."""
	client = _authenticated_client(hass)
	session = _attach_session(
		client,
		FakeSession(put=[FakeResponse(status=503, text="try later")]),
	)

	assert await client._async_update_time_limit(
		"child-1",
		["payload"],
		"daily limit",
	) is False

	assert session.calls == [
		{
			"method": "PUT",
			"url": f"{FamilyLinkClient.BASE_URL}/people/child-1/timeLimit:update",
			"headers": {
				"Content-Type": "application/json+protobuf",
				"Cookie": "SAPISID=cookie",
			},
			"data": json.dumps(["payload"]),
			"params": {"$httpMethod": "PUT"},
		}
	]


async def test_update_time_limit_returns_false_for_unexpected_exception(hass):
	"""Unexpected recurring schedule write errors are reported as False."""
	client = _authenticated_client(hass)
	client._get_session = AsyncMock(side_effect=RuntimeError("session exploded"))

	assert await client._async_update_time_limit(
		"child-1",
		["payload"],
		"daily limit",
	) is False
	client._get_session.assert_awaited_once()


@pytest.mark.parametrize(
	"payload",
	[
		None,
		[],
		[None],
		[None, "not-a-list"],
		[
			None,
			[
				"not-a-list-element",
				[
					["too-short"],
					_schooltime_override_row(123),
					_schooltime_override_row("bad-payload", "not-a-list"),
					_schooltime_override_row("short-payload", [2, [8, 0]]),
					_schooltime_override_row(
						"bad-rule-ref",
						[2, [8, 0], [23, 59], None, "school-rule"],
					),
					_schooltime_override_row(
						"wrong-day",
						[2, [8, 0], [23, 59], None, [2, "school-rule"]],
					),
					_schooltime_override_row(
						"wrong-rule",
						[2, [8, 0], [23, 59], None, [1, "other-rule"]],
					),
				],
			],
		],
	],
)
async def test_list_schooltime_overrides_ignores_malformed_payloads(hass, payload):
	"""School-time cleanup treats malformed time-limit payloads as no matches."""
	client = _authenticated_client(hass)
	_attach_session(client, FakeSession(get=[FakeResponse(payload=payload)]))

	assert await client._async_list_schooltime_overrides_today(
		"child-1",
		"school-rule",
		1,
	) == []


async def test_list_schooltime_overrides_returns_empty_when_json_parse_fails(hass):
	"""School-time cleanup is best-effort when a successful read is malformed."""
	client = _authenticated_client(hass)
	_attach_session(
		client,
		FakeSession(get=[FakeResponse(json_error=RuntimeError("bad json"))]),
	)

	assert await client._async_list_schooltime_overrides_today(
		"child-1",
		"school-rule",
		1,
	) == []


async def test_delete_time_limit_override_returns_false_on_post_exception(hass):
	"""Delete cleanup returns False when the POST itself fails."""
	client = _authenticated_client(hass)
	session = _attach_session(
		client,
		FakeSession(post_error=RuntimeError("offline")),
	)

	assert await client._async_delete_time_limit_override(
		"child-1",
		"override-1",
	) is False
	assert [request["method"] for request in session.calls] == ["POST"]


async def test_cleanup_swallows_close_errors_and_clears_cached_session(hass):
	"""Cleanup always clears session and cached cookie helpers."""
	client = _authenticated_client(hass)
	session = RaisingCloseSession()
	client._session = session
	client._cookie_dict = {"SAPISID": "cookie"}
	client._cookie_header = "SAPISID=cookie"

	await client.async_cleanup()

	assert session.close_count == 1
	assert client._session is None
	assert not hasattr(client, "_cookie_dict")
	assert not hasattr(client, "_cookie_header")
