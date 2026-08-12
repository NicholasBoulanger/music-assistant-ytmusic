#!/bin/sh
# Install the MA Provider Watcher add-on for ytmusic_free and Monochrome.
#
# Portable across HAOS (BusyBox ash) and Supervised installs. Uses curl + tar
# instead of git so it runs on HAOS, where git is not available.
#
# Usage:
#   sh install_watcher_addon.sh [--force] [--repo-owner OWNER] [--ref REF]
#                               [--monochrome-repo OWNER/REPO]
#                               [--monochrome-ref REF] [--ma-id ID]
#                               [--python-version VER] [--addons-dir DIR]
#
# See WATCHER_ADDON.md for the underlying manual procedure.

set -eu

REPO_OWNER="sproft"
REPO_NAME="music-assistant-ytmusic"
WATCHER_REPO_OWNER="NicholasBoulanger"
ADDON_SLUG="ma_provider_watcher"
ADDON_NAME="MA Provider Watcher"
MONOCHROME_REPO="NicholasBoulanger/music-assistant-monochrome"
MONOCHROME_REF="main"
# Stamp a fresh, strictly-increasing version on every run so Home Assistant sees
# a newer version and rebuilds the add-on image. Without this the version stays
# pinned, so re-running the installer (e.g. to fix the Python version or MA ID)
# silently keeps the stale cached image with the old run.sh -- issue #22.
ADDON_VERSION="1.0.$(date +%Y%m%d%H%M%S)"

REF="main"
FORCE=0
MA_ID=""
PYTHON_VERSION=""
ADDONS_DIR=""

log()  { printf '[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*"; }
die()  { printf 'ERROR: %s\n' "$*" >&2; exit 1; }
need() { command -v "$1" >/dev/null 2>&1 || die "required command not found: $1"; }

# A candidate is only usable if it is a directory we can actually write into.
# Some add-ons mount the add-ons share read-only (or owned by another uid), so
# [ -d ] alone would pick a dir the install then fails to write -- probe for real.
writable_dir() {
    [ -d "$1" ] || return 1
    _probe="$1/.maw_write_test.$$"
    if ( : > "$_probe" ) 2>/dev/null; then
        rm -f "$_probe" 2>/dev/null
        return 0
    fi
    return 1
}

usage() {
    cat <<EOF
Usage: sh install_watcher_addon.sh [options]

Options:
  --force, -f               Overwrite existing add-on directory without prompting
  --repo-owner OWNER        Repository owner (default: sproft)
  --ref REF                 Branch to download; auto-update follows this branch head (default: main)
  --monochrome-repo O/R     Private Monochrome repository (default: $MONOCHROME_REPO)
  --monochrome-ref REF      Monochrome branch to follow (default: $MONOCHROME_REF)
  --ma-id ID                Music Assistant container ID (default: auto-detect)
  --python-version VER      MA Python version, e.g. python3.13 (default: auto-detect)
  --addons-dir DIR          Local add-ons directory (default: auto-detect HAOS vs. Supervised)
  --help, -h                Show this help
EOF
}

while [ $# -gt 0 ]; do
    case "$1" in
        --force|-f) FORCE=1 ;;
        --repo-owner) shift; REPO_OWNER="${1:-}" ;;
        --ref) shift; REF="${1:-}" ;;
        --monochrome-repo) shift; MONOCHROME_REPO="${1:-}" ;;
        --monochrome-ref) shift; MONOCHROME_REF="${1:-}" ;;
        --ma-id) shift; MA_ID="${1:-}" ;;
        --python-version) shift; PYTHON_VERSION="${1:-}" ;;
        --addons-dir) shift; ADDONS_DIR="${1:-}" ;;
        --help|-h) usage; exit 0 ;;
        *) die "unknown option: $1 (try --help)" ;;
    esac
    shift || true
done

# URL of this script, used in re-run hints (including the one baked into the
# generated run.sh) so they are copy-pasteable. Honors --repo-owner / --ref, and
# shows the "sh -s --" pipe form: the documented install is "curl ... | sh",
# where a bare "--flag" is parsed by sh itself and fails with "sh: bad option".
SCRIPT_URL="https://raw.githubusercontent.com/$WATCHER_REPO_OWNER/$REPO_NAME/$REF/scripts/install_watcher_addon.sh"

