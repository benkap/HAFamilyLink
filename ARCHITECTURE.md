# Architecture

HAFamilyLink has two moving parts: an auth service that can run a browser, and a Home Assistant integration that talks to Google Family Link.

## Components

### Family Link Auth Add-On

Path: `familylink-playwright/`

The auth service handles Google login and cookie extraction:

- Runs Chromium with Playwright
- Supports browser-based Google login and 2FA
- Stores encrypted cookies
- Serves cookies to the integration through the protected local auth API

Home Assistant OS and Supervised installs use it as an add-on. Home Assistant Core and Container installs run it as a standalone Docker container.

### Home Assistant Integration

Path: `custom_components/familylink/`

The integration handles Home Assistant setup and entity behavior:

- Config flow and options flow
- Family Link API client
- Coordinator refresh and cache behavior
- Sensors, binary sensors, switches, buttons, device trackers, and services

## Why Two Components?

Google login needs browser automation. Home Assistant's normal integration environment is not a good place to run Chromium, so the auth service owns the browser work and the integration stays focused on data fetches and device control.

The integration can read cookies from the auth service API. The cookie endpoint is API-key protected. For add-on installs, the integration can also use the shared encrypted cookie files as a fallback.

## Data Flow

1. User authenticates with Google in the auth service browser.
2. Auth service stores encrypted Family Link cookies.
3. Home Assistant integration loads cookies through the auth API or file fallback.
4. Integration calls reverse-engineered Family Link endpoints.
5. Coordinator normalizes the response into Home Assistant entities.
6. Services call Family Link write endpoints for locks, bonuses, app controls, and supported schedules.

## API Endpoints Used

These endpoints are reverse-engineered and may change without notice. Paths below are relative to the Google Kids Management API base.

| Endpoint | Purpose |
| --- | --- |
| `/families/mine/members` | Family member information |
| `/families/mine/location/{userId}` | Child GPS location |
| `/people/{userId}/apps` | Installed apps list |
| `/people/{userId}/apps:updateRestrictions` | Block or unblock apps, set per-app limits, remove app limits, or mark apps as unlimited |
| `/people/{userId}/appsandusage` | App usage data |
| `/people/{userId}/devices` | Device metadata, including device timezone when exposed |
| `/people/{userId}/timeLimitOverrides:batchCreate` | Lock or unlock devices, add time bonuses, and apply today-only time-limit overrides |
| `/people/{userId}/timeLimitOverride/{id}?$httpMethod=DELETE` | Cancel time bonuses and remove supported overrides |
| `/people/{userId}/appliedTimeLimits` | Current time limits, active restrictions, and lock states |
| `/people/{userId}/timeLimit` | Time-limit rules, schedules, and revision data |
| `/people/{userId}/timeLimit:update` | Enable or disable bedtime and daily limits; update recurring bedtime and daily-limit schedules |

For deeper endpoint notes, response shapes, and parser details, see [Google Family Link API Analysis](GOOGLE_FAMILY_LINK_API_ANALYSIS.md).
