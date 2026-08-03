# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

Linux/GTK4 port of Ultimate Vocal Remover (upstream v5.6, Tkinter). The Tkinter app is gone; the GTK4/libadwaita UI (`ui/`) drives a Tk-free backend facade (`core/`). Canonical repo is **GitHub** (`origin` → `minarru/ultimatevocalremovergtk`); the former Codeberg host is archived (see [docs/mirroring.md](docs/mirroring.md)).

## Commands

```bash
./install_packages.sh              # venv on system Python with --system-site-packages (GTK from distro)
./install_packages.sh --cuda       # + requirements-cuda-linux.txt (ONNX GPU / CUDA wheels)
./install_packages.sh --system-deps # install distro packages first
./run_uvr.sh                       # launch (also installs the desktop entry, rebuilds stale venvs)
python -m ui                       # launch with the venv already activated
```

Tests are **stdlib unittest** (no pytest config, despite a stray `.pytest_cache`). CI runs:

```bash
.venv/bin/python -m unittest discover -s tests -v
python -m unittest tests.test_dispatch                                  # one module
python -m unittest tests.test_dispatch.DispatchTests.test_main_thread_wrapper  # one test
```

Type checking is **basedpyright** (a pyright fork — same CLI, same config file), configured in [pyrightconfig.json](pyrightconfig.json): `standard` mode plus a few strict-mode rules, over `ui/ core/ engines/ tests/ bundled/ ml/ scripts/` (plus `__version__.py`). Keep `models/` and `vendor/demucs` excluded — do not chase type errors there. Stubs live in [typings/](typings/). Install the checker with `pip install -r requirements-dev.txt`; CI runs it on every PR.

basedpyright's own extra rules are left **off**: measured against this tree they are almost all false positives (`reportUnreachable` fires on the `sys.platform` branches that `"pythonPlatform": "Linux"` statically prunes; `reportPrivateLocalImportUsage` fires on tests importing `_`-prefixed helpers). Its `recommended` mode reports ~15k diagnostics — don't enable it wholesale. If you want to tighten a rule despite existing violations, use `basedpyright --writebaseline` rather than turning the rule off.

**GTK is really type-checked.** `PyGObject-stubs` supplies Gtk4/Adw types (its default config already covers Gtk4+Gdk4 — no `PYGOBJECT_STUB_CONFIG` needed). The old `typings/gi` `__getattr__ -> Any` shims are gone; do not reintroduce them, and don't "fix" a GTK type error by widening to `Any`. Two consequences worth knowing:

- **Widget state goes through [ui/widget_state.py](ui/widget_state.py)** (`stash`/`fetch`/`has`/`drop`), not `row._uvr_foo = x` — real stubs reject unknown attributes on `Adw.ActionRow`. Keys keep the `_uvr_` prefix.
- **Nullable/interface returns narrow through [ui/gtk_narrow.py](ui/gtk_narrow.py)** (`root_window`, `file_paths`) or a local helper. `get_model()`, `get_root()`, `get_item()` and `get_selected_item()` are all typed against a base class or `| None`; unguarded dereferences of these were real latent `AttributeError`s.

```bash
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m basedpyright
```

Other:

```bash
./resources/compile_resources.sh   # rebuild ui/data/uvr.gresource after touching resources/icons or style.css
python -m core.cli separate song.wav -o /tmp/out --method mdx --stems both   # headless separation
python -m core.cli bench-ab song.wav -o /tmp/ab --env UVR_AUTOCAST=0 --env UVR_AUTOCAST=1
python scripts/generate_models_catalogue.py   # regenerate docs/models-catalogue.md
python scripts/model_sweep.py --list      # local-only: every installed model, one real run each
python scripts/model_sweep.py --method mdx --json /tmp/sweep.json
python scripts/model_probe.py --config <yaml>   # can this build run a model? no weights needed
python scripts/model_probe.py --entry <id> --check-keys   # + range-fetch the checkpoint header
```

There is no linter/formatter config in the repo.

## Architecture

Layers, strictly one-directional (`ui` → `core` → `engines` → `ml`; `bundled` is read by all):

- **`bundled/`** — read-only shipped data: `constants/` (stems, process methods, help strings, and a frozen legacy settings-key table for pickle migration), `error_handling.py` (traceback-substring → user message matching), changelog, download metadata. Imported as `from bundled.constants import *` in engine/model code to mirror upstream's flat namespace.
- **`core/`** — Tk-free backend facade. Public surface is re-exported in [core/__init__.py](core/__init__.py): `Settings`, `ModelConfig`/`ModelRepository`/`assemble_model`, `ProcessData`, `JobRunner`/`JobCallbacks`, `AudioToolRunner`.
- **`engines/`** — separation orchestration. `SeperateAttributes` ([engines/base.py](engines/base.py)) is the shared engine base; `SeperateVR` / `SeperateMDX` / `SeperateMDXC` / `SeperateDemucs` are selected in [engines/orchestration.py](engines/orchestration.py). [engines/separate.py](engines/separate.py) is a re-export shim for upstream import paths.
- **`ml/`** — networks and DSP (VR network, MDX/MDX-C, BS/Mel-Band Roformer, SCNet, Bandit, Apollo, `spec_utils`). Ported upstream code; type-checked at the same `standard` level as the app (same `reportMissingParameterType` floor).
- **`vendor/demucs/`** — vendored Demucs fork.

