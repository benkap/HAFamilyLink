"""Focused tests for Family Link device tracker edge behavior."""
from __future__ import annotations

import pytest
from homeassistant.components.device_tracker import SourceType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.familylink import device_tracker
from custom_components.familylink.const import CONF_ENABLE_LOCATION_TRACKING, DOMAIN

from conftest import TEST_CHILD_ID


async def _device_trackers_for_entry(hass, mock_config_entry, coordinator):
	if hass.config_entries.async_get_entry(mock_config_entry.entry_id) is None:
		mock_config_entry.add_to_hass(hass)
	hass.data.setdefault(DOMAIN, {})[mock_config_entry.entry_id] = coordinator
	entities = []

	def async_add_entities(new_entities, update_before_add=False):
		entities.extend(new_entities)

	await device_tracker.async_setup_entry(hass, mock_config_entry, async_add_entities)
	return entities


def _tracker_by_unique_id(entities, unique_id):
	return next(entity for entity in entities if entity.unique_id == unique_id)


def _child_data(coordinator):
	return coordinator.data["children_data"][0]


def _entry_with_location_option(mock_config_entry, enabled):
	return MockConfigEntry(
		domain=DOMAIN,
		title=mock_config_entry.title,
		data={
			**mock_config_entry.data,
			CONF_ENABLE_LOCATION_TRACKING: not enabled,
		},
		options={CONF_ENABLE_LOCATION_TRACKING: enabled},
		entry_id=f"{mock_config_entry.entry_id}-location-option-{enabled}",
		unique_id=f"{mock_config_entry.unique_id}-location-option-{enabled}",
	)


async def test_setup_creates_tracker_identity_for_each_child(
	hass, mock_config_entry, harness_coordinator
):
	"""Setup creates one tracker per child with stable HA identity metadata."""
	harness_coordinator.data["children_data"].append(
		{
			"child_id": "child-2",
			"child_name": "Sam",
			"location": {"latitude": 40.7128, "longitude": -74.006},
		}
	)

	trackers = await _device_trackers_for_entry(
		hass, mock_config_entry, harness_coordinator
	)

	assert {tracker.unique_id for tracker in trackers} == {
		f"{DOMAIN}_{TEST_CHILD_ID}_location",
		f"{DOMAIN}_child-2_location",
	}
	tracker = _tracker_by_unique_id(trackers, f"{DOMAIN}_{TEST_CHILD_ID}_location")
	assert tracker.name is None
	assert tracker.source_type is SourceType.GPS
	assert tracker.device_info["identifiers"] == {(DOMAIN, TEST_CHILD_ID)}
	assert tracker.device_info["name"] == "Alex (Family Link)"
	assert tracker.device_info["manufacturer"] == "Google"
	assert tracker.device_info["model"] == "Family Link Account"


@pytest.mark.parametrize(
	("enabled", "expected_count"),
	[(True, 1), (False, 0)],
	ids=["enabled", "disabled"],
)
async def test_location_tracking_option_controls_setup(
	hass, mock_config_entry, harness_coordinator, enabled, expected_count
):
	"""Config entry options take precedence for creating device trackers."""
	entry = _entry_with_location_option(mock_config_entry, enabled)

	trackers = await _device_trackers_for_entry(hass, entry, harness_coordinator)

	assert len(trackers) == expected_count


async def test_location_values_and_attributes_use_current_payload(
	hass, mock_config_entry, harness_coordinator
):
	"""Tracker coordinates and attributes come from the latest child location."""
	child_data = _child_data(harness_coordinator)
	child_data["location"].update(
		{
			"place_name": "Home",
			"place_address": "1 Test Street",
			"battery_level": 0,
		}
	)
	trackers = await _device_trackers_for_entry(
		hass, mock_config_entry, harness_coordinator
	)
	tracker = _tracker_by_unique_id(trackers, f"{DOMAIN}_{TEST_CHILD_ID}_location")

	assert tracker.latitude == 32.0853
	assert tracker.longitude == 34.7818
	assert tracker.location_accuracy == 25
	attributes = tracker.extra_state_attributes
	assert attributes["source_device"] == "Pixel Tablet"
	assert attributes["place_name"] == "Home"
	assert attributes["address"] == "1 Test Street"
	assert attributes["location_timestamp"] == "2026-06-23T12:00:00+00:00"
	assert attributes["battery_level"] == 0


