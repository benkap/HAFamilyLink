"""Remaining focused edge tests for Family Link sensor entities."""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from custom_components.familylink import sensor as sensor_module
from custom_components.familylink.sensor import (
    FamilyLinkAlwaysAllowedAppsSensor,
    FamilyLinkAppsWithLimitsSensor,
    FamilyLinkAppsWithoutLimitsSensor,
    FamilyLinkBatteryLevelSensor,
    FamilyLinkBlockedAppsSensor,
    FamilyLinkScheduleSensor,
    FamilyLinkScreenTimeFormattedSensor,
    FamilyLinkScreenTimeSensor,
    FamilyLinkTopAppSensor,
)

CHILD_ID = "child-1"
CHILD_NAME = "Alex"


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


def _schedule_sensor(coordinator: SimpleNamespace) -> FamilyLinkScheduleSensor:
    return FamilyLinkScheduleSensor(
        coordinator,
        CHILD_ID,
        CHILD_NAME,
        "Bedtime Schedule",
        "bedtime_schedule",
        "bedtime_enabled",
        "mdi:weather-night",
        "window",
    )


def _payload_size(attributes: dict) -> int:
    return len(json.dumps(attributes, ensure_ascii=False).encode("utf-8"))


@pytest.mark.parametrize("screen_time", [None, {}])
def test_screen_time_sensors_are_empty_for_none_or_empty_screen_time_payload(
    screen_time,
) -> None:
    """Total and formatted sensors stay empty when screen-time data has no values."""
    coordinator = _coordinator({"screen_time": screen_time})
    total = FamilyLinkScreenTimeSensor(coordinator, "total", CHILD_ID, CHILD_NAME)
    formatted = FamilyLinkScreenTimeFormattedSensor(coordinator, CHILD_ID, CHILD_NAME)

    for entity in (total, formatted):
        assert entity.native_value is None
        assert entity.available is (screen_time is not None)
        assert entity.extra_state_attributes == {}


def test_screen_time_sensors_are_unavailable_when_screen_time_key_is_missing() -> None:
    """Missing screen_time behaves the same as an unavailable data section."""
    coordinator = _coordinator()
    total = FamilyLinkScreenTimeSensor(coordinator, "total", CHILD_ID, CHILD_NAME)
    formatted = FamilyLinkScreenTimeFormattedSensor(coordinator, CHILD_ID, CHILD_NAME)

    for entity in (total, formatted):
        assert entity.native_value is None
        assert entity.available is False
        assert entity.extra_state_attributes == {}


def test_screen_time_app_breakdown_falls_back_to_package_and_marks_truncation() -> None:
    """Large app breakdowns keep the top package visible and flag truncation."""
    heavy_package = "com.example.heavy"
    app_breakdown = {
        heavy_package: 7200,
        **{
            f"com.example.app{index}": 3600 - index
            for index in range(450)
        },
    }
    apps = [
        {"packageName": heavy_package},
        *[
            {
                "packageName": f"com.example.app{index}",
                "title": f"App {index} " + "x" * 80,
            }
            for index in range(450)
        ],
    ]
    entity = FamilyLinkScreenTimeSensor(
        _coordinator(
            {
                "apps": apps,
                "screen_time": {
                    "total_seconds": sum(app_breakdown.values()),
                    "app_breakdown": app_breakdown,
                },
            }
        ),
        "total",
        CHILD_ID,
        CHILD_NAME,
    )

    attributes = entity.extra_state_attributes

    assert entity.native_value == round(sum(app_breakdown.values()) / 60, 1)
    assert attributes["app_count"] == len(app_breakdown)
    assert attributes["apps"][0]["name"] == heavy_package
    assert attributes["apps"][0]["package"] == heavy_package
    assert attributes["truncated"] is True
    assert len(attributes["apps"]) < len(app_breakdown)
    assert _payload_size(attributes) <= sensor_module.MAX_ATTR_SIZE


@pytest.mark.parametrize(
    ("sensor_cls", "apps", "expected_attributes"),
    [
        (
            FamilyLinkBlockedAppsSensor,
            [{"supervisionSetting": {"hidden": True}}],
            {
                "count": 1,
                "apps": [{"name": "Unknown", "package": ""}],
            },
        ),
        (
            FamilyLinkAppsWithLimitsSensor,
            [{"supervisionSetting": {"usageLimit": {}}}],
            {"count": 0, "apps": []},
        ),
        (
            FamilyLinkAppsWithLimitsSensor,
            [{"supervisionSetting": {"usageLimit": {"enabled": True}}}],
            {
                "count": 1,
                "apps": [
                    {
                        "name": "Unknown",
                        "package": "",
                        "limit_minutes": 0,
                        "enabled": True,
                    }
                ],
            },
        ),
        (
            FamilyLinkAlwaysAllowedAppsSensor,
            [{"supervisionSetting": {"alwaysAllowedAppInfo": {"enabled": True}}}],
            {
                "count": 1,
                "apps": [{"name": "Unknown", "package": ""}],
            },
        ),
        (
            FamilyLinkAppsWithoutLimitsSensor,
            [{}],
            {
                "count": 1,
                "apps": [{"name": "Unknown", "package": ""}],
            },
        ),
    ],
)
def test_app_list_sensors_use_default_names_packages_and_limit_attrs(
    sensor_cls, apps, expected_attributes
) -> None:
    """App list sensors expose readable defaults when app metadata is thin."""
    entity = sensor_cls(_coordinator({"apps": apps}), CHILD_ID, CHILD_NAME)
    expected_attributes = {
        "child_id": CHILD_ID,
        "child_name": CHILD_NAME,
        **expected_attributes,
    }

    assert entity.native_value == expected_attributes["count"]
    assert entity.available is True
    assert entity.extra_state_attributes == expected_attributes


