"""Additional focused tests for Family Link switch edge behavior."""
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from custom_components.familylink import switch as switch_platform
from custom_components.familylink.const import (
	ATTR_DEVICE_ID,
	ATTR_DEVICE_NAME,
	ATTR_LOCKED,
	DEVICE_LOCK_ACTION,
	DEVICE_UNLOCK_ACTION,
	DOMAIN,
)

from conftest import TEST_CHILD_ID, TEST_DEVICE_ID


async def _setup_switches(hass, mock_config_entry, coordinator):
	"""Create switch entities from the lightweight coordinator fixture."""
	if hass.config_entries.async_get_entry(mock_config_entry.entry_id) is None:
		mock_config_entry.add_to_hass(hass)

	hass.data.setdefault(DOMAIN, {})[mock_config_entry.entry_id] = coordinator
	entities = []

	def async_add_entities(new_entities, update_before_add=False):
		entities.extend(new_entities)

	await switch_platform.async_setup_entry(hass, mock_config_entry, async_add_entities)
	return entities


def _entity_by_unique_id(entities, unique_id):
	return next(entity for entity in entities if entity.unique_id == unique_id)


def _patch_pending_time_limit_state(coordinator):
	pending_states = {}

	def get_pending_time_limit_state(child_id, limit_type):
		return pending_states.get((child_id, limit_type))

	def set_pending_time_limit_state(child_id, limit_type, enabled):
		key = (child_id, limit_type)
		if enabled is None:
			pending_states.pop(key, None)
		else:
			pending_states[key] = enabled

	coordinator.get_pending_time_limit_state = get_pending_time_limit_state
	coordinator.set_pending_time_limit_state = set_pending_time_limit_state
	return pending_states


async def test_device_switch_uses_initial_unlocked_device_when_live_device_is_missing(
	hass, mock_config_entry, harness_coordinator
):
	"""A stale device payload still reports the device usable by default."""
	switches = await _setup_switches(hass, mock_config_entry, harness_coordinator)
	device_switch = _entity_by_unique_id(
		switches, f"{DOMAIN}_{TEST_CHILD_ID}_{TEST_DEVICE_ID}"
	)
	child_data = harness_coordinator.data["children_data"][0]
	time_data = child_data["devices_time_data"][TEST_DEVICE_ID]

	child_data["devices"] = []
	time_data["bonus_minutes"] = 0
	time_data["bedtime_active"] = False
	time_data["daily_limit_remaining"] = 30

	assert device_switch.is_on is True
	assert device_switch.icon == "mdi:cellphone"
	assert device_switch.extra_state_attributes[ATTR_DEVICE_ID] == TEST_DEVICE_ID
	assert device_switch.extra_state_attributes[ATTR_DEVICE_NAME] == "Pixel Tablet"
	assert device_switch.extra_state_attributes[ATTR_LOCKED] is False
	assert device_switch.extra_state_attributes["restriction_reason"] == "none"


@pytest.mark.parametrize(
	("time_data_changes", "expected_icon", "expected_reason", "expected_is_on"),
	[
		(
			{"bonus_minutes": 0, "bedtime_active": True, "daily_limit_remaining": 45},
			"mdi:cellphone-off",
			"bedtime_active",
			False,
		),
		(
			{"bonus_minutes": 0, "bedtime_active": False, "daily_limit_remaining": 0},
			"mdi:cellphone-remove",
			"daily_limit_reached",
			False,
		),
		(
			{"bonus_minutes": 20, "bedtime_active": True, "daily_limit_remaining": 0},
			"mdi:cellphone-clock",
			"bonus_active",
			True,
		),
	],
	ids=["bedtime", "daily-limit", "bonus"],
)
async def test_device_switch_explains_remaining_restriction_states(
	hass,
	mock_config_entry,
	harness_coordinator,
	time_data_changes,
	expected_icon,
	expected_reason,
	expected_is_on,
):
	"""Restriction icon and reason stay aligned when time data changes."""
	switches = await _setup_switches(hass, mock_config_entry, harness_coordinator)
	device_switch = _entity_by_unique_id(
		switches, f"{DOMAIN}_{TEST_CHILD_ID}_{TEST_DEVICE_ID}"
	)
	device = harness_coordinator.data["children_data"][0]["devices"][0]
	time_data = harness_coordinator.data["children_data"][0]["devices_time_data"][
		TEST_DEVICE_ID
	]
	device["locked"] = False
	time_data.update(time_data_changes)

	assert device_switch.is_on is expected_is_on
	assert device_switch.icon == expected_icon
	assert device_switch.extra_state_attributes["restriction_reason"] == expected_reason