# --- Preflight ---------------------------------------------------------------

log "Preflight checks..."
need curl
need tar
need mkdir
need cp
need rm

# --- Detect add-ons directory -----------------------------------------------

if [ -z "$ADDONS_DIR" ]; then
    # Probe known local add-ons locations, most-standard first. Notes:
    #  - Inside the SSH / Samba / Terminal add-on (the common case) the local
    #    repo is mapped to /addons; host paths below are invisible there.
    #  - HA renamed the Supervisor "addons" tree to "apps" (HAOS 18+, mirroring
    #    `ha apps` replacing the deprecated `ha addons`), so the modern layout is
    #    .../apps/local while older installs still use .../addons/local.
    #  - Supervised reads its data share from /etc/hassio.json ("data" key);
    #    the default moved from /usr/share/hassio to /var/lib/homeassistant.
    # /root/addons (a prior fallback) is intentionally dropped: it is not used by
    # any supported install type.
    _data_share=""
    if [ -r /etc/hassio.json ]; then
        _data_share="$(sed -n 's/.*"data" *: *"\([^"]*\)".*/\1/p' \
                       /etc/hassio.json 2>/dev/null | head -n1)"
    fi
    for _cand in \
        /addons \
        /addons/local \
        /data/apps/local \
        /data/addons/local \
        /mnt/data/supervisor/apps/local \
        /mnt/data/supervisor/addons/local \
        ${_data_share:+"$_data_share/apps/local" "$_data_share/addons/local"} \
        /var/lib/homeassistant/apps/local \
        /var/lib/homeassistant/addons/local \
        /usr/share/hassio/apps/local \
        /usr/share/hassio/addons/local
    do
        [ -d "$_cand" ] || continue
        if writable_dir "$_cand"; then
            ADDONS_DIR="$_cand"
            log "Detected local add-ons path: $ADDONS_DIR"
            break
        fi
        log "WARN: $_cand exists but is not writable; skipping."
    done
    if [ -z "$ADDONS_DIR" ]; then
        die "could not find a writable local add-ons directory (probed /addons, /data/{apps,addons}/local, /mnt/data/supervisor/{apps,addons}/local, /var/lib/homeassistant/{apps,addons}/local, /usr/share/hassio/{apps,addons}/local). Pass --addons-dir explicitly. Inside the SSH/Samba add-on use --addons-dir /addons; on the HAOS host console use --addons-dir /mnt/data/supervisor/apps/local. Re-run e.g.: curl -fsSL $SCRIPT_URL | sh -s -- --addons-dir /addons"
    fi
else
    [ -d "$ADDONS_DIR" ] || die "add-ons directory does not exist: $ADDONS_DIR"
fi

ADDON_DIR="$ADDONS_DIR/$ADDON_SLUG"

# --- Detect MA container & Python version (best effort) ---------------------

if [ -z "$MA_ID" ]; then
    if command -v docker >/dev/null 2>&1; then
        MA_ID="$(docker ps --format '{{.Names}}' 2>/dev/null \
                 | grep -E '^(addon|app)_[0-9a-f]+_music_assistant(_beta|_nightly|_dev)?$' \
                 | head -n1 || true)"
    fi
    if [ -z "$MA_ID" ]; then
        MA_ID="app_d5369777_music_assistant"
        log "WARN: could not auto-detect MA container; using fallback '$MA_ID'."
        log "      Verify with: docker ps | grep music"
        log "      then re-run with the right id, e.g.:"
        log "        curl -fsSL $SCRIPT_URL | sh -s -- --ma-id <ID>"
    else
        log "Detected MA container: $MA_ID"
    fi
fi

if [ -z "$PYTHON_VERSION" ]; then
    if command -v docker >/dev/null 2>&1 && [ -n "$MA_ID" ]; then
        PYTHON_VERSION="$(docker exec "$MA_ID" sh -c 'ls /app/venv/lib/ 2>/dev/null' \
                          | grep -E '^python3\.[0-9]+$' \
                          | head -n1 || true)"
    fi
    if [ -z "$PYTHON_VERSION" ]; then
        PYTHON_VERSION="python3.13"
        log "WARN: could not auto-detect Python version; using fallback '$PYTHON_VERSION'."
    else
        log "Detected MA Python version: $PYTHON_VERSION"
    fi
fi

# --- Idempotency check ------------------------------------------------------

if [ -e "$ADDON_DIR" ]; then
    if [ "$FORCE" -ne 1 ]; then
        printf '%s already exists. Overwrite? [y/N] ' "$ADDON_DIR"
        read -r reply
        case "$reply" in
            y|Y|yes|YES) ;;
            *) die "aborted by user (use --force to skip this prompt)" ;;
        esac
    fi
    log "Removing existing $ADDON_DIR"
    rm -rf "$ADDON_DIR"
