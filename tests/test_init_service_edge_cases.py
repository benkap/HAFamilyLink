"""Edge-case tests for Family Link setup, unload, and service handlers."""
from __future__ import annotations

from unittest.mock import AsyncMock, call

import pytest
import voluptuous as vol

from custom_components.familylink import (
	SCHEMA_ADD_TIME_BONUS,
	SCHEMA_BLOCK_APP,
	SCHEMA_SET_BEDTIME,
	SCHEMA_SET_DAILY_LIMIT,
	SCHEMA_SET_DAILY_LIMIT_SCHEDULE,
	async_setup_services,
	async_unload_entry,
)
from custom_components.familylink.const import (
	DOMAIN,
	SERVICE_ADD_TIME_BONUS,
	SERVICE_BLOCK_APP,
	SERVICE_BLOCK_DEVICE_FOR_SCHOOL,
	SERVICE_DISABLE_BEDTIME,
	SERVICE_DISABLE_DAILY_LIMIT,
	SERVICE_DISABLE_SCHOOL_TIME,
	SERVICE_ENABLE_BEDTIME,
	SERVICE_ENABLE_DAILY_LIMIT,
	SERVICE_ENABLE_SCHOOL_TIME,
	SERVICE_REFRESH_LOCATION,
	SERVICE_RING_DEVICE,
	SERVICE_SET_APP_DAILY_LIMIT,
	SERVICE_SET_BEDTIME,
	SERVICE_SET_BEDTIME_SCHEDULE,
	SERVICE_SET_DAILY_LIMIT,
	SERVICE_SET_DAILY_LIMIT_SCHEDULE,
	SERVICE_UNBLOCK_ALL_APPS,
	SERVICE_UNBLOCK_APP,
)
from custom_components.familylink.exceptions import FamilyLinkException

from conftest import TEST_CHILD_ID


REGISTERED_SERVICES = (
	SERVICE_BLOCK_DEVICE_FOR_SCHOOL,
	SERVICE_UNBLOCK_ALL_APPS,
	SERVICE_BLOCK_APP,
	SERVICE_UNBLOCK_APP,
	SERVICE_SET_APP_DAILY_LIMIT,
	SERVICE_ADD_TIME_BONUS,
	SERVICE_ENABLE_BEDTIME,
	SERVICE_DISABLE_BEDTIME,
	SERVICE_ENABLE_SCHOOL_TIME,
	SERVICE_DISABLE_SCHOOL_TIME,
	SERVICE_ENABLE_DAILY_LIMIT,
	SERVICE_DISABLE_DAILY_LIMIT,
	SERVICE_SET_DAILY_LIMIT,
	SERVICE_SET_BEDTIME,
	SERVICE_SET_BEDTIME_SCHEDULE,
	SERVICE_SET_DAILY_LIMIT_SCHEDULE,
	SERVICE_REFRESH_LOCATION,
	SERVICE_RING_DEVICE,
)


@pytest.fixture
async def services_hass(hass, harness_coordinator):
	"""Register Family Link services for handler edge-case tests."""
	await async_setup_services(hass, harness_coordinator)
	return hass


def _missing_services(hass) -> list[str]:
	"""Return services that are expected but not currently registered."""
	return [
		service
		for service in REGISTERED_SERVICES
		if not hass.services.has_service(DOMAIN, service)
	]


def _registered_services(hass) -> list[str]:
	"""Return expected Family Link services still present in the registry."""
	return [
		service
		for service in REGISTERED_SERVICES
		if hass.services.has_service(DOMAIN, service)
	]


async def test_setup_services_registers_full_service_surface(services_hass):
	"""Service setup exposes every supported Family Link service."""
	assert _missing_services(services_hass) == []


async def test_unload_keeps_services_when_other_entries_remain(
	hass, mock_config_entry, harness_coordinator, monkeypatch
):
	"""Unloading one entry keeps the shared services for remaining entries."""
	other_coordinator = AsyncMock()
	other_coordinator.async_cleanup = AsyncMock()
	hass.data[DOMAIN] = {
		mock_config_entry.entry_id: harness_coordinator,
		"other-entry": other_coordinator,
	}
	await async_setup_services(hass, harness_coordinator)
	monkeypatch.setattr(
		hass.config_entries,
		"async_unload_platforms",
		AsyncMock(return_value=True),
	)

	assert await async_unload_entry(hass, mock_config_entry) is True

	assert list(hass.data[DOMAIN]) == ["other-entry"]
	assert hass.data[DOMAIN]["other-entry"] is other_coordinator
	assert _missing_services(hass) == []
	harness_coordinator.async_cleanup.assert_awaited_once()
	other_coordinator.async_cleanup.assert_not_awaited()


