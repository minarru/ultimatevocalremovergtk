# Review pass 2: `feat/cli-package-split` redesign

**Date:** 2026-08-16  
**Branch:** `feat/cli-package-split`  
**Base:** `main` (`e4c2399`)  
**Committed HEAD:** `3faa1e8`  
**Scope:** uncommitted working tree on top of `3faa1e8` (about 2 600 insertions / 4 100 deletions across 70 tracked files, plus new `cli/` / `core/` modules). Re-checked every pass-1 finding and reviewed the areas pass 1 left open.

Pass 1: [2026-08-16-feat-cli-package-split.md](2026-08-16-feat-cli-package-split.md).

## Verdict

The pass-1 **Critical** (`uvr` `cd`) is fixed and tested. Several pass-1 Importants were also fixed. The tree is in better shape than yesterday.

It is still **not ready to commit as one PR**. The remaining defects are smaller than a cwd rewrite, but two of them will silently mangle filenames or break `--profile gui` after the identity migration this same change set performs.

**Ready to merge?** No. Fix the two filename/identity bugs, then split as before.

basedpyright on the new/rewritten modules reviewed here: **0 errors**.

---

## What improved since pass 1

| # | Pass-1 finding | Status |
| --- | --- | --- |
| C1 | `uvr` `cd`s to the repo | **Fixed.** No `cd`. `PYTHONPATH="${UVR_ROOT}" exec … -m cli`. `uvr gui` execs `run_uvr.sh`. Covered by `tests/test_uvr_launcher.py`. |
| I2 | Ctrl-C tests deleted | **Fixed.** `tests/test_cli.py` asserts exit 130 and `"stopped": true` for batch, `main()` `KeyboardInterrupt`, and JSONL. `test_cli_redesign.py` covers cooperative-then-force. |
| I3 | Interrupted JSON missing `"stopped"` | **Fixed.** `cmd_separate` / `cmd_ensemble` / `cmd_audio` / manifests include `"stopped": outcome.interrupted`. |
| I4 | `is_current` MD5 on the GTK thread | **Fixed.** Recheck runs on `uvr-plan-recheck`. Confirm-every-run default is unchanged (product issue, see I7 below). |
| I5 | `records()` forced `catalogue_offline` / env races | **Fixed in spirit.** `records()` now passes `allow_network=False`. `catalogue_offline()` is a **no-op** (see I5′). |
| I6 | Fuzzy resolve rewrites primary models across families | **Fixed for method views.** `ui/views/base.py` passes `family=family`. Apollo restore passes `family="apollo"`. Unscoped paths remain (vocal splitter / secondaries). |
| I7 | Identity migration races / `__dict__.update` / off-thread `save()` / network | **Mostly fixed.** Worker migrates a deepcopy; `AppContext.apply_identity_migration` patches only unchanged paths on the main thread and saves there. `ensure_catalogues(allow_network=False)`. Profile/ensemble JSON is still written from the worker. |
| I8 | Desktop entry loses venv repair | **Fixed.** `uvr gui` → `run_uvr.sh`. |
| I9 | Breaking changes undocumented | **Fixed.** `docs/environment.md` has a migration table. |
| I10 | `settings.json.*.bak` not gitignored | **Fixed.** |
| I11 | `settings show` raw dict / enum reprs | **Fixed.** `_human_cell` JSON-ifies containers and unwraps `Enum`. |
| I12 | `models configure` skips offline | **Masked.** `resolve()` → `records()` is local-only. The wrapper is still a no-op. |
| I13 | `models register` hashes the whole tree | **Fixed.** `ModelRegistryService.registered_id(model_hash)` fingerprints only the new file. |
| I14 | `validate --level model` resolves twice | **Fixed.** Uses `job.resolved`. |
| M | `replay.py` missing `PYTHONPATH` | **Fixed.** `_child_env()`. |
| M | `--report json` drops engine console | **Fixed.** `print_console=not args.quiet` (stderr). |

---

## Strengths (this pass)

- **`JobResolver._plan_inputs` order matches `job.inputs`.** `run_batch` indexing `job.plan["inputs"][i]` is safe. The plan dict stores `path` + `naming.track_base`, not `basename`; execution falls back correctly.
- **Settings layers are no longer discarded.** `cli/job.py` keeps `SettingsResolver` provenance and puts it on `JobSpec`.
- **Identity apply is conflict-aware.** Live edits during the worker are preserved; only the schema version is skipped when anything conflicted.
- **Catalogue policy is an argument, not an env mutation.** `allow_network=` is threaded through display merge, repo indexes, and `DownloadManager.ensure_catalogues`.
- **Audio `--pair` planning is coherent.** `AudioJobResolver` validates same-file pairs, missing files, and tool-specific options. Align/match stage then `_promote` without a shared basename, which is the right call for unrelated output names.
- **`model_sweep.py` retarget looks sound.** Children use `JobResolver` / `AudioJobResolver` / `run_blocking` and still kill the process group on timeout.

