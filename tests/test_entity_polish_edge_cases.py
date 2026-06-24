"""Focused polish edge tests for Family Link sensor and switch entities."""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from custom_components.familylink import sensor as sensor_module
from custom_components.familylink.sensor import (
    FamilyLinkAlwaysAllowedAppsSensor,
    FamilyLinkAppsWithLimitsSensor,
    FamilyLinkAppsWithoutLimitsSensor,
    FamilyLinkChildInfoSensor,
    FamilyLinkTopAppSensor,
)
from custom_components.familylink.switch import FamilyLinkDeviceSwitch

CHILD_ID = "child-1"
CHILD_NAME = "Alex"
DEVICE_ID = "device-1"
DEVICE_NAME = "Pixel Tablet"


def _coordinator(child_overrides: dict | None = None) -> SimpleNamespace:
    child_data = {
        "child_id": CHILD_ID,
        "child_name": CHILD_NAME,
        **(child_overrides or {}),
    }
    coordinator = SimpleNamespace(
        data={"children_data": [child_data]},
        last_update_success=True,
    )
    coordinator.async_add_listener = lambda update_callback, context=None: lambda: None
    return coordinator


def _device(**overrides) -> dict:
    return {
        "id": DEVICE_ID,
        "name": DEVICE_NAME,
        "model": "Pixel Tablet",
        **overrides,
    }


def _payload_size(attributes: dict) -> int:
    return len(json.dumps(attributes, ensure_ascii=False).encode("utf-8"))


def _large_app(index: int, supervision: dict) -> dict:
    return {
        "title": f"App {index} " + "x" * 90,
        "packageName": f"com.example.app{index}",
        "supervisionSetting": supervision,
    }


@pytest.mark.parametrize(
    ("sensor_cls", "supervision"),
    [
        (
            FamilyLinkAppsWithLimitsSensor,
            {"usageLimit": {"dailyUsageLimitMins": 45, "enabled": True}},
        ),
        (FamilyLinkAppsWithoutLimitsSensor, {}),
        (FamilyLinkAlwaysAllowedAppsSensor, {"alwaysAllowedAppInfo": {"enabled": True}}),
    ],
    ids=["apps-with-limits", "apps-without-limits", "always-allowed"],
)
def test_app_list_category_sensors_mark_large_payloads_truncated(
    sensor_cls, supervision
) -> None:
    """Requested app-list sensors flag truncation without depending on exact cutoffs."""
    apps = [_large_app(index, supervision) for index in range(500)]
    entity = sensor_cls(_coordinator({"apps": apps}), CHILD_ID, CHILD_NAME)

    attributes = entity.extra_state_attributes

    assert entity.native_value == len(apps)
    assert entity.available is True
    assert attributes["count"] == len(apps)
    assert attributes["truncated"] is True
    assert len(attributes["apps"]) < len(apps)
    assert attributes["apps"][0]["package"] == "com.example.app0"
    assert _payload_size(attributes) <= sensor_module.MAX_ATTR_SIZE


@pytest.mark.parametrize(
    "child_overrides",
    [
        {},
        {"screen_time": None},
        {"screen_time": {}},
        {"screen_time": {"app_breakdown": {}}},
        {"screen_time": {"total_seconds": 120}},
    ],
    ids=[
        "missing-screen-time",
        "none-screen-time",
        "empty-screen-time",
        "empty-app-breakdown",
        "missing-app-breakdown",
    ],
)
def test_top_app_sensor_hides_empty_screen_time_payloads(child_overrides) -> None:
    """Top-app sensors stay empty when screen-time data has no ranked app payload."""
    entity = FamilyLinkTopAppSensor(
        _coordinator(child_overrides),
        1,
        CHILD_ID,
        CHILD_NAME,
    )

    assert entity.native_value is None
    assert entity.available is False
    assert entity.extra_state_attributes == {}


@pytest.mark.parametrize(
    ("child_payload", "expected_available"),
    [(None, False), ({}, True)],
    ids=["none", "empty-dict"],
)
def test_child_info_sensor_handles_empty_child_payload(
    child_payload, expected_available
) -> None:
    """Child info exposes no partial attributes when the child payload is empty."""
    entity = FamilyLinkChildInfoSensor(
        _coordinator({"child": child_payload}),
        CHILD_ID,
        CHILD_NAME,
    )

    assert entity.native_value is None
    assert entity.available is expected_available
    assert entity.extra_state_attributes == {}


def test_device_switch_is_off_when_current_live_device_is_locked() -> None:
    """The live device payload wins over the setup payload for lock state."""
    entity = FamilyLinkDeviceSwitch(
        _coordinator(
            {
                "devices": [_device(locked=True)],
                "devices_time_data": {
                    DEVICE_ID: {
                        "bonus_minutes": 30,
                        "daily_limit_remaining": 60,
                    }
                },
            }
        ),
        _device(locked=False),
        CHILD_ID,
        CHILD_NAME,
    )

    assert entity.is_on is False


def test_device_switch_uses_setup_device_when_live_device_row_is_missing() -> None:
    """A missing live row is not the same thing as no current device at all."""
    entity = FamilyLinkDeviceSwitch(
        _coordinator(
            {
                "devices": [],
                "devices_time_data": {DEVICE_ID: {"daily_limit_remaining": 60}},
            }
        ),
        _device(locked=True),
        CHILD_ID,
        CHILD_NAME,
    )

    assert entity.is_on is False


def test_device_switch_returns_on_only_when_current_device_is_none() -> None:
    """The explicit no-device branch returns on before consulting restrictions."""

    class MissingCurrentDeviceSwitch(FamilyLinkDeviceSwitch):
        def _get_current_device(self) -> dict | None:
            return None

    entity = MissingCurrentDeviceSwitch(
        _coordinator(
            {
                "devices": [_device(locked=True)],
                "devices_time_data": {
                    DEVICE_ID: {
                        "bedtime_active": True,
                        "bonus_minutes": 0,
                        "daily_limit_remaining": 0,
                    }
                },
            }
        ),
        _device(locked=True),
        CHILD_ID,
        CHILD_NAME,
    )

    assert entity.is_on is True
