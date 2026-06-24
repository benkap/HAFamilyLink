"""Remaining edge-case coverage for Family Link service handlers."""
from __future__ import annotations

from unittest.mock import call

import pytest

import custom_components.familylink as familylink
from custom_components.familylink import async_setup_services
from custom_components.familylink.const import (
	DOMAIN,
	SERVICE_DISABLE_BEDTIME,
	SERVICE_DISABLE_DAILY_LIMIT,
	SERVICE_DISABLE_SCHOOL_TIME,
	SERVICE_ENABLE_BEDTIME,
	SERVICE_ENABLE_DAILY_LIMIT,
	SERVICE_ENABLE_SCHOOL_TIME,
	SERVICE_SET_BEDTIME_SCHEDULE,
	SERVICE_SET_DAILY_LIMIT,
	SERVICE_SET_DAILY_LIMIT_SCHEDULE,
	SERVICE_UNBLOCK_ALL_APPS,
)
from custom_components.familylink.exceptions import (
	FamilyLinkException,
	ScheduleUpdatePartialError,
)

from conftest import TEST_CHILD_ID, TEST_DEVICE_ID


@pytest.fixture
async def services_hass(hass, harness_coordinator):
	"""Register Family Link services for remaining edge-case tests."""
	await async_setup_services(hass, harness_coordinator)
	return hass


def _set_child_entity(hass, entity_id: str = "switch.alex_tablet") -> None:
	"""Create a test entity with child and device identifiers."""
	hass.states.async_set(
		entity_id,
		"on",
		{"child_id": TEST_CHILD_ID, "device_id": TEST_DEVICE_ID},
	)


async def test_unblock_all_apps_fans_out_to_all_children_and_refreshes(
	services_hass, harness_coordinator
):
	"""All-child unblock-all calls every child and refreshes afterward."""
	harness_coordinator.client.async_get_all_supervised_children.return_value = [
		{"id": "child-1", "name": "One"},
		{"id": "child-2", "name": "Two"},
	]
	harness_coordinator.client.async_unblock_all_apps.side_effect = [
		{"unblocked_count": 3, "failed_count": 0},
		{"unblocked_count": 1, "failed_count": 1},
	]

	await services_hass.services.async_call(
		DOMAIN,
		SERVICE_UNBLOCK_ALL_APPS,
		{},
		blocking=True,
	)

	harness_coordinator.client.async_get_all_supervised_children.assert_awaited_once()
	harness_coordinator.client.async_unblock_all_apps.assert_has_awaits(
		[
			call(account_id="child-1"),
			call(account_id="child-2"),
		]
	)
	harness_coordinator.async_request_refresh.assert_awaited_once()


async def test_unblock_all_apps_all_child_exception_stops_without_refresh(
	services_hass, harness_coordinator
):
	"""All-child unblock-all bubbles the child write error before refresh."""
	harness_coordinator.client.async_get_all_supervised_children.return_value = [
		{"id": "child-1", "name": "One"},
		{"id": "child-2", "name": "Two"},
		{"id": "child-3", "name": "Three"},
	]
	harness_coordinator.client.async_unblock_all_apps.side_effect = [
		{"unblocked_count": 3, "failed_count": 0},
		FamilyLinkException("unblock failed"),
	]

	with pytest.raises(FamilyLinkException, match="unblock failed"):
		await services_hass.services.async_call(
			DOMAIN,
			SERVICE_UNBLOCK_ALL_APPS,
			{},
			blocking=True,
		)

	harness_coordinator.client.async_unblock_all_apps.assert_has_awaits(
		[
			call(account_id="child-1"),
			call(account_id="child-2"),
		]
	)
	assert harness_coordinator.client.async_unblock_all_apps.await_count == 2
	harness_coordinator.async_request_refresh.assert_not_awaited()


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
async def test_child_time_limit_service_exceptions_skip_refresh(
	services_hass, harness_coordinator, service, client_method
):
	"""Child time-limit service exceptions bubble without refreshing."""
	client_call = getattr(harness_coordinator.client, client_method)
	client_call.side_effect = FamilyLinkException("toggle failed")

	with pytest.raises(FamilyLinkException, match="toggle failed"):
		await services_hass.services.async_call(
			DOMAIN,
			service,
			{"child_id": TEST_CHILD_ID},
			blocking=True,
		)

	client_call.assert_awaited_once_with(account_id=TEST_CHILD_ID)
	harness_coordinator.async_request_refresh.assert_not_awaited()


