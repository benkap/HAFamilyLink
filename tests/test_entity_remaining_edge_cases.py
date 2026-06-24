"""Focused remaining edge tests for Family Link entities and schedule helpers."""
from __future__ import annotations

import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from custom_components.familylink import schedules
from custom_components.familylink.binary_sensor import (
    BedtimeActiveBinarySensor,
    DailyLimitReachedBinarySensor,
    SchoolTimeActiveBinarySensor,
)
from custom_components.familylink.const import DEVICE_LOCK_ACTION, DOMAIN, LOGGER_NAME
from custom_components.familylink.sensor import (
    FamilyLinkAlwaysAllowedAppsSensor,
    FamilyLinkAppCountSensor,
    FamilyLinkAppsWithLimitsSensor,
    FamilyLinkAppsWithoutLimitsSensor,
    FamilyLinkBlockedAppsSensor,
    FamilyLinkChildInfoSensor,
    FamilyLinkDeviceCountSensor,
    FamilyLinkScheduleSensor,
    FamilyLinkScreenTimeSensor,
    FamilyLinkTopAppSensor,
    NextRestrictionSensor,
)
from custom_components.familylink.switch import (
    FamilyLinkBedtimeSwitch,
    FamilyLinkDailyLimitSwitch,
    FamilyLinkDeviceSwitch,
    FamilyLinkSchoolTimeSwitch,
)

from conftest import TEST_CHILD_ID, TEST_DEVICE_ID

CHILD_NAME = "Alex"
DEVICE_NAME = "Pixel Tablet"


def _coordinator(
    data: dict | None,
    *,
    last_update_success: bool = True,
    client: SimpleNamespace | None = None,
) -> SimpleNamespace:
    coordinator = SimpleNamespace(
        data=data,
        last_update_success=last_update_success,
        client=client,
        async_control_device=AsyncMock(return_value=True),
    )
    coordinator.async_add_listener = lambda update_callback, context=None: lambda: None
    coordinator.get_pending_time_limit_state = lambda child_id, limit_type: None
    coordinator.set_pending_time_limit_state = lambda child_id, limit_type, enabled: None
    return coordinator


def _children_data(*children: dict) -> dict:
    return {"children_data": list(children)}


def _child(**overrides) -> dict:
    return {
        "child_id": TEST_CHILD_ID,
        "child_name": CHILD_NAME,
        **overrides,
    }


def _device() -> dict:
    return {"id": TEST_DEVICE_ID, "name": DEVICE_NAME, "model": "Pixel Tablet"}


def _bedtime_schedule_sensor(coordinator: SimpleNamespace) -> FamilyLinkScheduleSensor:
    return FamilyLinkScheduleSensor(
        coordinator,
        TEST_CHILD_ID,
        CHILD_NAME,
        "Bedtime Schedule",
        "bedtime_schedule",
        "bedtime_enabled",
        "mdi:weather-night",
        "window",
    )


@pytest.mark.parametrize(
    "sensor_cls",
    [
        BedtimeActiveBinarySensor,
        SchoolTimeActiveBinarySensor,
        DailyLimitReachedBinarySensor,
    ],
)
@pytest.mark.parametrize(
    "coordinator_data",
    [
        None,
        {},
        _children_data(),
        _children_data({"child_id": "other", "devices_time_data": {}}),
    ],
    ids=["none", "empty", "empty-children", "missing-child"],
)
def test_binary_sensors_are_unavailable_without_matching_device_time_data(
    sensor_cls,
    coordinator_data,
) -> None:
    """Device-time binary sensors go quiet when coordinator data cannot find the device."""
    entity = sensor_cls(
        _coordinator(coordinator_data),
        TEST_DEVICE_ID,
        DEVICE_NAME,
        _device(),
        TEST_CHILD_ID,
        CHILD_NAME,
    )

    assert entity.available is False
    assert entity.is_on is False
    assert entity.extra_state_attributes == {}


def test_schooltime_binary_sensor_ignores_invalid_window_timestamps() -> None:
    """Invalid schooltime timestamps are not exposed as attributes."""
    entity = SchoolTimeActiveBinarySensor(
        _coordinator(
            _children_data(
                _child(
                    devices_time_data={
                        TEST_DEVICE_ID: {
                            "schooltime_active": True,
                            "schooltime_window": {
                                "start_ms": float("nan"),
                                "end_ms": float("nan"),
                            },
                        }
                    }
                )
            )
        ),
        TEST_DEVICE_ID,
        DEVICE_NAME,
        _device(),
        TEST_CHILD_ID,
        CHILD_NAME,
    )

    assert entity.is_on is True
    assert entity.extra_state_attributes == {
        "device_id": TEST_DEVICE_ID,
        "device_name": DEVICE_NAME,
        "child_id": TEST_CHILD_ID,
        "child_name": CHILD_NAME,
    }