### Invariants worth preserving

**No tkinter, anywhere.** `core` exists specifically to be framework-agnostic; importing tkinter from it breaks the whole design.

**Settings are typed and nested.** `Settings` owns the defaults and persists nested JSON to `settings.json`; a legacy `data.pkl` is imported once and renamed to `data.pkl.bak`. Existing widgets may use the flat `get`/`set` bridge defined by `core/settings/flat_map.py`, but new fields belong in the typed dataclasses and typed defaults first.

**Enum settings are `str, Enum` — but don't stringify them.** `process.method` and `process.save_format` are enums ([core/types/enums.py](core/types/enums.py)), as are the schema-v3 closed vocabularies in [core/types/settings_enums.py](core/types/settings_enums.py) (wav type, bitrate, denoise/phase options, audio tool, manual-ensemble algorithm, colour scheme) and `ensemble.main_stem` ([core/stems.py](core/stems.py)). `==` against a bundled constant, dict lookup, `.lower()` and `json.dumps` all behave as the value string, so most code Just Works. `str(v)` and `f"{v}"` do **not** — they yield `"SaveFormat.WAV"`, not `"WAV"`. Route filenames, paths and log lines through `enum_value` ([core/settings/coerce.py](core/settings/coerce.py)), re-exported for the UI from [ui/settings_bind.py](ui/settings_bind.py); it unwraps enums and passes everything else through.

**Shared settings have per-page widgets.** Separation, Ensemble and Audio Tools each hold their own copies of the global keys (format/quality, GPU, autocast, sample mode, vocal splitter). Bind a widget to one and you must re-apply it in that page's `_sync_shared_from_settings` — which runs on *every* tab activation — not only in the one-time `load()`. Miss it and the stale widget writes all its keys back over whatever another page just edited.

**Threading: worker → main loop.** `JobRunner` runs separation on a `KThread` worker and calls plain callbacks from that thread. GTK may only be touched on the main loop, so every callback crosses via `GLib.idle_add` in [ui/dispatch.py](ui/dispatch.py) (`gtk_job_callbacks`, `main_thread`, `idle_on_main`). Never call a widget straight from engine/runner code.

**Heavy imports are lazy.** `torch`, `onnxruntime`, and `engines` must not be imported at `core` import time — that's what keeps startup fast. [core/separate_import.py](core/separate_import.py) warms them on a background thread (`UVR_SKIP_SEPARATE_WARMUP=1` disables it).

**Bundled vs. runtime paths.** [core/paths.py](core/paths.py) splits read-only install data (`bundled/`, seed model metadata) from writable runtime data under `DATA_DIR` — `$UVR_DATA_DIR`, else the repo root when writable (portable dev layout: `./models`, `./settings.json`), else the OS user-data dir. Ephemeral download/catalogue caches go under `CACHE_DIR`. Never write into the install tree directly; resolve through `paths`.

**Model identity is MD5-based.** `ModelRepository` resolves checkpoints by hash against the JSON hash maps in `models/*/model_data/`; `assemble_model` builds the per-run `ModelConfig` objects the engines consume. Weights are gitignored — only metadata and the small `UVR-DeNoise-Lite.pth` are committed.

### Separation run pipeline

`JobRunner.start` (single) and `JobRunner.start_ensemble` (ensemble) both begin with `assemble_model(settings, repo, arch_type=...)`, which returns the list of `ModelConfig` objects for the run. Long inputs are sliced/rejoined by [core/audio_chunking.py](core/audio_chunking.py) (`slice_mix` → per-chunk inference → `concat_stems`).

**One `ModelConfig` can mean several inference passes.** Beyond the primary model, `ModelConfig.secondary_model_data` may attach a secondary model, a Demucs pre-process model, a vocal-splitter chain, and per-stem 4-stem secondaries. Engines invoke these through `process_secondary_model` / `process_chain_model` in [engines/orchestration.py](engines/orchestration.py). The progress denominator comes from `count_inference_passes_from_models` ([core/run_estimate.py](core/run_estimate.py)) via `true_model_count` — **if you add a pass, count it there or the progress bar silently lies.**

**Ensemble runs write then combine.** Each member runs with `is_ensemble_master` so engines emit per-member stems into `ENSEMBLE_TEMP_PATH` (or the export folder when `is_save_all_outputs_ensemble`), then `Ensembler.ensemble_outputs` combines them per stem through `spec_utils.ensemble_inputs`. The algorithm comes from the `ensemble_type` setting as a `Primary/Secondary` pair (e.g. `Max Spec/Min Spec`); 4-stem and multi-stem ensembles use only the single leading token. Members are deleted after combining unless `is_save_all_outputs_ensemble`.