async def test_set_daily_limit_requires_device_id_before_dispatch(
	services_hass, harness_coordinator
):
	"""Daily-limit writes fail before dispatch when no device target is known."""
	with pytest.raises(ValueError, match="device_id is required"):
		await services_hass.services.async_call(
			DOMAIN,
			SERVICE_SET_DAILY_LIMIT,
			{"daily_minutes": 90, "child_id": TEST_CHILD_ID},
			blocking=True,
		)

	harness_coordinator.client.async_set_daily_limit.assert_not_awaited()
	harness_coordinator.async_request_refresh.assert_not_awaited()


async def test_set_daily_limit_false_result_skips_refresh(
	services_hass, harness_coordinator
):
	"""Daily-limit false results do not refresh coordinator data."""
	harness_coordinator.client.async_set_daily_limit.return_value = False

	await services_hass.services.async_call(
		DOMAIN,
		SERVICE_SET_DAILY_LIMIT,
		{
			"daily_minutes": 90,
			"device_id": TEST_DEVICE_ID,
			"child_id": TEST_CHILD_ID,
		},
		blocking=True,
	)

	harness_coordinator.client.async_set_daily_limit.assert_awaited_once_with(
		daily_minutes=90,
		device_id=TEST_DEVICE_ID,
		account_id=TEST_CHILD_ID,
	)
	harness_coordinator.async_request_refresh.assert_not_awaited()


async def test_bedtime_schedule_uses_entity_child_fallback_and_refreshes(
	services_hass, harness_coordinator
):
	"""Bedtime schedule writes can target a child from entity attributes."""
	_set_child_entity(services_hass)

	await services_hass.services.async_call(
		DOMAIN,
		SERVICE_SET_BEDTIME_SCHEDULE,
		{
			"entity_id": "switch.alex_tablet",
			"day": 2,
			"start_time": "21:00",
			"end_time": "06:30",
			"enabled": True,
		},
		blocking=True,
	)

	harness_coordinator.client.async_set_bedtime_schedule.assert_awaited_once_with(
		day=2,
		start_time="21:00",
		end_time="06:30",
		enabled=True,
		account_id=TEST_CHILD_ID,
	)
	harness_coordinator.async_request_refresh.assert_awaited_once()


async def test_bedtime_schedule_validation_fails_before_dispatch(
	services_hass, harness_coordinator
):
	"""Bedtime schedule validation rejects half-window updates."""
	with pytest.raises(ValueError, match="start_time and end_time"):
		await services_hass.services.async_call(
			DOMAIN,
			SERVICE_SET_BEDTIME_SCHEDULE,
			{"day": 2, "start_time": "21:00"},
			blocking=True,
		)

	harness_coordinator.client.async_set_bedtime_schedule.assert_not_awaited()
	harness_coordinator.async_request_refresh.assert_not_awaited()


async def test_bedtime_schedule_false_result_skips_refresh(
	services_hass, harness_coordinator
):
	"""Bedtime schedule false results do not refresh coordinator data."""
	harness_coordinator.client.async_set_bedtime_schedule.return_value = False

	await services_hass.services.async_call(
		DOMAIN,
		SERVICE_SET_BEDTIME_SCHEDULE,
		{"day": 3, "enabled": False, "child_id": TEST_CHILD_ID},
		blocking=True,
	)

	harness_coordinator.client.async_set_bedtime_schedule.assert_awaited_once_with(
		day=3,
		start_time=None,
		end_time=None,
		enabled=False,
		account_id=TEST_CHILD_ID,
	)
	harness_coordinator.async_request_refresh.assert_not_awaited()


