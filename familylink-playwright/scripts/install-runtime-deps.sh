#!/bin/sh
set -eu

apt-get update
DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
    python3 \
    python3-pip \
    ca-certificates \
    xvfb \
    x11vnc \
    novnc \
    python3-websockify \
    fluxbox \
    xterm \
    dbus

if [ "${KEEP_APT_CACHE:-0}" != "1" ]; then
    apt-get clean
    rm -rf /var/lib/apt/lists/*
fi
