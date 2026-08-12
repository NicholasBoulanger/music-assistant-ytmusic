#!/usr/bin/env bash

MA_DEFAULT="app_d5369777_music_assistant"
PYTHON_DEFAULT="python3.13"
BUNDLED="/provider/ytmusic_free"
CACHE="/data/ytmusic_free"
HASHFILE="/data/ytmusic_free.sha256"
DATEFILE="/data/ytmusic_free.fetched_at"
PREVIOUS_CACHE="/data/ytmusic_free.previous"
PREVIOUS_HASHFILE="/data/ytmusic_free.previous.sha256"
PREVIOUS_DATEFILE="/data/ytmusic_free.previous.fetched_at"
MONOCHROME_CACHE="/data/monochrome"
MONOCHROME_HASHFILE="/data/monochrome.sha256"
MONOCHROME_DATEFILE="/data/monochrome.fetched_at"
MONOCHROME_PREVIOUS_CACHE="/data/monochrome.previous"
MONOCHROME_PREVIOUS_HASHFILE="/data/monochrome.previous.sha256"
MONOCHROME_PREVIOUS_DATEFILE="/data/monochrome.previous.fetched_at"
# Where auto-update pulls the latest provider from. Baked from the installer's
# --repo-owner/--ref so a fork self-updates from its own source.
TARBALL_URL="https://codeload.github.com/sproft/music-assistant-ytmusic/tar.gz/refs/heads/main"
MONOCHROME_TARBALL_URL="https://api.github.com/repos/NicholasBoulanger/music-assistant-monochrome/tarball/main"
# How long to wait for the configured MA container to appear before logging a
# loud ERROR. Catches the case where the installer's auto-detect fallback
# baked in a container name that does not exist on this host (issue #11).
MISSING_GRACE_SECONDS=60

# Add-on options (Configuration tab): opt-in auto-update from GitHub. Parsing +
# interval clamp live in a sourceable helper so they can be unit-tested.
. /watcher_lib.sh
read_options

echo "[$(date)] MA Provider Watcher starting..."

if ! docker info > /dev/null 2>&1; then
    echo "[$(date)] ERROR: No Docker socket (is Protection Mode off?)"
    sleep 300
    exit 1
fi
echo "[$(date)] Docker OK"

log() { echo "[$(date)] $*"; }

if [ "$MA_CONTAINER" = "auto" ]; then
    MA="$(docker ps --format '{{.Names}}' 2>/dev/null         | grep -E '^(addon|app)_[0-9a-f]+_music_assistant(_beta|_nightly|_dev)?$'         | head -n1 || true)"
    if [ -z "$MA" ]; then
        MA="$MA_DEFAULT"
        log "WARNING: MA container auto-detection failed; using fallback $MA"
    fi
else
    MA="$MA_CONTAINER"
fi
case "$MA" in ''|*[!A-Za-z0-9_.-]*) log "ERROR: invalid Music Assistant container name"; exit 1 ;; esac

if [ "$MA_PYTHON_VERSION" = "auto" ]; then
    ACTIVE_PYTHON="$(docker exec "$MA" sh -c 'ls /app/venv/lib/ 2>/dev/null'         | grep -E '^python3\.[0-9]+$' | head -n1 || true)"
    if [ -z "$ACTIVE_PYTHON" ]; then
        ACTIVE_PYTHON="$PYTHON_DEFAULT"
        log "WARNING: Python version auto-detection failed; using fallback $ACTIVE_PYTHON"
    fi
else
    ACTIVE_PYTHON="$MA_PYTHON_VERSION"
fi
case "$ACTIVE_PYTHON" in python3.[0-9]|python3.[0-9][0-9]) ;; *) log "ERROR: invalid Music Assistant Python version: $ACTIVE_PYTHON"; exit 1 ;; esac
DST="/app/venv/lib/$ACTIVE_PYTHON/site-packages/music_assistant/providers"
log "Watching container: $MA ($ACTIVE_PYTHON)"

slot_value() { value="$(cat "$1" 2>/dev/null || true)"; [ -n "$value" ] && printf '%s' "$value" || printf '%s' unknown; }

