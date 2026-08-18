# Remaining refactors

> Backlog after the ModelConfig / JobRunner / stem-identity / Save Stems series
> (#30–#42) and the uncommitted `refactor/stem-focus-sentinels` work (positional
> `stem_focus` sentinels, exclusive Settings keys deleted, CLI identity
> round-trip). Each item is its own PR. Do not stack unrelated seams.

**Land first:** the current branch (`refactor/stem-focus-sentinels`) — PR A/B
sentinels + exclusive-key deletion, plus the CLI identity prefix / assemble
member-tag path fixes. Later items assume that is on `origin/main`.

## Quality bar (unchanged)

Same as #30–#42:

- Canonical module owns the symbols; **no** facade re-export from the old home.
- **No** second writer, **no** flag-translator shim.
- **No** live model in [`apply_stem_selection`](../../../core/stem_selection.py).
- **No** multi-focus `stem_focus` string.
- Do not invent a first/second-inventory meaning for `--stems primary` on
  4-stem ensembles ([`planned_output_routes`](../../../core/job_plan.py) already
  ignores that sentinel; `--stems vocals` already filters finals).

Tests: listed modules for the seam, then `python -m unittest discover -s tests -v`
and `.venv/bin/python -m basedpyright` on touched files.

---

## Done (do not reopen)

| Seam | Home | PR |
| --- | --- | --- |
| ModelConfig out of `model_data` | [`core/model_config/`](../../../core/model_config/) | earlier |
| Ensembler | [`core/ensembler.py`](../../../core/ensembler.py) | #30 |
| Separator OOM loop | [`core/separator_run.py`](../../../core/separator_run.py) | extract-separator-run |
| Shared file/chunk loop | [`core/run_loop.py`](../../../core/run_loop.py) | #32 |
| Stem alias/tag ownership | [`core/stems.py`](../../../core/stems.py) | #33 |
| `write_audio` extract | [`engines/stem_writer.py`](../../../engines/stem_writer.py) | #34 |
| `SeperateMDXC` extract | [`engines/mdx_c.py`](../../../engines/mdx_c.py) | #35 |
| Save Stems state | [`core/stem_selection.py`](../../../core/stem_selection.py) | #36 |
| Exclusive persist onto `StemRoute` | [`ui/widgets/stem_only.py`](../../../ui/widgets/stem_only.py) | #37 |
| Engines write `selected_stem_routes` | engines + assemble | #38 |
| CLI / subset through `StemRoute` | CLI + Save Stems | #39–#41 |
| Empty-focus exclusive flags at assemble | [`_apply_stem_focus`](../../../core/model_config/config.py) | #42 |
| Positional sentinels; delete exclusive Settings keys | `stem_focus` `primary`/`secondary` | current branch (uncommitted) |
| CLI `MDX-Net:` identity / assemble filename | [`_qualified_family`](../../../core/model_identity.py), [`assemble.py`](../../../core/model_config/assemble.py) | current branch (uncommitted) |

---

## Remaining

Suggested order. Skip an item rather than invent scope.

### 1. Delete dead exclusive attributes on `ModelConfig` / engines

Settings no longer have `process.primary_stem_only` / `secondary_stem_only` or
the Demucs twins. Assemble no longer copies those fields onto `ModelConfig`
(instance attrs stay `False`). Engines still declare and shuffle them.

**Touch:**

- [`core/model_config/config.py`](../../../core/model_config/config.py) —
  `is_primary_stem_only`, `is_secondary_stem_only`,
  `is_primary_model_primary_stem_only` / `_secondary_…`, and the
  `StemRouting` copies of the same flags.
- [`engines/base.py`](../../../engines/base.py) — copy from `model_data`,
  vocal-split / ensemble swaps at ~212 and ~319.
- [`engines/mdx_c.py`](../../../engines/mdx_c.py) — still assigns the pair.
- Secondary-model slots already use `_exclusive_sides_from_routes`; keep that.

**Do not** put the flags back on Settings. Export must keep using
`selected_stem_routes`. Prove with a grep that no engine branch still *reads*
the bools for write policy before deleting.

### 2. CLI uses planned settings and reports the error

Two execution bugs the identity fix papered over; they are still the wrong
shape.

**2a. `cli/job.py` returns the pre-`JobResolver` `settings`.**
[`JobResolver.resolve`](../../../core/job_plan.py) deep-copies, writes
`record.id` onto the copy, and applies model-native values.
[`resolve_separate_job`](../../../cli/job.py) then builds `ResolvedJob` from
the original object (still `canonical_member_tag`).
[`run_batch`](../../../cli/execution.py) does `JobRunner(job.settings)` +
`resolve_models()`, so execution re-assembles from member tags. Assemble now
converts those tags; it should not have to. Return `effective.settings` (or
assemble from `job.resolved` and stop calling `resolve_models` on the stale
copy).

