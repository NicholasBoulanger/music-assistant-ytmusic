# Declare the build argument before FROM so it can be used in the base image tag
ARG MA_VERSION=latest
FROM ghcr.io/music-assistant/server:${MA_VERSION}

# Copy the provider directory from the repository context into the image
# We temporarily place it in a generic location to handle dynamic Python versions safely
COPY ytmusic_free/ /tmp/ytmusic_free/

# Detect the active Python version, move files to the correct site-packages folder,
# and install required dependencies inside the Music Assistant virtual environment
RUN PYVER=$(ls /app/venv/lib | grep -m1 '^python3') && \
    DST_DIR="/app/venv/lib/$PYVER/site-packages/music_assistant/providers/ytmusic_free" && \
    # Clean up any stale files if they exist
    rm -rf "$DST_DIR" && \
    # Move the provider to the correct active Python directory
    mv /tmp/ytmusic_free "$DST_DIR" && \
    # Install dependencies listed in requirements.txt directly into the MA virtual environment
    if [ -f "$DST_DIR/requirements.txt" ]; then \
        /app/venv/bin/pip install --no-cache-dir -r "$DST_DIR/requirements.txt"; \
    fi