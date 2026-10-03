# Stem Comparison Playback Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** After any GUI run, open a "Compare stems" dialog that plays the original and every output of each processed input in lockstep, switching the audible track instantly.

**Architecture:** Core reports each finished input's source, reference audio and written outputs through the existing `JobCallbacks.input_finished`. A pure `core/listening.py` turns those into `ComparisonSet`s. The GTK side keeps the latest run's sets in a `ListeningSession`, and a `CompareDialog` drives a `PlaybackEngine`, which is one GStreamer pipeline (`uridecodebin → audioconvert → audioresample → volume` per track, all into `audiomixer`) where the selected track has volume 1.0.

**Tech Stack:** Python 3.12+, PyGObject GTK 4 / libadwaita, GStreamer 1.x via GI (`Gst`, `GstPbutils`), Blueprint, stdlib `unittest`, basedpyright, ruff.

**Spec:** [docs/superpowers/specs/2026-09-28-stem-comparison-playback-design.md](../specs/2026-09-28-stem-comparison-playback-design.md)

## Global Constraints

- Backend code (`core/`) must not import GTK, GStreamer or anything under `ui/`.
- `Gst` / `GstPbutils` are imported only inside `ui/playback/engine.py`, and only inside functions (lazy); importing `ui.playback.engine` must not load GStreamer.
- No new Python packages. GStreamer is an optional distro dependency: when it is missing the app behaves exactly as today.
- GTK callbacks run on the main loop. Worker-thread callbacks reach the UI only through `ui/dispatch.py` wrappers.
- Blueprint sources live in `resources/ui/*.blp`; rebuild with `./resources/compile_resources.sh`, lint with `blueprint-compiler lint`, and verify with `./resources/compile_resources.sh --check`. Commit the regenerated `.ui` files and `ui/data/uvr.gresource` with the `.blp`.
- Use `ui.template.load_builder` / `object_from_builder`; widget state through `ui/widget_state.py`; no `row._uvr_x = …` attributes.
- Never call `widget.destroy()` in tests. GTK tests use `@unittest.skipUnless(DISPLAY or WAYLAND_DISPLAY)` and `gi.require_version` in `setUpClass`. Engine tests need no display, only GStreamer.
- User-facing copy: sentence case, no "please", no "successfully". Dialog title "Compare stems"; toast button "Compare"; footer button "Open folder"; hint "Space play · 1–9 switch · ← → 5 s".
- Diagnostics via `core.debug_log.log_event("playback", …)`; never log position ticks.
- Format every touched Python file with `.venv/bin/ruff format`, check with `.venv/bin/ruff check`. Before the final commit, run the full `.venv/bin/python -m basedpyright` (project-wide, not just touched files).
- Search with `rg`. Stage files explicitly by path; never `git add -A`, `git stash`, `git reset --hard`, or `git clean`.
- Deviation from the spec, recorded here: a separation input that *fails* aborts the whole run (the existing run loop raises), so `input_finished` is emitted for successful and skipped inputs only; failed runs show no Compare action. The volume switch is immediate (the spec allows this in place of a GstController ramp).

## Review Focus

1. **Paths with spaces and non-ASCII characters** (`Björk – Jóga (Vocals).flac`): the engine must convert with `Gst.filename_to_uri`, never by string concatenation. Pinned by `test_unicode_path_with_spaces_plays` in Task 3.
2. **Mismatched formats between tracks** (mono 44.1 kHz WAV original, stereo 48 kHz FLAC stem): the mixer must negotiate, and duration is the longest. Pinned by `test_different_rates_and_channels_mix` in Task 3.
3. **Seek requested before preroll finishes** (user drags the bar right after the dialog opens, or switching input keeps the position): the seek must be applied after `ASYNC_DONE`, not lost. Pinned by `test_seek_before_preroll_is_applied` in Task 3.
4. **Reference or output missing from disk when the dialog opens** (sample-mode clip cleaned up, or the user deleted a stem): that row is disabled and the others still play. Pinned by `test_missing_file_reports_track_error_and_others_play` in Task 3 and `test_failed_track_row_is_insensitive` in Task 4.
5. **A new run starting while the dialog is open**: the dialog closes and the pipeline goes to `NULL` before the session is cleared, so audio never keeps playing stale files. Pinned by `test_begin_run_closes_open_dialog_and_clears_session` in Task 5.

---

## File Structure

| File | Responsibility |
|---|---|
| `core/job_callbacks.py` (modify) | `input_finished` / `on_input_finished` carry an optional `reference` path |
| `core/job_runner.py` (modify) | `_planned_output_paths` (shared rebasing) and `finished_input_report` (source, reference, existing outputs) |
| `core/run_loop.py` (modify) | Emit `input_finished` per input after `hooks.after_file`, and for skipped inputs |
| `core/listening.py` (new) | `Track`, `ComparisonSet`, `build_comparison_set`: pure data, no GTK |
| `ui/playback/__init__.py` (new) | Package marker only |
| `ui/playback/engine.py` (new) | `PlaybackEngine` + `playback_unavailable_reason()`: the only GStreamer code |
| `ui/playback/session.py` (new) | `ListeningSession`: the latest run's comparison sets, no GTK |
| `ui/playback/dialog.py` (new) | `CompareDialog`: the Adw.Dialog, driven through an engine protocol |
| `resources/ui/compare-stems-dialog.blp` (new) | Fixed dialog layout |
| `resources/ui/main-header.blp` (modify) | Hidden `compare_button` in the header end box |
| `resources/uvr.gresource.xml` (modify) | Register the new `.ui` |
| `ui/dispatch.py` (modify) | `gtk_job_callbacks(..., on_input_finished=…)` |
| `ui/protocols.py`, `ui/run_host.py`, `ui/window.py` (modify) | `RunHost.set_compare_available`, header button wiring |
| `ui/run_control.py` (modify) | Session lifecycle, plan capture, Compare toast, dialog ownership |
| `README.md`, `install_packages.sh`, `.github/workflows/test.yml`, `docs/tracked-issues.md` (modify) | Dependencies, troubleshooting, CI packages, roadmap row |

Tests: `tests/test_run_output_reporting.py`, `tests/test_listening.py`, `tests/test_playback_engine.py`, `tests/test_compare_dialog.py`, `tests/test_compare_run_integration.py`.

---

### Task 1: Core reports each finished input's outputs

**Files:**
- Modify: `core/job_callbacks.py:41-44` (field type) and `core/job_callbacks.py:119-126` (`input_finished`)
- Modify: `core/job_runner.py:447-473` (extract helper), add methods after `_planned_input_for_file` (`core/job_runner.py:484-491`)
- Modify: `core/run_loop.py:352-358` (skipped input) and `core/run_loop.py:510-511` (after `hooks.after_file`)
- Test: `tests/test_run_output_reporting.py` (new)

**Interfaces:**
- Consumes: existing `PlannedInput`, `PlannedOutput` (`core.job_plan`), `JobRunner._planned_input_for_file`, `JobRunner._run_path_map`.
- Produces:
  - `JobCallbacks.on_input_finished: Callable[[tuple[str, ...], tuple[str, ...], BaseException | None, str | None], None] | None`: the 4th positional argument is the reference path, or `None`.
  - `JobCallbacks.input_finished(paths, generated=(), error=None, reference: str | None = None) -> None`
  - `JobRunner.finished_input_report(audio_file: str) -> tuple[str, str, tuple[str, ...]]`, which returns `(source, reference, outputs)`.
  - `run_models_on_files` calls `callbacks.input_finished((source,), outputs, None, reference=reference)` once per processed input, and `callbacks.input_finished((path,), (), None)` for a missing input.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_run_output_reporting.py`:

```python
"""Core reports each finished input's source, reference and written outputs."""

from __future__ import annotations

import os
import tempfile
import unittest
from typing import Any
from unittest.mock import patch

from core.export_naming import OutputNamingContext
from core.job_callbacks import JobCallbacks
from core.job_plan import PlannedInput, PlannedOutput
from core.job_runner import JobRunner
from core.run_loop import run_models_on_files
from core.settings import Settings
from tests.test_run_loop import _Hooks, _model, _runner


def _planned(path: str, out_dir: str, *stems: str) -> PlannedInput:
    return PlannedInput(
        path=path,
        naming=OutputNamingContext(
            input_path=path,
            track="song",
            track_base="song",
            export_directory=out_dir,
            extension="wav",
        ),
        outputs=tuple(
            PlannedOutput(os.path.join(out_dir, f"song ({stem}).wav"), stem) for stem in stems
        ),
    )


class _Recorder:
    def __init__(self) -> None:
        self.calls: list[tuple[Any, ...]] = []

    def __call__(self, paths: Any, generated: Any, error: Any, reference: Any) -> None:
        self.calls.append((paths, generated, error, reference))


class InputFinishedCallbackTests(unittest.TestCase):
    def test_reference_is_forwarded_positionally(self) -> None:
        rec = _Recorder()
        JobCallbacks(on_input_finished=rec).input_finished(
            ("/in/a.wav",), ("/out/a (Vocals).wav",), None, reference="/tmp/clip.wav"
        )
        self.assertEqual(
            rec.calls, [(("/in/a.wav",), ("/out/a (Vocals).wav",), None, "/tmp/clip.wav")]
        )

    def test_reference_defaults_to_none(self) -> None:
        rec = _Recorder()
        JobCallbacks(on_input_finished=rec).input_finished(("/in/a.wav",))
        self.assertEqual(rec.calls, [(("/in/a.wav",), (), None, None)])


