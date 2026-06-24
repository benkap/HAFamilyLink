"""Enabled-only recurring schedule write failure edge cases."""
from __future__ import annotations

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


@pytest.mark.parametrize(
    ("method_name", "kwargs", "description"),
    [
        (
            "async_set_bedtime_schedule",
            {"enabled": True},
            "bedtime schedule enabled state for day 2",
        ),
        (
            "async_set_daily_limit_schedule",
            {"enabled": True},
            "daily limit schedule enabled state for day 2",
        ),
    ],
)
async def test_enabled_only_schedule_first_write_failure_returns_false(
    hass,
    method_name,
    kwargs,
    description,
):
    """Enabled-only first sub-write failures return False, not partial errors."""
    client = _authenticated_client(hass)
    client._async_update_time_limit = AsyncMock(return_value=False)

    try:
        result = await getattr(client, method_name)(
            2,
            account_id="child-1",
            **kwargs,
        )
    except ScheduleUpdatePartialError as err:
        pytest.fail(f"Enabled-only write should not raise partial error: {err}")

    assert result is False
    client._async_update_time_limit.assert_awaited_once()
    assert client._async_update_time_limit.await_args.args[0] == "child-1"
    assert client._async_update_time_limit.await_args.args[2] == description
