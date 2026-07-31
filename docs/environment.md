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
| `UVR_DATA_DIR` | Writable checkout root, else OS user data dir | Models, settings (`settings.json`), profiles, ensembles, sample/ensemble temps |
| `UVR_CACHE_DIR` | OS cache dir (`~/.cache/uvr` on Linux) | Download size cache and Politrees catalogue JSON |

On first use, legacy copies of `download_size_cache.json` / `politrees_model_links.json` in the checkout root or `UVR_DATA_DIR` are moved into `UVR_CACHE_DIR`.

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
| `UVR_AUTOCAST` | `0`/`1` | **Override** for CUDA `torch.autocast` (fp16) around model forwards only; OLA stays float32. When unset, the GUI/settings key `is_autocast` applies. Applies to VR / MDX / Roformer; Demucs stays FP32 (fp16 produces NaN stems) |
| `UVR_MODEL_SWEEP` | `1` | Enables the local-only full model sweep in `tests/test_model_sweep.py`; the sweep itself is `scripts/model_sweep.py` and never runs in CI |

---

## Headless CLI

Drive the same `JobRunner` path as the GUI without GTK:

```bash
# Use the project venv (required for kthread, soundfile, torch, …)
./.venv/bin/python -m core.cli separate /path/to/song.wav -o /tmp/uvr_out --method mdx

# Force CPU / print resolved settings
./.venv/bin/python -m core.cli separate song.wav -o /tmp/out --cpu --print-settings

# Force both stems (ignores GUI karaoke "instrumental only" defaults)
./.venv/bin/python -m core.cli separate song.wav -o /tmp/out --method mdx --stems both

# A/B autocast (two fresh subprocesses + stem null metrics)
./.venv/bin/python -m core.cli bench-ab song.wav -o /tmp/uvr_ab \
  --method mdx --model "Your Model Name" --stems both \
  --env UVR_AUTOCAST=0 --env UVR_AUTOCAST=1 \
  --json /tmp/uvr_ab/summary.json
```

Notes:

- Ensemble mode is rejected in v1 (`--method mdx|demucs|vr`).
- CLI overrides are **not** written back to `settings.json`.
- Autocast: unset `UVR_AUTOCAST` uses the persisted `is_autocast` setting; `--env UVR_AUTOCAST=…` overrides for A/B benches.
- `--model` accepts GUI display names, on-disk basenames/filenames, or a
  **unique** substring of those (`karaoke_frazer` → Frazer Roformer when only
  one installed model matches). Ambiguous queries raise before separation starts.
  Filenames are mapped to display labels for the run only (UI/settings storage
  unchanged).
- `--stems` overrides which outputs are saved for the run only
  (`both` / `primary` / `secondary` / `vocals` / `instrumental`, plus Demucs
  `bass`/`drums`/`other`). Omit to keep GUI/settings defaults (karaoke models
  may default to instrumental-only).
- `bench-ab` requires exactly two `--env KEY=value` flags; outputs land in `ab_a_*` / `ab_b_*` under `-o`.

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
