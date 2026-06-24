"""Tests for final coordinator client setup and control edge cases."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

from custom_components.familylink.const import DEVICE_LOCK_ACTION
from custom_components.familylink.coordinator import FamilyLinkDataUpdateCoordinator

from conftest import TEST_CHILD_ID, TEST_DEVICE_ID


def _coordinator(hass, mock_config_entry) -> FamilyLinkDataUpdateCoordinator:
	"""Create a coordinator without building a real API client."""
	return FamilyLinkDataUpdateCoordinator(hass, mock_config_entry)


async def test_setup_client_constructs_authenticates_and_stores_client(
	hass, mock_config_entry, monkeypatch
):
	"""Client setup builds the API client, authenticates it, and keeps it."""
	created_clients = []

	class FakeFamilyLinkClient:
		def __init__(self, hass, config):
			self.hass = hass
			self.config = config
			self.async_authenticate = AsyncMock()
			created_clients.append(self)

	monkeypatch.setattr(
		"custom_components.familylink.coordinator.FamilyLinkClient",
		FakeFamilyLinkClient,
	)
	coordinator = _coordinator(hass, mock_config_entry)

	await coordinator._async_setup_client()

	assert len(created_clients) == 1
	assert coordinator.client is created_clients[0]
	assert created_clients[0].hass is hass
	assert created_clients[0].config == dict(mock_config_entry.data)
	created_clients[0].async_authenticate.assert_awaited_once()


async def test_refresh_auth_awaits_existing_client_and_keeps_it_on_success(
	hass, mock_config_entry
):
	"""Successful session refresh leaves the current client in place."""
	coordinator = _coordinator(hass, mock_config_entry)
	client = SimpleNamespace(async_refresh_session=AsyncMock())
	coordinator.client = client

	await coordinator._async_refresh_auth()

	client.async_refresh_session.assert_awaited_once()
	assert coordinator.client is client


async def test_control_device_sets_up_client_before_explicit_child_control(
	hass, mock_config_entry, monkeypatch
):
	"""Device control lazily creates the client before issuing explicit-child control."""
	coordinator = _coordinator(hass, mock_config_entry)
	call_order = []

	async def setup_client():
		call_order.append("setup")
		coordinator.client = client

	async def control_device(device_id, action, child_id):
		call_order.append("control")
		return True

	client = SimpleNamespace(
		async_control_device=AsyncMock(side_effect=control_device),
	)
	coordinator._async_setup_client = AsyncMock(side_effect=setup_client)
	coordinator.async_request_refresh = AsyncMock()
	sleep = AsyncMock()
	monkeypatch.setattr("custom_components.familylink.coordinator.asyncio.sleep", sleep)
	coordinator._devices["stale-cache-entry"] = {
		"id": TEST_DEVICE_ID,
		"child_id": "stale-child",
	}

	assert (
		await coordinator.async_control_device(
			TEST_DEVICE_ID,
			DEVICE_LOCK_ACTION,
			TEST_CHILD_ID,
		)
		is True
	)

	assert call_order == ["setup", "control"]
	coordinator._async_setup_client.assert_awaited_once()
	client.async_control_device.assert_awaited_once_with(
		TEST_DEVICE_ID,
		DEVICE_LOCK_ACTION,
		TEST_CHILD_ID,
	)
	sleep.assert_awaited_once_with(1)
	coordinator.async_request_refresh.assert_awaited_once()
	assert coordinator._pending_lock_states[TEST_DEVICE_ID][0] is True
