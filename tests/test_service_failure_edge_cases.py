"""Failure and edge-case tests for Family Link service handlers."""
from __future__ import annotations

from unittest.mock import call

import pytest

from custom_components.familylink import async_setup_services
from custom_components.familylink.const import (
	DOMAIN,
	SERVICE_ADD_TIME_BONUS,
	SERVICE_BLOCK_APP,
	SERVICE_BLOCK_DEVICE_FOR_SCHOOL,
	SERVICE_REFRESH_LOCATION,
	SERVICE_RING_DEVICE,
	SERVICE_SET_APP_DAILY_LIMIT,
	SERVICE_SET_DAILY_LIMIT,
	SERVICE_SET_DAILY_LIMIT_SCHEDULE,
	SERVICE_UNBLOCK_ALL_APPS,
	SERVICE_UNBLOCK_APP,
)
from custom_components.familylink.exceptions import (
	FamilyLinkException,
	ScheduleUpdatePartialError,
)

from conftest import TEST_CHILD_ID, TEST_DEVICE_ID


@pytest.fixture
async def services_hass(hass, harness_coordinator):
	"""Register Family Link services for failure edge-case tests."""
	await async_setup_services(hass, harness_coordinator)
	return hass


@pytest.mark.parametrize(
	("service", "payload", "client_method", "expected_call"),
	[
		(
			SERVICE_BLOCK_DEVICE_FOR_SCHOOL,
			{"whitelist": ["com.spotify.music"]},
			"async_block_device_for_school",
			call(account_id=TEST_CHILD_ID, whitelist=["com.spotify.music"]),
		),
		(
			SERVICE_UNBLOCK_ALL_APPS,
			{},
			"async_unblock_all_apps",
			call(account_id=TEST_CHILD_ID),
		),
		(
			SERVICE_BLOCK_APP,
			{"package_name": "com.example.app"},
			"async_block_app",
			call("com.example.app", account_id=TEST_CHILD_ID),
		),
		(
			SERVICE_UNBLOCK_APP,
			{"package_name": "com.example.app"},
			"async_unblock_app",
			call("com.example.app", account_id=TEST_CHILD_ID),
		),
	],
)
async def test_app_services_extract_child_id_from_entity(
	services_hass, harness_coordinator, service, payload, client_method, expected_call
):
	"""App services can target one child through entity attributes."""
	if client_method == "async_block_device_for_school":
		harness_coordinator.client.async_block_device_for_school.return_value = {
			"blocked_count": 2,
			"unblocked_count": 0,
			"failed_count": 0,
		}
	elif client_method == "async_unblock_all_apps":
		harness_coordinator.client.async_unblock_all_apps.return_value = {
			"unblocked_count": 2,
			"failed_count": 0,
		}
	services_hass.states.async_set(
		"switch.alex_tablet",
		"on",
		{"child_id": TEST_CHILD_ID, "device_id": TEST_DEVICE_ID},
	)

	await services_hass.services.async_call(
		DOMAIN,
		service,
		{"entity_id": "switch.alex_tablet", **payload},
		blocking=True,
	)

	harness_coordinator.client.async_get_all_supervised_children.assert_not_awaited()
	getattr(harness_coordinator.client, client_method).assert_has_awaits(
		[expected_call]
	)
	harness_coordinator.async_request_refresh.assert_awaited_once()


@pytest.mark.parametrize(
	("service", "client_method", "payload", "expected_call"),
	[
		(
			SERVICE_BLOCK_APP,
			"async_block_app",
			{"package_name": "com.example.app", "child_id": TEST_CHILD_ID},
			call("com.example.app", account_id=TEST_CHILD_ID),
		),
		(
			SERVICE_UNBLOCK_APP,
			"async_unblock_app",
			{"package_name": "com.example.app", "child_id": TEST_CHILD_ID},
			call("com.example.app", account_id=TEST_CHILD_ID),
		),
		(
			SERVICE_SET_APP_DAILY_LIMIT,
			"async_set_app_daily_limit",
			{
				"package_name": "com.example.app",
				"minutes": 30,
				"child_id": TEST_CHILD_ID,
			},
			call("com.example.app", 30, account_id=TEST_CHILD_ID),
		),
	],
)
async def test_single_child_app_services_refresh_after_false_result(
	services_hass, harness_coordinator, service, client_method, payload, expected_call
):
	"""Single-child app writes still refresh after a false client result."""
	client_call = getattr(harness_coordinator.client, client_method)
	client_call.return_value = False

	await services_hass.services.async_call(
		DOMAIN,
		service,
		payload,
		blocking=True,
	)

	client_call.assert_has_awaits([expected_call])
	harness_coordinator.async_request_refresh.assert_awaited_once()


