"""Tests for remaining Family Link coordinator fetch edge cases."""
from __future__ import annotations

from copy import deepcopy
import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from custom_components.familylink.coordinator import FamilyLinkDataUpdateCoordinator
from custom_components.familylink.exceptions import SessionExpiredError

from conftest import TEST_CHILD_ID, TEST_DEVICE_ID


def _supervised_child(
	child_id: str = TEST_CHILD_ID,
	child_name: str = "Alex",
) -> dict[str, object]:
	"""Return one supervised family member."""
	return {
		"userId": child_id,
		"memberSupervisionInfo": {"isSupervisedMember": True},
		"profile": {"displayName": child_name},
	}


def _coordinator(hass, mock_config_entry) -> FamilyLinkDataUpdateCoordinator:
	"""Create a coordinator without building a real API client."""
	return FamilyLinkDataUpdateCoordinator(hass, mock_config_entry)


def _client(**overrides) -> SimpleNamespace:
	"""Return a fake API client with coordinator-facing methods."""
	client = SimpleNamespace(
		async_get_family_members=AsyncMock(
			return_value={"members": [_supervised_child()]}
		),
		async_get_apps_and_usage=AsyncMock(
			return_value={
				"apps": [{"title": "YouTube", "packageName": "com.google.android.youtube"}],
				"deviceInfo": [
					{
						"deviceId": TEST_DEVICE_ID,
						"displayInfo": {
							"friendlyName": "Pixel Tablet",
							"model": "Pixel Tablet",
						},
					}
				],
				"appUsageSessions": [],
			}
		),
		async_update_google_schedule_timezone_from_devices=AsyncMock(),
		async_get_time_limit=AsyncMock(
			return_value={
				"bedtime_enabled": True,
				"school_time_enabled": False,
				"bedtime_enabled_today": True,
				"bedtime_today_source": "weekly",
				"bedtime_schedule": [],
				"school_time_schedule": [],
				"daily_limit_schedule": [],
				"schedule_today": 1,
				"schedule_timezone": "UTC",
				"schedule_timezone_source": "google",
			}
		),
		async_get_applied_time_limits=AsyncMock(
			return_value={
				"device_lock_states": {TEST_DEVICE_ID: False},
				"devices": {},
				"bedtime_enabled_today": True,
				"schooltime_enabled_today": False,
			}
		),
		async_get_daily_screen_time=AsyncMock(
			return_value={
				"total_seconds": 0,
				"formatted": "00:00:00",
				"hours": 0,
				"minutes": 0,
				"seconds": 0,
				"app_breakdown": {},
			}
		),
		async_get_location=AsyncMock(return_value=None),
		async_refresh_session=AsyncMock(),
		schedule_today=lambda account_id=None: 1,
	)
	for name, value in overrides.items():
		setattr(client, name, value)
	return client


async def test_update_data_returns_last_known_data_for_unexpected_exception(
	hass, mock_config_entry, sample_coordinator_data
):
	"""Unexpected non-FamilyLink fetch errors keep the cached payload alive."""
	coordinator = _coordinator(hass, mock_config_entry)
	cached_data = deepcopy(sample_coordinator_data)
	coordinator._last_known_data = cached_data
	coordinator._async_fetch_data = AsyncMock(side_effect=ValueError("weird failure"))

	result = await coordinator._async_update_data()

	assert result is cached_data
	assert coordinator._last_known_data is cached_data
	coordinator._async_fetch_data.assert_awaited_once()


async def test_fetch_data_reraises_family_member_session_expiry(
	hass, mock_config_entry
):
	"""Family-member session expiry bubbles out so auth recovery can run."""
	coordinator = _coordinator(hass, mock_config_entry)
	coordinator.client = _client(
		async_get_family_members=AsyncMock(
			side_effect=SessionExpiredError("members expired")
		)
	)

	with pytest.raises(SessionExpiredError, match="members expired"):
		await coordinator._async_fetch_data()

	coordinator.client.async_get_apps_and_usage.assert_not_awaited()
	coordinator.client.async_get_location.assert_not_awaited()


async def test_fetch_data_logs_location_error_and_keeps_child_data(
	hass, mock_config_entry, caplog
):
	"""Location failures do not discard the rest of the child refresh."""
	coordinator = _coordinator(hass, mock_config_entry)
	coordinator.client = _client(
		async_get_location=AsyncMock(side_effect=RuntimeError("location offline"))
	)
	caplog.set_level(logging.WARNING, logger="custom_components.familylink.coordinator")

	result = await coordinator._async_fetch_data()

	child = result["children_data"][0]
	assert child["child_id"] == TEST_CHILD_ID
	assert child["child_name"] == "Alex"
	assert child["location"] is None
	assert child["devices"][0]["id"] == TEST_DEVICE_ID
	assert "Failed to fetch location data for Alex: location offline" in caplog.text
	coordinator.client.async_get_location.assert_awaited_once_with(
		account_id=TEST_CHILD_ID
	)
