# Environment and developer configuration

This is the reference for optional environment variables read by the GTK app,
the `uvr` launcher, and the installer. Set a variable before starting the app,
either for one command or in your shell configuration.

```bash
# bash
UVR_LOG_LEVEL=debug ./run_uvr.sh

# fish
env UVR_LOG_LEVEL=debug ./run_uvr.sh
```

Runtime configuration comes first. Developer-only controls, including GTK
display-backend testing and UI visual-QA variables, are collected under
[Development configuration](#development-configuration).

For the structured diagnostic implementation and GLib compatibility domains,
see also `core/debug_log.py`.

---

## Runtime data and cache paths

| Variable | Default | Purpose |
|----------|---------|---------|
| `UVR_DATA_DIR` | Writable checkout root, else OS user data dir | Models, settings (`settings.json`), profiles, ensembles, sample/ensemble temps, and—when explicitly set—the model registry |
| `UVR_CACHE_DIR` | OS cache dir (`~/.cache/uvr` on Linux) | Download size cache, Politrees catalogue JSON, mvsepless `models.json` cache, catalogue YAML stem cache |

On first use, legacy copies of `download_size_cache.json` /
`politrees_model_links.json` in the checkout root or `UVR_DATA_DIR` are moved
into `UVR_CACHE_DIR`.

The model registry contains machine-specific checkpoint hashes, catalogue-label
evidence, and trusted local display overrides. It is never seeded from or
tracked by the repository. In a writable portable checkout it lives at
`.uvr-runtime/registered_models.json`; an explicit `UVR_DATA_DIR` places it at
`$UVR_DATA_DIR/registered_models.json`; a read-only installation uses the
platform user-data directory. A fresh installation therefore starts with an
empty in-memory schema-2 registry and creates the file only on mutation.

For compatibility, reads merge a legacy checkout-root
`registered_models.json` with the runtime file without modifying either one.
Runtime hash mappings and per-model presentation fields win conflicts. The next
registry mutation writes the merged schema-2 state atomically, then moves the
legacy file beside it as `registered_models.legacy.json` (or the next numbered
name when an archive already exists). A corrupt legacy file is left untouched
and blocks mutation until repaired; an archive failure leaves the published
runtime registry usable and emits a warning.

Standard XDG / platform paths (`XDG_DATA_HOME`, `XDG_CACHE_HOME`,
`LOCALAPPDATA`) apply when UVR-specific variables are unset. See
`core/paths.py` and `core/platform.py`.

---

## Logging and diagnostics

The GUI and CLI share one structured diagnostic pipeline. It defaults to
**Errors**, writing a rotating log at `UVR_CACHE_DIR/logs/uvr.log` (five files,
2 MiB each). In the GUI, change the live and persisted level under
**Preferences → General → Diagnostics**. The levels are:

- **Errors:** unrecovered failures, corrupt settings, uncaught exceptions, and
  export paths that produced no writes.
- **Debug:** lifecycle boundaries and compact decisions for startup, settings,
  planning, model inventory, execution, exports, catalogue refresh (including
  recoverable source warnings), and model downloads.
- **Trace:** Debug plus sampled progress, console-chunk, GTK-dispatch, and
  polling events. Progress traces retain semantic transitions, completion, 5%
  boundaries, and a five-second heartbeat; UI and CLI progress callbacks remain
  full fidelity.

Each line carries a UTC timestamp, level, component, process-session ID, event
name, and—where applicable—an operation ID shared by CLI commands, UI runs,
workers, exports, and downloads. Python warnings are captured at Debug/Trace;
uncaught main-thread and worker-thread exceptions are always captured.

Local paths and URL paths are redacted by default. **Include sensitive details**
reveals those paths for troubleshooting. Credentials, authorization values,
cookies, URL user-info/query strings, raw audio/sample arrays, tensors, and
model weights are never written. Structured values are escaped to one physical
line, and log files are forced to owner-only permissions. CLI JSON/JSONL stdout
remains reserved for the report document/events; diagnostics go to the log and
GLib/stderr.

The CLI accepts `--debug` or `--trace`, plus `--debug-sensitive` and
`--log-file PATH`. Put these before the command to apply them globally, or on a
processing/reporting command that exposes the same flags. `--verbose` remains
independent: it prints the effective plan and does not enable diagnostic logs.
Without a flag or environment override, the CLI uses the persisted diagnostic
policy from Preferences; functional job settings still follow the CLI profile
rules in [cli.md](cli.md).

| Variable | Values / example | Purpose |
|----------|------------------|---------|
| `UVR_LOG_LEVEL` | `errors`, `debug`, `trace` | Override the persisted diagnostic level |
| `UVR_LOG_FILE` | `/tmp/uvr.log` | Override the rotating cache-log destination |
| `UVR_DEBUG_SENSITIVE` | `1`, `true`, `yes` | Include local and URL paths (never secrets or URL queries) |
| `UVR_VERBOSE` | `1` | Legacy alias for Trace |
| `G_MESSAGES_DEBUG` | `uvr` · `uvr-ui,uvr-download` · `all` | Legacy GLib debug-domain filter (`uvr-*` shorthands expanded at launch) |

**Components:** `ui`, `cli`, `dispatch`, `trace`, `worker`, `separate`,
`cleanup`, `model`, `audio`, `download`, `ensemble`, `cache`, `error`, and
`settings`.

Environment-specific CLI diagnostic examples:

```bash
# Persistent structured debug log at the normal cache location
uvr --debug gui

# Trace one CLI job into an explicit file
uvr separate song.wav -o /tmp/stems --model mdx:MODEL_BASENAME \
  --trace --log-file /tmp/uvr-trace.log

# Legacy component-focused GLib output
G_MESSAGES_DEBUG=uvr-ui,uvr-settings,uvr-error python -m ui
```

`run_uvr.sh` normalizes `G_MESSAGES_DEBUG` and prints a hint when debug
variables are set.

`mdx:MODEL_BASENAME` above is a placeholder. Obtain an installed canonical ID
from `uvr models list` before running the example.

---

## Troubleshooting

- **The GUI appears not to open:** only one GUI instance may run. A second
  instance exits immediately; inspect the rotating cache log above or use
  `journalctl --user -f` for the active process.
- **A diagnostic log lacks the needed paths:** enable **Include sensitive
  details** temporarily, or use `--debug-sensitive`; credentials, tokens, URL
  queries, audio data, tensors, and weights remain excluded.
- **Runtime files or caches are in an unexpected location:** check
  `UVR_DATA_DIR` and `UVR_CACHE_DIR`, then the applicable XDG/platform path.
  Do not place the model registry in version control.
- **A CLI catalogue command must avoid network access:** add `--offline` as
  documented in [cli.md](cli.md). The variables below selectively disable
  sources or background features; they do not make a Download Center refresh
  fully offline.

---

## Catalogue and download configuration

| Variable | Values | Purpose |
|----------|--------|---------|
| `UVR_DISABLE_POLITREES` | `1`, `true`, `yes` | Skip the remote Politrees community supplement; bundled extras and mvsepless membership remain enabled unless separately disabled |
| `UVR_DISABLE_EXTRA_MODELS` | `1`, `true`, `yes` | Skip bundled fork-extra catalogue membership (a local source) |
| `UVR_DISABLE_MVSEPLESS` | `1`, `true`, `yes` | Skip the [mvsepless_resources](https://huggingface.co/noblebarkrr/mvsepless_resources) catalogue supplement |
| `UVR_DISABLE_CATALOGUE_STEMS` | `1`, `true`, `yes` | Skip background fetch of catalogue YAML configs for Download Center stem subtitles (mvsepless stems unchanged; use for offline/CI) |
| `UVR_DISABLE_MODEL_SCORES` | `1`, `true`, `yes` | Skip the benchmarked SDR catalogue (network fetch + seven-day cache); rows fall back to stems and size |
| `UVR_SIZE_HEAD_WORKERS` | positive int (default `8`) | Parallelism for Download Center size/identity HEAD warmup, and the size of each submitted wave. Non-numeric or `0` falls back to the default |
| `UVR_INSECURE_DOWNLOADS` | `1` | Disable TLS certificate verification (**dev only**) |

The three disable switches are independent. For a TRvlvr-only membership view,
disable all three supplements
(`UVR_DISABLE_POLITREES=1`, `UVR_DISABLE_EXTRA_MODELS=1`, and
`UVR_DISABLE_MVSEPLESS=1`).

See [Models and stems](models.md#advanced-catalogue-mechanics) for source order,
merging, refresh, caching, and deduplication behavior.

---

## External tools

| Variable | Purpose |
|----------|---------|
| `UVR_FFMPEG` | Path to `ffmpeg` when not on `PATH` |
| `UVR_RUBBERBAND` | Path to `rubberband` when not on `PATH` |

---

## Startup and performance

| Variable | Values | Purpose |
|----------|--------|---------|
| `UVR_SKIP_SEPARATE_WARMUP` | `1` | Skip background import of separation engines at startup (loads on first run instead) |
| `UVR_AUTOCAST` | `0`/`1` | **Override** for CUDA `torch.autocast` (fp16) around model forwards only; OLA stays float32. When unset, the GUI/settings key `is_autocast` applies. Applies to VR / MDX / Roformer; Demucs stays FP32 (fp16 produces NaN stems) |
| `UVR_MODEL_SWEEP` | `1` | Enables the local-only full model sweep in `tests/test_model_sweep.py`; the sweep itself is `scripts/model_sweep.py` and never runs in CI |

---

## Command-line interface

The full command-line reference is [cli.md](cli.md). Run `uvr --help` or a
subcommand's `--help` for the current command syntax.

---

## Launcher (`run_uvr.sh`)

| Variable | Default | Purpose |
|----------|---------|---------|
| `UVR_AUTO_REBUILD` | `auto` | Venv rebuild when stale: `auto` · `always` · `never` |
| `UVR_SKIP_CHECK` | `0` | Skip the GTK import health check entirely (stamp untouched) |
| `UVR_FORCE_VENV_CHECK` | `0` | Force a full GTK/Adw import probe even when the health stamp is fresh |

The installer exposes the source-tree launcher as `uvr` when
`~/.local/bin/uvr` is available. Use `./uvr` directly otherwise. The launcher
always selects this checkout's virtual environment.

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

Repository mirroring (GitHub backup, deploy keys) is documented in
[mirroring.md](mirroring.md) — not part of app runtime.

---

## Development configuration

The variables and procedures below are for UI development and automated GTK
validation. They are not required to run UVR normally.

### GTK display-backend testing

Choose one display flow for a run; they are deliberately non-overlapping.

1. **Codex sandbox-native GTK tests:** use the existing
   `testing-gtk-headless` private-Mutter runner
   (`scripts/run-private-wayland.sh` in that skill). It creates a private
   `WAYLAND_DISPLAY` and runs GTK with `GDK_BACKEND=wayland`; do not add
   `xvfb-run` inside that Wayland session.
2. **Outside-sandbox headless local tests and CI:** pin GTK to X11 and strip
   inherited host display/session endpoints before starting Xvfb:

   ```bash
   env -u DISPLAY -u WAYLAND_DISPLAY -u DBUS_SESSION_BUS_ADDRESS \
     -u DBUS_SYSTEM_BUS_ADDRESS -u XDG_RUNTIME_DIR -u XAUTHORITY \
     -u SESSION_MANAGER GDK_BACKEND=x11 GSK_RENDERER=cairo \
     xvfb-run -a .venv/bin/python -m unittest discover -s tests -t . -v
   ```

   Xvfb is an X11 virtual display, not a Wayland dependency.
3. **Host-realistic manual UI testing:** use the active host Wayland session
   with the repository venv or `./uvr`. Do not inject private-display
   variables or Xvfb into that session.

Every automated private-display flow must strip host `DISPLAY`,
`WAYLAND_DISPLAY`, D-Bus/session, and XDG runtime endpoints before creating
its own display. The private-Mutter runner is the current command source for
that isolation; use it rather than rebuilding those environment settings by
hand.

### UI development

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

Scenarios cycled by `UVR_DEBUG_QUEUE_CHIP=1`: `active`, `success`, `partial`,
`failed`, `cancelled`.

**OOM dialog mock** (Export / Stop / Retry chrome without a real CUDA failure):

```bash
UVR_DEBUG_OOM=1 ./run_uvr.sh
# Menu → Mock GPU OOM dialog (all three buttons)
# Menu → Mock OOM (Separation) (Stop + Retry only)
```
