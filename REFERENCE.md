# Advanced Reference

This page is for entity lookup, legacy sensors, and local development. If you are installing for the first time, start with the [README](README.md) and [Installation Guide](INSTALL.md).

## Available Entities

Entity IDs depend on your child and device names, so treat the examples below as patterns.

### Per-Child Entities

#### Device Tracker

Requires GPS location tracking.

- `device_tracker.<child>`
- State: `home`, `not_home`, or a zone name
- Useful attributes: `source_device`, `place_name`, `address`, `location_timestamp`, `battery_level`

#### Battery Sensor

Requires GPS location tracking.

- `sensor.<child>_battery_level`
- State: battery percentage from the Family Link location source device
- Useful attributes: `source_device`, `last_update`

This is the battery for the device selected for location tracking in Family Link, not every supervised device.

#### Global Switches

- `switch.<child>_bedtime`
- `switch.<child>_school_time`
- `switch.<child>_daily_limit`

#### Schedule Sensors

- `sensor.<child>_bedtime_schedule`
- `sensor.<child>_school_time_schedule`
- `sensor.<child>_daily_limit_schedule`

Common attributes include `enabled`, `enabled_days`, `schedule`, `today`, `schedule_today_key`, and weekday names from `monday` through `sunday`.

School time schedules are read-only. This fork supports recurring schedule writes for bedtime and daily limits, not weekly school time.

#### Schedule Services

- `familylink.set_bedtime`
- `familylink.set_daily_limit`
- `familylink.set_bedtime_schedule`
- `familylink.set_daily_limit_schedule`

Schedule day calculations use `schedule_timezone` when configured. Otherwise the integration uses the child's device timezone from Google when available, then Home Assistant's timezone.

#### App Control Services

- `familylink.block_app`
- `familylink.unblock_app`
- `familylink.set_app_daily_limit`
- `familylink.block_device_for_school`
- `familylink.unblock_all_apps`

These services need Android package names, such as `com.youtube.android`. You can find package names in app sensor attributes like:

- `sensor.<child>_blocked_apps`
- `sensor.<child>_apps_with_time_limits`
- `sensor.<child>_apps_without_limits`
- `sensor.<child>_always_allowed_apps`
- `sensor.<child>_top_app_1` through `sensor.<child>_top_app_10`

See [Services](SERVICES.md) for service parameters and examples.

### Per-Device Entities

#### Sensors

- `sensor.<device>_screen_time_remaining`
- `sensor.<device>_next_restriction`
- `sensor.<device>_daily_limit`
- `sensor.<device>_active_bonus`

#### Binary Sensors

- `binary_sensor.<device>_bedtime_active`
  - Useful attributes: `bedtime_start`, `bedtime_end`
- `binary_sensor.<device>_school_time_active`
  - Useful attributes: `schooltime_start`, `schooltime_end`
- `binary_sensor.<device>_daily_limit_reached`

#### Device Switch

- `switch.<device>`

State meaning:

- On: device is unlocked
- Off: device is locked

Useful bedtime attributes include:

- `bedtime_window_start`
- `bedtime_window_end`
- `bedtime_window_label`
- `bedtime_window_source`
- `bedtime_weekly_window_label`
- `bedtime_window_differs_from_weekly`
- `bedtime_today_source`
- `bedtime_today_override_action`

`bedtime_window_source` is `weekly`, `today_override`, or `none`. `bedtime_today_override_action` mirrors Google's raw action where `1` means disabled today and `2` means enabled today.

#### Buttons

- `button.<device>_15min`
- `button.<device>_30min`
- `button.<device>_60min`
- `button.<device>_reset_bonus`

The reset button is only available when a bonus is active.

## Legacy Sensors

These child-level sensors remain available for compatibility:

- `sensor.<child>_daily_screen_time`
- `sensor.<child>_screen_time_formatted`
- `sensor.<child>_installed_apps`
- `sensor.<child>_blocked_apps`
- `sensor.<child>_apps_with_time_limits`
- `sensor.<child>_apps_without_limits`
- `sensor.<child>_always_allowed_apps`
- `sensor.<child>_top_app_1` through `sensor.<child>_top_app_10`
- `sensor.<child>_device_count`
- `sensor.<child>_child_info`

## Development Setup

Create a local environment:

```bash
python -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
```

Run tests:

```bash
.venv/bin/python -m pytest
```

Useful checks before opening a pull request:

```bash
.venv/bin/python -m pytest --cov=custom_components.familylink --cov-report=term-missing --cov-report=xml --cov-fail-under=100
.venv/bin/python -m ruff check .
.venv/bin/python -m compileall -q custom_components/familylink familylink-playwright/app tests
git diff --check
```

For contribution expectations, version bumps, and bug-report details, see [Contributing](CONTRIBUTING.md).