async def test_unload_without_runtime_data_removes_registered_services(
	hass, mock_config_entry, harness_coordinator, monkeypatch
):
	"""Unload stays safe when coordinator runtime data is already missing."""
	await async_setup_services(hass, harness_coordinator)
	hass.data.pop(DOMAIN, None)
	monkeypatch.setattr(
		hass.config_entries,
		"async_unload_platforms",
		AsyncMock(return_value=True),
	)

	assert await async_unload_entry(hass, mock_config_entry) is True

	assert DOMAIN not in hass.data
	assert _registered_services(hass) == []
	harness_coordinator.async_cleanup.assert_not_awaited()


@pytest.mark.parametrize(
	("schema", "payload"),
	[
		(SCHEMA_BLOCK_APP, {}),
		(SCHEMA_ADD_TIME_BONUS, {"bonus_minutes": 0}),
		(SCHEMA_SET_DAILY_LIMIT, {"daily_minutes": 1441}),
		(SCHEMA_SET_BEDTIME, {"start_time": "21:00"}),
		(SCHEMA_SET_DAILY_LIMIT_SCHEDULE, {"day": 8, "enabled": True}),
	],
)
def test_service_schemas_reject_bad_arguments(schema, payload):
	"""Service schemas reject missing or out-of-range arguments."""
	with pytest.raises(vol.Invalid):
		schema(payload)


async def test_ring_device_requires_device_id_before_dispatch(
	services_hass, harness_coordinator
):
	"""Device-ring calls fail before dispatch when no device target is known."""
	with pytest.raises(ValueError, match="device_id is required"):
		await services_hass.services.async_call(
			DOMAIN,
			SERVICE_RING_DEVICE,
			{"child_id": TEST_CHILD_ID},
			blocking=True,
		)

	harness_coordinator.client.async_ring_device.assert_not_awaited()
	harness_coordinator.async_request_refresh.assert_not_awaited()


@pytest.mark.parametrize(
	("service", "payload", "client_method"),
	[
		(SERVICE_BLOCK_APP, {"package_name": "com.example.app"}, "async_block_app"),
		(SERVICE_REFRESH_LOCATION, {}, "async_get_location"),
	],
)
async def test_all_child_lookup_failure_bubbles_without_refresh(
	services_hass, harness_coordinator, service, payload, client_method
):
	"""All-child service calls stop cleanly when child lookup fails."""
	harness_coordinator.client.async_get_all_supervised_children.side_effect = (
		FamilyLinkException("children unavailable")
	)

	with pytest.raises(FamilyLinkException, match="children unavailable"):
		await services_hass.services.async_call(
			DOMAIN,
			service,
			payload,
			blocking=True,
		)

	getattr(harness_coordinator.client, client_method).assert_not_awaited()
	harness_coordinator.async_request_refresh.assert_not_awaited()


async def test_school_block_continues_after_one_child_write_failure(
	services_hass, harness_coordinator
):
	"""School blocking continues across children and refreshes after partial failure."""
	harness_coordinator.client.async_get_all_supervised_children.return_value = [
		{"id": "child-1", "name": "One"},
		{"id": "child-2", "name": "Two"},
		{"id": "child-3", "name": "Three"},
	]
	harness_coordinator.client.async_block_device_for_school.side_effect = [
		{"blocked_count": 2, "unblocked_count": 0, "failed_count": 0},
		FamilyLinkException("write failed"),
		{"blocked_count": 1, "failed_count": 0},
	]

	await services_hass.services.async_call(
		DOMAIN,
		SERVICE_BLOCK_DEVICE_FOR_SCHOOL,
		{"whitelist": ["com.spotify.music"]},
		blocking=True,
	)

	harness_coordinator.client.async_block_device_for_school.assert_has_awaits(
		[
			call(account_id="child-1", whitelist=["com.spotify.music"]),
			call(account_id="child-2", whitelist=["com.spotify.music"]),
			call(account_id="child-3", whitelist=["com.spotify.music"]),
		]
	)
	assert harness_coordinator.client.async_block_device_for_school.await_count == 3
	harness_coordinator.async_request_refresh.assert_awaited_once()
