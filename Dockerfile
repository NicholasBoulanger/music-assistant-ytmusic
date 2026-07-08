# Declare the build argument before FROM so it can be used in the base image tag
ARG MA_VERSION=latest
FROM ghcr.io/music-assistant/server:${MA_VERSION}

# Copy the provider directory from the repository context into the image
COPY ytmusic_free/ /tmp/ytmusic_free/

# Detect the active Python version and move files to the correct site-packages folder.
# Dependencies from manifest.json will be installed automatically by Music Assistant on first setup.
RUN PYVER=$(ls /app/venv/lib | grep -m1 '^python3') && \
    DST_DIR="/app/venv/lib/$PYVER/site-packages/music_assistant/providers/ytmusic_free" && \
    rm -rf "$DST_DIR" && \
    mv /tmp/ytmusic_free "$DST_DIR"