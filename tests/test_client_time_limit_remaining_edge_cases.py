"""Focused remaining edge-case tests for Family Link time-limit client paths."""
from __future__ import annotations

from datetime import datetime, timezone
import logging
from unittest.mock import AsyncMock, call

import pytest

from custom_components.familylink.client import api
from custom_components.familylink.client.api import FamilyLinkClient
from custom_components.familylink.const import CONF_SCHEDULE_TIMEZONE
from custom_components.familylink.exceptions import (
    AuthenticationError,
    ScheduleUpdatePartialError,
)


def _authenticated_client(hass) -> FamilyLinkClient:
    """Return an authenticated client configured for offline client tests."""
    client = FamilyLinkClient(hass, {CONF_SCHEDULE_TIMEZONE: "UTC"})
    client._cookies = [{"name": "SAPISID", "value": "cookie", "domain": ".google.com"}]
    return client


class FakeResponse:
    """Async response context manager for API requests."""

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
    """HTTP session fake that records GET calls."""

    def __init__(self, *, get: list[FakeResponse] | None = None) -> None:
        self._get_responses = list(get or [FakeResponse()])
        self.calls: list[dict[str, object]] = []

    def get(self, url, **kwargs):
        self.calls.append({"method": "GET", "url": url, **kwargs})
        if self._get_responses:
            return self._get_responses.pop(0)
        return FakeResponse()


def _attach_get_session(client: FamilyLinkClient, response: FakeResponse) -> FakeSession:
    """Attach and return a fake GET session."""
    session = FakeSession(get=[response])
    client._get_session = AsyncMock(return_value=session)
    return session


def _device_row(
    *items,
    device_id: str = "device-1",
    override: list[object] | None = None,
    pos19_ms: str | None = None,
    used_ms: str | None = None,
) -> list[object]:
    """Build the sparse appliedTimeLimits device row shape."""
    row: list[object] = [None] * 26
    row[0] = override
    for index, item in enumerate(items, start=1):
        row[index] = item
    if pos19_ms is not None:
        row[19] = pos19_ms
    if used_ms is not None:
        row[20] = used_ms
    row[25] = device_id
    return row


async def test_block_device_for_school_merges_custom_whitelist_without_duplicate_work(
    hass,
    monkeypatch,
):
    """Custom whitelist entries merge with defaults and duplicate packages are updated once."""
    client = _authenticated_client(hass)
    client.async_get_apps_and_usage = AsyncMock(
        return_value={
            "apps": [
                {
                    "title": "Maps",
                    "packageName": "com.google.android.apps.maps",
                    "supervisionSetting": {"hidden": True},
                },
                {
                    "title": "School",
                    "packageName": "com.example.school",
                    "supervisionSetting": {"hidden": True},
                },
                {
                    "title": "Game",
                    "packageName": "com.example.game",
                    "supervisionSetting": {"hidden": False},
                },
            ]
        }
    )
    client.async_unblock_app = AsyncMock(return_value=True)
    client.async_block_app = AsyncMock(return_value=True)
    sleep = AsyncMock()
    monkeypatch.setattr(api.asyncio, "sleep", sleep)

    result = await client.async_block_device_for_school(
        "child-1",
        whitelist=[
            "com.google.android.apps.maps",
            "com.example.school",
            "com.example.school",
        ],
    )

    assert result["blocked_apps"] == [{"name": "Game", "package": "com.example.game"}]
    assert result["unblocked_apps"] == [
        {"name": "Maps", "package": "com.google.android.apps.maps"},
        {"name": "School", "package": "com.example.school"},
    ]
    assert result["failed_apps"] == []
    assert result["whitelisted_count"] == 12
    client.async_unblock_app.assert_has_awaits(
        [
            call("com.google.android.apps.maps", "child-1"),
            call("com.example.school", "child-1"),
        ]
    )
    client.async_block_app.assert_awaited_once_with("com.example.game", "child-1")
    assert client.async_unblock_app.await_count == 2
    assert sleep.await_count == 3


async def test_applied_time_limits_logs_position_19_and_uses_position_20_for_used_minutes(
    hass,
    caplog,
):
    """Position 19 is debug-only; used minutes still come from position 20."""
    client = _authenticated_client(hass)
    client.schedule_today = lambda account_id: 1
    _attach_get_session(
        client,
        FakeResponse(
            payload=[
                None,
                [
                    _device_row(
                        ["CAEQAQ", 1, 2, 90, "created", "updated"],
                        pos19_ms="2700000",
                        used_ms="1200000",
                    )
                ],
            ]
        ),
    )

    with caplog.at_level(logging.DEBUG):
        result = await client.async_get_applied_time_limits("child-1")

    device = result["devices"]["device-1"]
    assert device["used_minutes"] == 20
    assert device["daily_limit_remaining"] == 70
    assert "Position 19 contains 45 minutes" in caplog.text


