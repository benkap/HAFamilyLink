"""Tests for entity platform creation from coordinator data."""
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from custom_components.familylink import binary_sensor, button, device_tracker, sensor, switch
from custom_components.familylink.const import (
	DEVICE_LOCK_ACTION,
	DEVICE_UNLOCK_ACTION,
	DOMAIN,
)

from conftest import TEST_CHILD_ID, TEST_DEVICE_ID


async def _entities_for_platform(hass, mock_config_entry, harness_coordinator, platform):
	if hass.config_entries.async_get_entry(mock_config_entry.entry_id) is None:
		mock_config_entry.add_to_hass(hass)
	hass.data.setdefault(DOMAIN, {})[mock_config_entry.entry_id] = harness_coordinator
	entities = []

	def async_add_entities(new_entities, update_before_add=False):
		entities.extend(new_entities)

	await platform.async_setup_entry(hass, mock_config_entry, async_add_entities)
	return entities


def _entity_by_unique_id(entities, unique_id):
	return next(entity for entity in entities if entity.unique_id == unique_id)


def _sensor_by_unique_id(entities, unique_id):
	return _entity_by_unique_id(entities, unique_id)


def _patch_pending_time_limit_state(coordinator):
	"""Patch pending-state helpers onto a lightweight coordinator."""
	pending_states = {}

	def get_pending_time_limit_state(child_id, limit_type):
		return pending_states.get((child_id, limit_type))

	def set_pending_time_limit_state(child_id, limit_type, enabled):
		if enabled is None:
			pending_states.pop((child_id, limit_type), None)
		else:
			pending_states[(child_id, limit_type)] = enabled

	coordinator.get_pending_time_limit_state = get_pending_time_limit_state
	coordinator.set_pending_time_limit_state = set_pending_time_limit_state
	return pending_states


async def test_sensor_entities_include_unique_ids_device_info_and_attributes(
	hass, mock_config_entry, harness_coordinator
):
	"""Sensor setup creates child, schedule, app, and device sensors."""
	entities = await _entities_for_platform(
		hass, mock_config_entry, harness_coordinator, sensor
	)

	assert len(entities) == 27
	app_count = _entity_by_unique_id(entities, f"{DOMAIN}_{TEST_CHILD_ID}_app_count")
	assert app_count.native_value == 3
	assert app_count.extra_state_attributes["blocked_apps"] == 1
	assert (DOMAIN, TEST_CHILD_ID) in app_count.device_info["identifiers"]

	screen_time = _entity_by_unique_id(
		entities, f"{DOMAIN}_{TEST_CHILD_ID}_{TEST_DEVICE_ID}_screen_time_remaining"
	)
	assert screen_time.native_value == 60
	assert screen_time.extra_state_attributes["device_id"] == TEST_DEVICE_ID

	battery = _entity_by_unique_id(entities, f"{DOMAIN}_{TEST_CHILD_ID}_battery_level")
	assert battery.native_value == 84


async def test_switch_binary_button_and_tracker_entities_are_created(
	hass, mock_config_entry, harness_coordinator
):
	"""The non-sensor platforms create entities from the same coordinator payload."""
	switches = await _entities_for_platform(
		hass, mock_config_entry, harness_coordinator, switch
	)
	binary_sensors = await _entities_for_platform(
		hass, mock_config_entry, harness_coordinator, binary_sensor
	)
	buttons = await _entities_for_platform(
		hass, mock_config_entry, harness_coordinator, button
	)
	trackers = await _entities_for_platform(
		hass, mock_config_entry, harness_coordinator, device_tracker
	)

	assert len(switches) == 4
	device_switch = _entity_by_unique_id(
		switches, f"{DOMAIN}_{TEST_CHILD_ID}_{TEST_DEVICE_ID}"
	)
	assert device_switch.is_on is True
	assert device_switch.extra_state_attributes["child_id"] == TEST_CHILD_ID
	assert (DOMAIN, f"{TEST_CHILD_ID}_{TEST_DEVICE_ID}") in device_switch.device_info[
		"identifiers"
	]

	assert len(binary_sensors) == 3
	bedtime = _entity_by_unique_id(
		binary_sensors, f"{DOMAIN}_{TEST_CHILD_ID}_{TEST_DEVICE_ID}_bedtime_active"
	)
	assert bedtime.is_on is False
	assert bedtime.extra_state_attributes["device_id"] == TEST_DEVICE_ID

	assert len(buttons) == 5
	assert _entity_by_unique_id(
		buttons, f"{DOMAIN}_{TEST_CHILD_ID}_{TEST_DEVICE_ID}_bonus_15min"
	)

	assert len(trackers) == 1
	tracker = trackers[0]
	assert tracker.unique_id == f"{DOMAIN}_{TEST_CHILD_ID}_location"
	assert tracker.latitude == 32.0853
	assert tracker.extra_state_attributes["battery_level"] == 84


