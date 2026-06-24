"""Focused tests for Family Link sensor device/detail edge behavior."""
from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

from homeassistant.const import EntityCategory

from custom_components.familylink import sensor as sensor_platform
from custom_components.familylink.const import DOMAIN
from custom_components.familylink.sensor import (
    ActiveBonusSensor,
    DailyLimitDeviceSensor,
    FamilyLinkBatteryLevelSensor,
    FamilyLinkChildInfoSensor,
    FamilyLinkDeviceCountSensor,
    NextRestrictionSensor,
    ScreenTimeRemainingSensor,
)

from conftest import TEST_CHILD_ID, TEST_DEVICE_ID

CHILD_NAME = "Alex"
DEVICE_NAME = "Pixel Tablet"


async def _sensor_entities_for_entry(hass, mock_config_entry, coordinator):
    """Create sensor entities from the lightweight coordinator fixture."""
    if hass.config_entries.async_get_entry(mock_config_entry.entry_id) is None:
        mock_config_entry.add_to_hass(hass)

    hass.data.setdefault(DOMAIN, {})[mock_config_entry.entry_id] = coordinator
    entities = []

    def async_add_entities(new_entities, update_before_add=False):
        entities.extend(new_entities)

    await sensor_platform.async_setup_entry(hass, mock_config_entry, async_add_entities)
    return entities


def _entity_by_unique_id(entities, unique_id):
    return next(entity for entity in entities if entity.unique_id == unique_id)


def _coordinator(child_overrides: dict | None = None) -> SimpleNamespace:
    child_data = {
        "child_id": TEST_CHILD_ID,
        "child_name": CHILD_NAME,
        **(child_overrides or {}),
    }
    coordinator = SimpleNamespace(
        data={"children_data": [child_data]},
        last_update_success=True,
    )
    coordinator.async_add_listener = lambda update_callback, context=None: lambda: None
    return coordinator


def _device_sensor_set(coordinator):
    return {
        "remaining": ScreenTimeRemainingSensor(
            coordinator, TEST_CHILD_ID, CHILD_NAME, TEST_DEVICE_ID, DEVICE_NAME
        ),
        "next_restriction": NextRestrictionSensor(
            coordinator, TEST_CHILD_ID, CHILD_NAME, TEST_DEVICE_ID, DEVICE_NAME
        ),
        "daily_limit": DailyLimitDeviceSensor(
            coordinator, TEST_CHILD_ID, CHILD_NAME, TEST_DEVICE_ID, DEVICE_NAME
        ),
        "active_bonus": ActiveBonusSensor(
            coordinator, TEST_CHILD_ID, CHILD_NAME, TEST_DEVICE_ID, DEVICE_NAME
        ),
    }


async def test_setup_uses_unknown_device_name_for_device_sensor_identity(
    hass, mock_config_entry, harness_coordinator
):
    """Device sensors keep stable IDs and HA device info when a name is missing."""
    device_id = "nameless-device"
    child_data = harness_coordinator.data["children_data"][0]
    child_data["devices"] = [{"id": device_id}]
    child_data["devices_time_data"] = {device_id: {}}

    entities = await _sensor_entities_for_entry(
        hass, mock_config_entry, harness_coordinator
    )

    expected_unique_ids = {
        f"{DOMAIN}_{TEST_CHILD_ID}_{device_id}_screen_time_remaining",
        f"{DOMAIN}_{TEST_CHILD_ID}_{device_id}_next_restriction",
        f"{DOMAIN}_{TEST_CHILD_ID}_{device_id}_daily_limit",
        f"{DOMAIN}_{TEST_CHILD_ID}_{device_id}_active_bonus",
    }
    device_entities = {
        entity.unique_id: entity
        for entity in entities
        if f"_{device_id}_" in entity.unique_id
    }

    assert set(device_entities) == expected_unique_ids
    assert device_entities[
        f"{DOMAIN}_{TEST_CHILD_ID}_{device_id}_screen_time_remaining"
    ].name == "Unknown Device Screen Time Remaining"
    assert device_entities[
        f"{DOMAIN}_{TEST_CHILD_ID}_{device_id}_next_restriction"
    ].entity_category == EntityCategory.DIAGNOSTIC

    for entity in device_entities.values():
        assert entity.device_info["identifiers"] == {
            (DOMAIN, f"{TEST_CHILD_ID}_{device_id}")
        }
        assert entity.device_info["name"] == "Unknown Device"
        assert entity.device_info["manufacturer"] == "Google"
        assert entity.device_info["model"] == "Family Link Device"
        assert entity.device_info["via_device"] == (DOMAIN, TEST_CHILD_ID)


def test_child_sensor_device_info_uses_family_link_account_identity() -> None:
    """Child-level sensors attach to the Family Link account device."""
    entity = FamilyLinkChildInfoSensor(_coordinator({"child": {}}), TEST_CHILD_ID, CHILD_NAME)

    assert entity.name == "Alex Child Info"
    assert entity.unique_id == f"{DOMAIN}_{TEST_CHILD_ID}_child_info"
    assert entity.device_info["identifiers"] == {(DOMAIN, TEST_CHILD_ID)}
    assert entity.device_info["name"] == "Alex (Family Link)"
    assert entity.device_info["manufacturer"] == "Google"
    assert entity.device_info["model"] == "Family Link Account"