async def test_applied_time_limits_parses_uuid_daily_limit_and_window_tuples(
    hass,
    monkeypatch,
):
    """UUID-shaped schedule rows are parsed as active daily, bedtime, then schooltime data."""

    def fixed_now(time_zone=None):
        return datetime(2026, 6, 22, 10, 30, tzinfo=time_zone or timezone.utc)

    monkeypatch.setattr(api.dt_util, "now", fixed_now)
    client = _authenticated_client(hass)
    client.schedule_today = lambda account_id: 1
    _attach_get_session(
        client,
        FakeResponse(
            payload=[
                None,
                [
                    _device_row(
                        [
                            "11111111-1111-4111-8111-111111111111",
                            1,
                            2,
                            75,
                            "created",
                            "updated",
                        ],
                        [
                            "22222222-2222-4222-8222-222222222222",
                            1,
                            2,
                            [9, 0],
                            [17, 0],
                            "created",
                            "updated",
                            "bedtime",
                        ],
                        [
                            "33333333-3333-4333-8333-333333333333",
                            1,
                            2,
                            [8, 0],
                            [14, 0],
                            "created",
                            "updated",
                            "schooltime",
                        ],
                        used_ms="1500000",
                    )
                ],
            ]
        ),
    )

    result = await client.async_get_applied_time_limits("child-1")

    device = result["devices"]["device-1"]
    assert device["daily_limit_enabled"] is True
    assert device["daily_limit_minutes"] == 75
    assert device["used_minutes"] == 25
    assert device["remaining_minutes"] == 50
    assert device["bedtime_window_start"] == "09:00"
    assert device["bedtime_window_end"] == "17:00"
    assert device["bedtime_active"] is True
    assert device["schooltime_window"] is not None
    assert device["schooltime_active"] is True
    assert result["bedtime_enabled_today"] is True
    assert result["schooltime_enabled_today"] is True


async def test_applied_time_limits_marks_prefixed_bedtime_and_schooltime_windows_active(
    hass,
    monkeypatch,
):
    """CAEQ and CAMQ 8-element rows both mark today's active applied windows."""

    def fixed_now(time_zone=None):
        return datetime(2026, 6, 22, 11, 0, tzinfo=time_zone or timezone.utc)

    monkeypatch.setattr(api.dt_util, "now", fixed_now)
    client = _authenticated_client(hass)
    client.schedule_today = lambda account_id: 1
    _attach_get_session(
        client,
        FakeResponse(
            payload=[
                None,
                [
                    _device_row(
                        ["CAEQ-bed", 1, 2, [9, 0], [17, 0], "created", "updated", "bed"],
                        ["CAMQ-school", 1, 2, [8, 0], [14, 0], "created", "updated", "school"],
                    )
                ],
            ]
        ),
    )

    result = await client.async_get_applied_time_limits("child-1")

    device = result["devices"]["device-1"]
    assert device["bedtime_window_start"] == "09:00"
    assert device["bedtime_window_end"] == "17:00"
    assert device["bedtime_active"] is True
    assert device["schooltime_window"] is not None
    assert device["schooltime_active"] is True
    assert result["bedtime_enabled_today"] is True
    assert result["schooltime_enabled_today"] is True


async def test_applied_time_limits_parses_epoch_window_pairs_and_ignores_bad_pair(hass):
    """Epoch-ms pairs become bedtime/schooltime windows; malformed pairs are ignored."""
    client = _authenticated_client(hass)
    bedtime_start = 1_781_972_400_000
    bedtime_end = 1_781_983_200_000
    school_start = 1_781_936_000_000
    school_end = 1_781_954_000_000
    _attach_get_session(
        client,
        FakeResponse(
            payload=[
                None,
                [
                    _device_row(
                        ["not-ms", str(bedtime_end)],
                        [str(bedtime_start), str(bedtime_end)],
                        [school_start, school_end],
                    )
                ],
            ]
        ),
    )

    result = await client.async_get_applied_time_limits("child-1")

    device = result["devices"]["device-1"]
    assert device["bedtime_window"] == {
        "start_ms": bedtime_start,
        "end_ms": bedtime_end,
    }
    assert device["schooltime_window"] == {
        "start_ms": school_start,
        "end_ms": school_end,
    }
    assert device["bedtime_active"] is True
    assert device["schooltime_active"] is True
    assert result["bedtime_enabled_today"] is True
    assert result["schooltime_enabled_today"] is True


