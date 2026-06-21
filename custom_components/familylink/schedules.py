"""Schedule parsing helpers for Google Family Link responses."""
from __future__ import annotations

from typing import Any

DAY_NAMES = {
	1: "Monday",
	2: "Tuesday",
	3: "Wednesday",
	4: "Thursday",
	5: "Friday",
	6: "Saturday",
	7: "Sunday",
}

DAY_CODES = {
	1: "CAEQAQ",
	2: "CAEQAg",
	3: "CAEQAw",
	4: "CAEQBA",
	5: "CAEQBQ",
	6: "CAEQBg",
	7: "CAEQBw",
}


def _is_int(value: Any) -> bool:
	"""Return true for plain integers, excluding booleans."""
	return type(value) is int


def _is_time_pair(value: Any) -> bool:
	"""Return true for [hour, minute] pairs."""
	return (
		isinstance(value, list)
		and len(value) == 2
		and _is_int(value[0])
		and _is_int(value[1])
		and 0 <= value[0] <= 23
		and 0 <= value[1] <= 59
	)


def format_time_pair(value: list[int]) -> str:
	"""Format a [hour, minute] pair as HH:MM."""
	return f"{value[0]:02d}:{value[1]:02d}"


def day_code_for(day: int) -> str:
	"""Return the Family Link day code for an ISO weekday."""
	if not _is_int(day) or day not in DAY_CODES:
		raise ValueError(f"Invalid day: {day}. Must be 1-7 (Monday-Sunday)")
	return DAY_CODES[day]


def parse_time_string(value: str) -> list[int]:
	"""Parse HH:MM into a Family Link [hour, minute] pair."""
	if not isinstance(value, str):
		raise ValueError("Time must be a string in HH:MM format")

	parts = value.split(":")
	if len(parts) != 2:
		raise ValueError(f"Invalid time: {value}. Expected HH:MM")

	try:
		pair = [int(parts[0]), int(parts[1])]
	except ValueError as err:
		raise ValueError(f"Invalid time: {value}. Expected HH:MM") from err

	if not _is_time_pair(pair):
		raise ValueError(f"Invalid time: {value}. Expected HH:MM in 24-hour time")

	return pair


def build_bedtime_schedule_update_payload(
	account_id: str,
	day: int,
	start_time: str,
	end_time: str,
) -> list[Any]:
	"""Build a recurring bedtime window update payload."""
	return [
		None,
		account_id,
		[[None, None, None, [[day_code_for(day), parse_time_string(start_time), parse_time_string(end_time)]]], None, None, None, []],
		None,
		[1],
	]


def build_bedtime_day_enabled_update_payload(
	account_id: str,
	day: int,
	enabled: bool,
) -> list[Any]:
	"""Build a recurring bedtime weekday on/off payload."""
	if type(enabled) is not bool:
		raise ValueError("enabled must be a boolean")

	return [
		None,
		account_id,
		[[None, None, [[day_code_for(day), 2 if enabled else 1]], None], None, None, None, []],
		None,
		[1],
	]


def build_daily_limit_schedule_update_payload(
	account_id: str,
	day: int,
	minutes: int,
) -> list[Any]:
	"""Build a recurring daily limit minutes update payload."""
	if not _is_int(minutes) or not 0 <= minutes <= 1440:
		raise ValueError("minutes must be an integer from 0 to 1440")

	return [
		None,
		account_id,
		[None, [[2, None, None, [[day_code_for(day), minutes]]]]],
		None,
		[1],
	]


def parse_window_schedule_items(items: Any, code_prefix: str) -> list[dict[str, Any]]:
	"""Parse bedtime or school time rows from a timeLimit schedule list."""
	schedules: list[dict[str, Any]] = []

	if not isinstance(items, list):
		return schedules

	for item in items:
		if not (isinstance(item, list) and len(item) >= 5):
			continue

		code = item[0]
		day = item[1] if len(item) > 1 else None
		state_flag = item[2] if len(item) > 2 else None
		start = item[3] if len(item) > 3 else None
		end = item[4] if len(item) > 4 else None

		if not (
			isinstance(code, str)
			and code.startswith(code_prefix)
			and _is_int(day)
			and day in DAY_NAMES
			and _is_int(state_flag)
			and _is_time_pair(start)
			and _is_time_pair(end)
		):
			continue

		schedules.append({
			"day": day,
			"day_name": DAY_NAMES[day],
			"enabled": state_flag == 2,
			"start": start,
			"end": end,
			"state_flag": state_flag,
		})

	return sorted(schedules, key=lambda slot: slot["day"])


def _walk_lists(value: Any):
	"""Yield nested lists from a response fragment."""
	if not isinstance(value, list):
		return

	yield value
	for item in value:
		if isinstance(item, list):
			yield from _walk_lists(item)


def parse_daily_limit_schedule(config: Any) -> list[dict[str, Any]]:
	"""Parse daily limit rows from the timeLimit daily limit config block."""
	schedules_by_day: dict[int, dict[str, Any]] = {}

	for item in _walk_lists(config):
		if len(item) < 4:
			continue

		code = item[0]
		day = item[1] if len(item) > 1 else None
		state_flag = item[2] if len(item) > 2 else None
		minutes = item[3] if len(item) > 3 else None

		if not (
			isinstance(code, str)
			and code.startswith("CAEQ")
			and _is_int(day)
			and day in DAY_NAMES
			and _is_int(state_flag)
			and _is_int(minutes)
			and minutes >= 0
		):
			continue

		schedules_by_day[day] = {
			"day": day,
			"day_name": DAY_NAMES[day],
			"enabled": state_flag == 2 and minutes > 0,
			"minutes": minutes,
			"state_flag": state_flag,
		}

	return [schedules_by_day[day] for day in sorted(schedules_by_day)]
