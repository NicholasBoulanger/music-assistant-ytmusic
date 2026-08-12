#!/usr/bin/env bash
# Helpers for the MA Provider Watcher. Source this, then call read_options.

# read_options [options.json path] -> sets update and Monochrome configuration.
# Booleans are parsed WITHOUT jq's `//` (which coerces an explicit false to the
# default). The old combined auto_update key is honored only when a new per-
# provider key is absent, making upgrades backward compatible.
read_options() {
    f="${1:-/data/options.json}"
    YTMUSIC_AUTO_UPDATE="false"; MONOCHROME_AUTO_UPDATE="false"
    YTMUSIC_ACTIVE_VERSION="current"; MONOCHROME_ACTIVE_VERSION="current"
    UPDATE_INTERVAL_HOURS=24
    MONOCHROME_ENABLED="true"; GITHUB_TOKEN=""
    MA_CONTAINER="auto"; MA_PYTHON_VERSION="auto"
    if [ -r "$f" ]; then
        YTMUSIC_AUTO_UPDATE="$(jq -r 'if has("ytmusic_auto_update") then (if .ytmusic_auto_update == true then "true" else "false" end) elif .auto_update == true then "true" else "false" end' "$f" 2>/dev/null || echo false)"
        MONOCHROME_AUTO_UPDATE="$(jq -r 'if has("monochrome_auto_update") then (if .monochrome_auto_update == true then "true" else "false" end) elif .auto_update == true then "true" else "false" end' "$f" 2>/dev/null || echo false)"
        YTMUSIC_ACTIVE_VERSION="$(jq -r 'if .ytmusic_active_version == "previous" then "previous" else "current" end' "$f" 2>/dev/null || echo current)"
        MONOCHROME_ACTIVE_VERSION="$(jq -r 'if .monochrome_active_version == "previous" then "previous" else "current" end' "$f" 2>/dev/null || echo current)"
        UPDATE_INTERVAL_HOURS="$(jq -r 'if (.update_interval_hours|type)=="number" then (.update_interval_hours|floor) else 24 end' "$f" 2>/dev/null || echo 24)"
        MONOCHROME_ENABLED="$(jq -r 'if .monochrome_enabled == false then "false" else "true" end' "$f" 2>/dev/null || echo true)"
        MA_CONTAINER="$(jq -r 'if (.ma_container|type)=="string" and (.ma_container|length)>0 then .ma_container else "auto" end' "$f" 2>/dev/null || echo auto)"
        MA_PYTHON_VERSION="$(jq -r 'if (.python_version|type)=="string" and (.python_version|length)>0 then .python_version else "auto" end' "$f" 2>/dev/null || echo auto)"
        GITHUB_TOKEN="$(jq -r 'if (.github_token|type)=="string" then .github_token else "" end' "$f" 2>/dev/null || true)"
    fi
    case "$UPDATE_INTERVAL_HOURS" in ''|*[!0-9-]*) UPDATE_INTERVAL_HOURS=24 ;; esac   # non-integer -> default
    [ "$UPDATE_INTERVAL_HOURS" -lt 1 ] 2>/dev/null && UPDATE_INTERVAL_HOURS=1          # 0/negative -> 1
    UPDATE_INTERVAL=$((UPDATE_INTERVAL_HOURS * 3600))
}

# Select the configured persistent slot. YouTube falls back to its image-bundled
# copy before the first cache is created; Monochrome has no public bundled copy.
provider_src() {
    if [ "${YTMUSIC_ACTIVE_VERSION:-current}" = "previous" ]; then
        if [ -d "$PREVIOUS_CACHE" ]; then printf '%s' "$PREVIOUS_CACHE"; else printf '%s' "$BUNDLED"; fi
    elif [ -d "$CACHE" ]; then
        printf '%s' "$CACHE"
    else
        printf '%s' "$BUNDLED"
    fi
}

# Monochrome is sourced from its persistent private-repository cache. There is
# intentionally no baked copy: the watcher fork remains public and never
# contains Monochrome source or credentials.
monochrome_src() {
    if [ "${MONOCHROME_ENABLED:-true}" != "true" ]; then return; fi
    if [ "${MONOCHROME_ACTIVE_VERSION:-current}" = "previous" ] && [ -d "$MONOCHROME_PREVIOUS_CACHE" ]; then
        printf '%s' "$MONOCHROME_PREVIOUS_CACHE"
    elif [ -d "$MONOCHROME_CACHE" ]; then
        printf '%s' "$MONOCHROME_CACHE"
    fi
}

