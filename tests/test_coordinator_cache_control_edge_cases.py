"""Tests for Family Link coordinator cache and control edge cases."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from custom_components.familylink.const import DEVICE_LOCK_ACTION
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
		async_control_device=AsyncMock(return_value=True),
		async_refresh_session=AsyncMock(),
		async_cleanup=AsyncMock(),
		schedule_today=lambda account_id=None: 1,
	)
	for name, value in overrides.items():
		setattr(client, name, value)
	return client


@pytest.mark.parametrize(
	"method_name",
	[
		"async_get_apps_and_usage",
		"async_update_google_schedule_timezone_from_devices",
		"async_get_time_limit",
		"async_get_applied_time_limits",
		"async_get_daily_screen_time",
		"async_get_location",
	],
)
async def test_child_session_expiry_bubbles_out_of_fetch(
	hass, mock_config_entry, method_name
):
	"""Child-level session expiry is not mistaken for recoverable stale data."""
	coordinator = _coordinator(hass, mock_config_entry)
	coordinator.client = _client(
		**{method_name: AsyncMock(side_effect=SessionExpiredError("expired"))}
	)

	with pytest.raises(SessionExpiredError, match="expired"):
		await coordinator._async_fetch_data()


async def test_fresh_pending_lock_state_overrides_default_api_state(
	hass, mock_config_entry, monkeypatch
):
	"""Recent optimistic lock state wins while the API still reports no lock data."""
	coordinator = _coordinator(hass, mock_config_entry)
	coordinator.client = _client(
		async_get_applied_time_limits=AsyncMock(
			return_value={
				"device_lock_states": {},
				"devices": {},
				"bedtime_enabled_today": True,
				"schooltime_enabled_today": False,
			}
		)
	)
	now = 1000.0
	monkeypatch.setattr("custom_components.familylink.coordinator.time.time", lambda: now)
	coordinator._pending_lock_states[TEST_DEVICE_ID] = (True, now - 1.0)

	result = await coordinator._async_fetch_data()

	device = result["children_data"][0]["devices"][0]
	assert device["locked"] is True
	assert coordinator._pending_lock_states[TEST_DEVICE_ID][0] is True


async def test_missing_lock_state_defaults_to_unlocked(hass, mock_config_entry):
	"""A device with no API lock state is treated as unlocked."""
	coordinator = _coordinator(hass, mock_config_entry)
	coordinator.client = _client(
		async_get_applied_time_limits=AsyncMock(
			return_value={
				"device_lock_states": {},
				"devices": {},
				"bedtime_enabled_today": True,
				"schooltime_enabled_today": False,
			}
		)
	)

	result = await coordinator._async_fetch_data()

	assert result["children_data"][0]["devices"][0]["locked"] is False


async def test_control_device_returns_false_when_child_id_cannot_be_resolved(
	hass, mock_config_entry
):
	"""Device control fails cleanly when neither caller nor cache supplies a child."""
	coordinator = _coordinator(hass, mock_config_entry)
	coordinator.client = _client()

	assert await coordinator.async_control_device(TEST_DEVICE_ID, DEVICE_LOCK_ACTION) is False
	coordinator.client.async_control_device.assert_not_awaited()


async def test_control_device_returns_false_when_client_raises(
	hass, mock_config_entry
):
	"""Device control exceptions do not leave optimistic lock state behind."""
	coordinator = _coordinator(hass, mock_config_entry)
	coordinator.client = _client(
		async_control_device=AsyncMock(side_effect=RuntimeError("control failed"))
	)
	coordinator.async_request_refresh = AsyncMock()

	assert (
		await coordinator.async_control_device(
			TEST_DEVICE_ID,
			DEVICE_LOCK_ACTION,
			TEST_CHILD_ID,
		)
		is False
	)
	assert TEST_DEVICE_ID not in coordinator._pending_lock_states
	coordinator.async_request_refresh.assert_not_awaited()


def test_pending_time_limit_state_can_be_set_cleared_and_expired(
	hass, mock_config_entry, monkeypatch
):
	"""Pending time-limit state tracks independent limits and cleans stale entries."""
	coordinator = _coordinator(hass, mock_config_entry)
	now = 1000.0
	monkeypatch.setattr("custom_components.familylink.coordinator.time.time", lambda: now)

	coordinator.set_pending_time_limit_state(TEST_CHILD_ID, "bedtime", True)
	coordinator.set_pending_time_limit_state(TEST_CHILD_ID, "school_time", False)
	assert coordinator.get_pending_time_limit_state(TEST_CHILD_ID, "bedtime") is True
	assert (
		coordinator.get_pending_time_limit_state(TEST_CHILD_ID, "school_time")
		is False
	)

	coordinator.set_pending_time_limit_state(TEST_CHILD_ID, "bedtime", None)
	assert coordinator.get_pending_time_limit_state(TEST_CHILD_ID, "bedtime") is None
	assert (
		coordinator.get_pending_time_limit_state(TEST_CHILD_ID, "school_time")
		is False
	)

	now = 1006.0
	assert (
		coordinator.get_pending_time_limit_state(TEST_CHILD_ID, "school_time")
		is None
	)
	assert "school_time" not in coordinator._pending_time_limit_states[TEST_CHILD_ID]


async def test_get_device_uses_exact_cache_key(hass, mock_config_entry):
	"""Device cache lookup returns exact stored keys and ignores near misses."""
	coordinator = _coordinator(hass, mock_config_entry)
	device = {"id": TEST_DEVICE_ID, "child_id": TEST_CHILD_ID}
	cache_key = f"{TEST_CHILD_ID}_{TEST_DEVICE_ID}"
	coordinator._devices[cache_key] = device

	assert await coordinator.async_get_device(cache_key) is device
	assert await coordinator.async_get_device(TEST_DEVICE_ID) is None


async def test_auth_notification_is_sent_once(hass, mock_config_entry):
	"""Repeated auth failures do not spam persistent notifications."""
	coordinator = _coordinator(hass, mock_config_entry)
	notification_calls = []

	async def handle_notification(service_call):
		notification_calls.append(service_call)

	hass.services.async_register(
		"persistent_notification",
		"create",
		handle_notification,
	)

	await coordinator._create_auth_notification()
	await coordinator._create_auth_notification()
	await hass.async_block_till_done()

	assert len(notification_calls) == 1
	assert notification_calls[0].data["notification_id"] == "familylink_auth_expired"
	assert coordinator._auth_notification_sent is True


async def test_setup_client_bubbles_authenticate_failure(
	hass, mock_config_entry, monkeypatch
):
	"""Client setup surfaces authentication failures from the API client."""
	created_clients = []

	class FailingClient:
		def __init__(self, hass, config):
			self.hass = hass
			self.config = config
			self.async_authenticate = AsyncMock(
				side_effect=RuntimeError("auth failed")
			)
			created_clients.append(self)

	monkeypatch.setattr(
		"custom_components.familylink.coordinator.FamilyLinkClient",
		FailingClient,
	)
	coordinator = _coordinator(hass, mock_config_entry)

	with pytest.raises(RuntimeError, match="auth failed"):
		await coordinator._async_setup_client()

	assert created_clients[0].hass is hass
	assert created_clients[0].config == dict(mock_config_entry.data)
	created_clients[0].async_authenticate.assert_awaited_once()


async def test_cleanup_closes_client_and_clears_reference(hass, mock_config_entry):
	"""Cleanup closes the client once and leaves the coordinator reusable."""
	coordinator = _coordinator(hass, mock_config_entry)
	client = _client()
	coordinator.client = client

	await coordinator.async_cleanup()
	await coordinator.async_cleanup()

	client.async_cleanup.assert_awaited_once()
	assert coordinator.client is None
