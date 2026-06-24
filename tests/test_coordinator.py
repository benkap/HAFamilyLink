"""Tests for Family Link coordinator state handling."""
from __future__ import annotations

from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from homeassistant.helpers.update_coordinator import UpdateFailed

from custom_components.familylink.const import DEVICE_LOCK_ACTION
from custom_components.familylink.coordinator import FamilyLinkDataUpdateCoordinator
from custom_components.familylink.exceptions import FamilyLinkException, SessionExpiredError

from conftest import TEST_CHILD_ID, TEST_DEVICE_ID

OTHER_CHILD_ID = "100200301"
OTHER_DEVICE_ID = "device-2"


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
	"""Create a coordinator without letting it build a real API client."""
	return FamilyLinkDataUpdateCoordinator(hass, mock_config_entry)


def _client(**overrides) -> SimpleNamespace:
	"""Return a fake API client with coordinator-facing methods."""
	client = SimpleNamespace(
		async_get_family_members=AsyncMock(
			return_value={"members": [_supervised_child()]}
		),
		async_get_apps_and_usage=AsyncMock(
			return_value={
				"apps": [
					{
						"title": "YouTube",
						"packageName": "com.google.android.youtube",
					}
				],
				"deviceInfo": [
					{
						"deviceId": TEST_DEVICE_ID,
						"displayInfo": {
							"friendlyName": "Pixel Tablet",
							"model": "Pixel Tablet",
							"lastActivityTimeMillis": 1710000000000,
						},
						"capabilityInfo": {"capabilities": ["LOCK"]},
					}
				],
				"appUsageSessions": [{"packageName": "com.google.android.youtube"}],
			}
		),
		async_update_google_schedule_timezone_from_devices=AsyncMock(),
		async_get_time_limit=AsyncMock(
			return_value={
				"bedtime_enabled": True,
				"school_time_enabled": False,
				"bedtime_enabled_today": False,
				"bedtime_today_source": "today_override",
				"bedtime_today_override_action": "disable",
				"bedtime_schedule": [
					{
						"day": 1,
						"day_name": "Monday",
						"enabled": True,
						"start": [21, 0],
						"end": [6, 0],
					}
				],
				"school_time_schedule": [],
				"daily_limit_schedule": [
					{
						"day": 1,
						"day_name": "Monday",
						"enabled": True,
						"minutes": 90,
					}
				],
				"schedule_today": 1,
				"schedule_timezone": "UTC",
				"schedule_timezone_source": "google",
			}
		),
		async_get_applied_time_limits=AsyncMock(
			return_value={
				"device_lock_states": {TEST_DEVICE_ID: True},
				"devices": {
					TEST_DEVICE_ID: {
						"remaining_minutes": 0,
						"total_allowed_minutes": 90,
						"used_minutes": 90,
						"daily_limit_enabled": True,
						"daily_limit_minutes": 90,
						"daily_limit_remaining": 0,
						"bedtime_active": True,
						"schooltime_active": False,
						"bonus_minutes": 0,
						"bedtime_window_start": "20:30",
						"bedtime_window_end": "06:30",
					}
				},
				"bedtime_enabled_today": True,
				"schooltime_enabled_today": False,
			}
		),
		async_get_daily_screen_time=AsyncMock(
			return_value={
				"total_seconds": 3600,
				"formatted": "01:00:00",
				"hours": 1,
				"minutes": 0,
				"seconds": 0,
				"app_breakdown": {"com.google.android.youtube": 3600},
			}
		),
		async_get_location=AsyncMock(
			return_value={
				"latitude": 32.0853,
				"longitude": 34.7818,
				"source_device_id": TEST_DEVICE_ID,
			}
		),
		async_control_device=AsyncMock(return_value=True),
		async_refresh_session=AsyncMock(),
		async_cleanup=AsyncMock(),
		schedule_today=lambda account_id=None: 1,
	)
	for name, value in overrides.items():
		setattr(client, name, value)
	return client