class FinishedInputReportTests(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = tmp.name
        self.src = os.path.join(self.dir, "song.wav")
        self.runner = JobRunner(Settings.defaults())

    def _touch(self, path: str) -> None:
        with open(path, "wb") as handle:
            handle.write(b"x")

    def test_reports_existing_outputs_in_plan_order(self) -> None:
        planned = _planned(self.src, self.dir, "Vocals", "Instrumental", "Other")
        self._touch(planned.outputs[1].path)
        self._touch(planned.outputs[0].path)
        self.runner._run_planned = (planned,)

        source, reference, outputs = self.runner.finished_input_report(self.src)

        self.assertEqual(source, self.src)
        self.assertEqual(reference, os.path.abspath(self.src))
        self.assertEqual(outputs, (planned.outputs[0].path, planned.outputs[1].path))

    def test_sample_mode_maps_clip_back_to_source(self) -> None:
        planned = _planned(self.src, self.dir, "Vocals")
        self._touch(planned.outputs[0].path)
        clip = os.path.join(self.dir, "clip.wav")
        self.runner._run_planned = (planned,)
        self.runner._run_path_map = {os.path.abspath(clip): os.path.abspath(self.src)}

        source, reference, outputs = self.runner.finished_input_report(clip)

        self.assertEqual(source, self.src)
        self.assertEqual(reference, os.path.abspath(clip))
        self.assertEqual(outputs, (planned.outputs[0].path,))

    def test_unplanned_run_reports_no_outputs(self) -> None:
        source, reference, outputs = self.runner.finished_input_report(self.src)
        self.assertEqual((source, reference, outputs), (os.path.abspath(self.src),) * 2 + ((),))


class RunLoopEmitsInputFinishedTests(unittest.TestCase):
    @patch("core.run_loop._decoded_mix_for_process")
    @patch("core.run_loop.run_separator")
    def test_emits_once_per_input_after_after_file(self, _run_sep: Any, decode: Any) -> None:
        import numpy as np

        decode.return_value = np.zeros((2, 4410), dtype=np.float32)
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "song.wav")
            with open(path, "wb") as handle:
                handle.write(b"x")
            runner = _runner()
            runner.finished_input_report = lambda f: (f, f + ".ref", (f + ".out",))
            rec = _Recorder()
            order: list[str] = []
            hooks = _Hooks()
            original_after = hooks.after_file

            def after_file(r: Any, state: Any) -> None:
                order.append("after_file")
                original_after(r, state)

            hooks.after_file = after_file  # type: ignore[method-assign]

            def recorder(*args: Any) -> None:
                order.append("input_finished")
                rec(*args)

            callbacks = JobCallbacks(on_input_finished=recorder)
            run_models_on_files(runner, [path], callbacks, [_model("m")], hooks=hooks)

        self.assertEqual(order, ["after_file", "input_finished"])
        self.assertEqual(rec.calls, [((path,), (path + ".out",), None, path + ".ref")])

    @patch("core.run_loop.run_separator")
    def test_missing_input_reports_no_outputs(self, _run_sep: Any) -> None:
        missing = os.path.join(tempfile.gettempdir(), "uvr-missing-output-report.wav")
        rec = _Recorder()
        run_models_on_files(
            _runner(),
            [missing],
            JobCallbacks(on_input_finished=rec),
            [_model("m")],
            hooks=_Hooks(),
        )
        self.assertEqual(rec.calls, [((missing,), (), None, None)])

    @patch("core.run_loop._decoded_mix_for_process")
    @patch("core.run_loop.run_separator")
    def test_runner_without_report_hook_still_runs(self, _run_sep: Any, decode: Any) -> None:
        import numpy as np

        decode.return_value = np.zeros((2, 4410), dtype=np.float32)
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "song.wav")
            with open(path, "wb") as handle:
                handle.write(b"x")
            rec = _Recorder()
            run_models_on_files(
                _runner(), [path], JobCallbacks(on_input_finished=rec), [_model("m")], hooks=_Hooks()
            )
        self.assertEqual(rec.calls, [])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m unittest tests.test_run_output_reporting -v`
Expected: FAIL. The recorder receives 3 arguments (`TypeError: __call__() missing 1 required positional argument: 'reference'`), and `AttributeError: 'JobRunner' object has no attribute 'finished_input_report'`.

- [ ] **Step 3: Add `reference` to `JobCallbacks`**

In `core/job_callbacks.py`, replace the field declaration:

```python
    on_input_finished: Optional[
        Callable[[tuple[str, ...], tuple[str, ...], BaseException | None, str | None], None]
    ] = None
```

and the method:

```python
    def input_finished(
        self,
        paths: typing.Sequence[str],
        generated: typing.Sequence[str] = (),
        error: BaseException | None = None,
        reference: str | None = None,
    ) -> None:
        """Report one finished input unit.

        ``reference`` is the audio the models actually read (a sample-mode clip
        or the input itself); ``None`` means "the first path in ``paths``".
        """
        if self.on_input_finished:
            self.on_input_finished(tuple(paths), tuple(generated), error, reference)
```

Update the class docstring's first paragraph to mention `on_input_finished` receives `(paths, generated, error, reference)`.

- [ ] **Step 4: Add the runner helpers and reuse them on the CLI path**

In `core/job_runner.py`, change the import on line 50 to:

```python
from .job_plan import PlannedInput, PlannedOutput, ResolvedJob
```

Add these methods directly after `_planned_input_for_file`:

```python
    def _planned_output_paths(self, planned: PlannedInput) -> list[tuple[PlannedOutput, str]]:
        """Planned outputs paired with the path this run writes them to.

        CLI runs stage exports under ``_run_output_root``; rebase through the same
        naming helper runtime export uses so both sides agree on the location.
        """
        pairs: list[tuple[PlannedOutput, str]] = []
        for output in planned.outputs:
            path = output.path
            if self._run_output_root is not None:
                naming = rebase_output_naming(
                    replace(planned.naming, export_directory=os.path.dirname(path)),
                    self.settings.process.export_path,
                    self._run_output_root,
                )
                path = os.path.join(naming.export_directory, os.path.basename(path))
            pairs.append((output, path))
        return pairs

    def finished_input_report(self, audio_file: str) -> tuple[str, str, tuple[str, ...]]:
        """``(source, reference, outputs)`` for an input the run loop just finished.

        ``source`` is the user's input path, ``reference`` the audio the models read
        (a sample-mode clip or the input), and ``outputs`` the planned outputs that
        exist on disk, in plan order. Unplanned runs report no outputs.
        """
        reference = os.path.abspath(audio_file)
        planned = self._planned_input_for_file(audio_file)
        if planned is None:
            return reference, reference, ()
        outputs = tuple(
            path for _output, path in self._planned_output_paths(planned) if os.path.isfile(path)
        )
        return planned.path, reference, outputs
```

Replace the per-input block in `_run_one_planned` (currently `core/job_runner.py:447-473`) with:

```python
        if box["status"] == "success":
            # CLI exports are still staged here. Check the same rebased directories
            # used by runtime naming, before the frontend promotes them to final paths.
            output_paths = self._planned_output_paths(planned)
            missing_required = tuple(
                path
                for output, path in output_paths
                if not output.conditional and not os.path.isfile(path)
            )
            if missing_required:
                return InputOutcome(
                    path=planned.path,
                    status="failed",
                    error=f"Missing required output after processing: {missing_required!r}",
                    elapsed_s=time.perf_counter() - started,
                )
            box["outputs"] = tuple(path for _output, path in output_paths if os.path.isfile(path))
```

- [ ] **Step 5: Emit from the run loop**

In `core/run_loop.py`, add this module-level helper above `run_models_on_files`:

```python
def _report_input_finished(runner: Any, callbacks: Any, audio_file: str) -> None:
    """Publish the finished input's outputs; runners without the hook stay silent."""
    report = getattr(runner, "finished_input_report", None)
    if not callable(report):
        return
    source, reference, outputs = report(audio_file)
    callbacks.input_finished((source,), outputs, None, reference=reference)
```

In the missing-file branch (`if plan is None:`), add the report after the console line:

```python
        if plan is None:
            audio_file = input_paths[file_num - 1]
            callbacks.console("Input file was not found; skipping.\n")
            callbacks.input_finished((audio_file,), (), None)
            runner.iteration += runner.true_model_count
            continue
```

After `hooks.after_file(runner, state)`, add:

```python
        hooks.after_file(runner, state)
        _report_input_finished(runner, callbacks, audio_file)
```

- [ ] **Step 6: Run the new and neighbouring tests**

The ensemble combine runs in `_EnsembleRunHooks.after_file` (`core/run_hooks.py:306`), so emitting after `after_file` reports the final combined outputs, not member files.

Run: `.venv/bin/python -m unittest tests.test_run_output_reporting tests.test_run_loop tests.test_job_runner_planned tests.test_run_console_output tests.test_audio_tools -v`
Expected: all PASS. If `tests.test_audio_tools` does not exist, run `rg -l "input_finished" tests` and include those modules instead.

- [ ] **Step 7: Lint, format and commit**

```bash
.venv/bin/ruff format core/job_callbacks.py core/job_runner.py core/run_loop.py tests/test_run_output_reporting.py
.venv/bin/ruff check core/job_callbacks.py core/job_runner.py core/run_loop.py tests/test_run_output_reporting.py
git add core/job_callbacks.py core/job_runner.py core/run_loop.py tests/test_run_output_reporting.py
git commit -m "feat(core): report each finished input's reference and outputs"
```

---

### Task 2: Comparison data model

**Files:**
- Create: `core/listening.py`
- Test: `tests/test_listening.py` (new)

**Interfaces:**
- Consumes: `core.job_plan.PlannedOutput` (`path`, `stem`, `role`), `core.stems.ui_label(str) -> str`.
- Produces:
  - `REFERENCE_LABEL = "Original"`
  - `@dataclass(frozen=True) class Track: label: str; path: str; role: str | None = None; is_reference: bool = False`
  - `@dataclass(frozen=True) class ComparisonSet: source: str; tracks: tuple[Track, ...]`, with property `name -> str` (basename of `source`)
  - `build_comparison_set(source: str, reference: str | None, outputs: Sequence[str], planned: Sequence[PlannedOutput] = ()) -> ComparisonSet | None`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_listening.py`:

```python
"""Comparison sets built from finished-input reports."""

from __future__ import annotations

import unittest

from core.job_plan import PlannedOutput
from core.listening import REFERENCE_LABEL, ComparisonSet, Track, build_comparison_set


class BuildComparisonSetTests(unittest.TestCase):
    def test_reference_first_then_outputs_with_plan_labels(self) -> None:
        planned = (
            PlannedOutput("/out/song (Vocals).wav", "Vocals"),
            PlannedOutput("/out/song (Instrumental).wav", "Instrumental"),
        )
        result = build_comparison_set(
            "/in/song.wav",
            "/in/song.wav",
            ["/out/song (Vocals).wav", "/out/song (Instrumental).wav"],
            planned,
        )
        assert result is not None
        self.assertEqual(result.name, "song.wav")
        self.assertEqual(
            result.tracks,
            (
                Track(REFERENCE_LABEL, "/in/song.wav", None, True),
                Track("Vocals", "/out/song (Vocals).wav"),
                Track("Instrumental", "/out/song (Instrumental).wav"),
            ),
        )

    def test_reference_defaults_to_source(self) -> None:
        result = build_comparison_set("/in/a.wav", None, ["/out/a (Restored).wav"])
        assert result is not None
        self.assertEqual(result.tracks[0].path, "/in/a.wav")

    def test_sample_clip_reference_is_kept(self) -> None:
        result = build_comparison_set("/in/a.wav", "/tmp/clip.wav", ["/out/a (Vocals).wav"])
        assert result is not None
        self.assertEqual(result.source, "/in/a.wav")
        self.assertEqual(result.tracks[0].path, "/tmp/clip.wav")

    def test_unplanned_outputs_use_parenthesised_filename_tag(self) -> None:
        result = build_comparison_set("/in/a.wav", None, ["/out/1_a_(Restored).wav"])
        assert result is not None
        self.assertEqual(result.tracks[1].label, "Restored")

    def test_unplanned_outputs_strip_the_input_name(self) -> None:
        result = build_comparison_set("/in/take.wav", None, ["/out/take_stretched.wav"])
        assert result is not None
        self.assertEqual(result.tracks[1].label, "stretched")

    def test_unplanned_label_falls_back_to_file_stem(self) -> None:
        result = build_comparison_set("/in/take.wav", None, ["/out/take.flac"])
        assert result is not None
        self.assertEqual(result.tracks[1].label, "take")

    def test_duplicates_dropped_and_order_stable(self) -> None:
        result = build_comparison_set(
            "/in/a.wav", None, ["/out/a (B).wav", "/out/a (A).wav", "/out/a (B).wav"]
        )
        assert result is not None
        self.assertEqual([t.label for t in result.tracks], [REFERENCE_LABEL, "B", "A"])

    def test_no_outputs_returns_none(self) -> None:
        self.assertIsNone(build_comparison_set("/in/a.wav", None, []))

    def test_role_text_is_carried(self) -> None:
        from core.stem_roles import StemRoleId

        role = StemRoleId("uvr.vocals")
        planned = (PlannedOutput("/out/a (Vocals).wav", "Vocals", role=role),)
        result = build_comparison_set("/in/a.wav", None, ["/out/a (Vocals).wav"], planned)
        assert result is not None
        self.assertEqual(result.tracks[1].role, "uvr.vocals")


class ComparisonSetTests(unittest.TestCase):
    def test_is_frozen(self) -> None:
        cset = ComparisonSet("/in/a.wav", (Track(REFERENCE_LABEL, "/in/a.wav", None, True),))
        with self.assertRaises(AttributeError):
            cset.source = "/x"  # type: ignore[misc]


if __name__ == "__main__":
    unittest.main()
```