async def test_device_switch_turn_on_logs_failure_without_extra_refresh(
	hass, mock_config_entry, harness_coordinator
):
	"""An unlock failure is contained to the coordinator control call."""
	switches = await _setup_switches(hass, mock_config_entry, harness_coordinator)
	device_switch = _entity_by_unique_id(
		switches, f"{DOMAIN}_{TEST_CHILD_ID}_{TEST_DEVICE_ID}"
	)
	harness_coordinator.async_control_device = AsyncMock(return_value=False)

	await device_switch.async_turn_on()

	harness_coordinator.async_control_device.assert_awaited_once_with(
		TEST_DEVICE_ID,
		DEVICE_UNLOCK_ACTION,
		TEST_CHILD_ID,
	)
	harness_coordinator.async_request_refresh.assert_not_awaited()


async def test_device_switch_turn_off_without_bonus_skips_cancel_and_locks(
	hass, mock_config_entry, harness_coordinator, monkeypatch
):
	"""Locking skips bonus cancellation when no active bonus override exists."""
	switches = await _setup_switches(hass, mock_config_entry, harness_coordinator)
	device_switch = _entity_by_unique_id(
		switches, f"{DOMAIN}_{TEST_CHILD_ID}_{TEST_DEVICE_ID}"
	)
	time_data = harness_coordinator.data["children_data"][0]["devices_time_data"][
		TEST_DEVICE_ID
	]
	time_data["bonus_minutes"] = 0
	time_data["bonus_override_id"] = None
	harness_coordinator.async_control_device = AsyncMock(return_value=True)
	sleep = AsyncMock()
	monkeypatch.setattr("custom_components.familylink.switch.asyncio.sleep", sleep)

	await device_switch.async_turn_off()

	harness_coordinator.client.async_cancel_time_bonus.assert_not_awaited()
	sleep.assert_not_awaited()
	harness_coordinator.async_control_device.assert_awaited_once_with(
		TEST_DEVICE_ID,
		DEVICE_LOCK_ACTION,
		TEST_CHILD_ID,
	)


@pytest.mark.parametrize(
	("unique_id", "limit_type", "enabled_icon", "disabled_icon"),
	[
		(
			f"{DOMAIN}_{TEST_CHILD_ID}_bedtime",
			"bedtime",
			"mdi:sleep",
			"mdi:sleep-off",
		),
		(
			f"{DOMAIN}_{TEST_CHILD_ID}_school_time",
			"school_time",
			"mdi:school",
			"mdi:school-outline",
		),
		(
			f"{DOMAIN}_{TEST_CHILD_ID}_daily_limit",
			"daily_limit",
			"mdi:timer",
			"mdi:timer-off",
		),
	],
)
async def test_child_switch_icons_follow_pending_state(
	hass,
	mock_config_entry,
	harness_coordinator,
	unique_id,
	limit_type,
	enabled_icon,
	disabled_icon,
):
	"""Child switch icons use the same pending-state precedence as is_on."""
	pending_states = _patch_pending_time_limit_state(harness_coordinator)
	switches = await _setup_switches(hass, mock_config_entry, harness_coordinator)
	entity = _entity_by_unique_id(switches, unique_id)

	pending_states[(TEST_CHILD_ID, limit_type)] = True
	assert entity.icon == enabled_icon

	pending_states[(TEST_CHILD_ID, limit_type)] = False
	assert entity.icon == disabled_icon
