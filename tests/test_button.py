"""Tests for Family Link button entities."""
from __future__ import annotations

import pytest

from custom_components.familylink import button
from custom_components.familylink.const import DOMAIN

from conftest import TEST_CHILD_ID, TEST_DEVICE_ID


async def _button_entities(hass, mock_config_entry, harness_coordinator):
	if hass.config_entries.async_get_entry(mock_config_entry.entry_id) is None:
		mock_config_entry.add_to_hass(hass)
	hass.data.setdefault(DOMAIN, {})[mock_config_entry.entry_id] = harness_coordinator
	entities = []

	def async_add_entities(new_entities, update_before_add=False):
		entities.extend(new_entities)

	await button.async_setup_entry(hass, mock_config_entry, async_add_entities)
	return entities


async def _button_by_unique_id(
	hass, mock_config_entry, harness_coordinator, unique_id
):
	entities = await _button_entities(hass, mock_config_entry, harness_coordinator)
	return next(entity for entity in entities if entity.unique_id == unique_id)


def _device_time_data(harness_coordinator):
	return harness_coordinator.data["children_data"][0]["devices_time_data"][
		TEST_DEVICE_ID
	]


async def test_setup_creates_expected_device_buttons(
	hass, mock_config_entry, harness_coordinator
):
	"""Button setup creates bonus, cancel, and ring entities for each device."""
	entities = await _button_entities(hass, mock_config_entry, harness_coordinator)

	expected_icons = {
		f"{DOMAIN}_{TEST_CHILD_ID}_{TEST_DEVICE_ID}_bonus_15min": "mdi:clock-plus-outline",
		f"{DOMAIN}_{TEST_CHILD_ID}_{TEST_DEVICE_ID}_bonus_30min": "mdi:clock-plus-outline",
		f"{DOMAIN}_{TEST_CHILD_ID}_{TEST_DEVICE_ID}_bonus_60min": "mdi:clock-plus-outline",
		f"{DOMAIN}_{TEST_CHILD_ID}_{TEST_DEVICE_ID}_reset_bonus": "mdi:clock-remove-outline",
		f"{DOMAIN}_{TEST_CHILD_ID}_{TEST_DEVICE_ID}_ring": "mdi:bell-ring",
	}

	assert [entity.unique_id for entity in entities] == list(expected_icons)
	for entity in entities:
		assert entity.icon == expected_icons[entity.unique_id]
		assert entity.available is True
		assert (DOMAIN, f"{TEST_CHILD_ID}_{TEST_DEVICE_ID}") in entity.device_info[
			"identifiers"
		]


@pytest.mark.parametrize(
	"coordinator_data",
	[None, {}, {"children_data": []}],
	ids=["none", "empty", "empty-children"],
)
async def test_setup_skips_buttons_without_children_data(
	hass, mock_config_entry, harness_coordinator, coordinator_data
):
	"""Button setup creates no entities when coordinator child data is absent."""
	harness_coordinator.data = coordinator_data

	entities = await _button_entities(hass, mock_config_entry, harness_coordinator)

	assert entities == []


async def test_buttons_unavailable_when_last_update_failed(
	hass, mock_config_entry, harness_coordinator
):
	"""All button entities report unavailable after a failed coordinator update."""
	entities = await _button_entities(hass, mock_config_entry, harness_coordinator)
	harness_coordinator.last_update_success = False

	assert entities
	assert all(entity.available is False for entity in entities)


@pytest.mark.parametrize(
	("success", "refreshes"),
	[(True, True), (False, False)],
	ids=["success", "failure"],
)
async def test_time_bonus_press_refreshes_only_after_success(
	hass, mock_config_entry, harness_coordinator, success, refreshes
):
	"""Time bonus buttons call the client and refresh only after success."""
	bonus = await _button_by_unique_id(
		hass,
		mock_config_entry,
		harness_coordinator,
		f"{DOMAIN}_{TEST_CHILD_ID}_{TEST_DEVICE_ID}_bonus_30min",
	)
	harness_coordinator.client.async_add_time_bonus.return_value = success

	await bonus.async_press()

	harness_coordinator.client.async_add_time_bonus.assert_awaited_once_with(
		bonus_minutes=30,
		device_id=TEST_DEVICE_ID,
		account_id=TEST_CHILD_ID,
	)
	if refreshes:
		harness_coordinator.async_request_refresh.assert_awaited_once()
	else:
		harness_coordinator.async_request_refresh.assert_not_awaited()