async def test_fetch_data_builds_child_device_and_schedule_state(
	hass, mock_config_entry
):
	"""Fetch data normalizes child, device, schedule, and location fields."""
	coordinator = _coordinator(hass, mock_config_entry)
	coordinator.client = _client()

	result = await coordinator._async_fetch_data()

	child = result["children_data"][0]
	device = child["devices"][0]
	time_data = child["devices_time_data"][TEST_DEVICE_ID]

	assert child["child_id"] == TEST_CHILD_ID
	assert child["child_name"] == "Alex"
	assert child["bedtime_enabled"] is True
	assert child["bedtime_enabled_today"] is False
	assert child["daily_limit_enabled"] is True
	assert child["schedule_timezone"] == "UTC"
	assert child["location"]["source_device_name"] == "Pixel Tablet"
	assert device["locked"] is True
	assert device["daily_limit_remaining"] == 0
	assert time_data["bedtime_window_label"] == "20:30-06:30"
	assert time_data["bedtime_weekly_window_label"] == "21:00-06:00"
	assert time_data["bedtime_window_differs_from_weekly"] is True
	assert coordinator._devices[f"{TEST_CHILD_ID}_{TEST_DEVICE_ID}"] == device


async def test_fetch_data_restores_cached_child_data_when_child_calls_fail(
	hass, mock_config_entry, sample_coordinator_data
):
	"""Transient child-level fetch failures keep cached devices and sensors alive."""
	coordinator = _coordinator(hass, mock_config_entry)
	coordinator._location_tracking_enabled = False
	coordinator._last_known_data = deepcopy(sample_coordinator_data)
	coordinator.client = _client(
		async_get_apps_and_usage=AsyncMock(side_effect=RuntimeError("apps down")),
		async_get_time_limit=AsyncMock(side_effect=RuntimeError("limits down")),
		async_get_applied_time_limits=AsyncMock(side_effect=RuntimeError("applied down")),
		async_get_daily_screen_time=AsyncMock(side_effect=RuntimeError("screen down")),
	)

	result = await coordinator._async_fetch_data()

	child = result["children_data"][0]
	device = child["devices"][0]

	assert child["apps"] == sample_coordinator_data["children_data"][0]["apps"]
	assert device["id"] == TEST_DEVICE_ID
	assert device["name"] == "Pixel Tablet"
	assert device["remaining_minutes"] == 60
	assert device["daily_limit_enabled"] is True
	assert child["devices_time_data"][TEST_DEVICE_ID]["remaining_minutes"] == 60
	assert child["devices_time_data"][TEST_DEVICE_ID]["bedtime_window_label"] == (
		"21:00-06:00"
	)
	assert child["screen_time"] == sample_coordinator_data["children_data"][0][
		"screen_time"
	]
	assert child["daily_limit_enabled"] is True


async def test_fetch_data_keeps_successful_child_when_sibling_uses_cached_data(
	hass, mock_config_entry, sample_coordinator_data
):
	"""One child's transient failures do not wipe another child's fresh data."""
	cached_child = deepcopy(sample_coordinator_data["children_data"][0])
	cached_child["child"] = _supervised_child(OTHER_CHILD_ID, "Blair")
	cached_child["child_id"] = OTHER_CHILD_ID
	cached_child["child_name"] = "Blair"
	cached_child["devices"][0]["id"] = OTHER_DEVICE_ID
	cached_child["devices"][0]["child_id"] = OTHER_CHILD_ID
	cached_child["devices_time_data"] = {
		OTHER_DEVICE_ID: cached_child["devices_time_data"].pop(TEST_DEVICE_ID)
	}
	fresh_client = _client()

	coordinator = _coordinator(hass, mock_config_entry)
	coordinator._location_tracking_enabled = False
	coordinator._last_known_data = {"children_data": [cached_child]}
	coordinator.client = _client(
		async_get_family_members=AsyncMock(
			return_value={
				"members": [
					_supervised_child(),
					_supervised_child(OTHER_CHILD_ID, "Blair"),
				]
			}
		),
		async_get_apps_and_usage=AsyncMock(
			side_effect=[
				fresh_client.async_get_apps_and_usage.return_value,
				RuntimeError("apps down"),
			]
		),
		async_get_time_limit=AsyncMock(
			side_effect=[
				fresh_client.async_get_time_limit.return_value,
				RuntimeError("limits down"),
			]
		),
		async_get_applied_time_limits=AsyncMock(
			side_effect=[
				fresh_client.async_get_applied_time_limits.return_value,
				RuntimeError("applied down"),
			]
		),
		async_get_daily_screen_time=AsyncMock(
			side_effect=[
				fresh_client.async_get_daily_screen_time.return_value,
				RuntimeError("screen down"),
			]
		),
	)

	result = await coordinator._async_fetch_data()

	children = {child["child_id"]: child for child in result["children_data"]}

	assert set(children) == {TEST_CHILD_ID, OTHER_CHILD_ID}
	assert children[TEST_CHILD_ID]["devices"][0]["locked"] is True
	assert children[TEST_CHILD_ID]["apps"][0]["title"] == "YouTube"
	assert children[OTHER_CHILD_ID]["apps"] == cached_child["apps"]
	assert children[OTHER_CHILD_ID]["devices"][0]["id"] == OTHER_DEVICE_ID
	assert children[OTHER_CHILD_ID]["devices"][0]["remaining_minutes"] == 60
	assert (
		children[OTHER_CHILD_ID]["devices_time_data"][OTHER_DEVICE_ID][
			"remaining_minutes"
		]
		== 60
	)
	assert children[OTHER_CHILD_ID]["screen_time"] == cached_child["screen_time"]


