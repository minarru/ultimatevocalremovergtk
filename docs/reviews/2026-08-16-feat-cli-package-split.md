# Review: `feat/cli-package-split`

**Date:** 2026-08-16  
**Branch:** `feat/cli-package-split`  
**Base:** `main` (`e4c2399`)  
**Committed HEAD:** `3faa1e8`  
**Scope reviewed:** committed range *and* the large uncommitted working tree on top of it

## Summary

There are two different change sets on this branch. Treating them as one PR would be a mistake.

| Layer | What it is | Verdict |
| --- | --- | --- |
| **Committed** `e4c2399`…`3faa1e8` | Original CLI package split: `python -m cli`, process flags, `ensemble`, `list-models`, `--json`, cooperative Ctrl-C | Already reviewed during implementation. In decent shape. |
| **Uncommitted** on top of `3faa1e8` | Redesign: delete `core/headless_run.py` / `core/cli.py`, public `uvr` entry, job/identity/catalogue services, GUI plan confirmation, settings identity migration | **Not ready to commit as-is.** Too large for one PR. |

The uncommitted work is roughly 2 070 insertions / 4 001 deletions across 58 tracked files, plus ~20 new modules. Layering still holds (`cli` → `core`, no reverse import, `cli/__init__.py` is a docstring, `import core` stays cheap). The problems are the new entry point, dropped tests, and GUI/settings side effects that do not belong in a CLI-split PR.

**Ready to merge?** No. Fix the `uvr` `cd` first, then split.

---

## Strengths (uncommitted redesign)

- **Layering is enforced, not just documented.** No `core` module imports `cli`. No tkinter in `core`/`cli`. `cli/__init__.py` is still a docstring. `import core` measured ~0.09 s with no torch/onnxruntime/gi/engines.
- **`fail()` stdout discipline is correct** (`cli/reporting.py`). The human line always goes to stderr; exactly one JSON document goes to stdout. `main()`’s `UsageError` path pre-scans argv for `--report` so argparse errors respect the selected mode.
- **Ensemble filename coupling was preserved.** `build_output_naming_context` (`core/export_naming.py`) still forces member/ensemble labels so `Ensembler.get_files_to_ensemble` prefix matching works.
- **`_promote` pre-checks all predictable targets** before moving any file (`cli/execution.py`), so a fail/skip race cannot expose half an input’s stems.
- **`run_runner_cli` restores SIGINT/SIGTERM in `finally`** (`cli/execution.py`). `run_blocking` does not re-raise `KeyboardInterrupt` (`core/blocking_runner.py`).

---

## Critical

### 1. `uvr` changes the working directory before parsing arguments

```13:14:uvr
cd "${UVR_ROOT}"
exec "${UVR_PYTHON}" -m cli "$@"
```

Relative inputs and `-o` resolve against the repo root, not the user’s cwd. The documented form `uvr separate song.wav -o ~/stems` fails unless you are already in the checkout; `-o out` can write into the tree.

**Fix:** drop the `cd`. Use `PYTHONPATH="${UVR_ROOT}" exec "${UVR_PYTHON}" -m cli "$@"`.

---

## Important

### 2. Ctrl-C tests were deleted and not replaced

HEAD had `test_stopped_run_exits_130_and_emits_json` and `test_main_keyboard_interrupt_emits_json_130` (`tests/test_cli.py`, from `659c438`). Both are gone. Nothing in `tests/test_cli*.py` asserts exit 130 or `"stopped": true`. The handler still exists in `cli/execution.py`; it is unverified. The only remaining `130` assertion in the tree is unrelated (`tests/test_stem_semantics_audit.py`).

Port those tests onto `run_runner_cli` / `BatchOutcome` / `main()`.

### 3. Interrupted batches and `main()` KeyboardInterrupt emit different JSON

`cli/execution.py` records an interrupted input as `status: "failed", error: "interrupted"` and sets `BatchOutcome.interrupted` (exit 130). `cmd_separate` / `cmd_ensemble` payloads never surface `"stopped": true`. `main()`’s own `KeyboardInterrupt` handler *does* emit `{"stopped": true}` (`cli/main.py`). Two JSON shapes for the same user action.

### 4. GUI confirms every run by default and re-hashes on the main loop

`confirm_processing_plan: bool = True` (`core/settings/model.py`, `core/settings/defaults.py`) makes `_present_plan_confirmation` fire on every Separation/Ensemble Start. Then `_accept_plan` (`ui/run_control.py`) calls `JobResolver.is_current(plan)` synchronously, which MD5s each checkpoint (`core/job_plan.py`). On a multi-GB Roformer/Demucs weight that is a multi-second GTK freeze right after “Start Processing”. The preflight resolve is correctly threaded; this recheck is not.

### 5. `ModelIdentityService.records()` always forces catalogue-offline

