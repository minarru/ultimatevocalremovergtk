# CLI Pass-2 First-Cut Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make planned names, identities, and interrupt JSON match what the runner actually writes, without the persistence/concurrency work from the remediation brief.

**Architecture:** `OutputNamingContext` is the name the runner writes. CLI stages into a temp dir, rebases that context onto the stage, and promotes exact planned destinations. `JobRunner` accepts already-assembled models and planned inputs so a one-file `start()` still writes `2-song`. Identity helpers prefix only unqualified GUI values and constrain family. Planning must not fetch MDX-C YAML.

**Tech Stack:** Python 3.14, stdlib `unittest`, basedpyright `standard`. No new dependencies.

**Spec:** [docs/plans/2026-08-16-cli-package-split-pass-2-remediation.md](../../plans/2026-08-16-cli-package-split-pass-2-remediation.md) (first-cut only). Findings: [docs/reviews/2026-08-16-feat-cli-package-split-pass-2.md](../../reviews/2026-08-16-feat-cli-package-split-pass-2.md).

## Global Constraints

- **First-cut only.** Do not add storage locks, overwrite backups, in-process promotion locks, or catalogue publish-retry. Those stay in the remediation brief for a later plan.
- **`cli` → `core`, never the reverse.** Staging, promotion, manifests, and report JSON stay in `cli/`. Naming, topology, identity, and runner behavior stay in `core/`.
- **No tkinter.** `core` stays framework-agnostic.
- **Enum settings are `str, Enum`; never stringify them.** Filenames go through `enum_value` / `OutputNamingContext.extension`.
- **`--report json` owns stdout.** Failures and interrupts still emit one document. `fail(..., exit_code=130)` must set `"stopped": true`.
- **Planning is offline and non-mutating.** `JobResolver` / dry-run / validate must not download MDX-C YAML or write `<hash>.json`. Missing YAML is a diagnostic. Users fetch configs with `uvr models download` or an already-cached file.
- **GUI plan confirmation stays enabled by default.** Do not flip `confirm_processing_plan`.
- **Tests are stdlib unittest.** Run `.venv/bin/python -m unittest …`, not pytest.
- **Tests must not touch the live network.** Patch fetches; do not rely on `catalogue_offline()` (it is a no-op).
- **Search with `rg`.** Stage exact paths; never `git add -A`.
- **Do not change `JobRunner.start` / `start_ensemble` positional signatures.** New behavior is keyword-only (`models=`, `planned=`).
- Every task ends with its focused tests green and `.venv/bin/python -m basedpyright` on the files that task touched.

---

## Out of scope (do not implement)

- Per-path profile/ensemble file locks and content-digest conflict retries
- Overwrite backup / rollback of existing stems
- Cross-process promotion serialization
- Catalogue-cache “publish only if generation unchanged” protocol
- Deleting `core/offline.catalogue_offline` (docs must stop claiming it disables the network)
- Changing the default of `confirm_processing_plan`
- A new `JobRunner.start_resolved` batch API with fail-fast policy inside core

---

## File Structure

**Created:**

| File | Responsibility |
| --- | --- |
| `tests/test_job_plan_topology.py` | Ensemble planned stems vs `ensemble.main_stem` |
| `tests/test_export_naming_rebase.py` | `rebase_output_naming` keeps `track_base`, rewrites export dir |
| `tests/test_cli_promotion.py` | Exact preflight, common-suffix rename, no double suffix |

**Modified:**

| File | Change |
| --- | --- |
| `core/job_plan.py` | `planned_output_stems()`; `_plan_inputs` uses it |
| `core/export_naming.py` | `rebase_output_naming()` |
| `core/job_runner.py` | `models=` / `planned=` on `start` and `start_ensemble`; use planned `track_base` |
| `core/mdx_config_fetch.py` | `allow_network=` on `ensure_mdx_c_config` |
| `core/model_data.py` | Honor `allow_network` when constructing MDX-C configs during assemble |
| `core/identity_migration.py` | Family-scoped `canonical()`; do not clear ambiguous refs |
| `cli/profiles.py` | `_identity_from_gui` prefixes only unqualified values; keep lists when flattening |
| `cli/job.py` | Family constraints on `_canonicalize_model_references` |
| `cli/execution.py` | Delete `_apply_planned_basename`; exact preflight; unit rename |
| `cli/reporting.py` | `fail(exit_code=130)` sets `stopped: true` |
| `cli/bench.py` | Topology from `plan["models"]`; empty topology is a failure |
| `cli/discovery.py` | Download interrupt already emits `stopped`; rely on `fail()` for 130 |
| `ui/run_control.py` | Run-local `runner.settings`; do not `__dict__.update` live settings |
| `docs/environment.md` | Manifest schemas, offline planning, interrupt fields |
| `CLAUDE.md`, `cli/CLAUDE.md` | Stop claiming `catalogue_offline` sets `UVR_DISABLE_*` |

---

### Task 1: Ensemble planned stems match `ensemble.main_stem`

**Files:**
- Modify: `core/job_plan.py` (`_stems`, `_plan_inputs`)
- Test: `tests/test_job_plan_topology.py`

**Interfaces:**
- Consumes: `EnsemblePair` / `coerce_ensemble_pair` (`core/stems.py`); `DEMUCS_4_SOURCE_LIST` (`bundled.constants`); existing `ModelDescriptor`, `PlannedOutput`, `JobResolver._plan_inputs`
- Produces: `planned_output_stems(settings, descriptors, *, command: str) -> tuple[tuple[str, bool], ...]` where each item is `(stem_label, conditional)`. `_plan_inputs` builds `PlannedOutput(..., conditional=conditional)` from that list.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_job_plan_topology.py`:

```python
from __future__ import annotations

import unittest
from unittest.mock import Mock

from bundled.constants import BASS_STEM, DRUM_STEM, OTHER_STEM, VOCAL_STEM
from core.job_plan import JobResolver, JobSpec, ModelDescriptor, planned_output_stems
from core.settings import Settings
from core.stems import EnsemblePair


def _desc(stem: str, secondary: str = "Instrumental") -> ModelDescriptor:
    return ModelDescriptor("mdx:a", "mdx", "a", "A", primary_stem=stem, secondary_stem=secondary)