def test_app_list_sensor_marks_large_attribute_payload_as_truncated() -> None:
    """Category sensors set truncated when their real attributes would be too large."""
    apps = [
        {
            "title": f"Blocked App {index} " + "x" * 90,
            "packageName": f"com.example.blocked{index}",
            "supervisionSetting": {"hidden": True},
        }
        for index in range(500)
    ]
    entity = FamilyLinkBlockedAppsSensor(
        _coordinator({"apps": apps}),
        CHILD_ID,
        CHILD_NAME,
    )

    attributes = entity.extra_state_attributes

    assert entity.native_value == len(apps)
    assert attributes["count"] == len(apps)
    assert attributes["truncated"] is True
    assert len(attributes["apps"]) < len(apps)
    assert _payload_size(attributes) <= sensor_module.MAX_ATTR_SIZE


def test_top_app_sensor_without_rank_data_is_unavailable_and_has_no_attributes() -> None:
    """A rank past the available breakdown stays hidden."""
    entity = FamilyLinkTopAppSensor(
        _coordinator({"screen_time": {"app_breakdown": {"com.example.only": 120}}}),
        2,
        CHILD_ID,
        CHILD_NAME,
    )

    assert entity.native_value is None
    assert entity.available is False
    assert entity.extra_state_attributes == {}


def test_top_app_sensor_falls_back_to_package_when_matching_app_has_no_title() -> None:
    """App metadata without a title still produces a stable top-app label."""
    package = "com.example.untitled"
    entity = FamilyLinkTopAppSensor(
        _coordinator(
            {
                "apps": [{"packageName": package}],
                "screen_time": {"app_breakdown": {package: 125}},
            }
        ),
        1,
        CHILD_ID,
        CHILD_NAME,
    )

    assert entity.native_value == 2.1
    assert entity.available is True
    assert entity.extra_state_attributes["app_name"] == package


def test_schedule_sensor_without_matching_child_has_unknown_state_and_no_today() -> None:
    """Schedule sensors remain unavailable when their child data disappears."""
    coordinator = SimpleNamespace(
        data={"children_data": [{"child_id": "other", "child_name": "Other"}]},
        last_update_success=True,
    )
    coordinator.async_add_listener = lambda update_callback, context=None: lambda: None
    entity = _schedule_sensor(coordinator)

    attributes = entity.extra_state_attributes

    assert entity.native_value == "unknown"
    assert entity.available is False
    assert attributes["enabled"] is None
    assert attributes["schedule"] == []
    assert attributes["monday"] == "off"
    assert "today" not in attributes
    assert "schedule_timezone" not in attributes


@pytest.mark.parametrize("child_overrides", [{}, {"location": None}, {"location": {}}])
def test_battery_sensor_without_location_or_battery_data_uses_unknown_icon(
    child_overrides,
) -> None:
    """Battery sensor hides state and attributes when location data is not useful."""
    entity = FamilyLinkBatteryLevelSensor(
        _coordinator(child_overrides),
        CHILD_ID,
        CHILD_NAME,
    )

    assert entity.native_value is None
    assert entity.available is False
    assert entity.icon == "mdi:battery-unknown"
    assert entity.extra_state_attributes == {}


@pytest.mark.parametrize(
    ("battery_level", "icon"),
    [
        (90, "mdi:battery"),
        (89, "mdi:battery-80"),
        (70, "mdi:battery-80"),
        (69, "mdi:battery-60"),
        (50, "mdi:battery-60"),
        (49, "mdi:battery-40"),
        (30, "mdi:battery-40"),
        (29, "mdi:battery-20"),
        (10, "mdi:battery-20"),
        (9, "mdi:battery-alert-variant-outline"),
    ],
)
def test_battery_sensor_icon_boundaries(battery_level, icon) -> None:
    """Battery icon thresholds include their lower boundary values."""
    entity = FamilyLinkBatteryLevelSensor(
        _coordinator({"location": {"battery_level": battery_level}}),
        CHILD_ID,
        CHILD_NAME,
    )

    assert entity.native_value == battery_level
    assert entity.available is True
    assert entity.icon == icon