`core/model_identity.py` wraps enumeration in `catalogue_offline(True)` with no online opt-in. `core/offline.py` mutates `os.environ` process-wide. The UI calls `records()` from `ui/views/base.py`, `ui/ensemble/window.py`, `ui/audio_tools/window.py`, `ui/widgets/vocal_split_row.py`, and the identity-migration worker — racing the politrees/mvsepless refresh threads. Interleaved enter/exit can leak `UVR_DISABLE_*=1`.

`_merged_for_display_at` is memoized on `_display_generation` alone (`core/model_display.py`). An early forced-offline `records()` can pin a local-only merge for the session.

### 6. Fuzzy resolve can rewrite a stored model across families

`ui/views/base.py` does `ModelIdentityService(repo).resolve(str(stored)).id` then `set_flat(...)`. `resolve()` defaults to `fuzzy=True` and, with no `family:` prefix, searches all families (`core/model_identity.py`). A bare stored display name can resolve into another family and get persisted into `vr.model`. The old `current_display_for_stored_model` was scoped to that arch’s basenames. Same pattern in `IdentityMigrator.canonical(..., family=None)` for `process.vocal_splitter` / secondaries (`core/identity_migration.py`) and in `assemble_model`’s `engine_value` (`core/model_config/assemble.py`).

### 7. Startup identity migration is racy

- `AppContext.start_identity_migration` (`ui/context.py`) reads `self.repo` from a worker. `AppContext.repo` is an unlocked lazy property. Concurrent first-touch can build two repositories and lose the unrecognized-model dialog hook.
- `MainWindow._on_identity_migration_complete` does `self.settings.__dict__.update(migrated.__dict__)` where `migrated` is a startup deepcopy. Edits made while the worker ran are silently reverted.
- `migrate_identity_storage` calls `settings.save()` from that worker (`core/identity_migration.py`) — a second writer to `settings.json`.
- `IdentityMigrator._known_records` calls `DownloadManager().ensure_catalogues()` — unguarded network on first startup.

### 8. Desktop entry loses venv self-repair

`packaging/desktop_entry.sh` changes `Exec=${HERE}/run_uvr.sh` → `Exec=${HERE}/uvr gui`. `run_uvr.sh` rebuilds stale venvs; `uvr` prints to stderr and exits 2. With `Terminal=false`, a broken venv becomes a silent no-op.

### 9. Breaking changes are undocumented

`docs/environment.md` deleted the trampoline / `--json-out` notes and added no migration table. Undocumented removals or renames:

| Old | New |
| --- | --- |
| `python -m core.cli` / `python -m core` | gone |
| `python -m cli` | `uvr` (internal: `python -m cli`) |
| `bench-ab` | `bench` |
| `--json` | `--report json` |
| `--json-out` | `--manifest-out` |
| `--print-settings` | `--verbose` |
| `--method` | gone (family is on the model id) |
| `--cpu` / `--gpu` | `--device` |
| `list-models` | `models list` |

### 10. `settings.json.pre-canonical-id.bak` is not gitignored

`.gitignore` has `data.pkl.bak` and `settings.json` but not `settings.json.*`. `git check-ignore` does not match the backup. Add `settings.json.*.bak` before anyone runs a broad add.

### 11. `uvr settings show` prints raw dict reprs

`_print_rows` (`cli/discovery.py`) does `"\t".join(str(value) for value in row.values())` on nested dicts. This also hits the `enum_value` trap: un-JSON-ified enums render as `SaveFormat.WAV`.

### 12. `models configure` skips the offline guard

`cli/discovery.py` builds a bare `ModelRepository()` and calls `ModelIdentityService(repo).resolve(...)` outside `catalogue_offline`. Siblings wrap it. Masked today because `records()` forces offline internally; once issue 5 is fixed this becomes a 60 s stall.

### 13. `models register` MD5s the entire installed tree

`cli/discovery.py` iterates every installed record and hashes each checkpoint to detect a duplicate. On a populated `models/` that is minutes of I/O for a one-file registration.

### 14. `validate --level model` resolves the job twice

`cli/validate.py`: `resolver(args, verify_model=True)` produces a MODEL-level plan, then a fresh `JobResolver(ModelRepository())` re-resolves without `metadata`. Duplicate hashing; profile, preset, and collision policy vanish from the reported plan.

---

## Minor

