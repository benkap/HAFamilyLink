"""Focused edge tests for Family Link sensor helpers and direct entities."""
from __future__ import annotations

from datetime import datetime, timedelta
import json
from types import SimpleNamespace

import pytest

from custom_components.familylink import sensor as sensor_module
from custom_components.familylink.sensor import (
    FamilyLinkAppsWithoutLimitsSensor,
    FamilyLinkBlockedAppsSensor,
    FamilyLinkScheduleSensor,
    FamilyLinkScreenTimeSensor,
    FamilyLinkTopAppSensor,
    NextRestrictionSensor,
    _truncate_app_list,
)

CHILD_ID = "child-1"
CHILD_NAME = "Alex"
DEVICE_ID = "device-1"
DEVICE_NAME = "Pixel Tablet"
FIXED_NOW = datetime(2026, 6, 24, 12, 0, 0)


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


def _schedule_sensor(
    child_overrides: dict,
    *,
    schedule_key: str = "bedtime_schedule",
    enabled_key: str | None = "bedtime_enabled",
    schedule_type: str = "window",
) -> FamilyLinkScheduleSensor:
    return FamilyLinkScheduleSensor(
        _coordinator(child_overrides),
        CHILD_ID,
        CHILD_NAME,
        "Bedtime Schedule",
        schedule_key,
        enabled_key,
        "mdi:weather-night",
        schedule_type,
    )


def _payload_size(attributes: dict) -> int:
    return len(json.dumps(attributes, ensure_ascii=False).encode("utf-8"))


def _ms_after(**delta_kwargs: int) -> int:
    return int((FIXED_NOW + timedelta(**delta_kwargs)).timestamp() * 1000)


def test_truncate_app_list_keeps_final_attributes_under_byte_limit() -> None:
    apps = [
        {
            "name": f"App {index} " + "x" * 80,
            "package": f"com.example.app{index}",
        }
        for index in range(500)
    ]
    base_attrs = {"child_id": CHILD_ID, "child_name": CHILD_NAME, "count": len(apps)}

    truncated_apps, was_truncated = _truncate_app_list(apps, base_attrs)
    final_attrs = {**base_attrs, "apps": truncated_apps, "truncated": was_truncated}

    assert was_truncated is True
    assert len(truncated_apps) < len(apps)
    assert _payload_size(final_attrs) <= sensor_module.MAX_ATTR_SIZE


def test_truncate_app_list_marks_truncation_only_when_needed() -> None:
    apps = [{"name": "Maps", "package": "com.google.android.apps.maps"}]
    base_attrs = {"child_id": CHILD_ID, "child_name": CHILD_NAME, "count": len(apps)}

    returned_apps, was_truncated = _truncate_app_list(apps, base_attrs)

    assert returned_apps == apps
    assert was_truncated is False


@pytest.mark.parametrize("schedule_value", [None, {}, "not-a-list"])
def test_schedule_sensor_treats_malformed_schedule_payload_as_unknown(schedule_value) -> None:
    entity = _schedule_sensor({"bedtime_schedule": schedule_value})

    assert entity.native_value == "unknown"
    assert entity.available is True
    assert entity.extra_state_attributes["schedule"] == []
    assert entity.extra_state_attributes["monday"] == "off"


def test_schedule_sensor_uses_slot_fallback_when_enabled_key_is_missing() -> None:
    entity = _schedule_sensor(
        {
            "bedtime_schedule": [
                {
                    "day": 1,
                    "day_name": "Monday",
                    "enabled": True,
                    "start": "bad-start",
                    "end": [6, 0],
                },
                {
                    "day": 2,
                    "day_name": "Tuesday",
                    "enabled": False,
                    "start": [8, 0],
                    "end": [13, 30],
                },
            ],
            "schedule_today": 1,
            "schedule_timezone": "Asia/Jerusalem",
            "schedule_timezone_source": "device",
        },
    )

    attributes = entity.extra_state_attributes

    assert entity.native_value == "enabled"
    assert attributes["enabled"] is True
    assert attributes["enabled_days"] == ["Monday"]
    assert attributes["monday"] == "off"
    assert attributes["tuesday"] == "off"
    assert attributes["schedule_today"] == 1
    assert attributes["schedule_today_key"] == "monday"
    assert attributes["today"] == "off"
    assert attributes["schedule_timezone"] == "Asia/Jerusalem"
    assert attributes["schedule_timezone_source"] == "device"


