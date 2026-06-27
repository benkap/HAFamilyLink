# Troubleshooting

Start with the Home Assistant logs and the auth service logs. Most issues are either expired Google cookies, an unreachable auth service, or a Family Link API response shape that changed.

## 401 Authentication Errors

Symptoms:

- Logs show `401 Unauthorized`
- Entities become unavailable after working before

Fix:

1. Verify the Family Link Auth add-on or standalone auth container is running.
2. Check the cookies API from the Home Assistant host with the auth key: `curl -H 'X-API-Key: <key>' http://localhost:8099/api/cookies`
3. For add-on file fallback, check that `/share/familylink/cookies.enc` and `/share/familylink/.key` exist.
4. Restart the auth service and authenticate again.
5. Reload the integration in Home Assistant.

## Cookies Expired

Symptoms:

- Logs mention an expired session.
- Re-authentication is requested.

Fix:

1. Open the auth service Web UI on port `8099`.
2. Start authentication.
3. Complete Google login in the noVNC browser.
4. Wait for the auth service to save fresh cookies.
5. Reload the integration if it does not recover automatically.

## Lock State Not Updating

Symptoms:

- Home Assistant does not match the Family Link app.
- Device switch state looks stale.

Fix:

1. Check Home Assistant logs for API errors.
2. Confirm the supervised device is online.
3. Wait for the next update cycle; the default is 5 minutes.
4. Lock or unlock the device in the Family Link app to confirm Google is accepting the change.
5. Reload the integration if the state still does not update.

## Bedtime Or School Time Not Detected

Symptoms:

- Bedtime or school time binary sensors stay off.
- Schedule sensors do not match the expected day.

Fix:

1. Confirm the schedule exists and is enabled in the Family Link app.
2. Check entity attributes for `bedtime_start`, `bedtime_end`, `schooltime_start`, or `schooltime_end`.
3. Confirm the schedule is enabled for the current weekday.
4. Check the integration's `schedule_timezone` option.
5. If `schedule_timezone` is blank, confirm Home Assistant's timezone matches the child's schedule timezone.

## Sensors Show Not Configured Or Unavailable

Common causes:

- Old entities left behind after an upgrade.
- No app usage data exists for the current day.
- Google returned a transient API error.

Fix:

1. Delete stale entities from the Home Assistant UI.
2. Wait until the child has app usage data for the day.
3. Check logs for transient Google API errors.
4. Reload the integration after fixing auth or stale entities.

## Standalone Docker Cannot Connect

Symptoms:

- Home Assistant Core or Container cannot reach the auth service.
- Setup fails when using a manual URL.

Fix:

1. Confirm the auth container is running.
2. Confirm port `8099` is reachable from the Home Assistant container or host.
3. Read the generated key from the auth container data directory, usually `./data/api_key`.
4. Use the auth service URL that is valid from Home Assistant's network, not just your laptop.
5. Append the key to the integration URL as `?api_key=<key>`.
6. See [Docker Standalone Guide](DOCKER_STANDALONE.md) for the supported flow.

## Standalone Container Shows Unhealthy

Symptoms:

- Docker, Dozzle, or Portainer shows the container as unhealthy.
- The auth service still answers `/api/health`.
- Container logs mention `curl` is not found.

Fix:

1. Remove any compose healthcheck override that runs `curl`.
2. Use the image default healthcheck, or set `test: ["CMD", "familylink-healthcheck"]`.
3. Recreate the container.
