#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
CONFIG_FILE="${SCRIPT_DIR}/config.json"

REGISTRY="${REGISTRY:-ghcr.io}"
IMAGE_OWNER="${IMAGE_OWNER:-benkap}"
IMAGE_NAME="${IMAGE_NAME:-familylink-auth}"
PLATFORMS="${PLATFORMS:-}"
PROGRESS="${PROGRESS:-auto}"
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
  --progress MODE    Docker build progress output. Default: auto.
  --addon-only       Build only the Home Assistant add-on image.
  --standalone-only  Build only the standalone Docker image.
  -h, --help         Show this help.

Environment:
  REGISTRY           Registry host. Default: ghcr.io
  IMAGE_OWNER        Registry owner/org. Default: benkap
  IMAGE_NAME         Image name. Default: familylink-auth
  PLATFORMS          Default platform list.
  PROGRESS           Docker build progress output. Default: auto.

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

normalize_platform() {
    case "$1" in
        linux/aarch64)
            echo "linux/arm64"
            ;;
        linux/x86_64)
            echo "linux/amd64"
            ;;
        linux/armhf)
            echo "linux/arm/v7"
            ;;
        *)
            echo "$1"
            ;;
    esac
}

normalize_platforms() {
    local value="$1"
    local normalized=""
    local platform

    IFS=',' read -ra platforms <<< "${value}"
    for platform in "${platforms[@]}"; do
        if [ -n "${normalized}" ]; then
            normalized+=","
        fi
        normalized+="$(normalize_platform "${platform}")"
    done

    echo "${normalized}"
}

format_bytes() {
    local bytes="$1"

    if command -v python3 >/dev/null 2>&1; then
        python3 -c 'import sys; size=int(sys.argv[1]); print(f"{size / 1024 / 1024:.1f} MiB")' "${bytes}"
    elif command -v awk >/dev/null 2>&1; then
        awk -v size="${bytes}" 'BEGIN { printf "%.1f MiB\n", size / 1024 / 1024 }'
    else
        echo "${bytes}"
    fi
}

print_loaded_image_sizes() {
    local tags=("$@")
    local tag
    local bytes

    if [ "${#tags[@]}" -eq 0 ]; then
        return
    fi

    echo "  Loaded image sizes:"
    for tag in "${tags[@]}"; do
        bytes="$(docker image inspect "${tag}" --format '{{.Size}}' 2>/dev/null || true)"
        if [ -n "${bytes}" ]; then
            echo "    - ${tag}: $(format_bytes "${bytes}")"
        fi
    done
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
PLATFORMS="$(normalize_platforms "${PLATFORMS}")"

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
    local build_args=("$@")
    local tags=()
    local index

    local output_arg="--load"
    if [ "${PUSH}" -eq 1 ]; then
        output_arg="--push"
    fi

    for ((index = 0; index < ${#build_args[@]}; index++)); do
        if [ "${build_args[index]}" = "-t" ] || [ "${build_args[index]}" = "--tag" ]; then
            if [ $((index + 1)) -lt "${#build_args[@]}" ]; then
                tags+=("${build_args[index + 1]}")
            fi
        fi
    done

    echo "Building ${label}"
    echo "  Image: ${IMAGE_REF}"
    echo "  Version: ${VERSION}"
    echo "  Platforms: ${PLATFORMS}"
    echo "  Output: $([ "${PUSH}" -eq 1 ] && echo push || echo local load)"

    docker buildx build \
        --progress "${PROGRESS}" \
        --platform "${PLATFORMS}" \
        -f "${SCRIPT_DIR}/${dockerfile}" \
        "${build_args[@]}" \
        "${output_arg}" \
        "${SCRIPT_DIR}"

    if [ "${PUSH}" -eq 0 ]; then
        print_loaded_image_sizes "${tags[@]}"
    fi
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
