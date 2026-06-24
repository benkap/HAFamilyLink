"""Remaining edge-case tests for the Family Link config flow."""
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_NAME
from homeassistant.data_entry_flow import AbortFlow, FlowResultType

from custom_components.familylink import config_flow
from custom_components.familylink.const import (
	CONF_AUTH_URL,
	CONF_ENABLE_LOCATION_TRACKING,
	CONF_SCHEDULE_TIMEZONE,
	CONF_TIMEOUT,
	CONF_UPDATE_INTERVAL,
	DEFAULT_TIMEOUT,
	DEFAULT_UPDATE_INTERVAL,
	DOMAIN,
	INTEGRATION_NAME,
)
from custom_components.familylink.config_flow import ConfigFlow

from conftest import TEST_AUTH_URL


class MockAddonCookieClient:
	"""Config-flow-facing auth client mock."""

	detected_source = "api"
	detected_url = TEST_AUTH_URL

	def __init__(self, hass, auth_url=None):
		self.hass = hass
		self.auth_url = auth_url

	async def detect_auth_source(self):
		return self.detected_source, self.detected_url


def _patch_addon_client(monkeypatch, *, detected_source="api", detected_url=TEST_AUTH_URL):
	MockAddonCookieClient.detected_source = detected_source
	MockAddonCookieClient.detected_url = detected_url
	monkeypatch.setattr(
		"custom_components.familylink.auth.addon_client.AddonCookieClient",
		MockAddonCookieClient,
	)


def _valid_config_input() -> dict[str, object]:
	return {
		CONF_NAME: INTEGRATION_NAME,
		CONF_UPDATE_INTERVAL: 60,
		CONF_TIMEOUT: 30,
		CONF_ENABLE_LOCATION_TRACKING: False,
		CONF_SCHEDULE_TIMEZONE: "",
	}


async def _start_configure_step(hass, monkeypatch):
	_patch_addon_client(monkeypatch)
	result = await hass.config_entries.flow.async_init(
		DOMAIN,
		context={"source": config_entries.SOURCE_USER},
	)
	assert result["type"] is FlowResultType.MENU

	result = await hass.config_entries.flow.async_configure(
		result["flow_id"],
		{"next_step_id": "auto_detect"},
	)
	assert result["type"] is FlowResultType.FORM
	assert result["step_id"] == "configure"
	return result


def _schema_defaults(schema: vol.Schema) -> dict[str, object]:
	return {marker.schema: marker.default() for marker in schema.schema}


def test_normalize_schedule_timezone_none_returns_blank():
	"""Treat a missing schedule timezone as the integration default."""
	assert config_flow._normalize_schedule_timezone(None) == ""


async def test_auto_detect_none_falls_back_to_manual_url_with_placeholder(
	hass, monkeypatch
):
	"""Auto-detect with no source shows the manual URL form and its default hint."""
	_patch_addon_client(monkeypatch, detected_source="none", detected_url=None)

	result = await hass.config_entries.flow.async_init(
		DOMAIN,
		context={"source": config_entries.SOURCE_USER},
	)
	result = await hass.config_entries.flow.async_configure(
		result["flow_id"],
		{"next_step_id": "auto_detect"},
	)

	assert result["type"] is FlowResultType.FORM
	assert result["step_id"] == "manual_url"
	assert result["errors"] == {}
	assert result["description_placeholders"] == {
		"default_url": "http://localhost:8099",
	}


@pytest.mark.parametrize(
	("side_effect", "expected_error"),
	[
		(config_flow.CannotConnect, "cannot_connect"),
		(config_flow.InvalidAuth, "invalid_auth"),
		(RuntimeError("boom"), "unknown"),
	],
)
async def test_configure_maps_validation_errors_to_form_errors(
	hass, monkeypatch, side_effect, expected_error
):
	"""Keep validation failures on the configure form with targeted messages."""
	result = await _start_configure_step(hass, monkeypatch)
	monkeypatch.setattr(
		config_flow,
		"validate_input",
		AsyncMock(side_effect=side_effect),
	)

	result = await hass.config_entries.flow.async_configure(
		result["flow_id"],
		_valid_config_input(),
	)

	assert result["type"] is FlowResultType.FORM
	assert result["step_id"] == "configure"
	assert result["errors"] == {"base": expected_error}


async def test_configure_propagates_abort_flow_from_validation(hass, monkeypatch):
	"""AbortFlow from validation should not be collapsed into an unknown error."""
	result = await _start_configure_step(hass, monkeypatch)
	monkeypatch.setattr(
		config_flow,
		"validate_input",
		AsyncMock(side_effect=AbortFlow("validation_aborted")),
	)

	result = await hass.config_entries.flow.async_configure(
		result["flow_id"],
		_valid_config_input(),
	)

	assert result["type"] is FlowResultType.ABORT
	assert result["reason"] == "validation_aborted"


def test_configure_schema_uses_expected_defaults():
	"""The configure form should start with the intended integration defaults."""
	defaults = _schema_defaults(ConfigFlow()._configure_schema())

	assert defaults == {
		CONF_NAME: INTEGRATION_NAME,
		CONF_UPDATE_INTERVAL: DEFAULT_UPDATE_INTERVAL,
		CONF_TIMEOUT: DEFAULT_TIMEOUT,
		CONF_ENABLE_LOCATION_TRACKING: False,
		CONF_SCHEDULE_TIMEZONE: "",
	}


def test_configure_schema_preserves_submitted_timezone_default():
	"""Invalid timezone retries should keep the submitted value visible."""
	defaults = _schema_defaults(
		ConfigFlow()._configure_schema({CONF_SCHEDULE_TIMEZONE: "Not/AZone"})
	)

	assert defaults[CONF_SCHEDULE_TIMEZONE] == "Not/AZone"


@pytest.mark.parametrize(
	("detected_source", "detected_url", "auth_url", "expected_source"),
	[
		("api", TEST_AUTH_URL, None, f"API ({TEST_AUTH_URL})"),
		("file", None, None, "Local file (/share/familylink/)"),
		(None, None, TEST_AUTH_URL, TEST_AUTH_URL),
		(None, None, None, "Manual URL"),
	],
)
def test_configure_description_placeholders(
	detected_source, detected_url, auth_url, expected_source
):
	"""Describe the selected auth source in the configure form."""
	flow = ConfigFlow()
	flow._detected_source = detected_source
	flow._detected_url = detected_url

	assert flow._description_placeholders(auth_url) == {
		"auth_source": expected_source,
	}


async def test_import_cannot_connect_aborts_invalid_config(hass, monkeypatch):
	"""YAML import connect failures should abort with invalid_config."""
	monkeypatch.setattr(
		config_flow,
		"validate_input",
		AsyncMock(side_effect=config_flow.CannotConnect),
	)

	result = await hass.config_entries.flow.async_init(
		DOMAIN,
		context={"source": config_entries.SOURCE_IMPORT},
		data={CONF_NAME: INTEGRATION_NAME},
	)

	assert result["type"] is FlowResultType.ABORT
	assert result["reason"] == "invalid_config"