- **Dead code:** `cli/validate.py` `_load_checkpoint` is unused (`core/job_plan.py` owns LOAD). Unused `check_runtime_deps` import. `cli/bench.py` `build_separate_argv` has no callers. `OutputNamingContext.extension` is computed and never read.
- **Unused imports** in new/modified CLI modules: `ENSEMBLE_MODE` in `cli/job.py`, `json` in `cli/profiles.py` / `cli/audio.py`, hash-dir constants in `cli/discovery.py`, `report_mode` in `cli/bench.py`, `Any` in `cli/validate.py`.
- **`--report json` drops engine console entirely** (`cli/execution.py` `print_console` only when `report == "human"`). Old contract: `--json` quiets engine stdout; progress and errors stay on stderr.
- **`cli/replay.py` spawns `-m cli` without `PYTHONPATH`.** Works only because `uvr` `cd`s to the root — fixing issue 1 will break `uvr run` unless replay adopts `cli/bench.py`’s `_child_env`.
- **`--profile gui` never inherits Audio Tools settings** (`cli/profiles.py` excludes `audio_tools`), but `cli/replay.py` includes them for `command == "audio"`.
- **`cmd_models_download` Ctrl-C has no force path** (`cli/discovery.py`), unlike the cooperative-then-forced contract in `cli/CLAUDE.md`.
- **`tests/test_removed_headless_surface.py`** dodges its grep with `"core." + "headless_run"` and does not scan `ui/` or docs.
- **`core/identity_migration.py`** `os.path.commonpath` check for a `cli` subdirectory is unreachable (loop already skips non-`.json`).
- **`assemble.py`** `if not str(value or "").split(":", 1)[0].casefold() in {...}` parses correctly but reads as a precedence bug; `not in` is clearer.

---

## Test-story regression

This is not a refactor that kept its tests. It replaced ~60 CLI tests with ~22. Deletions are concentrated where the committed layer had just fixed bugs:

- `test_stopped_run_exits_130_and_emits_json`
- `test_main_keyboard_interrupt_emits_json_130`
- `test_json_owns_stdout_and_suppresses_console`
- `test_uses_run_ensemble_sync_not_run_separation_sync`
- `test_missing_member_source_exits_two`
- `test_every_named_flag_targets_a_real_setting` (guard against silent `set_flat` no-ops)
- `test_offline_by_default_sets_both_disable_flags`
- `test_importing_core_does_not_import_cli` (replaced by a heavy-stack guard that checks something else)

The `ensemble` command surface is down to two tests. Commits `659c438` and `3faa1e8` exist on this branch because those paths were subtly wrong once already.

---

## Suggested split

Each slice independently reviewable and testable:

1. **`core` service extraction, behaviour-neutral** — `model_identity`, `model_registry`, `model_catalogue`, `ensemble_service`, `input_discovery`, `audio_probe`, `device`, `json_store`, `offline`, `blocking_runner`, plus `core/__init__` re-exports. Keep the existing CLI on top so the old tests still run and prove neutrality.
2. **`job_plan` / `audio_plan` and the shared resolver.**
3. **CLI surface rewrite** — `uvr` entry, subcommand modules, report modes. **Port the deleted tests.** Add a breaking-change table to `docs/environment.md`.
4. **Identity migration** — `identity_migration`, `identity_schema_version`, `.pre-canonical-id.bak`, plus the `.gitignore` entry. Own review: it rewrites persisted settings on a worker thread at startup.
5. **GUI preflight + plan confirmation.** User-visible default change; nothing to do with a CLI package split.

---

## Not reviewed in depth

- `core/job_plan.py` `JobResolver.resolve` / `adopt` / diagnostic codes. `run_batch` reads `job.plan["inputs"][i]["basename"]` positionally against `job.inputs` (`cli/execution.py`) — confirm the resolver guarantees that order.
- `core/audio_plan.py` and `cli/audio.py` dual-input `--pair` staging/promotion and `cmd_audio_validate`.
- `cli/discovery.py` `models catalog` / `models download` vs `core/model_catalogue.py` (`CatalogEntryId` quoting, `service.jobs()`).
- `core/settings/job_resolution.py` layer precedence vs the hand-built `_source_map` in `cli/job.py` (resolver `_layer_sources` is discarded at both call sites).
- `--on-exists rename` branch of `_promote` (`cli/execution.py`).
- `scripts/model_sweep.py` (170-line retarget).
- basedpyright on this working tree (CI gates it).

---

## Committed range (for context)

Already implemented and reviewed on this branch before the redesign:

| Commit | Subject |
| --- | --- |
| `bd0e427` | Plan file checkpoint |
| `7d0b1d4` | Extract `cli/` package |
| `6c10745` | Validated `(path, value)` overrides |
| `88ed0c1` | Shared process flags |
| `f28bbea` + `2d37689` | `--json` / `--quiet` / progress |
| `da1192b` + `60742de` | Cooperative Ctrl-C, exit 130 |
| `6d3d1d4` | Ensemble library helpers |
| `8703988` + `e81a086` | `ensemble` command |
| `2848c5b` | `list-models` |
| `6b4ab12` + `566a6bb` | Docs |
| `659c438` | JSON-safe `ValueError`, `--algorithm`, signal edges |
| `3faa1e8` | Write `--json-out` before claiming success |

Parked from that review (still true of the committed layer, and still true after the redesign unless re-fixed): `--set` value typos still go through lenient `coerce_field` (`process.save_format=falc` → WAV). Only `--algorithm` was made strict.
