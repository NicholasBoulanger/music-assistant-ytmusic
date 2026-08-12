ARG BUILD_FROM=ghcr.io/home-assistant/base:3.23
FROM ${BUILD_FROM}

RUN apk add --no-cache bash curl docker-cli jq tar

# Keep a known-good public provider in the watcher image. Runtime auto-update
# can subsequently promote newer copies into the persistent two-slot cache.
RUN set -eux; \
    build_tmp="$(mktemp -d)"; \
    curl -fsSL --connect-timeout 10 --max-time 120 \
      https://codeload.github.com/sproft/music-assistant-ytmusic/tar.gz/refs/heads/main \
      -o "$build_tmp/provider.tgz"; \
    tar -xzf "$build_tmp/provider.tgz" -C "$build_tmp"; \
    provider_src="$(find "$build_tmp" -maxdepth 3 -type d -name ytmusic_free | head -n1)"; \
    test -f "$provider_src/__init__.py"; \
    test -f "$provider_src/manifest.json"; \
    mkdir -p /provider/ytmusic_free; \
    cp -a "$provider_src/." /provider/ytmusic_free/; \
    rm -rf "$build_tmp"

COPY watcher_lib.sh /watcher_lib.sh
COPY run.sh /run.sh
RUN chmod +x /run.sh && sed -i 's/\r//' /run.sh /watcher_lib.sh

LABEL org.opencontainers.image.title="Home Assistant App: MA Provider Watcher (Monochrome)" \
      org.opencontainers.image.description="Keeps custom Music Assistant providers installed and updated" \
      org.opencontainers.image.source="https://github.com/NicholasBoulanger/music-assistant-ytmusic"

ENTRYPOINT ["/run.sh"]