class PlannedOutputStemTests(unittest.TestCase):
    def test_separate_uses_descriptor_stems(self) -> None:
        settings = Settings.defaults()
        stems = planned_output_stems(settings, (_desc("Vocals"),), command="separate")
        self.assertEqual(stems, (("Vocals", False), ("Instrumental", False)))

    def test_ensemble_pair_ignores_first_member_stems(self) -> None:
        settings = Settings.defaults()
        settings.ensemble.main_stem = EnsemblePair.VOCALS_INSTRUMENTAL
        stems = planned_output_stems(
            settings, (_desc("Drums", "Bass"), _desc("Vocals")), command="ensemble",
        )
        labels = tuple(stem for stem, _conditional in stems)
        self.assertEqual(labels, (VOCAL_STEM, "Instrumental"))
        self.assertFalse(any(conditional for _stem, conditional in stems))

    def test_four_stem_ensemble_is_the_standard_four(self) -> None:
        settings = Settings.defaults()
        settings.ensemble.main_stem = EnsemblePair.FOUR_STEM
        stems = planned_output_stems(settings, (_desc("Vocals"),), command="ensemble")
        labels = tuple(stem for stem, _conditional in stems)
        self.assertEqual(labels, (BASS_STEM, DRUM_STEM, OTHER_STEM, VOCAL_STEM))

    def test_multi_stem_marks_union_conditional_when_members_differ(self) -> None:
        settings = Settings.defaults()
        settings.ensemble.main_stem = EnsemblePair.MULTI_STEM
        stems = planned_output_stems(
            settings,
            (_desc("Vocals", "Instrumental"), _desc("Drums", "Bass")),
            command="ensemble",
        )
        self.assertTrue(any(conditional for _stem, conditional in stems))
        labels = {stem for stem, _conditional in stems}
        self.assertTrue({"Vocals", "Instrumental", "Drums", "Bass"} <= labels)

    def test_resolver_plan_outputs_use_ensemble_pair(self) -> None:
        settings = Settings.defaults()
        settings.process.method = "ensemble"
        settings.ensemble.main_stem = EnsemblePair.VOCALS_INSTRUMENTAL
        settings.ensemble.selected_models = ["mdx:a", "mdx:b"]
        resolver = JobResolver(Mock())
        resolver._identity_records = Mock(return_value=[])  # type: ignore[method-assign]
        spec = JobSpec("ensemble", settings, ("/tmp/song.wav",), "/tmp/out")
        # Bypass assemble: feed descriptors through _plan_inputs.
        planned = resolver._plan_inputs(
            settings, spec, (_desc("Drums", "Bass"), _desc("Vocals")),
        )
        self.assertEqual(
            [output.stem for output in planned[0].outputs],
            [VOCAL_STEM, "Instrumental"],
        )


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m unittest tests.test_job_plan_topology -v`

Expected: `ImportError` for `planned_output_stems`, or the ensemble pair test fails because `_plan_inputs` still uses `descriptors[0]`.

- [ ] **Step 3: Implement `planned_output_stems` and switch `_plan_inputs`**

In `core/job_plan.py`:

```python
from bundled.constants import DEMUCS_4_SOURCE_LIST
from .stems import EnsemblePair, coerce_ensemble_pair


def planned_output_stems(
    settings: Settings,
    descriptors: Sequence[ModelDescriptor],
    *,
    command: str,
) -> tuple[tuple[str, bool], ...]:
    if command == "ensemble":
        pair = coerce_ensemble_pair(settings.ensemble.main_stem)
        if pair is EnsemblePair.FOUR_STEM:
            return tuple((stem, False) for stem in DEMUCS_4_SOURCE_LIST)
        if pair is EnsemblePair.MULTI_STEM:
            seen: dict[str, bool] = {}
            for descriptor in descriptors:
                for stem in (descriptor.primary_stem, descriptor.secondary_stem):
                    if stem:
                        seen.setdefault(stem, False)
            # More than one distinct member topology => conditional.
            topologies = {
                (item.primary_stem, item.secondary_stem) for item in descriptors
            }
            conditional = len(topologies) > 1
            return tuple((stem, conditional) for stem in seen)
        left, right = pair.stem_halves()
        result: list[tuple[str, bool]] = []
        if left:
            result.append((left, False))
        if right and not right.startswith("No "):
            result.append((right, False))
        return tuple(result)
    descriptor = descriptors[0] if descriptors else ModelDescriptor("", "", "", "")
    if settings.process.primary_stem_only:
        return ((descriptor.primary_stem or "Primary", False),)
    if settings.process.secondary_stem_only:
        return ((descriptor.secondary_stem or "Secondary", False),)
    return (
        (descriptor.primary_stem or "Primary", False),
        (descriptor.secondary_stem or "Secondary", False),
    )
```

Use `pair.stem_halves()` for dual-stem pairs (not `filename_tag` of UNKNOWN). Complement pairs (`other` / `drums` / `bass`) guarantee only the primary half.

Replace `_stems(...)` usage in `_plan_inputs` with:

```python
stem_entries = planned_output_stems(settings, descriptors, command=spec.command)
outputs = tuple(
    PlannedOutput(
        os.path.join(
            naming.export_directory,
            f"{format_stem_basename(naming.track_base, stem)}.{naming.extension}",
        ),
        stem,
        conditional,
    )
    for stem, conditional in stem_entries
)
```

Export `planned_output_stems` from `__all__`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m unittest tests.test_job_plan_topology -v`

Expected: PASS. If the vocals/instrumental label is `Instrumental` vs `Inst`, match whatever `EnsemblePair.VOCALS_INSTRUMENTAL.stem_halves()` returns (`VOCAL_STEM`, `INST_STEM`).

- [ ] **Step 5: Commit**

```bash
git add core/job_plan.py tests/test_job_plan_topology.py
git commit -m "$(cat <<'EOF'
fix(core): plan ensemble outputs from main_stem, not the first member

Dry-run and GUI preflight were advertising the first member's stems.
EOF
)"
```

---

### Task 2: Benchmark topology and interrupt JSON

**Files:**
- Modify: `cli/bench.py` (`_stem_topology`, `cmd_bench` failure paths)
- Modify: `cli/reporting.py` (`fail`)
- Test: `tests/test_cli.py` (add cases; keep existing 130 tests)