Before running, confirm `StemRoleId`'s constructor with `rg -n "class StemRoleId" -A15 core/stem_roles.py`. If it validates a different namespace format, change `"uvr.vocals"` in `test_role_text_is_carried` to a value it accepts, keeping the assertion equal to that value.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m unittest tests.test_listening -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'core.listening'`.

- [ ] **Step 3: Implement `core/listening.py`**

```python
"""Comparison sets for in-app listening: which tracks belong to one input.

Pure data built from :meth:`core.job_callbacks.JobCallbacks.input_finished`
reports. No GTK and no GStreamer; the UI's playback engine consumes these.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Any, Sequence

from .job_plan import PlannedOutput
from .stems import ui_label

REFERENCE_LABEL = "Original"

_TRAILING_TAG = re.compile(r"\(([^()]+)\)\s*$")


@dataclass(frozen=True)
class Track:
    label: str
    path: str
    role: str | None = None
    is_reference: bool = False


@dataclass(frozen=True)
class ComparisonSet:
    source: str
    tracks: tuple[Track, ...]

    @property
    def name(self) -> str:
        return os.path.basename(self.source)


def _role_text(role: Any) -> str | None:
    if role is None:
        return None
    for attr in ("value", "tag"):
        text = getattr(role, attr, None)
        if isinstance(text, str) and text:
            return text
    return str(role)


def _filename_label(source: str, path: str) -> str:
    stem = os.path.splitext(os.path.basename(path))[0]
    tag = _TRAILING_TAG.search(stem)
    if tag:
        return tag.group(1).strip()
    base = os.path.splitext(os.path.basename(source))[0]
    stripped = stem.replace(base, "", 1).strip(" _-") if base else stem
    return stripped or stem


def build_comparison_set(
    source: str,
    reference: str | None,
    outputs: Sequence[str],
    planned: Sequence[PlannedOutput] = (),
) -> ComparisonSet | None:
    """Reference first, then each output once, in report order; ``None`` if no outputs."""
    by_path = {os.path.abspath(item.path): item for item in planned}
    tracks: list[Track] = []
    seen: set[str] = set()
    for path in outputs:
        key = os.path.abspath(path)
        if key in seen:
            continue
        seen.add(key)
        item = by_path.get(key)
        if item is not None:
            tracks.append(Track(ui_label(item.stem), path, _role_text(item.role)))
        else:
            tracks.append(Track(_filename_label(source, path), path))
    if not tracks:
        return None
    ref = Track(REFERENCE_LABEL, reference or source, None, True)
    return ComparisonSet(source, (ref, *tracks))


__all__ = ["REFERENCE_LABEL", "ComparisonSet", "Track", "build_comparison_set"]
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m unittest tests.test_listening -v`
Expected: all PASS.

- [ ] **Step 5: Lint, format and commit**

```bash
.venv/bin/ruff format core/listening.py tests/test_listening.py
.venv/bin/ruff check core/listening.py tests/test_listening.py
git add core/listening.py tests/test_listening.py
git commit -m "feat(core): comparison sets for in-app listening"
```

---

### Task 3: GStreamer playback engine

**Files:**
- Create: `ui/playback/__init__.py`, `ui/playback/engine.py`
- Test: `tests/test_playback_engine.py` (new)

**Interfaces:**
- Consumes: `core.listening.Track` (`label`, `path`).
- Produces:
  - `playback_unavailable_reason() -> str | None`: cached; `None` means playback works.
  - `class PlaybackEngine`:
    - `__init__(self, *, sink_factory: Callable[[], Gst.Element] | None = None, discover_timeout: float = 3.0)`
    - Callback attributes, each defaulting to a no-op: `on_position: Callable[[float], None]`, `on_duration: Callable[[float], None]`, `on_state: Callable[[bool], None]`, `on_track_error: Callable[[int, str], None]`, `on_error: Callable[[str], None]`
    - `load(tracks: Sequence[Track], *, selected: int = 0, position: float = 0.0) -> None`
    - `play() -> None`, `pause() -> None`, `toggle() -> None`, `seek(seconds: float) -> None`, `select(index: int) -> None`, `unload() -> None`
    - Read-only properties: `playing: bool`, `duration: float`, `position: float`, `selected: int`, `loaded: bool`
  - A `PlaybackControls` Protocol (in the same module) listing exactly those methods, properties and callback attributes, for the dialog to depend on.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_playback_engine.py`:

```python
"""GStreamer playback engine: lockstep mixing, instant selection, error isolation."""

from __future__ import annotations

import os
import tempfile
import time
import unittest
from typing import Any, Callable

import numpy as np
import soundfile as sf

from core.listening import Track
from ui.playback.engine import playback_unavailable_reason

_REASON = playback_unavailable_reason()


def _spin_until(predicate: Callable[[], bool], timeout: float = 5.0) -> bool:
    from gi.repository import GLib

    ctx = GLib.MainContext.default()
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        while ctx.pending():
            ctx.iteration(False)
        if predicate():
            return True
        time.sleep(0.01)
    return predicate()


def _fakesink() -> Any:
    from gi.repository import Gst

    sink = Gst.ElementFactory.make("fakesink")
    assert sink is not None
    sink.set_property("sync", True)
    return sink


def _tone(path: str, seconds: float, rate: int = 44100, channels: int = 1) -> None:
    t = np.linspace(0, seconds, int(rate * seconds), endpoint=False, dtype=np.float32)
    mono = 0.2 * np.sin(2 * np.pi * 440 * t)
    data = mono if channels == 1 else np.stack([mono] * channels, axis=1)
    sf.write(path, data, rate)


@unittest.skipIf(_REASON is not None, f"GStreamer playback unavailable: {_REASON}")
class PlaybackEngineTests(unittest.TestCase):
    def setUp(self) -> None:
        from ui.playback.engine import PlaybackEngine

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = tmp.name
        self.a = os.path.join(self.dir, "a.wav")
        self.b = os.path.join(self.dir, "b.wav")
        _tone(self.a, 1.0)
        _tone(self.b, 2.0)
        self.engine = PlaybackEngine(sink_factory=_fakesink)
        self.addCleanup(self.engine.unload)
        self.durations: list[float] = []
        self.positions: list[float] = []
        self.states: list[bool] = []
        self.track_errors: list[tuple[int, str]] = []
        self.errors: list[str] = []
        self.engine.on_duration = self.durations.append
        self.engine.on_position = self.positions.append
        self.engine.on_state = self.states.append
        self.engine.on_track_error = lambda i, m: self.track_errors.append((i, m))
        self.engine.on_error = self.errors.append

    def _load(self, *paths: str, selected: int = 0, position: float = 0.0) -> None:
        tracks = [Track(os.path.basename(p), p) for p in paths]
        self.engine.load(tracks, selected=selected, position=position)
        self.assertTrue(_spin_until(lambda: bool(self.durations)), "no duration reported")

    def test_duration_is_longest_track(self) -> None:
        self._load(self.a, self.b)
        self.assertAlmostEqual(self.durations[-1], 2.0, delta=0.05)

    def test_play_advances_position_and_pause_reports_state(self) -> None:
        self._load(self.a, self.b)
        self.engine.play()
        self.assertTrue(_spin_until(lambda: self.engine.position > 0.2))
        self.engine.pause()
        self.assertEqual(self.states, [True, False])
        self.assertFalse(self.engine.playing)

    def test_seek_moves_the_shared_position(self) -> None:
        self._load(self.a, self.b)
        self.engine.seek(1.5)
        self.assertTrue(_spin_until(lambda: abs(self.engine.position - 1.5) < 0.05))

    def test_seek_before_preroll_is_applied(self) -> None:
        tracks = [Track("a", self.a), Track("b", self.b)]
        self.engine.load(tracks, selected=0, position=1.2)
        self.assertTrue(_spin_until(lambda: abs(self.engine.position - 1.2) < 0.05))

    def test_select_sets_exactly_one_audible_branch_without_state_change(self) -> None:
        self._load(self.a, self.b)
        self.engine.play()
        _spin_until(lambda: self.engine.position > 0.1)
        self.engine.select(1)
        self.assertEqual(self.engine.selected, 1)
        self.assertEqual(self.engine._volumes_for_test(), {0: 0.0, 1: 1.0})
        self.assertEqual(self.states, [True])

    def test_missing_file_reports_track_error_and_others_play(self) -> None:
        missing = os.path.join(self.dir, "gone.wav")
        self._load(self.a, missing, self.b)
        self.assertEqual([i for i, _ in self.track_errors], [1])
        self.assertAlmostEqual(self.durations[-1], 2.0, delta=0.05)
        self.engine.play()
        self.assertTrue(_spin_until(lambda: self.engine.position > 0.1))
        self.assertEqual(self.errors, [])

    def test_corrupt_file_reports_track_error(self) -> None:
        bad = os.path.join(self.dir, "bad.wav")
        with open(bad, "wb") as handle:
            handle.write(b"RIFFnot-really-audio" * 8)
        self._load(bad, self.a)
        self.assertEqual([i for i, _ in self.track_errors], [0])

    def test_select_of_failed_track_is_ignored(self) -> None:
        missing = os.path.join(self.dir, "gone.wav")
        self._load(self.a, missing)
        self.engine.select(1)
        self.assertEqual(self.engine.selected, 0)

    def test_no_playable_tracks_reports_error(self) -> None:
        self.engine.load([Track("x", os.path.join(self.dir, "none.wav"))])
        self.assertTrue(_spin_until(lambda: bool(self.errors)))
        self.assertFalse(self.engine.loaded)

    def test_end_of_stream_pauses_and_play_restarts(self) -> None:
        self._load(self.a)
        self.engine.seek(0.9)
        self.engine.play()
        self.assertTrue(_spin_until(lambda: self.states[-1:] == [False], timeout=3.0))
        self.engine.play()
        self.assertTrue(_spin_until(lambda: 0.0 <= self.engine.position < 0.5))

    def test_different_rates_and_channels_mix(self) -> None:
        stereo48 = os.path.join(self.dir, "stereo.flac")
        _tone(stereo48, 1.5, rate=48000, channels=2)
        self._load(self.a, stereo48)
        self.assertAlmostEqual(self.durations[-1], 1.5, delta=0.05)
        self.assertEqual(self.track_errors, [])

    def test_unicode_path_with_spaces_plays(self) -> None:
        odd = os.path.join(self.dir, "Björk – Jóga (Vocals).wav")
        _tone(odd, 0.5)
        self._load(odd)
        self.assertEqual(self.track_errors, [])

    def test_unload_reaches_null_and_is_idempotent(self) -> None:
        self._load(self.a)
        self.engine.unload()
        self.engine.unload()
        self.assertFalse(self.engine.loaded)