def test_daily_limit_schedule_sensor_keeps_disabled_or_missing_slots_off() -> None:
    entity = _schedule_sensor(
        {
            "daily_limit_schedule": [
                {"day": 3, "day_name": "Wednesday", "enabled": False, "minutes": 90},
                {"day": 4, "day_name": "Thursday", "minutes": 45},
            ],
            "schedule_today": 3,
        },
        schedule_key="daily_limit_schedule",
        enabled_key=None,
        schedule_type="minutes",
    )

    attributes = entity.extra_state_attributes

    assert entity.native_value == "disabled"
    assert attributes["enabled"] is False
    assert attributes["enabled_days"] == []
    assert attributes["wednesday"] == "off"
    assert attributes["thursday"] == "off"
    assert attributes["today"] == "off"


@pytest.mark.parametrize(
    ("time_data", "expected"),
    [
        (
            {
                "bedtime_active": True,
                "bedtime_window": {"end_ms": _ms_after(hours=1, minutes=5)},
            },
            "Bedtime (ends in 1h05)",
        ),
        (
            {
                "schooltime_active": True,
                "schooltime_window": {"end_ms": _ms_after(minutes=30)},
            },
            "School time (ends in 30min)",
        ),
        (
            {"bedtime_window": {"start_ms": _ms_after(hours=2, minutes=10)}},
            "Bedtime in 2h10",
        ),
        (
            {"schooltime_window": {"start_ms": _ms_after(minutes=25)}},
            "School time in 25min",
        ),
        (
            {"daily_limit_enabled": True, "remaining_minutes": 20},
            "Daily limit 20min remaining",
        ),
    ],
)
def test_next_restriction_sensor_prioritizes_active_upcoming_and_daily_limit(
    monkeypatch, time_data, expected
) -> None:
    class FixedDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return FIXED_NOW.replace(tzinfo=tz)

    monkeypatch.setattr(sensor_module, "datetime", FixedDateTime)
    entity = NextRestrictionSensor(
        _coordinator({"devices_time_data": {DEVICE_ID: time_data}}),
        CHILD_ID,
        CHILD_NAME,
        DEVICE_ID,
        DEVICE_NAME,
    )

    assert entity.native_value == expected


def test_app_category_sensor_handles_missing_apps_key() -> None:
    entity = FamilyLinkBlockedAppsSensor(_coordinator(), CHILD_ID, CHILD_NAME)

    assert entity.native_value == 0
    assert entity.available is False
    assert entity.extra_state_attributes == {}


def test_apps_without_limits_sensor_handles_apps_missing_optional_fields() -> None:
    entity = FamilyLinkAppsWithoutLimitsSensor(
        _coordinator({"apps": [{}, {"title": "Hidden", "supervisionSetting": {"hidden": True}}]}),
        CHILD_ID,
        CHILD_NAME,
    )

    assert entity.native_value == 1
    assert entity.available is True
    assert entity.extra_state_attributes["apps"] == [{"name": "Unknown", "package": ""}]


def test_screen_time_sensor_handles_missing_app_metadata() -> None:
    entity = FamilyLinkScreenTimeSensor(
        _coordinator(
            {
                "screen_time": {
                    "total_seconds": 90,
                    "formatted": "00:01:30",
                    "app_breakdown": {"com.example.unknown": 90},
                },
            }
        ),
        "total",
        CHILD_ID,
        CHILD_NAME,
    )

    attributes = entity.extra_state_attributes

    assert entity.native_value == 1.5
    assert entity.available is True
    assert attributes["app_count"] == 1
    assert attributes["apps"] == [
        {
            "name": "com.example.unknown",
            "package": "com.example.unknown",
            "time": "00:01:30",
            "minutes": 1.5,
        }
    ]


def test_top_app_sensor_falls_back_to_package_name_when_app_details_are_missing() -> None:
    entity = FamilyLinkTopAppSensor(
        _coordinator({"screen_time": {"app_breakdown": {"com.example.unknown": 120}}}),
        1,
        CHILD_ID,
        CHILD_NAME,
    )

    assert entity.native_value == 2
    assert entity.available is True
    assert entity.extra_state_attributes["app_name"] == "com.example.unknown"
