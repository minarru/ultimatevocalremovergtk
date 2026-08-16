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
| `UVR_CACHE_DIR` | OS cache dir (`~/.cache/uvr` on Linux) | Download size cache, Politrees catalogue JSON, mvsepless `models.json` cache, catalogue YAML stem cache |

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
| `UVR_DISABLE_MVSEPLESS` | `1`, `true`, `yes` | Skip the [mvsepless_resources](https://huggingface.co/noblebarkrr/mvsepless_resources) catalogue supplement |
| `UVR_DISABLE_CATALOGUE_STEMS` | `1`, `true`, `yes` | Skip background fetch of catalogue YAML configs for Download Center stem subtitles (mvsepless stems unchanged; use for offline/CI) |
| `UVR_DISABLE_MODEL_SCORES` | `1`, `true`, `yes` | Skip the benchmarked SDR catalogue (network fetch + seven-day cache); rows fall back to stems and size |
| `UVR_SIZE_HEAD_WORKERS` | positive int (default `8`) | Parallelism for Download Center size/identity HEAD warmup, and the size of each submitted wave. Non-numeric or `0` falls back to the default |
| `UVR_INSECURE_DOWNLOADS` | `1` | Disable TLS certificate verification (**dev only**) |

Download size-cache warmup (`size_cache_warmup start` in logs) is scheduled when the Download Center opens, not at main-window map. HEADs are submitted a wave at a time so quitting mid-warmup only waits on the wave in flight, not the whole backlog. When the warmup's identity pass drops rehosted duplicates, the open Download Center removes those rows in place (`catalogue refresh removed N row(s)` in logs) instead of rebuilding the list. Catalogue YAML stem fetches are rate-limited (≤2 concurrent), notify per completed chunk, and prioritize visible Download Center rows — a row already queued in the bulk backlog is promoted when it becomes visible. Name-mapper refresh merges local-only keys; see [models.md](models.md).

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

## Command-line interface

The installer exposes the source-tree launcher as `uvr` when
`~/.local/bin/uvr` is available. Use `./uvr` directly otherwise. The
launcher always selects this checkout's virtual environment.

This CLI is still pre-release and intentionally does not retain compatibility
shims for its earlier experimental surface:

| Earlier experimental interface | Current interface |
| --- | --- |
| `python -m core` / `python -m core.cli` | Removed; use `uvr` |
| `python -m cli` | Internal/testing only; public scripts use `uvr` |
| `bench-ab` | `uvr bench` |
| `list-models` | `uvr models list` |
| `--json` | `--report json` |
| `--json-out` | `--manifest-out` for job manifests |
| `--print-settings` | `--verbose`, `--dry-run`, or `uvr settings show` |
| `--method` | Removed; the canonical model ID determines the family |
| `--cpu` / `--gpu` | `--device auto|cpu|cuda:N|mps|directml:N` |

The removed Python headless helpers have likewise been replaced by the public
resolved-job and blocking-runner APIs in `core`; no import trampoline remains.

### Commands and model IDs

```bash
uvr models list --family mdx
uvr models show mdx:UVR-MDX-NET-Inst_HQ_4
uvr devices list

uvr separate song.wav -o /tmp/stems \
  --model mdx:UVR-MDX-NET-Inst_HQ_4

uvr ensemble song.wav -o /tmp/stems \
  --model mdx:model-a --model demucs:hdemucs_mmi \
  --main-stem vocals_instrumental
```

Canonical model IDs are `vr:<basename>`, `mdx:<basename>`, and
`demucs:<basename>`. An unqualified display name, basename, or substring is
accepted only when it resolves uniquely across every installed family. Unknown
checkpoints must be registered before use:

```bash
uvr models register model.ckpt --family mdx --config model.json
```

Registration copies the checkpoint into the managed model tree and stores its
validated per-hash configuration. Local metadata overrides catalogue metadata.

### Defaults and profiles

CLI jobs start from typed application defaults and do not read GUI settings
implicitly. Select `--profile gui`, a named sparse profile, or a JSON profile
path explicitly:

```bash
uvr settings profile create fast-gpu \
  --model mdx:UVR-MDX-NET-Inst_HQ_4 \
  --set process.autocast=true --set mdx.segment_size=256

uvr separate song.wav -o /tmp/stems --profile fast-gpu
uvr settings explain mdx.segment_size --profile fast-gpu
```

When a profile supplies the model, ensemble preset, or member list, an
interactive run previews the effective plan and asks `Use these settings?
[y/N]`. Machine and non-TTY runs must pass `--accept-inherited`. CLI and
profile changes never write back to GUI settings.

A portable sparse profile uses schema version 1. Identity is separate from the
flat setting map; use either `model`, `ensemble`, or `members`:

```json
{
  "schema_version": 1,
  "name": "fast-gpu",
  "model": "mdx:UVR-MDX-NET-Inst_HQ_4",
  "ensemble": null,
  "members": [],
  "settings": {
    "process.autocast": true,
    "mdx.segment_size": 256
  }
}
```

Precedence is built-in defaults, model-native automatic values, ensemble
preset, profile, named CLI flags, `--set`, environment, then derived runtime
values. `UVR_AUTOCAST` is the currently supported environment override.

### Inspection and validation

```bash
uvr separate song.wav -o /tmp/stems --model mdx:model --dry-run
uvr validate separate song.wav -o /tmp/stems \
  --model mdx:model --level runtime
uvr models validate mdx:model
```

Dry-run verifies input paths, checkpoint existence/hash, model configuration,
and planned outputs. It does not load weights, import the inference engines,
create output directories, or start a runner.

Validation levels are `config`, `model`, `runtime`, and `load`. The last
level loads the checkpoint through the applicable runtime without inference.

### Audio Tools and administration

The GUI Audio Tools are also available through `uvr audio`: `inspect`,
`ensemble`, `stretch`, `pitch`, `align`, `match`, and Apollo `restore`.
Single-input tools accept files or directories; align and match require
repeatable `--pair A B`. They use the same profiles, reports, validation,
dry-run, staging, collision policies, manifests, and replay checks as
separation jobs. Validate them with `uvr validate audio TOOL ...`.

`uvr models catalog` searches downloadable catalogue entries and `uvr models
download ENTRY...` is the only processing-adjacent command that downloads
models. `uvr models configure` manages validated local hash metadata. Saved
ensembles can be created or deleted with `uvr ensembles create|delete`, and
`uvr update check` performs a read-only source-release check.

### Batch safety and manifests

Directories are accepted as inputs. Use `--recursive` and repeatable
`--include GLOB` filters. Inputs are sorted and deduplicated.

```bash
uvr separate ~/Music -o /tmp/stems --recursive --include '*.flac' \
  --model mdx:model --on-exists rename --continue-on-error

uvr separate song.wav -o /tmp/stems --model mdx:model --manifest
uvr run /tmp/stems/uvr-manifest-JOB_ID.json -o /tmp/replay
```

Outputs are staged per input and promoted only after success.
`--on-exists` accepts `fail` (default), `overwrite`, `rename`, or
`skip`. Batches continue after an input failure by default; `--fail-fast`
reverses this. Manifests record effective settings, provenance, model hashes,
inputs, outputs, backend, and outcomes. Replay rejects changed model hashes
unless `--allow-model-change` is supplied.

### Reports and exit codes

`--report human|json|jsonl` selects output ownership. JSON is exactly one
versioned result document. JSONL emits versioned planning, progress,
per-input, and terminal events. Engine logs never enter machine-readable
stdout. `--quiet` suppresses progress and engine chatter; `--verbose`
prints the effective plan for a real job.

JSON documents have the stable outer shape below. Success results add the
effective `plan`, per-input outcomes, timings, and output paths; failures use
the same envelope with `ok: false` and an `error` object.

```json
{
  "schema_version": 1,
  "job_id": "UUID",
  "ok": true,
  "status": "success",
  "command": "separate",
  "plan": {},
  "inputs": []
}
```

JSONL writes one object per line. Its `event` values are `planned`, `started`,
`progress`, `input_finished`, and `finished`; every event includes the schema
version and job ID. Diagnostics remain on stderr in both machine modes.

Exit codes are: `0` success/skipped, `1` complete runtime failure, `2`
usage/configuration/validation/confirmation failure, `3` partial batch
success, and `130` interruption.

| Manifest `schema_version` | `1` for `separate` / `ensemble`; `2` for `audio` |
| Interrupt document | `ok: false`, `status: "failed"`, `stopped: true`, exit `130` |
| Planning / validate / dry-run | Installed + cached metadata only. Missing MDX-C YAML is an error; use `uvr models download` |

Planning / validate / dry-run use `mdx_c_network(False)` /
`ensure_mdx_c_config(..., allow_network=False)`, not `catalogue_offline()`.

### Benchmarking and completion

```bash
uvr bench song.wav -o /tmp/bench --model mdx:model \
  --a-env UVR_AUTOCAST=0 --b-env UVR_AUTOCAST=1 \
  --a-set mdx.segment_size=256 --b-set mdx.segment_size=512

uvr completion bash
```

Both benchmark legs validate before leg A starts and use a fresh job-ID
directory. Use per-leg model/profile/environment/setting flags for broader
comparisons and `--keep-outputs always|failure|never` for retention.

GPU kernels may not be bitwise deterministic. The CLI intentionally has no
`--seed` option until an engine exposes a real controllable randomness source.

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
| `UVR_DEBUG_OOM` | `1` | Add menu entries to mock the GPU OOM recovery dialog (no inference) |

**Chip debug example** (visual QA for morph icons and labels):

```bash
UVR_DEBUG_QUEUE_CHIP=1 UVR_DEBUG_QUEUE_POPUP=1 UVR_DEV_CSS=1 ./run_uvr.sh
```

Scenarios cycled by `UVR_DEBUG_QUEUE_CHIP=1`: `active`, `success`, `partial`, `failed`, `cancelled`.

**OOM dialog mock** (Export / Stop / Retry chrome without a real CUDA failure):

```bash
UVR_DEBUG_OOM=1 ./run_uvr.sh
# Menu → Mock GPU OOM dialog (all three buttons)
# Menu → Mock OOM (Separation) (Stop + Retry only)
```

---

## Launcher (`run_uvr.sh`)

| Variable | Default | Purpose |
|----------|---------|---------|
| `UVR_AUTO_REBUILD` | `auto` | Venv rebuild when stale: `auto` · `always` · `never` |
| `UVR_SKIP_CHECK` | `0` | Skip the GTK import health check entirely (stamp untouched) |
| `UVR_FORCE_VENV_CHECK` | `0` | Force a full GTK/Adw import probe even when the health stamp is fresh |

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