provider_hash() {
    (cd "$1" && find . -type f -exec sha256sum {} \; 2>/dev/null | sort) \
        | sha256sum | awk '{print $1}'
}

# Promote a validated directory to current and rotate the former current into
# previous. Arguments: source hash cache hashfile datefile previous-cache
# previous-hash previous-date label.
promote_provider() {
    source_dir="$1"; new_hash="$2"; cache_dir="$3"; hash_file="$4"
    date_file="$5"; previous_cache="$6"; previous_hash="$7"
    previous_date="$8"; log_label="$9"
    stage="${cache_dir}.new"; previous_stage="${previous_cache}.new"
    rm -rf "$stage" "$previous_stage"
    mkdir -p "$stage" && cp -a "$source_dir/." "$stage/" || { rm -rf "$stage"; return 1; }
    if [ -d "$cache_dir" ]; then
        mkdir -p "$previous_stage" && cp -a "$cache_dir/." "$previous_stage/" \
            || { rm -rf "$stage" "$previous_stage"; return 1; }
        rm -rf "$previous_cache" && mv "$previous_stage" "$previous_cache" || return 1
        if [ -f "$hash_file" ]; then cp "$hash_file" "$previous_hash"; else provider_hash "$previous_cache" > "$previous_hash"; fi
        if [ -f "$date_file" ]; then cp "$date_file" "$previous_date"; else date -u +'%Y-%m-%dT%H:%M:%SZ' > "$previous_date"; fi
    fi
    rm -rf "$cache_dir"
    if ! mv "$stage" "$cache_dir"; then
        [ -d "$previous_cache" ] && cp -a "$previous_cache" "$cache_dir"
        return 1
    fi
    printf '%s\n' "$new_hash" > "$hash_file"
    date -u +'%Y-%m-%dT%H:%M:%SZ' > "$date_file"
    echo "$log_label update: cached new provider ($new_hash)"
}

# Fetch one provider directory from an archive into an atomic persistent cache.
# Arguments: provider_dir archive_url cache_dir hash_file date_file token
# log_label previous_cache previous_hash previous_date
# Return: 0 = updated, 2 = unchanged, 1 = fetch/parse failed.
fetch_provider() {
    provider_dir="$1"; archive_url="$2"; cache_dir="$3"
    hash_file="$4"; date_file="$5"; token="$6"; log_label="$7"
    previous_cache="$8"; previous_hash="$9"; previous_date="${10}"
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
    if [ ! -f "$nd/__init__.py" ] || [ ! -f "$nd/manifest.json" ]; then
        echo "$log_label update: provider is missing __init__.py or manifest.json"
        rm -rf "$tmp"
        return 1
    fi
    nh="$(provider_hash "$nd")"
    oh="$(cat "$hash_file" 2>/dev/null || echo none)"
    if [ "$nh" = "$oh" ] && [ -d "$cache_dir" ]; then
        rm -rf "$tmp"
        return 2
    fi
    promote_provider "$nd" "$nh" "$cache_dir" "$hash_file" "$date_file" \
        "$previous_cache" "$previous_hash" "$previous_date" "$log_label" \
        || { rm -rf "$tmp"; return 1; }
    rm -rf "$tmp"
    return 0
}

# Fetch the latest provider from GitHub into $CACHE.
# Return: 0 = updated (changed), 2 = unchanged, 1 = fetch/parse failed.
fetch_latest() {
    fetch_provider ytmusic_free "$TARBALL_URL" "$CACHE" "$HASHFILE" "$DATEFILE" \
        "" "ytmusic_free" "$PREVIOUS_CACHE" "$PREVIOUS_HASHFILE" "$PREVIOUS_DATEFILE"
}

fetch_monochrome() {
    if [ -z "${GITHUB_TOKEN:-}" ]; then
        echo "monochrome update: GitHub token is missing"
        return 1
    fi
    fetch_provider monochrome "$MONOCHROME_TARBALL_URL" "$MONOCHROME_CACHE" \
        "$MONOCHROME_HASHFILE" "$MONOCHROME_DATEFILE" "$GITHUB_TOKEN" "monochrome" \
        "$MONOCHROME_PREVIOUS_CACHE" "$MONOCHROME_PREVIOUS_HASHFILE" \
        "$MONOCHROME_PREVIOUS_DATEFILE"
}