async def test_fetch_data_aggregates_sparse_device_location_and_usage_payloads(
	hass, mock_config_entry
):
	"""Sparse device/location payloads still produce useful child state."""
	apps_usage_data = {
		"apps": [{"title": "Maps", "packageName": "com.google.android.apps.maps"}],
		"deviceInfo": [
			{"deviceId": OTHER_DEVICE_ID},
			{
				"deviceId": TEST_DEVICE_ID,
				"displayInfo": {
					"friendlyName": "Pixel Tablet",
					"model": "Pixel Tablet",
				},
			},
		],
		"appUsageSessions": [
			{"packageName": "com.google.android.apps.maps", "durationMillis": 120000}
		],
	}
	screen_time = {
		"total_seconds": 120,
		"formatted": "00:02:00",
		"hours": 0,
		"minutes": 2,
		"seconds": 0,
		"app_breakdown": {"com.google.android.apps.maps": 120},
	}
	coordinator = _coordinator(hass, mock_config_entry)
	coordinator.client = _client(
		async_get_apps_and_usage=AsyncMock(return_value=apps_usage_data),
		async_get_applied_time_limits=AsyncMock(
			return_value={
				"device_lock_states": {TEST_DEVICE_ID: True},
				"devices": {
					TEST_DEVICE_ID: {
						"remaining_minutes": 10,
						"total_allowed_minutes": 60,
						"used_minutes": 50,
						"daily_limit_enabled": True,
						"daily_limit_minutes": 60,
						"daily_limit_remaining": 10,
						"bedtime_active": False,
						"schooltime_active": False,
						"bonus_minutes": 0,
						"bedtime_window_start": "22:00",
						"bedtime_window_end": "07:00",
					}
				},
				"bedtime_enabled_today": None,
				"schooltime_enabled_today": None,
			}
		),
		async_get_daily_screen_time=AsyncMock(return_value=screen_time),
		async_get_location=AsyncMock(
			return_value={
				"latitude": 32.1,
				"longitude": 34.8,
				"source_device_id": "missing-device",
			}
		),
	)

	result = await coordinator._async_fetch_data()

	child = result["children_data"][0]
	sparse_device, timed_device = child["devices"]

	assert child["apps"] == apps_usage_data["apps"]
	assert child["app_usage_sessions"] == apps_usage_data["appUsageSessions"]
	assert child["screen_time"] == screen_time
	assert child["daily_limit_enabled"] is True
	assert child["location"]["source_device_name"] is None
	assert sparse_device["name"] == "Unknown Device"
	assert sparse_device["model"] == "Unknown"
	assert sparse_device["capabilities"] == []
	assert sparse_device["locked"] is False
	assert "daily_limit_enabled" not in sparse_device
	assert timed_device["locked"] is True
	assert timed_device["remaining_minutes"] == 10
	coordinator.client.async_get_daily_screen_time.assert_awaited_once_with(
		account_id=TEST_CHILD_ID,
		data=apps_usage_data,
	)


async def test_update_data_retries_once_after_session_expiry(
	hass, mock_config_entry, sample_coordinator_data
):
	"""Session expiry triggers one auth refresh and one retry."""
	coordinator = _coordinator(hass, mock_config_entry)
	result = deepcopy(sample_coordinator_data)
	coordinator._async_fetch_data = AsyncMock(
		side_effect=[SessionExpiredError("expired"), result]
	)
	coordinator._async_refresh_auth = AsyncMock()

	assert await coordinator._async_update_data() == result
	coordinator._async_refresh_auth.assert_awaited_once()
	assert coordinator._last_known_data == result
	assert coordinator._is_retrying_auth is False


