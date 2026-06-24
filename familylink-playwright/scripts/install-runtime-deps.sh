#!/bin/sh
set -eu

apt-get update
DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
    python3 \
    python3-pip \
    curl \
    ca-certificates \
    xvfb \
    x11vnc \
    novnc \
    python3-websockify \
    fluxbox \
    xterm \
    dbus
apt-get clean
rm -rf /var/lib/apt/lists/*