async def test_schedule_sensors_expose_weekday_today_and_timezone_attributes(
	hass, mock_config_entry, harness_coordinator
):
	"""Schedule sensors expose readable weekday values and timezone metadata."""
	entities = await _entities_for_platform(
		hass, mock_config_entry, harness_coordinator, sensor
	)

	bedtime = _entity_by_unique_id(
		entities, f"{DOMAIN}_{TEST_CHILD_ID}_bedtime_schedule"
	)
	daily_limit = _entity_by_unique_id(
		entities, f"{DOMAIN}_{TEST_CHILD_ID}_daily_limit_schedule"
	)

	assert bedtime.native_value == "enabled"
	assert bedtime.extra_state_attributes["enabled"] is True
	assert bedtime.extra_state_attributes["monday"] == "21:00-06:00"
	assert bedtime.extra_state_attributes["today"] == "21:00-06:00"
	assert bedtime.extra_state_attributes["schedule_today_key"] == "monday"
	assert bedtime.extra_state_attributes["schedule_timezone"] == "UTC"
	assert bedtime.extra_state_attributes["schedule_timezone_source"] == "config"
	assert daily_limit.extra_state_attributes["monday"] == "120 min"


async def test_screen_time_sensors_expose_usage_summary_and_app_breakdown(
	hass, mock_config_entry, harness_coordinator
):
	"""Screen time sensors expose totals and app usage in sorted order."""
	entities = await _entities_for_platform(
		hass, mock_config_entry, harness_coordinator, sensor
	)
	screen_time = _sensor_by_unique_id(
		entities, f"{DOMAIN}_{TEST_CHILD_ID}_screen_time_total"
	)
	formatted = _sensor_by_unique_id(
		entities, f"{DOMAIN}_{TEST_CHILD_ID}_screen_time_formatted"
	)

	assert screen_time.native_value == 90
	assert screen_time.available is True
	assert screen_time.extra_state_attributes["total_seconds"] == 5400
	assert screen_time.extra_state_attributes["app_count"] == 2
	assert screen_time.extra_state_attributes["apps"] == [
		{
			"name": "YouTube",
			"package": "com.google.android.youtube",
			"time": "01:00:00",
			"minutes": 60.0,
		},
		{
			"name": "Spotify",
			"package": "com.spotify.music",
			"time": "00:30:00",
			"minutes": 30.0,
		},
	]
	assert formatted.native_value == "01:30:00"
	assert formatted.extra_state_attributes["total_minutes"] == 90


@pytest.mark.parametrize(
	("unique_id", "value", "apps_attr"),
	[
		(
			f"{DOMAIN}_{TEST_CHILD_ID}_blocked_apps",
			1,
			[{"name": "YouTube", "package": "com.google.android.youtube"}],
		),
		(
			f"{DOMAIN}_{TEST_CHILD_ID}_apps_with_limits",
			1,
			[
				{
					"name": "Spotify",
					"package": "com.spotify.music",
					"limit_minutes": 45,
					"enabled": True,
				}
			],
		),
		(
			f"{DOMAIN}_{TEST_CHILD_ID}_always_allowed_apps",
			1,
			[{"name": "Calculator", "package": "com.android.calculator2"}],
		),
	],
)
async def test_app_category_sensors_list_matching_apps(
	hass, mock_config_entry, harness_coordinator, unique_id, value, apps_attr
):
	"""App category sensors list the apps behind each count."""
	entities = await _entities_for_platform(
		hass, mock_config_entry, harness_coordinator, sensor
	)
	entity = _sensor_by_unique_id(entities, unique_id)

	assert entity.native_value == value
	assert entity.available is True
	assert entity.extra_state_attributes["count"] == value
	assert entity.extra_state_attributes["apps"] == apps_attr