class AvailabilityTests(unittest.TestCase):
    def test_import_does_not_load_gstreamer(self) -> None:
        import subprocess
        import sys

        code = (
            "import sys, ui.playback.engine; "
            "print('gi.repository.Gst' in sys.modules)"
        )
        out = subprocess.run(
            [sys.executable, "-c", code], capture_output=True, text=True, check=True
        ).stdout.strip()
        self.assertEqual(out, "False")

    def test_reason_is_cached(self) -> None:
        self.assertIs(playback_unavailable_reason(), playback_unavailable_reason())


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m unittest tests.test_playback_engine -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'ui.playback'`.

- [ ] **Step 3: Implement the engine**

Create `ui/playback/__init__.py`:

```python
"""In-app listening: GStreamer playback engine, session and comparison dialog."""
```

Create `ui/playback/engine.py`:

```python
"""Lockstep multi-track playback on one GStreamer pipeline.

Every track is decoded continuously into one ``audiomixer``; only the selected
branch has volume 1.0, so switching is instant and sample-aligned. Tracks are
screened with ``GstPbutils.Discoverer`` first: a branch that fails mid-stream
would stall the mixer, so unreadable files never join the pipeline.

This is the only module that imports GStreamer, and it does so lazily.
"""

from __future__ import annotations

import functools
from typing import TYPE_CHECKING, Callable, Protocol, Sequence

from gi.repository import GLib

from core.debug_log import log_event

if TYPE_CHECKING:
    from gi.repository import Gst

    from core.listening import Track

_REQUIRED_FACTORIES = (
    "uridecodebin",
    "audioconvert",
    "audioresample",
    "volume",
    "audiomixer",
    "autoaudiosink",
)
_POSITION_INTERVAL_MS = 100
_SECOND = 1_000_000_000


@functools.cache
def playback_unavailable_reason() -> str | None:
    """``None`` when playback works, else a short user-facing reason (cached)."""
    try:
        import gi

        gi.require_version("Gst", "1.0")
        gi.require_version("GstPbutils", "1.0")
        from gi.repository import Gst, GstPbutils  # noqa: F401
    except (ImportError, ValueError) as exc:
        reason = f"GStreamer is not installed ({exc})"
        log_event("playback", "unavailable", reason=reason)
        return reason
    ok, _argv = Gst.init_check(None)
    if not ok:
        reason = "GStreamer failed to initialise"
        log_event("playback", "unavailable", reason=reason)
        return reason
    missing = [name for name in _REQUIRED_FACTORIES if Gst.ElementFactory.find(name) is None]
    if missing:
        reason = "Missing GStreamer plugins: " + ", ".join(missing)
        log_event("playback", "unavailable", reason=reason)
        return reason
    return None


class PlaybackControls(Protocol):
    on_position: Callable[[float], None]
    on_duration: Callable[[float], None]
    on_state: Callable[[bool], None]
    on_track_error: Callable[[int, str], None]
    on_error: Callable[[str], None]

    @property
    def playing(self) -> bool: ...
    @property
    def duration(self) -> float: ...
    @property
    def position(self) -> float: ...
    @property
    def selected(self) -> int: ...
    @property
    def loaded(self) -> bool: ...
    def load(
        self, tracks: Sequence[Track], *, selected: int = 0, position: float = 0.0
    ) -> None: ...
    def play(self) -> None: ...
    def pause(self) -> None: ...
    def toggle(self) -> None: ...
    def seek(self, seconds: float) -> None: ...
    def select(self, index: int) -> None: ...
    def unload(self) -> None: ...


def _noop(*_args: object) -> None:
    return None


class PlaybackEngine:
    """One pipeline per loaded :class:`~core.listening.ComparisonSet`."""

    def __init__(
        self,
        *,
        sink_factory: Callable[[], Gst.Element] | None = None,
        discover_timeout: float = 3.0,
    ) -> None:
        self.on_position: Callable[[float], None] = _noop
        self.on_duration: Callable[[float], None] = _noop
        self.on_state: Callable[[bool], None] = _noop
        self.on_track_error: Callable[[int, str], None] = _noop
        self.on_error: Callable[[str], None] = _noop
        self._sink_factory = sink_factory
        self._discover_timeout = discover_timeout
        self._pipeline: Gst.Pipeline | None = None
        self._bus: Gst.Bus | None = None
        self._volumes: dict[int, Gst.Element] = {}
        self._selected = 0
        self._playing = False
        self._at_end = False
        self._prerolled = False
        self._pending_seek: float | None = None
        self._duration = 0.0
        self._timer: int | None = None

    # -- state ---------------------------------------------------------------

    @property
    def playing(self) -> bool:
        return self._playing

    @property
    def duration(self) -> float:
        return self._duration

    @property
    def selected(self) -> int:
        return self._selected

    @property
    def loaded(self) -> bool:
        return self._pipeline is not None

    @property
    def position(self) -> float:
        if self._pipeline is None:
            return 0.0
        from gi.repository import Gst

        ok, value = self._pipeline.query_position(Gst.Format.TIME)
        return value / _SECOND if ok and value >= 0 else 0.0

    def _volumes_for_test(self) -> dict[int, float]:
        return {i: float(v.get_property("volume")) for i, v in self._volumes.items()}

    # -- loading -------------------------------------------------------------

    def load(self, tracks: Sequence[Track], *, selected: int = 0, position: float = 0.0) -> None:
        from gi.repository import Gst, GstPbutils

        self.unload()
        discoverer = GstPbutils.Discoverer.new(int(self._discover_timeout * _SECOND))
        playable: list[tuple[int, str]] = []
        for index, track in enumerate(tracks):
            uri = Gst.filename_to_uri(track.path)
            try:
                info = discoverer.discover_uri(uri)
            except GLib.Error as exc:
                self._track_failed(index, exc.message)
                continue
            if not info.get_audio_streams():
                self._track_failed(index, "No audio stream")
                continue
            playable.append((index, uri))
        if not playable:
            self._fail("No playable tracks")
            return

        pipeline = Gst.Pipeline.new("uvr-compare")
        mixer = Gst.ElementFactory.make("audiomixer")
        out_convert = Gst.ElementFactory.make("audioconvert")
        sink = (
            self._sink_factory()
            if self._sink_factory is not None
            else Gst.ElementFactory.make("autoaudiosink")
        )
        if mixer is None or out_convert is None or sink is None:
            self._fail("Missing GStreamer elements")
            return
        for element in (mixer, out_convert, sink):
            pipeline.add(element)
        mixer.link(out_convert)
        out_convert.link(sink)

        for index, uri in playable:
            decode = Gst.ElementFactory.make("uridecodebin")
            convert = Gst.ElementFactory.make("audioconvert")
            resample = Gst.ElementFactory.make("audioresample")
            volume = Gst.ElementFactory.make("volume")
            if decode is None or convert is None or resample is None or volume is None:
                self._fail("Missing GStreamer elements")
                return
            decode.set_property("uri", uri)
            for element in (decode, convert, resample, volume):
                pipeline.add(element)
            convert.link(resample)
            resample.link(volume)
            volume.link(mixer)
            decode.connect("pad-added", self._on_pad_added, convert)
            self._volumes[index] = volume

        self._pipeline = pipeline
        self._selected = selected if selected in self._volumes else min(self._volumes)
        self._apply_volumes()
        self._pending_seek = position if position > 0 else None
        bus = pipeline.get_bus()
        if bus is not None:
            bus.add_signal_watch()
            bus.connect("message", self._on_message)
        self._bus = bus
        pipeline.set_state(Gst.State.PAUSED)
        log_event("playback", "load", tracks=len(tracks), playable=len(playable))

    @staticmethod
    def _on_pad_added(_decode: Gst.Element, pad: Gst.Pad, convert: Gst.Element) -> None:
        caps = pad.get_current_caps() or pad.query_caps(None)
        if not caps.to_string().startswith("audio/"):
            return
        sink_pad = convert.get_static_pad("sink")
        if sink_pad is not None and not sink_pad.is_linked():
            pad.link(sink_pad)

    # -- transport -----------------------------------------------------------

    def play(self) -> None:
        if self._pipeline is None:
            return
        from gi.repository import Gst

        if self._at_end:
            self._at_end = False
            self.seek(0.0)
        self._pipeline.set_state(Gst.State.PLAYING)
        self._set_playing(True)

    def pause(self) -> None:
        if self._pipeline is None:
            return
        from gi.repository import Gst

        self._pipeline.set_state(Gst.State.PAUSED)
        self._set_playing(False)
        self.on_position(self.position)

    def toggle(self) -> None:
        if self._playing:
            self.pause()
        else:
            self.play()

    def seek(self, seconds: float) -> None:
        if self._pipeline is None:
            return
        target = max(0.0, seconds)
        if self._duration > 0:
            target = min(target, self._duration)
        if not self._prerolled:
            self._pending_seek = target
            return
        from gi.repository import Gst

        self._at_end = False
        self._pipeline.seek_simple(
            Gst.Format.TIME,
            Gst.SeekFlags.FLUSH | Gst.SeekFlags.ACCURATE,
            int(target * _SECOND),
        )
        self.on_position(target)

    def select(self, index: int) -> None:
        if index not in self._volumes:
            return
        self._selected = index
        self._apply_volumes()

    def unload(self) -> None:
        self._stop_timer()
        pipeline, self._pipeline = self._pipeline, None
        if self._bus is not None:
            self._bus.remove_signal_watch()
            self._bus = None
        if pipeline is not None:
            from gi.repository import Gst

            pipeline.set_state(Gst.State.NULL)
        self._volumes = {}
        self._prerolled = False
        self._pending_seek = None
        self._duration = 0.0
        self._at_end = False
        if self._playing:
            self._playing = False
            self.on_state(False)

    # -- internals -----------------------------------------------------------

    def _apply_volumes(self) -> None:
        for index, volume in self._volumes.items():
            volume.set_property("volume", 1.0 if index == self._selected else 0.0)

    def _set_playing(self, playing: bool) -> None:
        if playing == self._playing:
            return
        self._playing = playing
        if playing:
            self._start_timer()
        else:
            self._stop_timer()
        self.on_state(playing)

    def _start_timer(self) -> None:
        if self._timer is None:
            self._timer = GLib.timeout_add(_POSITION_INTERVAL_MS, self._tick)

    def _stop_timer(self) -> None:
        if self._timer is not None:
            GLib.source_remove(self._timer)
            self._timer = None

    def _tick(self) -> bool:
        if self._pipeline is None:
            self._timer = None
            return GLib.SOURCE_REMOVE
        self.on_position(self.position)
        return GLib.SOURCE_CONTINUE

    def _track_failed(self, index: int, message: str) -> None:
        log_event("playback", "track_error", index=index, error=message)
        self.on_track_error(index, message)

    def _fail(self, message: str) -> None:
        log_event("playback", "error", level="error", error=message)
        self.unload()
        self.on_error(message)

    def _on_message(self, _bus: Gst.Bus, message: Gst.Message) -> None:
        from gi.repository import Gst

        if self._pipeline is None:
            return
        kind = message.type
        if kind == Gst.MessageType.ASYNC_DONE and not self._prerolled:
            self._prerolled = True
            ok, value = self._pipeline.query_duration(Gst.Format.TIME)
            self._duration = value / _SECOND if ok and value > 0 else 0.0
            self.on_duration(self._duration)
            if self._pending_seek is not None:
                pending, self._pending_seek = self._pending_seek, None
                self.seek(pending)
        elif kind == Gst.MessageType.EOS:
            self._pipeline.set_state(Gst.State.PAUSED)
            self._at_end = True
            self._set_playing(False)
            self.on_position(self._duration)
        elif kind == Gst.MessageType.ERROR:
            error, _debug = message.parse_error()
            self._fail(error.message if error is not None else "Playback failed")


