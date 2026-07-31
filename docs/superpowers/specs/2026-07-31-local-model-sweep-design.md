# Local model sweep — design

**Date:** 2026-07-31
**Status:** approved, not yet implemented

## Problem

`MelBandRoformer.__init__` rejected `attn_dropout=0` from its YAML because beartype's
default configuration disallows PEP 484's implicit numeric tower. Twelve of the
twenty-two installed MDX models could not be constructed at all, and nothing in the
test suite noticed: the suite builds tiny synthetic Roformers, never the models on
disk. Weights are gitignored, so CI structurally cannot catch this class of bug.

We want a local-only sweep that starts a real run for every model present on this
device and reports which ones fail.

## Goals

- Catch any error that occurs between "user presses Start" and "stems are on disk",
  for every installed model: config resolution, network construction, weight loading,
  inference, chunking, export naming, cleanup.
- Cover the multi-pass shapes (ensemble, secondary chain, vocal splitter, 4-stem)
  that single-model runs never reach.
- Never touch the user's `settings.json`, export folders, or model tree.
- Stay out of CI. Zero added cost to `unittest discover`.

## Non-goals

- Audio quality. A model that produces garbage passes, as long as it produces it.
- Progress-bar accuracy, SDR, timing regressions, memory profiling.
- Running models that are not installed. Nothing is downloaded.

## Deliverables

| File | Purpose |
|---|---|
| `scripts/model_sweep.py` | Parent driver + child worker (one file, two modes) |
| `tests/test_model_sweep.py` | Always-on unit tests for pure helpers; full sweep behind an env guard |
| `core/headless_run.py` | Add `run_ensemble_sync` (supporting change) |
| `core/settings/` | Move `get_path` / `set_path` down from `ui/` (supporting change) |

## Supporting changes to existing code

### 1. `run_ensemble_sync`

`run_separation_sync` raises on `ENSEMBLE_MODE` ("not supported by the headless CLI
(v1)", `core/headless_run.py:411`). Extract its callback/wait/cleanup plumbing into a
private `_run_job(start_fn, settings, input_paths, ...)` and add `run_ensemble_sync`
alongside, calling `JobRunner.start_ensemble`. Roughly 30 lines moved, no behavior
change for existing callers, no new CLI surface. The alternative — re-implementing
`JobCallbacks` + `done.wait()` + `release_inference_memory` inside the sweep — would
drift from the real path and defeat the point of the exercise.

### 2. `get_path` / `set_path` move to `core`

They live in `ui/settings_bind.py` but depend only on `core.settings`,
`core.settings.coerce` and `core.settings.flat_map`. The sweep needs typed setting
writes and must not import GTK. Move both (and `get_flat` / `set_flat`) into
`core/settings/`, leaving thin re-exports in `ui/settings_bind.py` so existing UI call
sites are untouched.

Per CLAUDE.md, `set_flat` silently no-ops on a key missing from `FLAT_TO_PATH`. Every
flat key the sweep writes must be confirmed present in `core/settings/flat_map.py`
during implementation; add missing mappings there first.

## Architecture

Parent and child are the same file, selected by `--run-job`.

### Parent

1. Builds a scratch data dir: `UVR_DATA_DIR=<tmp>`, with `models/` symlinked to the
   repo's model tree (the isolation recipe CLAUDE.md prescribes — without the symlink
   model resolution comes back empty).
2. Copies the user's `settings.json` into the scratch dir as the base settings, so the
   sweep reproduces the configuration that actually runs on this machine
   (`mdx_segment_size=2208`, `denoise_option=Standard`, GPU on). `--stock-settings`
   uses `Settings()` defaults instead.
3. Generates the input clip once (below).
4. Discovers jobs, then runs each in its own subprocess **serially** —
   `subprocess.run()` in a loop. One child alive at a time; peak memory equals a single
   normal run. There is deliberately no `--jobs` flag.
5. Classifies each result, prints a live table, writes `--json`, sets the exit code.

The parent imports only `core`, which lazy-imports torch by design, and sets
`UVR_SKIP_SEPARATE_WARMUP=1` so the warm-up thread does not pull torch in behind it.
Parent RSS stays around 50 MB and it holds no CUDA context.

### Child

`python scripts/model_sweep.py --run-job <spec.json>` reads a job spec, builds
`Settings`, runs exactly one job, writes `<job_dir>/result.json`, exits.

Job spec fields: `id`, `kind` (`single` | `ensemble` | `tool`), `method`, `model`,
`settings_overrides` (flat key → value), `input_path`, `export_dir`, `cpu`, `timeout`.

Result JSON: `verdict`, `exception_type`, `message`, `elapsed_s`, `outputs` (list of
written files with sizes), `stderr_tail`.

A file, not stdout parsing: engines write freely to stdout, and a missing
`result.json` is itself the signal for `CRASH`.

### Why subprocesses

Not for parallelism. For isolation:

- A CUDA OOM leaves the caching allocator fragmented and the weight cache holding
  device memory; process exit is the only guaranteed full reclaim.
- ONNX Runtime CUDA failures and torch fatal errors abort the process. An in-process
  sweep would stop at the first one.
- The child exercises `release_inference_memory` on the way out, which is itself worth
  covering.

## Job discovery