**Interfaces:**
- Consumes: `ResolvedJob.to_dict()` `models[].primary_stem` / `secondary_stem`; `fail()`
- Produces: `_stem_topology(plan) -> tuple[str, ...]` of guaranteed stems (sorted). Empty tuple is invalid. `fail(..., exit_code=130)` always includes `"stopped": true` unless `extra` already set it.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_cli.py`:

```python
    def test_fail_exit_130_sets_stopped(self) -> None:
        from cli.reporting import fail
        from types import SimpleNamespace
        import io
        from contextlib import redirect_stdout, redirect_stderr

        args = SimpleNamespace(report="json", quiet=False, verbose=False)
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = fail(args, "interrupted", exit_code=130)
        payload = json.loads(out.getvalue())
        self.assertEqual(code, 130)
        self.assertTrue(payload["stopped"])
        self.assertFalse(payload["ok"])

    def test_bench_topology_reads_plan_models_not_identity(self) -> None:
        from cli.bench import _stem_topology

        dead = {"identity": {"primary_stem": "Vocals"}}
        live = {"models": [{"primary_stem": "Vocals", "secondary_stem": "Instrumental"}]}
        self.assertNotEqual(_stem_topology(dead), _stem_topology(live))
        self.assertEqual(_stem_topology(live), ("Instrumental", "Vocals"))
        self.assertEqual(_stem_topology({}), ())
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m unittest tests.TestCli.test_fail_exit_130_sets_stopped tests.TestCli.test_bench_topology_reads_plan_models_not_identity -v`

Use the actual class names from `tests/test_cli.py` (`rg -n "class " tests/test_cli.py`). Expected: `fail` payload has no `stopped`; `_stem_topology` returns `(None, None)` from the dead identity path and equals the empty-models case.

- [ ] **Step 3: Implement**

`cli/reporting.py` `fail()`:

```python
        if extra:
            payload.update(extra)
        if exit_code == 130:
            payload.setdefault("stopped", True)
        emit_document(args, payload)
```

`cli/bench.py`:

```python
def _stem_topology(plan: dict[str, Any]) -> tuple[str, ...]:
    models = plan.get("models") or []
    stems: set[str] = set()
    for model in models:
        for key in ("primary_stem", "secondary_stem"):
            value = model.get(key)
            if value:
                stems.add(str(value))
    return tuple(sorted(stems))
```

After both dry-runs succeed:

```python
    topo_a = _stem_topology(check_a.get("plan") or {})
    topo_b = _stem_topology(check_b.get("plan") or {})
    if not topo_a or not topo_b or topo_a != topo_b:
        return fail(args, "benchmark legs have incompatible stem topology", exit_code=2)
```

Do not add a second `"stopped"` in `cmd_bench` 130 `fail()` calls; `fail()` now owns it. Leave `extra={"a": ..., "b": ...}` as-is.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m unittest tests.test_cli -v`

Expected: new tests PASS; existing 130 tests still PASS (`setdefault` does not overwrite an explicit `stopped`).

- [ ] **Step 5: Commit**

```bash
git add cli/bench.py cli/reporting.py tests/test_cli.py
git commit -m "$(cat <<'EOF'
fix(cli): compare bench stems from the resolved plan

The identity payload is gone, so the old check treated every pair as compatible.
EOF
)"
```

---

### Task 3: Runner writes planned names and reuses assembled models

**Files:**
- Modify: `core/export_naming.py`
- Modify: `core/job_runner.py` (`start`, `start_ensemble`, `_reset_run_state`, `_run`, `_run_ensemble`)
- Test: `tests/test_export_naming_rebase.py`
- Test: `tests/test_run_control.py` or new `tests/test_job_runner_planned.py`

**Interfaces:**
- Consumes: `OutputNamingContext`, `PlannedInput` (`core/job_plan.py`), existing `resolve_models()`
- Produces:

```python
def rebase_output_naming(
    naming: OutputNamingContext,
    export_path: str,
    planned_output_root: str,
) -> OutputNamingContext:
    """Keep track_base / labels; rewrite export_directory under export_path."""

# JobRunner.start / start_ensemble gain keyword-only:
#   models: Sequence[ModelConfig] | None = None
#   planned: Sequence[PlannedInput] | None = None
# When models is not None, do not call resolve_models() / assemble_model().
# When planned is not None, audio_file_base comes from the matching PlannedInput.naming.track_base
# (after rebase onto settings.process.export_path using plan.output as planned_output_root).
```

Store `self._run_models` and `self._run_planned` on the runner; clear both in `_reset_run_state`.

- [ ] **Step 1: Write the failing rebase test**

```python
# tests/test_export_naming_rebase.py
from __future__ import annotations

import os
import unittest

from core.export_naming import OutputNamingContext, rebase_output_naming


class RebaseOutputNamingTests(unittest.TestCase):
    def test_preserves_track_base_and_rewrites_directory(self) -> None:
        naming = OutputNamingContext(
            input_path="/in/song.wav",
            track="song",
            track_base="2-song Model",
            export_directory="/out/Model/song",
            extension="wav",
            file_index=2,
            file_total=3,
            model_label="Model",
        )
        rebased = rebase_output_naming(naming, "/stage/1", "/out")
        self.assertEqual(rebased.track_base, "2-song Model")
        self.assertEqual(rebased.export_directory, os.path.join("/stage/1", "Model", "song"))

    def test_root_export_stays_at_stage_root(self) -> None:
        naming = OutputNamingContext(
            input_path="/in/song.wav", track="song", track_base="song",
            export_directory="/out", extension="wav",
        )
        rebased = rebase_output_naming(naming, "/stage/1", "/out")
        self.assertEqual(rebased.export_directory, "/stage/1")


if __name__ == "__main__":
    unittest.main()
```

Add `tests/test_job_runner_planned.py`:

```python
from __future__ import annotations

import unittest
from unittest.mock import Mock, patch

from core.export_naming import OutputNamingContext
from core.job_plan import PlannedInput, PlannedOutput
from core.job_runner import JobRunner
from core.settings import Settings


class JobRunnerPlannedTests(unittest.TestCase):
    def test_start_skips_assemble_when_models_supplied(self) -> None:
        runner = JobRunner(Settings.defaults())
        models = [Mock(name="already-assembled")]
        with patch.object(runner, "resolve_models") as resolve:
            with patch("core.job_runner.KThread") as thread:
                runner.start(["/in/a.wav"], Mock(), models=models)
        resolve.assert_not_called()
        self.assertIs(runner._run_models, models)
        thread.assert_called_once()

    def test_reset_clears_run_models_and_planned(self) -> None:
        runner = JobRunner(Settings.defaults())
        runner._run_models = [Mock()]
        runner._run_planned = ()
        runner._reset_run_state()
        self.assertIsNone(runner._run_models)
        self.assertIsNone(runner._run_planned)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m unittest tests.test_export_naming_rebase tests.test_job_runner_planned -v`

Expected: `rebase_output_naming` missing; `start()` TypeError on `models=`.

- [ ] **Step 3: Implement rebase and runner kwargs**

`core/export_naming.py`:

```python
def rebase_output_naming(
    naming: OutputNamingContext,
    export_path: str,
    planned_output_root: str,
) -> OutputNamingContext:
    import dataclasses

    root = os.path.abspath(planned_output_root)
    current = os.path.abspath(naming.export_directory)
    rel = os.path.relpath(current, root)
    if rel.startswith(".."):
        raise ValueError(
            f"planned export {naming.export_directory!r} is not under {planned_output_root!r}"
        )
    directory = os.path.abspath(export_path) if rel == "." else os.path.join(export_path, rel)
    return dataclasses.replace(naming, export_directory=directory)
```

`core/job_runner.py`:

- Add `self._run_models = None` and `self._run_planned = None` in `__init__` (or only in `_reset_run_state` if attributes are created there — create them in `__init__` so they always exist).
- `_reset_run_state` sets both to `None`.
- `start` / `start_ensemble`:

```python
    def start(
        self,
        input_paths: Sequence[str],
        callbacks: JobCallbacks,
        *,
        models: Sequence[Any] | None = None,
        planned: Sequence[Any] | None = None,
    ) -> None:
        if self.is_running():
            return
        if self.settings.process.method == ProcessMethod.ENSEMBLE:
            self.start_ensemble(input_paths, callbacks, models=models, planned=planned)
            return
        # existing KThread path
        self._reset_run_state()
        self._run_models = list(models) if models is not None else None
        self._run_planned = tuple(planned) if planned is not None else None
        ...
```

Same keyword args on `start_ensemble`.

In `_run` (and the equivalent place in `_run_ensemble` that sets `audio_file_base`):

```python
            models = self._run_models if self._run_models is not None else self.resolve_models()
```

When building naming for each file:

```python
                    planned_item = None
                    if self._run_planned:
                        planned_item = next(
                            (item for item in self._run_planned if item.path == audio_file),
                            None,
                        )
                    if planned_item is not None:
                        naming = rebase_output_naming(
                            planned_item.naming,
                            export_path,
                            planned_item.naming.export_directory
                            if planned_item.naming.export_directory == export_path
                            else os.path.commonpath(
                                [planned_item.naming.export_directory, export_path]
                            )
                            if False else
                            # CLI always rebases against the job's final output.
                            # Pass it on PlannedInput via naming + JobRunner.settings.process.export_path.
                            self.settings.process.export_path  # replaced below
                        )
```

Do **not** ship that `if False` sketch. Use this rule:

1. Look up `PlannedInput` by `path == audio_file`.
2. `naming = rebase_output_naming(item.naming, settings.process.export_path, item.naming.export_directory if item.naming.export_directory.startswith(settings.process.export_path) else os.path.dirname(item.outputs[0].path) and …)`

Cleaner: add `output_root: str` on the runner for the rebase source, defaulting to `os.path.commonpath([item.naming.export_directory for item in planned])` when `planned` is set, else `settings.process.export_path`.

Simplest implementable rule:

```python
def _naming_for_file(self, audio_file: str, *, export_path: str, **build_kwargs) -> OutputNamingContext:
    if self._run_planned:
        item = next(item for item in self._run_planned if os.path.abspath(item.path) == os.path.abspath(audio_file))
        root = os.path.commonpath(
            [os.path.abspath(entry.naming.export_directory) for entry in self._run_planned]
            + [os.path.abspath(out.path) for entry in self._run_planned for out in entry.outputs]
        )
        # If create_model_folder nested dirs, commonpath may be the job output root.
        return rebase_output_naming(item.naming, export_path, root)
    return build_output_naming_context(self.settings, audio_file, export_path=export_path, **build_kwargs)
```

If `commonpath` is too wide (only one file, export is `/out/Model/song`), pass the job output explicitly:

Add keyword `planned_output_root: str | None = None` to `start` / `start_ensemble`, stored as `self._run_output_root`. CLI passes `job.output`. GUI passes `plan.output`.

```python
    return rebase_output_naming(item.naming, export_path, self._run_output_root or item.naming.export_directory)
```

Use `planned_output_root`. Update the Task 3 tests to assert `start(..., planned_output_root="/out")` stores it.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m unittest tests.test_export_naming_rebase tests.test_job_runner_planned tests.test_export_naming -v`

Expected: PASS. Existing export-naming tests unchanged.

- [ ] **Step 5: Commit**

```bash
git add core/export_naming.py core/job_runner.py tests/test_export_naming_rebase.py tests/test_job_runner_planned.py
git commit -m "$(cat <<'EOF'
feat(core): JobRunner honors planned names and reused models

A one-file start can still write 2-song, and a batch no longer reassembles per input.
EOF
)"
```

---

### Task 4: CLI promotion uses the plan; delete `_apply_planned_basename`

**Files:**
- Modify: `cli/execution.py` (`preflight_collisions`, `_promote`, `run_batch`, `_run_job_cli`)
- Modify: `cli/audio.py` only if it still calls `_promote` without a unit suffix (keep audio’s per-file rename; do not force a shared basename on align/match)
- Test: `tests/test_cli_promotion.py`
- Modify: `tests/test_cli_redesign.py` (`test_same_basename_inputs_receive_deterministic_names` must use real `ResolvedJob` / `PlannedInput` naming, not `{"basename": "song_2"}`)

**Interfaces:**
- Consumes: `job.resolved.inputs: tuple[PlannedInput, ...]` (not `job.plan["inputs"][i]["basename"]`); `rebase_output_naming`; `JobRunner.start(..., models=, planned=, planned_output_root=)`
- Produces: `_promote(stage, output, policy, *, destinations: Sequence[str])` where `destinations` are the exact final paths for this input’s **guaranteed** outputs (and any extra files found in stage). `rename` picks one `_{n}` inserted before the stem suffix / extension so every destination in the unit shares it. Delete `_apply_planned_basename`.

- [ ] **Step 1: Write the failing tests**

`tests/test_cli_promotion.py`:

```python
from __future__ import annotations