fi

# --- Download repo tarball --------------------------------------------------

TMPDIR="$(mktemp -d 2>/dev/null || mktemp -d -t maw)"
trap 'rm -rf "$TMPDIR"' EXIT INT TERM

TARBALL_URL="https://codeload.github.com/$REPO_OWNER/$REPO_NAME/tar.gz/refs/heads/$REF"
log "Downloading $TARBALL_URL"
curl -fsSL "$TARBALL_URL" -o "$TMPDIR/repo.tar.gz" \
    || die "download failed (check --ref or your network)"

log "Extracting..."
tar -xzf "$TMPDIR/repo.tar.gz" -C "$TMPDIR" \
    || die "extraction failed (corrupt archive?)"

# Tarball top-level dir is "<repo>-<ref>" with slashes in ref replaced by '-'.
SAFE_REF="$(printf '%s' "$REF" | tr '/' '-')"
SRC_ROOT="$TMPDIR/$REPO_NAME-$SAFE_REF"
[ -d "$SRC_ROOT/ytmusic_free" ] \
    || die "ytmusic_free/ not found in archive at $SRC_ROOT"

# --- Build the add-on directory ---------------------------------------------

log "Creating $ADDON_DIR"
mkdir -p "$ADDON_DIR"
cp -R "$SRC_ROOT/ytmusic_free" "$ADDON_DIR/ytmusic_free"

# Guard values that get interpolated into run.sh (unquoted heredoc) + TARBALL_URL
# against shell metacharacters, so operator input can't inject code into the
# root-run watcher. Conservative charset covers real owners/refs/ids/versions.
for _pair in "repo-owner:$REPO_OWNER" "ref:$REF" \
             "monochrome-repo:$MONOCHROME_REPO" "monochrome-ref:$MONOCHROME_REF" \
             "ma-id:$MA_ID" "python-version:$PYTHON_VERSION"; do
    _val="${_pair#*:}"
    case "$_val" in
        ""|*[!A-Za-z0-9._/-]*) die "invalid --${_pair%%:*} value '$_val' (allowed: letters digits . _ / -)" ;;
    esac
done

log "Writing config.yaml"
cat > "$ADDON_DIR/config.yaml" <<EOF
name: "$ADDON_NAME"
description: "Keeps YouTube Music Free and Monochrome installed in Music Assistant."
version: "$ADDON_VERSION"
slug: $ADDON_SLUG
init: false
boot: auto
docker_api: true
arch:
  - aarch64
  - amd64
  - armhf
  - armv7
  - i386
options:
  auto_update: false
  update_interval_hours: 24
  monochrome_enabled: true
  github_token: ""
schema:
  auto_update: bool
  update_interval_hours: int(1,)
  monochrome_enabled: bool
  github_token: password
EOF

log "Writing translations/en.yaml"
mkdir -p "$ADDON_DIR/translations"
cat > "$ADDON_DIR/translations/en.yaml" <<'EOF'
configuration:
  auto_update:
    name: Keep providers up to date
    description: >-
      Off by default. When enabled, periodically check GitHub for newer
      ytmusic_free and Monochrome providers and reinstall them (restarting Music
      Assistant once) only when code changed. Note this downloads and runs
      branch-head code inside Music Assistant unattended. This is NOT the
      add-on's own "Auto update" control on the Info tab, which updates the
      watcher add-on itself; this option updates the music providers.
  update_interval_hours:
    name: Check the provider for updates every (hours)
    description: >-
      How often to check GitHub for a newer provider, in hours. 24 = once a
      day, 168 = weekly, 1 = hourly. Minimum 1 hour.
  monochrome_enabled:
    name: Install the Monochrome provider
    description: >-
      Keep the Monochrome provider installed and update it from its configured
      private GitHub repository.
  github_token:
    name: GitHub personal access token
    description: >-
      Token used only to read the private Monochrome repository. The token is
      never written to logs. A classic token may also carry read:packages for
      private GHCR pulls, but this watcher only uses repository access.