async def test_apps_without_limits_sensor_handles_empty_result(
	hass, mock_config_entry, harness_coordinator
):
	"""Apps-without-limits sensor returns zero and no bulky attributes when empty."""
	entities = await _entities_for_platform(
		hass, mock_config_entry, harness_coordinator, sensor
	)
	entity = _sensor_by_unique_id(
		entities, f"{DOMAIN}_{TEST_CHILD_ID}_apps_without_limits"
	)

	assert entity.native_value == 0
	assert entity.available is True
	assert entity.extra_state_attributes == {}


async def test_top_app_sensors_rank_usage_and_hide_missing_ranks(
	hass, mock_config_entry, harness_coordinator
):
	"""Top app sensors sort by usage and mark ranks without data unavailable."""
	entities = await _entities_for_platform(
		hass, mock_config_entry, harness_coordinator, sensor
	)
	first = _sensor_by_unique_id(entities, f"{DOMAIN}_{TEST_CHILD_ID}_top_app_1")
	second = _sensor_by_unique_id(entities, f"{DOMAIN}_{TEST_CHILD_ID}_top_app_2")
	third = _sensor_by_unique_id(entities, f"{DOMAIN}_{TEST_CHILD_ID}_top_app_3")

	assert first.native_value == 60
	assert first.available is True
	assert first.extra_state_attributes["app_name"] == "YouTube"
	assert first.extra_state_attributes["formatted_time"] == "01:00:00"
	assert second.native_value == 30
	assert second.extra_state_attributes["app_name"] == "Spotify"
	assert third.native_value is None
	assert third.available is False
	assert third.extra_state_attributes == {}


async def test_child_and_device_summary_sensors_expose_details(
	hass, mock_config_entry, harness_coordinator
):
	"""Child and device summary sensors expose useful identifying attributes."""
	entities = await _entities_for_platform(
		hass, mock_config_entry, harness_coordinator, sensor
	)
	child_info = _sensor_by_unique_id(entities, f"{DOMAIN}_{TEST_CHILD_ID}_child_info")
	device_count = _sensor_by_unique_id(
		entities, f"{DOMAIN}_{TEST_CHILD_ID}_device_count"
	)

	assert child_info.native_value == "Alex"
	assert child_info.available is True
	assert child_info.extra_state_attributes["birthday"] == "2016-06-23"
	assert child_info.extra_state_attributes["email"] == "alex@example.test"
	assert child_info.extra_state_attributes["age_band"] == "Child"
	assert device_count.native_value == 1
	assert device_count.extra_state_attributes["devices"] == [
		{"name": "Pixel Tablet", "model": "Pixel Tablet", "id": TEST_DEVICE_ID}
	]


async def test_device_quota_bonus_and_restriction_sensors_reflect_time_data(
	hass, mock_config_entry, harness_coordinator
):
	"""Device-level sensors expose quota, bonus, and restriction state."""
	entities = await _entities_for_platform(
		hass, mock_config_entry, harness_coordinator, sensor
	)
	remaining = _sensor_by_unique_id(
		entities, f"{DOMAIN}_{TEST_CHILD_ID}_{TEST_DEVICE_ID}_screen_time_remaining"
	)
	daily_limit = _sensor_by_unique_id(
		entities, f"{DOMAIN}_{TEST_CHILD_ID}_{TEST_DEVICE_ID}_daily_limit"
	)
	active_bonus = _sensor_by_unique_id(
		entities, f"{DOMAIN}_{TEST_CHILD_ID}_{TEST_DEVICE_ID}_active_bonus"
	)
	next_restriction = _sensor_by_unique_id(
		entities, f"{DOMAIN}_{TEST_CHILD_ID}_{TEST_DEVICE_ID}_next_restriction"
	)

	assert remaining.native_value == 60
	assert remaining.extra_state_attributes["percentage_used"] == 50.0
	assert daily_limit.native_value == 120
	assert daily_limit.extra_state_attributes["enabled"] is True
	assert active_bonus.native_value == 15
	assert active_bonus.extra_state_attributes["has_bonus"] is True
	assert next_restriction.native_value == "No restrictions"

	time_data = harness_coordinator.data["children_data"][0]["devices_time_data"][
		TEST_DEVICE_ID
	]
	time_data["bonus_minutes"] = 0
	time_data["remaining_minutes"] = 20

	assert active_bonus.native_value == 0
	assert active_bonus.extra_state_attributes["has_bonus"] is False
	assert next_restriction.native_value == "Daily limit 20min remaining"


