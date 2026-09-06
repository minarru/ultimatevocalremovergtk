# AGENTS.md

Shared guidance for coding agents working in this repository.

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

## Architecture and scope

Before changing application code, read [docs/development-architecture.md](docs/development-architecture.md) for the settings, model identity, planning, stem routing, and export contracts. Keep backend code independent of GTK and CLI presentation; keep heavy imports lazy. Canonical model IDs are `family:basename`, never display labels. Resolve writable data through `core.paths` and preserve the single bundled model manifest authority.

Scoped guidance lives in [ui/AGENTS.md](ui/AGENTS.md), [cli/AGENTS.md](cli/AGENTS.md), and [scripts/AGENTS.md](scripts/AGENTS.md). Read the relevant scoped file when changing those modules from the repository root.

## Repository workflow

Push to `origin` (**GitHub**: `minarru/ultimatevocalremovergtk`) only. Prefer `gh pr create` / `gh pr merge` for review. The former Codeberg remote may exist locally as `codeberg` until you remove it after archive.

Root `.superpowers/` scratch files also stay off `main`; the main-branch policy check covers that directory as well as plans and specs.

The **`dev`** branch holds in-progress work that is not ready for `main`. Superpowers
plans and specs under `docs/superpowers/plans/` and `docs/superpowers/specs/` stay
on `dev` only: gitignore them on feature branches, `git add -f` them on `dev`, and
promote through `scripts/dev_docs_policy.py prepare`, which strips them before a
PR to `main`; the existing unittest job rejects them on `main` as a backstop. Do
not merge `main` back into `dev`, because its intentional removals would propagate;
cherry-pick any main-only hotfix into `dev` instead. See
[docs/superpowers/README.md](docs/superpowers/README.md).

CI is **GitHub Actions** in [`.github/workflows/`](.github/workflows/). `test.yml` runs unittest + basedpyright on pushes to `main` and every PR. `release.yml` fires on `v*` tags and **asserts the tag equals all three version strings**: `VERSION` in [__version__.py](__version__.py), and `latest_version` in both [packaging/release.json](packaging/release.json) and [bundled/release.json](bundled/release.json). Bump all four together or the release check fails.

```bash
gh run list
gh pr checks
```

Known bugs and roadmap gaps are tracked in [docs/tracked-issues.md](docs/tracked-issues.md); check it before filing or "fixing" something.

## Conventions

- Search with `rg` (ripgrep), not `grep` or `git grep`.
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
- GTK widget behaviour and layout-diagnosis notes live in [ui/AGENTS.md](ui/AGENTS.md), loaded when working under `ui/`.
- Headless CLI layer rules live in [cli/AGENTS.md](cli/AGENTS.md), loaded when working under `cli/`.
- **Read-only CLI commands default to offline.** Display resolution can reach remote catalogue metadata through compatibility helpers unless network access is disabled. Read-only listing passes `allow_network=False` into catalogue helpers. Planning / validate / identity use `access_policy(allow_network=False, allow_metadata_writes=False)` / `mdx_c_network(False)`, not `catalogue_offline()`.
- This working tree often carries long-lived uncommitted edits (model metadata under `models/*/model_data/`) and ignored portable state under `.uvr-runtime/`; a legacy root `registered_models.json` may also remain until the next registry mutation migrates it. Never stage runtime state or run unscoped `git checkout -- .`, `git restore .`, `git reset --hard`, `git stash` or `git clean`; restore only exact paths, and stage explicitly rather than `git add -A`.