def test_child_info_handles_missing_profile_details() -> None:
    """Child info falls back cleanly when profile details are incomplete."""
    entity = FamilyLinkChildInfoSensor(
        _coordinator(
            {
                "child": {
                    "userId": TEST_CHILD_ID,
                    "role": "MEMBER",
                    "profile": {"birthday": {"year": 2016, "month": None, "day": 23}},
                }
            }
        ),
        TEST_CHILD_ID,
        CHILD_NAME,
    )

    attributes = entity.extra_state_attributes

    assert entity.native_value == "Unknown"
    assert entity.available is True
    assert attributes["user_id"] == TEST_CHILD_ID
    assert attributes["role"] == "MEMBER"
    assert attributes["display_name"] is None
    assert attributes["given_name"] is None
    assert attributes["family_name"] is None
    assert attributes["email"] is None
    assert "birthday" not in attributes
    assert "age_band" not in attributes


def test_device_count_lists_unknown_optional_device_fields() -> None:
    """Device count keeps the count and marks missing optional details unknown."""
    entity = FamilyLinkDeviceCountSensor(
        _coordinator(
            {
                "devices": [
                    {},
                    {"id": "phone-1", "name": "Phone"},
                ]
            }
        ),
        TEST_CHILD_ID,
        CHILD_NAME,
    )

    assert entity.native_value == 2
    assert entity.available is True
    assert entity.extra_state_attributes["devices"] == [
        {"name": "Unknown", "model": "Unknown", "id": ""},
        {"name": "Phone", "model": "Unknown", "id": "phone-1"},
    ]


def test_device_sensors_return_empty_state_when_device_time_data_is_missing() -> None:
    """Device sensors expose identity but no values when their time data is absent."""
    coordinator = _coordinator({"devices_time_data": {}})
    entities = _device_sensor_set(coordinator)

    for entity in entities.values():
        assert entity.available is True
        assert entity.extra_state_attributes == {
            "child_id": TEST_CHILD_ID,
            "child_name": CHILD_NAME,
            "device_id": TEST_DEVICE_ID,
            "device_name": DEVICE_NAME,
        }

    assert entities["remaining"].native_value is None
    assert entities["next_restriction"].native_value is None
    assert entities["daily_limit"].native_value is None
    assert entities["active_bonus"].native_value is None

    coordinator.last_update_success = False
    assert all(entity.available is False for entity in entities.values())


def test_device_sensors_use_time_data_defaults_for_derived_values() -> None:
    """Empty device time data produces deterministic zero/default attributes."""
    entities = _device_sensor_set(_coordinator({"devices_time_data": {TEST_DEVICE_ID: {}}}))

    assert entities["remaining"].native_value == 0
    assert entities["remaining"].extra_state_attributes["total_allowed_minutes"] == 0
    assert entities["remaining"].extra_state_attributes["used_minutes"] == 0
    assert entities["remaining"].extra_state_attributes["daily_limit_enabled"] is False
    assert entities["remaining"].extra_state_attributes["daily_limit_minutes"] == 0
    assert entities["remaining"].extra_state_attributes["percentage_used"] == 0

    assert entities["daily_limit"].native_value == 0
    assert entities["daily_limit"].extra_state_attributes["enabled"] is False

    assert entities["active_bonus"].native_value == 0
    assert entities["active_bonus"].extra_state_attributes["has_bonus"] is False

    assert entities["next_restriction"].native_value == "No restrictions"
    assert entities["next_restriction"].extra_state_attributes["bedtime_active"] is False
    assert entities["next_restriction"].extra_state_attributes["schooltime_active"] is False


def test_next_restriction_attributes_skip_invalid_timestamps() -> None:
    """Invalid restriction timestamps are omitted while valid ones are converted."""
    valid_end_ms = 1710050400000
    entity = NextRestrictionSensor(
        _coordinator(
            {
                "devices_time_data": {
                    TEST_DEVICE_ID: {
                        "bedtime_window": {
                            "start_ms": float("nan"),
                            "end_ms": valid_end_ms,
                        },
                        "schooltime_window": {
                            "start_ms": valid_end_ms,
                            "end_ms": float("nan"),
                        },
                    }
                }
            }
        ),
        TEST_CHILD_ID,
        CHILD_NAME,
        TEST_DEVICE_ID,
        DEVICE_NAME,
    )

    attributes = entity.extra_state_attributes

    assert "bedtime_start" not in attributes
    assert attributes["bedtime_end"] == datetime.fromtimestamp(
        valid_end_ms / 1000
    ).isoformat()
    assert attributes["schooltime_start"] == datetime.fromtimestamp(
        valid_end_ms / 1000
    ).isoformat()
    assert "schooltime_end" not in attributes


def test_battery_sensor_treats_zero_as_valid_and_omits_missing_metadata() -> None:
    """Battery level zero is available; optional source and update attrs stay absent."""
    entity = FamilyLinkBatteryLevelSensor(
        _coordinator({"location": {"battery_level": 0}}),
        TEST_CHILD_ID,
        CHILD_NAME,
    )

    assert entity.native_value == 0
    assert entity.available is True
    assert entity.icon == "mdi:battery-alert-variant-outline"
    assert entity.extra_state_attributes == {
        "child_id": TEST_CHILD_ID,
        "child_name": CHILD_NAME,
    }


def test_battery_sensor_exposes_source_and_last_update_when_present() -> None:
    """Battery attributes include source device and last update metadata when present."""
    entity = FamilyLinkBatteryLevelSensor(
        _coordinator(
            {
                "location": {
                    "battery_level": 84,
                    "source_device_name": DEVICE_NAME,
                    "timestamp_iso": "2026-06-23T12:00:00+00:00",
                }
            }
        ),
        TEST_CHILD_ID,
        CHILD_NAME,
    )

    assert entity.extra_state_attributes == {
        "child_id": TEST_CHILD_ID,
        "child_name": CHILD_NAME,
        "source_device": DEVICE_NAME,
        "last_update": "2026-06-23T12:00:00+00:00",
    }