@pytest.mark.parametrize(
	("battery_level", "icon"),
	[
		(95, "mdi:battery"),
		(75, "mdi:battery-80"),
		(55, "mdi:battery-60"),
		(35, "mdi:battery-40"),
		(15, "mdi:battery-20"),
		(5, "mdi:battery-alert-variant-outline"),
		(None, "mdi:battery-unknown"),
	],
)
async def test_battery_sensor_icons_follow_battery_level(
	hass, mock_config_entry, harness_coordinator, battery_level, icon
):
	"""Battery sensor chooses an icon for each battery range."""
	harness_coordinator.data["children_data"][0]["location"][
		"battery_level"
	] = battery_level
	entities = await _entities_for_platform(
		hass, mock_config_entry, harness_coordinator, sensor
	)
	battery = _sensor_by_unique_id(
		entities, f"{DOMAIN}_{TEST_CHILD_ID}_battery_level"
	)

	assert battery.native_value == battery_level
	assert battery.icon == icon
	assert battery.available is (battery_level is not None)


async def test_device_switch_reflects_lock_limit_bedtime_and_bonus_priority(
	hass, mock_config_entry, harness_coordinator
):
	"""Device switch state and icon explain the active restriction."""
	switches = await _entities_for_platform(
		hass, mock_config_entry, harness_coordinator, switch
	)
	device_switch = _entity_by_unique_id(
		switches, f"{DOMAIN}_{TEST_CHILD_ID}_{TEST_DEVICE_ID}"
	)
	child_data = harness_coordinator.data["children_data"][0]
	device = child_data["devices"][0]
	time_data = child_data["devices_time_data"][TEST_DEVICE_ID]

	device["locked"] = True
	assert device_switch.is_on is False
	assert device_switch.icon == "mdi:cellphone-lock"
	assert device_switch.extra_state_attributes["restriction_reason"] == "manually_locked"

	device["locked"] = False
	time_data["bonus_minutes"] = 0
	time_data["bedtime_active"] = True
	time_data["daily_limit_remaining"] = 30
	assert device_switch.is_on is False
	assert device_switch.icon == "mdi:cellphone-off"
	assert device_switch.extra_state_attributes["restriction_reason"] == "bedtime_active"

	time_data["bedtime_active"] = False
	time_data["daily_limit_remaining"] = 0
	assert device_switch.is_on is False
	assert device_switch.icon == "mdi:cellphone-remove"
	assert device_switch.extra_state_attributes["restriction_reason"] == "daily_limit_reached"

	time_data["bonus_minutes"] = 15
	assert device_switch.is_on is True
	assert device_switch.icon == "mdi:cellphone-clock"
	assert device_switch.extra_state_attributes["restriction_reason"] == "bonus_active"


async def test_time_limit_switches_prefer_pending_state_then_today_state(
	hass, mock_config_entry, harness_coordinator
):
	"""Child switches use pending UI state before today-effective API state."""
	pending_states = _patch_pending_time_limit_state(harness_coordinator)
	child_data = harness_coordinator.data["children_data"][0]
	child_data["bedtime_enabled"] = True
	child_data["bedtime_enabled_today"] = False

	switches = await _entities_for_platform(
		hass, mock_config_entry, harness_coordinator, switch
	)
	bedtime = _entity_by_unique_id(switches, f"{DOMAIN}_{TEST_CHILD_ID}_bedtime")

	assert bedtime.is_on is False
	pending_states[(TEST_CHILD_ID, "bedtime")] = True
	assert bedtime.is_on is True