**2b. Human `--report` hides the exception.**
[`_emit_human_result`](../../../cli/reporting.py) prints `status=` /
`elapsed_s=` / `export_path=` and only lists per-input errors when there is
more than one input. Single-file failure is `Process failed` with no
`ONNXRuntimeError`. Print `inputs[0].error` (or the payload error) in human
mode.

**2c. Stale `--stems` help.**
[`STEMS_HELP`](../../../cli/separate.py) still says positional names “clear
`process.stem_focus`”. After PR A they write sentinels. Fix that sentence
when touching the CLI file.

### 3. `JobCallbacks` out of `job_runner`

Deferred from every JobRunner extract. [`JobCallbacks`](../../../core/job_runner.py)
(~128–238) is the public callback surface; UI (`ui/dispatch.py`) and CLI
(`cli/execution.py`) both depend on it. [`core/__init__.py`](../../../core/__init__.py)
re-exports it next to `JobRunner`.

Move to something like `core/job_callbacks.py`. `JobRunner` imports it.
Retarget `core.__init__`, CLI, GTK dispatch, and tests that patch
`core.job_runner.JobCallbacks`. Do **not** keep a forwarding alias on
`job_runner`.

Leave `JobRunner` itself: thread lifecycle (`start` / `start_ensemble` /
`start_resolved`), naming, source cache, `resolve_models`. That file is still
~1100 lines; callbacks are the named leftover seam, not “split the rest
arbitrarily.”

### 4. Remaining `job_runner` extracts (only if 3 is not enough)

Only after `JobCallbacks` has a home. Candidates, each its own PR:

- **Run hooks** — `_SingleRunHooks` / `_EnsembleRunHooks` (~240–480) already
  implement `run_loop.FilePassHooks`. They can live next to
  [`run_models_on_files`](../../../core/run_loop.py) if `job_runner` is still
  the god object after callbacks move.
- **`_write_captured_stems`** — already in `run_loop`; `job_runner` still
  imports it for hooks. Do not re-export from `job_runner`.
- **`process_determine_*`** — still in
  [`core/model_data.py`](../../../core/model_data.py); `ModelConfig` lazy-imports
  them. Fold into `model_config` if you touch that cycle again.
- **Deprecated `_ModelConfigImplementation` alias** in `model_data.py` — delete
  when nothing imports it (tests should already use `ModelConfig`).

Do **not** merge `_run` and `_run_ensemble` into one flagged function. Do
**not** move `engines.orchestration._run_seperator`.

### 5. Model identity: stop persisting member tags as Settings values

CLI [`_canonicalize_model_references`](../../../cli/job.py) writes
`canonical_member_tag(record)` (`MDX-Net: Display`) into `settings.mdx.model`.
Planning and assemble now both have to recognize legacy arch prefixes.

Write **canonical ids** (`mdx:UVR-MDX-NET-Inst_HQ_4`) or engine basenames into
Settings after resolve. Keep `canonical_member_tag` for ensemble member lists
and display. Ensemble `selected_models` may stay as `Arch: Display` because
`ModelConfig` still partitions on `ENSEMBLE_PARTITION` — do not change that
in the same PR as separate/primary Settings.

Related: [`cli/job.py`](../../../cli/job.py) `ResolvedJob.settings` vs
`effective.settings` (item 2a) is the consumer; this item is the producer.

### 6. Optional later (do not start from this backlog)

These were repeatedly marked out of scope on purpose. Open a new spec before
touching them.

- **Live model in `apply_stem_selection`.** Persist stays token → Settings.
  Assemble already maps sentinels onto routes. Resolving `primary` against a
  `ModelRepository` in the CLI persist path recreates the “need a model to
  store a choice” cycle.
- **Multi-focus `select_stem_routes`.** One `stem_focus` string. Subset is
  `mdx.stems_selected` natives, not a comma list in `stem_focus`.
- **Engine inversion** (return arrays only; `write_audio` as a post-pass).
  `stem_writer` is already extracted; inverting all four engines is a rewrite.
- **Split `SeperateMDXC.seperate` / `demix_roformer`** into a third file.
- **Move `export_stem_label` / `resolve_stem_dict_key`** out of
  `model_stem_semantics.py`. Semantics may import `stems`; `stems` must not
  import semantics (already tested).
- **`ModelRepository` relocation** out of `model_data.py`.
- **4-stem ensemble positional `--stems primary`.** Skip. Use concept names
  (`--stems vocals`) for 4-stem finals.

---

## Suggested next PR

**Item 1** (dead exclusive attrs) if you want to finish the stem-focus
migration, or **item 2** if you want the CLI to tell the truth after a failed
run. Item 2 is smaller and user-visible. Item 3 is the leftover JobRunner
split that every prior plan deferred.
