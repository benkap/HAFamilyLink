"""Helpers for Family Link entity setup."""
from __future__ import annotations

import logging
from collections.abc import Callable, Iterable
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import LOGGER_NAME
from .coordinator import FamilyLinkDataUpdateCoordinator

_LOGGER = logging.getLogger(LOGGER_NAME)

DeviceEntityFactory = Callable[
	[FamilyLinkDataUpdateCoordinator, dict[str, Any], str, str],
	Iterable[Any],
]


def iter_child_devices(
	coordinator: FamilyLinkDataUpdateCoordinator,
) -> Iterable[tuple[str, str, dict[str, Any]]]:
	"""Yield child/device pairs from the latest coordinator payload."""
	if not coordinator.data or "children_data" not in coordinator.data:
		return

	for child_data in coordinator.data.get("children_data", []):
		child_id = child_data.get("child_id")
		child_name = child_data.get("child_name", "Unknown")
		if not child_id:
			continue

		for device in child_data.get("devices", []):
			if not device.get("id"):
				_LOGGER.debug("Skipping Family Link device without id for child %s", child_name)
				continue
			yield child_id, child_name, device


def async_setup_dynamic_device_entities(
	entry: ConfigEntry,
	coordinator: FamilyLinkDataUpdateCoordinator,
	async_add_entities: AddEntitiesCallback,
	create_entities: DeviceEntityFactory,
	platform_name: str,
) -> None:
	"""Add per-device entities now and whenever new devices appear later."""
	known_device_keys: set[tuple[str, str]] = set()

	def add_missing_device_entities() -> None:
		new_entities: list[Any] = []

		for child_id, child_name, device in iter_child_devices(coordinator):
			device_id = device["id"]
			device_key = (child_id, device_id)
			if device_key in known_device_keys:
				continue

			device_entities = list(create_entities(coordinator, device, child_id, child_name))
			known_device_keys.add(device_key)
			new_entities.extend(device_entities)

		if new_entities:
			_LOGGER.debug(
				"Adding %s new Family Link %s device entit%s",
				len(new_entities),
				platform_name,
				"y" if len(new_entities) == 1 else "ies",
			)
			async_add_entities(new_entities)

	add_missing_device_entities()
	entry.async_on_unload(coordinator.async_add_listener(add_missing_device_entities))
