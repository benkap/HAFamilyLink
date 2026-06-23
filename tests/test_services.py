"""Tests for Family Link service schemas and dispatch."""
from __future__ import annotations

import pytest
import voluptuous as vol

from custom_components.familylink import (
	SCHEMA_SET_BEDTIME_SCHEDULE,
	async_setup_services,
	extract_ids_from_entity,
)
from custom_components.familylink.const import (
	DOMAIN,
	SERVICE_ADD_TIME_BONUS,
	SERVICE_BLOCK_APP,
	SERVICE_DISABLE_BEDTIME,
	SERVICE_DISABLE_DAILY_LIMIT,
	SERVICE_DISABLE_SCHOOL_TIME,
	SERVICE_ENABLE_BEDTIME,
	SERVICE_ENABLE_DAILY_LIMIT,
	SERVICE_ENABLE_SCHOOL_TIME,
	SERVICE_REFRESH_DEVICES,
	SERVICE_REFRESH_LOCATION,
	SERVICE_RING_DEVICE,
	SERVICE_SET_APP_DAILY_LIMIT,
	SERVICE_SET_BEDTIME,
	SERVICE_SET_BEDTIME_SCHEDULE,
	SERVICE_SET_DAILY_LIMIT,
	SERVICE_SET_DAILY_LIMIT_SCHEDULE,
	SERVICE_UNBLOCK_APP,
)
from custom_components.familylink.exceptions import FamilyLinkException, ScheduleUpdatePartialError

from conftest import TEST_CHILD_ID, TEST_DEVICE_ID


@pytest.fixture
async def services_hass(hass, harness_coordinator):
	"""Register Family Link services for service tests."""
	await async_setup_services(hass, harness_coordinator)
	return hass


def test_bedtime_schedule_schema_rejects_invalid_times():
	"""Service schemas reject invalid schedule times."""
	with pytest.raises(vol.Invalid):
		SCHEMA_SET_BEDTIME_SCHEDULE(
			{"day": 1, "start_time": "25:00", "end_time": "06:30"}
		)


def test_schema_keeps_numeric_looking_child_id_as_string():
	"""Child IDs look numeric but must remain strings."""
	result = SCHEMA_SET_BEDTIME_SCHEDULE(
		{"day": 1, "enabled": True, "child_id": "001002003"}
	)

	assert result["child_id"] == "001002003"


async def test_schedule_service_dispatch_keeps_child_id_string(
	services_hass, harness_coordinator
):
	"""Service dispatch passes child_id through to the API client unchanged."""
	await services_hass.services.async_call(
		DOMAIN,
		SERVICE_SET_DAILY_LIMIT_SCHEDULE,
		{"day": 1, "enabled": True, "child_id": "001002003"},
		blocking=True,
	)

	harness_coordinator.client.async_set_daily_limit_schedule.assert_awaited_once_with(
		day=1,
		daily_minutes=None,
		enabled=True,
		account_id="001002003",
	)


async def test_entity_id_fallback_extracts_child_and_device_ids(
	services_hass, harness_coordinator
):
	"""Entity attributes are used as fallback service targets."""
	services_hass.states.async_set(
		"switch.pixel_tablet",
		"on",
		{"child_id": TEST_CHILD_ID, "device_id": TEST_DEVICE_ID},
	)

	await services_hass.services.async_call(
		DOMAIN,
		SERVICE_RING_DEVICE,
		{"entity_id": "switch.pixel_tablet"},
		blocking=True,
	)

	harness_coordinator.client.async_ring_device.assert_awaited_once_with(
		device_id=TEST_DEVICE_ID,
		child_id=TEST_CHILD_ID,
	)


def test_extract_ids_from_entity_requires_existing_device_attributes(hass):
	"""Entity helper rejects missing entities and missing device IDs when required."""
	with pytest.raises(ValueError, match="Entity switch.missing not found"):
		extract_ids_from_entity(hass, "switch.missing")

	hass.states.async_set("switch.child_only", "on", {"child_id": TEST_CHILD_ID})

	assert extract_ids_from_entity(hass, "switch.child_only") == (
		None,
		TEST_CHILD_ID,
	)
	with pytest.raises(ValueError, match="does not have a device_id"):
		extract_ids_from_entity(hass, "switch.child_only", require_device_id=True)


async def test_service_calls_raise_when_client_is_not_connected(
	hass, harness_coordinator
):
	"""Service handlers fail clearly when the coordinator has no API client."""
	harness_coordinator.client = None
	await async_setup_services(hass, harness_coordinator)

	with pytest.raises(FamilyLinkException, match="client is not connected"):
		await hass.services.async_call(
			DOMAIN,
			SERVICE_ENABLE_BEDTIME,
			{"child_id": TEST_CHILD_ID},
			blocking=True,
		)