@pytest.mark.parametrize(
	(
		"unique_id",
		"limit_type",
		"turn_method",
		"client_method",
		"expected_pending",
	),
	[
		(
			f"{DOMAIN}_{TEST_CHILD_ID}_bedtime",
			"bedtime",
			"async_turn_on",
			"async_enable_bedtime",
			True,
		),
		(
			f"{DOMAIN}_{TEST_CHILD_ID}_bedtime",
			"bedtime",
			"async_turn_off",
			"async_disable_bedtime",
			False,
		),
		(
			f"{DOMAIN}_{TEST_CHILD_ID}_school_time",
			"school_time",
			"async_turn_on",
			"async_enable_school_time",
			True,
		),
		(
			f"{DOMAIN}_{TEST_CHILD_ID}_school_time",
			"school_time",
			"async_turn_off",
			"async_disable_school_time",
			False,
		),
		(
			f"{DOMAIN}_{TEST_CHILD_ID}_daily_limit",
			"daily_limit",
			"async_turn_on",
			"async_enable_daily_limit",
			True,
		),
		(
			f"{DOMAIN}_{TEST_CHILD_ID}_daily_limit",
			"daily_limit",
			"async_turn_off",
			"async_disable_daily_limit",
			False,
		),
	],
)
async def test_time_limit_switch_actions_update_pending_state_and_refresh(
	hass,
	mock_config_entry,
	harness_coordinator,
	unique_id,
	limit_type,
	turn_method,
	client_method,
	expected_pending,
):
	"""Child switch actions dispatch to the client and refresh on success."""
	pending_states = _patch_pending_time_limit_state(harness_coordinator)
	switches = await _entities_for_platform(
		hass, mock_config_entry, harness_coordinator, switch
	)
	entity = _entity_by_unique_id(switches, unique_id)
	entity.async_write_ha_state = lambda: None

	await getattr(entity, turn_method)()

	assert pending_states[(TEST_CHILD_ID, limit_type)] is expected_pending
	getattr(harness_coordinator.client, client_method).assert_awaited_once_with(
		account_id=TEST_CHILD_ID
	)
	harness_coordinator.async_request_refresh.assert_awaited_once()


async def test_time_limit_switch_failed_action_clears_pending_state(
	hass, mock_config_entry, harness_coordinator
):
	"""Failed child switch actions clear optimistic UI state and skip refresh."""
	pending_states = _patch_pending_time_limit_state(harness_coordinator)
	harness_coordinator.client.async_enable_bedtime.return_value = False
	switches = await _entities_for_platform(
		hass, mock_config_entry, harness_coordinator, switch
	)
	bedtime = _entity_by_unique_id(switches, f"{DOMAIN}_{TEST_CHILD_ID}_bedtime")
	bedtime.async_write_ha_state = lambda: None

	await bedtime.async_turn_on()

	assert (TEST_CHILD_ID, "bedtime") not in pending_states
	harness_coordinator.client.async_enable_bedtime.assert_awaited_once_with(
		account_id=TEST_CHILD_ID
	)
	harness_coordinator.async_request_refresh.assert_not_awaited()


async def test_device_switch_actions_control_device_and_cancel_bonus_first(
	hass, mock_config_entry, harness_coordinator, monkeypatch
):
	"""Device switch actions unlock, or cancel bonus before locking."""
	switches = await _entities_for_platform(
		hass, mock_config_entry, harness_coordinator, switch
	)
	device_switch = _entity_by_unique_id(
		switches, f"{DOMAIN}_{TEST_CHILD_ID}_{TEST_DEVICE_ID}"
	)
	harness_coordinator.async_control_device = AsyncMock(return_value=True)
	sleep = AsyncMock()
	monkeypatch.setattr("custom_components.familylink.switch.asyncio.sleep", sleep)

	await device_switch.async_turn_on()
	await device_switch.async_turn_off()

	assert harness_coordinator.async_control_device.await_args_list[0].args == (
		TEST_DEVICE_ID,
		DEVICE_UNLOCK_ACTION,
		TEST_CHILD_ID,
	)
	harness_coordinator.client.async_cancel_time_bonus.assert_awaited_once_with(
		override_id="bonus-1",
		account_id=TEST_CHILD_ID,
	)
	sleep.assert_awaited_once_with(1)
	assert harness_coordinator.async_control_device.await_args_list[1].args == (
		TEST_DEVICE_ID,
		DEVICE_LOCK_ACTION,
		TEST_CHILD_ID,
	)


