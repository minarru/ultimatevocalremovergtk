# Remaining refactors

> Backlog after the ModelConfig / JobRunner / stem-identity / Save Stems series
> (#30–#49). Each item is its own PR. Do not stack unrelated seams.

## Quality bar (unchanged)

Same as #30–#49:

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
| Positional sentinels; delete exclusive Settings keys | `stem_focus` `primary`/`secondary` | #44 |
| CLI planned settings / human errors / `STEMS_HELP` | [`cli/job.py`](../../../cli/job.py) | #45 |
| `JobCallbacks` out of `job_runner` | [`core/job_callbacks.py`](../../../core/job_callbacks.py) | #46 |
| Run hooks | [`core/run_hooks.py`](../../../core/run_hooks.py) | #47 |
| Delete `_ModelConfigImplementation` alias | [`core/model_data.py`](../../../core/model_data.py) | #48 |
| CLI persist canonical ids in Settings | [`cli/job.py`](../../../cli/job.py) | #49 |
| CLI `MDX-Net:` identity / assemble filename | [`_qualified_family`](../../../core/model_identity.py), [`assemble.py`](../../../core/model_config/assemble.py) | with sentinels / #49 |

---

## Remaining

Suggested order. Skip an item rather than invent scope.

### 1. `ModelConfig` ensemble mode accepts canonical ids (this PR)

[`assemble_model`](../../../core/model_config/assemble.py) still translated
ids with `engine_value(..., member=True)` because
[`ModelConfig`](../../../core/model_config/config.py) partitioned on
`ENSEMBLE_PARTITION` (`": "`). Teach the constructor to consume `mdx:basename`
(and still accept `Arch: Display` for dry-check/checklist). Keep emitting
`model_and_process_tag` as `Arch: Display`. Do **not** change
`list_*_model_tags` / checklist row keys in this PR.

### 2. Fold `process_determine_*` into `model_config`

Still in [`core/model_data.py`](../../../core/model_data.py);
`ModelConfig` lazy-imports them. Fold into `model_config` if you touch that
cycle again. Do **not** merge `_run` and `_run_ensemble`. Do **not** move
`engines.orchestration._run_seperator`.

### 3. GTK checklist row keys

[`list_vr_model_tags`](../../../core/model_data.py) (and MDX/Demucs) still emit
`Arch: Display`. [`format_tag_title`](../../../core/model_display.py),
[`option_summaries`](../../../ui/option_summaries.py), eligibility matching,
and UI tests parse `ENSEMBLE_PARTITION`. Switching row identity to
`mdx:basename` is a **large** display rewrite. Display names colliding across
families is why the prefix exists on the widget, not why Settings persist it.

### 4. Optional later (do not start from this backlog)

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

After this constructor seam lands: **item 2** (`process_determine_*`) if you
are already in the `model_data` / `model_config` cycle, or **item 3**
(checklist row keys) as its own large display rewrite. Do not start item 4
without a new spec.