EOF

log "Writing build.yaml"
cat > "$ADDON_DIR/build.yaml" <<'EOF'
build_from:
  aarch64: ghcr.io/home-assistant/aarch64-base:latest
  amd64: ghcr.io/home-assistant/amd64-base:latest
  armhf: ghcr.io/home-assistant/armhf-base:latest
  armv7: ghcr.io/home-assistant/armv7-base:latest
  i386: ghcr.io/home-assistant/i386-base:latest
EOF

log "Writing Dockerfile"
cat > "$ADDON_DIR/Dockerfile" <<'EOF'
ARG BUILD_FROM
FROM $BUILD_FROM

RUN apk add --no-cache docker-cli bash curl tar jq

COPY ytmusic_free/ /provider/ytmusic_free/

COPY watcher_lib.sh /watcher_lib.sh
COPY run.sh /run.sh
RUN chmod +x /run.sh && sed -i 's/\r//' /run.sh /watcher_lib.sh

ENTRYPOINT ["/run.sh"]
EOF

log "Writing watcher_lib.sh"
# Sourceable helpers, unit-testable without docker/network. Quoted heredoc: no
# install-time interpolation — pure runtime logic. Callers set CACHE / BUNDLED /
# HASHFILE / TARBALL_URL first.
cat > "$ADDON_DIR/watcher_lib.sh" <<'LIBEOF'
#!/usr/bin/env bash
# Helpers for the MA Provider Watcher. Source this, then call read_options.

# read_options [options.json path] -> sets update and Monochrome configuration.
# Boolean is parsed WITHOUT jq's `//` (which coerces an explicit false to the
# default); auto-update is opt-in, so anything but an explicit true is false.
read_options() {
    f="${1:-/data/options.json}"
    AUTO_UPDATE="false"; UPDATE_INTERVAL_HOURS=24
    MONOCHROME_ENABLED="true"; GITHUB_TOKEN=""
    if [ -r "$f" ]; then
        AUTO_UPDATE="$(jq -r 'if .auto_update == true then "true" else "false" end' "$f" 2>/dev/null || echo false)"
        UPDATE_INTERVAL_HOURS="$(jq -r 'if (.update_interval_hours|type)=="number" then (.update_interval_hours|floor) else 24 end' "$f" 2>/dev/null || echo 24)"
        MONOCHROME_ENABLED="$(jq -r 'if .monochrome_enabled == false then "false" else "true" end' "$f" 2>/dev/null || echo true)"
        GITHUB_TOKEN="$(jq -r 'if (.github_token|type)=="string" then .github_token else "" end' "$f" 2>/dev/null || true)"
    fi
    case "$UPDATE_INTERVAL_HOURS" in ''|*[!0-9-]*) UPDATE_INTERVAL_HOURS=24 ;; esac   # non-integer -> default
    [ "$UPDATE_INTERVAL_HOURS" -lt 1 ] 2>/dev/null && UPDATE_INTERVAL_HOURS=1          # 0/negative -> 1
    UPDATE_INTERVAL=$((UPDATE_INTERVAL_HOURS * 3600))
}

# Inject source: the auto-updated cache in /data when auto-update is ENABLED and a
# cache exists, else the copy baked into the image at build time. Disabling
# auto-update reverts to the bundled copy (the cache is kept for re-enabling), so
# opting out actually stops running fetched branch-head code. /data survives
# add-on rebuilds.
provider_src() { if [ "${AUTO_UPDATE:-false}" = "true" ] && [ -d "$CACHE" ]; then printf '%s' "$CACHE"; else printf '%s' "$BUNDLED"; fi; }

