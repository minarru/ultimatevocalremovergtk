# Environment variables

Optional variables read by the GTK app, launcher scripts, and installer. Set them **before** starting the app (prefix the command or export in your shell).

```bash
# bash
UVR_DEV_CSS=1 ./run_uvr.sh

# fish
env UVR_DEV_CSS=1 ./run_uvr.sh
```

For GLib debug logging details and component names, see also `core/debug_log.py`.

---

## Runtime data paths

| Variable | Default | Purpose |
|----------|---------|---------|
| `UVR_DATA_DIR` | Writable checkout root, else OS user data dir | Models, settings (`data.pkl`), profiles, ensembles |
| `UVR_CACHE_DIR` | OS cache dir under `ultimatevocalremover` | Cache override |

Standard XDG / platform paths (`XDG_DATA_HOME`, `XDG_CACHE_HOME`, `LOCALAPPDATA`) apply when UVR-specific vars are unset. See `core/paths.py` and `core/platform.py`.

---

## Logging and debug

| Variable | Example | Purpose |
|----------|---------|---------|
| `G_MESSAGES_DEBUG` | `uvr` · `uvr-ui,uvr-download` · `all` | GLib debug domains (`uvr-*` shorthands expanded at launch) |
| `UVR_LOG_FILE` | `/tmp/uvr.log` | Mirror debug output to a plain-text file |
| `UVR_VERBOSE` | `1` | High-frequency trace (`uvr-trace`; progress ticks, worker polls) |

**Components:** `ui`, `dispatch`, `trace`, `worker`, `separate`, `cleanup`, `model`, `audio`, `download`, `error`, `settings`.

**Suggested profiles:**

```bash
# UI and settings
G_MESSAGES_DEBUG=uvr-ui,uvr-settings,uvr-error python -m ui

# Separation run
G_MESSAGES_DEBUG=uvr-ui,uvr-worker,uvr-dispatch,uvr-separate,uvr-model,uvr-error python -m ui

# File + domains
G_MESSAGES_DEBUG=uvr-download UVR_LOG_FILE=/tmp/uvr.log python -m ui
```

`run_uvr.sh` normalizes `G_MESSAGES_DEBUG` and prints a hint when debug vars are set. A second instance exits immediately (single-instance app) — use `journalctl --user -f` or `UVR_LOG_FILE` + `tail -f` on a running session.

---

## Downloads and catalogues

| Variable | Values | Purpose |
|----------|--------|---------|
| `UVR_DISABLE_POLITREES` | `1`, `true`, `yes` | Use only the official TRvlvr catalogue (skip Politrees community models) |
| `UVR_INSECURE_DOWNLOADS` | `1` | Disable TLS certificate verification (**dev only**) |

---

## External tools

| Variable | Purpose |
|----------|---------|
| `UVR_FFMPEG` | Path to `ffmpeg` when not on `PATH` |
| `UVR_RUBBERBAND` | Path to `rubberband` when not on `PATH` |

---

## Startup / workers

| Variable | Values | Purpose |
|----------|--------|---------|
| `UVR_SKIP_SEPARATE_WARMUP` | `1` | Skip background import of separation engines at startup (loads on first run instead) |

---

## UI development

| Variable | Values | Purpose |
|----------|--------|---------|
| `UVR_DEV_CSS` | `1` | Load `resources/style.css` from disk with live reload (skip bundled copy for CSS) |
| `UVR_DEBUG_QUEUE` | `1` | Seed fake download queue rows for popover styling |
| `UVR_DEBUG_QUEUE_CHIP` | `1` · `cycle` · `active` · `success,partial` | Cycle or pin header chip visual states |
| `UVR_DEBUG_QUEUE_CHIP_INTERVAL` | seconds (default `4`) | Interval between chip debug scenarios |
| `UVR_DEBUG_QUEUE_POPUP` | `1` | Open download popover on window map (disables autohide) |
| `UVR_DEBUG_QUEUE_STICKY` | `1` | Never auto-dismiss finished queue items; keep chip visible when empty |

**Chip debug example** (visual QA for morph icons and labels):

```bash
UVR_DEBUG_QUEUE_CHIP=1 UVR_DEBUG_QUEUE_POPUP=1 UVR_DEV_CSS=1 ./run_uvr.sh
```

Scenarios cycled by `UVR_DEBUG_QUEUE_CHIP=1`: `active`, `success`, `partial`, `failed`, `cancelled`.

---

## Launcher (`run_uvr.sh`)

| Variable | Default | Purpose |
|----------|---------|---------|
| `UVR_AUTO_REBUILD` | `auto` | Venv rebuild when stale: `auto` · `always` · `never` |
| `UVR_SKIP_CHECK` | `0` | Skip GTK import health check on the venv |

---

## Installer (`install_packages.sh`)

| Variable | Default | Purpose |
|----------|---------|---------|
| `UVR_VENV_DIR` | `./.venv` | Virtual environment directory |
| `UVR_PYTHON_VERSION` | `3.12` | Python version for uv-managed (fallback) installs |
| `UVR_INSTALL_MODE` | `system` | `system` (system site-packages) or `fallback` (uv-managed 3.12) |
| `UVR_SYSTEM_PYTHON` | `/usr/bin/python3` | System interpreter for `system` mode |
| `PYTHON_BIN` | `python3` | Python executable passed to the installer |
| `UVR_SKIP_SYSTEM_DEPS` | `0` | Skip distro package install step |
| `UVR_PRIVDROP_DONE` | — | Internal: set when installer re-execs as non-root after `sudo` |

Repository mirroring (GitHub backup, deploy keys) is documented in [mirroring.md](mirroring.md) — not part of app runtime.