Note the coupling: `Ensembler.get_files_to_ensemble` collects members by **filename prefix/suffix** (`{base} {model} ({stem}).wav`), so [core/export_naming.py](core/export_naming.py) and ensemble collection must change together — a naming tweak that looks cosmetic will make ensembles silently produce single-member output.

**Run payloads are typed.** `ProcessData` carries callbacks, routing flags, and source-cache state into engines. Engines reuse already-computed stems within one input file via its `cached_source_callback` / `cached_model_source_holder` fields; the runner clears the cache per input file (`_cached_sources_clear`). `_build_all_models` supplies `list_all_models`, which engines use to decide whether a referenced primary/secondary model actually participates in this run.

### UI structure

`UVRApplication` ([ui/application.py](ui/application.py)) → `MainWindow` ([ui/window.py](ui/window.py)), with one `AppContext` ([ui/context.py](ui/context.py)) holding the shared `Settings` and lazily-built repository/runner. Per-method option panels are `MethodView` subclasses in [ui/views/](ui/views/) registered in `METHOD_VIEWS` — add a method there rather than editing the window assembly. Options shared across Separation/Ensemble/Audio Tools live in [ui/shared_settings.py](ui/shared_settings.py).

## Repository workflow

Push to `origin` (**GitHub**: `minarru/ultimatevocalremovergtk`) only. Prefer `gh pr create` / `gh pr merge` for review. The former Codeberg remote may exist locally as `codeberg` until you remove it after archive.

CI is **GitHub Actions** in [`.github/workflows/`](.github/workflows/). `test.yml` runs unittest + basedpyright on push/PR to `main`. `release.yml` fires on `v*` tags and **asserts the tag equals all three version strings**: `VERSION` in [__version__.py](__version__.py), and `latest_version` in both [packaging/release.json](packaging/release.json) and [bundled/release.json](bundled/release.json). Bump all four together or the release check fails.

```bash
gh run list
gh pr checks
```

Known bugs and roadmap gaps are tracked in [docs/tracked-issues.md](docs/tracked-issues.md); check it before filing or "fixing" something.

## Conventions

- Search with `rg` (ripgrep), not `grep` or `git grep` — see [.cursor/rules/use-rg.mdc](.cursor/rules/use-rg.mdc).
- GTK-dependent tests guard with `@unittest.skipUnless(...)` plus `gi.require_version("Gtk", "4.0")` / `("Adw", "1")` inside `setUpClass`, so the suite still runs where GTK is unavailable. Non-UI logic is tested by mocking `GLib.idle_add` rather than starting a main loop.
- Debug logging goes through [core/debug_log.py](core/debug_log.py) components (`ui`, `dispatch`, `trace`, `worker`, `separate`, `cleanup`, `model`, `audio`, `download`, `error`, `settings`), surfaced as GLib domains: `G_MESSAGES_DEBUG=uvr-ui,uvr-worker python -m ui`, `UVR_LOG_FILE=/tmp/uvr.log`, `UVR_VERBOSE=1`. Full list of switches in [docs/environment.md](docs/environment.md).
- Upstream's `Seperate*` misspelling is the real class-name prefix across the engine layer — keep it. Likewise, the error strings in `bundled/error_handling.py` are matched against upstream tracebacks verbatim; don't "fix" them.
- Tests that build a real `MainWindow` read on-disk `settings.json` via `AppContext()` — set every setting an assertion depends on. Verify isolation with `UVR_DATA_DIR=<scratch>` (symlink `models/` into it, or model resolution comes back empty).
- `core.model_display.format_tag_title` resolves through `load_politrees_links()`, which fetches over the network (30s timeout) unless `UVR_DISABLE_POLITREES=1`. Tests patch `core.politrees_catalog.load_politrees_links` — see [tests/test_mdx_c_registry.py](tests/test_mdx_c_registry.py).
- `get_flat`/`set_flat` ([ui/settings_bind.py](ui/settings_bind.py)) **no-op silently** on a key missing from `FLAT_TO_PATH`: reads return the default, writes vanish. Nearly every UI call site builds its key at runtime, so a typo or a new field is invisible until the setting quietly stops persisting — add the mapping in `core/settings/flat_map.py` first.
- `set_combo_tag_values` takes `(stored_id, display_label)` pairs; pass `format_tag_title(tag, repo)` as the label or the list shows raw architecture-prefixed tags.
- A model combo seeded before its real list loads must not persist its value: if the stored tag is absent from the fresh list the combo falls to index 0 and writes `NO_MODEL` over the user's choice. See the `ready` flag in `_ensure_model_combos_populated`.
- Never call `widget.destroy()` in a test or smoke script — with no running main loop it segfaults.
- GTK widget behaviour and layout-diagnosis notes live in [ui/CLAUDE.md](ui/CLAUDE.md), loaded when working under `ui/`.
- This working tree often carries long-lived uncommitted edits (model metadata under `models/*/model_data/`). Never run unscoped `git checkout -- .`, `git restore .`, `git reset --hard`, `git stash` or `git clean`; restore only exact paths, and stage explicitly rather than `git add -A`.