log_provider_slots() {
    label="$1"; active="$2"; current_dir="$3"; current_hash="$4"
    current_date="$5"; previous_dir="$6"; previous_hash="$7"; previous_date="$8"
    if [ -d "$current_dir" ]; then
        log "$label current: date=$(slot_value "$current_date") hash=$(slot_value "$current_hash")"
    elif [ "$label" = "ytmusic_free" ]; then
        log "$label current: bundled with watcher image"
    fi
    if [ -d "$previous_dir" ]; then
        log "$label previous: date=$(slot_value "$previous_date") hash=$(slot_value "$previous_hash")"
    elif [ "$label" = "ytmusic_free" ]; then
        log "$label previous fallback: bundled with watcher image"
    else
        log "$label previous: unavailable until a successful update replaces current"
    fi
    log "$label active slot: $active"
}

# Provider source and fetch helpers come from /watcher_lib.sh (sourced above).

copy_provider() {
    provider_name="$1"
    src="$2"
    echo "[$(date)] Installing $provider_name provider from $src ..."
    # Clear any stale in-place copy so docker cp is a clean replace, not a merge:
    # files deleted upstream would otherwise linger across periodic auto-updates
    # (docker restart keeps the container filesystem). Mirrors install_provider.sh.
    docker exec "$MA" rm -rf "$DST/$provider_name" 2>/dev/null || true
    docker cp "$src" "$MA:$DST/"         && echo "[$(date)] Copied $provider_name OK"         || { echo "[$(date)] ERROR: $provider_name copy failed"; return 1; }
}

install_providers() {
    sleep 3
    failed=0
    copy_provider ytmusic_free "$(provider_src)" || failed=1
    if [ "$MONOCHROME_ENABLED" = "true" ]; then
        mono_src="$(monochrome_src)"
        if [ -n "$mono_src" ]; then
            copy_provider monochrome "$mono_src" || failed=1
        else
            log "WARNING: Monochrome is enabled but no cached provider is available."
        fi
    fi
    if [ "$failed" -ne 0 ]; then
        log "ERROR: one or more provider copies failed; MA was not restarted."
        return 1
    fi
    docker restart "$MA" >/dev/null         && echo "[$(date)] MA restarted"         || { echo "[$(date)] ERROR: restart failed"; return 1; }
}

warn_if_ma_misconfigured() {
    # If the configured container name doesn't match anything, give the
    # user enough information to fix it. Always check at least one known
    # candidate so the diagnostic surfaces even when nothing matches $MA.
    found="$(docker ps --format '{{.Names}}' 2>/dev/null | grep -E 'music' || true)"
    echo "[$(date)] ERROR: no container matched name '$MA' after ${MISSING_GRACE_SECONDS}s."
    if [ -n "$found" ]; then
        echo "[$(date)] HINT: containers with 'music' in the name on this host:"
        printf '%s\n' "$found" | sed "s/^/[$(date)]   /"
        echo "[$(date)] HINT: re-run the installer with the right --ma-id, then restart this add-on:"
        echo "[$(date)]   curl -fsSL https://raw.githubusercontent.com/NicholasBoulanger/music-assistant-ytmusic/main/scripts/install_watcher_addon.sh | sh -s -- --ma-id <name> --force"
    else
        echo "[$(date)] HINT: docker ps shows no container with 'music' in the name. Is the Music Assistant add-on installed and running?"
    fi
}

# A private provider cannot use Previous before an update has created that
# slot. Fall back visibly instead of leaving MA without Monochrome.
if [ "$MONOCHROME_ACTIVE_VERSION" = "previous" ] && [ ! -d "$MONOCHROME_PREVIOUS_CACHE" ]; then
    log "WARNING: Monochrome Previous was selected but is unavailable; using Current."
    MONOCHROME_ACTIVE_VERSION="current"
fi

# Prime current with the latest provider before the first inject (opt-in).
# Selecting Previous pauses updates so the rollback slot cannot be overwritten.
if [ "$YTMUSIC_AUTO_UPDATE" = "true" ] && [ "$YTMUSIC_ACTIVE_VERSION" = "current" ]; then
    log "ytmusic_free auto-update enabled (checking every ${UPDATE_INTERVAL_HOURS}h); fetching latest..."
    fetch_latest || true
elif [ "$YTMUSIC_ACTIVE_VERSION" = "previous" ]; then
    log "ytmusic_free Previous selected; auto-update paused to preserve rollback."
else
    log "ytmusic_free auto-update disabled; keeping the selected version pinned."
