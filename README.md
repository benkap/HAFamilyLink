# <img src="custom_components/familylink/brand/icon.png" alt="Google Family Link Extended icon" width="42"> Google Family Link Extended <img src="https://brands.home-assistant.io/familylink/icon.png" alt="Google Family Link icon" width="30">

[![GitHub Release][releases-shield]][releases]
[![HACS][hacsbadge]][hacs]
[![License][license-shield]][license]

Unofficial Home Assistant integration for Google Family Link.

This fork builds on [noiwid/HAFamilyLink](https://github.com/noiwid/HAFamilyLink) and keeps the same Home Assistant domain (`familylink`). It is a replacement for the original integration, not something to install beside it.

> If you only need the original behavior, start with [noiwid/HAFamilyLink](https://github.com/noiwid/HAFamilyLink). This fork is for people who want more schedule visibility, schedule editing, app controls, and standalone auth hardening.

## Docs

- [Installation Guide](docs/INSTALL.md)
- [Docker Standalone Guide](docs/DOCKER_STANDALONE.md)
- [Services](docs/SERVICES.md)
- [Example Automations](docs/AUTOMATIONS.md)
- [Advanced Reference](docs/REFERENCE.md)
- [Architecture](docs/ARCHITECTURE.md)
- [Troubleshooting](docs/TROUBLESHOOTING.md)
- [Changelog](CHANGELOG.md)
- [Contributing](CONTRIBUTING.md)

## Install And Configure

For the full walkthrough, use the [Installation Guide](docs/INSTALL.md).

### Home Assistant OS / Supervised

1. Install the Family Link Auth add-on:

[![Open your Home Assistant instance and show the add add-on repository dialog with a specific repository URL pre-filled.](https://my.home-assistant.io/badges/supervisor_add_addon_repository.svg)](https://my.home-assistant.io/redirect/supervisor_add_addon_repository/?repository_url=https%3A%2F%2Fgithub.com%2Fbenkap%2FHAFamilyLink)

2. Install the integration with HACS:

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=benkap&repository=HAFamilyLink&category=integration)

3. In Home Assistant, go to **Settings > Devices & Services > Add Integration**, search for **Family Link**, and finish the setup flow.

### Home Assistant Core / Container

Run the auth service as a standalone Docker container, then point the integration at it. If the container generates an API key, append it to the auth URL as `?api_key=<key>`. See the [Docker Standalone Guide](docs/DOCKER_STANDALONE.md).

### Configuration

Configuration is done in the Home Assistant UI. YAML configuration is not supported.

**Main options:**

- **Name**: integration display name
- **Update interval**: how often to fetch data; default is 300 seconds
- **Timeout**: API request timeout; default is 30 seconds
- **GPS location tracking**: optional and disabled by default
- **Schedule timezone**: optional override for schedule day calculations

To change options later, open **Settings > Devices & Services**, find Family Link, and click **Configure**.

## ⚠️ Important

This project uses unofficial, reverse-engineered Google Family Link endpoints. Use it at your own risk. Google can change or remove this behavior without notice, and this project is not affiliated with Google.

GPS location tracking is opt-in. Each location poll may notify the child's device.

## What This Fork Adds

- Recurring bedtime schedule editing with `familylink.set_bedtime_schedule`
- Recurring daily-limit schedule editing with `familylink.set_daily_limit_schedule`
- Schedule sensors for bedtime, school time, and daily limits
- Daily-limit schedule parsing and readback
- Timezone-aware schedule calculations through `schedule_timezone`
- Better bedtime readback attributes for weekly schedules vs. one-day overrides
- Hardened standalone auth-container behavior

## Features

- Lock or unlock supervised devices from Home Assistant
- Enable or disable bedtime, school time, and daily limits
- Apply one-day bedtime and daily-limit overrides
- Add or cancel time bonuses
- Monitor screen time, remaining time, daily limits, and top-used apps
- Block or unblock apps by Android package name
- Set per-app daily limits or mark apps as unlimited
- Optionally track GPS location and battery level from the Family Link location source device
- Expose supervised child, device, and family profile details

For the full entity list, see [Advanced Reference](docs/REFERENCE.md).

## Limits

Not currently supported:

- Weekly school time schedule editing
- Parent approval or app install approval workflows
- Website allowlists or blocklists
- A built-in app picker; app-control services need Android package names

## Support

- [Report an issue](https://github.com/benkap/HAFamilyLink/issues)
- [Request a feature](https://github.com/benkap/HAFamilyLink/issues/new)

## Credits

- Huge thanks to [@noiwid](https://github.com/noiwid) for the original HAFamilyLink project.
- Based on work by [@tducret](https://github.com/tducret/familylink), which documented Family Link API endpoints.
- Inspired by [@Vortitron's HAFamilyLink](https://github.com/Vortitron/HAFamilyLink).
- noVNC integration inspired by [@jnctech's fork](https://github.com/jnctech/HAFamilyLink).
- Thanks to the Home Assistant community for integration examples and best practices.

## License

This project is licensed under the MIT License. See [LICENSE](LICENSE).

## ⚠️ Legal

This is an unofficial integration and is not affiliated with, endorsed by, or connected to Google LLC. All product names, logos, and brands are property of their respective owners.

[releases-shield]: https://img.shields.io/github/release/benkap/HAFamilyLink.svg?style=for-the-badge
[releases]: https://github.com/benkap/HAFamilyLink/releases
[license-shield]: https://img.shields.io/github/license/benkap/HAFamilyLink.svg?style=for-the-badge
[license]: LICENSE
[hacsbadge]: https://img.shields.io/badge/HACS-Custom-orange.svg?style=for-the-badge
[hacs]: https://github.com/hacs/integration