# Monochrome is sourced from its persistent private-repository cache. There is
# intentionally no baked copy: the watcher fork remains public and never
# contains Monochrome source or credentials.
monochrome_src() {
    if [ "${MONOCHROME_ENABLED:-true}" = "true" ] && [ -d "$MONOCHROME_CACHE" ]; then
        printf '%s' "$MONOCHROME_CACHE"
    fi
}

# Fetch one provider directory from an archive into an atomic persistent cache.
# Arguments: provider_dir archive_url cache_dir hash_file token log_label
# Return: 0 = updated, 2 = unchanged, 1 = fetch/parse failed.
fetch_provider() {
    provider_dir="$1"; archive_url="$2"; cache_dir="$3"
    hash_file="$4"; token="$5"; log_label="$6"
    tmp="$(mktemp -d 2>/dev/null || mktemp -d -t maw)" || return 1
    curl_args=(-fsSL --connect-timeout 10 --max-time 120)
    if [ -n "$token" ]; then
        curl_args+=(-H "Authorization: Bearer ${token}" -H "Accept: application/vnd.github+json")
    fi
    if ! curl "${curl_args[@]}" "$archive_url" -o "$tmp/p.tgz" 2>/dev/null; then
        echo "$log_label update: download failed"
        rm -rf "$tmp"
        return 1
    fi
    if ! tar -xzf "$tmp/p.tgz" -C "$tmp" 2>/dev/null; then
        echo "$log_label update: extract failed"
        rm -rf "$tmp"
        return 1
    fi
    nd="$(find "$tmp" -maxdepth 4 -type d -name "$provider_dir" 2>/dev/null | head -n1)"
    if [ -z "$nd" ]; then
        echo "$log_label update: $provider_dir not found in tarball"
        rm -rf "$tmp"
        return 1
    fi
    nh="$( (cd "$nd" && find . -type f -exec sha256sum {} \; 2>/dev/null | sort) | sha256sum | awk '{print $1}')"
    oh="$(cat "$hash_file" 2>/dev/null || echo none)"
    if [ "$nh" = "$oh" ] && [ -d "$cache_dir" ]; then
        rm -rf "$tmp"
        return 2
    fi
    rm -rf "$cache_dir.new"
    mkdir -p "$cache_dir.new" && cp -a "$nd/." "$cache_dir.new/" \
        || { rm -rf "$tmp" "$cache_dir.new"; return 1; }
    rm -rf "$cache_dir" && mv "$cache_dir.new" "$cache_dir" \
        || { rm -rf "$tmp"; return 1; }
    printf '%s\n' "$nh" > "$hash_file"
    echo "$log_label update: cached new provider ($nh)"
    rm -rf "$tmp"
    return 0
}

# Fetch the latest provider from GitHub into $CACHE.
# Return: 0 = updated (changed), 2 = unchanged, 1 = fetch/parse failed.
fetch_latest() {
    fetch_provider ytmusic_free "$TARBALL_URL" "$CACHE" "$HASHFILE" "" "ytmusic_free"
}

fetch_monochrome() {
    if [ -z "${GITHUB_TOKEN:-}" ]; then
        echo "monochrome update: GitHub token is missing"
        return 1
    fi
    fetch_provider monochrome "$MONOCHROME_TARBALL_URL" "$MONOCHROME_CACHE" \
        "$MONOCHROME_HASHFILE" "$GITHUB_TOKEN" "monochrome"
}
LIBEOF

log "Writing run.sh (MA=$MA_ID, $PYTHON_VERSION)"
cat > "$ADDON_DIR/run.sh" <<EOF
#!/usr/bin/env bash

MA="$MA_ID"
BUNDLED="/provider/ytmusic_free"
CACHE="/data/ytmusic_free"
HASHFILE="/data/ytmusic_free.sha256"
MONOCHROME_CACHE="/data/monochrome"
MONOCHROME_HASHFILE="/data/monochrome.sha256"
DST="/app/venv/lib/$PYTHON_VERSION/site-packages/music_assistant/providers"
# Where auto-update pulls the latest provider from. Baked from the installer's
# --repo-owner/--ref so a fork self-updates from its own source.
TARBALL_URL="https://codeload.github.com/$REPO_OWNER/$REPO_NAME/tar.gz/refs/heads/$REF"
MONOCHROME_TARBALL_URL="https://api.github.com/repos/$MONOCHROME_REPO/tarball/$MONOCHROME_REF"
# How long to wait for the configured MA container to appear before logging a
# loud ERROR. Catches the case where the installer's auto-detect fallback
# baked in a container name that does not exist on this host (issue #11).
MISSING_GRACE_SECONDS=60