async def test_update_data_notifies_when_session_still_expired_after_refresh(
	hass, mock_config_entry
):
	"""A retry that still sees an expired session asks the user to re-authenticate."""
	coordinator = _coordinator(hass, mock_config_entry)
	coordinator._async_fetch_data = AsyncMock(
		side_effect=[
			SessionExpiredError("expired"),
			SessionExpiredError("still expired"),
		]
	)
	coordinator._async_refresh_auth = AsyncMock()
	notification_calls = []

	async def handle_notification(service_call):
		notification_calls.append(service_call)

	hass.services.async_register(
		"persistent_notification",
		"create",
		handle_notification,
	)

	with pytest.raises(UpdateFailed, match="Session expired"):
		await coordinator._async_update_data()

	await hass.async_block_till_done()

	coordinator._async_refresh_auth.assert_awaited_once()
	assert len(notification_calls) == 1
	assert notification_calls[0].data["notification_id"] == "familylink_auth_expired"
	assert coordinator._auth_notification_sent is True
	assert coordinator._is_retrying_auth is False


async def test_update_data_uses_last_known_data_after_familylink_error(
	hass, mock_config_entry, sample_coordinator_data
):
	"""A later API failure returns the last successful payload."""
	coordinator = _coordinator(hass, mock_config_entry)
	coordinator._last_known_data = deepcopy(sample_coordinator_data)
	coordinator._async_fetch_data = AsyncMock(
		side_effect=FamilyLinkException("temporary failure")
	)

	assert await coordinator._async_update_data() == sample_coordinator_data


async def test_update_data_raises_when_no_cached_data_exists(
	hass, mock_config_entry
):
	"""Initial API failures surface as update failures."""
	coordinator = _coordinator(hass, mock_config_entry)
	coordinator._async_fetch_data = AsyncMock(
		side_effect=FamilyLinkException("temporary failure")
	)

	with pytest.raises(UpdateFailed):
		await coordinator._async_update_data()


async def test_control_device_uses_cached_child_id_and_sets_pending_state(
	hass, mock_config_entry, monkeypatch
):
	"""Device control can infer child ID and briefly trust the requested state."""
	coordinator = _coordinator(hass, mock_config_entry)
	coordinator.client = _client()
	coordinator._devices[f"{TEST_CHILD_ID}_{TEST_DEVICE_ID}"] = {
		"id": TEST_DEVICE_ID,
		"child_id": TEST_CHILD_ID,
	}
	coordinator.async_request_refresh = AsyncMock()
	sleep = AsyncMock()
	monkeypatch.setattr(
		"custom_components.familylink.coordinator.asyncio.sleep",
		sleep,
	)

	assert await coordinator.async_control_device(TEST_DEVICE_ID, DEVICE_LOCK_ACTION) is True
	coordinator.client.async_control_device.assert_awaited_once_with(
		TEST_DEVICE_ID,
		DEVICE_LOCK_ACTION,
		TEST_CHILD_ID,
	)
	assert coordinator._pending_lock_states[TEST_DEVICE_ID][0] is True
	sleep.assert_awaited_once_with(1)
	coordinator.async_request_refresh.assert_awaited_once()


async def test_fetch_data_removes_expired_pending_lock_state_and_uses_api_state(
	hass, mock_config_entry, monkeypatch
):
	"""Expired optimistic lock state falls back to the latest API lock state."""
	coordinator = _coordinator(hass, mock_config_entry)
	coordinator.client = _client()
	now = 1000.0
	monkeypatch.setattr("custom_components.familylink.coordinator.time.time", lambda: now)
	coordinator._pending_lock_states[TEST_DEVICE_ID] = (False, now - 6.0)

	result = await coordinator._async_fetch_data()

	device = result["children_data"][0]["devices"][0]
	assert device["locked"] is True
	assert TEST_DEVICE_ID not in coordinator._pending_lock_states


def test_pending_time_limit_state_expires(hass, mock_config_entry, monkeypatch):
	"""Pending switch states only override API state briefly."""
	coordinator = _coordinator(hass, mock_config_entry)
	now = 1000.0
	monkeypatch.setattr("custom_components.familylink.coordinator.time.time", lambda: now)

	coordinator.set_pending_time_limit_state(TEST_CHILD_ID, "bedtime", True)
	assert coordinator.get_pending_time_limit_state(TEST_CHILD_ID, "bedtime") is True

	now = 1006.0
	assert coordinator.get_pending_time_limit_state(TEST_CHILD_ID, "bedtime") is None
	assert "bedtime" not in coordinator._pending_time_limit_states[TEST_CHILD_ID]
