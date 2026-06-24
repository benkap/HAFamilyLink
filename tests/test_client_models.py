"""Tests for Family Link client data models."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from custom_components.familylink.client.models import Device, DeviceStatus


@pytest.mark.parametrize(
	("locked", "status", "expected_status"),
	[
		(True, "unlocked", DeviceStatus.LOCKED),
		(False, "locked", DeviceStatus.UNLOCKED),
	],
	ids=["locked-wins", "unlocked-wins"],
)
def test_device_from_dict_locked_field_takes_precedence(
	locked: bool,
	status: str,
	expected_status: DeviceStatus,
) -> None:
	"""Explicit locked state wins over a conflicting status string."""
	device = Device.from_dict(
		{
			"id": "device-1",
			"name": "Pixel Tablet",
			"locked": locked,
			"status": status,
		}
	)

	assert device.status is expected_status


@pytest.mark.parametrize(
	("status", "expected_status"),
	[
		("locked", DeviceStatus.LOCKED),
		("unlocked", DeviceStatus.UNLOCKED),
		("offline", DeviceStatus.OFFLINE),
		("unknown", DeviceStatus.UNKNOWN),
		("charging", DeviceStatus.UNKNOWN),
		("LOCKED", DeviceStatus.UNKNOWN),
	],
	ids=[
		"locked",
		"unlocked",
		"offline",
		"unknown",
		"unexpected-value",
		"case-sensitive",
	],
)
def test_device_from_dict_parses_status_strings(
	status: str,
	expected_status: DeviceStatus,
) -> None:
	"""Known status values parse to enum members; unknown strings stay safe."""
	device = Device.from_dict({"id": "device-1", "status": status})

	assert device.status is expected_status


def test_device_from_dict_uses_default_name_when_missing() -> None:
	"""Missing names fall back to a stable device label."""
	device = Device.from_dict({"id": "device-99"})

	assert device.name == "Device device-99"
	assert device.status is DeviceStatus.UNKNOWN


def test_device_from_dict_preserves_optional_fields() -> None:
	"""Optional payload fields are copied into the model."""
	last_seen = datetime(2026, 6, 24, 18, 30, tzinfo=timezone.utc)
	location = {"latitude": 32.0853, "longitude": 34.7818}

	device = Device.from_dict(
		{
			"id": "device-1",
			"name": "Pixel Tablet",
			"status": "offline",
			"type": "tablet",
			"last_seen": last_seen,
			"battery_level": 73,
			"location": location,
		}
	)

	assert device.device_type == "tablet"
	assert device.last_seen == last_seen
	assert device.battery_level == 73
	assert device.location == location


@pytest.mark.parametrize(
	("status", "expected_locked"),
	[
		(DeviceStatus.LOCKED, True),
		(DeviceStatus.UNLOCKED, False),
		(DeviceStatus.OFFLINE, False),
		(DeviceStatus.UNKNOWN, False),
	],
	ids=["locked", "unlocked", "offline", "unknown"],
)
def test_device_to_dict_serializes_status_and_locked_flag(
	status: DeviceStatus,
	expected_locked: bool,
) -> None:
	"""Dictionary output exposes status text and a lock boolean."""
	last_seen = datetime(2026, 6, 24, 18, 30, 15, tzinfo=timezone.utc)
	location = {"latitude": 32.0853, "longitude": 34.7818}

	result = Device(
		id="device-1",
		name="Pixel Tablet",
		status=status,
		device_type="tablet",
		last_seen=last_seen,
		battery_level=73,
		location=location,
	).to_dict()

	assert result == {
		"id": "device-1",
		"name": "Pixel Tablet",
		"status": status.value,
		"locked": expected_locked,
		"device_type": "tablet",
		"last_seen": "2026-06-24T18:30:15+00:00",
		"battery_level": 73,
		"location": location,
	}


def test_device_to_dict_serializes_missing_optional_fields_as_none() -> None:
	"""Optional fields remain present and null when they were not provided."""
	result = Device(
		id="device-1",
		name="Pixel Tablet",
		status=DeviceStatus.UNKNOWN,
	).to_dict()

	assert result == {
		"id": "device-1",
		"name": "Pixel Tablet",
		"status": "unknown",
		"locked": False,
		"device_type": None,
		"last_seen": None,
		"battery_level": None,
		"location": None,
	}


def test_device_from_dict_requires_id() -> None:
	"""Missing IDs raise immediately, matching the model contract today."""
	with pytest.raises(KeyError):
		Device.from_dict({"name": "Pixel Tablet"})