# Add-on options (Configuration tab): opt-in auto-update from GitHub. Parsing +
# interval clamp live in a sourceable helper so they can be unit-tested.
. /watcher_lib.sh
read_options

echo "[\$(date)] MA Provider Watcher starting..."
echo "[\$(date)] Watching for container name: \$MA"

if ! docker info > /dev/null 2>&1; then
    echo "[\$(date)] ERROR: No Docker socket (is Protection Mode off?)"
    sleep 300
    exit 1
fi
echo "[\$(date)] Docker OK"

log() { echo "[\$(date)] \$*"; }

# Provider source and fetch helpers come from /watcher_lib.sh (sourced above).

copy_provider() {
    provider_name="\$1"
    src="\$2"
    echo "[\$(date)] Installing \$provider_name provider from \$src ..."
    # Clear any stale in-place copy so docker cp is a clean replace, not a merge:
    # files deleted upstream would otherwise linger across periodic auto-updates
    # (docker restart keeps the container filesystem). Mirrors install_provider.sh.
    docker exec "\$MA" rm -rf "\$DST/\$provider_name" 2>/dev/null || true
    docker cp "\$src" "\$MA:\$DST/" \
        && echo "[\$(date)] Copied \$provider_name OK" \
        || { echo "[\$(date)] ERROR: \$provider_name copy failed"; return 1; }
}

install_providers() {
    sleep 3
    failed=0
    copy_provider ytmusic_free "\$(provider_src)" || failed=1
    if [ "\$MONOCHROME_ENABLED" = "true" ]; then
        mono_src="\$(monochrome_src)"
        if [ -n "\$mono_src" ]; then
            copy_provider monochrome "\$mono_src" || failed=1
        else
            log "WARNING: Monochrome is enabled but no cached provider is available."
        fi
    fi
    if [ "\$failed" -ne 0 ]; then
        log "ERROR: one or more provider copies failed; MA was not restarted."
        return 1
    fi
    docker restart "\$MA" >/dev/null \
        && echo "[\$(date)] MA restarted" \
        || { echo "[\$(date)] ERROR: restart failed"; return 1; }
}

warn_if_ma_misconfigured() {
    # If the configured container name doesn't match anything, give the
    # user enough information to fix it. Always check at least one known
    # candidate so the diagnostic surfaces even when nothing matches \$MA.
    found="\$(docker ps --format '{{.Names}}' 2>/dev/null | grep -E 'music' || true)"
    echo "[\$(date)] ERROR: no container matched name '\$MA' after \${MISSING_GRACE_SECONDS}s."
    if [ -n "\$found" ]; then
        echo "[\$(date)] HINT: containers with 'music' in the name on this host:"
        printf '%s\n' "\$found" | sed "s/^/[\$(date)]   /"
        echo "[\$(date)] HINT: re-run the installer with the right --ma-id, then restart this add-on:"
        echo "[\$(date)]   curl -fsSL $SCRIPT_URL | sh -s -- --ma-id <name> --force"
    else
        echo "[\$(date)] HINT: docker ps shows no container with 'music' in the name. Is the Music Assistant add-on installed and running?"
    fi
}

# Prime the cache with the latest provider before the first inject (opt-in).
if [ "\$AUTO_UPDATE" = "true" ]; then
    log "auto-update enabled (checking every \${UPDATE_INTERVAL_HOURS}h); fetching latest providers..."
    fetch_latest || true
else
    log "auto-update disabled; using the bundled provider copy."
fi
if [ "\$MONOCHROME_ENABLED" = "true" ]; then
    # A first-time install always needs to populate Monochrome's private cache.
    # With auto-update disabled, an existing cache is deliberately left pinned.
    if [ "\$AUTO_UPDATE" = "true" ] || [ ! -d "\$MONOCHROME_CACHE" ]; then
        fetch_monochrome || true
    fi
