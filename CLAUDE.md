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

Tests are **stdlib unittest** (no pytest config, despite a stray `.pytest_cache`). Run locally:

```bash
.venv/bin/python -m unittest discover -s tests -t . -v
.venv/bin/python -m unittest tests.test_dispatch                                  # one module
.venv/bin/python -m unittest tests.test_dispatch.DispatchTests.test_main_thread_wrapper  # one test
```

CI runs full discovery with the isolated Xvfb flow in
[docs/environment.md](docs/environment.md#gtk-display-backend-testing).

Type checking is **basedpyright** (a pyright fork — same CLI, same config file), configured in [pyrightconfig.json](pyrightconfig.json): `standard` mode plus a few strict-mode rules, over `ui/ cli/ core/ engines/ tests/ bundled/ ml/ scripts/` (plus `__version__.py`). Keep `models/` and `vendor/demucs` excluded — do not chase type errors there. Stubs live in [typings/](typings/). Install the checker with `pip install -r requirements-dev.txt`; CI runs it on every PR.

basedpyright's own extra rules are left **off**: measured against this tree they are almost all false positives (`reportUnreachable` fires on the `sys.platform` branches that `"pythonPlatform": "Linux"` statically prunes; `reportPrivateLocalImportUsage` fires on tests importing `_`-prefixed helpers). Its `recommended` mode reports ~15k diagnostics — don't enable it wholesale. If you want to tighten a rule despite existing violations, use `basedpyright --writebaseline` rather than turning the rule off.

**GTK is really type-checked.** `PyGObject-stubs` supplies Gtk4/Adw types (its default config already covers Gtk4+Gdk4 — no `PYGOBJECT_STUB_CONFIG` needed). The old `typings/gi` `__getattr__ -> Any` shims are gone; do not reintroduce them, and don't "fix" a GTK type error by widening to `Any`. Two consequences worth knowing:

- **Widget state goes through [ui/widget_state.py](ui/widget_state.py)** (`stash`/`fetch`/`has`/`drop`), not `row._uvr_foo = x` — real stubs reject unknown attributes on `Adw.ActionRow`. Keys keep the `_uvr_` prefix.
- **Nullable/interface returns narrow through [ui/gtk_narrow.py](ui/gtk_narrow.py)** (`root_window`, `file_paths`) or a local helper. `get_model()`, `get_root()`, `get_item()` and `get_selected_item()` are all typed against a base class or `| None`; unguarded dereferences of these were real latent `AttributeError`s.

```bash
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/pip install --no-deps -r requirements-stubs.txt   # --no-deps is required
.venv/bin/python -m basedpyright
```

The stubs are a **separate `--no-deps` install on purpose**: `PyGObject-stubs` declares a runtime dependency on `PyGObject`, and resolving it builds PyGObject from PyPI source (meson + pycairo, cairo dev headers) — which fails on a bare runner and contradicts the `--system-site-packages` design, where GTK comes from the distro. Don't fold that line back into [requirements-dev.txt](requirements-dev.txt).

Ruff is pinned in `requirements-dev.txt` and configured by [ruff.toml](ruff.toml)
for deterministic local linting and formatting. The configured Python target is
3.12, the documented fallback floor; running Ruff from a newer system or venv
Python does not change that compatibility target. Prefer checking or formatting
only the Python files touched by a change:

```bash
.venv/bin/ruff check path/to/file.py
.venv/bin/ruff format --check path/to/file.py
.venv/bin/ruff format path/to/file.py
```

The full-tree commands are useful for auditing, but currently report accepted
backlog and are **not CI gates**:

```bash
.venv/bin/ruff check .
.venv/bin/ruff format --check .
```

Do not apply unrestricted `ruff check --fix` or bulk-format the repository as
part of unrelated work. Existing intentional wildcard and lazy-import patterns
use scoped configuration or inline `noqa` comments; preserve their rationale.

Other:

```bash
./resources/compile_resources.sh   # rebuild ui/data/uvr.gresource after touching resources/icons or style.css
./uvr separate song.wav -o /tmp/out --model mdx:Model --stems both
./uvr separate song.wav -o /tmp/out --profile gui --accept-inherited
./uvr ensemble song.wav -o /tmp/out --ensemble "Curated: Vocal Clean"
./uvr models list --family mdx
./uvr models list --all-known
./uvr bench song.wav -o /tmp/ab --model mdx:Model --a-env UVR_AUTOCAST=0 --b-env UVR_AUTOCAST=1
python scripts/generate_models_catalogue.py   # regenerate unified manifest + catalogue Markdown/TSVs
python scripts/generate_models_catalogue.py --refresh   # refresh one live snapshot, then publish the whole bundle
python scripts/generate_models_catalogue.py --check --offline  # read-only warm-cache consistency check
python scripts/generate_models_catalogue.py --summary   # counts + mismatches to stdout
python scripts/model_sweep.py --list      # local-only: every installed model, one real run each
python scripts/model_sweep.py --method mdx --json /tmp/sweep.json
python scripts/model_sweep.py --list --manifest /tmp/jobs.json   # resolved job list as JSON
python scripts/model_probe.py --config <yaml>   # can this build run a model? no weights needed
python scripts/model_probe.py --entry <id> --check-keys   # + range-fetch the checkpoint header
python scripts/generate_models_catalogue.py --audit-stem-confidence --guessed-only
```

## Architecture

Layers, strictly one-directional (`ui` → `core` → `engines` → `ml`, and `cli` → `core`; `bundled` is read by all):

- **`bundled/`** — read-only shipped data: [model_manifest.json](bundled/model_manifest.json) (the one atomic presentation, reviewed-stem, MDX-runtime-contract, lifecycle, and exact catalogue/config-evidence authority), `constants/` (stems, process methods, help strings, and a frozen legacy settings-key table for pickle migration), `error_handling.py` (traceback-substring → user message matching), changelog, and download metadata. Imported as `from bundled.constants import *` in engine/model code to mirror upstream's flat namespace.
- **`core/`** — Tk-free backend facade. Public surface is re-exported in [core/__init__.py](core/__init__.py): `Settings`, `ModelConfig`/`ModelRepository`/`assemble_model` (`ModelRepository` lives in [core/model_repository.py](core/model_repository.py); MDX-C yaml and hash-JSON helpers remain in [core/model_data.py](core/model_data.py)), `ProcessData`, `JobRunner`/`JobCallbacks` (callbacks live in [core/job_callbacks.py](core/job_callbacks.py); single/ensemble file-pass hooks live in [core/run_hooks.py](core/run_hooks.py)), `AudioToolRunner`.
- **`cli/`** — command-line front end exposed through `uvr` (with `python -m cli` as an internal entry point), a presentation layer peer of `ui/`. Core has no CLI trampoline.
- **`engines/`** — separation orchestration. `SeperateAttributes` ([engines/base.py](engines/base.py)) is the shared engine base; `SeperateVR` / `SeperateMDX` / `SeperateMDXC` / `SeperateDemucs` are constructed by [engines/separator_factory.py](engines/separator_factory.py). GUI startup preloads those modules through [core/separate_import.py](core/separate_import.py) so the first run does not stall on torch.
- **`ml/`** — networks and DSP (VR network, MDX/MDX-C, BS/Mel-Band Roformer, SCNet, Bandit, Apollo, `spec_utils`). Ported upstream code; type-checked at the same `standard` level as the app (same `reportMissingParameterType` floor).
- **`vendor/demucs/`** — vendored Demucs fork.

### Invariants worth preserving

**No tkinter, anywhere.** `core` exists specifically to be framework-agnostic; importing tkinter from it breaks the whole design.

**Settings are typed and nested.** `Settings` owns the defaults and persists nested JSON to `settings.json`; a legacy `data.pkl` is imported once and renamed to `data.pkl.bak`. Existing widgets may use the flat `get`/`set` bridge defined by `core/settings/flat_map.py`, but new fields belong in the typed dataclasses and typed defaults first.

**`--set` and named CLI flags share one validated path.** `set_path` cannot reject an unknown field on its own — the settings sections are plain dataclasses without `slots`, so `setattr` invents the attribute instead of raising. Anything that accepts a user-supplied settings path must flow through `SettingsResolver` and the validation helpers in [core/settings/access.py](core/settings/access.py). Named `cli` flags compile to `(path, value)` pairs in `cli/process_flags.py`; `--set` is the final CLI layer.

**Enum settings are `str, Enum` — but don't stringify them.** `process.method` and `process.save_format` are enums ([core/types/enums.py](core/types/enums.py)), as are the closed vocabularies in [core/types/settings_enums.py](core/types/settings_enums.py) (wav type, bitrate, denoise/phase options, audio tool, manual-ensemble algorithm, colour scheme). `ensemble.main_stem` is instead a plain `str` in [core/settings/model.py](core/settings/model.py), normalized against the unified manifest's `pair.*` definitions and reserved `mode.*` IDs by [core/stem_pairs.py](core/stem_pairs.py). `==` against a bundled constant, dict lookup, `.lower()` and `json.dumps` all behave as the value string, so most code Just Works. `str(v)` and `f"{v}"` do **not** — they yield `"SaveFormat.WAV"`, not `"WAV"`. Route filenames, paths and log lines through `enum_value` ([core/settings/coerce.py](core/settings/coerce.py)), re-exported for the UI from [ui/settings_bind.py](ui/settings_bind.py); it unwraps enums and passes everything else through.

**Shared settings have per-page widgets.** Separation, Ensemble and Audio Tools each hold their own copies of the global keys (format/quality, GPU, autocast, sample mode, vocal splitter). Bind a widget to one and you must re-apply it in that page's `_sync_shared_from_settings` — which runs on *every* tab activation — not only in the one-time `load()`. Miss it and the stale widget writes all its keys back over whatever another page just edited.

**Threading: worker → main loop.** `JobRunner` runs separation on a `KThread` worker and calls plain callbacks from that thread. GTK may only be touched on the main loop, so every callback crosses via `GLib.idle_add` in [ui/dispatch.py](ui/dispatch.py) (`gtk_job_callbacks`, `main_thread`, `idle_on_main`). Never call a widget straight from engine/runner code.

**Heavy imports are lazy.** `torch`, `onnxruntime`, and `engines` must not be imported at `core` import time — that's what keeps startup fast. [core/separate_import.py](core/separate_import.py) warms them on a background thread (`UVR_SKIP_SEPARATE_WARMUP=1` disables it).

**Bundled vs. runtime paths.** [core/paths.py](core/paths.py) splits read-only install data (`bundled/`, seed model metadata) from writable runtime data under `DATA_DIR` — `$UVR_DATA_DIR`, else the repo root when writable (portable dev layout: `./models`, `./settings.json`), else the OS user-data dir. The mutable model registry is a special case: portable mode stores it under ignored `./.uvr-runtime/`, an explicit `$UVR_DATA_DIR` stores it directly there, and a read-only install uses the OS user-data dir. Ephemeral download/catalogue caches go under `CACHE_DIR`. Never write into the install tree directly; resolve through `paths`.

**Model identity is MD5-based.** `ModelRepository` resolves checkpoints by hash against the JSON hash maps in `models/*/model_data/`; `assemble_model` builds the per-run `ModelConfig` objects the engines consume. Weights are gitignored — only metadata and the small `UVR-DeNoise-Lite.pth` are committed.

**Canonical model identity is `family:basename`, resolved exactly.** [core/model_identity.py](core/model_identity.py) defines `ModelId`/`ModelRecord` over the four families `vr`, `mdx`, `demucs`, `apollo`; [core/model_inventory.py](core/model_inventory.py) builds one `IdentityIndex` per `(inventory_generation, catalogue_revision, naming_revision)` from family adapters, offline (no network, no hashing). Installed-file or execution-metadata changes publish through `ModelRepository.invalidate_models()`. Catalogue association and label refinements use `invalidate_model_presentation()` and its separate subscriber; they must not bump `inventory_generation` or invalidate resolved plans. GUI method/ensemble/karaoke pickers list installed `ModelRecord`s only; catalogue-only entries surface solely via `models list --all-known`. Runtime code must never import a display-to-basename resolver (`resolve_mdx_model_basename` and siblings) — `core/model_display.py` is the sole allowed importer, enforced by [tests/test_no_runtime_display_inversion.py](tests/test_no_runtime_display_inversion.py).

**Bundled model metadata loads atomically.** [core/model_manifest/](core/model_manifest/) validates [bundled/model_manifest.json](bundled/model_manifest.json) once and projects immutable presentation, stem-semantics, and MDX runtime-contract views through the existing compatibility facades. A failure in any domain publishes none of them; application boundaries log once and retain raw/isolated runtime behavior. Do not add a second bundled parser, authority, or fallback file.

**Model display is a one-way projection.** [core/model_naming.py](core/model_naming.py) applies trusted override → exact unified-manifest alias → conservatively formatted source label → raw basename. [core/model_registry.py](core/model_registry.py) atomically persists schema-2 presentation evidence at `paths.REGISTERED_MODEL_INDEX`; there is no checked-in registry seed. Reads merge a legacy root `registered_models.json` without rewriting it, and the next registry mutation migrates and archives that file under runtime state. Display text must never be used to recover canonical identity.

### Separation run pipeline

`JobRunner.start` begins with `assemble_model(settings, repo, arch_type=...)` (ensemble when `process.method` is Ensemble Mode), which returns the list of `ModelConfig` objects for the run. Long inputs are sliced/rejoined by [core/audio_chunking.py](core/audio_chunking.py) (`slice_mix` → per-chunk inference → `concat_stems`).

**One `ModelConfig` can mean several inference passes.** Beyond the primary model, `ModelConfig.secondary_model_data` may attach a secondary model, a Demucs pre-process model, a vocal-splitter chain, and per-stem 4-stem secondaries. Engines invoke these through `process_secondary_model` / `process_chain_model` in [engines/orchestration.py](engines/orchestration.py). The progress denominator comes from `count_inference_passes_from_models` ([core/run_estimate.py](core/run_estimate.py)) via `true_model_count` — **if you add a pass, count it there or the progress bar silently lies.**

**Ensemble runs write then combine.** Each member runs with `is_ensemble_master` so engines emit per-member stems into `ENSEMBLE_TEMP_PATH` (or the export folder when `is_save_all_outputs_ensemble`), then `Ensembler.ensemble_outputs` combines them per stem through `spec_utils.ensemble_inputs`. The algorithm comes from the `ensemble_type` setting as a `Primary/Secondary` pair (e.g. `Max Spec/Min Spec`); 4-stem and multi-stem ensembles use only the single leading token. Members are deleted after combining unless `is_save_all_outputs_ensemble`.

Note the coupling: `Ensembler.get_files_to_ensemble` collects members by **filename prefix/suffix** (`{base} {model} ({stem}).wav`), so [core/export_naming.py](core/export_naming.py) and ensemble collection must change together — a naming tweak that looks cosmetic will make ensembles silently produce single-member output.

**Stem export resolves by concept, not by native key.** [core/stems.py](core/stems.py) turns a model's outputs into `StemRoute`s — the `native` yaml/source key it is addressed by, a stable `concept` id (bucket value or `raw:<casefolded>`), and the `label`/`filename_tag` it is written under. `model_stem_routes` is the single inventory and `select_stem_routes` matches `process.stem_focus` against it; `assemble_model` stores both sides on `ModelConfig.StemRouting` (`available_routes` / `selected_routes`). Engines write from `run_export_routes` / `exports_named_stem` ([core/stems.py](core/stems.py)): vocal splitters and 4-stem/multi-stem ensemble *members* emit the full inventory, and every other run uses `selected_stem_routes`. `_apply_stem_focus` ([core/model_config/config.py](core/model_config/config.py)) only fills those route tuples — it does not rewrite `primary_stem`, `mdxnet_stems_selected`, or `demucs_stems`. `primary` / `secondary` in `stem_focus` are positional sentinels (CLI `--stems primary|secondary`); they filter `selected_stem_routes` to the model's primary/secondary native or derived complement. When `stem_focus` is empty, a multi-stem MDX-C subset in `mdxnet_stems_selected` still filters `selected_stem_routes` (Demucs/VR leftover sidecars are ignored). A new exportable output needs a route in `model_stem_routes`, or planning, filenames and the engines disagree with what is actually written.

`instrumental` on a multi-source MDX-C model is a **derived** route with no native key: `derive_mdx_multi_complement` ([engines/mdx_c.py](engines/mdx_c.py)) either sums the remaining sources or subtracts the primary from the mix depending on Combine Stems. That is a recipe change only — it must never change the route's concept, label or filename.

**Stem focus is validated at plan time, and severity follows provenance.** `_stem_focus_diagnostics` ([core/job_plan.py](core/job_plan.py)) makes an unavailable stem an `error` when it came from the CLI and a `warning` (fall back to every viable output) when inherited from a GUI profile. For 4-stem and multi-stem ensembles focus filters only the **final** combined outputs — members must still emit their complete stem set for aggregation — and `select_ensemble_stem_routes` reports `INSUFFICIENT_MEMBERS` separately from unmatched when fewer than two members contribute.

**Semantic review and catalogue evidence availability are independent.** Reviewed/waived/raw stem status comes only from the unified manifest; `ready`, `pending`, `unavailable`, `stale`, and `not_applicable` describe whether exact catalogue/config evidence can currently be validated. A timeout, cold cache, or stale last-known-good entry must not downgrade a reviewed declaration to raw, and successful parsed evidence may report drift but must never invent semantics.

**Run payloads are typed.** `ProcessData` carries callbacks, routing flags, and source-cache state into engines. Engines reuse already-computed stems within one input file via its `cached_source_callback` / `cached_model_source_holder` fields; the runner clears the cache per input file (`_cached_sources_clear`). `_build_all_models` supplies `list_all_models`, which engines use to decide whether a referenced primary/secondary model actually participates in this run.

### UI structure

`UVRApplication` ([ui/application.py](ui/application.py)) → `MainWindow` ([ui/window.py](ui/window.py)), with one `AppContext` ([ui/context.py](ui/context.py)) holding the shared `Settings` and lazily-built repository/runner. Per-method option panels are `MethodView` subclasses in [ui/views/](ui/views/) registered in `METHOD_VIEWS` — add a method there rather than editing the window assembly. Options shared across Separation/Ensemble/Audio Tools live in [ui/shared_settings.py](ui/shared_settings.py).

## Maintenance scripts

Three command entry points under `scripts/`, plus `model_tool_support.py` and the `scripts/catalogue/` collection/rendering package. None are part of the app.

- **`scripts/*` is gitignored behind an allowlist.** A new script needs its own
  `!scripts/<name>.py` line in [.gitignore](.gitignore), or `git add` refuses it and the
  file never lands.
- **One shared low-level module.** [scripts/model_tool_support.py](scripts/model_tool_support.py)
  owns validated HTTP ranges, checkpoint headers and tail hashes, catalogue target
  resolution and cache identity. `model_probe.py` and the generator's optional
  stem-confidence audit both import from it; verdicts, reporting and architecture construction
  stay in their owning commands. Range reads validate the 206 and `Content-Range` and raise `RangeError`
  rather than returning whatever the server sent.
- **The catalogue generator publishes one validated bundle from one snapshot.** The unified manifest, catalogue Markdown, intent/display/stem TSVs, and IR are rendered and validated in memory from the same post-deduplication collection before any target is replaced; never hand-edit a generated Markdown/TSV. The generator refuses to publish a degraded run. Exit codes are distinct:
  `0` wrote/up to date, `1` drift (`--check`), `2` this run's data is too degraded to
  judge. A cold cache yields a fraction of the catalogue, so without the guard a partial
  run replaces a good 7,000-line document. `--allow-degraded` overrides.
- **`--check` and `--summary` are read-only.** Publication YAML evidence comes only from
  checked-in seed configs or the URL-keyed generator cache; `FetchPolicy.allow_cache_writes`
  gates persistence there, and no generator path writes runtime model config storage.
  `--summary` prints to stdout and writes nothing.
- **Drift means the catalogue changed, not that time passed.** `--check` compares canonical
  forms with the volatile header lines (`Generated:`, provenance, cache ages) stripped.
- **Ephemeral catalogue caches live under `CACHE_DIR`**, separate from the checked-in
  unified authority and runtime/user state. Source/config entries are keyed by URL rather
  than basename (two models can both ship a `config.yaml`) and use TTL plus stale-while-
  revalidate. The schema-2 stem-evidence cache keeps exact last-known-good parsed evidence
  and its error/staleness state; a failed refresh never erases usable evidence. `--refresh`
  forces a refetch of Download Center coordinator sources (upstream, Politrees, extras,
  mvsepless) and supplements; `--offline` is strictly cache-only and may serve stale data.
- **The `.ir.json` sidecar is tied to its document by SHA-256** and is gitignored. The
  publication guard reads its previous entry count from it only when that digest matches,
  falling back to the document — a stale sidecar must not lower the guard's floor.
- **`model_sweep.main()` asserts the parent stays torch-free.** An in-process test must hide
  `torch` from `sys.modules` for the call rather than weaken the assert; another test module
  importing torch first trips it, so failures depend on test ordering.
- **`--timeout` does not reach composite jobs.** They are their own group (`SweepJob.composite`,
  not `kind`, and not identifiable from the timeout they carry) and take `--composite-timeout`.
- **The optional stem-confidence audit caches successful hashes indefinitely and failures never.**
  Checkpoint tails are immutable once published; caching a failure would let one bad network
  day poison every later report. Run it through
  `generate_models_catalogue.py --audit-stem-confidence`; `--only`/`--limit` narrow a run,
  `--no-cache` re-fetches, and `--offline` requires the hash cache.
- **VR architecture sizes have one definition**, `VR_ARCH_SIZES` / `VR_5_1_ARCH_SIZES` in
  [ml/vr_network/nets.py](ml/vr_network/nets.py). `model_probe.py` imports them lazily —
  that module pulls in torch, and the probe must stay importable without it.
- **`build_mdx_c_model` / `filter_init_kwargs`** ([engines/mdx_c.py](engines/mdx_c.py)) are
  public engine-layer API, built against from the engine and the probe.
- Script artifacts publish through `core.json_store.write_text_atomic` / `write_json_atomic`:
  a failed write must not truncate a checked-in document, and the sweep parent treats an
  unreadable child `result.json` as a classified job failure rather than crashing.

## Repository workflow

Push to `origin` (**GitHub**: `minarru/ultimatevocalremovergtk`) only. Prefer `gh pr create` / `gh pr merge` for review. The former Codeberg remote may exist locally as `codeberg` until you remove it after archive.

The **`dev`** branch holds in-progress work that is not ready for `main`. Superpowers
plans and specs under `docs/superpowers/plans/` and `docs/superpowers/specs/` stay
on `dev` only: gitignore them on feature branches, `git add -f` them on `dev`, and
promote through `scripts/dev_docs_policy.py prepare`, which strips them before a
PR to `main`; the existing unittest job rejects them on `main` as a backstop. Do
not merge `main` back into `dev`, because its intentional removals would propagate;
cherry-pick any main-only hotfix into `dev` instead. See
[docs/superpowers/README.md](docs/superpowers/README.md).

CI is **GitHub Actions** in [`.github/workflows/`](.github/workflows/). `test.yml` runs unittest + basedpyright on push/PR to `main`. `release.yml` fires on `v*` tags and **asserts the tag equals all three version strings**: `VERSION` in [__version__.py](__version__.py), and `latest_version` in both [packaging/release.json](packaging/release.json) and [bundled/release.json](bundled/release.json). Bump all four together or the release check fails.

```bash
gh run list
gh pr checks
```

Known bugs and roadmap gaps are tracked in [docs/tracked-issues.md](docs/tracked-issues.md); check it before filing or "fixing" something.

## Conventions

- Search with `rg` (ripgrep), not `grep` or `git grep` — see [.cursor/rules/use-rg.mdc](.cursor/rules/use-rg.mdc).
- GTK-dependent tests guard with `@unittest.skipUnless(...)` plus `gi.require_version("Gtk", "4.0")` / `("Adw", "1")` inside `setUpClass`, so the suite still runs where GTK is unavailable. Non-UI logic is tested by mocking `GLib.idle_add` rather than starting a main loop.
- **GTK display-backend selection:** follow the [authoritative environment convention](docs/environment.md#gtk-display-backend-testing); do not mix private Wayland, Xvfb, or active-host sessions.
- Structured diagnostics go through [core/debug_log.py](core/debug_log.py). Errors are recorded by default in the rotating cache log; Preferences and CLI `--debug` / `--trace` raise the level, while `G_MESSAGES_DEBUG` and `UVR_VERBOSE` remain development compatibility switches. Use named `log_event` boundaries for new code and keep high-frequency events Trace-only. Full privacy and switch details are in [docs/environment.md](docs/environment.md).
- Upstream's `Seperate*` misspelling is the real class-name prefix across the engine layer — keep it. Likewise, the error strings in `bundled/error_handling.py` are matched against upstream tracebacks verbatim; don't "fix" them.
- Tests that build a real `MainWindow` read on-disk `settings.json` via `AppContext()` — set every setting an assertion depends on. Verify isolation with `UVR_DATA_DIR=<scratch>` (symlink `models/` into it, or model resolution comes back empty).
- `core.model_display.format_tag_title` normally reads the attached `CatalogueCoordinator` display index. Its direct `load_politrees_links()` route is a compatibility fallback when no coordinator is attached; tests covering that fallback patch `core.politrees_catalog.load_politrees_links` — see [tests/test_mdx_c_registry.py](tests/test_mdx_c_registry.py).
- **The test suite blocks live outbound network.** Importing `tests` arms [tests/net_guard.py](tests/net_guard.py), which raises `BlockedNetworkAccess` on any TCP connect to a non-loopback address (AF_UNIX and loopback stay open, so GTK/DBus and local servers are fine). Set `UVR_TESTS_ALLOW_NETWORK=1` to bypass it while debugging. Note that most fetch paths swallow their own errors, so a new offender usually shows up as a slow test rather than a failure — patch the fetch instead of relying on the guard.
- **Catalogue membership has four sources:** upstream/TRvlvr, Politrees, bundled fork extras, and mvsepless. Upstream/TRvlvr, Politrees, and mvsepless are remote membership sources; extras is bundled and local. Their individual switches are `UVR_DISABLE_POLITREES`, `UVR_DISABLE_EXTRA_MODELS`, and `UVR_DISABLE_MVSEPLESS`; disabling Politrees alone leaves extras and mvsepless. CI runs `unittest discover -s tests -t .` so `tests/__init__.py` arms the network guard. Any test reaching compatibility `_merged_for_display()` must neutralise the relevant remote compatibility sources and, when membership matters, extras as well.
- `CatalogueCoordinator` owns source snapshots, merge, and projections for one AppContext or CLI command. `ModelRepository.inventory_generation` still changes only when installed files/local metadata change. Catalogue/identity refinements must not bump it or rebuild picker membership. Use `invalidate_model_presentation(reload_mappers=False)` for catalogue source/association refinements and `invalidate_model_presentation(reload_mappers=True)` after durable presentation-evidence changes. Calling `reload_mappers()` alone does not notify UI consumers. `format_tag_title` is keyed on `(tag, catalogue revision, naming revision)`.
- **Job resolution fetches configs.** `resolve_mdx_jobs` → `ensure_mdx_c_config` downloads a missing MDX-C YAML. Tests that only care about the resolved job list should patch `core.mdx_config_fetch.ensure_mdx_c_config` (resolved at call time inside `politrees_catalog`) and `core.downloads.ensure_mdx_c_config` (bound by value at import).
- Modules bind network helpers by value (`from .mdx_config_fetch import _urlopen`), so patching `core.mdx_config_fetch._urlopen` does **not** intercept them. Patch the importing module's own name (`core.politrees_catalog._urlopen`, `core.mvsepless_catalog._urlopen`). Late-bound wrappers accept `str | urllib.request.Request` so conditional GETs stay interceptable.
- `core.model_display._merged_for_display()` remains a compatibility cache (`lru_cache`, keyed on `_display_generation`). Prefer coordinator indexes when a repository has been given a coordinator. `clear_display_cache()` still wraps `invalidate_catalogue_merge` for loaders that have not migrated.
- **"The models on disk changed" has one spelling: `ModelRepository.invalidate_models()`.** It clears the dry-check and karaoke pools, the ephemeral hash cache, and reloads the mappers, then fires `subscribe_models_changed`. `invalidate_stem_check()` is the narrow primitive for "filters changed, files didn't". Clearing `model_hash_table` is cheap: the persistent stat-guarded table refills it with an `os.stat` per checkpoint, not an md5.
- **Every model-list widget refreshes through `MainWindow._model_list_consumers()`** — the three `MethodView`s plus the ensemble page, Audio Tools page and the shared `VocalSplitRow`. A new model-list widget must expose `refresh_models()` and be added there; `self._views` is only the method views and is not the refresh spine.
- **Lazily-populated expander contents use `ui/widgets/lazy_populate.LazyPopulator`** (composed, no GTK import, so it tests without a display). Invalidating a lazy list is not enough on its own: repopulation hangs off `notify::expanded`, which GObject emits only on an actual change, so a section the user already has open needs `invalidate()` to repopulate it directly. Keep collapsed sections lazy — populating resolves model lists, which hashes checkpoints.
- `get_flat`/`set_flat` ([ui/settings_bind.py](ui/settings_bind.py)) **no-op silently** on a key missing from `FLAT_TO_PATH`: reads return the default, writes vanish. Nearly every UI call site builds its key at runtime, so a typo or a new field is invisible until the setting quietly stops persisting — add the mapping in `core/settings/flat_map.py` first.
- `set_combo_tag_values` takes `(stored_id, display_label)` pairs; pass `format_tag_title(tag, repo)` as the label or the list shows raw architecture-prefixed tags.
- A model combo seeded before its real list loads must not persist its value: if the stored tag is absent from the fresh list the combo falls to index 0 and writes `NO_MODEL` over the user's choice. The gate is `LazyPopulator.ready` (per-combo `entry["ready"]` in `MethodView`); a refresh must snapshot the combo's current value *before* invalidating, or the selection reverts to whatever was last applied.
- Never call `widget.destroy()` in a test or smoke script — with no running main loop it segfaults.
- GTK widget behaviour and layout-diagnosis notes live in [ui/CLAUDE.md](ui/CLAUDE.md), loaded when working under `ui/`.
- Headless CLI layer rules live in [cli/CLAUDE.md](cli/CLAUDE.md), loaded when working under `cli/`.
- **Read-only CLI commands default to offline.** `map_basenames_to_display`, `all_model_tags`, and `karaoke_model_list` (used by `--vocal-split`) reach `_merged_for_display()`, which fetches the politrees and mvsepless catalogues (30s timeout each). Read-only listing passes `allow_network=False` into catalogue helpers. Planning / validate / identity use `access_policy(allow_network=False, allow_metadata_writes=False)` / `mdx_c_network(False)`, not `catalogue_offline()`.
- This working tree often carries long-lived uncommitted edits (model metadata under `models/*/model_data/`) and ignored portable state under `.uvr-runtime/`; a legacy root `registered_models.json` may also remain until the next registry mutation migrates it. Never stage runtime state or run unscoped `git checkout -- .`, `git restore .`, `git reset --hard`, `git stash` or `git clean`; restore only exact paths, and stage explicitly rather than `git add -A`.