__all__ = ["PlaybackControls", "PlaybackEngine", "playback_unavailable_reason"]
```

If `from gi.repository import GLib` at module level makes `test_import_does_not_load_gstreamer` fail, the cause is `GLib` pulling in `Gst`, which it should not. Investigate rather than weaken the test.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m unittest tests.test_playback_engine -v`
Expected: all PASS here. On a machine without GStreamer, `PlaybackEngineTests` skips and `AvailabilityTests` passes.

If `test_seek_before_preroll_is_applied` is flaky because `ACCURATE` seeks land a few ms early, keep the 0.05 s tolerance and do not raise it. A larger miss means the pending seek ran before `ASYNC_DONE`.

- [ ] **Step 5: Type-check, lint, format and commit**

```bash
.venv/bin/ruff format ui/playback/__init__.py ui/playback/engine.py tests/test_playback_engine.py
.venv/bin/ruff check ui/playback/__init__.py ui/playback/engine.py tests/test_playback_engine.py
.venv/bin/python -m basedpyright ui/playback tests/test_playback_engine.py
git add ui/playback/__init__.py ui/playback/engine.py tests/test_playback_engine.py
git commit -m "feat(ui): lockstep GStreamer playback engine for stem comparison"
```

basedpyright must report 0 errors. Fix any GStreamer type errors by narrowing (`if x is None: …`), never by casting to `Any`.

---

### Task 4: Compare stems dialog

**Files:**
- Create: `resources/ui/compare-stems-dialog.blp`, `ui/playback/dialog.py`
- Modify: `resources/uvr.gresource.xml` (add `<file>ui/compare-stems-dialog.ui</file>` next to `ui/dual-batch-dialog.ui`), then regenerate `resources/ui/compare-stems-dialog.ui` and `ui/data/uvr.gresource`
- Test: `tests/test_compare_dialog.py` (new)

**Interfaces:**
- Consumes: `PlaybackControls` (Task 3), `ComparisonSet`, `Track` (Task 2), `ui.template.load_builder`, `ui.template.object_from_builder`, `ui.dialogs.utils.present_modal_dialog`, `ui.files.open_folder_in_file_manager`.
- Produces: `class CompareDialog`:
  - `__init__(self, sets: Sequence[ComparisonSet], engine: PlaybackControls, *, output_dir: str = "", on_toast: Callable[[str], None] | None = None, on_closed: Callable[[], None] | None = None)`
  - `present(self, parent: Gtk.Window | None) -> None`
  - `close(self) -> None`: force-closes and unloads.
  - Attributes used by tests: `dialog: Adw.Dialog`, `input_dropdown: Gtk.DropDown`, `rows: list[Adw.ActionRow]`, `play_button: Gtk.Button`, `seek_scale: Gtk.Scale`, `folder_button: Gtk.Button`
  - `handle_key(keyval: int) -> bool` (the key controller delegates to it, so tests call it directly)

- [ ] **Step 1: Write the Blueprint and register it**

Create `resources/ui/compare-stems-dialog.blp`:

```
using Gtk 4.0;
using Adw 1;

Adw.Dialog dialog {
  title: "Compare stems";
  content-width: 480;
  child: Adw.ToolbarView {
    [top]
    Adw.HeaderBar {}
    content: Gtk.Box {
      orientation: vertical;
      spacing: 12;
      margin-top: 6;
      margin-bottom: 12;
      margin-start: 12;
      margin-end: 12;
      Gtk.DropDown input_dropdown {
        visible: false;
      }
      Gtk.ListBox track_list {
        selection-mode: none;
        styles ["boxed-list"]
      }
      Gtk.Box {
        orientation: horizontal;
        spacing: 12;
        Gtk.Button play_button {
          icon-name: "media-playback-start-symbolic";
          valign: center;
          styles ["circular"]
        }
        Gtk.Label elapsed_label {
          label: "0:00";
          styles ["numeric", "dim-label"]
        }
        Gtk.Scale seek_scale {
          hexpand: true;
          draw-value: false;
          adjustment: Gtk.Adjustment {
            lower: 0;
            upper: 1;
            step-increment: 5;
          };
        }
        Gtk.Label total_label {
          label: "0:00";
          styles ["numeric", "dim-label"]
        }
      }
      Gtk.Box {
        orientation: horizontal;
        spacing: 12;
        Gtk.Label {
          label: "Space play · 1–9 switch · ← → 5 s";
          hexpand: true;
          xalign: 0;
          styles ["dim-label", "caption"]
        }
        Gtk.Button folder_button {
          label: "Open folder";
        }
      }
    };
  };
}
```

Add `<file>ui/compare-stems-dialog.ui</file>` to `resources/uvr.gresource.xml` directly after the `ui/dual-batch-dialog.ui` line, then run:

```bash
blueprint-compiler lint resources/ui/compare-stems-dialog.blp
./resources/compile_resources.sh
./resources/compile_resources.sh --check
```

