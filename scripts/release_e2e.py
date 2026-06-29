#!/usr/bin/env python3
"""Interactive release E2E checks for HAFamilyLink.

The harness automates the local Home Assistant setup and pauses only for the
Google login that cannot be safely automated.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import re
import secrets
import shutil
import socket
import subprocess
import sys
import tarfile
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple, Union
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parents[1]
FAMILYLINK_COMPONENT = ROOT / "custom_components" / "familylink"
DEFAULT_HA_IMAGE = "ghcr.io/home-assistant/home-assistant:stable"
DEFAULT_HAOS_VM_NAME = "HAFamilyLink-HAOS-E2E"
DEFAULT_HAFAMILYLINK_REPO = "https://github.com/benkap/HAFamilyLink"
DEFAULT_HAFAMILYLINK_ADDON_SLUG_SUFFIX = "familylink-playwright"
DEFAULT_SSH_ADDON_SLUG = "core_ssh"
DEFAULT_UTMCTL = "/Applications/UTM.app/Contents/MacOS/utmctl"
HAOS_ADDON_AUTH_TIMEOUT_MIN = 60
HAOS_ADDON_AUTH_TIMEOUT_MAX = 600
MIN_PYTHON = (3, 11)

if sys.version_info < MIN_PYTHON:
    raise SystemExit(
        "scripts/release_e2e.py requires Python 3.11 or newer. "
        "On this Mac, use /opt/homebrew/bin/python3 or a release-test venv "
        "created from a modern Python."
    )

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(line_buffering=True)
    sys.stderr.reconfigure(line_buffering=True)


class E2EError(RuntimeError):
    """Release E2E failure."""


@dataclass
class HaToken:
    access_token: str
    refresh_token: Optional[str]
    client_id: str


def require_requests():
    try:
        import requests  # type: ignore[import-not-found]
    except ImportError as err:  # pragma: no cover - depends on local env
        raise E2EError(
            "Missing release dependency: requests. Run: "
            "python -m pip install -r requirements-release.txt"
        ) from err
    return requests


def require_websocket():
    try:
        import websocket  # type: ignore[import-not-found]
    except ImportError as err:  # pragma: no cover - depends on local env
        raise E2EError(
            "Missing release dependency: websocket-client. Run: "
            "python -m pip install -r requirements-release.txt"
        ) from err
    return websocket


def run(
    cmd: List[str],
    *,
    cwd: Path = ROOT,
    capture: bool = True,
    check: bool = True,
    input_bytes: Optional[bytes] = None,
) -> subprocess.CompletedProcess:
    """Run a command with consistent error reporting."""
    result = subprocess.run(
        cmd,
        cwd=cwd,
        input=input_bytes,
        capture_output=capture,
        text=input_bytes is None,
        check=False,
    )
    if check and result.returncode != 0:
        stdout = result.stdout if isinstance(result.stdout, str) else ""
        stderr = result.stderr if isinstance(result.stderr, str) else ""
        raise E2EError(
            "Command failed: "
            + " ".join(cmd)
            + f"\nexit={result.returncode}\nstdout={stdout}\nstderr={stderr}"
        )
    return result  # type: ignore[return-value]


def ensure_tool(name: str) -> None:
    if shutil.which(name) is None:
        raise E2EError(f"Missing required tool: {name}")


def ensure_port_free(port: int, host: str = "127.0.0.1") -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((host, port))
        except OSError as err:
            raise E2EError(f"Port {host}:{port} is already in use") from err


def compact_json(data: Dict[str, Any]) -> str:
    return json.dumps(data, indent=2, sort_keys=True)


def read_version() -> str:
    return json.loads((ROOT / "familylink-playwright" / "config.json").read_text())["version"]


def copy_integration(target_config: Path) -> None:
    target = target_config / "custom_components" / "familylink"
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(
        FAMILYLINK_COMPONENT,
        target,
        ignore=shutil.ignore_patterns("__pycache__"),
    )


def wait_for_http(
    url: str,
    *,
    expected_statuses: Optional[Set[int]] = None,
    timeout: int = 180,
    request_timeout: int = 5,
    label: str = "HTTP endpoint",
) -> None:
    requests = require_requests()
    expected_statuses = expected_statuses or {200}
    deadline = time.monotonic() + timeout
    next_report = time.monotonic() + 15
    last_error = ""
    while time.monotonic() < deadline:
        try:
            response = requests.get(url, timeout=request_timeout)
            if response.status_code in expected_statuses:
                return
            last_error = f"HTTP {response.status_code}: {response.text[:200]}"
        except Exception as err:  # noqa: BLE001 - report final connection problem
            last_error = str(err)
        if time.monotonic() >= next_report:
            remaining = max(0, int(deadline - time.monotonic()))
            print(f"Still waiting for {label} at {url} ({remaining}s left): {last_error}")
            next_report = time.monotonic() + 15
        time.sleep(2)
    raise E2EError(f"{label} did not become ready at {url}: {last_error}")


def request_json(
    method: str,
    url: str,
    *,
    headers: Optional[Dict[str, str]] = None,
    json_body: Optional[Dict[str, Any]] = None,
    data: Optional[Dict[str, str]] = None,
    timeout: int = 30,
    allow_statuses: Optional[Set[int]] = None,
) -> Tuple[int, Any]:
    requests = require_requests()
    response = requests.request(
        method,
        url,
        headers=headers,
        json=json_body,
        data=data,
        timeout=timeout,
    )
    allow_statuses = allow_statuses or {200}
    try:
        payload = response.json()
    except ValueError:
        payload = response.text
    if response.status_code not in allow_statuses:
        raise E2EError(f"{method} {url} returned {response.status_code}: {payload}")
    return response.status_code, payload


def ha_headers(token: HaToken) -> Dict[str, str]:
    return {
        "Authorization": f"Bearer {token.access_token}",
        "Content-Type": "application/json",
    }


def local_login(ha_url: str, username: str, password: str) -> HaToken:
    client_id = f"{ha_url.rstrip('/')}/"
    redirect_uri = f"{client_id}?auth_callback=1"
    _, providers = request_json("GET", f"{ha_url}/auth/providers")
    handler: Union[str, List[Any]] = "homeassistant"
    for provider in providers.get("providers", []):
        if provider.get("type") == "homeassistant":
            handler = ["homeassistant", provider.get("id")]
            break

    _, flow = request_json(
        "POST",
        f"{ha_url}/auth/login_flow",
        json_body={
            "client_id": client_id,
            "handler": handler,
            "redirect_uri": redirect_uri,
        },
    )
    _, result = request_json(
        "POST",
        f"{ha_url}/auth/login_flow/{flow['flow_id']}",
        json_body={
            "client_id": client_id,
            "username": username,
            "password": password,
        },
    )
    auth_code = result.get("result")
    if not auth_code:
        raise E2EError(f"Home Assistant login did not return an auth code: {result}")
    _, token = request_json(
        "POST",
        f"{ha_url}/auth/token",
        data={
            "grant_type": "authorization_code",
            "code": auth_code,
            "client_id": client_id,
        },
    )
    return HaToken(
        access_token=token["access_token"],
        refresh_token=token.get("refresh_token"),
        client_id=client_id,
    )


def onboard_or_login(ha_url: str, username: str, password: str) -> HaToken:
    client_id = f"{ha_url.rstrip('/')}/"
    status_code, status = request_json(
        "GET",
        f"{ha_url}/api/onboarding",
        allow_statuses={200, 401},
    )
    if status_code == 401:
        print("Home Assistant is already onboarded; logging in with configured credentials.")
        return local_login(ha_url, username, password)
    user_step = next((step for step in status if step.get("step") == "user"), None)
    if user_step and not user_step.get("done"):
        _, result = request_json(
            "POST",
            f"{ha_url}/api/onboarding/users",
            json_body={
                "name": "HAFamilyLink E2E",
                "username": username,
                "password": password,
                "client_id": client_id,
                "language": "en",
            },
            timeout=60,
        )
        _, token = request_json(
            "POST",
            f"{ha_url}/auth/token",
            data={
                "grant_type": "authorization_code",
                "code": result["auth_code"],
                "client_id": client_id,
            },
        )
        return HaToken(
            access_token=token["access_token"],
            refresh_token=token.get("refresh_token"),
            client_id=client_id,
        )
    return local_login(ha_url, username, password)


def ha_get(ha_url: str, token: HaToken, path: str) -> Any:
    _, payload = request_json("GET", f"{ha_url}{path}", headers=ha_headers(token))
    return payload


def ha_ws_call(
    ha_url: str,
    token: HaToken,
    message: Dict[str, Any],
    *,
    timeout: Optional[int] = 60,
    allow_error: bool = False,
    allow_disconnect: bool = False,
) -> Any:
    websocket = require_websocket()
    parsed = urlparse(ha_url)
    scheme = "wss" if parsed.scheme == "https" else "ws"
    ws_url = f"{scheme}://{parsed.netloc}/api/websocket"
    ws = websocket.create_connection(ws_url, timeout=timeout or 60)
    try:
        auth_required = json.loads(ws.recv())
        if auth_required.get("type") != "auth_required":
            raise E2EError(f"Unexpected HA WebSocket greeting: {auth_required}")
        ws.send(json.dumps({"type": "auth", "access_token": token.access_token}))
        auth_result = json.loads(ws.recv())
        if auth_result.get("type") != "auth_ok":
            raise E2EError(f"Home Assistant WebSocket auth failed: {auth_result}")

        ws.send(json.dumps({"id": 1, **message}))
        while True:
            raw_message = ws.recv()
            if not raw_message:
                if allow_disconnect:
                    return {}
                raise E2EError(f"Home Assistant WebSocket closed during {message}")
            result = json.loads(raw_message)
            if result.get("id") != 1:
                continue
            if result.get("success"):
                return result.get("result", {})
            if allow_error:
                return {"error": result.get("error")}
            raise E2EError(f"Home Assistant WebSocket command failed: {result}")
    finally:
        ws.close()


def configure_familylink_manual(
    ha_url: str,
    token: HaToken,
    *,
    auth_url: str,
    title: str,
    schedule_timezone: str,
) -> Dict[str, Any]:
    _, flow = request_json(
        "POST",
        f"{ha_url}/api/config/config_entries/flow",
        headers=ha_headers(token),
        json_body={"handler": "familylink", "show_advanced_options": False},
        timeout=60,
    )
    flow_id = flow["flow_id"]
    _, step = request_json(
        "POST",
        f"{ha_url}/api/config/config_entries/flow/{flow_id}",
        headers=ha_headers(token),
        json_body={"next_step_id": "manual_url"},
        timeout=60,
    )
    if step.get("step_id") != "manual_url":
        raise E2EError(f"Expected manual_url step, got: {step}")
    _, step = request_json(
        "POST",
        f"{ha_url}/api/config/config_entries/flow/{flow_id}",
        headers=ha_headers(token),
        json_body={"auth_url": auth_url},
        timeout=90,
    )
    if step.get("step_id") != "configure":
        raise E2EError(f"Expected configure step after auth URL, got: {step}")
    _, result = request_json(
        "POST",
        f"{ha_url}/api/config/config_entries/flow/{flow_id}",
        headers=ha_headers(token),
        json_body={
            "name": title,
            "update_interval": 60,
            "timeout": 30,
            "enable_location_tracking": False,
            "schedule_timezone": schedule_timezone,
        },
        timeout=120,
    )
    if result.get("type") != "create_entry":
        raise E2EError(f"Expected create_entry, got: {result}")
    return result


def configure_familylink_auto(
    ha_url: str,
    token: HaToken,
    *,
    title: str,
    schedule_timezone: str,
) -> Dict[str, Any]:
    _, flow = request_json(
        "POST",
        f"{ha_url}/api/config/config_entries/flow",
        headers=ha_headers(token),
        json_body={"handler": "familylink", "show_advanced_options": False},
        timeout=60,
    )
    flow_id = flow["flow_id"]
    _, step = request_json(
        "POST",
        f"{ha_url}/api/config/config_entries/flow/{flow_id}",
        headers=ha_headers(token),
        json_body={"next_step_id": "auto_detect"},
        timeout=90,
    )
    if step.get("step_id") != "configure":
        raise E2EError(f"Expected configure step after auto-detect, got: {step}")
    _, result = request_json(
        "POST",
        f"{ha_url}/api/config/config_entries/flow/{flow_id}",
        headers=ha_headers(token),
        json_body={
            "name": title,
            "update_interval": 60,
            "timeout": 30,
            "enable_location_tracking": False,
            "schedule_timezone": schedule_timezone,
        },
        timeout=120,
    )
    if result.get("type") != "create_entry":
        raise E2EError(f"Expected create_entry, got: {result}")
    return result


def family_like_states(states: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    found = []
    for state in states:
        blob = json.dumps(state, sort_keys=True).lower()
        if "familylink" in blob or "family link" in blob or "google family" in blob:
            found.append(state)
    return found


def familylink_registry_entries(
    ha_url: str,
    token: HaToken,
    entry_id: Optional[str],
) -> List[Dict[str, Any]]:
    registry = ha_ws_call(ha_url, token, {"type": "config/entity_registry/list"})
    if isinstance(registry, dict):
        entities = registry.get("entities", [])
    else:
        entities = registry
    if not isinstance(entities, list):
        return []
    return [
        entity
        for entity in entities
        if isinstance(entity, dict)
        and (
            entity.get("platform") == "familylink"
            or (entry_id is not None and entity.get("config_entry_id") == entry_id)
        )
    ]


def verify_familylink(ha_url: str, token: HaToken, *, timeout: int = 180) -> Dict[str, Any]:
    deadline = time.monotonic() + timeout
    family_states: List[Dict[str, Any]] = []
    states: List[Dict[str, Any]] = []
    last_summary: Dict[str, Any] = {}
    while time.monotonic() < deadline:
        config = ha_get(ha_url, token, "/api/config")
        services = ha_get(ha_url, token, "/api/services")
        entries = ha_get(ha_url, token, "/api/config/config_entries/entry?domain=familylink")
        service_domain = next(
            (domain for domain in services if domain.get("domain") == "familylink"),
            {},
        )
        service_names = sorted((service_domain.get("services") or {}).keys())
        entry = entries[0] if entries else {}
        entry_id = entry.get("entry_id")
        registry_entries = familylink_registry_entries(ha_url, token, entry_id)
        registry_ids = {entity.get("entity_id") for entity in registry_entries}
        states = ha_get(ha_url, token, "/api/states")
        family_states = [
            state
            for state in states
            if state.get("entity_id") in registry_ids
        ] or family_like_states(states)
        last_summary = {
            "config_entry_state": entry.get("state"),
            "familylink_service_count": len(service_names),
            "familylink_registry_entity_count": len(registry_entries),
            "familylink_state_count": len(family_states),
        }
        if (
            entry.get("state") == "loaded"
            and service_names
            and registry_entries
            and family_states
        ):
            break
        time.sleep(5)
    else:
        raise E2EError(
            "Family Link verification did not reach loaded/services/entities: "
            f"{compact_json(last_summary)}"
        )

    return {
        "ha_version": config.get("version"),
        "component_familylink_loaded": "familylink" in (config.get("components") or []),
        "config_entry_state": entry.get("state"),
        "config_entry_title": entry.get("title"),
        "familylink_service_count": len(service_names),
        "familylink_services": service_names,
        "familylink_entity_count": len(registry_entries),
        "familylink_state_count": len(family_states),
        "familylink_entities": [
            {
                "entity_id": entity.get("entity_id"),
                "name": entity.get("name") or entity.get("original_name"),
                "device_id": entity.get("device_id"),
            }
            for entity in registry_entries[:25]
        ],
        "total_state_count": len(states),
    }


def wait_for_auth_cookies(
    api_url: str,
    *,
    api_key: Optional[str],
    timeout: int,
    label: str,
) -> Tuple[int, Optional[Dict[str, Any]]]:
    print(f"\nWaiting for Google auth cookies ({label}).")
    print("Complete the Google login in noVNC. The harness will continue automatically.")
    requests = require_requests()
    deadline = time.monotonic() + timeout
    last_status: Union[str, int] = "not checked"
    while time.monotonic() < deadline:
        with contextlib.suppress(Exception):
            check = requests.get(f"{api_url}/api/cookies/check", timeout=5)
            if check.status_code == 200 and check.json().get("exists") is True:
                headers = {"X-API-Key": api_key} if api_key else {}
                cookies = requests.get(f"{api_url}/api/cookies", headers=headers, timeout=10)
                last_status = cookies.status_code
                if cookies.status_code == 200:
                    payload = cookies.json()
                    return int(payload.get("count", len(payload.get("cookies", [])))), payload
        time.sleep(5)
    raise E2EError(f"Timed out waiting for cookies from {api_url}; last status={last_status}")


def docker_image_info(image: str) -> Dict[str, Any]:
    result = run(
        [
            "docker",
            "image",
            "inspect",
            image,
            "--format",
            "{{.Id}} {{.Size}} {{index .Config.Labels \"org.opencontainers.image.version\"}}",
        ]
    )
    parts = result.stdout.strip().split()
    return {
        "id": parts[0] if parts else None,
        "size_bytes": int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else None,
        "label_version": parts[2] if len(parts) > 2 else None,
    }


def docker_rm(name: str) -> None:
    run(["docker", "rm", "-f", name], capture=True, check=False)


def docker_network_rm(name: str) -> None:
    run(["docker", "network", "rm", name], capture=True, check=False)


def docker_image_rm(image: str) -> None:
    run(["docker", "image", "rm", image], capture=True, check=False)


def docker_image_exists(image: str) -> bool:
    return run(["docker", "image", "inspect", image], capture=True, check=False).returncode == 0


def run_sidecar(args: argparse.Namespace) -> Dict[str, Any]:
    ensure_tool("docker")
    for port in (args.api_port, args.vnc_port, args.ha_port):
        ensure_port_free(port)

    run_id = secrets.token_hex(4)
    network = f"hafl-e2e-{run_id}"
    auth_name = f"hafl-e2e-auth-{run_id}"
    ha_name = f"hafl-e2e-ha-{run_id}"
    temp_root = Path(tempfile.mkdtemp(prefix="hafl-release-e2e."))
    auth_data = temp_root / "auth-data"
    ha_config = temp_root / "ha-config"
    auth_data.mkdir()
    ha_config.mkdir()
    image = args.image
    auth_image_existed = docker_image_exists(image) if image else False
    ha_image_existed = docker_image_exists(args.ha_image)
    built_image = False
    failed = True

    def cleanup_image(image_ref: str, reason: str) -> None:
        print(f"Removing {reason}: {image_ref}")
        docker_image_rm(image_ref)

    def cleanup() -> None:
        if args.keep_always or (failed and args.keep_on_failure):
            print(f"Kept sidecar E2E resources. Temp root: {temp_root}")
            print(f"Containers: {auth_name}, {ha_name}; network: {network}")
            return
        docker_rm(auth_name)
        docker_rm(ha_name)
        docker_network_rm(network)
        if image is not None and (built_image or not auth_image_existed):
            cleanup_image(image, "temporary auth image")
        if not ha_image_existed:
            cleanup_image(args.ha_image, "temporary Home Assistant image")
        shutil.rmtree(temp_root, ignore_errors=True)

    try:
        copy_integration(ha_config)
        (ha_config / "configuration.yaml").write_text("default_config:\n", encoding="utf-8")

        if image is None:
            image = f"hafamilylink-release-e2e:{read_version()}-{run_id}"
            print(f"Building standalone image from current checkout: {image}")
            run(
                [
                    "docker",
                    "build",
                    "-f",
                    "familylink-playwright/Dockerfile.standalone",
                    "-t",
                    image,
                    "familylink-playwright",
                ]
            )
            built_image = True
        else:
            print(f"Using standalone image: {image}")

        run(["docker", "network", "create", network])
        run(
            [
                "docker",
                "run",
                "-d",
                "--name",
                auth_name,
                "--network",
                network,
                "--network-alias",
                "familylink-auth",
                "--shm-size=2gb",
                "-p",
                f"127.0.0.1:{args.api_port}:8099",
                "-p",
                f"127.0.0.1:{args.vnc_port}:6080",
                "-v",
                f"{auth_data}:/share/familylink:rw",
                "-e",
                "LOG_LEVEL=info",
                "-e",
                f"AUTH_TIMEOUT={args.google_timeout}",
                "-e",
                "SESSION_DURATION=86400",
                "-e",
                f"VNC_PASSWORD={args.vnc_password}",
                "-e",
                "LANGUAGE=en-US",
                "-e",
                f"TIMEZONE={args.timezone}",
                "--restart",
                "no",
                image,
            ]
        )
        run(
            [
                "docker",
                "run",
                "-d",
                "--name",
                ha_name,
                "--network",
                network,
                "-p",
                f"127.0.0.1:{args.ha_port}:8123",
                "-v",
                f"{ha_config}:/config",
                "-e",
                f"TZ={args.timezone}",
                "--restart",
                "no",
                args.ha_image,
            ]
        )

        api_url = f"http://127.0.0.1:{args.api_port}"
        ha_url = f"http://127.0.0.1:{args.ha_port}"
        wait_for_http(f"{api_url}/api/health", timeout=180, label="auth service")
        wait_for_http(f"{ha_url}/api/", expected_statuses={200, 401}, timeout=240, label="HA")

        status, health = request_json("GET", f"{api_url}/api/health")
        if status != 200:
            raise E2EError(f"Unexpected health status: {health}")
        api_key_path = auth_data / "api_key"
        if not api_key_path.exists():
            raise E2EError(f"Auth API key was not generated at {api_key_path}")
        api_key = api_key_path.read_text(encoding="utf-8").strip()
        unauth_status, _ = request_json(
            "GET",
            f"{api_url}/api/cookies",
            allow_statuses={200, 403, 404},
        )
        if unauth_status != 403:
            raise E2EError(
                f"Expected unauthenticated /api/cookies to return 403, got {unauth_status}"
            )

        _, auth_start = request_json("POST", f"{api_url}/api/auth/start", timeout=60)
        print("\nGoogle auth started.")
        print(f"Session: {auth_start.get('session_id')}")
        print(
            f"Auth UI: {api_url} (diagnostics only; Start Authentication is already "
            "running and clicking it may show a harmless error)"
        )
        print(
            "noVNC: "
            f"http://127.0.0.1:{args.vnc_port}/vnc.html?autoconnect=true"
        )
        print("noVNC login: enter the configured --vnc-password value if prompted.")
        cookie_count, _ = wait_for_auth_cookies(
            api_url,
            api_key=api_key,
            timeout=args.google_timeout,
            label="sidecar",
        )

        token = onboard_or_login(ha_url, args.ha_username, args.ha_password)
        configure_familylink_manual(
            ha_url,
            token,
            auth_url=f"http://familylink-auth:8099?api_key={api_key}",
            title="Google Family Link Extended Sidecar E2E",
            schedule_timezone=args.schedule_timezone,
        )
        verification = verify_familylink(ha_url, token, timeout=args.verify_timeout)

        summary = {
            "mode": "sidecar",
            "result": "passed",
            "built_image": built_image,
            "auth_image": image,
            "auth_image_info": docker_image_info(image),
            "auth_health": health,
            "cookie_count": cookie_count,
            "ha_url": ha_url,
            **verification,
        }
        failed = False
        return summary
    finally:
        cleanup()


def list_utm_vms(utmctl: str) -> List[Dict[str, str]]:
    result = run([utmctl, "list"], capture=True)
    vms: List[Dict[str, str]] = []
    for line in result.stdout.splitlines()[1:]:
        parts = line.split(None, 2)
        if len(parts) == 3:
            vms.append({"uuid": parts[0], "status": parts[1], "name": parts[2]})
    return vms


def wait_for_utm_ip(utmctl: str, vm_name: str, timeout: int) -> str:
    deadline = time.monotonic() + timeout
    ip_pattern = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
    while time.monotonic() < deadline:
        result = run([utmctl, "ip-address", "--hide", vm_name], capture=True, check=False)
        if result.returncode == 0:
            for ip in ip_pattern.findall(result.stdout):
                if not ip.startswith("127."):
                    return ip
        time.sleep(5)
    raise E2EError(f"Timed out waiting for an IPv4 address from UTM VM {vm_name!r}")


def start_utm_disposable(utmctl: str, vm_name: str) -> Optional[subprocess.Popen]:
    process = subprocess.Popen(
        [utmctl, "start", "--hide", vm_name, "--disposable"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    time.sleep(5)
    if process.poll() is None:
        print("UTM start command is still attached; continuing while the VM boots.")
        return process
    if process.returncode != 0:
        raise E2EError(f"Failed to start UTM VM {vm_name!r}; exit={process.returncode}")
    return None


def stop_background_process(process: Optional[subprocess.Popen]) -> None:
    if process is None or process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()


def close_utm_vm_window(vm_name: str) -> None:
    script = f"""