fi
if [ "$MONOCHROME_ENABLED" = "true" ]; then
    # A first-time install always needs to populate Monochrome's private cache.
    # With its auto-update disabled, an existing cache is deliberately pinned.
    if { [ "$MONOCHROME_AUTO_UPDATE" = "true" ] && [ "$MONOCHROME_ACTIVE_VERSION" = "current" ]; } || [ ! -d "$MONOCHROME_CACHE" ]; then
        fetch_monochrome || true
    elif [ "$MONOCHROME_ACTIVE_VERSION" = "previous" ]; then
        log "Monochrome Previous selected; auto-update paused to preserve rollback."
    fi
fi
log "ytmusic_free source: $(provider_src)"
log_provider_slots ytmusic_free "$YTMUSIC_ACTIVE_VERSION" "$CACHE" "$HASHFILE" "$DATEFILE"     "$PREVIOUS_CACHE" "$PREVIOUS_HASHFILE" "$PREVIOUS_DATEFILE"
if [ "$MONOCHROME_ENABLED" = "true" ]; then
    mono_src="$(monochrome_src)"
    if [ -n "$mono_src" ]; then log "monochrome source: $mono_src"; fi
    log_provider_slots monochrome "$MONOCHROME_ACTIVE_VERSION" "$MONOCHROME_CACHE"         "$MONOCHROME_HASHFILE" "$MONOCHROME_DATEFILE" "$MONOCHROME_PREVIOUS_CACHE"         "$MONOCHROME_PREVIOUS_HASHFILE" "$MONOCHROME_PREVIOUS_DATEFILE"
fi

LAST_ID=$(docker ps -q --no-trunc --filter name="$MA" 2>/dev/null)
if [ -n "$LAST_ID" ]; then
    echo "[$(date)] MA running (${LAST_ID:0:12}), installing providers..."
    install_providers
else
    echo "[$(date)] MA not running, waiting..."
fi

echo "[$(date)] Polling for MA container changes every 10s..."
MISSING_SINCE=0
MISSING_WARNED=0
LAST_UPDATE=$(date +%s)
[ -z "$LAST_ID" ] && MISSING_SINCE=$(date +%s)
while true; do
    sleep 10
    CUR_ID=$(docker ps -q --no-trunc --filter name="$MA" 2>/dev/null)
    if [ -n "$CUR_ID" ] && [ "$CUR_ID" != "$LAST_ID" ]; then
        echo "[$(date)] New MA container (${CUR_ID:0:12}), reinstalling providers..."
        LAST_ID="$CUR_ID"
        install_providers
        MISSING_SINCE=0
        MISSING_WARNED=0
    elif [ -z "$CUR_ID" ] && [ -n "$LAST_ID" ]; then
        echo "[$(date)] MA stopped"
        LAST_ID=""
        MISSING_SINCE=$(date +%s)
    elif [ -z "$CUR_ID" ] && [ "$MISSING_WARNED" -eq 0 ] && [ "$MISSING_SINCE" -gt 0 ]; then
        if [ $(($(date +%s) - MISSING_SINCE)) -ge "$MISSING_GRACE_SECONDS" ]; then
            warn_if_ma_misconfigured
            MISSING_WARNED=1
        fi
    fi
    # Periodic auto-update: fetch both providers, then reinject and restart MA
    # once when either provider changed.
    if { [ "$YTMUSIC_AUTO_UPDATE" = "true" ] && [ "$YTMUSIC_ACTIVE_VERSION" = "current" ]; } ||        { [ "$MONOCHROME_ENABLED" = "true" ] && [ "$MONOCHROME_AUTO_UPDATE" = "true" ] && [ "$MONOCHROME_ACTIVE_VERSION" = "current" ]; }; then
        now=$(date +%s)
        if [ $((now - LAST_UPDATE)) -ge "$UPDATE_INTERVAL" ]; then
            LAST_UPDATE=$now
            providers_changed=0
            if [ "$YTMUSIC_AUTO_UPDATE" = "true" ] && [ "$YTMUSIC_ACTIVE_VERSION" = "current" ]; then
                if fetch_latest; then providers_changed=1; fi
            fi
            if [ "$MONOCHROME_ENABLED" = "true" ] && [ "$MONOCHROME_AUTO_UPDATE" = "true" ] && [ "$MONOCHROME_ACTIVE_VERSION" = "current" ]; then
                if fetch_monochrome; then providers_changed=1; fi
            fi
            if [ "$providers_changed" -eq 1 ]; then
                log "auto-update: provider change detected -> reinstalling"
                CUR_ID=$(docker ps -q --no-trunc --filter name="$MA" 2>/dev/null)
                if [ -n "$CUR_ID" ]; then LAST_ID="$CUR_ID"; install_providers; fi
            fi
        fi
    fi
done