import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from cli.execution import _promote, preflight_collisions, run_batch
from core.export_naming import OutputNamingContext, format_stem_basename
from core.job_plan import PlannedInput, PlannedOutput
from core.settings import Settings


def _planned(path: str, output: str, track_base: str, stems: tuple[str, ...] = ("Vocals", "Instrumental")):
    naming = OutputNamingContext(
        input_path=path, track="song", track_base=track_base,
        export_directory=output, extension="wav",
    )
    outputs = tuple(
        PlannedOutput(os.path.join(output, f"{format_stem_basename(track_base, stem)}.wav"), stem)
        for stem in stems
    )
    return PlannedInput(path, naming, outputs)


class PromotionTests(unittest.TestCase):
    def test_add_model_name_does_not_double_suffix(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            stage = os.path.join(root, "stage")
            output = os.path.join(root, "out")
            os.makedirs(stage)
            planned = "song Model"
            for stem in ("Vocals", "Instrumental"):
                name = f"{format_stem_basename(planned, stem)}.wav"
                open(os.path.join(stage, name), "wb").write(b"x")
            promoted = _promote(
                stage, output, "fail",
                destinations=[
                    os.path.join(output, f"{format_stem_basename(planned, stem)}.wav")
                    for stem in ("Vocals", "Instrumental")
                ],
            )
            self.assertTrue(os.path.isfile(os.path.join(output, "song Model (Vocals).wav")))
            self.assertFalse(os.path.isfile(os.path.join(output, "song Model Model (Vocals).wav")))
            self.assertEqual(len(promoted), 2)

    def test_rename_uses_one_suffix_for_the_unit(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            stage = os.path.join(root, "stage")
            output = os.path.join(root, "out")
            os.makedirs(stage)
            os.makedirs(output)
            open(os.path.join(output, "song (Vocals).wav"), "wb").write(b"old")
            for stem in ("Vocals", "Instrumental"):
                open(os.path.join(stage, f"song ({stem}).wav"), "wb").write(b"new")
            promoted = _promote(
                stage, output, "rename",
                destinations=[
                    os.path.join(output, f"song ({stem}).wav")
                    for stem in ("Vocals", "Instrumental")
                ],
            )
            names = sorted(os.path.basename(path) for path in promoted)
            self.assertEqual(names, ["song_2 (Instrumental).wav", "song_2 (Vocals).wav"])

    def test_preflight_ignores_unrelated_prefix(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            output = os.path.join(root, "out")
            os.makedirs(output)
            open(os.path.join(output, "song_live (Vocals).wav"), "wb").write(b"x")
            job = SimpleNamespace(
                inputs=[os.path.join(root, "song.wav")],
                output=output,
                resolved=SimpleNamespace(inputs=(
                    _planned(os.path.join(root, "song.wav"), output, "song"),
                )),
            )
            collided = preflight_collisions(job, "fail")
            self.assertEqual(collided, set())
```

Rewrite `test_same_basename_inputs_receive_deterministic_names` in `tests/test_cli_redesign.py` so `job.resolved.inputs` is two `PlannedInput`s with `track_base` `1-song` and `2-song` (what `JobResolver` actually emits). The fake runner must write `1-song (Vocals).wav` / `2-song (Vocals).wav` using `settings.process.export_path`. Assert those names in `output` after `run_batch`. If `run_batch` is not yet wired, this test fails until Step 3.

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m unittest tests.test_cli_promotion tests.TestCliRedesign.test_same_basename_inputs_receive_deterministic_names -v`

Expected: `_promote` has no `destinations=`; preflight still flags `song_live`; same-basename test still depends on `_apply_planned_basename`.

- [ ] **Step 3: Implement**

`preflight_collisions`:

```python
def preflight_collisions(job: ResolvedJob, policy: str) -> set[str]:
    planned_inputs = job.resolved.inputs if job.resolved is not None else ()
    collided: set[str] = set()
    for item in planned_inputs:
        guaranteed = [output.path for output in item.outputs if not output.conditional]
        if any(os.path.exists(path) for path in guaranteed):
            collided.add(item.path)
    if collided and policy == "fail":
        first = sorted(collided)[0]
        raise ValueError(
            f"output already exists for {first}; choose --on-exists overwrite, rename, or skip"
        )
    return collided
```

`_promote`: drop the `basename=` batch-rename that slices `os.path.basename(target)[len(basename):]`. New rule:

1. Build `entries` as today (walk stage).
2. If `destinations` is provided, the unit’s collision set is those paths (guaranteed). Extra staged files still promote with the same numeric suffix if `rename`.
3. `rename`: find the smallest `n >= 2` such that **no** rewritten destination exists. Rewrite `{track_base} ({stem}).{ext}` → `{track_base}_{n} ({stem}).{ext}` for every file whose name starts with `track_base + " ("` or `track_base + "."`. Do not use `startswith(track_base)` alone (that is the `song` / `song Model` bug).
4. `fail` / `skip`: if any guaranteed destination exists, raise `FileExistsError` / `PromotionSkipped` before any `os.replace`.
5. `overwrite`: `os.replace` as today. No backup in this plan.

Delete `_apply_planned_basename` and its call in `run_batch`.

`run_batch` per input:

```python
            planned_item = job.resolved.inputs[index - 1]
            staged = dataclasses.replace(
                planned_item,
                naming=rebase_output_naming(
                    planned_item.naming, stage, job.output,
                ),
            )
            result = runner(
                settings, [input_path],
                print_console=not args.quiet,
                on_progress=progress,
                runner=shared_runner,
                models=shared_models,
                planned=(staged,),
                planned_output_root=job.output,
            )
            outputs = _promote(
                stage, job.output, args.on_exists,
                destinations=[
                    output.path for output in planned_item.outputs if not output.conditional
                ],
            )
```

Assemble once before the loop:

```python
    shared_runner = JobRunner(job.settings)
    shared_models = shared_runner.resolve_models()
```

Thread `models` / `planned` / `planned_output_root` through `_run_job_cli` → `run_runner_cli` is the wrong layer (signals only). Put the new kwargs on `_run_job_cli` / `run_separation_cli` / `run_ensemble_cli`:

```python
def run_separation_cli(..., models=None, planned=None, planned_output_root=None, runner=None):
    ...
    return run_runner_cli(
        job_runner,
        lambda callbacks: job_runner.start(
            list(input_paths), callbacks,
            models=models, planned=planned, planned_output_root=planned_output_root,
        ),
        ...
    )
```

`run_batch`’s `runner` callable must accept those kwargs (update the `Callable[..., RunResult]` usages and the fake runners in `tests/test_cli_redesign.py`).

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m unittest tests.test_cli_promotion tests.test_cli_redesign tests.test_cli -v`

Expected: PASS. No remaining references to `_apply_planned_basename` (`rg _apply_planned_basename`).

- [ ] **Step 5: Commit**

```bash
git add cli/execution.py tests/test_cli_promotion.py tests/test_cli_redesign.py
git commit -m "$(cat <<'EOF'
fix(cli): promote planned destinations and stop rewriting engine names

The runner already writes OutputNamingContext; prefix substitution doubled model labels.
EOF
)"
```

---

### Task 5: Canonical GUI identities and family-scoped resolve

**Files:**
- Modify: `cli/profiles.py` (`_identity_from_gui`, `_flatten_settings`)
- Modify: `cli/job.py` (`_canonicalize_model_references`)
- Modify: `core/identity_migration.py` (`canonical`, `replace`)
- Test: `tests/test_cli_redesign.py` (profile tests)
- Test: `tests/test_core_consolidation.py` (migration tests)

**Interfaces:**
- Consumes: `FAMILIES`, `ModelIdentityService.resolve(..., family=, allowed_families=)`
- Produces: `_qualify_stored_model(family: str, value: str) -> str | None` in `cli/profiles.py`. `_flatten_settings` keeps `list` values (still skips `dict`, identity paths, `ui`, `audio_tools` except apollo is identity). Migration `canonical(..., family=)` / `allowed_families=`; on `ValueError` that is ambiguous or family-mismatched, leave the field unchanged and append a failure/conflict string — do **not** write `NO_MODEL` / `CHOOSE_MODEL`. Genuinely unknown (`unknown or unregistered`) still clears to the existing sentinel.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_cli_redesign.py`:

```python
    def test_gui_profile_does_not_double_prefix_canonical_ids(self) -> None:
        settings = Settings.defaults()
        settings.process.method = settings.process.method  # keep
        from core.types import ProcessMethod
        settings.process.method = ProcessMethod.MDX
        settings.mdx.model = "mdx:UVR-MDX-NET-Inst_HQ_4"
        with patch("cli.profiles.Settings.load", return_value=settings):
            _loaded, profile = load_profile("gui")
        self.assertEqual(profile.model, "mdx:UVR-MDX-NET-Inst_HQ_4")

    def test_gui_profile_prefixes_legacy_display_names(self) -> None:
        settings = Settings.defaults()
        from core.types import ProcessMethod
        settings.process.method = ProcessMethod.MDX
        settings.mdx.model = "UVR-MDX-NET-Inst_HQ_4"
        with patch("cli.profiles.Settings.load", return_value=settings):
            _loaded, profile = load_profile("gui")
        self.assertEqual(profile.model, "mdx:UVR-MDX-NET-Inst_HQ_4")

    def test_flatten_keeps_list_settings(self) -> None:
        from cli.profiles import _flatten_settings
        settings = Settings.defaults()
        settings.mdx.stems_selected = ["Vocals", "Drums"]
        flat = _flatten_settings(settings)
        self.assertEqual(flat["mdx.stems_selected"], ["Vocals", "Drums"])
```

Add to `tests/test_core_consolidation.py`:

```python
    def test_ambiguous_secondary_is_left_unchanged(self) -> None:
        from core.identity_migration import IdentityMigrator
        from bundled.constants import NO_MODEL

        settings = Settings.defaults()
        settings.mdx.voc_inst_secondary_model = "Kim"
        migrator = IdentityMigrator(Mock())
        with patch(
            "core.identity_migration.resolve_model_record",
            side_effect=ValueError("ambiguous model 'Kim'; matches: mdx:a, vr:a"),
        ):
            migrator.migrate_settings(settings)
        self.assertEqual(settings.mdx.voc_inst_secondary_model, "Kim")
        self.assertNotEqual(settings.mdx.voc_inst_secondary_model, NO_MODEL)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m unittest tests.test_cli_redesign tests.test_core_consolidation -v`

Expected: `profile.model == "mdx:mdx:UVR-MDX-NET-Inst_HQ_4"`; lists missing from flatten; ambiguous secondary cleared to `NO_MODEL`.

- [ ] **Step 3: Implement**

`cli/profiles.py`:

```python
from core.model_identity import FAMILIES


def _qualify_stored_model(family: str, model: str) -> str | None:
    raw = str(model or "").strip()
    if not raw or raw.casefold() in {"choose model", "no model selected", "none"}:
        return None
    prefix = raw.partition(":")[0].casefold()
    if prefix in FAMILIES:
        return raw
    return f"{family}:{raw}"
```

`_identity_from_gui` uses `_qualify_stored_model(family, model)` instead of `f"{family}:{model}"`.

`_flatten_settings`: change `if path not in IDENTITY_SETTING_PATHS and not isinstance(value, (dict, list))` to `if path not in IDENTITY_SETTING_PATHS and not isinstance(value, dict)`.

`cli/job.py` `_canonicalize_model_references`:

```python
        family_by_path = {
            "vr.model": "vr", "mdx.model": "mdx", "demucs.model": "demucs",
            "audio_tools.apollo_model": "apollo",
        }
        allowed_by_path = {
            "process.vocal_splitter": ("vr", "mdx"),
            "demucs.pre_proc_model": ("vr", "mdx"),
        }
        # secondaries: allowed_families=("vr", "mdx", "demucs")
        record = resolve_model_id(raw, repo)  # replace with:
        service = ModelIdentityService(repo)
        if path in family_by_path:
            record = service.resolve(raw, family=family_by_path[path], fuzzy=False)
        elif path in allowed_by_path:
            record = service.resolve(raw, allowed_families=allowed_by_path[path], fuzzy=False)
        elif "secondary_model" in path:
            record = service.resolve(raw, allowed_families=("vr", "mdx", "demucs"), fuzzy=False)
        else:
            record = service.resolve(raw, fuzzy=False)
```

Primary `--model` on the CLI may stay fuzzy (user typing). Stored/profile canonicalization is exact.

`IdentityMigrator.canonical`: pass `family=` into `resolve_model_record` by filtering records first (or call `self.identities.resolve(query, family=family, fuzzy=True)`). On `ValueError`, if `"ambiguous"` in the message or `"does not belong"` / `"not eligible"`, return a sentinel object or raise a dedicated `IdentityConflict` — `replace()` catches it, leaves `old` in place, and records a conflict. Only `unknown or unregistered` clears.

Do **not** keep `identity_schema_version` old forever: bump it after the pass, and surface conflicts on `IdentityMigrationResult.failures` (or a new `conflicts` tuple if you already have `settings_changes`). The GUI toast already reports failures.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m unittest tests.test_cli_redesign tests.test_core_consolidation -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add cli/profiles.py cli/job.py core/identity_migration.py tests/test_cli_redesign.py tests/test_core_consolidation.py
git commit -m "$(cat <<'EOF'
fix(cli): keep canonical GUI model IDs and family-scoped references

--profile gui was prefixing mdx:mdx:… after identity migration.
EOF
)"
```

---

### Task 6: GUI runs from a settings copy

**Files:**
- Modify: `ui/run_control.py` (`_start_target`, completion/stop/error handlers)
- Test: `tests/test_run_control.py`

**Interfaces:**
- Consumes: `plan.settings` (`ResolvedJob` or `ResolvedAudioJob`); `AppContext.runner`
- Produces: `_start_target` sets `context.runner.settings = copy.deepcopy(plan.settings)` and does **not** write `window.settings`. After complete/stop/error, restore `context.runner.settings = window.settings`.

- [ ] **Step 1: Write the failing test**

In `tests/test_run_control.py` (follow the file’s existing GTK skip / mock style):

```python
    def test_start_target_does_not_mutate_window_settings(self) -> None:
        # window.settings.mdx.compensate is None
        # plan.settings.mdx.compensate is 1.055
        # _start_target(target, plan)
        # assert window.settings.mdx.compensate is None
        # assert window.context.runner.settings.mdx.compensate == 1.055
```

If the existing tests construct a real `RunControl` with a fake window, reuse that. Do not call `widget.destroy()`.

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/python -m unittest tests.test_run_control -v`

Expected: after `_start_target`, `window.settings.mdx.compensate == 1.055` (current `__dict__.update` behavior).

- [ ] **Step 3: Implement**

Replace the `__dict__.update` block:

```python
    def _start_target(self, target: typing.Any, plan: typing.Any=None) -> None:
        runner = self._window.context.runner
        if plan is not None:
            import copy
            runner.settings = copy.deepcopy(plan.settings)
        else:
            runner.settings = self._window.settings
        callbacks = self._callbacks()
        debug("ui", f"handle_start -> {type(target).__name__}.start()")
        target.start(callbacks)
```

In `_on_complete`, `_on_stopped`, and `_on_error` (the three places that already clear `_running_target`), restore:

```python
        if self._window.context._runner is not None:
            self._window.context.runner.settings = self._window.settings
```

Use `_runner is not None` so restore does not lazily create a runner on a window that never started.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m unittest tests.test_run_control -v`

Expected: PASS. Existing preflight tests still pass.

- [ ] **Step 5: Commit**

```bash
git add ui/run_control.py tests/test_run_control.py
git commit -m "$(cat <<'EOF'
fix(ui): keep resolved plan settings on the runner only

Start was copying model-native compensate/segment into the live Settings object.
EOF
)"
```

---

### Task 7: Planning must not fetch MDX-C YAML

**Files:**
- Modify: `core/mdx_config_fetch.py` (`ensure_mdx_c_config`)
- Modify: `core/job_plan.py` (`JobResolver._assemble`)
- Modify: `core/model_data.py` only if it calls `ensure_mdx_c_config` without going through the new flag (pass the flag or a contextvar — pick **one** and use it everywhere in this task)
- Test: `tests/test_job_plan_topology.py` or `tests/test_mdx_c_registry.py`

**Interfaces:**
- Consumes: existing `ensure_mdx_c_config(filename) -> bool`
- Produces: `ensure_mdx_c_config(filename: str, *, allow_network: bool = True) -> bool`. If the dest file exists, return `True`. If it is missing and `allow_network` is false, return `False` without opening a socket and without writing. `JobResolver._assemble` calls assemble with network forbidden. A missing YAML becomes `Diagnostic("model.configuration", ...)`.

- [ ] **Step 1: Write the failing test**

```python
    def test_ensure_mdx_c_config_offline_does_not_fetch(self) -> None:
        from core.mdx_config_fetch import ensure_mdx_c_config
        with patch("core.mdx_config_fetch._fetch_url_to_file") as fetch:
            ok = ensure_mdx_c_config("definitely-missing-uvr-test.yaml", allow_network=False)
        self.assertFalse(ok)
        fetch.assert_not_called()

    def test_job_assemble_disables_mdx_c_network(self) -> None:
        from core.job_plan import JobResolver
        from core.mdx_config_fetch import _ALLOW_NETWORK
        from core.settings import Settings

        seen: list[bool] = []

        def fake_assemble(*_args, **_kwargs):
            seen.append(_ALLOW_NETWORK.get())
            return []

        resolver = JobResolver(Mock())
        with patch("core.job_plan.assemble_model", side_effect=fake_assemble):
            resolver._assemble(Settings.defaults(), "separate", [])
        self.assertEqual(seen, [False])
