#!/usr/bin/env bash
set -euo pipefail

IMAGE="${IMAGE:-ghcr.io/benkap/familylink-auth:standalone}"
NAME="${NAME:-familylink-auth-smoke-$$}"
API_PORT="${API_PORT:-18102}"
VNC_PORT="${VNC_PORT:-16083}"
KEEP_SMOKE_DATA="${KEEP_SMOKE_DATA:-0}"

if [ -n "${DATA_DIR:-}" ]; then
    DATA_DIR_CREATED=0
else
    DATA_DIR="$(mktemp -d "${TMPDIR:-/tmp}/familylink-auth-smoke.XXXXXX")"
    DATA_DIR_CREATED=1
fi

cleanup() {
    docker rm -f "${NAME}" >/dev/null 2>&1 || true
    if [ "${KEEP_SMOKE_DATA}" != "1" ] && [ "${DATA_DIR_CREATED}" = "1" ]; then
        rm -rf "${DATA_DIR}"
    elif [ "${KEEP_SMOKE_DATA}" = "1" ]; then
        echo "Kept smoke data at ${DATA_DIR}"
    fi
}

wait_for_health() {
    local health_url="http://127.0.0.1:${API_PORT}/api/health"
    local attempt

    for attempt in $(seq 1 30); do
        if curl -fsS "${health_url}" >/dev/null 2>&1; then
            return 0
        fi
        sleep 1
    done

    docker logs "${NAME}" >&2 || true
    echo "Standalone auth service did not become healthy" >&2
    return 1
}

http_code() {
    curl -sS -o /dev/null -w "%{http_code}" "$@"
}

docker rm -f "${NAME}" >/dev/null 2>&1 || true
mkdir -p "${DATA_DIR}"
trap cleanup EXIT

docker run -d \
    --name "${NAME}" \
    -p "${API_PORT}:8099" \
    -p "${VNC_PORT}:6080" \
    -v "${DATA_DIR}:/share/familylink:rw" \
    "${IMAGE}" >/dev/null

wait_for_health

api_url="http://127.0.0.1:${API_PORT}"
unauthenticated_code="$(http_code "${api_url}/api/cookies")"
if [ "${unauthenticated_code}" != "403" ]; then
    echo "Expected unauthenticated /api/cookies to return 403, got ${unauthenticated_code}" >&2
    exit 1
fi

if [ ! -s "${DATA_DIR}/api_key" ]; then
    echo "Expected generated API key at ${DATA_DIR}/api_key" >&2
    exit 1
fi

api_key="$(cat "${DATA_DIR}/api_key")"
authenticated_code="$(http_code -H "X-API-Key: ${api_key}" "${api_url}/api/cookies")"
case "${authenticated_code}" in
    200|404)
        ;;
    *)
        echo "Expected authenticated /api/cookies to return 200 or 404, got ${authenticated_code}" >&2
        exit 1
        ;;
esac

echo "Standalone smoke passed (${IMAGE})"
