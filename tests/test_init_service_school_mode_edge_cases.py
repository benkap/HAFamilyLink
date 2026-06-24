"""Focused setup/service edge cases for school mode and schedules."""
from __future__ import annotations

import pytest

from custom_components.familylink import async_setup_services, extract_ids_from_entity
from custom_components.familylink.const import (
	DOMAIN,
	SERVICE_BLOCK_DEVICE_FOR_SCHOOL,
	SERVICE_SET_BEDTIME_SCHEDULE,
)
from custom_components.familylink.exceptions import FamilyLinkException

from conftest import TEST_CHILD_ID


@pytest.fixture
async def services_hass(hass, harness_coordinator):
	"""Register Family Link services for school-mode edge-case tests."""
	await async_setup_services(hass, harness_coordinator)
	return hass


@pytest.mark.parametrize("entity_id", [None, ""])
def test_extract_ids_from_empty_entity_id_returns_no_ids(hass, entity_id):
	"""Missing entity targets are treated as no extracted IDs."""
	assert extract_ids_from_entity(hass, entity_id) == (None, None)


async def test_child_school_block_exception_bubbles_without_refresh(
	services_hass, harness_coordinator
):
	"""Targeted school-block failures bubble before coordinator refresh."""
	harness_coordinator.client.async_block_device_for_school.side_effect = (
		FamilyLinkException("school block failed")
	)

	with pytest.raises(FamilyLinkException, match="school block failed"):
		await services_hass.services.async_call(
			DOMAIN,
			SERVICE_BLOCK_DEVICE_FOR_SCHOOL,
			{"child_id": TEST_CHILD_ID, "whitelist": ["com.spotify.music"]},
			blocking=True,
		)

	harness_coordinator.client.async_block_device_for_school.assert_awaited_once_with(
		account_id=TEST_CHILD_ID,
		whitelist=["com.spotify.music"],
	)
	harness_coordinator.client.async_get_all_supervised_children.assert_not_awaited()
	harness_coordinator.async_request_refresh.assert_not_awaited()


async def test_bedtime_schedule_generic_exception_bubbles_without_refresh(
	services_hass, harness_coordinator
):
	"""Non-partial bedtime schedule failures bubble without refreshing."""
	harness_coordinator.client.async_set_bedtime_schedule.side_effect = RuntimeError(
		"bedtime schedule failed"
	)

	with pytest.raises(RuntimeError, match="bedtime schedule failed"):
		await services_hass.services.async_call(
			DOMAIN,
			SERVICE_SET_BEDTIME_SCHEDULE,
			{"day": 2, "enabled": True, "child_id": TEST_CHILD_ID},
			blocking=True,
		)

	harness_coordinator.client.async_set_bedtime_schedule.assert_awaited_once_with(
		day=2,
		start_time=None,
		end_time=None,
		enabled=True,
		account_id=TEST_CHILD_ID,
	)
	harness_coordinator.async_request_refresh.assert_not_awaited()
