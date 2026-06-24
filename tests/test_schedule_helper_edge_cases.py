"""Edge-case tests for Family Link schedule parsing helpers."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


MODULE_PATH = (
	Path(__file__).parents[1]
	/ "custom_components"
	/ "familylink"
	/ "schedules.py"
)
spec = importlib.util.spec_from_file_location("familylink_schedules_edge_cases", MODULE_PATH)
schedules = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(schedules)


@pytest.mark.parametrize("value", [None, 3, True, False, "", " ", "\t\n", "UTC+03:00"])
def test_get_time_zone_rejects_non_string_blank_and_invalid_names(value):
	assert schedules.get_time_zone(value) is None


def test_find_device_time_zone_name_skips_invalid_payload_shapes():
	invalid_device_too_short = [None] * 11
	invalid_settings_type = [None] * 11 + ["Asia/Jerusalem"]
	invalid_empty_settings = [None] * 11 + [[]]
	invalid_timezone_type = [None] * 11 + [[True]]
	invalid_timezone_name = [None] * 11 + [["UTC+03:00"]]
	valid_timezone = [None] * 11 + [["  Asia/Jerusalem  "]]

	for source in (
		None,
		[],
		[None],
		[None, "devices"],
		[None, [None, invalid_device_too_short]],
		[None, [invalid_settings_type]],
		[None, [invalid_empty_settings]],
		[None, [invalid_timezone_type]],
		[None, [invalid_timezone_name]],
	):
		assert schedules.find_device_time_zone_name(source) is None

	assert (
		schedules.find_device_time_zone_name([
			None,
			[
				invalid_settings_type,
				invalid_timezone_name,
				valid_timezone,
			],
		])
		== "Asia/Jerusalem"
	)


@pytest.mark.parametrize("invalid_day", [True, False])
def test_day_helper_rejects_booleans(invalid_day):
	with pytest.raises(ValueError):
		schedules.day_code_for(invalid_day)


@pytest.mark.parametrize("invalid_time", [True, False])
def test_time_helper_rejects_booleans(invalid_time):
	with pytest.raises(ValueError):
		schedules.parse_time_string(invalid_time)


@pytest.mark.parametrize("invalid_minutes", [True, False])
def test_minute_helper_rejects_booleans(invalid_minutes):
	with pytest.raises(ValueError):
		schedules.build_daily_limit_schedule_update_payload("child123", 1, invalid_minutes)


def test_parse_window_schedule_items_skips_malformed_rows():
	items = [
		None,
		["CAEQAQ", 1, 2, [21, 0]],
		["CAEQAQ", True, 2, [21, 0], [6, 30]],
		["CAEQAQ", 1, True, [21, 0], [6, 30]],
		["CAEQAQ", 8, 2, [21, 0], [6, 30]],
		["CAEQAQ", 1, 2, [21, True], [6, 30]],
		["CAEQAQ", 1, 2, [24, 0], [6, 30]],
		["CAEQAQ", 1, 2, [21, 0], [6, 60]],
		["CAMQAQ", 1, 2, [21, 0], [6, 30]],
		["CAEQAg", 2, 2, [20, 45], [7, 15]],
	]

	assert schedules.parse_window_schedule_items(items, "CAEQ") == [
		{
			"day": 2,
			"day_name": "Tuesday",
			"enabled": True,
			"start": [20, 45],
			"end": [7, 15],
			"state_flag": 2,
		}
	]


def test_parse_daily_limit_schedule_skips_malformed_rows():
	config = [
		[
			["CAEQAQ", 1, 2, 90],
			["CAEQAg", True, 2, 45],
			["CAEQAw", 3, True, 45],
			["CAEQBA", 4, 2, True],
			["CAEQBQ", 5, 2, -1],
			["CAEQBg", 6, 2, "60"],
			["CAEQBw", 7, 2],
			["other", 2, 2, 60],
		]
	]

	assert schedules.parse_daily_limit_schedule(None) == []
	assert schedules.parse_daily_limit_schedule(config) == [
		{
			"day": 1,
			"day_name": "Monday",
			"enabled": True,
			"minutes": 90,
			"state_flag": 2,
		}
	]


def test_describe_effective_window_handles_invalid_day_without_weekly_match():
	weekly_schedule = [{
		"day": 1,
		"day_name": "Monday",
		"enabled": True,
		"start": [21, 0],
		"end": [6, 30],
		"state_flag": 2,
	}]

	assert schedules.describe_effective_window("21:00", "06:30", weekly_schedule, True) == {
		"start": "21:00",
		"end": "06:30",
		"label": "21:00-06:30",
		"source": "none",
		"weekly_start": None,
		"weekly_end": None,
		"weekly_label": None,
		"differs_from_weekly": False,
	}


def test_describe_effective_window_keeps_weekly_context_when_no_effective_window():
	weekly_schedule = [{
		"day": 1,
		"day_name": "Monday",
		"enabled": True,
		"start": [21, 0],
		"end": [6, 30],
		"state_flag": 2,
	}]

	assert schedules.describe_effective_window(None, None, weekly_schedule, 1) == {
		"start": None,
		"end": None,
		"label": None,
		"source": "none",
		"weekly_start": "21:00",
		"weekly_end": "06:30",
		"weekly_label": "21:00-06:30",
		"differs_from_weekly": False,
	}


def test_describe_effective_window_ignores_disabled_weekly_slot():
	weekly_schedule = [{
		"day": 1,
		"day_name": "Monday",
		"enabled": False,
		"start": [21, 0],
		"end": [6, 30],
		"state_flag": 1,
	}]

	assert schedules.describe_effective_window("21:00", "06:30", weekly_schedule, 1) == {
		"start": "21:00",
		"end": "06:30",
		"label": "21:00-06:30",
		"source": "today_override",
		"weekly_start": None,
		"weekly_end": None,
		"weekly_label": None,
		"differs_from_weekly": False,
	}


@pytest.mark.parametrize(
	("bedtime_window", "bedtime_today_source", "expected"),
	[
		({"label": None, "source": "weekly"}, "today_override", "weekly"),
		({"label": None, "source": None}, "today_override", "none"),
		({"label": "21:00-06:30", "source": "weekly"}, None, "weekly"),
		({"label": "21:00-06:30", "source": "weekly"}, "today_override", "today_override"),
	],
)
def test_effective_bedtime_window_source_falls_back_to_window_source(
	bedtime_window,
	bedtime_today_source,
	expected,
):
	assert (
		schedules.effective_bedtime_window_source(bedtime_window, bedtime_today_source)
		== expected
	)
