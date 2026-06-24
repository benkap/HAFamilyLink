ARG BUILD_FROM=ghcr.io/hassio-addons/debian-base:7.3.3
FROM ${BUILD_FROM}

# Set shell
SHELL ["/bin/bash", "-o", "pipefail", "-c"]

# Install system dependencies shared by the add-on and standalone images.
COPY scripts/install-runtime-deps.sh /tmp/install-runtime-deps.sh
RUN /tmp/install-runtime-deps.sh \
    && rm /tmp/install-runtime-deps.sh

# Set environment variables for Playwright
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
ENV PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=0
ENV PYTHONUNBUFFERED=1

# Set working directory
WORKDIR /app

# Copy requirements and install Python dependencies
COPY requirements.txt .
RUN pip3 install --no-cache-dir --break-system-packages -r requirements.txt

# Install Chromium for Playwright. Debian-based images support ARM64.
RUN python3 -m playwright install --with-deps chromium

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
    CMD curl -f http://localhost:8099/api/health || exit 1

# Labels
LABEL \
    io.hass.name="Google Family Link Auth" \
    io.hass.description="Authentication service for Google Family Link" \
    io.hass.type="addon" \
    io.hass.version="1.6.1"