async def test_bedtime_schedule_partial_error_refreshes_before_reraising(
	services_hass, harness_coordinator
):
	"""Partial bedtime schedule errors still refresh coordinator data."""
	harness_coordinator.client.async_set_bedtime_schedule.side_effect = (
		ScheduleUpdatePartialError(["window"], "enabled")
	)

	with pytest.raises(ScheduleUpdatePartialError):
		await services_hass.services.async_call(
			DOMAIN,
			SERVICE_SET_BEDTIME_SCHEDULE,
			{
				"day": 4,
				"start_time": "22:00",
				"end_time": "07:00",
				"enabled": True,
				"child_id": TEST_CHILD_ID,
			},
			blocking=True,
		)

	harness_coordinator.client.async_set_bedtime_schedule.assert_awaited_once_with(
		day=4,
		start_time="22:00",
		end_time="07:00",
		enabled=True,
		account_id=TEST_CHILD_ID,
	)
	harness_coordinator.async_request_refresh.assert_awaited_once()


async def test_daily_limit_schedule_uses_entity_child_fallback_and_refreshes(
	services_hass, harness_coordinator
):
	"""Daily-limit schedule writes can target a child from entity attributes."""
	_set_child_entity(services_hass)

	await services_hass.services.async_call(
		DOMAIN,
		SERVICE_SET_DAILY_LIMIT_SCHEDULE,
		{
			"entity_id": "switch.alex_tablet",
			"day": 5,
			"daily_minutes": 120,
		},
		blocking=True,
	)

	harness_coordinator.client.async_set_daily_limit_schedule.assert_awaited_once_with(
		day=5,
		daily_minutes=120,
		enabled=None,
		account_id=TEST_CHILD_ID,
	)
	harness_coordinator.async_request_refresh.assert_awaited_once()


async def test_daily_limit_schedule_no_change_validation_fails_before_dispatch(
	services_hass, harness_coordinator
):
	"""Daily-limit schedule writes require minutes, enabled, or both."""
	with pytest.raises(ValueError, match="Provide daily_minutes"):
		await services_hass.services.async_call(
			DOMAIN,
			SERVICE_SET_DAILY_LIMIT_SCHEDULE,
			{"day": 6},
			blocking=True,
		)

	harness_coordinator.client.async_set_daily_limit_schedule.assert_not_awaited()
	harness_coordinator.async_request_refresh.assert_not_awaited()


async def test_daily_limit_schedule_non_partial_exception_skips_refresh(
	services_hass, harness_coordinator
):
	"""Non-partial daily-limit schedule errors bubble without refreshing."""
	harness_coordinator.client.async_set_daily_limit_schedule.side_effect = (
		FamilyLinkException("daily schedule failed")
	)

	with pytest.raises(FamilyLinkException, match="daily schedule failed"):
		await services_hass.services.async_call(
			DOMAIN,
			SERVICE_SET_DAILY_LIMIT_SCHEDULE,
			{"day": 7, "enabled": True, "child_id": TEST_CHILD_ID},
			blocking=True,
		)

	harness_coordinator.client.async_set_daily_limit_schedule.assert_awaited_once_with(
		day=7,
		daily_minutes=None,
		enabled=True,
		account_id=TEST_CHILD_ID,
	)
	harness_coordinator.async_request_refresh.assert_not_awaited()


async def test_async_reload_entry_unloads_before_setup(
	hass, mock_config_entry, monkeypatch
):
	"""Reloading an entry unloads the old runtime before setting up again."""
	calls: list[str] = []

	async def fake_unload(unload_hass, unload_entry):
		assert unload_hass is hass
		assert unload_entry is mock_config_entry
		calls.append("unload")
		return True

	async def fake_setup(setup_hass, setup_entry):
		assert setup_hass is hass
		assert setup_entry is mock_config_entry
		calls.append("setup")
		return True

	monkeypatch.setattr(familylink, "async_unload_entry", fake_unload)
	monkeypatch.setattr(familylink, "async_setup_entry", fake_setup)

	await familylink.async_reload_entry(hass, mock_config_entry)

	assert calls == ["unload", "setup"]