```

Minimum bar: both tests above. Implementation that keeps `ModelConfig` unchanged:

```python
# core/mdx_config_fetch.py
import contextvars
_ALLOW_NETWORK = contextvars.ContextVar("uvr_mdx_c_allow_network", default=True)

@contextlib.contextmanager
def mdx_c_network(allow_network: bool) -> Iterator[None]:
    token = _ALLOW_NETWORK.set(allow_network)
    try:
        yield
    finally:
        _ALLOW_NETWORK.reset(token)

def ensure_mdx_c_config(filename: str, *, allow_network: bool | None = None) -> bool:
    allowed = _ALLOW_NETWORK.get() if allow_network is None else allow_network
    ...
```

`JobResolver._assemble`:

```python
        from .mdx_config_fetch import mdx_c_network
        with mdx_c_network(False):
            return assemble_model(...)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m unittest tests.test_job_plan_topology -v`

Expected: `allow_network` TypeError, or fetch is called.

- [ ] **Step 3: Implement**

Add `allow_network` / `mdx_c_network` as above. In `ensure_mdx_c_config`, after the dest-exists check:

```python
    if not allowed:
        debug("download", f"mdx_c_config offline-miss name={safe}")
        return False
```

Do not change `DownloadManager` / `uvr models download` — they keep the default `allow_network=True`.

If `register_mdx_c_checkpoint(..., write=True)` is reached from assemble during resolve, pass `write=False` from the dry path or skip register when `_ALLOW_NETWORK` is false. Grep callers: `rg -n "register_mdx_c_checkpoint|ensure_mdx_c_config" core`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m unittest tests.test_job_plan_topology tests.test_mdx_c_registry -v`