fi
log "ytmusic_free source: \$(provider_src)"
if [ "\$MONOCHROME_ENABLED" = "true" ]; then
    mono_src="\$(monochrome_src)"
    if [ -n "\$mono_src" ]; then log "monochrome source: \$mono_src"; fi
fi

LAST_ID=\$(docker ps -q --no-trunc --filter name="\$MA" 2>/dev/null)
if [ -n "\$LAST_ID" ]; then
    echo "[\$(date)] MA running (\${LAST_ID:0:12}), installing providers..."
    install_providers
else
    echo "[\$(date)] MA not running, waiting..."
fi

echo "[\$(date)] Polling for MA container changes every 10s..."
MISSING_SINCE=0
MISSING_WARNED=0
LAST_UPDATE=\$(date +%s)
[ -z "\$LAST_ID" ] && MISSING_SINCE=\$(date +%s)
while true; do
    sleep 10
    CUR_ID=\$(docker ps -q --no-trunc --filter name="\$MA" 2>/dev/null)
    if [ -n "\$CUR_ID" ] && [ "\$CUR_ID" != "\$LAST_ID" ]; then
        echo "[\$(date)] New MA container (\${CUR_ID:0:12}), reinstalling providers..."
        LAST_ID="\$CUR_ID"
        install_providers
        MISSING_SINCE=0
        MISSING_WARNED=0
    elif [ -z "\$CUR_ID" ] && [ -n "\$LAST_ID" ]; then
        echo "[\$(date)] MA stopped"
        LAST_ID=""
        MISSING_SINCE=\$(date +%s)
    elif [ -z "\$CUR_ID" ] && [ "\$MISSING_WARNED" -eq 0 ] && [ "\$MISSING_SINCE" -gt 0 ]; then
        if [ \$((\$(date +%s) - MISSING_SINCE)) -ge "\$MISSING_GRACE_SECONDS" ]; then
            warn_if_ma_misconfigured
            MISSING_WARNED=1
        fi
    fi
    # Periodic auto-update: fetch both providers, then reinject and restart MA
    # once when either provider changed.
    if [ "\$AUTO_UPDATE" = "true" ]; then
        now=\$(date +%s)
        if [ \$((now - LAST_UPDATE)) -ge "\$UPDATE_INTERVAL" ]; then
            LAST_UPDATE=\$now
            providers_changed=0
            if fetch_latest; then providers_changed=1; fi
            if [ "\$MONOCHROME_ENABLED" = "true" ]; then
                if fetch_monochrome; then providers_changed=1; fi
            fi
            if [ "\$providers_changed" -eq 1 ]; then
                log "auto-update: provider change detected -> reinstalling"
                CUR_ID=\$(docker ps -q --no-trunc --filter name="\$MA" 2>/dev/null)
                if [ -n "\$CUR_ID" ]; then LAST_ID="\$CUR_ID"; install_providers; fi
            fi
        fi
    fi
done
EOF
chmod +x "$ADDON_DIR/run.sh" 2>/dev/null || true

# --- Done -------------------------------------------------------------------

log "Install complete: $ADDON_DIR"
cat <<EOF

Next steps:
  1. In Home Assistant: Settings -> Add-ons -> Add-on Store
     (three-dot menu) -> Check for updates.
  2. Open "$ADDON_NAME" under Local add-ons.
       First install:  click Install.
       Re-installing:  click Rebuild (three-dot menu) so the new run.sh and
                       provider files are baked into the image. A running
                       add-on keeps its old cached image until you rebuild.
  3. On the Info tab, turn Protection mode OFF (required for Docker socket access).
  4. Start the add-on and check the logs for "Copied OK" / "MA restarted".

This installer stamped version $ADDON_VERSION so Home Assistant detects the
change. If you re-ran to fix the MA container ID or Python version and the
add-on still uses the old value, Rebuild it (step 2) -- "Check for updates"
alone does not rebuild a cached local add-on image.

If MA container ID or Python version was wrong, re-run with:
  curl -fsSL $SCRIPT_URL | sh -s -- --force --ma-id <ID> --python-version <pythonX.Y>
EOF