def test_daily_limit_reached_is_false_when_remaining_key_is_missing() -> None:
    """Missing daily_limit_remaining means the daily limit is not considered reached."""
    entity = DailyLimitReachedBinarySensor(
        _coordinator(
            _children_data(
                _child(
                    devices_time_data={
                        TEST_DEVICE_ID: {
                            "remaining_minutes": 12,
                        }
                    }
                )
            )
        ),
        TEST_DEVICE_ID,
        DEVICE_NAME,
        _device(),
        TEST_CHILD_ID,
        CHILD_NAME,
    )

    assert entity.available is True
    assert entity.is_on is False
    assert entity.icon == "mdi:timer-check"
    assert entity.extra_state_attributes["remaining_minutes"] == 12


@pytest.mark.parametrize(
    "coordinator_data",
    [None, {}, _children_data({"child_id": "other", "child_name": "Other"})],
    ids=["none", "empty", "missing-child"],
)
def test_child_data_mixin_entities_handle_missing_coordinator_data(
    coordinator_data,
) -> None:
    """ChildDataMixin users stay unavailable when child payload lookup fails."""
    coordinator = _coordinator(coordinator_data)
    screen_time = FamilyLinkScreenTimeSensor(
        coordinator,
        "total",
        TEST_CHILD_ID,
        CHILD_NAME,
    )
    schedule = _bedtime_schedule_sensor(coordinator)

    assert screen_time.native_value is None
    assert screen_time.available is False
    assert screen_time.extra_state_attributes == {}

    assert schedule.native_value == "unknown"
    assert schedule.available is False
    assert schedule.extra_state_attributes["schedule"] == []
    assert schedule.extra_state_attributes["monday"] == "off"
    assert "schedule_timezone" not in schedule.extra_state_attributes


def test_next_restriction_sensor_ignores_invalid_time_window_timestamps() -> None:
    """Invalid bedtime and schooltime timestamp attributes are skipped."""
    entity = NextRestrictionSensor(
        _coordinator(
            _children_data(
                _child(
                    devices_time_data={
                        TEST_DEVICE_ID: {
                            "bedtime_window": {
                                "start_ms": float("nan"),
                                "end_ms": float("nan"),
                            },
                            "schooltime_window": {
                                "start_ms": float("nan"),
                                "end_ms": float("nan"),
                            },
                        }
                    }
                )
            )
        ),
        TEST_CHILD_ID,
        CHILD_NAME,
        TEST_DEVICE_ID,
        DEVICE_NAME,
    )

    attributes = entity.extra_state_attributes

    assert "bedtime_start" not in attributes
    assert "bedtime_end" not in attributes
    assert "schooltime_start" not in attributes
    assert "schooltime_end" not in attributes


@pytest.mark.parametrize(
    ("sensor_cls", "expected_value"),
    [
        (FamilyLinkAppCountSensor, None),
        (FamilyLinkBlockedAppsSensor, 0),
        (FamilyLinkAppsWithLimitsSensor, 0),
        (FamilyLinkAppsWithoutLimitsSensor, 0),
        (FamilyLinkAlwaysAllowedAppsSensor, 0),
    ],
)
def test_app_list_sensors_are_unavailable_and_empty_when_apps_are_missing(
    sensor_cls,
    expected_value,
) -> None:
    """App-count/list sensors expose empty values when the apps payload is absent."""
    entity = sensor_cls(_coordinator(_children_data(_child())), TEST_CHILD_ID, CHILD_NAME)

    assert entity.native_value == expected_value
    assert entity.available is False
    assert entity.extra_state_attributes == {}