async def test_time_limit_parser_applies_today_override_with_malformed_timestamp(
    hass,
    monkeypatch,
):
    """Malformed override timestamps do not crash and still fall through the parser."""

    def fixed_now(time_zone=None):
        return datetime(2026, 6, 22, 12, 0, tzinfo=time_zone or timezone.utc)

    monkeypatch.setattr(api.dt_util, "now", fixed_now)
    bedtime_rule_id = "b" * 32
    client = _authenticated_client(hass)
    _attach_get_session(
        client,
        FakeResponse(
            payload=[
                ["metadata"],
                [
                    [
                        2,
                        [["CAEQAQ", 1, 2, [21, 0], [6, 30], "1", "2", "bed"]],
                        "created",
                        "updated",
                        1,
                    ],
                    [[2, [6, 0], [], "created", "updated"]],
                    [
                        [
                            "bad-timestamp",
                            "not-ms",
                            9,
                            None,
                            None,
                            None,
                            [1, [21, 0], [6, 30], "CAEQAQ"],
                        ]
                    ],
                    None,
                    [1],
                    [[bedtime_rule_id, 1, 2, [123, 0]]],
                ],
            ]
        ),
    )

    result = await client.async_get_time_limit("child-1")

    assert result["bedtime_enabled"] is True
    assert result["bedtime_enabled_today"] is False
    assert result["bedtime_today_source"] == "today_override"
    assert result["bedtime_today_override_action"] == 1


SCHEDULE_HELPER_CASES = [
    (
        "async_set_bedtime_schedule",
        (1,),
        {"start_time": "21:00", "end_time": "06:30", "enabled": True},
        "bedtime schedule for day 1",
        "bedtime schedule enabled state for day 1",
    ),
    (
        "async_set_daily_limit_schedule",
        (1,),
        {"daily_minutes": 90, "enabled": True},
        "daily limit schedule for day 1",
        "daily limit schedule enabled state for day 1",
    ),
]


@pytest.mark.parametrize(
    ("method_name", "args", "kwargs", "_first_description", "_second_description"),
    SCHEDULE_HELPER_CASES,
)
async def test_recurring_schedule_helpers_require_authentication(
    hass,
    method_name,
    args,
    kwargs,
    _first_description,
    _second_description,
):
    """Recurring schedule writes reject unauthenticated callers."""
    client = FamilyLinkClient(hass, {CONF_SCHEDULE_TIMEZONE: "UTC"})

    with pytest.raises(AuthenticationError, match="Not authenticated"):
        await getattr(client, method_name)(*args, **kwargs)


@pytest.mark.parametrize(
    ("method_name", "args", "kwargs", "_first_description", "_second_description"),
    SCHEDULE_HELPER_CASES,
)
async def test_recurring_schedule_helpers_resolve_default_child(
    hass,
    method_name,
    args,
    kwargs,
    _first_description,
    _second_description,
):
    """Recurring schedule writes resolve the default child before building payloads."""
    client = _authenticated_client(hass)
    client.async_get_supervised_child_id = AsyncMock(return_value="default-child")
    client._async_update_time_limit = AsyncMock(return_value=True)

    assert await getattr(client, method_name)(*args, **kwargs) is True

    client.async_get_supervised_child_id.assert_awaited_once_with()
    assert client._async_update_time_limit.await_count == 2
    assert all(
        update_call.args[0] == "default-child"
        for update_call in client._async_update_time_limit.await_args_list
    )


@pytest.mark.parametrize(
    ("method_name", "args", "kwargs", "_first_description", "_second_description"),
    SCHEDULE_HELPER_CASES,
)
async def test_recurring_schedule_helpers_return_false_on_first_write_failure(
    hass,
    method_name,
    args,
    kwargs,
    _first_description,
    _second_description,
):
    """A first recurring schedule sub-write failure returns False without a partial error."""
    client = _authenticated_client(hass)
    client._async_update_time_limit = AsyncMock(return_value=False)

    assert await getattr(client, method_name)(*args, account_id="child-1", **kwargs) is False
    assert client._async_update_time_limit.await_count == 1


@pytest.mark.parametrize(
    ("method_name", "args", "kwargs", "first_description", "second_description"),
    SCHEDULE_HELPER_CASES,
)
async def test_recurring_schedule_helpers_raise_partial_on_second_write_failure(
    hass,
    method_name,
    args,
    kwargs,
    first_description,
    second_description,
):
    """A failed second recurring schedule sub-write reports the successful first step."""
    client = _authenticated_client(hass)
    client._async_update_time_limit = AsyncMock(side_effect=[True, False])

    with pytest.raises(ScheduleUpdatePartialError) as exc:
        await getattr(client, method_name)(*args, account_id="child-1", **kwargs)

    assert exc.value.successful_updates == [first_description]
    assert exc.value.failed_update == second_description
    assert client._async_update_time_limit.await_count == 2