---

## Important

### 1. `_apply_planned_basename` double-applies a suffix the engine already wrote

`cli/execution.py` rewrites staged files from the *input* basename to `naming.track_base` by prefix substitution:

```232:242:cli/execution.py
def _apply_planned_basename(stage: str, input_path: str, planned: str) -> None:
    original = os.path.splitext(os.path.basename(input_path))[0]
    if original == planned:
        return
    for root, _dirs, files in os.walk(stage):
        for name in files:
            if name.startswith(original):
                os.replace(
                    os.path.join(root, name),
                    os.path.join(root, f"{planned}{name[len(original):]}"),
                )
```

`JobRunner` already writes `format_stem_basename(naming.track_base, stem)`. When `track_base` is a superstring of the input basename — `process.add_model_name=True`, or ensemble `append_ensemble_name=True` — the file is already `song Model (Vocals).wav`. The rewrite keeps the leading `song` match and produces `song Model Model (Vocals).wav`.

Defaults (`add_model_name=False`, `append_ensemble_name=False`) take the `original == planned` early return, so a clean single-file run is fine. `--profile gui` with those options on, or any `--set process.add_model_name=true`, is not.

Multi-file batches use a `1-` prefix, so `startswith(original)` misses and the rewrite is skipped — accidentally safe.

**Fix:** do not rewrite names the runner already composed. Either promote the staged tree as-is, or match on the full engine prefix (`original` plus the exact suffix the plan already baked in), not `startswith(original)`.

There is no test against real `format_stem_basename` output. `test_same_basename_inputs_receive_deterministic_names` injects a synthetic `basename` and a fake `song_(Vocals).wav`.

### 2. `--profile gui` double-prefixes already-canonical model IDs

After identity migration, `settings.mdx.model` is `mdx:UVR-…`. `_identity_from_gui` always adds the family again:

```85:92:cli/profiles.py
    section = {"vr": settings.vr, "mdx": settings.mdx, "demucs": settings.demucs}.get(family or "")
    model = str(getattr(section, "model", "") or "") if section is not None else ""
    return (f"{family}:{model}" if family and model else None), None, []
```

`resolve_separate_job` then calls `resolve_model_id("mdx:mdx:UVR-…")`. Exact match fails; fuzzy may fail or pick the wrong row. `JobResolver._identity_records` already has the correct guard (`prefix not in {vr,mdx,demucs}`). Use that.

Ensemble members from the GUI are used as-is and are fine.

### 3. Ensemble plans use the first member’s stems, not `ensemble.main_stem`

`JobResolver._plan_inputs` takes `descriptors[0]` and `_stems(settings, descriptor)` (`primary_stem` / `secondary_stem`, honoring `primary_stem_only`). Ensemble export uses `ensemble.main_stem` buckets (`JobRunner` `ensemble_primary_stem` / `ensemble_secondary_stem`). A 4-stem ensemble whose first member is a 2-stem VR model is planned as two guaranteed outputs. Dry-run JSON, GUI “N guaranteed”, and any consumer of `plan["inputs"][i]["outputs"]` are wrong. CLI collision preflight does **not** use those paths (it prefix-matches the input basename), so this does not by itself overwrite files.

### 4. Starting a GUI run replaces the live `Settings` object graph

```185:187:ui/run_control.py
            self._window.settings.__dict__.update(
                copy.deepcopy(plan.settings).__dict__
            )
```

`JobResolver` mutates the plan copy: fills `mdx.compensate` / `demucs.segment` when they were `None` (auto), rewrites model fields to canonical IDs, sets `export_path`. Those nested dataclasses replace the ones widgets are bound to. The next save persists model-native numbers the user never chose. Prefer copying only the fields the run must adopt, or run from the plan settings without writing them back.

### 5. `catalogue_offline()` is a no-op; the docs still describe the old contract

```13:16:core/offline.py
@contextlib.contextmanager
def catalogue_offline(enabled: bool = True) -> Iterator[None]:
    del enabled
    yield
```

`cli/CLAUDE.md` and root `CLAUDE.md` still say it sets `UVR_DISABLE_*`. Call sites that only wrap this and then hit `_merged_for_display()` (default `allow_network=True`) will fetch. Identity listing is safe because it passes `allow_network=False` explicitly. Update the docs, or restore a real guard for leftover call sites.

### 6. Identity migration still writes profile/ensemble JSON from a worker

`migrate_identity_storage` still `backup_once` + `write_json_atomic` on every stale profile/ensemble file inside the background thread. Settings.json is the part that moved to the main thread. Editing a saved ensemble during the first second of startup can still race. Vocal splitter and per-stem secondaries still call `canonical(..., family=None)` and can jump families.