@pytest.mark.parametrize(
	("service", "client_method"),
	[
		(SERVICE_BLOCK_APP, "async_block_app"),
		(SERVICE_UNBLOCK_APP, "async_unblock_app"),
	],
)
async def test_app_services_apply_to_all_children_when_no_target_is_provided(
	services_hass, harness_coordinator, service, client_method
):
	"""App block/unblock services fan out to every supervised child."""
	harness_coordinator.client.async_get_all_supervised_children.return_value = [
		{"id": "child-1", "name": "One"},
		{"id": "child-2", "name": "Two"},
	]

	await services_hass.services.async_call(
		DOMAIN,
		service,
		{"package_name": "com.example.app"},
		blocking=True,
	)

	client_call = getattr(harness_coordinator.client, client_method)
	assert client_call.await_args_list[0].args == ("com.example.app",)
	assert client_call.await_args_list[0].kwargs == {"account_id": "child-1"}
	assert client_call.await_args_list[1].args == ("com.example.app",)
	assert client_call.await_args_list[1].kwargs == {"account_id": "child-2"}
	harness_coordinator.async_request_refresh.assert_awaited_once()


async def test_set_app_daily_limit_uses_entity_child_fallback(
	services_hass, harness_coordinator
):
	"""App daily-limit service can target a child via entity attributes."""
	services_hass.states.async_set(
		"switch.pixel_tablet",
		"on",
		{"child_id": TEST_CHILD_ID, "device_id": TEST_DEVICE_ID},
	)

	await services_hass.services.async_call(
		DOMAIN,
		SERVICE_SET_APP_DAILY_LIMIT,
		{
			"entity_id": "switch.pixel_tablet",
			"package_name": "com.example.app",
			"minutes": 45,
		},
		blocking=True,
	)

	harness_coordinator.client.async_set_app_daily_limit.assert_awaited_once_with(
		"com.example.app",
		45,
		account_id=TEST_CHILD_ID,
	)
	harness_coordinator.async_request_refresh.assert_awaited_once()


@pytest.mark.parametrize(
	("service", "client_method"),
	[
		(SERVICE_ENABLE_BEDTIME, "async_enable_bedtime"),
		(SERVICE_DISABLE_BEDTIME, "async_disable_bedtime"),
		(SERVICE_ENABLE_SCHOOL_TIME, "async_enable_school_time"),
		(SERVICE_DISABLE_SCHOOL_TIME, "async_disable_school_time"),
		(SERVICE_ENABLE_DAILY_LIMIT, "async_enable_daily_limit"),
		(SERVICE_DISABLE_DAILY_LIMIT, "async_disable_daily_limit"),
	],
)
async def test_child_time_limit_services_use_entity_child_fallback(
	services_hass, harness_coordinator, service, client_method
):
	"""Child time-limit services extract child_id from entity attributes."""
	services_hass.states.async_set(
		"switch.alex_bedtime",
		"off",
		{"child_id": TEST_CHILD_ID},
	)

	await services_hass.services.async_call(
		DOMAIN,
		service,
		{"entity_id": "switch.alex_bedtime"},
		blocking=True,
	)

	getattr(harness_coordinator.client, client_method).assert_awaited_once_with(
		account_id=TEST_CHILD_ID
	)
	harness_coordinator.async_request_refresh.assert_awaited_once()


async def test_child_time_limit_services_skip_refresh_on_false_result(
	services_hass, harness_coordinator
):
	"""Child time-limit services refresh only after successful client writes."""
	harness_coordinator.client.async_enable_bedtime.return_value = False

	await services_hass.services.async_call(
		DOMAIN,
		SERVICE_ENABLE_BEDTIME,
		{"child_id": TEST_CHILD_ID},
		blocking=True,
	)

	harness_coordinator.client.async_enable_bedtime.assert_awaited_once_with(
		account_id=TEST_CHILD_ID
	)
	harness_coordinator.async_request_refresh.assert_not_awaited()