tell application "UTM"
    set matchingWindows to every window whose name is {json.dumps(vm_name)}
    repeat with matchingWindow in matchingWindows
        close matchingWindow
    end repeat
    return (count of matchingWindows)
end tell
""".strip()
    result = run(["osascript", "-e", script], capture=True, check=False)
    if result.returncode != 0:
        stderr = result.stderr.strip() if isinstance(result.stderr, str) else ""
        print(f"Could not close UTM VM window {vm_name!r}: {stderr}")


def supervisor_api(
    ha_url: str,
    token: HaToken,
    *,
    endpoint: str,
    method: str = "get",
    data: Optional[Dict[str, Any]] = None,
    timeout: Optional[int] = 60,
    allow_error: bool = False,
    allow_disconnect: bool = False,
) -> Any:
    msg: Dict[str, Any] = {
        "type": "supervisor/api",
        "endpoint": endpoint,
        "method": method,
    }
    if data is not None:
        msg["data"] = data
    if timeout is not None:
        msg["timeout"] = timeout
    return ha_ws_call(
        ha_url,
        token,
        msg,
        timeout=timeout,
        allow_error=allow_error,
        allow_disconnect=allow_disconnect,
    )


def supervisor_data(payload: Any) -> Any:
    if isinstance(payload, dict) and "data" in payload:
        return payload["data"]
    return payload


def discover_familylink_addon_slug(
    ha_url: str,
    token: HaToken,
    *,
    slug_suffix: str,
) -> str:
    store = supervisor_data(
        supervisor_api(ha_url, token, endpoint="/store", method="get", timeout=60)
    )
    addons = store.get("addons", []) if isinstance(store, dict) else []
    matches = [
        addon
        for addon in addons
        if isinstance(addon, dict)
        and (
            addon.get("slug") == slug_suffix
            or str(addon.get("slug", "")).endswith(f"_{slug_suffix}")
        )
    ]
    if len(matches) != 1:
        slugs = sorted(
            str(addon.get("slug"))
            for addon in addons
            if isinstance(addon, dict) and addon.get("slug")
        )
        raise E2EError(
            f"Expected exactly one add-on slug ending with {slug_suffix!r}; "
            f"found {len(matches)}. Available slugs: {slugs}"
        )
    return str(matches[0]["slug"])


def get_addon_info(ha_url: str, token: HaToken, addon_slug: str) -> Dict[str, Any]:
    info = supervisor_api(
        ha_url,
        token,
        endpoint=f"/addons/{addon_slug}/info",
        method="get",
        timeout=60,
    )
    data = supervisor_data(info)
    if not isinstance(data, dict):
        raise E2EError(f"Unexpected add-on info for {addon_slug}: {data}")
    return data


def addon_is_installed(info: Dict[str, Any]) -> bool:
    return (
        info.get("installed") is True
        or info.get("version") is not None
        or info.get("state") in {"stopped", "started"}
    )


def wait_for_addon_installed(
    ha_url: str,
    token: HaToken,
    *,
    addon_slug: str,
    timeout: int = 600,
) -> Dict[str, Any]:
    deadline = time.monotonic() + timeout
    next_report = time.monotonic()
    last_info: Dict[str, Any] = {}
    while time.monotonic() < deadline:
        last_info = get_addon_info(ha_url, token, addon_slug)
        if addon_is_installed(last_info):
            print(
                f"Add-on {addon_slug} is installed "
                f"(state={last_info.get('state')}, version={last_info.get('version')})."
            )
            return last_info
        if time.monotonic() >= next_report:
            remaining = max(0, int(deadline - time.monotonic()))
            print(
                f"Waiting for add-on {addon_slug} to finish installing "
                f"({remaining}s left; state={last_info.get('state')}, "
                f"version={last_info.get('version')}, installed={last_info.get('installed')})"
            )
            next_report = time.monotonic() + 15
        time.sleep(5)
    raise E2EError(
        f"Timed out waiting for add-on {addon_slug} to install: {compact_json(last_info)}"
    )


def wait_for_ssh(host: str, port: int, timeout: int) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(5)
            with contextlib.suppress(OSError):
                sock.connect((host, port))
                return
        time.sleep(3)
    raise E2EError(f"SSH did not become reachable at {host}:{port}")


def make_integration_tar(temp_dir: Path) -> Path:
    archive = temp_dir / "familylink-custom-component.tar.gz"
    with tarfile.open(archive, "w:gz") as tar:
        tar.add(
            FAMILYLINK_COMPONENT,
            arcname="familylink",
            filter=lambda item: None if "__pycache__" in item.name else item,
        )
    return archive


def install_integration_over_ssh(
    *,
    host: str,
    port: int,
    private_key: Path,
    archive: Path,
) -> None:
    ssh_base = [
        "ssh",
        "-i",
        str(private_key),
        "-p",
        str(port),
        "-o",
        "StrictHostKeyChecking=no",
        "-o",
        "UserKnownHostsFile=/dev/null",
        "-o",
        "LogLevel=ERROR",
        f"root@{host}",
    ]
    remote_cmd = "mkdir -p /config/custom_components && tar -xzf - -C /config/custom_components"
    with archive.open("rb") as stream:
        result = subprocess.run(
            [*ssh_base, remote_cmd],
            input=stream.read(),
            capture_output=True,
            check=False,
        )
    if result.returncode != 0:
        raise E2EError(
            "Failed to copy integration through SSH add-on:\n"
            f"stdout={result.stdout.decode(errors='replace')}\n"
            f"stderr={result.stderr.decode(errors='replace')}"
        )


def read_remote_file_over_ssh(
    *,
    host: str,
    port: int,
    private_key: Path,
    path: str,
    timeout: int = 120,
) -> str:
    deadline = time.monotonic() + timeout
    cmd = [
        "ssh",
        "-i",
        str(private_key),
        "-p",
        str(port),
        "-o",
        "StrictHostKeyChecking=no",
        "-o",
        "UserKnownHostsFile=/dev/null",
        "-o",
        "LogLevel=ERROR",
        f"root@{host}",
        f"cat {path}",
    ]
    last_error = ""
    while time.monotonic() < deadline:
        result = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
        last_error = result.stderr.strip() or result.stdout.strip()
        time.sleep(3)
    raise E2EError(f"Could not read {path} over SSH: {last_error}")


def setup_ssh_addon(
    ha_url: str,
    token: HaToken,
    *,
    host: str,
    port: int,
    temp_dir: Path,
    addon_slug: str,
) -> Path:
    ensure_tool("ssh")
    ensure_tool("ssh-keygen")
    key_path = temp_dir / "haos-e2e-ssh-key"
    run(["ssh-keygen", "-t", "ecdsa", "-N", "", "-f", str(key_path), "-C", "hafamilylink-e2e"])
    public_key = key_path.with_suffix(".pub").read_text(encoding="utf-8").strip()

    supervisor_api(
        ha_url,
        token,
        endpoint=f"/addons/{addon_slug}/install",
        method="post",
        timeout=None,
        allow_error=True,
    )
    wait_for_addon_installed(ha_url, token, addon_slug=addon_slug)
    supervisor_api(
        ha_url,
        token,
        endpoint=f"/addons/{addon_slug}/options",
        method="post",
        data={
            "options": {
                "authorized_keys": [public_key],
                "password": "",
                "apks": [],
                "server": {"tcp_forwarding": False},
            },
            "network": {"22/tcp": port},
        },
        timeout=60,
    )
    supervisor_api(
        ha_url,
        token,
        endpoint=f"/addons/{addon_slug}/start",
        method="post",
        timeout=60,
        allow_error=True,
    )
    wait_for_ssh(host, port, 120)
    return key_path


def ensure_familylink_addon(
    ha_url: str,
    token: HaToken,
    *,
    repo_url: str,
    addon_slug: Optional[str],
    addon_slug_suffix: str,
    vnc_password: str,
    google_timeout: int,
    timezone: str,
) -> str:
    supervisor_api(
        ha_url,
        token,
        endpoint="/store/repositories",
        method="post",
        data={"repository": repo_url},
        timeout=None,
        allow_error=True,
    )
    supervisor_api(
        ha_url,
        token,
        endpoint="/store/reload",
        method="post",
        timeout=None,
        allow_error=True,
    )
    if addon_slug is None:
        addon_slug = discover_familylink_addon_slug(
            ha_url,
            token,
            slug_suffix=addon_slug_suffix,
        )
    print(f"Using HAFamilyLink add-on slug: {addon_slug}")
    supervisor_api(
        ha_url,
        token,
        endpoint=f"/addons/{addon_slug}/install",
        method="post",
        timeout=None,
        allow_error=True,
    )
    wait_for_addon_installed(ha_url, token, addon_slug=addon_slug)
    addon_auth_timeout = max(
        HAOS_ADDON_AUTH_TIMEOUT_MIN,
        min(google_timeout, HAOS_ADDON_AUTH_TIMEOUT_MAX),
    )
    if addon_auth_timeout != google_timeout:
        print(
            "Using HAOS add-on auth_timeout="
            f"{addon_auth_timeout}; harness wait remains {google_timeout}s."
        )
    supervisor_api(
        ha_url,
        token,
        endpoint=f"/addons/{addon_slug}/options",
        method="post",
        data={
            "options": {
                "log_level": "info",
                "auth_timeout": addon_auth_timeout,
                "session_duration": 86400,
                "language": "en-US",
                "timezone": timezone,
                "vnc_password": vnc_password,
            }
        },
        timeout=60,
    )
    supervisor_api(
        ha_url,
        token,
        endpoint=f"/addons/{addon_slug}/start",
        method="post",
        timeout=60,
        allow_error=True,
    )
    return addon_slug


def run_haos(args: argparse.Namespace) -> Dict[str, Any]:
    utmctl = args.utmctl
    if not Path(utmctl).exists():
        raise E2EError(f"UTM CLI not found at {utmctl}")
    ensure_tool("ssh")

    vms = [vm for vm in list_utm_vms(utmctl) if vm["name"] == args.vm_name]
    if len(vms) != 1:
        raise E2EError(
            f"Expected exactly one UTM VM named {args.vm_name!r}; found {len(vms)}"
        )
    vm = vms[0]
    if vm["status"] != "stopped":
        raise E2EError(
            f"Refusing to touch VM {args.vm_name!r}: expected stopped, got {vm['status']}"
        )

    temp_root = Path(tempfile.mkdtemp(prefix="hafl-haos-e2e."))
    vm_started = False
    interrupted = False
    utm_start_process: Optional[subprocess.Popen] = None
    failed = True

    def cleanup() -> None:
        keep_for_debug = args.keep_always or (failed and args.keep_on_failure) or interrupted
        if keep_for_debug:
            print(f"Kept HAOS E2E temp files at {temp_root}")
            if vm_started:
                print(f"Left disposable UTM VM {args.vm_name!r} running for debugging.")
                if utm_start_process is not None and utm_start_process.poll() is None:
                    print("The detached utmctl start helper will exit when the VM stops.")
            return
        if vm_started:
            print(f"Killing disposable UTM VM {args.vm_name!r}.")
            run([utmctl, "stop", "--hide", args.vm_name, "--kill"], capture=True, check=False)
            stop_background_process(utm_start_process)
            close_utm_vm_window(args.vm_name)
        shutil.rmtree(temp_root, ignore_errors=True)

    try:
        print(f"Starting UTM VM {args.vm_name!r} in disposable mode.")
        utm_start_process = start_utm_disposable(utmctl, args.vm_name)
        vm_started = True
        print(f"Waiting for UTM to report an IPv4 address for {args.vm_name!r}.")
        host = wait_for_utm_ip(utmctl, args.vm_name, args.vm_ip_timeout)
        print(f"Discovered HAOS IP: {host}")
        ha_url = f"http://{host}:8123"
        print(f"Waiting for HAOS API at {ha_url}/api/.")
        wait_for_http(
            f"{ha_url}/api/",
            expected_statuses={200, 401},
            timeout=600,
            request_timeout=25,
            label="HAOS",
        )
        print("HAOS API is reachable.")
        print("Creating or logging into the Home Assistant test user.")
        token = onboard_or_login(ha_url, args.ha_username, args.ha_password)
        print("Home Assistant authentication is ready.")

        print("Installing temporary SSH add-on for direct integration copy.")
        key_path = setup_ssh_addon(
            ha_url,
            token,
            host=host,
            port=args.ssh_port,
            temp_dir=temp_root,
            addon_slug=args.ssh_addon_slug,
        )
        archive = make_integration_tar(temp_root)
        install_integration_over_ssh(
            host=host,
            port=args.ssh_port,
            private_key=key_path,
            archive=archive,
        )

        print("Restarting Home Assistant Core after direct integration install.")
        supervisor_api(
            ha_url,
            token,
            endpoint="/core/restart",
            method="post",
            timeout=None,
            allow_disconnect=True,
        )
        time.sleep(10)
        print("Waiting for Home Assistant Core to come back after restart.")
        wait_for_http(
            f"{ha_url}/api/",
            expected_statuses={200, 401},
            timeout=300,
            request_timeout=25,
            label="HAOS Core",
        )
        token = local_login(ha_url, args.ha_username, args.ha_password)

        print("Installing and starting HAFamilyLink auth add-on.")
        addon_slug = ensure_familylink_addon(
            ha_url,
            token,
            repo_url=args.repo_url,
            addon_slug=args.familylink_addon_slug,
            addon_slug_suffix=args.familylink_addon_slug_suffix,
            vnc_password=args.vnc_password,
            google_timeout=args.google_timeout,
            timezone=args.timezone,
        )
        api_url = f"http://{host}:8099"
        wait_for_http(f"{api_url}/api/health", timeout=300, label="HAFamilyLink add-on")
        _, health = request_json("GET", f"{api_url}/api/health")
        api_key = read_remote_file_over_ssh(
            host=host,
            port=args.ssh_port,
            private_key=key_path,
            path="/share/familylink/api_key",
        )
        _, auth_start = request_json("POST", f"{api_url}/api/auth/start", timeout=60)
        print("\nGoogle auth started.")
        print(f"Session: {auth_start.get('session_id')}")
        print(
            f"Auth UI: {api_url} (diagnostics only; Start Authentication is already "
            "running and clicking it may show a harmless error)"
        )
        print(f"noVNC: http://{host}:6080/vnc.html?autoconnect=true")
        print("noVNC login: enter the configured --vnc-password value if prompted.")
        cookie_count, _ = wait_for_auth_cookies(
            api_url,
            api_key=api_key,
            timeout=args.google_timeout,
            label="HAOS add-on",
        )

        configure_familylink_auto(
            ha_url,
            token,
            title="Google Family Link Extended HAOS E2E",
            schedule_timezone=args.schedule_timezone,
        )
        verification = verify_familylink(ha_url, token, timeout=args.verify_timeout)
        summary = {
            "mode": "haos",
            "result": "passed",
            "vm_name": args.vm_name,
            "haos_ip": host,
            "familylink_addon_slug": addon_slug,
            "auth_health": health,
            "cookie_count": cookie_count,
            "ha_url": ha_url,
            **verification,
        }
        failed = False
        return summary
    except KeyboardInterrupt:
        interrupted = True
        raise
    finally:
        cleanup()


def add_common_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--google-timeout", type=int, default=900)
    parser.add_argument("--verify-timeout", type=int, default=180)
    parser.add_argument("--ha-username", default="ben")
    parser.add_argument("--ha-password", default="123456")
    parser.add_argument("--timezone", default="Asia/Jerusalem")
    parser.add_argument("--schedule-timezone", default="Asia/Jerusalem")
    parser.add_argument("--vnc-password", default="familylink")
    parser.add_argument("--keep-on-failure", action="store_true")
    parser.add_argument("--keep-always", action="store_true")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run local interactive HAFamilyLink release E2E checks.",
    )
    subparsers = parser.add_subparsers(dest="mode", required=True)

    sidecar = subparsers.add_parser("sidecar", help="Run Docker sidecar E2E")
    add_common_args(sidecar)
    sidecar.add_argument(
        "--image",
        help=(
            "Standalone auth image to run. If omitted, the image is built from "
            "familylink-playwright/Dockerfile.standalone."
        ),
    )
    sidecar.add_argument("--ha-image", default=DEFAULT_HA_IMAGE)
    sidecar.add_argument("--api-port", type=int, default=18099)
    sidecar.add_argument("--vnc-port", type=int, default=16080)
    sidecar.add_argument("--ha-port", type=int, default=18123)
    sidecar.set_defaults(func=run_sidecar)

    haos = subparsers.add_parser("haos", help="Run optional HAOS VM E2E")
    add_common_args(haos)
    haos.add_argument("--vm-name", default=DEFAULT_HAOS_VM_NAME)
    haos.add_argument("--utmctl", default=DEFAULT_UTMCTL)
    haos.add_argument("--vm-ip-timeout", type=int, default=240)
    haos.add_argument("--ssh-port", type=int, default=22222)
    haos.add_argument("--ssh-addon-slug", default=DEFAULT_SSH_ADDON_SLUG)
    haos.add_argument(
        "--familylink-addon-slug",
        help="Exact add-on slug override. If omitted, the slug is discovered by suffix.",
    )
    haos.add_argument(
        "--familylink-addon-slug-suffix",
        default=DEFAULT_HAFAMILYLINK_ADDON_SLUG_SUFFIX,
    )
    haos.add_argument("--repo-url", default=DEFAULT_HAFAMILYLINK_REPO)
    haos.set_defaults(func=run_haos)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        summary = args.func(args)
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        return 130
    except E2EError as err:
        print(f"\nE2E failed: {err}", file=sys.stderr)
        return 1
    print("\nE2E summary:")
    print(compact_json(summary))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