| Source | Approx. count | Job kind |
|---|---|---|
| `ModelRepository.list_mdx_models()` | 22 | `single`, method `mdx` |
| `ModelRepository.list_vr_models()` | 8 | `single`, method `vr` |
| `ModelRepository.list_demucs_models()` (bag members already filtered) | ~5 | `single`, method `demucs` |
| `core.apollo.list_apollo_models()` | 4 | `tool`, Apollo Restore |
| composites | 5 | see below |

Nothing is hardcoded; the sweep reflects whatever is on disk.

### Composite jobs

Each pins to models found on disk and reports `SKIP(unavailable)` when its models are
missing, so the sweep stays honest on a machine with a different model set.

1. **4-stem** — Demucs `hdemucs_mmi` with all stems; falls back to
   `huge_scnet_4stems_fullness.ckpt` with `mdx_stems=All Stems`.
2. **Ensemble** — the two smallest MDX weights, `Max Spec/Min Spec`,
   `is_save_all_outputs_ensemble=False`. Additionally asserts `ENSEMBLE_TEMP_PATH` is
   empty afterwards, since member collection is filename-coupled
   (`Ensembler.get_files_to_ensemble` vs `core/export_naming.py`).
3. **Secondary chain** — smallest VR model as primary, smallest MDX model as secondary
   at rate 0.5.
4. **Vocal splitter** — an MDX instrumental model with a karaoke model as splitter.
5. **Apollo restore** — via `AudioToolRunner.start(APOLLO_RESTORE, ...)` with
   `apollo_params` built from `core.apollo.ApolloModelData`, mirroring
   `ui/audio_tools/window.py::_resolve_apollo_model` minus the toasts and the
   unrecognized-model dialog (headless passes `on_unrecognized=None`).

## Input clip

One 3-second, 44.1 kHz, stereo WAV, generated once per sweep with a fixed seed: a few
sine partials plus low-level noise, peak-normalized to −3 dBFS, 16-bit PCM via
`soundfile`. Not silence — silence can produce all-zero stems and trip level-matching
and clipping paths in ways that say nothing about the model.

Three seconds is enough: every engine pads short input up to one full chunk, so cost
per model is one chunk regardless, and weight loading dominates anyway.

## Verdicts

Pass requires exit 0 **and** at least one non-empty audio file in the job's export
dir.

| Verdict | Meaning | Fails the sweep |
|---|---|---|
| `PASS` | Clean run, output written | no |
| `FAIL(<Type>)` | Exception from the run | yes |
| `NO_OUTPUT` | Exit 0, nothing written — the naming/collection regression signal | yes |
| `TIMEOUT` | Exceeded the per-job cap | yes |
| `CRASH(exit N)` | No `result.json`; segfault or abort | yes |
| `OOM(cpu-ok)` | Out of VRAM, but identical run passes on CPU | no |
| `UNRECOGNIZED` | `ModelConfig.model_status` false — metadata gap, not a code bug | only with `--strict` |
| `SKIP(...)` | Composite whose models are absent | no |

Exit 0 iff nothing in the "fails" column occurred.

### OOM handling

Three layers:

1. **Let the engines back off first.** `next_batch_after_oom` halves the MDX batch on
   CUDA OOM (`engines/mdx_classic_batch.py`) and `ensure_weight_cache_vram_headroom`
   reclaims cached device weights below 2 GiB / 15% free
   (`engines/model_weight_cache.py`). A job that recovers this way is a genuine `PASS`;
   that recovery is behavior worth covering.
2. **Classify with existing matchers.** Use `engines.mdx_classic_batch.is_oom_message`
   rather than a new regex, so ORT's `Fail` / `RuntimeException` OOM strings are caught
   alongside `torch.cuda.OutOfMemoryError`.
3. **Retry once on CPU, same settings.** Passes → `OOM(cpu-ok)`, reported but not a
   code defect. Fails → the real `FAIL(<Type>)`. Only OOM-ing jobs pay the cost.
   `--no-cpu-retry` disables.

Layer 3 matters because the base settings are the user's own: `mdx_segment_size=2208`
with `mdx_batch_size=2` is the most likely source of a legitimate OOM on a 16 GB card
with a desktop session resident. Without the CPU retry, "your segment size is too big"
and "this model is broken" look identical in the table.

## CLI

```
python scripts/model_sweep.py [--method mdx|vr|demucs|apollo|composite]
                              [--only SUBSTR] [--skip NAME[,NAME]]
                              [--cpu] [--no-cpu-retry] [--stock-settings]
                              [--timeout 300] [--json report.json]
                              [--list] [--fail-fast] [--strict]
                              [--keep-outputs]
```

Output is a live table (`model`, `verdict`, `elapsed`, first traceback line on
failure) and a summary count. Export dirs are deleted per job unless `--keep-outputs`.

## Testing the tester

`tests/test_model_sweep.py`:

- **Always on, CI-safe:** unit tests over the pure helpers with fakes — directory
  listings → job list, child `result.json` + exit code → verdict, OOM message →
  `OOM` classification, table formatting, exit-code aggregation. No torch, no models,
  milliseconds.
- **Opt-in:** the full sweep behind `@unittest.skipUnless(os.getenv("UVR_MODEL_SWEEP"))`,
  so `UVR_MODEL_SWEEP=1 python -m unittest tests.test_model_sweep` works while
  `unittest discover` stays unaffected.

Keeping discovery, classification and reporting as pure functions that take data and
return data is what makes this possible; the subprocess call is the only impure part.

## Expected runtime

Roughly 10–25 minutes for ~44 jobs on an RTX 4080, dominated by reading ~15 GB of
weights from disk. `--method` and `--only` cut it down during development.