@pytest.mark.parametrize(
	("service", "client_method", "payload"),
	[
		(
			SERVICE_BLOCK_APP,
			"async_block_app",
			{"package_name": "com.example.app", "child_id": TEST_CHILD_ID},
		),
		(
			SERVICE_UNBLOCK_APP,
			"async_unblock_app",
			{"package_name": "com.example.app", "child_id": TEST_CHILD_ID},
		),
		(
			SERVICE_SET_APP_DAILY_LIMIT,
			"async_set_app_daily_limit",
			{
				"package_name": "com.example.app",
				"minutes": 30,
				"child_id": TEST_CHILD_ID,
			},
		),
	],
)
async def test_single_child_app_service_exceptions_skip_refresh(
	services_hass, harness_coordinator, service, client_method, payload
):
	"""Single-child app write exceptions bubble before refresh."""
	client_call = getattr(harness_coordinator.client, client_method)
	client_call.side_effect = FamilyLinkException("write failed")

	with pytest.raises(FamilyLinkException, match="write failed"):
		await services_hass.services.async_call(
			DOMAIN,
			service,
			payload,
			blocking=True,
		)

	client_call.assert_awaited_once()
	harness_coordinator.async_request_refresh.assert_not_awaited()


async def test_set_app_daily_limit_fans_out_to_all_children_after_mixed_results(
	services_hass, harness_coordinator
):
	"""App daily-limit fan-out counts failures and still refreshes."""
	harness_coordinator.client.async_get_all_supervised_children.return_value = [
		{"id": "child-1", "name": "One"},
		{"id": "child-2", "name": "Two"},
		{"id": "child-3", "name": "Three"},
	]
	harness_coordinator.client.async_set_app_daily_limit.side_effect = [
		True,
		False,
		True,
	]

	await services_hass.services.async_call(
		DOMAIN,
		SERVICE_SET_APP_DAILY_LIMIT,
		{"package_name": "com.example.app", "minutes": 45},
		blocking=True,
	)

	harness_coordinator.client.async_set_app_daily_limit.assert_has_awaits(
		[
			call("com.example.app", 45, account_id="child-1"),
			call("com.example.app", 45, account_id="child-2"),
			call("com.example.app", 45, account_id="child-3"),
		]
	)
	harness_coordinator.async_request_refresh.assert_awaited_once()


async def test_set_app_daily_limit_all_child_exception_stops_without_refresh(
	services_hass, harness_coordinator
):
	"""App daily-limit fan-out stops when one child write raises."""
	harness_coordinator.client.async_get_all_supervised_children.return_value = [
		{"id": "child-1", "name": "One"},
		{"id": "child-2", "name": "Two"},
		{"id": "child-3", "name": "Three"},
	]
	harness_coordinator.client.async_set_app_daily_limit.side_effect = [
		True,
		FamilyLinkException("write failed"),
	]

	with pytest.raises(FamilyLinkException, match="write failed"):
		await services_hass.services.async_call(
			DOMAIN,
			SERVICE_SET_APP_DAILY_LIMIT,
			{"package_name": "com.example.app", "minutes": 45},
			blocking=True,
		)

	harness_coordinator.client.async_set_app_daily_limit.assert_has_awaits(
		[
			call("com.example.app", 45, account_id="child-1"),
			call("com.example.app", 45, account_id="child-2"),
		]
	)
	assert harness_coordinator.client.async_set_app_daily_limit.await_count == 2
	harness_coordinator.async_request_refresh.assert_not_awaited()


