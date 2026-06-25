#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
CONFIG_FILE="${SCRIPT_DIR}/config.json"

REGISTRY="${REGISTRY:-ghcr.io}"
IMAGE_OWNER="${IMAGE_OWNER:-benkap}"
IMAGE_NAME="${IMAGE_NAME:-familylink-auth}"
PLATFORMS="${PLATFORMS:-}"
PUSH=0
BUILD_ADDON=1
BUILD_STANDALONE=1

usage() {
    cat <<'EOF'
Build Family Link auth Docker images.

Local builds are loaded into Docker by default. Publishing is opt-in.

Usage:
  ./build-docker.sh [options]

Options:
  --push             Push images to the registry instead of loading locally.
  --platforms LIST   Build platform list, for example linux/amd64,linux/arm64.
  --addon-only       Build only the Home Assistant add-on image.
  --standalone-only  Build only the standalone Docker image.
  -h, --help         Show this help.

Environment:
  REGISTRY           Registry host. Default: ghcr.io
  IMAGE_OWNER        Registry owner/org. Default: benkap
  IMAGE_NAME         Image name. Default: familylink-auth
  PLATFORMS          Default platform list.

Examples:
  ./build-docker.sh
  ./build-docker.sh --standalone-only
  ./build-docker.sh --push --platforms linux/amd64,linux/arm64
EOF
}

read_version() {
    if command -v jq >/dev/null 2>&1; then
        jq -r '.version' "${CONFIG_FILE}"
    elif command -v python3 >/dev/null 2>&1; then
        python3 -c 'import json, sys; print(json.load(open(sys.argv[1]))["version"])' "${CONFIG_FILE}"
    else
        sed -n 's/.*"version": *"\([^"]*\)".*/\1/p' "${CONFIG_FILE}"
    fi
}

while [ "$#" -gt 0 ]; do
    case "$1" in
        --push)
            PUSH=1
            ;;
        --platforms)
            shift
            PLATFORMS="${1:?missing value for --platforms}"
            ;;
        --addon-only)
            BUILD_ADDON=1
            BUILD_STANDALONE=0
            ;;
        --standalone-only)
            BUILD_ADDON=0
            BUILD_STANDALONE=1
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            echo "Unknown option: $1" >&2
            usage >&2
            exit 2
            ;;
    esac
    shift
done

if [ -z "${PLATFORMS}" ]; then
    PLATFORMS="$(docker info --format '{{.OSType}}/{{.Architecture}}' 2>/dev/null || echo linux/amd64)"
fi

if [ "${PUSH}" -eq 0 ] && [[ "${PLATFORMS}" == *,* ]]; then
    echo "Local builds can only load one platform. Use --push for multi-platform builds." >&2
    exit 2
fi

VERSION="$(read_version)"
IMAGE_REF="${REGISTRY}/${IMAGE_OWNER}/${IMAGE_NAME}"

if [ -z "${VERSION}" ] || [ "${VERSION}" = "null" ]; then
    echo "Could not read version from ${CONFIG_FILE}" >&2
    exit 1
fi

build_image() {
    local label="$1"
    local dockerfile="$2"
    shift 2

    local output_arg="--load"
    if [ "${PUSH}" -eq 1 ]; then
        output_arg="--push"
    fi

    echo "Building ${label}"
    echo "  Image: ${IMAGE_REF}"
    echo "  Version: ${VERSION}"
    echo "  Platforms: ${PLATFORMS}"
    echo "  Output: $([ "${PUSH}" -eq 1 ] && echo push || echo local load)"

    docker buildx build \
        --platform "${PLATFORMS}" \
        -f "${SCRIPT_DIR}/${dockerfile}" \
        "$@" \
        "${output_arg}" \
        "${SCRIPT_DIR}"
}

if [ "${BUILD_ADDON}" -eq 1 ]; then
    build_image "Home Assistant add-on image" "Dockerfile" \
        -t "${IMAGE_REF}:${VERSION}" \
        -t "${IMAGE_REF}:latest"
fi

if [ "${BUILD_STANDALONE}" -eq 1 ]; then
    build_image "standalone Docker image" "Dockerfile.standalone" \
        -t "${IMAGE_REF}:${VERSION}-standalone" \
        -t "${IMAGE_REF}:standalone"
fi
