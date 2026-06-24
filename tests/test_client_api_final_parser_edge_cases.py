"""Final focused parser edge-case tests for the Family Link API client."""
from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock

from custom_components.familylink.client import api
from custom_components.familylink.client.api import FamilyLinkClient
from custom_components.familylink.const import CONF_SCHEDULE_TIMEZONE


def _authenticated_client(hass) -> FamilyLinkClient:
    """Return an authenticated client configured for offline parser tests."""
    client = FamilyLinkClient(hass, {CONF_SCHEDULE_TIMEZONE: "UTC"})
    client._cookies = [{"name": "SAPISID", "value": "cookie", "domain": ".google.com"}]
    return client


class FakeResponse:
    """Async response context manager for API requests."""

    def __init__(self, payload: object) -> None:
        self.status = 200
        self._payload = payload

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None

    async def json(self):
        return self._payload

    async def text(self):
        return "response text"


class FakeSession:
    """HTTP session fake that records API calls."""

    def __init__(self, response: FakeResponse) -> None:
        self.response = response
        self.calls: list[dict[str, object]] = []

    def get(self, url, **kwargs):
        self.calls.append({"method": "GET", "url": url, **kwargs})
        return self.response


def _attach_get_session(client: FamilyLinkClient, payload: object) -> FakeSession:
    """Attach and return a fake GET session."""
    session = FakeSession(FakeResponse(payload))
    client._get_session = AsyncMock(return_value=session)
    return session


async def test_time_limit_parser_skips_today_override_without_caeq_payload(
    hass,
    monkeypatch,
):
    """Malformed type-9 rows do not block a later valid bedtime override."""

    def fixed_now(time_zone=None):
        return datetime(2026, 6, 22, 12, 0, tzinfo=time_zone)

    monkeypatch.setattr(api.dt_util, "now", fixed_now)
    bedtime_rule_id = "b" * 32
    client = _authenticated_client(hass)
    _attach_get_session(
        client,
        [
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
                        "malformed-no-caeq",
                        "5000",
                        9,
                        None,
                        None,
                        None,
                        ["not", "a", "bedtime", "payload"],
                        [2, [21, 0], [6, 30], 123],
                    ],
                    [
                        "valid-disable",
                        "1000",
                        9,
                        None,
                        None,
                        None,
                        [1, [21, 0], [6, 30], "CAEQAQ"],
                    ],
                ],
                None,
                [1],
                [[bedtime_rule_id, 1, 2, [123, 0]]],
            ],
        ],
    )

    result = await client.async_get_time_limit("child-1")

    assert result["bedtime_enabled"] is True
    assert result["bedtime_enabled_today"] is False
    assert result["bedtime_today_source"] == "today_override"
    assert result["bedtime_today_override_action"] == 1


async def test_enable_bedtime_returns_false_for_invalid_today_without_posting(hass):
    """Invalid schedule_today values fail before building the today override."""
    client = _authenticated_client(hass)
    client.schedule_today = lambda account_id: 8
    client.async_get_time_limit = AsyncMock(
        return_value={
            "bedtime_rule_id": "bedtime-rule",
            "bedtime_schedule": [{"day": 1, "start": [20, 45], "end": [6, 15]}],
        }
    )
    client._get_session = AsyncMock()

    assert await client.async_enable_bedtime("child-1") is False

    client.async_get_time_limit.assert_awaited_once_with("child-1")
    client._get_session.assert_not_awaited()
