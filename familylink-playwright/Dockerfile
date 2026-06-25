# syntax=docker/dockerfile:1.7

ARG BUILD_FROM=ghcr.io/hassio-addons/debian-base:7.3.3
FROM ${BUILD_FROM}

# Set shell
SHELL ["/bin/bash", "-o", "pipefail", "-c"]

# Install system dependencies shared by the add-on and standalone images.
COPY scripts/install-runtime-deps.sh /tmp/install-runtime-deps.sh
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt/lists,sharing=locked \
    KEEP_APT_CACHE=1 /tmp/install-runtime-deps.sh \
    && rm /tmp/install-runtime-deps.sh

# Set environment variables for Playwright
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
ENV PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=0
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# Set working directory
WORKDIR /app

# Copy requirements and install Python dependencies
COPY requirements.txt .
COPY --chmod=755 scripts/healthcheck.py /usr/local/bin/familylink-healthcheck
RUN --mount=type=cache,target=/root/.cache/pip \
    pip3 install --break-system-packages --no-compile -r requirements.txt

# Install headed Chromium for Playwright. The auth flow uses Xvfb/noVNC, so
# the separate Chromium headless shell is unused image weight.
RUN python3 -m playwright install --with-deps --no-shell chromium \
    && rm -rf /var/lib/apt/lists/*

# Copy application code
COPY app/ /app/app/
COPY rootfs/ /
COPY welcome-banner.sh /usr/local/bin/welcome-banner.sh

# Set permissions
RUN chmod a+x /usr/local/bin/run.sh && \
    chmod a+x /usr/local/bin/welcome-banner.sh && \
    chmod a+x /etc/services.d/familylink/run && \
    chmod a+x /etc/services.d/familylink/finish

# Create necessary directories
RUN mkdir -p /share/familylink && \
    chmod 700 /share/familylink

# Expose ports
EXPOSE 8099 6080

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD familylink-healthcheck

# Labels
LABEL \
    io.hass.name="Google Family Link Auth" \
    io.hass.description="Authentication service for Google Family Link" \
    io.hass.type="addon" \
    io.hass.version="1.7.1"