Expected: PASS. Existing registry tests still fetch only when they patch `_urlopen` / allow network.

- [ ] **Step 5: Commit**

```bash
git add core/mdx_config_fetch.py core/job_plan.py tests/test_job_plan_topology.py
git commit -m "$(cat <<'EOF'
fix(core): do not download MDX-C YAML while planning a job

Validate and dry-run now fail with a configuration diagnostic instead of hitting the network.
EOF
)"
```

---

### Task 8: Docs and leftover presentation

**Files:**
- Modify: `docs/environment.md`
- Modify: `CLAUDE.md` (the read-only-offline bullet)
- Modify: `cli/CLAUDE.md` (the `catalogue_offline` bullet)
- Modify: `cli/discovery.py` (`_setting_paths`) so `settings show` / `explain` include `audio_tools` and `ui`
- Test: `tests/test_cli_redesign.py` or a small case in `tests/test_cli.py` that `fail(130)` still documents the contract (already in Task 2). Add `test_setting_paths_include_audio_tools`.

**Interfaces:**
- Consumes: Task 2 `fail()` contract; Task 7 offline planning
- Produces: documented manifest `schema_version` 1 (separate/ensemble) and 2 (audio); documented `--report json` interrupt fields; docs that say planning uses `allow_network=False` / `mdx_c_network(False)`, not `catalogue_offline()`.

