#!/bin/bash
set -euo pipefail

# ==============================================================================
# Start Family Link Auth Service (Standalone)
# ==============================================================================

BACKGROUND_PIDS=()
UVICORN_PID=""
LAST_PID=""

cleanup_processes() {
    local status=$?
    trap - EXIT INT TERM

    echo ""
    echo "Stopping Family Link Auth Service..."

    if [ -n "${UVICORN_PID}" ] && kill -0 "${UVICORN_PID}" 2>/dev/null; then
        kill -TERM "${UVICORN_PID}" 2>/dev/null || true
    fi

    if [ "${#BACKGROUND_PIDS[@]}" -gt 0 ]; then
        kill -TERM "${BACKGROUND_PIDS[@]}" 2>/dev/null || true
        wait "${BACKGROUND_PIDS[@]}" 2>/dev/null || true
    fi

    if [ -n "${UVICORN_PID}" ]; then
        wait "${UVICORN_PID}" 2>/dev/null || true
    fi

    exit "${status}"
}

start_background() {
    "$@" >/dev/null 2>&1 &
    LAST_PID=$!
    BACKGROUND_PIDS+=("${LAST_PID}")
}

check_process() {
    local pid="$1"
    local ok_message="$2"
    local fail_message="$3"

    if kill -0 "${pid}" 2>/dev/null; then
        echo "✓ ${ok_message}"
        return 0
    fi

    echo "⚠ ${fail_message}"
    return 1
}

trap cleanup_processes EXIT
trap 'exit 143' TERM
trap 'exit 130' INT

echo "=============================================="
echo "Google Family Link Auth Service (Standalone)"
echo "=============================================="
echo ""

# Read configuration from environment variables
LOG_LEVEL="${LOG_LEVEL:-info}"
AUTH_TIMEOUT="${AUTH_TIMEOUT:-300}"
SESSION_DURATION="${SESSION_DURATION:-86400}"
VNC_PASSWORD="${VNC_PASSWORD:-familylink}"
LANGUAGE="${LANGUAGE:-en-US}"
TIMEZONE="${TIMEZONE:-Europe/Paris}"

echo "Configuration:"
echo "  - Log Level: ${LOG_LEVEL}"
echo "  - Auth Timeout: ${AUTH_TIMEOUT}s"
echo "  - Session Duration: ${SESSION_DURATION}s"
echo "  - VNC Password: [configured]"
echo "  - Language: ${LANGUAGE}"
echo "  - Timezone: ${TIMEZONE}"
echo ""

# Ensure shared directory exists
mkdir -p /share/familylink
chmod 700 /share/familylink
echo "✓ Shared storage ready at /share/familylink"

# The cookie endpoint (/api/cookies) always requires an API key. It is
# auto-generated on first start unless the API_KEY env variable is set.
if [ -n "${API_KEY:-}" ]; then
    echo "✓ Cookie API key: provided via API_KEY environment variable"
else
    echo "ℹ Cookie API key: auto-generated in /share/familylink/api_key (./data/api_key on the host)"
fi
echo "  Configure the HA integration with: http://<this-host>:8099?api_key=<key>"

# Start D-Bus system bus if not available (fixes blank screen on RPi4/ARM64)
if [ ! -S /run/dbus/system_bus_socket ]; then
    echo "Starting D-Bus system bus..."
    mkdir -p /run/dbus
    DBUS_PID="$(dbus-daemon --system --fork --print-pid 2>/dev/null)" || DBUS_PID=""
    if [ -n "${DBUS_PID}" ]; then
        BACKGROUND_PIDS+=("${DBUS_PID}")
        echo "✓ D-Bus system bus started"
    else
        echo "⚠ D-Bus not available (non-critical)"
    fi
fi

# Start Xvfb (virtual display)
# Using 16-bit color depth for better VM compatibility and lower memory usage
echo "Starting virtual display (Xvfb)..."
start_background Xvfb :99 -screen 0 1280x1024x16 -ac -nolisten tcp
XVFB_PID="${LAST_PID}"
export DISPLAY=:99

# Wait for Xvfb to start
sleep 2
check_process "${XVFB_PID}" "Virtual display started on :99" "Virtual display failed to start" || exit 1

# Start window manager
start_background fluxbox
FLUXBOX_PID="${LAST_PID}"
check_process "${FLUXBOX_PID}" "Window manager (fluxbox) started" "Window manager (fluxbox) failed to start" || true

# Start VNC server (localhost only) and noVNC web interface
echo "Starting VNC server (localhost only)..."
start_background x11vnc -display :99 -forever -shared -rfbport 5900 -localhost -passwd "${VNC_PASSWORD}"
VNC_PID="${LAST_PID}"
sleep 1
check_process "${VNC_PID}" "VNC server started" "VNC server failed to start — noVNC will not be available" || true

echo "Starting noVNC on port 6080..."
start_background websockify --web=/usr/share/novnc 6080 localhost:5900
NOVNC_PID="${LAST_PID}"
sleep 1
check_process "${NOVNC_PID}" "noVNC started" "noVNC (websockify) failed to start on port 6080" || true

# Display a welcome banner on the Xvfb display so noVNC is not black
# before the user triggers the authentication flow (issue #108).
if [ -x /usr/local/bin/welcome-banner.sh ]; then
    /usr/local/bin/welcome-banner.sh || echo "⚠ Welcome banner failed to start (non-critical)"
fi
echo ""

echo "=============================================="
echo "Service Ready!"
echo "  - Web UI: http://localhost:8099"
echo "  - noVNC:  http://localhost:6080/vnc.html"
echo "=============================================="
echo ""

# Start the FastAPI application with uvicorn
cd /app || exit 1
uvicorn app.main:app \
    --host 0.0.0.0 \
    --port 8099 \
    --log-level "${LOG_LEVEL}" \
    --no-access-log \
    --workers 1 &
UVICORN_PID=$!
wait "${UVICORN_PID}"