Expected: lint has no errors (review any suggestions but don't redesign), compile succeeds, and `--check` reports the bundle matches.

- [ ] **Step 2: Write the failing tests**

Create `tests/test_compare_dialog.py`:

```python
"""Compare stems dialog driven through a fake engine."""

from __future__ import annotations

import os
import unittest
from typing import Any, Callable, Sequence

from core.listening import REFERENCE_LABEL, ComparisonSet, Track


def _noop(*_a: object) -> None:
    return None


class FakeEngine:
    def __init__(self) -> None:
        self.on_position: Callable[[float], None] = _noop
        self.on_duration: Callable[[float], None] = _noop
        self.on_state: Callable[[bool], None] = _noop
        self.on_track_error: Callable[[int, str], None] = _noop
        self.on_error: Callable[[str], None] = _noop
        self.calls: list[tuple[Any, ...]] = []
        self._playing = False
        self._selected = 0
        self._loaded = False
        self._position = 0.0
        self._duration = 0.0

    playing = property(lambda self: self._playing)
    duration = property(lambda self: self._duration)
    position = property(lambda self: self._position)
    selected = property(lambda self: self._selected)
    loaded = property(lambda self: self._loaded)

    def load(self, tracks: Sequence[Track], *, selected: int = 0, position: float = 0.0) -> None:
        self.calls.append(("load", tuple(t.path for t in tracks), selected, position))
        self._loaded = True
        self._selected = selected

    def play(self) -> None:
        self.calls.append(("play",))
        self._playing = True
        self.on_state(True)

    def pause(self) -> None:
        self.calls.append(("pause",))
        self._playing = False
        self.on_state(False)

    def toggle(self) -> None:
        self.pause() if self._playing else self.play()

    def seek(self, seconds: float) -> None:
        self.calls.append(("seek", seconds))
        self._position = seconds

    def select(self, index: int) -> None:
        self.calls.append(("select", index))
        self._selected = index

    def unload(self) -> None:
        self.calls.append(("unload",))
        self._loaded = False


def _set(name: str, *labels: str) -> ComparisonSet:
    src = f"/in/{name}.wav"
    tracks = [Track(REFERENCE_LABEL, src, None, True)]
    tracks += [Track(label, f"/out/{name} ({label}).wav") for label in labels]
    return ComparisonSet(src, tuple(tracks))


@unittest.skipUnless(
    os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"),
    "GTK widget construction needs a display",
)
class CompareDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        import gi

        gi.require_version("Gtk", "4.0")
        gi.require_version("Adw", "1")
        from gi.repository import Adw

        Adw.init()

    def _dialog(self, *sets: ComparisonSet, output_dir: str = "") -> tuple[Any, FakeEngine]:
        from ui.playback.dialog import CompareDialog

        engine = FakeEngine()
        closed: list[bool] = []
        dialog = CompareDialog(
            list(sets), engine, output_dir=output_dir, on_closed=lambda: closed.append(True)
        )
        self.closed = closed
        return dialog, engine

    def test_loads_first_set_with_first_output_selected(self) -> None:
        dialog, engine = self._dialog(_set("song", "Vocals", "Instrumental"))
        self.assertEqual(
            engine.calls[0],
            (
                "load",
                ("/in/song.wav", "/out/song (Vocals).wav", "/out/song (Instrumental).wav"),
                1,
                0.0,
            ),
        )
        self.assertEqual([r.get_title() for r in dialog.rows], [REFERENCE_LABEL, "Vocals", "Instrumental"])

    def test_dropdown_hidden_for_single_input(self) -> None:
        dialog, _ = self._dialog(_set("song", "Vocals"))
        self.assertFalse(dialog.input_dropdown.get_visible())

    def test_dropdown_switch_reloads_and_keeps_position_paused(self) -> None:
        dialog, engine = self._dialog(_set("a", "Vocals"), _set("b", "Vocals", "Drums"))
        self.assertTrue(dialog.input_dropdown.get_visible())
        engine.play()
        engine._position = 12.0
        dialog.input_dropdown.set_selected(1)
        self.assertIn(("pause",), engine.calls)
        self.assertEqual(engine.calls[-1][0], "load")
        self.assertEqual(engine.calls[-1][1][0], "/in/b.wav")
        self.assertEqual(engine.calls[-1][3], 12.0)
        self.assertEqual(len(dialog.rows), 3)

    def test_row_activation_selects_track(self) -> None:
        dialog, engine = self._dialog(_set("song", "Vocals", "Instrumental"))
        dialog.rows[2].activate()
        self.assertEqual(engine.calls[-1], ("select", 2))

    def test_number_keys_select_and_space_toggles(self) -> None:
        from gi.repository import Gdk

        dialog, engine = self._dialog(_set("song", "Vocals", "Instrumental"))
        self.assertTrue(dialog.handle_key(Gdk.KEY_1))
        self.assertEqual(engine.calls[-1], ("select", 0))
        self.assertTrue(dialog.handle_key(Gdk.KEY_space))
        self.assertEqual(engine.calls[-1], ("play",))
        self.assertFalse(dialog.handle_key(Gdk.KEY_9))

    def test_arrow_keys_seek_five_seconds(self) -> None:
        from gi.repository import Gdk

        dialog, engine = self._dialog(_set("song", "Vocals"))
        engine._position = 10.0
        dialog.handle_key(Gdk.KEY_Right)
        self.assertEqual(engine.calls[-1], ("seek", 15.0))
        dialog.handle_key(Gdk.KEY_Left)
        self.assertEqual(engine.calls[-1], ("seek", 10.0))

    def test_failed_track_row_is_insensitive(self) -> None:
        dialog, engine = self._dialog(_set("song", "Vocals", "Instrumental"))
        engine.on_track_error(2, "Could not determine type of stream")
        self.assertFalse(dialog.rows[2].get_sensitive())
        self.assertIn("Could not determine", dialog.rows[2].get_tooltip_text() or "")

    def test_engine_error_disables_transport_and_toasts(self) -> None:
        from ui.playback.dialog import CompareDialog

        toasts: list[str] = []
        engine = FakeEngine()
        dialog = CompareDialog([_set("song", "Vocals")], engine, on_toast=toasts.append)
        engine.on_error("No audio sink")
        self.assertFalse(dialog.play_button.get_sensitive())
        self.assertEqual(toasts, ["Couldn't start playback. No audio sink"])

    def test_duration_and_position_update_labels_and_scale(self) -> None:
        dialog, engine = self._dialog(_set("song", "Vocals"))
        engine.on_duration(225.0)
        engine.on_position(83.0)
        self.assertEqual(dialog.seek_scale.get_adjustment().get_upper(), 225.0)
        self.assertEqual(dialog.seek_scale.get_value(), 83.0)

    def test_play_button_icon_follows_state(self) -> None:
        dialog, engine = self._dialog(_set("song", "Vocals"))
        engine.play()
        self.assertEqual(dialog.play_button.get_icon_name(), "media-playback-pause-symbolic")
        engine.pause()
        self.assertEqual(dialog.play_button.get_icon_name(), "media-playback-start-symbolic")

    def test_folder_button_hidden_without_output_dir(self) -> None:
        dialog, _ = self._dialog(_set("song", "Vocals"))
        self.assertFalse(dialog.folder_button.get_visible())

    def test_closed_signal_unloads_and_notifies(self) -> None:
        dialog, engine = self._dialog(_set("song", "Vocals"))
        dialog.dialog.emit("closed")
        self.assertEqual(engine.calls[-1], ("unload",))
        self.assertEqual(self.closed, [True])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 3: Run the tests to verify they fail**

Run under the isolated display:

```bash
env -u DISPLAY -u WAYLAND_DISPLAY -u DBUS_SESSION_BUS_ADDRESS -u DBUS_SYSTEM_BUS_ADDRESS -u XDG_RUNTIME_DIR -u XAUTHORITY -u SESSION_MANAGER -u UVR_REQUIRE_PRIVATE_GTK GDK_BACKEND=x11 GSK_RENDERER=cairo xvfb-run -a -s "-screen 0 1920x1080x24" .venv/bin/python -m unittest tests.test_compare_dialog -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'ui.playback.dialog'`.

- [ ] **Step 4: Implement `ui/playback/dialog.py`**

```python
"""Compare stems dialog: one input's tracks, one audible at a time."""

from __future__ import annotations

from typing import Callable, Sequence

from gi.repository import Adw, Gdk, Gtk

from core.listening import ComparisonSet

from ..dialogs.utils import present_modal_dialog
from ..files import open_folder_in_file_manager
from ..template import load_builder, object_from_builder
from .engine import PlaybackControls

_SEEK_STEP = 5.0
_PLAY_ICON = "media-playback-start-symbolic"
_PAUSE_ICON = "media-playback-pause-symbolic"
_NUMBER_KEYS = {getattr(Gdk, f"KEY_{n}"): n - 1 for n in range(1, 10)}
_NUMBER_KEYS.update({getattr(Gdk, f"KEY_KP_{n}"): n - 1 for n in range(1, 10)})


def _mmss(seconds: float) -> str:
    whole = max(0, int(seconds))
    return f"{whole // 60}:{whole % 60:02d}"


class CompareDialog:
    def __init__(
        self,
        sets: Sequence[ComparisonSet],
        engine: PlaybackControls,
        *,
        output_dir: str = "",
        on_toast: Callable[[str], None] | None = None,
        on_closed: Callable[[], None] | None = None,
    ) -> None:
        self._sets = list(sets)
        self._engine = engine
        self._output_dir = output_dir
        self._on_toast = on_toast
        self._on_closed = on_closed
        self._parent: Gtk.Window | None = None

        builder = load_builder("compare-stems-dialog")
        self.dialog = object_from_builder(builder, "dialog", Adw.Dialog)
        self.input_dropdown = object_from_builder(builder, "input_dropdown", Gtk.DropDown)
        self._track_list = object_from_builder(builder, "track_list", Gtk.ListBox)
        self.play_button = object_from_builder(builder, "play_button", Gtk.Button)
        self._elapsed = object_from_builder(builder, "elapsed_label", Gtk.Label)
        self.seek_scale = object_from_builder(builder, "seek_scale", Gtk.Scale)
        self._total = object_from_builder(builder, "total_label", Gtk.Label)
        self.folder_button = object_from_builder(builder, "folder_button", Gtk.Button)
        self.rows: list[Adw.ActionRow] = []
        self._checks: list[Gtk.CheckButton] = []

        self.play_button.update_property([Gtk.AccessibleProperty.LABEL], ["Play"])
        self.play_button.connect("clicked", lambda _b: self._engine.toggle())
        self.seek_scale.connect("change-value", self._on_change_value)
        self.folder_button.set_visible(bool(output_dir))
        self.folder_button.connect("clicked", self._on_open_folder)
        self.dialog.connect("closed", self._on_dialog_closed)

        keys = Gtk.EventControllerKey()
        keys.connect("key-pressed", lambda _c, keyval, _code, _state: self.handle_key(keyval))
        self.dialog.add_controller(keys)

        engine.on_position = self._on_position
        engine.on_duration = self._on_duration
        engine.on_state = self._on_state
        engine.on_track_error = self._on_track_error
        engine.on_error = self._on_engine_error

        if len(self._sets) > 1:
            total = len(self._sets)
            names = [f"{s.name}  {i} of {total}" for i, s in enumerate(self._sets, start=1)]
            self.input_dropdown.set_model(Gtk.StringList.new(names))
            self.input_dropdown.set_visible(True)
            self.input_dropdown.connect("notify::selected", self._on_input_changed)
        self._show_set(0, position=0.0)

    # -- public ----------------------------------------------------------------

    def present(self, parent: Gtk.Window | None) -> None:
        self._parent = parent
        present_modal_dialog(self.dialog, parent)

    def close(self) -> None:
        self.dialog.force_close()
        self._engine.unload()

    def handle_key(self, keyval: int) -> bool:
        if keyval == Gdk.KEY_space:
            self._engine.toggle()
            return True
        if keyval == Gdk.KEY_Left:
            self._engine.seek(self._engine.position - _SEEK_STEP)
            return True
        if keyval == Gdk.KEY_Right:
            self._engine.seek(self._engine.position + _SEEK_STEP)
            return True
        index = _NUMBER_KEYS.get(keyval)
        if index is not None and index < len(self.rows) and self.rows[index].get_sensitive():
            self._select(index)
            return True
        return False

    # -- building --------------------------------------------------------------

    def _show_set(self, index: int, *, position: float) -> None:
        cset = self._sets[index]
        for row in self.rows:
            self._track_list.remove(row)
        self.rows = []
        self._checks = []
        group: Gtk.CheckButton | None = None
        for track in cset.tracks:
            row = Adw.ActionRow(title=track.label)
            if track.is_reference:
                row.set_subtitle("Reference")
            check = Gtk.CheckButton()
            if group is not None:
                check.set_group(group)
            else:
                group = check
            row.add_prefix(check)
            row.set_activatable_widget(check)
            row_index = len(self.rows)
            check.connect("toggled", self._on_check_toggled, row_index)
            self._track_list.append(row)
            self.rows.append(row)
            self._checks.append(check)
        selected = 1 if len(cset.tracks) > 1 else 0
        self._checks[selected].set_active(True)
        self.play_button.set_sensitive(True)
        self._engine.load(cset.tracks, selected=selected, position=position)

    def _select(self, index: int) -> None:
        if not self._checks[index].get_active():
            self._checks[index].set_active(True)
        else:
            self._engine.select(index)

    # -- signal handlers -------------------------------------------------------

    def _on_check_toggled(self, check: Gtk.CheckButton, index: int) -> None:
        if check.get_active():
            self._engine.select(index)

    def _on_input_changed(self, dropdown: Gtk.DropDown, _pspec: object) -> None:
        position = self._engine.position
        if self._engine.playing:
            self._engine.pause()
        self._show_set(dropdown.get_selected(), position=position)

    def _on_change_value(self, _scale: Gtk.Scale, _scroll: Gtk.ScrollType, value: float) -> bool:
        self._engine.seek(value)
        return False

    def _on_open_folder(self, _button: Gtk.Button) -> None:
        open_folder_in_file_manager(self._parent, self._output_dir, on_error=self._toast)

    def _on_dialog_closed(self, _dialog: Adw.Dialog) -> None:
        self._engine.unload()
        if self._on_closed is not None:
            self._on_closed()

    # -- engine callbacks ------------------------------------------------------

    def _on_position(self, seconds: float) -> None:
        self.seek_scale.set_value(seconds)
        self._elapsed.set_label(_mmss(seconds))

    def _on_duration(self, seconds: float) -> None:
        self.seek_scale.get_adjustment().set_upper(max(seconds, 1.0))
        self._total.set_label(_mmss(seconds))

    def _on_state(self, playing: bool) -> None:
        self.play_button.set_icon_name(_PAUSE_ICON if playing else _PLAY_ICON)
        self.play_button.update_property(
            [Gtk.AccessibleProperty.LABEL], ["Pause" if playing else "Play"]
        )

    def _on_track_error(self, index: int, message: str) -> None:
        if 0 <= index < len(self.rows):
            self.rows[index].set_sensitive(False)
            self.rows[index].set_tooltip_text(message)

    def _on_engine_error(self, message: str) -> None:
        self.play_button.set_sensitive(False)
        self._toast(f"Couldn't start playback. {message}")

    def _toast(self, message: str) -> None:
        if self._on_toast is not None:
            self._on_toast(message)


__all__ = ["CompareDialog"]
```

Check the signature of `open_folder_in_file_manager` with `rg -n "def open_folder_in_file_manager" -A6 ui/files.py`. If its first parameter does not accept `None`, pass `self._parent or self.dialog.get_root()` narrowed through `ui.gtk_narrow.root_window`.

- [ ] **Step 5: Run the tests to verify they pass**

Run the same `xvfb-run` command as in Step 3.
Expected: all PASS.

`dialog.dialog.emit("closed")` on a never-presented dialog is valid for this test. If `force_close()` inside `close()` warns because the dialog was never presented, guard it with `if self.dialog.get_parent() is not None or self.dialog.get_root() is not None:`.

- [ ] **Step 6: Type-check, lint, format and commit**

```bash
.venv/bin/ruff format ui/playback/dialog.py tests/test_compare_dialog.py
.venv/bin/ruff check ui/playback/dialog.py tests/test_compare_dialog.py
.venv/bin/python -m basedpyright ui/playback tests/test_compare_dialog.py
./resources/compile_resources.sh --check
git add resources/ui/compare-stems-dialog.blp resources/ui/compare-stems-dialog.ui resources/uvr.gresource.xml ui/data/uvr.gresource ui/playback/dialog.py tests/test_compare_dialog.py
git commit -m "feat(ui): compare stems dialog"
```

---

### Task 5: Run integration (session, callbacks, toast, header button)

**Files:**
- Create: `ui/playback/session.py`
- Modify: `ui/dispatch.py:202-220` (`gtk_job_callbacks`)
- Modify: `ui/protocols.py:138-195` (add `set_compare_available` to `RunHost`)
- Modify: `ui/run_host.py` (implement it)
- Modify: `resources/ui/main-header.blp` (compare button), `ui/window.py:361-365` (wire it), then regenerate `resources/ui/main-header.ui` and `ui/data/uvr.gresource`
- Modify: `ui/run_control.py` (`__init__`, `_callbacks`, `_start_target`, `begin_run`, `_on_complete`, `_on_stopped`, `_show_complete_toast`, new methods)
- Test: `tests/test_compare_run_integration.py` (new)

**Interfaces:**
- Consumes: `build_comparison_set` (Task 2), `playback_unavailable_reason`, `PlaybackEngine` (Task 3), `CompareDialog` (Task 4), `JobCallbacks.on_input_finished` 4-argument signature (Task 1).
- Produces:
  - `class ListeningSession`: `clear() -> None`, `add(cset: ComparisonSet) -> None` (replaces an existing set with the same `source`, keeping its position), `sets() -> tuple[ComparisonSet, ...]`, `__bool__`, `__len__`
  - `gtk_job_callbacks(..., on_input_finished: Callable[..., None] | None = None)`: lossless, ordered with console output via `boundary`
  - `RunHost.set_compare_available(self, available: bool) -> None`
  - `RunController.listening: ListeningSession`, `RunController.open_compare() -> None`, `RunController.compare_ready() -> bool`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_compare_run_integration.py`:

```python
"""Run controller collects finished inputs and offers the compare dialog."""

from __future__ import annotations

import unittest
from typing import Any, cast
from unittest import mock

from core.job_plan import PlannedOutput
from core.listening import REFERENCE_LABEL, ComparisonSet, Track
from ui.playback.session import ListeningSession


def _cset(src: str, *outs: str) -> ComparisonSet:
    return ComparisonSet(
        src, (Track(REFERENCE_LABEL, src, None, True), *(Track(o, o) for o in outs))
    )


class ListeningSessionTests(unittest.TestCase):
    def test_add_clear_and_order(self) -> None:
        session = ListeningSession()
        self.assertFalse(session)
        session.add(_cset("/a", "/a1"))
        session.add(_cset("/b", "/b1"))
        self.assertEqual([s.source for s in session.sets()], ["/a", "/b"])
        self.assertEqual(len(session), 2)
        session.clear()
        self.assertFalse(session)

    def test_same_source_replaces_in_place(self) -> None:
        session = ListeningSession()
        session.add(_cset("/a", "/a1"))
        session.add(_cset("/b", "/b1"))
        session.add(_cset("/a", "/a2"))
        self.assertEqual([s.tracks[-1].path for s in session.sets()], ["/a2", "/b1"])


class DispatchInputFinishedTests(unittest.TestCase):
    def test_input_finished_is_marshalled_with_all_arguments(self) -> None:
        from ui.dispatch import gtk_job_callbacks

        received: list[tuple[Any, ...]] = []
        scheduled: list[Any] = []
        with mock.patch("ui.dispatch.GLib.idle_add", side_effect=lambda f, *a: scheduled.append((f, a))):
            callbacks = gtk_job_callbacks(on_input_finished=lambda *a: received.append(a))
            callbacks.input_finished(("/in/a.wav",), ("/out/a.wav",), None, reference="/c.wav")
            self.assertEqual(received, [])
            for func, args in scheduled:
                func(*args)
        self.assertEqual(received, [(("/in/a.wav",), ("/out/a.wav",), None, "/c.wav")])


def _controller() -> tuple[Any, mock.Mock]:
    from core.settings import Settings
    from ui.run_control import RunController
    from ui.run_error_context import RunErrorContext
    from ui.run_host import GtkRunHost
    from ui.run_progress import RunProgressPresenter

    window = mock.Mock()
    window.settings = Settings.defaults()
    window.context.runner.settings = Settings.defaults()
    controller = RunController(GtkRunHost(cast(Any, window)))
    controller.progress = RunProgressPresenter()
    controller._snapshot_error_context = mock.Mock(return_value=RunErrorContext("test"))
    controller._run_label_for = mock.Mock(return_value="Separation")
    controller._set_running = mock.Mock()
    controller._restore_runner_settings = mock.Mock()
    controller._send_completion_notification = mock.Mock()
    controller._schedule_release_inference_memory = mock.Mock()
    return controller, window


def _begin(controller: Any) -> None:
    with (
        mock.patch("ui.run_control.mark_run_start"),
        mock.patch("ui.run_control.reset_progress_log"),
        mock.patch("core.error_context.clear_run_error_context"),
        mock.patch("core.error_context.set_run_error_context"),
    ):
        controller.begin_run(mock.Mock())


class RunControllerCompareTests(unittest.TestCase):
    def test_input_finished_builds_labelled_sets_from_the_plan(self) -> None:
        controller, _ = _controller()
        controller._run_planned_outputs = {
            "/in/song.wav": (PlannedOutput("/out/song (Vocals).wav", "Vocals"),)
        }
        _begin(controller)
        controller._on_input_finished(("/in/song.wav",), ("/out/song (Vocals).wav",), None, None)
        (cset,) = controller.listening.sets()
        self.assertEqual([t.label for t in cset.tracks], [REFERENCE_LABEL, "Vocals"])

    def test_input_without_outputs_is_ignored(self) -> None:
        controller, _ = _controller()
        _begin(controller)
        controller._on_input_finished(("/in/song.wav",), (), None, None)
        self.assertFalse(controller.listening)

    def test_begin_run_closes_open_dialog_and_clears_session(self) -> None:
        controller, window = _controller()
        controller.listening.add(_cset("/a", "/a1"))
        dialog = mock.Mock()
        controller._compare_dialog = dialog
        _begin(controller)
        dialog.close.assert_called_once()
        self.assertIsNone(controller._compare_dialog)
        self.assertFalse(controller.listening)
        window.set_compare_available.assert_called_with(False)

    def test_complete_toast_offers_compare_when_ready(self) -> None:
        controller, window = _controller()
        _begin(controller)
        controller.listening.add(_cset("/a", "/a1"))
        with mock.patch("ui.run_control.playback_unavailable_reason", return_value=None):
            controller._on_complete()
        toast = window.toast_overlay.add_toast.call_args.args[0]
        self.assertEqual(toast.get_button_label(), "Compare")
        window.set_compare_available.assert_called_with(True)

    def test_complete_toast_keeps_open_folder_without_gstreamer(self) -> None:
        controller, window = _controller()
        _begin(controller)
        controller.listening.add(_cset("/a", "/a1"))
        controller._run_output_dir = "/"
        with mock.patch("ui.run_control.playback_unavailable_reason", return_value="missing"):
            controller._on_complete()
        toast = window.toast_overlay.add_toast.call_args.args[0]
        self.assertEqual(toast.get_button_label(), "Open Folder")
        window.set_compare_available.assert_called_with(False)

    def test_stopped_run_with_finished_inputs_offers_compare(self) -> None:
        controller, window = _controller()
        _begin(controller)
        controller.listening.add(_cset("/a", "/a1"))
        window.context.runner.last_oom_exported = False
        controller._host.exported_after_oom = mock.Mock(return_value=False)
        controller._finish_run_ui = mock.Mock()
        with mock.patch("ui.run_control.playback_unavailable_reason", return_value=None):
            controller._on_stopped()
        toast = window.toast_overlay.add_toast.call_args.args[0]
        self.assertEqual(toast.get_button_label(), "Compare")

    def test_open_compare_presents_one_dialog(self) -> None:
        controller, _ = _controller()
        controller.listening.add(_cset("/a", "/a1"))
        with (
            mock.patch("ui.run_control.playback_unavailable_reason", return_value=None),
            mock.patch("ui.playback.engine.PlaybackEngine") as engine_cls,
            mock.patch("ui.playback.dialog.CompareDialog") as dialog_cls,
        ):
            controller.open_compare()
            controller.open_compare()
        dialog_cls.assert_called_once()
        self.assertIs(dialog_cls.call_args.args[1], engine_cls.return_value)
        dialog_cls.return_value.present.assert_called()


if __name__ == "__main__":
    unittest.main()
```

`window` is a `mock.Mock`, so `GtkRunHost.set_compare_available` must call a window method named `set_compare_available` (Step 5). That is what these assertions observe.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m unittest tests.test_compare_run_integration -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'ui.playback.session'`.

- [ ] **Step 3: Implement the session**

Create `ui/playback/session.py`:

```python
"""The latest run's comparison sets, in arrival order. No GTK."""

from __future__ import annotations

from core.listening import ComparisonSet


class ListeningSession:
    def __init__(self) -> None:
        self._sets: dict[str, ComparisonSet] = {}

    def clear(self) -> None:
        self._sets.clear()

    def add(self, cset: ComparisonSet) -> None:
        self._sets[cset.source] = cset

    def sets(self) -> tuple[ComparisonSet, ...]:
        return tuple(self._sets.values())

    def __len__(self) -> int:
        return len(self._sets)

    def __bool__(self) -> bool:
        return bool(self._sets)


__all__ = ["ListeningSession"]
```

A `dict` keeps insertion order, and reassigning an existing key keeps its position, which is exactly what `test_same_source_replaces_in_place` requires.

- [ ] **Step 4: Marshal `on_input_finished` in `ui/dispatch.py`**

Replace `gtk_job_callbacks` with:

```python
def gtk_job_callbacks(
    on_progress: Optional[Callable[[float], None]] = None,
    on_console: Optional[Callable[[str], None]] = None,
    on_complete: Optional[Callable[[], None]] = None,
    on_stopped: Optional[Callable[[], None]] = None,
    on_error: Optional[Callable[[BaseException], None]] = None,
    on_oom_choice: Optional[Callable[[OomChoiceRequest], None]] = None,
    on_input_finished: Optional[Callable[..., None]] = None,
) -> JobCallbacks:
    """Build :class:`JobCallbacks` whose handlers run on the GTK main loop."""
    console = _ConsoleBatch(on_console) if on_console else None
    boundary = console.boundary if console else main_thread
    return JobCallbacks(
        on_progress=latest_main_thread(on_progress) if on_progress else None,
        on_console=console.append if console else None,
        on_complete=boundary(on_complete) if on_complete else None,
        on_stopped=boundary(on_stopped) if on_stopped else None,
        on_error=boundary(on_error) if on_error else None,
        on_oom_choice=boundary(on_oom_choice) if on_oom_choice else None,
        on_input_finished=boundary(on_input_finished) if on_input_finished else None,
    )
```

`boundary` is lossless and ordered with console output, so every finished input is delivered before `on_complete`.

- [ ] **Step 5: Host method, header button, window wiring**

In `ui/protocols.py`, add to `RunHost` after `mark_run_complete`:

```python
    def set_compare_available(self, available: bool) -> None: ...
```

In `ui/run_host.py`, add after `mark_run_complete`:

```python
    def set_compare_available(self, available: bool) -> None:
        self.window.set_compare_available(available)
```

In `resources/ui/main-header.blp`, add the button before `menu_button`:

```
    Gtk.Button compare_button {
      icon-name: "media-playback-start-symbolic";
      visible: false;
    }
    Gtk.MenuButton menu_button { icon-name: "open-menu-symbolic"; }
```

In `ui/window.py`, next to the existing `menu_button` lines (`ui/window.py:363-365`):

```python
        self._compare_button = object_from_builder(builder, "compare_button", Gtk.Button)
        set_icon_button_a11y(self._compare_button, "Compare stems")
        self._compare_button.connect("clicked", lambda _b: self._run_controller.open_compare())
```

Add this public method to `MainWindow` (place it near the other run-host-facing helpers such as `toast`):

```python
    def set_compare_available(self, available: bool) -> None:
        """Show the header Compare button while the last run has tracks to play."""
        self._compare_button.set_visible(available)
```

Check with `rg -n "_run_controller\s*=" ui/window.py` that `_run_controller` exists by the time the button can be clicked. The lambda resolves it at click time, so construction order does not matter.

Rebuild resources:

```bash
blueprint-compiler lint resources/ui/main-header.blp
./resources/compile_resources.sh
./resources/compile_resources.sh --check
```

- [ ] **Step 6: Wire the controller**

In `ui/run_control.py`:

1. Imports. Add at module top, alongside the existing `from .dispatch import …`:

```python
from .playback.engine import playback_unavailable_reason
from .playback.session import ListeningSession
```

(`ui.playback.engine` is GStreamer-free at import time, as enforced by Task 3's `test_import_does_not_load_gstreamer`.) Add a constant next to `_OPEN_FOLDER_LABEL`:

```python
_COMPARE_LABEL = "Compare"
_PROGRESS_STOPPED_TOAST = "Process stopped."
```

2. In `RunController.__init__`, next to `self._run_output_dir = ""`:

```python
        self.listening = ListeningSession()
        self._compare_dialog: Any = None
        self._run_planned_outputs: dict[str, tuple[Any, ...]] = {}
```

3. In `_callbacks`, pass the new handler to `gtk_job_callbacks`:

```python
            on_input_finished=current_run(self._on_input_finished),
```

4. In `_start_target`, record planned outputs before `target.start(...)` is called (right after `callbacks = self._callbacks()`):

```python
        self._run_planned_outputs = {}
        if isinstance(plan, ResolvedJob):
            self._run_planned_outputs = {
                os.path.abspath(item.path): tuple(item.outputs) for item in plan.inputs
            }
```

5. At the start of `begin_run`'s body, right after `self._ensure_operation()`:

```python
        self._close_compare_dialog()
        self.listening.clear()
        self._host.set_compare_available(False)
```

6. New methods (place them after `_on_open_output_folder`):

```python
    def _on_input_finished(
        self,
        paths: tuple[str, ...],
        generated: tuple[str, ...],
        _error: BaseException | None,
        reference: str | None,
    ) -> None:
        from core.listening import build_comparison_set

        if not paths or not generated:
            return
        source = paths[0]
        planned = self._run_planned_outputs.get(os.path.abspath(source), ())
        cset = build_comparison_set(source, reference, generated, planned)
        if cset is not None:
            self.listening.add(cset)

    def compare_ready(self) -> bool:
        return bool(self.listening) and playback_unavailable_reason() is None

    def open_compare(self) -> None:
        if not self.compare_ready():
            return
        if self._compare_dialog is not None:
            self._compare_dialog.present(self._host.dialog_parent)
            return
        from .playback.dialog import CompareDialog
        from .playback.engine import PlaybackEngine

        self._compare_dialog = CompareDialog(
            self.listening.sets(),
            PlaybackEngine(),
            output_dir=self._run_output_dir,
            on_toast=self._host.toast,
            on_closed=self._on_compare_closed,
        )
        self._compare_dialog.present(self._host.dialog_parent)

    def _on_compare_closed(self) -> None:
        self._compare_dialog = None

    def _close_compare_dialog(self) -> None:
        dialog, self._compare_dialog = self._compare_dialog, None
        if dialog is not None:
            dialog.close()

    def _on_compare_toast(self, _toast: Adw.Toast) -> None:
        self.open_compare()
```

`test_open_compare_presents_one_dialog` patches `ui.playback.dialog.CompareDialog` and `ui.playback.engine.PlaybackEngine`; the function-local imports above resolve those patched names at call time.

7. Replace `_show_complete_toast`:

```python
    def _show_complete_toast(self, output_dir: str) -> None:
        toast = Adw.Toast.new("Process complete.")
        if self.compare_ready():
            toast.set_button_label(_COMPARE_LABEL)
            toast.connect("button-clicked", self._on_compare_toast)
        elif output_dir and os.path.isdir(output_dir):
            toast.set_button_label(_OPEN_FOLDER_LABEL)
            toast.connect("button-clicked", self._on_open_output_folder, output_dir)
        self._host.add_toast(toast)
```

8. In `_on_complete`, directly after `self._show_complete_toast(output_dir)`:

```python
        self._host.set_compare_available(self.compare_ready())
```

9. Replace `_on_stopped`'s toast block:

```python
        exported = self._host.exported_after_oom()
        self._finish_run_ui(stopped=True)
        ready = self.compare_ready()
        self._host.set_compare_available(ready)
        if exported:
            toast = Adw.Toast.new("Exported completed ensemble outputs.")
            output_dir = self._run_output_dir
            if ready:
                toast.set_button_label(_COMPARE_LABEL)
                toast.connect("button-clicked", self._on_compare_toast)
            elif output_dir and os.path.isdir(output_dir):
                toast.set_button_label(_OPEN_FOLDER_LABEL)
                toast.connect("button-clicked", self._on_open_output_folder, output_dir)
            self._host.add_toast(toast)
        elif ready:
            toast = Adw.Toast.new(_PROGRESS_STOPPED_TOAST)
            toast.set_button_label(_COMPARE_LABEL)
            toast.connect("button-clicked", self._on_compare_toast)
            self._host.add_toast(toast)
```

10. Shutdown: find the controller's close path with `rg -n "def _complete_shutdown|def shutdown|_closing = True" ui/run_control.py`, and call `self._close_compare_dialog()` at the start of `_complete_shutdown`.

- [ ] **Step 7: Run the new and existing controller tests**

```bash
.venv/bin/python -m unittest tests.test_compare_run_integration tests.test_run_control tests.test_run_callback_guards tests.test_dispatch tests.test_ui_boundaries -v
```

Expected: all PASS. If `tests.test_ui_boundaries` flags `ui.run_control` importing `ui.playback.engine`, confirm the rule it enforces. The engine module is GStreamer-free at import time, so add it to that test's allow-list with a comment, rather than moving the import into a function.

Existing tests that call `_show_complete_toast` or `_on_stopped` with a `mock.Mock()` window now also see `set_compare_available` calls on the mock. That is harmless; do not change those tests.

- [ ] **Step 8: Lint, format and commit**

```bash
.venv/bin/ruff format ui/playback/session.py ui/dispatch.py ui/protocols.py ui/run_host.py ui/window.py ui/run_control.py tests/test_compare_run_integration.py
.venv/bin/ruff check ui/playback/session.py ui/dispatch.py ui/protocols.py ui/run_host.py ui/window.py ui/run_control.py tests/test_compare_run_integration.py
./resources/compile_resources.sh --check
git add ui/playback/session.py ui/dispatch.py ui/protocols.py ui/run_host.py ui/window.py ui/run_control.py resources/ui/main-header.blp resources/ui/main-header.ui ui/data/uvr.gresource tests/test_compare_run_integration.py
git commit -m "feat(ui): offer stem comparison after runs"
```

---

### Task 6: Dependencies, CI, docs and full verification

**Files:**
- Modify: `install_packages.sh:116-131`, `.github/workflows/test.yml:50` and `:140`, `README.md` (distro blocks at the "Install system packages manually" section, troubleshooting table at `README.md:196-203`, Highlights list), `docs/tracked-issues.md` (Product gaps table)

**Interfaces:**
- Consumes: everything above.
- Produces: installed GStreamer packages in the installer and CI; user docs.

- [ ] **Step 1: Installer packages**

In `install_packages.sh` `install_system_deps`, append to each package list:
- apt: `gir1.2-gstreamer-1.0 gstreamer1.0-plugins-base gstreamer1.0-plugins-good`
- dnf: `gstreamer1 gstreamer1-plugins-base gstreamer1-plugins-good`
- pacman: `gstreamer gst-plugins-base gst-plugins-good`
- zypper: `typelib-1_0-Gst-1_0 gstreamer-plugins-base gstreamer-plugins-good`

Run: `bash -n install_packages.sh`
Expected: no output (the syntax is valid).

- [ ] **Step 2: CI packages**

In both `pkgs=(...)` arrays in `.github/workflows/test.yml` (lines 50 and 140), append `gir1.2-gstreamer-1.0 gstreamer1.0-plugins-base gstreamer1.0-plugins-good`.

The Ubuntu runner has no sound card. `autoaudiosink` is only found, not opened, by `playback_unavailable_reason()`, and the engine tests use `fakesink`, so no audio device is needed.

- [ ] **Step 3: README**

- Add the same package names to each distro `<details>` block under "Install system packages manually" (`README.md` Debian/Fedora/Arch/openSUSE blocks).
- Add a Highlights bullet after the Download Center bullet: `- Listen to the results inside the app and switch between stems at the same moment.`
- Add a troubleshooting row after the Rubber Band row:

```markdown
| No **Compare** button after a run | Install GStreamer's GI bindings plus base and good plugins (for example `gir1.2-gstreamer-1.0 gstreamer1.0-plugins-base gstreamer1.0-plugins-good`) and restart the app |
```

- [ ] **Step 4: Tracked issues**

In `docs/tracked-issues.md` "Product gaps (roadmap)", add a row after P3:

```markdown
| **P4** | In-app listening / stem comparison | done | medium | — | — | Latest run's outputs play in a "Compare stems" dialog with gapless switching over one GStreamer `audiomixer` pipeline ([ui/playback/](../ui/playback/)); core reports outputs through `JobCallbacks.input_finished` ([core/listening.py](../core/listening.py)). Optional dependency: GStreamer base/good plugins. |
```

Update the `*Last reviewed:*` line's date to the implementation date and prepend `P4 added and closed by in-app stem comparison;`.

- [ ] **Step 5: Full verification**

```bash
.venv/bin/ruff check .
.venv/bin/ruff format --check .
.venv/bin/python -m basedpyright
./resources/compile_resources.sh --check
env -u DISPLAY -u WAYLAND_DISPLAY -u DBUS_SESSION_BUS_ADDRESS -u DBUS_SYSTEM_BUS_ADDRESS -u XDG_RUNTIME_DIR -u XAUTHORITY -u SESSION_MANAGER -u UVR_REQUIRE_PRIVATE_GTK GDK_BACKEND=x11 GSK_RENDERER=cairo xvfb-run -a -s "-screen 0 1920x1080x24" .venv/bin/python -m unittest discover -s tests -t .
```

Expected: ruff clean, basedpyright `0 errors, 0 warnings, 0 notes`, and the resource check passes. The full suite reports `OK` with the same skip count as before this work (2 at the time of planning). The new engine tests must run, not skip, because GStreamer is installed locally.

- [ ] **Step 6: Manual smoke check in the real app**

Launch with `./run_uvr.sh`. Separate a short file with any installed MDX model, then:
1. The "Process complete." toast shows **Compare**. Click it.
2. The dialog lists Original, then the stems. Press Space: audio plays. Press 1, 2, 3: the audible track changes with no gap, and the time label keeps running.
3. Press ← / →: position moves by 5 s.
4. Close the dialog: audio stops. The header shows the play-icon button; clicking it reopens the dialog.
5. Start another run: the header button disappears.

Record the result in the commit message body (for example "Smoke-tested: MDX single file, 2 stems").

- [ ] **Step 7: Commit**

```bash
git add install_packages.sh .github/workflows/test.yml README.md docs/tracked-issues.md
git commit -m "docs: GStreamer dependency and stem comparison notes"
```