### 7. Plan confirmation still defaults on

`confirm_processing_plan: bool = True` is now a preference, but every existing user gets a modal on Start. That is a product change bundled into a CLI rewrite. Default it off, or ship it in the GUI-preflight slice.

### 8. `_promote --on-exists rename` can split a stem pair

When `basename` is set and every staged name starts with it, the batch rename keeps `(Vocals)` / `(Instrumental)` together (`song_2 (Vocals).wav`). If any name does *not* start with `basename` (index prefix, or leftover after issue 1), those files fall through to per-file `_unique_target` and can become `…_2` / `…_3`. Audio tools omit `basename` on purpose; align/match pairs have the same split risk.

No unit tests exercise the rename branch.

---

## Minor

- **`cli/CLAUDE.md` “read-only commands default to offline via `catalogue_offline()`”** is false. Same sentence in root `CLAUDE.md` still names `cli/offline.py`, which is deleted.
- **`_flatten_settings` drops lists.** GUI profile provenance/re-apply skips `mdx.stems_selected` and any other list. The live `Settings.load()` object still has them; replay’s `_flat_settings` keeps lists. Inconsistent.
- **`settings show` omits `audio_tools` and `ui`.** `_setting_paths` only walks process/vr/mdx/demucs/ensemble.
- **`models download` second SIGINT raises `KeyboardInterrupt` from the handler** rather than a cooperative force flag. Exit 130 is still set if `stop_event` is set.
- **Manifest schema split:** jobs write `schema_version: 1`; audio writes `2`. `uvr run` accepts both. Fine, but undocumented.
- **`test_removed_headless_surface.py`** still concatenates `"core." + "headless_run"` to dodge its own scan and still ignores `ui/` / docs.
- **`assemble.py` `engine_value`:** bare (non-`family:`) names are passed through unchanged — the pass-1 cross-family rewrite is gone. The `not … in {…}` form still reads like a precedence bug; `not in` is clearer.
- **Parked from the committed layer:** `--set process.save_format=falc` still coerces to WAV. Only `--algorithm` is strict.

---

## Previously unreviewed areas (this pass)

| Area | Result |
| --- | --- |
| `JobResolver.resolve` / `adopt` / `is_current` | Sound. CONFIG skips assemble; MODEL hashes; LOAD opens ONNX/torch. `is_current` is now off the GTK thread. Ensemble identity requires ≥2 members. |
| `run_batch` vs `plan["inputs"][i]` | Order is guaranteed. Uses `naming.track_base`. The rewrite itself is issue 1. |
| `SettingsResolver` vs CLI `_source_map` | Old discarded-sources issue is gone. |
| `core/audio_plan.py` / `cli/audio.py` `--pair` | Planning and staging look correct. Promotion-without-basename is intentional. |
| `cli/discovery.py` catalog / download | `CatalogEntryId` quotes the selection (`catalog:mdx:…`). `jobs()` is a thin `manager.resolve` wrap. Download has a stop event and `"stopped"` in the result. |
| `_promote` rename | See issue 8. Fail/skip still pre-check all targets before moving. |
| `scripts/model_sweep.py` | Uses the new resolvers and `run_blocking`; process-group kill unchanged. `--method` / `--json` here are the sweep’s own flags, not the public CLI. |

---

## Test story

Better than pass 1: 130 / `"stopped"` / launcher cwd / identity apply / blocking runner are back. Still thin where the new machinery is most likely to be wrong:

- No test that staged engine names (`song (Vocals).wav` / `song Model (Vocals).wav`) survive promotion.
- No test for `--on-exists rename` keeping a stem pair together.
- No test that `--profile gui` after canonical IDs still resolves.
- No test that an ensemble plan’s `outputs` match `ensemble.main_stem`.
- Ensemble command surface is still a handful of tests versus the suite that found `659c438` / `3faa1e8`.

---

## Suggested split (unchanged)

1. **`core` services, behaviour-neutral** — identity, registry, catalogue, ensemble service, discovery, probe, device, json_store, offline-as-argument, blocking_runner. Keep the existing CLI so the old tests prove neutrality.
2. **`job_plan` / `audio_plan`.** Fix ensemble stem planning here.
3. **CLI / `uvr` rewrite.** Port remaining tests. Fix issues 1, 2, and 8 before this lands.
4. **Identity migration** — own review; worker-written profile files and unscoped `canonical()`.
5. **GUI preflight + plan confirmation.** Do not default the modal on in a CLI PR. Drop the `__dict__.update`.

---

## Committed range

Unchanged from pass 1. `e4c2399`…`3faa1e8` is the original package split and is in decent shape. The redesign on top of it is still a second project.