@pytest.mark.parametrize(
	"location",
	[
		None,
		{},
		{"latitude": None, "longitude": None, "accuracy": None},
	],
	ids=["missing", "empty", "empty-values"],
)
async def test_missing_or_empty_location_keeps_tracker_available_without_coordinates(
	hass, mock_config_entry, harness_coordinator, location
):
	"""A child can be tracked as available even when location data is unknown."""
	child_data = _child_data(harness_coordinator)
	if location is None:
		child_data.pop("location")
	else:
		child_data["location"] = location

	trackers = await _device_trackers_for_entry(
		hass, mock_config_entry, harness_coordinator
	)
	tracker = _tracker_by_unique_id(trackers, f"{DOMAIN}_{TEST_CHILD_ID}_location")

	assert tracker.available is True
	assert tracker.source_type is SourceType.GPS
	assert tracker.latitude is None
	assert tracker.longitude is None
	assert tracker.location_accuracy == 0
	assert tracker.extra_state_attributes == {}


async def test_optional_location_attributes_skip_empty_values(
	hass, mock_config_entry, harness_coordinator
):
	"""Only populated location metadata is exposed as extra state attributes."""
	_child_data(harness_coordinator)["location"] = {
		"latitude": 32.0,
		"longitude": 34.0,
		"accuracy": None,
		"source_device_name": "",
		"place_name": "",
		"place_address": None,
		"timestamp_iso": "",
		"battery_level": None,
	}
	trackers = await _device_trackers_for_entry(
		hass, mock_config_entry, harness_coordinator
	)
	tracker = _tracker_by_unique_id(trackers, f"{DOMAIN}_{TEST_CHILD_ID}_location")

	assert tracker.latitude == 32.0
	assert tracker.longitude == 34.0
	assert tracker.location_accuracy == 0
	assert tracker.extra_state_attributes == {}


@pytest.mark.parametrize(
	("coordinator_data", "last_update_success"),
	[
		(None, True),
		({}, True),
		({"children_data": []}, True),
		({"children_data": [{"child_id": "other-child", "child_name": "Sam"}]}, True),
		(None, False),
	],
	ids=[
		"no-data",
		"empty-data",
		"empty-children",
		"different-child",
		"failed-update",
	],
)
async def test_tracker_becomes_unavailable_when_current_child_data_is_missing(
	hass,
	mock_config_entry,
	harness_coordinator,
	coordinator_data,
	last_update_success,
):
	"""Existing trackers follow coordinator availability and current child rows."""
	trackers = await _device_trackers_for_entry(
		hass, mock_config_entry, harness_coordinator
	)
	tracker = _tracker_by_unique_id(trackers, f"{DOMAIN}_{TEST_CHILD_ID}_location")

	harness_coordinator.data = coordinator_data
	harness_coordinator.last_update_success = last_update_success

	assert tracker.available is False
	assert tracker.latitude is None
	assert tracker.longitude is None
	assert tracker.location_accuracy == 0
	assert tracker.extra_state_attributes == {}


async def test_tracker_reads_updated_coordinator_location_after_setup(
	hass, mock_config_entry, harness_coordinator
):
	"""Tracker properties read from coordinator data each time they are accessed."""
	trackers = await _device_trackers_for_entry(
		hass, mock_config_entry, harness_coordinator
	)
	tracker = _tracker_by_unique_id(trackers, f"{DOMAIN}_{TEST_CHILD_ID}_location")

	_child_data(harness_coordinator)["location"] = {
		"latitude": 31.7683,
		"longitude": 35.2137,
		"accuracy": 7,
		"source_device_name": "Phone",
		"timestamp_iso": "2026-06-24T09:30:00+00:00",
	}

	assert tracker.latitude == 31.7683
	assert tracker.longitude == 35.2137
	assert tracker.location_accuracy == 7
	assert tracker.extra_state_attributes["source_device"] == "Phone"
	assert (
		tracker.extra_state_attributes["location_timestamp"]
		== "2026-06-24T09:30:00+00:00"
	)
