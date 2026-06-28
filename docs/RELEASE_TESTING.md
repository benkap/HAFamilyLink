# Release Testing

This page covers the local release checks that need a real Google login. CI still
runs the normal unit, HACS, hassfest, Docker build, Trivy, and dependency checks;
these E2E checks are for the final release-bump gate.

## Setup

Create a release tooling environment with Python 3.11 or newer. CI currently
uses Python 3.12; on this Mac, `/opt/homebrew/bin/python3` is the safe choice.

```bash
/opt/homebrew/bin/python3 -m venv .venv-release
.venv-release/bin/python -m pip install -r requirements-release.txt
```

Docker Desktop must be running for the sidecar test.

## Required: Docker Sidecar E2E

Run this before every release bump:

```bash
.venv-release/bin/python scripts/release_e2e.py sidecar
```

By default the harness builds the standalone auth image from the current checkout,
starts an isolated Docker network, runs a standalone auth sidecar, runs a
throwaway Home Assistant Container, installs the local integration by copying
`custom_components/familylink`, and configures Home Assistant through the config
flow API.

The only manual step is Google authentication. The harness starts the auth
session itself; use the printed noVNC URL and do not click **Start
Authentication** in the auth service Web UI during the harness run. If you do
click it, the Web UI may show a harmless start error because the session is
already running.

```text
http://127.0.0.1:16080/vnc.html?autoconnect=true&password=familylink
```

Complete the Google login there. The script continues once the auth container
saves cookies.

For post-publish verification against the published image instead of a local
build:

```bash
.venv-release/bin/python scripts/release_e2e.py sidecar \
  --image ghcr.io/benkap/familylink-auth:standalone
```

The check passes only if:

- the auth service health endpoint returns healthy;
- unauthenticated `/api/cookies` returns `403`;
- authenticated `/api/cookies` returns saved Google cookies;
- the Family Link config entry is loaded;
- Family Link services are registered;
- Family Link entities are created.

Successful runs remove the temporary containers, network, data directory, and
any Docker images that the harness introduced. Images that already existed
before the run are left alone. Use `--keep-on-failure` to keep harness-owned
resources for debugging.

A passing sidecar run prints a compact JSON summary with the image version,
Home Assistant version, cookie count, loaded config-entry state, Family Link
service count, and Family Link entity IDs.

## Optional: HAOS Add-on E2E

The HAOS test proves the add-on/runtime path. It intentionally does not use HACS;
HACS is a distribution-path test, not a requirement for HAOS runtime support.

The harness will only touch a UTM VM with this exact name:

```text
HAFamilyLink-HAOS-E2E
```

The VM must be stopped. The script starts it with UTM disposable mode, so changes
are discarded when the VM is killed. By default, the harness kills the disposable
VM on success or failure and makes a best-effort attempt to close the UTM viewer
window. A keyboard interrupt leaves the disposable VM running for debugging. Use
`--keep-on-failure` to leave a failed HAOS VM running too.

Run:

```bash
.venv-release/bin/python scripts/release_e2e.py haos \
  --vm-name HAFamilyLink-HAOS-E2E
```

The HAOS flow:

- discovers the VM IP through `utmctl ip-address`;
- creates or logs into the Home Assistant user;
- installs the official Terminal & SSH add-on temporarily;
- copies `custom_components/familylink` into `/config/custom_components`;
- restarts Home Assistant Core;
- adds the HAFamilyLink add-on repository through the Supervisor WebSocket API;
- discovers the Supervisor-generated HAFamilyLink add-on slug by suffix;
- installs and starts the HAFamilyLink auth add-on;
- pauses only for Google auth through noVNC;
- configures the integration through auto-detect;
- verifies services and entities.

Use `--keep-on-failure` to keep local temp files and leave the disposable VM
running after a failure. If you interrupt a run and want to stop the VM manually:

```bash
/Applications/UTM.app/Contents/MacOS/utmctl stop --hide HAFamilyLink-HAOS-E2E --kill
```

A passing HAOS run prints the same integration summary as the sidecar run, plus
the UTM VM name, HAOS IP, and discovered Supervisor add-on slug.

## Useful Options

- `--google-timeout 1200`: give yourself more time for Google auth. HAOS add-on
  configuration is capped at 600 seconds by the add-on schema; the harness still
  waits for the full requested timeout.
- `--keep-on-failure`: keep failed-run containers/temp files.
- `--keep-always`: keep resources even after a passing run.
- `--schedule-timezone Asia/Jerusalem`: timezone used in the integration config.
- `--ha-username` and `--ha-password`: credentials for non-fresh HA instances.
- `--familylink-addon-slug`: exact HAOS add-on slug override, only if discovery fails.

## Interpreting Failures

- Port collision: another service is already using the requested local port.
- Missing cookies: Google auth did not finish, or the auth browser timed out.
- `403` from `/api/cookies` after auth: the integration URL has the wrong API key.
- Config entry not loaded: Home Assistant could not initialize the integration.
- No entities: the integration loaded but did not find supervised Family Link data.
- Wrong/running UTM VM: HAOS mode refuses to touch anything except the exact stopped
  test VM.

## VM Bootstrap Follow-up

The first version expects a prepared UTM VM. A later helper can automate template
creation on macOS arm64 by downloading the official HAOS aarch64 image, using
UTM's bundled `qemu-img`, generating a `.utm` bundle named
`HAFamilyLink-HAOS-E2E`, and requiring explicit confirmation before registering
or deleting any VM.
