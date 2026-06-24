"""Focused tests for Family Link binary sensors."""
from __future__ import annotations

from datetime import datetime

import pytest

from custom_components.familylink import binary_sensor
from custom_components.familylink.const import DOMAIN

from conftest import TEST_CHILD_ID, TEST_DEVICE_ID


async def _binary_sensors_for_entry(hass, mock_config_entry, harness_coordinator):
    if hass.config_entries.async_get_entry(mock_config_entry.entry_id) is None:
        mock_config_entry.add_to_hass(hass)
    hass.data.setdefault(DOMAIN, {})[mock_config_entry.entry_id] = harness_coordinator
    entities = []

    def async_add_entities(new_entities, update_before_add=False):
        entities.extend(new_entities)

    await binary_sensor.async_setup_entry(hass, mock_config_entry, async_add_entities)
    return entities


def _entity_by_unique_id(entities, unique_id):
    return next(entity for entity in entities if entity.unique_id == unique_id)


def _time_data(harness_coordinator):
    return harness_coordinator.data["children_data"][0]["devices_time_data"][
        TEST_DEVICE_ID
    ]


@pytest.mark.parametrize(
    "coordinator_data",
    [None, {}, {"children_data": []}],
    ids=["none", "empty", "empty-children"],
)
async def test_setup_skips_missing_children_data(
    hass, mock_config_entry, harness_coordinator, coordinator_data
):
    """Setup creates no binary sensors when child data is unavailable."""
    harness_coordinator.data = coordinator_data

    entities = await _binary_sensors_for_entry(
        hass, mock_config_entry, harness_coordinator
    )

    assert entities == []


async def test_setup_creates_device_binary_sensors_and_device_info(
    hass, mock_config_entry, harness_coordinator
):
    """Setup creates the expected device binary sensors with readable metadata."""
    entities = await _binary_sensors_for_entry(
        hass, mock_config_entry, harness_coordinator
    )

    assert {entity.unique_id for entity in entities} == {
        f"{DOMAIN}_{TEST_CHILD_ID}_{TEST_DEVICE_ID}_bedtime_active",
        f"{DOMAIN}_{TEST_CHILD_ID}_{TEST_DEVICE_ID}_schooltime_active",
        f"{DOMAIN}_{TEST_CHILD_ID}_{TEST_DEVICE_ID}_daily_limit_reached",
    }

    bedtime = _entity_by_unique_id(
        entities, f"{DOMAIN}_{TEST_CHILD_ID}_{TEST_DEVICE_ID}_bedtime_active"
    )
    assert bedtime.device_info["identifiers"] == {
        (DOMAIN, f"{TEST_CHILD_ID}_{TEST_DEVICE_ID}")
    }
    assert bedtime.device_info["model"] == "Pixel Tablet"
    assert bedtime.device_info["sw_version"] == "14"
    assert bedtime.device_info["via_device"] == (DOMAIN, TEST_CHILD_ID)


@pytest.mark.parametrize(
    ("last_update_success", "has_time_data", "expected_available"),
    [
        (True, True, True),
        (False, True, False),
        (True, False, False),
        (False, False, False),
    ],
)
async def test_availability_requires_successful_update_and_device_time_data(
    hass,
    mock_config_entry,
    harness_coordinator,
    last_update_success,
    has_time_data,
    expected_available,
):
    """Base availability requires coordinator success and device time data."""
    entities = await _binary_sensors_for_entry(
        hass, mock_config_entry, harness_coordinator
    )
    bedtime = _entity_by_unique_id(
        entities, f"{DOMAIN}_{TEST_CHILD_ID}_{TEST_DEVICE_ID}_bedtime_active"
    )

    harness_coordinator.last_update_success = last_update_success
    if not has_time_data:
        harness_coordinator.data["children_data"][0]["devices_time_data"].clear()

    assert bedtime.available is expected_available


@pytest.mark.parametrize(
    (
        "unique_id_suffix",
        "window_key",
        "start_attr",
        "end_attr",
        "valid_start_ms",
        "valid_end_ms",
    ),
    [
        (
            "bedtime_active",
            "bedtime_window",
            "bedtime_start",
            "bedtime_end",
            1710021600000,
            1710050400000,
        ),
        (
            "schooltime_active",
            "schooltime_window",
            "schooltime_start",
            "schooltime_end",
            1710061200000,
            1710075600000,
        ),
    ],
)
async def test_time_window_attributes_convert_valid_timestamps_and_skip_invalid(
    hass,
    mock_config_entry,
    harness_coordinator,
    unique_id_suffix,
    window_key,
    start_attr,
    end_attr,
    valid_start_ms,
    valid_end_ms,
):
    """Bedtime and schooltime attributes convert valid timestamps and skip bad ones."""
    entities = await _binary_sensors_for_entry(
        hass, mock_config_entry, harness_coordinator
    )
    entity = _entity_by_unique_id(
        entities, f"{DOMAIN}_{TEST_CHILD_ID}_{TEST_DEVICE_ID}_{unique_id_suffix}"
    )
    time_data = _time_data(harness_coordinator)
    time_data[window_key] = {
        "start_ms": valid_start_ms,
        "end_ms": valid_end_ms,
    }

    attrs = entity.extra_state_attributes

    assert attrs[start_attr] == datetime.fromtimestamp(
        valid_start_ms / 1000
    ).isoformat()
    assert attrs[end_attr] == datetime.fromtimestamp(valid_end_ms / 1000).isoformat()

    time_data[window_key] = {
        "start_ms": float("nan"),
        "end_ms": float("nan"),
    }

    attrs = entity.extra_state_attributes

    assert start_attr not in attrs
    assert end_attr not in attrs


@pytest.mark.parametrize(
    ("daily_limit_remaining", "expected_on", "expected_icon"),
    [
        (None, False, "mdi:timer-check"),
        (15, False, "mdi:timer-check"),
        (0, True, "mdi:timer-alert"),
        (-1, True, "mdi:timer-alert"),
    ],
)
async def test_daily_limit_reached_handles_remaining_edges(
    hass,
    mock_config_entry,
    harness_coordinator,
    daily_limit_remaining,
    expected_on,
    expected_icon,
):
    """Daily-limit reached handles empty, positive, zero, and negative remaining values."""
    entities = await _binary_sensors_for_entry(
        hass, mock_config_entry, harness_coordinator
    )
    daily_limit = _entity_by_unique_id(
        entities, f"{DOMAIN}_{TEST_CHILD_ID}_{TEST_DEVICE_ID}_daily_limit_reached"
    )
    time_data = _time_data(harness_coordinator)
    time_data["daily_limit_remaining"] = daily_limit_remaining
    time_data["remaining_minutes"] = 23

    assert daily_limit.is_on is expected_on
    assert daily_limit.icon == expected_icon
    assert daily_limit.extra_state_attributes["remaining_minutes"] == 23
