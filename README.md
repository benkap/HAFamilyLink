# <img src="https://brands.home-assistant.io/familylink/icon.png" alt="Google Family Link" width="30" > Google Family Link Home Assistant Integration

[![GitHub Release][releases-shield]][releases]
[![HACS][hacsbadge]][hacs]
[![License][license-shield]][license]

Built from the brilliant work by [@noiwid](https://github.com/noiwid), this fork adds the Family Link API coverage and opinionated tweaks I needed for my own home. If that sounds like more than you need, start with [noiwid/HAFamilyLink](https://github.com/noiwid/HAFamilyLink) first; it may be the cleaner fit for your setup.

## 🚨 Important Disclaimer

This integration uses unofficial, reverse-engineered Google Family Link API endpoints. **Use at your own risk**. This may violate Google's Terms of Service and could result in account suspension. This project is not affiliated with, endorsed by, or connected to Google LLC.

This fork's added controls and sensors are built the same way: by observing and reverse-engineering Google's undocumented Family Link behavior. They work against the current API shape, but Google can change or remove that behavior without notice, so any feature here may break or need updates.

## ✨ Features

### 📱 Device Control
- **Lock/Unlock Devices** - Control device access with switches in Home Assistant
- **Real-time Synchronization** - Lock state automatically syncs with Google Family Link
- **Multi-device Support** - Manage multiple supervised devices
- **Bi-directional Control** - Changes made in Family Link app reflect in Home Assistant

### ⏰ Time Management
- **Bedtime Control** - Enable/disable bedtime (downtime) restrictions
- **Set Bedtime Schedule** - Modify recurring bedtime start/end times for any weekday
- **Daily Limit Control** - Enable/disable daily screen time limits (0-1440 minutes)
- **Today Overrides** - Apply one-day bedtime and daily limit changes without editing the weekly schedule
- **Set Daily Limit Schedule** - Modify recurring daily limit minutes for any weekday
- **Time Bonuses** - Add extra time (15min, 30min, 60min) or cancel active bonuses
- **Smart Detection** - Reads bedtime and school time windows from Google and exposes active-state sensors when that data is available
- **Schedule Visibility** - View bedtime, school time, and daily limit schedules in sensor attributes

### 📊 Screen Time Monitoring
- **Daily Screen Time** - Track total daily usage per child
- **Screen Time Remaining** - See remaining time per device (accounts for bonuses and used time)
- **Daily Limit Tracking** - Monitor daily limit quota per device
- **Active Bonus Display** - See active time bonuses per device
- **Top 10 Apps** - Monitor most-used apps with detailed usage statistics
- **App Breakdown** - Per-application usage breakdown

### 📲 App Visibility and Control
- **Installed Apps Count** - Total number of apps on supervised devices
- **Blocked Apps** - List and count of blocked/hidden apps
- **Apps with Time Limits** - Track apps with usage restrictions
- **App Details** - Package names, titles, and limit information
- **App Control Services** - Block/unblock apps by package name, set per-app daily limits, remove app limits, or mark apps as unlimited

### 📍 GPS Location Tracking (Optional)
- **Device Tracker** - Track your child's location via `device_tracker` entity
- **Place Detection** - Automatically shows when child is at a saved place (Home, School, etc.)
- **Address Display** - Full address of current location
- **Source Device** - Shows which device provided the location
- **Battery Level** - Monitor battery percentage of the location source device
- **On-Demand Refresh** - Force a fresh GPS update from the child's device
- **Privacy First** - Disabled by default, opt-in via configuration
- **⚠️ Warning** - Each location poll may notify the child's device

### 👶 Child Information
- **Profile Details** - Child's name, email, birthday, age band
- **Device Information** - Device model, name, capabilities, last activity
- **Family Members** - List of all family members with roles

## 🚧 Limitations / Not Currently Supported

Based on the current code, this fork does not currently provide:

- Weekly school time schedule editing; school time can be read and toggled for today, but recurring school time schedule writes are not implemented
- Parent approval / app install approval workflows
- Website allowlists or blocklists
- A built-in app picker for control services; app control requires Android package names

## 📋 Available Entities

### Per-Child Entities

#### Device Tracker (GPS Location - Optional)
- `device_tracker.<child>` - Child's GPS location
  - **State**: `home`, `not_home`, or zone name
  - **Attributes**:
    - `source_device` - Device name providing the location
    - `place_name` - Saved place name (e.g., "Home", "School")
    - `address` - Full address of the location
    - `location_timestamp` - When the location was captured
    - `battery_level` - Battery percentage of source device
  - **Note**: Requires enabling "GPS location tracking" in integration config

#### Battery Sensor (GPS Location - Optional)
- `sensor.<child>_battery_level` - Battery level of location source device
  - **State**: Battery percentage (0-100%)
  - **Device Class**: `battery`
  - **Attributes**:
    - `source_device` - Device name providing the battery data
    - `last_update` - Timestamp of last update
  - **Note**: Requires enabling "GPS location tracking" in integration config
  - **⚠️ Limitation**: Shows battery of the device selected for location tracking in Family Link app, not all devices

#### Switches (Global Controls)
- `switch.<child>_bedtime` - Enable/disable bedtime restrictions
- `switch.<child>_school_time` - Enable/disable school time for today
- `switch.<child>_daily_limit` - Enable/disable daily screen time limit

#### Schedule Sensors
- `sensor.<child>_bedtime_schedule` - Weekly bedtime schedule
- `sensor.<child>_school_time_schedule` - Weekly school time schedule
- `sensor.<child>_daily_limit_schedule` - Weekly daily limit schedule
  - Attributes: `enabled`, `enabled_days`, `schedule`, `today`, `schedule_today_key`, `monday` through `sunday`

#### Schedule Services
- `familylink.set_bedtime` - Apply a one-day bedtime override; defaults to today when no day is provided
- `familylink.set_daily_limit` - Apply today's daily time limit override for a device
- `familylink.set_bedtime_schedule` - Update a recurring bedtime weekday window and enabled state
- `familylink.set_daily_limit_schedule` - Update recurring daily limit minutes and enabled state for one weekday
- School time schedules are exposed read-only through `sensor.<child>_school_time_schedule`. This fork's recurring schedule write work focuses on bedtime and daily limits; it does not implement weekly school time schedule editing.
- Schedule day calculations use the optional `schedule_timezone` setting when provided. Leave it blank to use the child's device timezone from Google when available, then fall back to Home Assistant's timezone.

#### App Control Services
- `familylink.block_app` - Block an app by Android package name
- `familylink.unblock_app` - Remove app restrictions by Android package name
- `familylink.set_app_daily_limit` - Set a per-app daily limit, remove the app limit, block for the day, or mark the app as unlimited
- `familylink.block_device_for_school` - Block all apps except essential apps and an optional whitelist
- `familylink.unblock_all_apps` - Remove app blocks created by app-control services
- These services need Android package names such as `com.youtube.android`. You can find package names in app sensor attributes like `sensor.<child>_blocked_apps`, `sensor.<child>_apps_with_time_limits`, `sensor.<child>_apps_without_limits`, `sensor.<child>_always_allowed_apps`, and `sensor.<child>_top_app_1` through `sensor.<child>_top_app_10`.

### Per-Device Entities

#### Sensors
- `sensor.<device>_screen_time_remaining` - Remaining screen time in minutes
- `sensor.<device>_next_restriction` - Next upcoming restriction (bedtime/school time)
- `sensor.<device>_daily_limit` - Daily limit quota in minutes
- `sensor.<device>_active_bonus` - Active time bonus in minutes

#### Binary Sensors
- `binary_sensor.<device>_bedtime_active` - Currently in bedtime window
  - Attributes: `bedtime_start`, `bedtime_end` (ISO timestamps)
- `binary_sensor.<device>_school_time_active` - Currently in school time window
  - Attributes: `schooltime_start`, `schooltime_end` (ISO timestamps)
- `binary_sensor.<device>_daily_limit_reached` - Daily limit reached (true/false, ignores bonuses)

#### Switches
- `switch.<device>` - Lock/unlock device
  - **ON** = Device unlocked (child can use device) 📱
  - **OFF** = Device locked (device is locked) 🔒
  - Attributes include effective bedtime window details: `bedtime_window_start`, `bedtime_window_end`, `bedtime_window_label`, `bedtime_window_source`, `bedtime_weekly_window_label`, `bedtime_window_differs_from_weekly`, `bedtime_today_source`, and `bedtime_today_override_action`
  - `bedtime_window_source` is `weekly` when the active effective window comes from the recurring schedule, `today_override` when it comes from a one-day override (even if the hours match weekly), or `none` when no effective bedtime window is active
  - `bedtime_today_source` is `weekly` or `today_override` even when today's override disables downtime and no effective bedtime window exists; `bedtime_today_override_action` mirrors Google's raw action (`1` = disabled today, `2` = enabled today)

#### Buttons
- `button.<device>_15min` - Add 15 minutes bonus
- `button.<device>_30min` - Add 30 minutes bonus
- `button.<device>_60min` - Add 60 minutes bonus
- `button.<device>_reset_bonus` - Cancel active bonus (only available when bonus is active)

### Legacy Sensors (Child Level)
- `sensor.<child>_daily_screen_time` - Daily screen time in **minutes**
- `sensor.<child>_screen_time_formatted` - Daily screen time in **HH:MM:SS** format
- `sensor.<child>_installed_apps` - Number of installed apps
- `sensor.<child>_blocked_apps` - Number and list of blocked apps
- `sensor.<child>_apps_with_time_limits` - Apps with usage restrictions
- `sensor.<child>_apps_without_limits` - Apps that follow device limits
- `sensor.<child>_always_allowed_apps` - Apps marked as unlimited/always allowed
- `sensor.<child>_top_app_1` through `sensor.<child>_top_app_10` - Top 10 most-used apps
- `sensor.<child>_device_count` - Number of supervised devices
- `sensor.<child>_child_info` - Supervised child's profile information

## 🎯 What's New

### On-Demand Location Refresh (#78)

New `refresh_location` service to force a fresh GPS update from the child's device:

```yaml
service: familylink.refresh_location
data:
  entity_id: device_tracker.emma
```

## 🏗️ Architecture

This project consists of two components that work together:

### 1. Family Link Auth Add-on (`familylink-playwright/`)
Provides secure, browser-based authentication:
- **Playwright Automation** - Headless Chromium for Google login
- **2FA Support** - Handles SMS, authenticator, and push notifications
- **Cookie Extraction** - Securely stores authentication cookies
- **Auto-refresh** - Keeps authentication fresh

### 2. Home Assistant Integration (`custom_components/familylink/`)
Provides monitoring and control:
- **Config Flow** - User-friendly setup wizard
- **API Client** - Communicates with Google Family Link API
- **Coordinator** - Manages data updates and caching
- **Entities** - Sensors, binary sensors, switches, and buttons

### Why Two Components?

Home Assistant's Docker environment restricts browser automation. The add-on runs in a separate container with Chromium and Playwright, while the integration handles data fetching and device control.

## 📦 Installation

See the detailed [Installation Guide](INSTALL.md) for step-by-step instructions.

> **📌 Note for Home Assistant Core/Container Users**
>
> If you're running Home Assistant **without Supervisor** (Core or Container installation), you'll need to run the authentication add-on as a standalone Docker container. See the [Docker Standalone Guide](DOCKER_STANDALONE.md) for detailed instructions.

### Quick Start (Home Assistant OS / Supervised)

1. **Install Family Link Auth Add-on**

[![Open your Home Assistant instance and show the add add-on repository dialog with a specific repository URL pre-filled.](https://my.home-assistant.io/badges/supervisor_add_addon_repository.svg)](https://my.home-assistant.io/redirect/supervisor_add_addon_repository/?repository_url=https%3A%2F%2Fgithub.com%2Fbenkap%2FHAFamilyLink)
   - Add repository to Home Assistant 
   - Install and start the add-on
   - Authenticate via Web UI (open noVNC in your browser - see [Installation Guide](INSTALL.md))


2. **Install Integration**

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=benkap&repository=HAFamilyLink&category=integration)
   - Via HACS (recommended) or manually
   - Configure through Home Assistant UI
   - Cookies automatically loaded from add-on

3. **Enjoy!**
   - Monitor screen time
   - Control time limits
   - Manage bonuses
   - Create automations

## ⚙️ Configuration

This integration is configured entirely through the Home Assistant UI (Config Flow). **YAML configuration is not supported.**

### Setup via UI

1. Go to **Settings → Devices & Services → Add Integration**
2. Search for "**Family Link**" and select it
3. Configure the following options in the setup wizard:
   - **Name**: Display name for the integration (default: "Google Family Link")
   - **Update Interval**: How often to fetch data, in seconds (default: 300, range: 30-3600)
   - **Timeout**: API request timeout in seconds (default: 30)
   - **Enable GPS Location Tracking**: Opt-in for device location tracking (default: disabled)

### Update Interval

The default update interval is 5 minutes (300 seconds). You can change this value during initial setup or by reconfiguring the integration:
1. Go to **Settings → Devices & Services**
2. Find the Family Link integration
3. Click **Configure** to modify settings

### Lock State Synchronization

Device states are fetched from Google's `appliedTimeLimits` API endpoint. Changes made from the Family Link app or website are reflected in Home Assistant within the next update cycle.

## 🔧 API Endpoints Used

This integration uses reverse-engineered Google Family Link API endpoints:

| Endpoint | Purpose |
|----------|---------|
| `/families/mine/members` | Family member information |
| `/families/mine/location/{userId}` | Child GPS location |
| `/people/{userId}/apps` | Installed apps list |
| `/people/{userId}/apps:updateRestrictions` | Block/unblock apps, set per-app limits, remove app limits, or set apps as unlimited |
| `/people/{userId}/appsandusage` | App usage data |
| `/people/{userId}/devices` | Device metadata, including device timezone when exposed |
| `/people/{userId}/timeLimitOverrides:batchCreate` | Lock/unlock devices, add time bonuses, and apply today-only time-limit overrides |
| `/people/{userId}/timeLimitOverride/{id}?$httpMethod=DELETE` | Cancel time bonuses |
| `/people/{userId}/appliedTimeLimits` | Current time limits and lock states |
| `/people/{userId}/timeLimit` | Time limit rules and schedules |
| `/people/{userId}/timeLimit:update` | Enable/disable bedtime and daily limit; update recurring bedtime and daily limit schedules |

## 🐛 Troubleshooting

### 401 Authentication Errors

**Symptoms**: Logs show "401 Unauthorized" errors

**Solutions**:
1. Verify Family Link Auth add-on is running
2. Check API is accessible: `curl http://localhost:8099/api/cookies` (or your addon IP)
3. For file fallback: Check `/share/familylink/cookies.enc` and `.key` exist
4. Restart add-on to refresh authentication
5. Reload integration in Home Assistant

### Lock State Not Updating

**Symptoms**: Device lock state doesn't reflect actual state

**Solutions**:
1. Check logs for API errors
2. Verify device is online and connected
3. Wait for next update cycle (default: 5 minutes)
4. Manually lock/unlock from Family Link app to test sync

### Bedtime/School Time Not Detected

**Symptoms**: Binary sensors always show "off"

**Solutions**:
1. Verify schedules are configured in Family Link app
2. Check sensor attributes for `bedtime_start` and `bedtime_end` timestamps
3. Ensure schedules are enabled for current day of week
4. Check the integration's `schedule_timezone` option. If it is blank, confirm Google exposes the child device timezone or ensure Home Assistant timezone matches the child's schedule timezone

### Sensors Show "Not Configured" or "Unavailable"

**Symptoms**: Some sensors don't show data

**Cause**:
- Child-level schedule sensors removed in v0.8.0 (use device-level binary sensors instead)
- No app usage data for current date

**Solution**:
- Manually delete old entities from UI
- Wait until child uses apps today for usage data

### Cookies Expired

**Symptoms**: "Session expired" errors in logs

**Solution**:
1. Open add-on Web UI (port 8099)
2. Click "Démarrer l'authentification"
3. Complete Google login
4. Integration automatically picks up new cookies

## 📊 Example Automations

### Bedtime Lock

```yaml
automation:
  - alias: "Lock phone at bedtime"
    trigger:
      - platform: time
        at: "21:00:00"
    condition:
      - condition: time
        weekday:
          - mon
          - tue
          - wed
          - thu
          - fri
    action:
      - service: switch.turn_off
        target:
          entity_id: switch.child_phone
```

### Enable Bedtime Mode on Weeknights

```yaml
automation:
  - alias: "Enable bedtime on weeknights"
    trigger:
      - platform: time
        at: "20:00:00"
    condition:
      - condition: time
        weekday:
          - mon
          - tue
          - wed
          - thu
    action:
      - service: switch.turn_on
        target:
          entity_id: switch.firstname_lastname_bedtime
```

### Screen Time Alert

```yaml
automation:
  - alias: "Alert on excessive screen time"
    trigger:
      - platform: numeric_state
        entity_id: sensor.galaxy_tab_firstname_screen_time_remaining
        below: 30  # Less than 30 minutes remaining
    action:
      - service: notify.mobile_app
        data:
          message: "Only {{ states('sensor.galaxy_tab_firstname_screen_time_remaining') }} minutes remaining!"
```

### Add Bonus Time on Homework Completion

```yaml
automation:
  - alias: "Bonus time for homework"
    trigger:
      - platform: state
        entity_id: input_boolean.homework_done
        to: "on"
    action:
      - service: button.press
        target:
          entity_id: button.galaxy_tab_firstname_30min
      - service: notify.mobile_app
        data:
          message: "Good job! Added 30 minutes bonus time."
```

### Daily Limit Reached Notification

```yaml
automation:
  - alias: "Notify when daily limit reached"
    trigger:
      - platform: state
        entity_id: binary_sensor.galaxy_tab_firstname_daily_limit_reached
        to: "on"
    action:
      - service: notify.mobile_app
        data:
          message: "{{ trigger.to_state.attributes.device_name }} has reached its daily limit"
```

### Location-Based Automation (GPS Tracking)

```yaml
automation:
  - alias: "Notify when child leaves school"
    trigger:
      - platform: state
        entity_id: device_tracker.firstname
        from: "School"
    action:
      - service: notify.mobile_app_parent
        data:
          message: "{{ trigger.to_state.name }} has left school"

  - alias: "Notify when child arrives home"
    trigger:
      - platform: state
        entity_id: device_tracker.firstname
        to: "home"
    action:
      - service: notify.mobile_app_parent
        data:
          message: "{{ trigger.to_state.name }} is home!"
```

## 📈 Version History

- **v1.0.0** (2026-01) - Multi-child groundwork
  - Better targeting support across child/device entities
  - Improved app visibility data for installed apps, blocked apps, and app usage
 
- **v0.9.8** (2026-01) - Battery Level Support
  - **Battery Level Sensor** - Monitor battery % of location source device
  - Requires location tracking to be enabled
  - Shows battery of the device selected for location in Family Link app

- **v0.9.7** (2025-12) - Regional Google Domains Auth Fix
  - Fixed authentication loop with regional Google domains (.google.com.au, .google.co.uk, etc.)

- **v0.9.6** (2025-12) - Set Bedtime Service
  - New `familylink.set_bedtime` service to modify bedtime schedules dynamically
  - Fixed authentication issues
  - `set_daily_limit` now accepts 0 minutes to disable device

- **v0.9.5** (2025-11) - Bedtime/School Time Toggle Fix
  - Fixed bedtime/school time toggle (was using hardcoded UUIDs)
  - Now dynamically fetches rule IDs from timeLimit API

- **v0.9.4** (2025-11) - GPS Location & Docker Standalone
  - **GPS Device Tracker** - Track child location via `device_tracker` entity
    - Opt-in configuration (disabled by default for privacy)
    - Shows saved places (Home, School) and full address
  - **Docker Standalone Mode** - Run without Home Assistant Supervisor
    - HTTP API for cookie retrieval
    - Separate Docker images for addon vs standalone
  - **Entity Selectors** - Services now show entity pickers in UI
  - **French & English translations** - Full i18n support
  - **Auth Notification Fix** - Properly triggers when session expires (no spam)
  - **Bug Fixes** - Fixed set_daily_limit dynamic day codes, bashio errors

- **v0.9.3** (2025-11) - Set Daily Limit Fix
  - Fixed `set_daily_limit` applying to wrong day of week

- **v0.9.2** (2025-11) - Standalone Docker Fix
  - Fixed bashio errors in standalone Docker deployment
  - Created separate Docker images for HA OS/Supervised vs pure Docker

- **v0.9.1** (2025-11) - Auth Expiration Notification
  - Persistent notification when Google authentication expires
  - Re-authentication instructions included
  - "No app usage data" moved from warning to debug log

- **v0.8.0** (2025-01) - Release Candidate
  - Time bonus management (add/cancel bonuses)
  - Enhanced per-device sensors (daily limit, active bonus, screen time remaining)
  - Fixed bedtime/school time window parsing
  - Fixed time calculations (bonus replaces time, not adds)
  - Daily Limit Reached sensor returns true/false
  - Removed redundant child-level schedule sensors

- **v0.7.6** (2025-01) - Bonus cancellation and fixes
  - Parse bonus override_id from API
  - Reset Bonus button implementation
  - Fixed bonus detection false positives
  - Fixed used time parsing (position 20)

- **v0.7.4** (2025-01) - Bedtime/School Time parsing
  - Complete bedtime window parsing
  - Complete school time window parsing
  - Midnight-crossing support
  - Binary sensors for active detection

- **v0.6.5** (2024-12) - Stable base version
  - Bedtime, School Time, Daily Limit switches
  - Device lock/unlock functionality
  - Screen time monitoring

- **v0.5.0** - Real-time device lock state synchronization
- **v0.4.x** - Device lock/unlock functionality
- **v0.3.0** - App usage and screen time sensors
- **v0.2.x** - Authentication fixes and improvements
- **v0.1.0** - Initial release

## 🤝 Contributing

Contributions are welcome! Please follow these steps:

1. Fork the repository
2. Create a feature branch
3. Make your changes with clear commit messages
4. Test thoroughly
5. Submit a pull request

### Development Setup

```bash
git clone https://github.com/benkap/HAFamilyLink.git
cd HAFamilyLink
python -m venv venv
source venv/bin/activate
pip install -r requirements-dev.txt
```

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## 🙏 Credits

- Huge thanks to [@noiwid](https://github.com/noiwid) for the brilliant original HAFamilyLink project. This fork would not exist without that work.
- Based on the original work by [@tducret](https://github.com/tducret/familylink) (Python package documenting Family Link API endpoints)
- Inspired by [@Vortitron's HAFamilyLink](https://github.com/Vortitron/HAFamilyLink) repository
- noVNC integration inspired by [@jnctech's fork](https://github.com/jnctech/HAFamilyLink)
- Home Assistant community for integration examples and best practices
- Reverse engineering insights from browser DevTools analysis

## 📞 Support

- [Report Issues](https://github.com/benkap/HAFamilyLink/issues)
- [Feature Requests](https://github.com/benkap/HAFamilyLink/issues/new)
- [Discussions](https://github.com/benkap/HAFamilyLink/discussions)

## ⚠️ Legal

This is an unofficial integration and is not affiliated with, endorsed by, or connected to Google LLC. All product names, logos, and brands are property of their respective owners. Use at your own risk.

[releases-shield]: https://img.shields.io/github/release/benkap/HAFamilyLink.svg?style=for-the-badge
[releases]: https://github.com/benkap/HAFamilyLink/releases
[license-shield]: https://img.shields.io/github/license/benkap/HAFamilyLink.svg?style=for-the-badge
[license]: LICENSE
[hacsbadge]: https://img.shields.io/badge/HACS-Custom-orange.svg?style=for-the-badge
[hacs]: https://github.com/hacs/integration
