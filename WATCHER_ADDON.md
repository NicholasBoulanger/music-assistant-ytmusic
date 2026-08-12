# Provider Watcher Add-on

When Home Assistant restarts, the Supervisor recreates the MA container from its image, wiping any files you copied into it, including custom providers. The watcher add-on solves this by automatically re-copying the `ytmusic_free` and Monochrome provider files whenever the MA container is recreated.

---

## How it works

The add-on polls the MA container ID every 10 seconds. When the Supervisor recreates the MA container (new ID), the watcher copies the provider files into the new container and restarts MA so it picks up the fresh files. On first startup, the watcher also installs the provider immediately if MA is already running.

The public `ytmusic_free` files are baked into the watcher image. Private Monochrome files are downloaded with the configured GitHub token and kept in the add-on's persistent `/data` directory. The token and private source are never baked into this public watcher repository or image.

Optionally, the watcher can also keep the provider **up to date**: enable `auto_update` (opt-in, off by default) and it periodically fetches the latest provider from GitHub, then reinstalls + restarts MA **only when the code actually changed** (SHA-256 comparison). See [Auto-update](#auto-update) below.

---

## File layout

```
/mnt/data/supervisor/apps/local/ma_provider_watcher/   # HAOS 18+; older HAOS: .../addons/local/
├── build.yaml
├── config.yaml
├── Dockerfile
├── run.sh
├── watcher_lib.sh       # options, source selection, authenticated fetch + hashing
├── translations/
│   └── en.yaml          # friendly names/descriptions for the options below
└── ytmusic_free/
    ├── __init__.py
    └── manifest.json
```

---

## config.yaml

```yaml
name: "MA Provider Watcher"
description: "Keeps YouTube Music Free and Monochrome installed in Music Assistant."
version: "1.0.0"  # the installer stamps a fresh "1.0.<timestamp>" on each run so HA detects the change
slug: ma_provider_watcher
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
```

The `options`/`schema` block exposes the [Auto-update](#auto-update) settings in the add-on's **Configuration** tab. `update_interval_hours` is in hours and clamped to a minimum of 1 at runtime. A `translations/en.yaml` file gives the fields friendly names and descriptions instead of the raw keys:

```yaml
# translations/en.yaml
configuration:
  auto_update:
    name: Keep providers up to date
    description: >-
      Off by default. When enabled, periodically check GitHub for newer
      ytmusic_free and Monochrome providers and reinstall them only when code
      changed.
  update_interval_hours:
    name: Check the provider for updates every (hours)
    description: >-
      How often to check GitHub for a newer provider, in hours. 24 = once a
      day, 168 = weekly, 1 = hourly. Minimum 1 hour.
  monochrome_enabled:
    name: Install the Monochrome provider
  github_token:
    name: GitHub personal access token
    description: Token used only to read the private Monochrome repository.
```

---

## build.yaml

```yaml
build_from:
  aarch64: ghcr.io/home-assistant/aarch64-base:latest
  amd64: ghcr.io/home-assistant/amd64-base:latest
  armhf: ghcr.io/home-assistant/armhf-base:latest
  armv7: ghcr.io/home-assistant/armv7-base:latest
  i386: ghcr.io/home-assistant/i386-base:latest
```

---

## Dockerfile

```dockerfile
ARG BUILD_FROM
FROM $BUILD_FROM

RUN apk add --no-cache docker-cli bash curl tar jq

COPY ytmusic_free/ /provider/ytmusic_free/

COPY run.sh /run.sh
RUN chmod +x /run.sh && sed -i 's/\r//' /run.sh

ENTRYPOINT ["/run.sh"]
```

---

## run.sh

```bash
#!/usr/bin/env bash

MA="addon_d5369777_music_assistant"
SRC="/provider/ytmusic_free"
DST="/app/venv/lib/python3.13/site-packages/music_assistant/providers"

echo "[$(date)] MA Provider Watcher starting..."

if ! docker info > /dev/null 2>&1; then
    echo "[$(date)] ERROR: No Docker socket (is Protection Mode off?)"
    sleep 300
    exit 1
fi
echo "[$(date)] Docker OK"

install_provider() {
    echo "[$(date)] Installing ytmusic_free provider..."
    sleep 3
    docker cp "$SRC" "$MA:$DST/" && echo "[$(date)] Copied OK" || { echo "[$(date)] ERROR: cp failed"; return 1; }
    docker restart "$MA" && echo "[$(date)] MA restarted" || echo "[$(date)] ERROR: restart failed"
}

LAST_ID=$(docker ps -q --no-trunc --filter name="$MA" 2>/dev/null)
if [ -n "$LAST_ID" ]; then
    echo "[$(date)] MA running (${LAST_ID:0:12}), installing provider..."
    install_provider
else
    echo "[$(date)] MA not running, waiting..."
fi

echo "[$(date)] Polling for MA container changes every 10s..."
while true; do
    sleep 10
    CUR_ID=$(docker ps -q --no-trunc --filter name="$MA" 2>/dev/null)
    if [ -n "$CUR_ID" ] && [ "$CUR_ID" != "$LAST_ID" ]; then
        echo "[$(date)] New MA container (${CUR_ID:0:12}), reinstalling..."
        LAST_ID="$CUR_ID"
        install_provider
    elif [ -z "$CUR_ID" ] && [ -n "$LAST_ID" ]; then
        echo "[$(date)] MA stopped"
        LAST_ID=""
    fi
done
```

> **Note:** If your MA add-on ID differs from `addon_d5369777_music_assistant`, update the `MA=` line.
> Check with: `docker ps | grep music`

> **Note:** The `python3.13` in `DST=` tracks MA's Python version, which changes over time (recent Music Assistant builds use `python3.14`). The installer auto-detects it; if you edit `run.sh` by hand, set it to match.
> Check with: `docker exec addon_d5369777_music_assistant ls /app/venv/lib/`

> **Note:** The `run.sh` above is the minimal core (re-inject after container recreation). The `run.sh` that the installer generates additionally implements [Auto-update](#auto-update): it reads all four Configuration options from `/data/options.json`, fetches the enabled providers into `/data` caches, and reinstalls only when a SHA-256 changes.

---

## Quick install (recommended)

For most users the [`scripts/install_watcher_addon.sh`](scripts/install_watcher_addon.sh) installer handles steps 1-3 below automatically:

```bash
curl -fsSL https://raw.githubusercontent.com/sproft/music-assistant-ytmusic/main/scripts/install_watcher_addon.sh | sh
```

The script is POSIX `sh` (works on HAOS BusyBox `ash`), uses `curl + tar` instead of `git`, auto-detects the local add-ons path (HAOS `apps/local` and legacy `addons/local`, Supervised, and the in-add-on `/addons` mapping), and tries to detect the MA container ID and Python venv version. After it finishes, jump to [step 4 (Install the add-on)](#4-install-the-add-on) below.

> **Re-running the installer? Rebuild the add-on.** The provider files and `run.sh` are baked into the add-on image at build time. If the add-on is already installed and you re-run the script (for example to fix `--python-version` or `--ma-id`), Home Assistant keeps the cached image until you rebuild it: open the add-on → three-dot menu → **Rebuild**, then **Start**. The installer stamps a fresh version on every run so "Check for updates" flags the change, but a cached image is only replaced by a rebuild.
>
> **Getting the new options after an upgrade from a version without them:** the Supervisor caches a local add-on's config schema at install time. If you had an older watcher installed, a Rebuild alone may not surface `auto_update`, `update_interval_hours`, `monochrome_enabled`, and `github_token`; the schema is only re-read on an **update**. Do **Check for updates**, then **Update** the add-on (three-dot menu). A fresh install shows them immediately.

Common flags:
- `--force`: overwrite an existing install without prompting
- `--ref TAG`: pin to a release tag instead of `main`
- `--ma-id ID` / `--python-version pythonX.Y`: override auto-detection
- `--addons-dir DIR`: skip path auto-detection (useful for non-standard installs)

Run `sh install_watcher_addon.sh --help` to see all options.

> **Passing flags through `curl | sh`:** if you re-run the one-liner with a flag, use `sh -s --` as a separator so the flag goes to the script and not to `sh` itself:
>
> ```bash
> curl -fsSL https://raw.githubusercontent.com/sproft/music-assistant-ytmusic/main/scripts/install_watcher_addon.sh | sh -s -- --force
> ```
>
> `curl ... | sh --force` parses `--force` as a shell option and fails with `sh: bad option '--force'`.

> **Auto-detection caveats:** the MA container ID and Python version are detected via `docker ps` / `docker exec`, which requires running the script from a host shell with Docker access (e.g. the SSH & Web Terminal add-on with Protection Mode off, or the host shell on a Supervised install). If detection fails, the script falls back to `addon_d5369777_music_assistant` and `python3.13` and prints a warning, so verify and re-run with `--ma-id` / `--python-version` if those defaults are wrong for your install.

---

## Manual installation

### 1. Create the add-on directory

Open the Terminal add-on and create the directory structure. The path depends on your HA installation type:

| Installation | Local add-ons path |
|---|---|
| **HAOS 18+** | `/mnt/data/supervisor/apps/local/` |
| **HAOS (older)** | `/mnt/data/supervisor/addons/local/` |
| **Supervised** | `/usr/share/hassio/apps/local/` (older: `/usr/share/hassio/addons/local/`) |
| **Inside the SSH / Samba add-on** | `/addons/` |

> Home Assistant renamed the Supervisor `addons` tree to `apps` (HAOS 18+, the same rename behind `ha apps` replacing `ha addons`). On upgrade the Supervisor migrates existing local add-ons from `addons/local` to `apps/local`. From the HAOS host console, find yours with `find /mnt/data/supervisor -maxdepth 3 -type d -name local`.

```bash
# HAOS 18+ (host console)
mkdir -p /mnt/data/supervisor/apps/local/ma_provider_watcher

# Inside the SSH / Samba add-on
mkdir -p /addons/ma_provider_watcher
```

### 2. Copy the provider files

Copy the `ytmusic_free` provider folder into the add-on directory (use whichever
path matches your shell from the table above: `/addons/...` inside the SSH/Samba
add-on, or the `/mnt/data/supervisor/...` host path from the HAOS console):

```bash
# Inside the SSH / Samba add-on
cp -r /path/to/ytmusic_free /addons/ma_provider_watcher/ytmusic_free
```

### 3. Create the add-on files

Create `config.yaml`, `build.yaml`, `Dockerfile`, and `run.sh` as shown above.

<a id="4-install-the-add-on"></a>
### 4. Install the add-on

In Home Assistant: **Settings → Add-ons → Add-on Store** (three-dot menu) → **Check for updates**. The **MA Provider Watcher** appears under **Local add-ons**. Click → **Install**.

### 5. Disable Protection Mode

Go to the add-on's **Info** tab and turn **Protection mode OFF**. This is required. Without it, the Docker socket is not mounted and the add-on cannot manage MA containers.

### 6. Start and verify

Start the add-on and check the logs. You should see:

```
Docker OK
MA running (...), installing provider...
Copied OK
MA restarted
Polling for MA container changes every 10s...
```

---

## Updating the provider

When you update the `ytmusic_free` provider code, copy the new files into the add-on directory and rebuild (path as in the table above: `/addons/...` inside the SSH/Samba add-on):

```bash
cp -r /path/to/ytmusic_free /addons/ma_provider_watcher/ytmusic_free
ha apps rebuild local_ma_provider_watcher
ha apps restart local_ma_provider_watcher
```

Or let the watcher do it for you, see [Auto-update](#auto-update).

---

<a id="auto-update"></a>
## Auto-update

The watcher can keep both providers current on its own. It follows the original `ytmusic_free` repository and the configured private Monochrome repository independently.

### Options

Set these in the add-on's **Configuration** tab (or `options` in `config.yaml`):

| Option | Type | Default | Description |
|---|---|---|---|
| `auto_update` | bool | `false` | Off by default (opt-in). When on, the watcher periodically checks GitHub for a newer provider and reinstalls it. Note it then runs branch-head code inside MA unattended. Leave off to pin to the version baked into the image. |
| `update_interval_hours` | int (hours) | `24` | How often to check. `24` = daily, `168` = weekly, `1` = hourly. Clamped to a minimum of `1` at runtime; invalid values fall back to the default. |
| `monochrome_enabled` | bool | `true` | Downloads, installs, and watches the private Monochrome provider. |
| `github_token` | password | empty | PAT used to read the private Monochrome repository. It is masked in the UI and never logged. A classic PAT needs the `repo` scope; a fine-grained PAT needs Contents read access to that repository. |

You can change the sources when running the installer with `--ref`, `--monochrome-repo OWNER/REPO`, and `--monochrome-ref`. By default it follows `sproft/music-assistant-ytmusic:main` and `NicholasBoulanger/music-assistant-monochrome:main`.

### How it works

1. On first startup, the watcher uses the PAT to populate `/data/monochrome` from the private repository. The public `ytmusic_free` copy is already baked into the image.
2. With `auto_update` enabled, it checks both repositories every `update_interval_hours` and compares the SHA-256 of each provider with its persistent cache.
3. **Only if either provider changed**, it copies both current providers into the MA container and restarts MA once. Unchanged checks are a no-op.
4. If a fetch fails, the watcher logs a warning and keeps the last cached copy. A first-time Monochrome fetch without a valid PAT cannot install Monochrome, but it does not prevent `ytmusic_free` from being installed.

Once a newer version has been cached, it also survives MA container recreation: the watcher installs from the cache in preference to the image-baked copy.

### Logs

With auto-update active you'll see lines such as:

```
ytmusic_free source: /data/ytmusic_free
monochrome source: /data/monochrome
auto-update: provider change detected -> reinstalling
```

If `auto_update` is `false`, the watcher fetches Monochrome only when its persistent cache is empty, then pins both provider versions and re-injects them on container recreation.

---

## Troubleshooting

**`monochrome update: GitHub token is missing` or `download failed`**
- In the add-on's **Configuration** tab, paste a PAT that can read `NicholasBoulanger/music-assistant-monochrome`, save, and restart the watcher.
- If the same classic PAT pulls a private GHCR image, it can carry both `repo` and `read:packages`; the watcher itself only needs repository access.

**`ERROR: No Docker socket (is Protection Mode off?)`**
- Turn **Protection mode OFF** in the add-on settings. This is the most common issue.

**`lstat /provider: no such file or directory`**
- The `ytmusic_free/` folder is missing from the add-on directory. Copy it and rebuild.

**`could not find local add-ons directory. Pass --addons-dir explicitly.`**
- The installer probed the known locations and none existed in your shell. Most often this is HAOS 18+, where the path moved from `addons/local` to `apps/local`.
- From the HAOS host console, locate it: `find /mnt/data/supervisor -maxdepth 3 -type d -name local`, then re-run with `--addons-dir /mnt/data/supervisor/apps/local`.
- Inside the SSH / Samba add-on the path is usually `/addons`, so re-run with `--addons-dir /addons`.

**Add-on not found in store**
- Ensure `config.yaml` and `build.yaml` are valid YAML. Check Supervisor logs: `ha supervisor logs | grep ma_provider`.
- Run `ha supervisor reload` and wait 30 seconds.

**Provider still missing after HA restart**
- Check the watcher logs for `cp failed` or `restart failed` errors.
- Confirm the MA container name matches `MA=` in `run.sh`.

**`cp failed` with `Could not find the file /app/venv/lib/pythonX.Y/...`, or re-running the installer changes nothing**
- The add-on is running a cached image with the old `run.sh` (wrong Python version or MA ID baked in). Re-running the installer updates the files on disk but not the running image.
- Rebuild the add-on: open it → three-dot menu → **Rebuild**, then **Start** (or `ha apps rebuild local_ma_provider_watcher && ha apps restart local_ma_provider_watcher`).
- Confirm the Python version MA actually uses with `docker exec <ma-id> ls /app/venv/lib/`, and re-run with `--python-version pythonX.Y` if it differs.