- [ ] **Step 1: Write the failing test**

```python
    def test_setting_paths_include_audio_and_ui(self) -> None:
        from cli.discovery import _setting_paths
        paths = _setting_paths()
        self.assertIn("audio_tools.apollo_model", paths)
        self.assertIn("ui.confirm_processing_plan", paths)
```

- [ ] **Step 2: Run it to verify it fails**

Run: `.venv/bin/python -m unittest tests.TestCliRedesign.test_setting_paths_include_audio_and_ui -v`

Expected: assertion fail.

- [ ] **Step 3: Implement docs and `_setting_paths`**

`_setting_paths`:

```python
    for section in ("process", "vr", "mdx", "demucs", "ensemble", "audio_tools", "ui"):
        result.extend(
            f"{section}.{field.name}"
            for field in dataclasses.fields(getattr(settings, section))
        )
```

`docs/environment.md` — add under the CLI section:

```markdown
| Manifest `schema_version` | `1` for `separate` / `ensemble`; `2` for `audio` |
| Interrupt document | `ok: false`, `status: "failed"`, `stopped: true`, exit `130` |
| Planning / validate / dry-run | Installed + cached metadata only. Missing MDX-C YAML is an error; use `uvr models download` |
```

Replace the root `CLAUDE.md` sentence that names `cli/offline.py` with: read-only listing passes `allow_network=False` into catalogue helpers; `core.offline.catalogue_offline` is a deprecated no-op.

Replace the `cli/CLAUDE.md` bullet the same way.

Do not edit `docs/reviews/*`.

- [ ] **Step 4: Run tests and basedpyright**

Run:

```bash
.venv/bin/python -m unittest tests.test_cli tests.test_cli_redesign tests.test_cli_promotion tests.test_job_plan_topology tests.test_job_runner_planned tests.test_export_naming_rebase tests.test_run_control tests.test_core_consolidation tests.test_mdx_c_registry -v
.venv/bin/python -m basedpyright cli/execution.py cli/bench.py cli/reporting.py cli/profiles.py cli/job.py cli/discovery.py core/job_plan.py core/job_runner.py core/export_naming.py core/mdx_config_fetch.py core/identity_migration.py ui/run_control.py
```

Expected: tests PASS, 0 basedpyright errors.

- [ ] **Step 5: Commit**

```bash
git add cli/discovery.py docs/environment.md CLAUDE.md cli/CLAUDE.md tests/test_cli_redesign.py
git commit -m "$(cat <<'EOF'
docs(cli): document planning offline rules and interrupt JSON

Stop describing catalogue_offline as an env-flag guard; it no longer mutates UVR_DISABLE_*.
EOF
)"
```

---

## Delivery gate (after Task 8)

```bash
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python -m basedpyright
.venv/bin/python -m unittest tests.test_uvr_launcher -v
git diff --check
```

`rg catalogue_offline` should no longer appear in `CLAUDE.md` / `cli/CLAUDE.md` as something that sets disable flags. `rg _apply_planned_basename` must be empty. `rg __dict__.update` in `ui/run_control.py` must be empty.

---

## Coverage vs the first-cut list

| First-cut item | Task |
| --- | --- |
| Runner writes `PlannedInput.naming`; delete `_apply_planned_basename` | 3, 4 |
| Exact-destination preflight; common-suffix rename | 4 |
| Assemble once per job; planned `file_index` / `file_total` on one-file start | 3, 4 |
| Ensemble topology helper; bench reads `plan["models"]` | 1, 2 |
| `--profile gui` prefix guard; family constraints; GUI run-local settings | 5, 6 |
| Interrupt JSON on `fail(130)`; MDX-C planning diagnostic; docs | 2, 7, 8 |
