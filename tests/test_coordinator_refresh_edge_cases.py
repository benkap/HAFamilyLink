"""Tests for Family Link coordinator refresh edge cases."""
from __future__ import annotations

from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from homeassistant.helpers.update_coordinator import UpdateFailed

from custom_components.familylink.coordinator import FamilyLinkDataUpdateCoordinator
from custom_components.familylink.exceptions import FamilyLinkException, SessionExpiredError

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
				"bedtime_enabled_today": False,
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


async def test_update_data_success_clears_auth_notification_and_replaces_cache(
	hass, mock_config_entry, sample_coordinator_data
):
	"""A clean refresh resets auth state and stores the new payload."""
	coordinator = _coordinator(hass, mock_config_entry)
	coordinator._auth_notification_sent = True
	coordinator._last_known_data = {"children_data": []}
	fresh_data = deepcopy(sample_coordinator_data)
	fresh_data["children_data"][0]["child_name"] = "Fresh Alex"
	coordinator._async_fetch_data = AsyncMock(return_value=fresh_data)

	assert await coordinator._async_update_data() == fresh_data

	assert coordinator._auth_notification_sent is False
	assert coordinator._last_known_data == fresh_data


@pytest.mark.parametrize(
	"exception",
	[
		FamilyLinkException("temporary familylink outage"),
		RuntimeError("temporary client outage"),
	],
)
async def test_update_data_returns_last_known_data_for_transient_errors(
	hass, mock_config_entry, sample_coordinator_data, exception
):
	"""Transient fetch failures keep entities backed by the last successful data."""
	coordinator = _coordinator(hass, mock_config_entry)
	cached_data = deepcopy(sample_coordinator_data)
	coordinator._last_known_data = cached_data
	coordinator._async_fetch_data = AsyncMock(side_effect=exception)

	assert await coordinator._async_update_data() == cached_data
	assert coordinator._last_known_data == cached_data


async def test_update_data_retry_failure_keeps_cache_and_resets_retry_flag(
	hass, mock_config_entry, sample_coordinator_data
):
	"""A non-auth failure after session refresh does not replace cached data."""
	coordinator = _coordinator(hass, mock_config_entry)
	cached_data = deepcopy(sample_coordinator_data)
	coordinator._last_known_data = cached_data
	coordinator._async_fetch_data = AsyncMock(
		side_effect=[SessionExpiredError("expired"), RuntimeError("still down")]
	)
	coordinator._async_refresh_auth = AsyncMock()

	with pytest.raises(UpdateFailed, match="Failed after auth refresh"):
		await coordinator._async_update_data()

	coordinator._async_refresh_auth.assert_awaited_once()
	assert coordinator._last_known_data == cached_data
	assert coordinator._is_retrying_auth is False
	assert coordinator._auth_notification_sent is False


async def test_refresh_auth_failure_clears_client(hass, mock_config_entry):
	"""Failed session refresh clears the client so the next update can rebuild it."""
	coordinator = _coordinator(hass, mock_config_entry)
	coordinator.client = _client(
		async_refresh_session=AsyncMock(side_effect=RuntimeError("refresh failed"))
	)

	with pytest.raises(RuntimeError, match="refresh failed"):
		await coordinator._async_refresh_auth()

	assert coordinator.client is None


@pytest.mark.parametrize(
	("family_members_result", "expected_family_members", "expected_supervised"),
	[
		({"members": []}, [], []),
		(
			{"members": [{"userId": "parent", "memberSupervisionInfo": {}}]},
			[{"userId": "parent", "memberSupervisionInfo": {}}],
			[],
		),
		(
			{"members": [{"memberSupervisionInfo": {"isSupervisedMember": True}}]},
			[{"memberSupervisionInfo": {"isSupervisedMember": True}}],
			[{"memberSupervisionInfo": {"isSupervisedMember": True}}],
		),
	],
)
async def test_fetch_data_empty_or_incomplete_family_members_skip_child_fetches(
	hass,
	mock_config_entry,
	family_members_result,
	expected_family_members,
	expected_supervised,
):
	"""Missing supervised child IDs produce an empty refresh without child calls."""
	coordinator = _coordinator(hass, mock_config_entry)
	coordinator._devices["stale-device"] = {"id": "stale-device"}
	coordinator.client = _client(
		async_get_family_members=AsyncMock(return_value=family_members_result)
	)

	result = await coordinator._async_fetch_data()

	assert result == {
		"family_members": expected_family_members,
		"supervised_children": expected_supervised,
		"children_data": [],
	}
	assert coordinator._devices == {}
	coordinator.client.async_get_apps_and_usage.assert_not_awaited()
	coordinator.client.async_get_time_limit.assert_not_awaited()
	coordinator.client.async_get_applied_time_limits.assert_not_awaited()
	coordinator.client.async_get_daily_screen_time.assert_not_awaited()
	coordinator.client.async_get_location.assert_not_awaited()


async def test_fetch_data_family_member_failure_returns_empty_payload_and_clears_devices(
	hass, mock_config_entry
):
	"""Family-member lookup failures leave no stale child or device data behind."""
	coordinator = _coordinator(hass, mock_config_entry)
	coordinator._devices["stale-device"] = {"id": "stale-device"}
	coordinator.client = _client(
		async_get_family_members=AsyncMock(side_effect=RuntimeError("members down"))
	)

	result = await coordinator._async_fetch_data()

	assert result == {
		"family_members": None,
		"supervised_children": [],
		"children_data": [],
	}
	assert coordinator._devices == {}
	coordinator.client.async_get_apps_and_usage.assert_not_awaited()
	coordinator.client.async_get_time_limit.assert_not_awaited()
	coordinator.client.async_get_applied_time_limits.assert_not_awaited()
	coordinator.client.async_get_daily_screen_time.assert_not_awaited()


async def test_fetch_data_apps_failure_without_cache_keeps_child_without_stale_devices(
	hass, mock_config_entry
):
	"""A child apps failure without cached data keeps the child but drops stale devices."""
	coordinator = _coordinator(hass, mock_config_entry)
	coordinator._devices["stale-device"] = {"id": "stale-device"}
	coordinator.client = _client(
		async_get_apps_and_usage=AsyncMock(side_effect=RuntimeError("apps down"))
	)

	result = await coordinator._async_fetch_data()

	child = result["children_data"][0]
	assert child["child_id"] == TEST_CHILD_ID
	assert child["apps"] == []
	assert child["app_usage_sessions"] == []
	assert child["devices"] == []
	assert child["devices_time_data"] == {}
	assert child["screen_time"]["formatted"] == "00:00:00"
	assert child["daily_limit_enabled"] is False
	assert coordinator._devices == {}
	coordinator.client.async_update_google_schedule_timezone_from_devices.assert_not_awaited()
	coordinator.client.async_get_daily_screen_time.assert_awaited_once_with(
		account_id=TEST_CHILD_ID,
		data=None,
	)
