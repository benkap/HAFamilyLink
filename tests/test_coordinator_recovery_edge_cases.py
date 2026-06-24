"""Focused coordinator recovery edge-case tests."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from homeassistant.helpers.update_coordinator import UpdateFailed

from custom_components.familylink.coordinator import FamilyLinkDataUpdateCoordinator
from custom_components.familylink.exceptions import SessionExpiredError

from conftest import TEST_CHILD_ID


def _coordinator(hass, mock_config_entry) -> FamilyLinkDataUpdateCoordinator:
	"""Create a coordinator without building a real API client."""
	return FamilyLinkDataUpdateCoordinator(hass, mock_config_entry)


async def test_update_data_already_retrying_session_expiry_creates_notification(
	hass, mock_config_entry
):
	"""A nested session expiry reports auth failure without refreshing again."""
	coordinator = _coordinator(hass, mock_config_entry)
	coordinator._is_retrying_auth = True
	coordinator._async_fetch_data = AsyncMock(
		side_effect=SessionExpiredError("still expired")
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

	coordinator._async_refresh_auth.assert_not_awaited()
	assert len(notification_calls) == 1
	assert notification_calls[0].data["notification_id"] == "familylink_auth_expired"
	assert coordinator._auth_notification_sent is True


async def test_setup_client_returns_early_when_client_exists(
	hass, mock_config_entry, monkeypatch
):
	"""Existing clients are reused without constructing or authenticating a new one."""
	coordinator = _coordinator(hass, mock_config_entry)
	existing_client = SimpleNamespace(async_authenticate=AsyncMock())
	coordinator.client = existing_client

	def fail_new_client(*args, **kwargs):
		raise AssertionError("client should not be rebuilt")

	monkeypatch.setattr(
		"custom_components.familylink.coordinator.FamilyLinkClient",
		fail_new_client,
	)

	await coordinator._async_setup_client()

	assert coordinator.client is existing_client
	existing_client.async_authenticate.assert_not_awaited()


async def test_refresh_auth_returns_early_without_client(hass, mock_config_entry):
	"""Refreshing auth is a no-op when setup has not created a client yet."""
	coordinator = _coordinator(hass, mock_config_entry)

	await coordinator._async_refresh_auth()

	assert coordinator.client is None


def test_pending_time_limit_state_returns_none_for_missing_child_or_limit(
	hass, mock_config_entry
):
	"""Missing pending child or limit state is reported as no override."""
	coordinator = _coordinator(hass, mock_config_entry)
	coordinator.set_pending_time_limit_state(TEST_CHILD_ID, "bedtime", True)

	assert coordinator.get_pending_time_limit_state("missing-child", "bedtime") is None
	assert coordinator.get_pending_time_limit_state(TEST_CHILD_ID, "daily_limit") is None
