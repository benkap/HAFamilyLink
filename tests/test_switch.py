"""Focused tests for Family Link switch edge behavior."""
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from custom_components.familylink import switch as switch_platform
from custom_components.familylink.const import (
	ATTR_DEVICE_ID,
	ATTR_DEVICE_NAME,
	ATTR_DEVICE_TYPE,
	ATTR_LAST_SEEN,
	ATTR_LOCKED,
	DEVICE_LOCK_ACTION,
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


async def test_setup_creates_child_and_device_switches(
	hass, mock_config_entry, harness_coordinator
):
	"""Setup creates one switch group per child plus one switch per device."""
	child_data = harness_coordinator.data["children_data"][0]
	child_data["devices"].append({"id": "device-2", "name": "Phone"})

	switches = await _setup_switches(hass, mock_config_entry, harness_coordinator)

	assert {entity.unique_id for entity in switches} == {
		f"{DOMAIN}_{TEST_CHILD_ID}_bedtime",
		f"{DOMAIN}_{TEST_CHILD_ID}_school_time",
		f"{DOMAIN}_{TEST_CHILD_ID}_daily_limit",
		f"{DOMAIN}_{TEST_CHILD_ID}_{TEST_DEVICE_ID}",
		f"{DOMAIN}_{TEST_CHILD_ID}_device-2",
	}


@pytest.mark.parametrize(
	("coordinator_data", "expected_count"),
	[
		(None, 0),
		({}, 0),
		({"children_data": []}, 0),
		({"children_data": [{"child_id": TEST_CHILD_ID, "child_name": "Alex"}]}, 3),
	],
	ids=["none", "empty", "empty-children", "child-without-devices"],
)
async def test_setup_handles_missing_switch_data(
	hass, mock_config_entry, harness_coordinator, coordinator_data, expected_count
):
	"""Setup skips missing coordinator data and tolerates children without devices."""
	harness_coordinator.data = coordinator_data

	switches = await _setup_switches(hass, mock_config_entry, harness_coordinator)

	assert len(switches) == expected_count


async def test_device_switch_uses_initial_device_when_current_data_is_missing(
	hass, mock_config_entry, harness_coordinator
):
	"""Device switches keep useful fallback identity when live device data disappears."""
	device_id = "fallback-device"
	harness_coordinator.data["children_data"][0]["devices"] = [
		{
			"id": device_id,
			"type": "tablet",
			"model": "Nexus 7",
			"version": "15",
			"locked": True,
			"last_activity": 1234,
		}
	]
	harness_coordinator.data["children_data"][0]["devices_time_data"] = {}
	switches = await _setup_switches(hass, mock_config_entry, harness_coordinator)
	device_switch = _entity_by_unique_id(
		switches, f"{DOMAIN}_{TEST_CHILD_ID}_{device_id}"
	)

	harness_coordinator.data = None
	harness_coordinator.last_update_success = False

	assert device_switch.is_on is False
	assert device_switch.available is False
	assert device_switch.device_info["name"] == f"Alex Device {device_id}"
	assert device_switch.device_info["model"] == "Nexus 7"
	assert device_switch.extra_state_attributes == {
		ATTR_DEVICE_ID: device_id,
		ATTR_DEVICE_NAME: f"Alex Device {device_id}",
		"child_id": TEST_CHILD_ID,
		"child_name": "Alex",
		ATTR_DEVICE_TYPE: "tablet",
		ATTR_LAST_SEEN: 1234,
		ATTR_LOCKED: True,
		"model": "Nexus 7",
	}


async def test_device_switch_locks_even_when_bonus_cancel_fails(
	hass, mock_config_entry, harness_coordinator, monkeypatch
):
	"""Locking still proceeds if cancelling the active bonus fails."""
	switches = await _setup_switches(hass, mock_config_entry, harness_coordinator)
	device_switch = _entity_by_unique_id(
		switches, f"{DOMAIN}_{TEST_CHILD_ID}_{TEST_DEVICE_ID}"
	)
	harness_coordinator.client.async_cancel_time_bonus.return_value = False
	harness_coordinator.async_control_device = AsyncMock(return_value=True)
	sleep = AsyncMock()
	monkeypatch.setattr("custom_components.familylink.switch.asyncio.sleep", sleep)

	await device_switch.async_turn_off()

	harness_coordinator.client.async_cancel_time_bonus.assert_awaited_once_with(
		override_id="bonus-1",
		account_id=TEST_CHILD_ID,
	)
	sleep.assert_not_awaited()
	harness_coordinator.async_control_device.assert_awaited_once_with(
		TEST_DEVICE_ID,
		DEVICE_LOCK_ACTION,
		TEST_CHILD_ID,
	)


async def test_device_switch_turn_off_without_client_is_noop(
	hass, mock_config_entry, harness_coordinator
):
	"""Device lock action does nothing when the client is missing."""
	switches = await _setup_switches(hass, mock_config_entry, harness_coordinator)
	device_switch = _entity_by_unique_id(
		switches, f"{DOMAIN}_{TEST_CHILD_ID}_{TEST_DEVICE_ID}"
	)
	harness_coordinator.client = None
	harness_coordinator.async_control_device = AsyncMock()

	await device_switch.async_turn_off()

	harness_coordinator.async_control_device.assert_not_awaited()


@pytest.mark.parametrize(
	("unique_id", "limit_type", "weekly_field", "today_field"),
	[
		(f"{DOMAIN}_{TEST_CHILD_ID}_bedtime", "bedtime", "bedtime_enabled", "bedtime_enabled_today"),
		(
			f"{DOMAIN}_{TEST_CHILD_ID}_school_time",
			"school_time",
			"school_time_enabled",
			"school_time_enabled_today",
		),
		(f"{DOMAIN}_{TEST_CHILD_ID}_daily_limit", "daily_limit", "daily_limit_enabled", None),
	],
)
async def test_child_switches_use_pending_today_weekly_then_unknown_state(
	hass,
	mock_config_entry,
	harness_coordinator,
	unique_id,
	limit_type,
	weekly_field,
	today_field,
):
	"""Child switches prefer pending state, then today-effective, then weekly state."""
	pending_states = _patch_pending_time_limit_state(harness_coordinator)
	child_data = harness_coordinator.data["children_data"][0]
	child_data[weekly_field] = True
	if today_field:
		child_data[today_field] = False

	switches = await _setup_switches(hass, mock_config_entry, harness_coordinator)
	entity = _entity_by_unique_id(switches, unique_id)

	if today_field:
		assert entity.is_on is False
		child_data[today_field] = None

	assert entity.is_on is True

	pending_states[(TEST_CHILD_ID, limit_type)] = False
	assert entity.is_on is False

	pending_states.clear()
	child_data[weekly_field] = None
	assert entity.is_on is False


@pytest.mark.parametrize(
	("unique_id", "limit_type", "turn_method", "client_method"),
	[
		(
			f"{DOMAIN}_{TEST_CHILD_ID}_bedtime",
			"bedtime",
			"async_turn_on",
			"async_enable_bedtime",
		),
		(
			f"{DOMAIN}_{TEST_CHILD_ID}_bedtime",
			"bedtime",
			"async_turn_off",
			"async_disable_bedtime",
		),
		(
			f"{DOMAIN}_{TEST_CHILD_ID}_school_time",
			"school_time",
			"async_turn_on",
			"async_enable_school_time",
		),
		(
			f"{DOMAIN}_{TEST_CHILD_ID}_school_time",
			"school_time",
			"async_turn_off",
			"async_disable_school_time",
		),
		(
			f"{DOMAIN}_{TEST_CHILD_ID}_daily_limit",
			"daily_limit",
			"async_turn_on",
			"async_enable_daily_limit",
		),
		(
			f"{DOMAIN}_{TEST_CHILD_ID}_daily_limit",
			"daily_limit",
			"async_turn_off",
			"async_disable_daily_limit",
		),
	],
)
async def test_child_switch_failures_clear_pending_state_and_skip_refresh(
	hass,
	mock_config_entry,
	harness_coordinator,
	unique_id,
	limit_type,
	turn_method,
	client_method,
):
	"""Failed child switch actions clear optimistic state and do not refresh."""
	pending_states = _patch_pending_time_limit_state(harness_coordinator)
	getattr(harness_coordinator.client, client_method).return_value = False
	switches = await _setup_switches(hass, mock_config_entry, harness_coordinator)
	entity = _entity_by_unique_id(switches, unique_id)
	entity.async_write_ha_state = lambda: None

	await getattr(entity, turn_method)()

	assert (TEST_CHILD_ID, limit_type) not in pending_states
	getattr(harness_coordinator.client, client_method).assert_awaited_once_with(
		account_id=TEST_CHILD_ID
	)
	harness_coordinator.async_request_refresh.assert_not_awaited()


@pytest.mark.parametrize(
	("unique_id", "turn_method"),
	[
		(f"{DOMAIN}_{TEST_CHILD_ID}_bedtime", "async_turn_on"),
		(f"{DOMAIN}_{TEST_CHILD_ID}_bedtime", "async_turn_off"),
		(f"{DOMAIN}_{TEST_CHILD_ID}_school_time", "async_turn_on"),
		(f"{DOMAIN}_{TEST_CHILD_ID}_school_time", "async_turn_off"),
		(f"{DOMAIN}_{TEST_CHILD_ID}_daily_limit", "async_turn_on"),
		(f"{DOMAIN}_{TEST_CHILD_ID}_daily_limit", "async_turn_off"),
	],
)
async def test_child_switch_actions_without_client_are_noops(
	hass, mock_config_entry, harness_coordinator, unique_id, turn_method
):
	"""Child switch actions do not set pending state or refresh without a client."""
	pending_states = _patch_pending_time_limit_state(harness_coordinator)
	switches = await _setup_switches(hass, mock_config_entry, harness_coordinator)
	entity = _entity_by_unique_id(switches, unique_id)
	entity.async_write_ha_state = lambda: None
	harness_coordinator.client = None

	await getattr(entity, turn_method)()

	assert pending_states == {}
	harness_coordinator.async_request_refresh.assert_not_awaited()