@pytest.mark.parametrize(
	("service", "client_method", "payload", "expected_kwargs"),
	[
		(
			SERVICE_ADD_TIME_BONUS,
			"async_add_time_bonus",
			{
				"bonus_minutes": 15,
				"device_id": TEST_DEVICE_ID,
				"child_id": TEST_CHILD_ID,
			},
			{
				"bonus_minutes": 15,
				"device_id": TEST_DEVICE_ID,
				"account_id": TEST_CHILD_ID,
			},
		),
		(
			SERVICE_SET_DAILY_LIMIT,
			"async_set_daily_limit",
			{
				"daily_minutes": 90,
				"device_id": TEST_DEVICE_ID,
				"child_id": TEST_CHILD_ID,
			},
			{
				"daily_minutes": 90,
				"device_id": TEST_DEVICE_ID,
				"account_id": TEST_CHILD_ID,
			},
		),
	],
)
async def test_device_limit_service_exceptions_skip_refresh(
	services_hass,
	harness_coordinator,
	service,
	client_method,
	payload,
	expected_kwargs,
):
	"""Device limit service exceptions bubble without refreshing."""
	client_call = getattr(harness_coordinator.client, client_method)
	client_call.side_effect = FamilyLinkException("device write failed")

	with pytest.raises(FamilyLinkException, match="device write failed"):
		await services_hass.services.async_call(
			DOMAIN,
			service,
			payload,
			blocking=True,
		)

	client_call.assert_awaited_once_with(**expected_kwargs)
	harness_coordinator.async_request_refresh.assert_not_awaited()


async def test_daily_limit_schedule_partial_error_still_requests_refresh(
	services_hass, harness_coordinator
):
	"""Partial daily-limit schedule writes refresh before re-raising."""
	harness_coordinator.client.async_set_daily_limit_schedule.side_effect = (
		ScheduleUpdatePartialError(["daily_limit"], "enabled")
	)

	with pytest.raises(ScheduleUpdatePartialError):
		await services_hass.services.async_call(
			DOMAIN,
			SERVICE_SET_DAILY_LIMIT_SCHEDULE,
			{"day": 2, "daily_minutes": 60, "enabled": True},
			blocking=True,
		)

	harness_coordinator.async_request_refresh.assert_awaited_once()


@pytest.mark.parametrize("client_result", [False, True])
async def test_ring_device_does_not_request_refresh(
	services_hass, harness_coordinator, client_result
):
	"""Ring-device calls do not refresh for success or false results."""
	harness_coordinator.client.async_ring_device.return_value = client_result

	await services_hass.services.async_call(
		DOMAIN,
		SERVICE_RING_DEVICE,
		{"device_id": TEST_DEVICE_ID, "child_id": TEST_CHILD_ID},
		blocking=True,
	)

	harness_coordinator.client.async_ring_device.assert_awaited_once_with(
		device_id=TEST_DEVICE_ID,
		child_id=TEST_CHILD_ID,
	)
	harness_coordinator.async_request_refresh.assert_not_awaited()


async def test_ring_device_exception_bubbles_without_refresh(
	services_hass, harness_coordinator
):
	"""Ring-device exceptions bubble without refreshing."""
	harness_coordinator.client.async_ring_device.side_effect = FamilyLinkException(
		"ring failed"
	)

	with pytest.raises(FamilyLinkException, match="ring failed"):
		await services_hass.services.async_call(
			DOMAIN,
			SERVICE_RING_DEVICE,
			{"device_id": TEST_DEVICE_ID, "child_id": TEST_CHILD_ID},
			blocking=True,
		)

	harness_coordinator.async_request_refresh.assert_not_awaited()


async def test_refresh_location_no_location_still_requests_refresh(
	services_hass, harness_coordinator
):
	"""A targeted location refresh still refreshes coordinator data when none returns."""
	harness_coordinator.client.async_get_location.return_value = None

	await services_hass.services.async_call(
		DOMAIN,
		SERVICE_REFRESH_LOCATION,
		{"child_id": TEST_CHILD_ID},
		blocking=True,
	)

	harness_coordinator.client.async_get_location.assert_awaited_once_with(
		account_id=TEST_CHILD_ID,
		refresh=True,
	)
	harness_coordinator.async_request_refresh.assert_awaited_once()