def test_top_app_device_count_and_child_info_missing_payloads_are_empty() -> None:
    """Summary sensors handle absent screen-time, device, and child payloads."""
    coordinator = _coordinator(_children_data(_child()))
    top_app = FamilyLinkTopAppSensor(coordinator, 1, TEST_CHILD_ID, CHILD_NAME)
    device_count = FamilyLinkDeviceCountSensor(coordinator, TEST_CHILD_ID, CHILD_NAME)
    child_info = FamilyLinkChildInfoSensor(coordinator, TEST_CHILD_ID, CHILD_NAME)

    assert top_app.native_value is None
    assert top_app.available is False
    assert top_app.extra_state_attributes == {}

    assert device_count.native_value == 0
    assert device_count.available is False
    assert device_count.extra_state_attributes == {}

    assert child_info.native_value is None
    assert child_info.available is False
    assert child_info.extra_state_attributes == {}


def test_device_switch_defaults_on_when_live_device_payload_is_missing() -> None:
    """A missing live device entry falls back to the setup payload and stays usable."""
    entity = FamilyLinkDeviceSwitch(
        _coordinator(
            _children_data(
                _child(
                    devices=[],
                    devices_time_data={TEST_DEVICE_ID: {"remaining_minutes": 0}},
                )
            )
        ),
        _device(),
        TEST_CHILD_ID,
        CHILD_NAME,
    )

    assert entity.is_on is True
    assert entity.icon == "mdi:cellphone"
    assert entity.extra_state_attributes["restriction_reason"] == "none"


async def test_device_switch_failed_lock_logs_without_crashing(caplog) -> None:
    """A failed lock call is logged and contained."""
    client = SimpleNamespace(async_cancel_time_bonus=AsyncMock(return_value=True))
    coordinator = _coordinator(
        _children_data(
            _child(
                devices=[_device()],
                devices_time_data={TEST_DEVICE_ID: {"bonus_override_id": None}},
            )
        ),
        client=client,
    )
    coordinator.async_control_device = AsyncMock(return_value=False)
    entity = FamilyLinkDeviceSwitch(
        coordinator,
        _device(),
        TEST_CHILD_ID,
        CHILD_NAME,
    )

    with caplog.at_level(logging.ERROR, logger=LOGGER_NAME):
        await entity.async_turn_off()

    coordinator.async_control_device.assert_awaited_once_with(
        TEST_DEVICE_ID,
        DEVICE_LOCK_ACTION,
        TEST_CHILD_ID,
    )
    client.async_cancel_time_bonus.assert_not_awaited()
    assert f"Failed to lock device {TEST_DEVICE_ID}" in caplog.text


@pytest.mark.parametrize(
    "switch_cls",
    [
        FamilyLinkBedtimeSwitch,
        FamilyLinkSchoolTimeSwitch,
        FamilyLinkDailyLimitSwitch,
    ],
)
def test_account_switches_use_child_device_info_and_update_availability(
    switch_cls,
) -> None:
    """Account-level switches share the child device identity and coordinator availability."""
    coordinator = _coordinator(_children_data(_child()))
    entity = switch_cls(coordinator, TEST_CHILD_ID, CHILD_NAME)

    assert entity.available is True
    assert entity.device_info == {
        "identifiers": {(DOMAIN, TEST_CHILD_ID)},
        "name": f"{CHILD_NAME} (Family Link)",
        "manufacturer": "Google",
        "model": "Family Link Account",
    }

    coordinator.last_update_success = False

    assert entity.available is False


@pytest.mark.parametrize("value", ["aa:30", "10:mm"])
def test_parse_time_string_rejects_non_numeric_parts(value) -> None:
    """Non-numeric HH:MM parts hit the parser's integer conversion failure path."""
    with pytest.raises(ValueError, match="Expected HH:MM"):
        schedules.parse_time_string(value)


@pytest.mark.parametrize("items", [None, {}, "CAEQAQ", ("CAEQAQ",)])
def test_parse_window_schedule_items_rejects_non_list_input(items) -> None:
    """Only list payloads are parsed as window schedule rows."""
    assert schedules.parse_window_schedule_items(items, "CAEQ") == []


def test_describe_effective_window_skips_malformed_weekly_slots() -> None:
    """Malformed weekly rows are ignored before matching a valid slot."""
    result = schedules.describe_effective_window(
        "22:00",
        "07:00",
        [
            "not-a-slot",
            {"day": 1, "enabled": True, "start": [21, "00"], "end": [6, 30]},
            {"day": 1, "enabled": True, "start": [25, 0], "end": [7, 0]},
            {"day": 1, "enabled": True, "start": [22, 0], "end": [7, 0]},
        ],
        1,
    )

    assert result["source"] == "weekly"
    assert result["weekly_label"] == "22:00-07:00"
    assert result["differs_from_weekly"] is False