async def test_button_presses_dispatch_to_client_and_refresh(
	hass, mock_config_entry, harness_coordinator
):
	"""Time bonus and ring buttons call the expected client methods."""
	buttons = await _entities_for_platform(
		hass, mock_config_entry, harness_coordinator, button
	)
	bonus = _entity_by_unique_id(
		buttons, f"{DOMAIN}_{TEST_CHILD_ID}_{TEST_DEVICE_ID}_bonus_15min"
	)
	ring = _entity_by_unique_id(
		buttons, f"{DOMAIN}_{TEST_CHILD_ID}_{TEST_DEVICE_ID}_ring"
	)

	await bonus.async_press()
	await ring.async_press()

	harness_coordinator.client.async_add_time_bonus.assert_awaited_once_with(
		bonus_minutes=15,
		device_id=TEST_DEVICE_ID,
		account_id=TEST_CHILD_ID,
	)
	harness_coordinator.client.async_ring_device.assert_awaited_once_with(
		device_id=TEST_DEVICE_ID,
		child_id=TEST_CHILD_ID,
	)
	harness_coordinator.async_request_refresh.assert_awaited_once()


async def test_cancel_bonus_button_dispatches_only_when_bonus_exists(
	hass, mock_config_entry, harness_coordinator
):
	"""Cancel bonus button availability and dispatch follow coordinator data."""
	buttons = await _entities_for_platform(
		hass, mock_config_entry, harness_coordinator, button
	)
	cancel = _entity_by_unique_id(
		buttons, f"{DOMAIN}_{TEST_CHILD_ID}_{TEST_DEVICE_ID}_reset_bonus"
	)

	assert cancel.available is True
	await cancel.async_press()

	harness_coordinator.client.async_cancel_time_bonus.assert_awaited_once_with(
		override_id="bonus-1",
		account_id=TEST_CHILD_ID,
	)
	harness_coordinator.async_request_refresh.assert_awaited_once()

	harness_coordinator.client.async_cancel_time_bonus.reset_mock()
	harness_coordinator.async_request_refresh.reset_mock()
	harness_coordinator.data["children_data"][0]["devices_time_data"][TEST_DEVICE_ID][
		"bonus_override_id"
	] = None

	assert cancel.available is False
	await cancel.async_press()

	harness_coordinator.client.async_cancel_time_bonus.assert_not_awaited()
	harness_coordinator.async_request_refresh.assert_not_awaited()


@pytest.mark.parametrize(
	("unique_id", "field", "active_value", "active_icon", "inactive_icon"),
	[
		(
			f"{DOMAIN}_{TEST_CHILD_ID}_{TEST_DEVICE_ID}_bedtime_active",
			"bedtime_active",
			True,
			"mdi:sleep",
			"mdi:sleep-off",
		),
		(
			f"{DOMAIN}_{TEST_CHILD_ID}_{TEST_DEVICE_ID}_schooltime_active",
			"schooltime_active",
			True,
			"mdi:school",
			"mdi:school-outline",
		),
		(
			f"{DOMAIN}_{TEST_CHILD_ID}_{TEST_DEVICE_ID}_daily_limit_reached",
			"daily_limit_remaining",
			0,
			"mdi:timer-alert",
			"mdi:timer-check",
		),
	],
)
async def test_binary_sensor_states_icons_and_availability(
	hass,
	mock_config_entry,
	harness_coordinator,
	unique_id,
	field,
	active_value,
	active_icon,
	inactive_icon,
):
	"""Binary sensors derive state, icon, and availability from device time data."""
	entities = await _entities_for_platform(
		hass, mock_config_entry, harness_coordinator, binary_sensor
	)
	entity = _entity_by_unique_id(entities, unique_id)
	time_data = harness_coordinator.data["children_data"][0]["devices_time_data"][
		TEST_DEVICE_ID
	]

	assert entity.is_on is False
	assert entity.icon == inactive_icon
	assert entity.available is True

	time_data[field] = active_value

	assert entity.is_on is True
	assert entity.icon == active_icon

	harness_coordinator.data["children_data"][0]["devices_time_data"].clear()

	assert entity.available is False
	assert entity.extra_state_attributes == {}
