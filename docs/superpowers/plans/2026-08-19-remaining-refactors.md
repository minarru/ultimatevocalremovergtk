# Remaining refactors

> Backlog after the ModelConfig / JobRunner / stem-identity / Save Stems series
> (#30–#51). Each item is its own PR. Do not stack unrelated seams.

## Quality bar (unchanged)

Same as #30–#51:

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
| `ModelConfig` ensemble mode accepts canonical ids | [`config.py`](../../../core/model_config/config.py), [`assemble.py`](../../../core/model_config/assemble.py) | #50 |
| Fold `process_determine_*` into `model_config` | [`core/model_config/determine.py`](../../../core/model_config/determine.py) | #51 |
| GTK checklist row keys (`family:basename` lists) | [`list_*_model_tags`](../../../core/model_repository.py) | #52 |
| Relocate `ModelRepository` | [`core/model_repository.py`](../../../core/model_repository.py) | #53 |

---

## Remaining

Suggested order. Skip an item rather than invent scope.

### 1. Drop stem-label facades from semantics (this PR)

Delete `export_stem_label` / `resolve_stem_dict_key` shims in
[`model_stem_semantics.py`](../../../core/model_stem_semantics.py). Callers use
[`core.stems.export_stem_label`](../../../core/stems.py) and
[`resolve_in_sources`](../../../core/stems.py). No re-export from the old home.

### 2. Optional later (do not start from this backlog)

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
- **4-stem ensemble positional `--stems primary`.** Skip. Use concept names
  (`--stems vocals`) for 4-stem finals.
- **Putting canonical ids in export filenames.**
  [`_model_output_label`](../../../core/run_hooks.py) stays a display name;
  [`sanitize_filename_component`](../../../core/export_naming.py) would turn
  `mdx:basename` into `mdx_basename`.
- **Merging `_run` and `_run_ensemble`** / moving
  `engines.orchestration._run_seperator`.

---

## Suggested next PR

After this facade drop lands: only **item 2** (optional later). Do not
start it without a new spec.