async def test_time_bonus_press_noops_without_client(
	hass, mock_config_entry, harness_coordinator
):
	"""Time bonus buttons do nothing when the coordinator has no client."""
	bonus = await _button_by_unique_id(
		hass,
		mock_config_entry,
		harness_coordinator,
		f"{DOMAIN}_{TEST_CHILD_ID}_{TEST_DEVICE_ID}_bonus_15min",
	)
	client = harness_coordinator.client
	harness_coordinator.client = None

	await bonus.async_press()

	client.async_add_time_bonus.assert_not_awaited()
	harness_coordinator.async_request_refresh.assert_not_awaited()


@pytest.mark.parametrize(
	(
		"override_id",
		"client_present",
		"client_success",
		"expected_available",
		"expected_call",
		"expected_refresh",
	),
	[
		(None, True, True, False, False, False),
		("bonus-2", True, True, True, True, True),
		("bonus-2", True, False, True, True, False),
		("bonus-2", False, True, True, False, False),
	],
	ids=["no-bonus", "success", "failure", "missing-client"],
)
async def test_cancel_bonus_press_availability_and_refresh(
	hass,
	mock_config_entry,
	harness_coordinator,
	override_id,
	client_present,
	client_success,
	expected_available,
	expected_call,
	expected_refresh,
):
	"""Cancel bonus buttons require an override and refresh only after success."""
	_device_time_data(harness_coordinator)["bonus_override_id"] = override_id
	cancel = await _button_by_unique_id(
		hass,
		mock_config_entry,
		harness_coordinator,
		f"{DOMAIN}_{TEST_CHILD_ID}_{TEST_DEVICE_ID}_reset_bonus",
	)
	client = harness_coordinator.client
	client.async_cancel_time_bonus.return_value = client_success
	if not client_present:
		harness_coordinator.client = None

	assert cancel.available is expected_available
	await cancel.async_press()

	if expected_call:
		client.async_cancel_time_bonus.assert_awaited_once_with(
			override_id=override_id,
			account_id=TEST_CHILD_ID,
		)
	else:
		client.async_cancel_time_bonus.assert_not_awaited()

	if expected_refresh:
		harness_coordinator.async_request_refresh.assert_awaited_once()
	else:
		harness_coordinator.async_request_refresh.assert_not_awaited()


@pytest.mark.parametrize(
	("client_present", "client_success", "expected_call"),
	[
		(True, True, True),
		(True, False, True),
		(False, True, False),
	],
	ids=["success", "failure", "missing-client"],
)
async def test_ring_button_press_behavior(
	hass,
	mock_config_entry,
	harness_coordinator,
	client_present,
	client_success,
	expected_call,
):
	"""Ring buttons dispatch to the client and never request a data refresh."""
	ring = await _button_by_unique_id(
		hass,
		mock_config_entry,
		harness_coordinator,
		f"{DOMAIN}_{TEST_CHILD_ID}_{TEST_DEVICE_ID}_ring",
	)
	client = harness_coordinator.client
	client.async_ring_device.return_value = client_success
	if not client_present:
		harness_coordinator.client = None

	assert ring.available is True
	await ring.async_press()

	if expected_call:
		client.async_ring_device.assert_awaited_once_with(
			device_id=TEST_DEVICE_ID,
			child_id=TEST_CHILD_ID,
		)
	else:
		client.async_ring_device.assert_not_awaited()
	harness_coordinator.async_request_refresh.assert_not_awaited()