async def test_device_limit_services_require_or_extract_device_id(
	services_hass, harness_coordinator
):
	"""Device-targeted services reject missing device IDs and use entity fallback."""
	with pytest.raises(ValueError, match="device_id is required"):
		await services_hass.services.async_call(
			DOMAIN,
			SERVICE_ADD_TIME_BONUS,
			{"bonus_minutes": 15, "child_id": TEST_CHILD_ID},
			blocking=True,
		)

	services_hass.states.async_set(
		"switch.pixel_tablet",
		"on",
		{"child_id": TEST_CHILD_ID, "device_id": TEST_DEVICE_ID},
	)

	await services_hass.services.async_call(
		DOMAIN,
		SERVICE_ADD_TIME_BONUS,
		{"entity_id": "switch.pixel_tablet", "bonus_minutes": 30},
		blocking=True,
	)
	await services_hass.services.async_call(
		DOMAIN,
		SERVICE_SET_DAILY_LIMIT,
		{"entity_id": "switch.pixel_tablet", "daily_minutes": 90},
		blocking=True,
	)

	harness_coordinator.client.async_add_time_bonus.assert_awaited_once_with(
		bonus_minutes=30,
		device_id=TEST_DEVICE_ID,
		account_id=TEST_CHILD_ID,
	)
	harness_coordinator.client.async_set_daily_limit.assert_awaited_once_with(
		daily_minutes=90,
		device_id=TEST_DEVICE_ID,
		account_id=TEST_CHILD_ID,
	)
	assert harness_coordinator.async_request_refresh.await_count == 2


async def test_set_bedtime_service_passes_day_child_and_window(
	services_hass, harness_coordinator
):
	"""One-day bedtime service passes the normalized window to the client."""
	await services_hass.services.async_call(
		DOMAIN,
		SERVICE_SET_BEDTIME,
		{
			"start_time": "21:15",
			"end_time": "06:45",
			"day": 2,
			"child_id": TEST_CHILD_ID,
		},
		blocking=True,
	)

	harness_coordinator.client.async_set_bedtime.assert_awaited_once_with(
		start_time="21:15",
		end_time="06:45",
		day=2,
		account_id=TEST_CHILD_ID,
	)
	harness_coordinator.async_request_refresh.assert_awaited_once()


async def test_partial_schedule_write_still_requests_refresh(
	services_hass, harness_coordinator
):
	"""Partial schedule failures still request a coordinator refresh."""
	harness_coordinator.client.async_set_bedtime_schedule.side_effect = (
		ScheduleUpdatePartialError(["window"], "enabled")
	)

	with pytest.raises(ScheduleUpdatePartialError):
		await services_hass.services.async_call(
			DOMAIN,
			SERVICE_SET_BEDTIME_SCHEDULE,
			{"day": 1, "start_time": "21:00", "end_time": "06:30", "enabled": False},
			blocking=True,
		)

	harness_coordinator.async_request_refresh.assert_awaited_once()


async def test_schedule_services_reject_incomplete_or_empty_updates(
	services_hass, harness_coordinator
):
	"""Schedule services require complete windows or enabled/minutes changes."""
	with pytest.raises(ValueError, match="start_time and end_time"):
		await services_hass.services.async_call(
			DOMAIN,
			SERVICE_SET_BEDTIME_SCHEDULE,
			{"day": 1, "start_time": "21:00"},
			blocking=True,
		)

	with pytest.raises(ValueError, match="Provide start_time/end_time"):
		await services_hass.services.async_call(
			DOMAIN,
			SERVICE_SET_BEDTIME_SCHEDULE,
			{"day": 1},
			blocking=True,
		)

	with pytest.raises(ValueError, match="Provide daily_minutes"):
		await services_hass.services.async_call(
			DOMAIN,
			SERVICE_SET_DAILY_LIMIT_SCHEDULE,
			{"day": 1},
			blocking=True,
		)

	harness_coordinator.async_request_refresh.assert_not_awaited()


async def test_refresh_location_targets_all_children_when_no_child_is_provided(
	services_hass, harness_coordinator
):
	"""Location refresh fans out to all supervised children when untargeted."""
	harness_coordinator.client.async_get_all_supervised_children.return_value = [
		{"id": "child-1", "name": "One"},
		{"id": "child-2", "name": "Two"},
	]

	await services_hass.services.async_call(
		DOMAIN,
		SERVICE_REFRESH_LOCATION,
		{},
		blocking=True,
	)

	assert harness_coordinator.client.async_get_location.await_args_list[0].kwargs == {
		"account_id": "child-1",
		"refresh": True,
	}
	assert harness_coordinator.client.async_get_location.await_args_list[1].kwargs == {
		"account_id": "child-2",
		"refresh": True,
	}
	harness_coordinator.async_request_refresh.assert_awaited_once()


def test_removed_or_unsupported_services_are_not_registered(services_hass):
	"""Deprecated or unsupported services stay out of the service registry."""
	assert not services_hass.services.has_service(DOMAIN, SERVICE_REFRESH_DEVICES)
	assert not services_hass.services.has_service(DOMAIN, "set_school_time_schedule")
