# Local Model Sweep Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A local-only script that starts a real separation run for every model installed on this machine and reports which ones fail.

**Architecture:** `scripts/model_sweep.py` is both parent and child. The parent discovers jobs from disk, then runs each in its own subprocess **serially** (`subprocess.run` in a loop — one child alive at a time, peak memory equals one normal run). The child builds `Settings`, drives one job through `core.headless_run`, and writes `result.json`. Discovery, classification and reporting are pure functions so they can be unit-tested in CI without models or torch.

**Tech Stack:** Python 3.14, stdlib `unittest`, `subprocess`, `argparse`; `soundfile` + `numpy` for the input clip; existing `core` / `engines` APIs.

**Spec:** [docs/superpowers/specs/2026-07-31-local-model-sweep-design.md](../specs/2026-07-31-local-model-sweep-design.md)

## Global Constraints

- **No tkinter anywhere.** Never import `ui` (and therefore GTK) from `core`, `scripts`, or the sweep.
- **Layering:** `ui` → `core` → `engines` → `ml`; `bundled` is read by all.
- **Heavy imports stay lazy.** The sweep parent must not import `torch`, `onnxruntime`, or `engines`. Verify with `'torch' in sys.modules`. `core`, `core.model_data` and `core.apollo` are torch-free today — keep it that way.
- **Tests are stdlib `unittest`.** No pytest. Run with `.venv/bin/python -m unittest ...`.
- **Pyright `basic` must pass:** `.venv/bin/python -m pyright` → `0 errors`. `scripts/` is inside the checked roots.
- **`set_flat` silently no-ops on keys missing from `FLAT_TO_PATH`.** Every flat key used here was verified present in `core/settings/flat_map.py`; if you add one, add the mapping first.
- **Enum settings:** `process.method` is a `str, Enum`. Use `.value` when building a path or log line; never `str(v)` or f-string interpolation.
- **Search with `rg`**, not `grep`.
- **Never** run unscoped `git checkout -- .`, `git restore .`, `git reset --hard`, `git stash`, or `git clean`. This tree carries long-lived uncommitted edits under `models/*/model_data/`. Stage explicit paths; never `git add -A`.
- Upstream's `Seperate*` misspelling is the real prefix. Keep it.
- Commit messages end with:
  `Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>`

**Before Task 1:** the working branch is `main`. Create a feature branch first:

```bash
git switch -c feat/local-model-sweep
```

---

### Task 1: Make the sweep's helpers importable without GTK or torch

The sweep needs typed setting writes and OOM-message classification. Today the first lives in `ui/` (pulls GTK) and the second is behind `engines/__init__.py` (pulls torch). Move both down, leaving re-exports so every existing call site keeps working.

**Files:**
- Create: `core/settings/access.py`
- Create: `core/oom_markers.py`
- Modify: `ui/settings_bind.py` (whole file → re-exports)
- Modify: `engines/mdx_classic_batch.py:56-73` (markers + `is_oom_message` → re-export from core)
- Test: `tests/test_settings_access.py` (create)

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces:
  - `core.settings.access.get_path(settings: Settings, path: str, default: Any = _MISSING) -> Any`
  - `core.settings.access.set_path(settings: Settings, path: str, value: Any) -> None`
  - `core.settings.access.get_flat(settings: Settings, key: str, default: Any = None) -> Any`
  - `core.settings.access.set_flat(settings: Settings, key: str, value: Any) -> None`
  - `core.oom_markers.is_oom_message(text: str | None) -> bool`

- [ ] **Step 1: Write the failing test**

Create `tests/test_settings_access.py`:

```python
"""The typed-settings accessors and OOM matcher must import without GTK/torch."""

import subprocess
import sys
import unittest

from core.oom_markers import is_oom_message
from core.settings import Settings
from core.settings.access import get_flat, get_path, set_flat, set_path


class SettingsAccessTests(unittest.TestCase):
    def test_set_path_coerces_value(self) -> None:
        settings = Settings()
        set_path(settings, "mdx.segment_size", "512")
        self.assertEqual(settings.mdx.segment_size, 512)

    def test_get_path_returns_default_for_missing(self) -> None:
        settings = Settings()
        self.assertEqual(get_path(settings, "mdx.nope", "fallback"), "fallback")

    def test_flat_bridge_round_trips(self) -> None:
        settings = Settings()
        set_flat(settings, "is_gpu_conversion", True)
        self.assertTrue(settings.process.use_gpu)
        self.assertTrue(get_flat(settings, "is_gpu_conversion"))

    def test_set_flat_ignores_unmapped_key(self) -> None:
        settings = Settings()
        before = settings.process.use_gpu
        set_flat(settings, "not_a_real_key", 1)  # documented no-op
        self.assertEqual(settings.process.use_gpu, before)

    def test_ui_bridge_still_exports_the_same_objects(self) -> None:
        import ui.settings_bind as bridge

        self.assertIs(bridge.set_flat, set_flat)
        self.assertIs(bridge.get_path, get_path)


class ImportWeightTests(unittest.TestCase):
    def test_helpers_import_without_torch(self) -> None:
        code = (
            "import sys;"
            "import core.oom_markers, core.settings.access;"
            "print('torch' in sys.modules)"
        )
        out = subprocess.run(
            [sys.executable, "-c", code], capture_output=True, text=True, check=True
        )
        self.assertEqual(out.stdout.strip(), "False")


class OomMarkerTests(unittest.TestCase):
    def test_matches_cuda_message(self) -> None:
        self.assertTrue(is_oom_message("CUDA out of memory. Tried to allocate 2 GiB"))

    def test_matches_ort_message(self) -> None:
        self.assertTrue(is_oom_message("Failed to allocate memory for requested buffer"))

    def test_rejects_unrelated_message(self) -> None:
        self.assertFalse(is_oom_message("shape mismatch in layer 3"))

    def test_engines_module_still_re_exports(self) -> None:
        from engines.mdx_classic_batch import is_oom_message as engines_matcher

        self.assertIs(engines_matcher, is_oom_message)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m unittest tests.test_settings_access -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'core.oom_markers'`

- [ ] **Step 3: Create `core/oom_markers.py`**

```python
"""GPU out-of-memory message matching, free of torch / ORT imports.

Lives in ``core`` so tools that must not import the engine stack (and with it
torch) can classify an OOM failure. ``engines.mdx_classic_batch`` re-exports it
for the batch-size backoff.
"""

from __future__ import annotations

_OOM_MARKERS = (
    "out of memory",
    "cuda_error_out_of_memory",
    "cudamalloc failed",
    "failed to allocate memory",
)


def is_oom_message(text: str | None) -> bool:
    """Whether an exception message indicates a GPU memory allocation failure.

    ``onnxruntime`` reports CUDA OOM through its own ``Fail``/``RuntimeException``
    types rather than ``torch.cuda.OutOfMemoryError``, so callers that also run
    ORT sessions need a message-based check to trigger the batch-size backoff
    without swallowing unrelated ORT errors.
    """
    lowered = (text or "").lower()
    return any(marker in lowered for marker in _OOM_MARKERS)
```

- [ ] **Step 4: Re-export from `engines/mdx_classic_batch.py`**

Delete the `_OOM_MARKERS` tuple and the `is_oom_message` body (currently lines 56-73) and put this near the top imports instead:

```python
from core.oom_markers import _OOM_MARKERS, is_oom_message  # noqa: F401  (re-export)
```

Keep `next_batch_after_oom` where it is. `engines/model_weight_cache.py` already imports from `core`, so this direction is established.

- [ ] **Step 5: Create `core/settings/access.py`**

Move the four functions out of `ui/settings_bind.py` verbatim — same bodies, same `_MISSING` sentinel:

```python
"""Typed-settings access helpers (nested paths and the legacy flat bridge).

Framework-agnostic: lives in ``core`` so headless tools can write settings
without importing the GTK layer. ``ui.settings_bind`` re-exports these.
"""

from __future__ import annotations

from typing import Any

from core.settings import Settings
from core.settings.coerce import coerce_field
from core.settings.flat_map import FLAT_TO_PATH

_MISSING = object()


def get_path(settings: Settings, path: str, default: Any = _MISSING) -> Any:
    """Read a ``section.field`` path from nested :class:`Settings`."""
    try:
        section_name, field_name = path.split(".", 1)
        return getattr(getattr(settings, section_name), field_name)
    except (AttributeError, ValueError):
        if default is _MISSING:
            raise
        return default


def set_path(settings: Settings, path: str, value: Any) -> None:
    """Write a ``section.field`` path on nested :class:`Settings`."""
    section_name, field_name = path.split(".", 1)
    setattr(
        getattr(settings, section_name),
        field_name,
        coerce_field(section_name, field_name, value),
    )


def get_flat(settings: Settings, key: str, default: Any = None) -> Any:
    """Read a legacy flat key through :data:`FLAT_TO_PATH`."""
    path = FLAT_TO_PATH.get(key)
    if path is None:
        return default
    return get_path(settings, ".".join(path), default)


def set_flat(settings: Settings, key: str, value: Any) -> None:
    """Write a legacy flat key through :data:`FLAT_TO_PATH`."""
    path = FLAT_TO_PATH.get(key)
    if path is not None:
        set_path(settings, ".".join(path), value)
```

- [ ] **Step 6: Reduce `ui/settings_bind.py` to re-exports**

Replace the entire file with:

```python
"""Small typed-settings access helpers for dynamic UI bindings.

The implementations live in :mod:`core.settings.access` so headless callers can
use them without importing GTK. Re-exported here for existing UI call sites.
"""

from __future__ import annotations

from core.settings.access import _MISSING, get_flat, get_path, set_flat, set_path

__all__ = ["_MISSING", "get_flat", "get_path", "set_flat", "set_path"]
```

- [ ] **Step 7: Run the new test plus everything that touches these helpers**

```bash
.venv/bin/python -m unittest tests.test_settings_access tests.test_mdx_classic_batch -v
```
Expected: PASS

- [ ] **Step 8: Run the full suite and pyright**

```bash
xvfb-run -a .venv/bin/python -m unittest discover -s tests 2>&1 | tail -3
.venv/bin/python -m pyright 2>&1 | tail -3
```
Expected: `OK` (864+ tests, 1 skipped) and `0 errors`. The UI imports `set_flat`/`get_flat` from `ui.settings_bind` in many places — a failure here means a missed re-export.

- [ ] **Step 9: Commit**

```bash
git add core/oom_markers.py core/settings/access.py ui/settings_bind.py \
        engines/mdx_classic_batch.py tests/test_settings_access.py
git commit -m "$(cat <<'EOF'
refactor(core): move settings accessors and OOM matching out of ui/engines

Headless tools need typed setting writes and OOM classification without
importing GTK (ui.settings_bind) or torch (engines/__init__). Both move to
core with re-exports at the old locations.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: Headless ensemble support

`build_settings` and `run_separation_sync` both hard-reject `ENSEMBLE_MODE` (`core/headless_run.py:361-366` and `:411-413`). The ensemble composite job needs a supported path.

**Files:**
- Modify: `core/headless_run.py` (add `allow_ensemble` param; extract `_run_job`; add `run_ensemble_sync`)
- Test: `tests/test_headless_ensemble.py` (create)

**Interfaces:**
- Consumes: nothing from Task 1.
- Produces:
  - `core.headless_run.build_settings(..., allow_ensemble: bool = False) -> Settings`
  - `core.headless_run.run_ensemble_sync(settings: Settings, input_paths: Sequence[str], *, print_console: bool = True, join_timeout: Optional[float] = None) -> HeadlessResult`
  - `HeadlessResult` is unchanged: `.ok`, `.elapsed_s`, `.export_path`, `.error`, `.stopped`, `.console`

- [ ] **Step 1: Write the failing test**

Create `tests/test_headless_ensemble.py`. The fake runner stands in for `JobRunner`, so no models or torch are needed:

```python
"""Headless ensemble entry point (no models, no torch — JobRunner is faked)."""

import unittest
from typing import Any, List, Optional, Sequence
from unittest import mock

from bundled.constants import ENSEMBLE_MODE
from core.headless_run import build_settings, run_ensemble_sync
from core.settings import Settings
from core.types import ProcessMethod


class _FakeRunner:
    """Records which start method was used and fires callbacks synchronously."""

    calls: List[str] = []

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._thread = None
        self.error: Optional[BaseException] = None

    def is_running(self) -> bool:
        return False

    def start(self, input_paths: Sequence[str], callbacks: Any) -> None:
        _FakeRunner.calls.append("single")
        callbacks.complete()

    def start_ensemble(self, input_paths: Sequence[str], callbacks: Any) -> None:
        _FakeRunner.calls.append("ensemble")
        callbacks.console("combining\n")
        if self.error is not None:
            callbacks.error(self.error)
        else:
            callbacks.complete()

    def release_inference_memory(self, **kwargs: Any) -> None:
        pass

    def stop(self, **kwargs: Any) -> None:
        pass


class RunEnsembleSyncTests(unittest.TestCase):
    def setUp(self) -> None:
        _FakeRunner.calls = []
        self.settings = Settings()
        self.settings.process.method = ProcessMethod(ENSEMBLE_MODE)
        self.settings.process.export_path = "/tmp/sweep-export"

    def test_uses_start_ensemble(self) -> None:
        with mock.patch("core.headless_run.JobRunner", _FakeRunner):
            result = run_ensemble_sync(self.settings, ["/tmp/in.wav"], print_console=False)
        self.assertEqual(_FakeRunner.calls, ["ensemble"])
        self.assertTrue(result.ok)
        self.assertIn("combining\n", result.console)

    def test_reports_error(self) -> None:
        boom = RuntimeError("member failed")

        def factory(settings: Settings) -> _FakeRunner:
            runner = _FakeRunner(settings)
            runner.error = boom
            return runner

        with mock.patch("core.headless_run.JobRunner", factory):
            result = run_ensemble_sync(self.settings, ["/tmp/in.wav"], print_console=False)
        self.assertFalse(result.ok)
        self.assertIs(result.error, boom)

    def test_requires_input_paths(self) -> None:
        with self.assertRaises(ValueError):
            run_ensemble_sync(self.settings, [], print_console=False)

    def test_requires_export_path(self) -> None:
        self.settings.process.export_path = ""
        with self.assertRaises(ValueError):
            run_ensemble_sync(self.settings, ["/tmp/in.wav"], print_console=False)


class BuildSettingsEnsembleTests(unittest.TestCase):
    def test_rejects_ensemble_by_default(self) -> None:
        settings = Settings()
        settings.process.method = ProcessMethod(ENSEMBLE_MODE)
        with mock.patch("core.headless_run.Settings.load", return_value=settings):
            with self.assertRaises(ValueError):
                build_settings(export_path="/tmp/out")

    def test_allows_ensemble_when_opted_in(self) -> None:
        settings = Settings()
        settings.process.method = ProcessMethod(ENSEMBLE_MODE)
        with mock.patch("core.headless_run.Settings.load", return_value=settings):
            built = build_settings(export_path="/tmp/out", allow_ensemble=True)
        self.assertEqual(built.process.method, ENSEMBLE_MODE)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m unittest tests.test_headless_ensemble -v`
Expected: FAIL — `ImportError: cannot import name 'run_ensemble_sync'`

- [ ] **Step 3: Add `allow_ensemble` to `build_settings`**

In `core/headless_run.py`, add the keyword to the signature (after `repo`):

```python
    allow_ensemble: bool = False,
```

and gate the existing rejection:

```python
    chosen = settings.process.method
    if chosen == ENSEMBLE_MODE and not allow_ensemble:
        raise ValueError(
            "ensemble mode is not supported by the headless CLI (v1); "
            "pass --method mdx|demucs|vr"
        )
```

- [ ] **Step 4: Extract `_run_job` and add `run_ensemble_sync`**

Replace the body of `run_separation_sync` with a delegation, and move the existing machinery into `_run_job` unchanged apart from the `start_fn` indirection:

```python
def _run_job(
    settings: Settings,
    input_paths: Sequence[str],
    *,
    start_attr: str,
    print_console: bool,
    join_timeout: Optional[float],
) -> HeadlessResult:
    """Start ``JobRunner.<start_attr>`` and block until complete / error / stop."""
    if not input_paths:
        raise ValueError("at least one input path is required")

    export_path = str(settings.process.export_path or "")
    if not export_path:
        raise ValueError("export_path is empty; pass -o/--output")

    console_lines: list[str] = []
    error_box: list[BaseException] = []
    done = threading.Event()
    outcome = {"stopped": False}

    def on_console(text: str) -> None:
        console_lines.append(text)
        if print_console:
            sys.stdout.write(text if text.endswith("\n") else text + "\n")
            sys.stdout.flush()

    def on_complete() -> None:
        done.set()

    def on_stopped() -> None:
        outcome["stopped"] = True
        done.set()

    def on_error(exc: BaseException) -> None:
        error_box.append(exc)
        done.set()

    callbacks = JobCallbacks(
        on_console=on_console,
        on_complete=on_complete,
        on_stopped=on_stopped,
        on_error=on_error,
    )

    runner = JobRunner(settings)
    started = time.perf_counter()
    try:
        getattr(runner, start_attr)(list(input_paths), callbacks)
        while not done.wait(timeout=0.25):
            if not runner.is_running() and not done.is_set():
                # Worker exited without signaling (unexpected).
                done.set()
                break
            if join_timeout is not None and (time.perf_counter() - started) > join_timeout:
                runner.stop(force=True)
                raise TimeoutError(f"separation exceeded {join_timeout:.0f}s")
    except KeyboardInterrupt:
        runner.stop(force=True)
        done.wait(timeout=5.0)
        raise
    finally:
        thread = getattr(runner, "_thread", None)
        if thread is not None and thread.is_alive():
            thread.join(timeout=join_timeout if join_timeout else None)
        try:
            runner.release_inference_memory(clear_weight_cache=False)
        except Exception:
            # Best-effort: never mask the original start/run failure.
            pass

    elapsed = time.perf_counter() - started
    err = error_box[0] if error_box else None
    ok = err is None and not outcome["stopped"]
    return HeadlessResult(
        ok=ok,
        elapsed_s=elapsed,
        export_path=export_path,
        error=err,
        stopped=bool(outcome["stopped"]),
        console=console_lines,
    )


def run_separation_sync(
    settings: Settings,
    input_paths: Sequence[str],
    *,
    print_console: bool = True,
    join_timeout: Optional[float] = None,
) -> HeadlessResult:
    """Start :class:`JobRunner` and block until complete / error / stop."""
    if settings.process.method == ENSEMBLE_MODE:
        raise ValueError("ensemble mode requires run_ensemble_sync")
    return _run_job(
        settings,
        input_paths,
        start_attr="start",
        print_console=print_console,
        join_timeout=join_timeout,
    )


def run_ensemble_sync(
    settings: Settings,
    input_paths: Sequence[str],
    *,
    print_console: bool = True,
    join_timeout: Optional[float] = None,
) -> HeadlessResult:
    """Run an ensemble through :meth:`JobRunner.start_ensemble` and block."""
    return _run_job(
        settings,
        input_paths,
        start_attr="start_ensemble",
        print_console=print_console,
        join_timeout=join_timeout,
    )
```

Note the guard in `run_separation_sync` changed wording; that path is now unreachable from the CLI, which still rejects ensembles earlier in `build_settings`.

- [ ] **Step 5: Run the tests**

```bash
.venv/bin/python -m unittest tests.test_headless_ensemble tests.test_cli_headless -v
```
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add core/headless_run.py tests/test_headless_ensemble.py
git commit -m "$(cat <<'EOF'
feat(core): add run_ensemble_sync to the headless runner

Extracts the shared callback/wait/cleanup plumbing out of
run_separation_sync into _run_job and adds an ensemble entry point, plus an
allow_ensemble opt-in on build_settings. Needed to drive ensemble runs
headlessly; the CLI surface is unchanged.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 3: Job model and discovery (pure)

**Files:**
- Create: `scripts/model_sweep.py`
- Test: `tests/test_model_sweep.py` (create)

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces:
  - `SweepJob` frozen dataclass: `id: str`, `kind: str` (`"single" | "ensemble" | "tool" | "skip"`), `method: Optional[str]`, `model: Optional[str]`, `overrides: dict[str, Any]`, `timeout: float`, `detail: str`
  - `Installed` frozen dataclass: `mdx: list[str]`, `vr: list[str]`, `demucs: list[str]`, `apollo: list[str]`, `ensemble_tags: list[str]`, `karaoke_tags: list[str]`
  - `discover_jobs(installed: Installed, *, methods: set[str], only: str = "", skip: frozenset[str] = frozenset()) -> list[SweepJob]`
  - `collect_installed(repo: Any, settings: Any) -> Installed`
  - Constants `KIND_SINGLE`, `KIND_ENSEMBLE`, `KIND_TOOL`, `KIND_SKIP`

- [ ] **Step 1: Write the failing test**

Create `tests/test_model_sweep.py`:

```python
"""Pure-helper tests for the local model sweep. No models, no torch."""

import importlib.util
import os
import unittest

_SPEC = importlib.util.spec_from_file_location(
    "model_sweep",
    os.path.join(os.path.dirname(os.path.dirname(__file__)), "scripts", "model_sweep.py"),
)
assert _SPEC is not None and _SPEC.loader is not None
model_sweep = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(model_sweep)


def _installed(**kwargs):
    base = dict(mdx=[], vr=[], demucs=[], apollo=[], ensemble_tags=[], karaoke_tags=[])
    base.update(kwargs)
    return model_sweep.Installed(**base)


class DiscoveryTests(unittest.TestCase):
    ALL = {"mdx", "vr", "demucs", "apollo", "composite"}

    def test_one_job_per_installed_weight(self) -> None:
        installed = _installed(
            mdx=["a.ckpt", "b.onnx"], vr=["v.pth"], demucs=["hdemucs_mmi.yaml"]
        )
        jobs = model_sweep.discover_jobs(installed, methods={"mdx", "vr", "demucs"})
        self.assertEqual(
            [(j.method, j.model) for j in jobs],
            [
                ("mdx", "a.ckpt"),
                ("mdx", "b.onnx"),
                ("vr", "v.pth"),
                ("demucs", "hdemucs_mmi.yaml"),
            ],
        )
        self.assertTrue(all(j.kind == model_sweep.KIND_SINGLE for j in jobs))

    def test_method_filter_excludes_others(self) -> None:
        installed = _installed(mdx=["a.ckpt"], vr=["v.pth"])
        jobs = model_sweep.discover_jobs(installed, methods={"vr"})
        self.assertEqual([j.model for j in jobs], ["v.pth"])

    def test_only_filter_is_substring_match(self) -> None:
        installed = _installed(mdx=["roformer_inst.ckpt", "mdx23c.ckpt"])
        jobs = model_sweep.discover_jobs(installed, methods={"mdx"}, only="roformer")
        self.assertEqual([j.model for j in jobs], ["roformer_inst.ckpt"])

    def test_skip_filter_drops_named_model(self) -> None:
        installed = _installed(mdx=["a.ckpt", "b.ckpt"])
        jobs = model_sweep.discover_jobs(
            installed, methods={"mdx"}, skip=frozenset({"a.ckpt"})
        )
        self.assertEqual([j.model for j in jobs], ["b.ckpt"])

    def test_apollo_models_become_tool_jobs(self) -> None:
        installed = _installed(apollo=["apollo_universal_model.ckpt"])
        jobs = model_sweep.discover_jobs(installed, methods={"apollo"})
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0].kind, model_sweep.KIND_TOOL)
        self.assertEqual(
            jobs[0].overrides["audio_tools.apollo_model"], "apollo_universal_model.ckpt"
        )

    def test_ensemble_composite_uses_two_member_tags(self) -> None:
        installed = _installed(
            mdx=["a.ckpt", "b.ckpt"],
            ensemble_tags=["MDX-Net: A", "MDX-Net: B", "MDX-Net: C"],
        )
        jobs = model_sweep.discover_jobs(installed, methods={"composite"})
        ensemble = [j for j in jobs if j.kind == model_sweep.KIND_ENSEMBLE]
        self.assertEqual(len(ensemble), 1)
        self.assertEqual(
            ensemble[0].overrides["selected_models"], ["MDX-Net: A", "MDX-Net: B"]
        )
        self.assertEqual(ensemble[0].overrides["ensemble_type"], "Max Spec/Min Spec")
        self.assertEqual(
            ensemble[0].overrides["ensemble_main_stem"], "Vocals/Instrumental"
        )
        self.assertFalse(ensemble[0].overrides["is_save_all_outputs_ensemble"])

    def test_ensemble_composite_skips_with_one_member(self) -> None:
        installed = _installed(mdx=["a.ckpt"], ensemble_tags=["MDX-Net: A"])
        jobs = model_sweep.discover_jobs(installed, methods={"composite"})
        ensemble = [j for j in jobs if j.id == "composite:ensemble"]
        self.assertEqual(len(ensemble), 1)
        self.assertEqual(ensemble[0].kind, model_sweep.KIND_SKIP)
        self.assertIn("two", ensemble[0].detail)

    def test_secondary_chain_composite_pairs_vr_with_mdx(self) -> None:
        installed = _installed(
            mdx=["m.ckpt"], vr=["v.pth"], ensemble_tags=["MDX-Net: M", "VR Arc: V"]
        )
        jobs = model_sweep.discover_jobs(installed, methods={"composite"})
        chain = next(j for j in jobs if j.id == "composite:secondary-chain")
        self.assertEqual(chain.method, "vr")
        self.assertEqual(chain.model, "v.pth")
        self.assertTrue(chain.overrides["vr_is_secondary_model_activate"])
        self.assertEqual(chain.overrides["vr_voc_inst_secondary_model"], "MDX-Net: M")
        self.assertEqual(chain.overrides["vr_voc_inst_secondary_model_scale"], 0.5)

    def test_vocal_splitter_composite_needs_a_karaoke_model(self) -> None:
        installed = _installed(mdx=["m.ckpt"], karaoke_tags=[])
        jobs = model_sweep.discover_jobs(installed, methods={"composite"})
        splitter = next(j for j in jobs if j.id == "composite:vocal-splitter")
        self.assertEqual(splitter.kind, model_sweep.KIND_SKIP)

    def test_job_ids_are_unique(self) -> None:
        installed = _installed(
            mdx=["a.ckpt", "b.ckpt"],
            vr=["v.pth"],
            demucs=["d.yaml"],
            apollo=["ap.ckpt"],
            ensemble_tags=["MDX-Net: A", "MDX-Net: B"],
            karaoke_tags=["MDX-Net: K"],
        )
        jobs = model_sweep.discover_jobs(installed, methods=self.ALL)
        ids = [j.id for j in jobs]
        self.assertEqual(len(ids), len(set(ids)))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m unittest tests.test_model_sweep -v`
Expected: FAIL — `FileNotFoundError` on `scripts/model_sweep.py`

- [ ] **Step 3: Create `scripts/model_sweep.py` with the job model and discovery**

```python
#!/usr/bin/env python3
"""Local-only sweep: start a real run for every model installed on this machine.

Not part of CI — weights are gitignored, so this can only run where models
exist. The parent process discovers jobs and runs each one in its own
subprocess, serially. See docs/superpowers/specs/2026-07-31-local-model-sweep-design.md
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

KIND_SINGLE = "single"
KIND_ENSEMBLE = "ensemble"
KIND_TOOL = "tool"
KIND_SKIP = "skip"

DEFAULT_TIMEOUT = 300.0
ENSEMBLE_TIMEOUT = 900.0

# Literal values verified against bundled/constants/process.py.
MAX_MIN = "Max Spec/Min Spec"
VOCAL_PAIR = "Vocals/Instrumental"
APOLLO_RESTORE = "Apollo Restore"
ALL_STEMS = "All Stems"


@dataclass(frozen=True)
class SweepJob:
    """One unit of work: exactly one run, executed in its own subprocess."""

    id: str
    kind: str
    method: Optional[str] = None
    model: Optional[str] = None
    overrides: Dict[str, Any] = field(default_factory=dict)
    timeout: float = DEFAULT_TIMEOUT
    detail: str = ""


@dataclass(frozen=True)
class Installed:
    """What is actually present on this machine."""

    mdx: List[str]
    vr: List[str]
    demucs: List[str]
    apollo: List[str]
    ensemble_tags: List[str]
    karaoke_tags: List[str]


def collect_installed(repo: Any, settings: Any) -> Installed:
    """Read the model tree. Impure; ``discover_jobs`` stays testable without it."""
    from core.apollo import list_apollo_models
    from bundled.constants import INST_STEM, VOCAL_STEM

    return Installed(
        mdx=list(repo.list_mdx_models()),
        vr=list(repo.list_vr_models()),
        demucs=list(repo.list_demucs_models()),
        apollo=list(list_apollo_models()),
        ensemble_tags=list(repo.model_list(settings, VOCAL_STEM, INST_STEM)),
        karaoke_tags=list(repo.karaoke_model_list(settings)),
    )


def _wanted(name: str, only: str, skip: frozenset) -> bool:
    if name in skip:
        return False
    return only.lower() in name.lower() if only else True


def discover_jobs(
    installed: Installed,
    *,
    methods: set,
    only: str = "",
    skip: frozenset = frozenset(),
) -> List[SweepJob]:
    """Build the job list from what is installed. Pure: lists in, jobs out."""
    jobs: List[SweepJob] = []

    for method, names in (
        ("mdx", installed.mdx),
        ("vr", installed.vr),
        ("demucs", installed.demucs),
    ):
        if method not in methods:
            continue
        for name in names:
            if not _wanted(name, only, skip):
                continue
            jobs.append(
                SweepJob(id=f"{method}:{name}", kind=KIND_SINGLE, method=method, model=name)
            )

    if "apollo" in methods:
        for name in installed.apollo:
            if not _wanted(name, only, skip):
                continue
            jobs.append(
                SweepJob(
                    id=f"apollo:{name}",
                    kind=KIND_TOOL,
                    overrides={
                        "audio_tools.apollo_model": name,
                        "audio_tools.chosen_audio_tool": APOLLO_RESTORE,
                    },
                )
            )

    if "composite" in methods:
        jobs.extend(_composite_jobs(installed))

    return jobs


def _skip(job_id: str, reason: str) -> SweepJob:
    return SweepJob(id=job_id, kind=KIND_SKIP, detail=reason)


def _composite_jobs(installed: Installed) -> List[SweepJob]:
    """Multi-pass shapes single-model runs never reach."""
    jobs: List[SweepJob] = []

    # 1. Four-stem export.
    four_stem = next((n for n in installed.demucs if "hdemucs_mmi" in n), None)
    if four_stem is not None:
        jobs.append(
            SweepJob(
                id="composite:4-stem",
                kind=KIND_SINGLE,
                method="demucs",
                model=four_stem,
                overrides={"demucs_stems": ALL_STEMS},
            )
        )
    else:
        scnet = next((n for n in installed.mdx if "4stems" in n), None)
        if scnet is not None:
            jobs.append(
                SweepJob(
                    id="composite:4-stem",
                    kind=KIND_SINGLE,
                    method="mdx",
                    model=scnet,
                    overrides={"mdx_stems": ALL_STEMS},
                )
            )
        else:
            jobs.append(_skip("composite:4-stem", "no 4-stem model installed"))

    # 2. Two-member ensemble.
    if len(installed.ensemble_tags) >= 2:
        jobs.append(
            SweepJob(
                id="composite:ensemble",
                kind=KIND_ENSEMBLE,
                overrides={
                    "selected_models": installed.ensemble_tags[:2],
                    "ensemble_type": MAX_MIN,
                    "ensemble_main_stem": VOCAL_PAIR,
                    "is_save_all_outputs_ensemble": False,
                },
                timeout=ENSEMBLE_TIMEOUT,
            )
        )
    else:
        jobs.append(_skip("composite:ensemble", "needs two ensemble-capable models"))

    # 3. Primary + secondary chain.
    mdx_tag = next((t for t in installed.ensemble_tags if t.startswith("MDX-Net")), None)
    if installed.vr and mdx_tag is not None:
        jobs.append(
            SweepJob(
                id="composite:secondary-chain",
                kind=KIND_SINGLE,
                method="vr",
                model=installed.vr[0],
                overrides={
                    "vr_is_secondary_model_activate": True,
                    "vr_voc_inst_secondary_model": mdx_tag,
                    "vr_voc_inst_secondary_model_scale": 0.5,
                },
                timeout=ENSEMBLE_TIMEOUT,
            )
        )
    else:
        jobs.append(_skip("composite:secondary-chain", "needs a VR and an MDX model"))

    # 4. Vocal splitter chain.
    if installed.mdx and installed.karaoke_tags:
        jobs.append(
            SweepJob(
                id="composite:vocal-splitter",
                kind=KIND_SINGLE,
                method="mdx",
                model=installed.mdx[0],
                overrides={
                    "is_set_vocal_splitter": True,
                    "set_vocal_splitter": installed.karaoke_tags[0],
                    "is_save_inst_set_vocal_splitter": True,
                },
                timeout=ENSEMBLE_TIMEOUT,
            )
        )
    else:
        jobs.append(_skip("composite:vocal-splitter", "needs an MDX and a karaoke model"))

    return jobs
```

- [ ] **Step 4: Run the tests**

Run: `.venv/bin/python -m unittest tests.test_model_sweep -v`
Expected: PASS (all discovery tests)

- [ ] **Step 5: Commit**

```bash
git add scripts/model_sweep.py tests/test_model_sweep.py
git commit -m "$(cat <<'EOF'
feat(scripts): add model sweep job discovery

Pure discovery over what is installed on disk: one job per weight plus the
multi-pass composites (4-stem, ensemble, secondary chain, vocal splitter),
each degrading to a SKIP job when its models are absent.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 4: Verdict classification and reporting (pure)

**Files:**
- Modify: `scripts/model_sweep.py` (append)
- Test: `tests/test_model_sweep.py` (append a class)

**Interfaces:**
- Consumes: `SweepJob`, `KIND_SKIP` from Task 3.
- Produces:
  - `classify(*, exit_code: int, result: Optional[dict], timed_out: bool) -> tuple[str, str]` returning `(verdict, detail)`
  - `is_failure(verdict: str, *, strict: bool) -> bool`
  - `render_row(job_id: str, verdict: str, elapsed_s: float, detail: str) -> str`
  - `render_summary(verdicts: Sequence[str]) -> str`
  - Verdict constants: `PASS`, `NO_OUTPUT`, `TIMEOUT`, `OOM`, `OOM_CPU_OK`, `UNRECOGNIZED`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_model_sweep.py` (before the `if __name__` block):

```python
class ClassifyTests(unittest.TestCase):
    def _result(self, **kwargs):
        base = {
            "ok": True,
            "error_type": None,
            "message": "",
            "elapsed_s": 1.0,
            "outputs": [["/tmp/out/x (Vocals).wav", 1024]],
            "stopped": False,
            "unrecognized": False,
        }
        base.update(kwargs)
        return base

    def test_clean_run_with_output_passes(self) -> None:
        verdict, _ = model_sweep.classify(exit_code=0, result=self._result(), timed_out=False)
        self.assertEqual(verdict, model_sweep.PASS)

    def test_clean_run_without_output_is_no_output(self) -> None:
        verdict, _ = model_sweep.classify(
            exit_code=0, result=self._result(outputs=[]), timed_out=False
        )
        self.assertEqual(verdict, model_sweep.NO_OUTPUT)

    def test_exception_becomes_typed_failure(self) -> None:
        verdict, detail = model_sweep.classify(
            exit_code=1,
            result=self._result(
                ok=False,
                error_type="BeartypeCallHintParamViolation",
                message="parameter attn_dropout=0 violates type hint <class 'float'>",
                outputs=[],
            ),
            timed_out=False,
        )
        self.assertEqual(verdict, "FAIL(BeartypeCallHintParamViolation)")
        self.assertIn("attn_dropout", detail)

    def test_cuda_oom_is_classified_as_oom(self) -> None:
        verdict, _ = model_sweep.classify(
            exit_code=1,
            result=self._result(
                ok=False,
                error_type="OutOfMemoryError",
                message="CUDA out of memory. Tried to allocate 3.00 GiB",
                outputs=[],
            ),
            timed_out=False,
        )
        self.assertEqual(verdict, model_sweep.OOM)

    def test_ort_allocation_failure_is_oom(self) -> None:
        verdict, _ = model_sweep.classify(
            exit_code=1,
            result=self._result(
                ok=False,
                error_type="Fail",
                message="Failed to allocate memory for requested buffer of size 4",
                outputs=[],
            ),
            timed_out=False,
        )
        self.assertEqual(verdict, model_sweep.OOM)

    def test_missing_result_is_crash(self) -> None:
        verdict, _ = model_sweep.classify(exit_code=-11, result=None, timed_out=False)
        self.assertEqual(verdict, "CRASH(exit -11)")

    def test_timeout_wins_over_everything(self) -> None:
        verdict, _ = model_sweep.classify(exit_code=None, result=None, timed_out=True)
        self.assertEqual(verdict, model_sweep.TIMEOUT)

    def test_unrecognized_model_is_its_own_verdict(self) -> None:
        verdict, _ = model_sweep.classify(
            exit_code=0, result=self._result(unrecognized=True, outputs=[]), timed_out=False
        )
        self.assertEqual(verdict, model_sweep.UNRECOGNIZED)

    def test_detail_is_first_line_only(self) -> None:
        _, detail = model_sweep.classify(
            exit_code=1,
            result=self._result(
                ok=False, error_type="RuntimeError", message="line one\nline two", outputs=[]
            ),
            timed_out=False,
        )
        self.assertEqual(detail, "line one")


class FailurePolicyTests(unittest.TestCase):
    def test_pass_and_skip_are_not_failures(self) -> None:
        self.assertFalse(model_sweep.is_failure(model_sweep.PASS, strict=False))
        self.assertFalse(model_sweep.is_failure("SKIP(no model)", strict=False))

    def test_oom_cpu_ok_is_not_a_failure(self) -> None:
        self.assertFalse(model_sweep.is_failure(model_sweep.OOM_CPU_OK, strict=False))

    def test_bare_oom_is_a_failure(self) -> None:
        self.assertTrue(model_sweep.is_failure(model_sweep.OOM, strict=False))

    def test_unrecognized_only_fails_under_strict(self) -> None:
        self.assertFalse(model_sweep.is_failure(model_sweep.UNRECOGNIZED, strict=False))
        self.assertTrue(model_sweep.is_failure(model_sweep.UNRECOGNIZED, strict=True))

    def test_typed_failures_and_crashes_fail(self) -> None:
        self.assertTrue(model_sweep.is_failure("FAIL(RuntimeError)", strict=False))
        self.assertTrue(model_sweep.is_failure("CRASH(exit -11)", strict=False))
        self.assertTrue(model_sweep.is_failure(model_sweep.NO_OUTPUT, strict=False))
        self.assertTrue(model_sweep.is_failure(model_sweep.TIMEOUT, strict=False))


class RenderTests(unittest.TestCase):
    def test_row_contains_id_verdict_and_elapsed(self) -> None:
        row = model_sweep.render_row("mdx:a.ckpt", model_sweep.PASS, 12.5, "")
        self.assertIn("mdx:a.ckpt", row)
        self.assertIn("PASS", row)
        self.assertIn("12.5s", row)

    def test_summary_counts_each_verdict(self) -> None:
        summary = model_sweep.render_summary(
            [model_sweep.PASS, model_sweep.PASS, "FAIL(RuntimeError)"]
        )
        self.assertIn("2 passed", summary)
        self.assertIn("1 failed", summary)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m unittest tests.test_model_sweep.ClassifyTests -v`
Expected: FAIL — `AttributeError: module 'model_sweep' has no attribute 'classify'`

- [ ] **Step 3: Append the implementation to `scripts/model_sweep.py`**

```python
PASS = "PASS"
NO_OUTPUT = "NO_OUTPUT"
TIMEOUT = "TIMEOUT"
OOM = "OOM"
OOM_CPU_OK = "OOM(cpu-ok)"
UNRECOGNIZED = "UNRECOGNIZED"


def _first_line(text: str) -> str:
    return (text or "").strip().splitlines()[0] if (text or "").strip() else ""


def classify(
    *, exit_code: Optional[int], result: Optional[dict], timed_out: bool
) -> tuple:
    """Turn a child's exit code and result payload into a verdict + detail."""
    from core.oom_markers import is_oom_message

    if timed_out:
        return TIMEOUT, ""
    if result is None:
        return f"CRASH(exit {exit_code})", ""
    if result.get("unrecognized"):
        return UNRECOGNIZED, "model hash not in the metadata tables"

    error_type = result.get("error_type")
    message = str(result.get("message") or "")
    if error_type:
        detail = _first_line(message)
        if is_oom_message(message) or error_type == "OutOfMemoryError":
            return OOM, detail
        return f"FAIL({error_type})", detail
    if result.get("stopped"):
        return "FAIL(stopped)", "run stopped before completion"
    if not result.get("outputs"):
        return NO_OUTPUT, "run completed but wrote no audio"
    return PASS, ""


def is_failure(verdict: str, *, strict: bool) -> bool:
    """Whether a verdict should make the sweep exit non-zero."""
    if verdict in (PASS, OOM_CPU_OK) or verdict.startswith("SKIP"):
        return False
    if verdict == UNRECOGNIZED:
        return strict
    return True


def render_row(job_id: str, verdict: str, elapsed_s: float, detail: str) -> str:
    row = f"{job_id:<52.52} {verdict:<34.34} {elapsed_s:>7.1f}s"
    return f"{row}\n    {detail}" if detail else row


def render_summary(verdicts: Sequence[str]) -> str:
    passed = sum(1 for v in verdicts if v == PASS)
    skipped = sum(1 for v in verdicts if v.startswith("SKIP"))
    oom_ok = sum(1 for v in verdicts if v == OOM_CPU_OK)
    unrecognized = sum(1 for v in verdicts if v == UNRECOGNIZED)
    failed = len(verdicts) - passed - skipped - oom_ok - unrecognized
    parts = [f"{passed} passed", f"{failed} failed"]
    if oom_ok:
        parts.append(f"{oom_ok} OOM(cpu-ok)")
    if unrecognized:
        parts.append(f"{unrecognized} unrecognized")
    if skipped:
        parts.append(f"{skipped} skipped")
    return "  ".join(parts)
```

- [ ] **Step 4: Run the tests**

Run: `.venv/bin/python -m unittest tests.test_model_sweep -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add scripts/model_sweep.py tests/test_model_sweep.py
git commit -m "$(cat <<'EOF'
feat(scripts): classify sweep results into verdicts

Exit code plus the child's result payload map to PASS / FAIL(<Type>) /
NO_OUTPUT / TIMEOUT / CRASH / OOM / UNRECOGNIZED, reusing the shared OOM
matcher so ORT allocation failures are recognised alongside torch's.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 5: Scratch environment and input clip

**Files:**
- Modify: `scripts/model_sweep.py` (append)
- Test: `tests/test_model_sweep.py` (append a class)

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces:
  - `make_input_clip(path: str, *, seconds: float = 3.0, rate: int = 44100) -> str`
  - `prepare_scratch(root: str, *, models_dir: str, settings_src: Optional[str]) -> tuple[str, str]` returning `(data_dir, settings_path)`
  - `child_env(data_dir: str) -> dict[str, str]`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_model_sweep.py`:

```python
class ScratchEnvTests(unittest.TestCase):
    def test_clip_is_three_seconds_stereo(self) -> None:
        import tempfile

        import soundfile as sf

        with tempfile.TemporaryDirectory() as tmp:
            path = model_sweep.make_input_clip(os.path.join(tmp, "in.wav"))
            data, rate = sf.read(path)
        self.assertEqual(rate, 44100)
        self.assertEqual(data.shape[1], 2)
        self.assertEqual(data.shape[0], 44100 * 3)

    def test_clip_is_not_silent(self) -> None:
        import tempfile

        import soundfile as sf

        with tempfile.TemporaryDirectory() as tmp:
            path = model_sweep.make_input_clip(os.path.join(tmp, "in.wav"))
            data, _ = sf.read(path)
        self.assertGreater(abs(data).max(), 0.1)

    def test_clip_is_deterministic(self) -> None:
        import tempfile

        import soundfile as sf

        with tempfile.TemporaryDirectory() as tmp:
            a, _ = sf.read(model_sweep.make_input_clip(os.path.join(tmp, "a.wav")))
            b, _ = sf.read(model_sweep.make_input_clip(os.path.join(tmp, "b.wav")))
        self.assertTrue((a == b).all())

    def test_scratch_symlinks_models_and_copies_settings(self) -> None:
        import json
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            models = os.path.join(tmp, "models")
            os.makedirs(os.path.join(models, "VR_Models"))
            src = os.path.join(tmp, "settings.json")
            with open(src, "w") as handle:
                json.dump({"schema_version": 1}, handle)

            data_dir, settings_path = model_sweep.prepare_scratch(
                os.path.join(tmp, "scratch"), models_dir=models, settings_src=src
            )

            self.assertTrue(os.path.islink(os.path.join(data_dir, "models")))
            self.assertTrue(
                os.path.isdir(os.path.join(data_dir, "models", "VR_Models"))
            )
            self.assertTrue(os.path.isfile(settings_path))
            self.assertNotEqual(os.path.abspath(settings_path), os.path.abspath(src))

    def test_scratch_without_source_settings_writes_defaults(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            models = os.path.join(tmp, "models")
            os.makedirs(models)
            _, settings_path = model_sweep.prepare_scratch(
                os.path.join(tmp, "scratch"), models_dir=models, settings_src=None
            )
        self.assertTrue(os.path.isfile(settings_path))

    def test_child_env_pins_data_dir_and_disables_warmup(self) -> None:
        env = model_sweep.child_env("/scratch/data")
        self.assertEqual(env["UVR_DATA_DIR"], "/scratch/data")
        self.assertEqual(env["UVR_SKIP_SEPARATE_WARMUP"], "1")
        self.assertEqual(env["UVR_DISABLE_POLITREES"], "1")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m unittest tests.test_model_sweep.ScratchEnvTests -v`
Expected: FAIL — `AttributeError: module 'model_sweep' has no attribute 'make_input_clip'`

- [ ] **Step 3: Append the implementation**

```python
def make_input_clip(path: str, *, seconds: float = 3.0, rate: int = 44100) -> str:
    """Write a short deterministic stereo clip.

    Not silence: an all-zero input can produce all-zero stems and trip the
    level-matching and clipping paths in ways that say nothing about the model.
    """
    import numpy as np
    import soundfile as sf

    frames = int(rate * seconds)
    t = np.arange(frames, dtype=np.float64) / rate
    rng = np.random.default_rng(0)
    left = (
        0.5 * np.sin(2 * np.pi * 220.0 * t)
        + 0.25 * np.sin(2 * np.pi * 880.0 * t)
        + 0.05 * rng.standard_normal(frames)
    )
    right = (
        0.4 * np.sin(2 * np.pi * 330.0 * t)
        + 0.2 * np.sin(2 * np.pi * 1320.0 * t)
        + 0.05 * rng.standard_normal(frames)
    )
    stereo = np.stack([left, right], axis=1)
    stereo = stereo / max(1e-9, float(np.abs(stereo).max())) * 0.7  # ~-3 dBFS
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    sf.write(path, stereo, rate, subtype="PCM_16")
    return path


def prepare_scratch(
    root: str, *, models_dir: str, settings_src: Optional[str]
) -> tuple:
    """Build an isolated UVR data dir: symlinked models, copied settings.

    Model resolution comes back empty without the ``models`` symlink, and the
    user's own ``settings.json`` must never be written to.
    """
    import json
    import shutil

    os.makedirs(root, exist_ok=True)
    link = os.path.join(root, "models")
    if not os.path.exists(link):
        os.symlink(os.path.abspath(models_dir), link)

    settings_path = os.path.join(root, "settings.json")
    if settings_src and os.path.isfile(settings_src):
        shutil.copyfile(settings_src, settings_path)
    else:
        with open(settings_path, "w") as handle:
            json.dump({}, handle)
    return root, settings_path


def child_env(data_dir: str) -> Dict[str, str]:
    """Environment for a child run: isolated data dir, no warmup, no network."""
    env = dict(os.environ)
    env["UVR_DATA_DIR"] = data_dir
    env["UVR_SKIP_SEPARATE_WARMUP"] = "1"
    env["UVR_DISABLE_POLITREES"] = "1"
    return env
```

- [ ] **Step 4: Run the tests**

Run: `.venv/bin/python -m unittest tests.test_model_sweep -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add scripts/model_sweep.py tests/test_model_sweep.py
git commit -m "$(cat <<'EOF'
feat(scripts): add sweep scratch environment and input clip

Isolated UVR_DATA_DIR with symlinked models and a copied settings.json, plus
a deterministic 3s stereo clip. The user's settings file is never written to.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 6: Child worker

**Files:**
- Modify: `scripts/model_sweep.py` (append)
- Test: `tests/test_model_sweep.py` (append a class)

**Interfaces:**
- Consumes: `SweepJob` fields, `KIND_*` (Task 3).
- Produces:
  - `apply_overrides(settings: Any, overrides: dict) -> None` — dotted keys via `set_path`, bare keys via `set_flat`
  - `collect_outputs(export_dir: str) -> list[list]` — `[path, size]` pairs for audio files
  - `run_child(spec_path: str) -> int`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_model_sweep.py`:

```python
class ChildHelperTests(unittest.TestCase):
    def test_apply_overrides_handles_flat_and_dotted_keys(self) -> None:
        from core.settings import Settings

        settings = Settings()
        model_sweep.apply_overrides(
            settings,
            {
                "is_gpu_conversion": False,
                "mdx_segment_size": 256,
                "audio_tools.apollo_model": "apollo_universal_model.ckpt",
            },
        )
        self.assertFalse(settings.process.use_gpu)
        self.assertEqual(settings.mdx.segment_size, 256)
        self.assertEqual(settings.audio_tools.apollo_model, "apollo_universal_model.ckpt")

    def test_apply_overrides_raises_on_unmapped_flat_key(self) -> None:
        from core.settings import Settings

        with self.assertRaises(KeyError):
            model_sweep.apply_overrides(Settings(), {"totally_made_up_key": 1})

    def test_collect_outputs_lists_audio_only(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            for name in ("a (Vocals).wav", "b.flac", "notes.txt", "empty.wav"):
                with open(os.path.join(tmp, name), "wb") as handle:
                    handle.write(b"" if name == "empty.wav" else b"RIFFdata")
            outputs = model_sweep.collect_outputs(tmp)
        names = sorted(os.path.basename(p) for p, _ in outputs)
        self.assertEqual(names, ["a (Vocals).wav", "b.flac"])
```

Note the third case: zero-byte files do not count as output, which is what makes `NO_OUTPUT` meaningful.

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m unittest tests.test_model_sweep.ChildHelperTests -v`
Expected: FAIL — `AttributeError: module 'model_sweep' has no attribute 'apply_overrides'`

- [ ] **Step 3: Append the child implementation**

```python
AUDIO_SUFFIXES = (".wav", ".flac", ".mp3", ".aiff", ".ogg", ".opus")


def apply_overrides(settings: Any, overrides: Dict[str, Any]) -> None:
    """Apply job overrides. Dotted keys are nested paths; bare keys are flat keys.

    ``set_flat`` silently no-ops on an unmapped key, which would make a job
    quietly test the wrong configuration — so unmapped keys raise here instead.
    """
    from core.settings.access import set_flat, set_path
    from core.settings.flat_map import FLAT_TO_PATH

    for key, value in overrides.items():
        if "." in key:
            set_path(settings, key, value)
            continue
        if key not in FLAT_TO_PATH:
            raise KeyError(f"flat key {key!r} is not in FLAT_TO_PATH; add the mapping first")
        set_flat(settings, key, value)


def collect_outputs(export_dir: str) -> List[List[Any]]:
    """Non-empty audio files written into ``export_dir``."""
    found: List[List[Any]] = []
    for root, _dirs, files in os.walk(export_dir):
        for name in sorted(files):
            if not name.lower().endswith(AUDIO_SUFFIXES):
                continue
            path = os.path.join(root, name)
            size = os.path.getsize(path)
            if size > 0:
                found.append([path, size])
    return found


def _model_is_recognized(settings: Any, method: Optional[str], model: Optional[str]) -> bool:
    """Whether the weight resolves to known metadata (MD5 → model_data)."""
    if not model or method is None:
        return True
    from bundled.constants import DEMUCS_ARCH_TYPE, MDX_ARCH_TYPE, VR_ARCH_TYPE
    from core import ModelConfig, ModelRepository

    arch = {"mdx": MDX_ARCH_TYPE, "vr": VR_ARCH_TYPE, "demucs": DEMUCS_ARCH_TYPE}[method]
    repo = ModelRepository()
    config = ModelConfig(settings, repo, model, arch, is_dry_check=True)
    return bool(config.model_status)


def run_child(spec_path: str) -> int:
    """Execute exactly one job and write ``result.json`` next to the spec."""
    import json
    import time
    import traceback

    with open(spec_path) as handle:
        spec = json.load(handle)

    job_dir = os.path.dirname(os.path.abspath(spec_path))
    export_dir = spec["export_dir"]
    os.makedirs(export_dir, exist_ok=True)

    result: Dict[str, Any] = {
        "ok": False,
        "error_type": None,
        "message": "",
        "elapsed_s": 0.0,
        "outputs": [],
        "stopped": False,
        "unrecognized": False,
    }
    started = time.perf_counter()
    try:
        from bundled.constants import ENSEMBLE_MODE
        from core.headless_run import build_settings, run_ensemble_sync, run_separation_sync
        from core.types import ProcessMethod

        kind = spec["kind"]
        settings = build_settings(
            settings_path=spec["settings_path"],
            export_path=export_dir,
            method=spec.get("method"),
            model=spec.get("model"),
            use_gpu=False if spec.get("cpu") else None,
            stable_names=True,
            allow_ensemble=(kind == KIND_ENSEMBLE),
        )
        if kind == KIND_ENSEMBLE:
            settings.process.method = ProcessMethod(ENSEMBLE_MODE)
        apply_overrides(settings, spec.get("overrides") or {})

        if kind == KIND_SINGLE and not _model_is_recognized(
            settings, spec.get("method"), spec.get("model")
        ):
            result["unrecognized"] = True
            result["elapsed_s"] = time.perf_counter() - started
            _write_result(job_dir, result)
            return 0

        timeout = float(spec.get("timeout") or DEFAULT_TIMEOUT)
        if kind == KIND_TOOL:
            outcome_error, stopped = _run_tool(settings, spec["input_path"], timeout)
        elif kind == KIND_ENSEMBLE:
            outcome = run_ensemble_sync(
                settings, [spec["input_path"]], print_console=True, join_timeout=timeout
            )
            outcome_error, stopped = outcome.error, outcome.stopped
        else:
            outcome = run_separation_sync(
                settings, [spec["input_path"]], print_console=True, join_timeout=timeout
            )
            outcome_error, stopped = outcome.error, outcome.stopped

        result["stopped"] = bool(stopped)
        if outcome_error is not None:
            result["error_type"] = type(outcome_error).__name__
            result["message"] = str(outcome_error)
        else:
            result["ok"] = not stopped
    except BaseException as exc:  # noqa: BLE001 - the point is to report anything
        result["error_type"] = type(exc).__name__
        result["message"] = f"{exc}\n{traceback.format_exc()}"

    result["elapsed_s"] = time.perf_counter() - started
    result["outputs"] = collect_outputs(export_dir)
    _write_result(job_dir, result)
    return 0 if result["ok"] and result["outputs"] else 1


def _write_result(job_dir: str, result: Dict[str, Any]) -> None:
    import json

    with open(os.path.join(job_dir, "result.json"), "w") as handle:
        json.dump(result, handle)


def _run_tool(settings: Any, input_path: str, timeout: float) -> tuple:
    """Run the Apollo restore tool, mirroring the UI's model resolution."""
    import threading

    from core import ModelRepository
    from core.apollo import ApolloModelData
    from core.audio_tools import AudioToolRunner
    from core.job_runner import JobCallbacks

    repo = ModelRepository()
    model_data = ApolloModelData(
        settings.audio_tools.apollo_model,
        model_hash_table=repo.model_hash_table,
        on_unrecognized=None,
    )
    if not model_data.is_model_status:
        raise RuntimeError(f"Apollo model not valid: {settings.audio_tools.apollo_model}")

    done = threading.Event()
    error_box: List[BaseException] = []
    stopped_box: List[bool] = []

    callbacks = JobCallbacks(
        on_console=lambda text: sys.stdout.write(text),
        on_complete=done.set,
        on_stopped=lambda: (stopped_box.append(True), done.set()),
        on_error=lambda exc: (error_box.append(exc), done.set()),
    )
    runner = AudioToolRunner(settings)
    runner.start(
        APOLLO_RESTORE,
        [input_path],
        [],
        callbacks,
        apollo_params={
            "extracted_params": model_data.extracted_params,
            "config": model_data.config,
        },
    )
    if not done.wait(timeout=timeout):
        runner.stop()
        raise TimeoutError(f"audio tool exceeded {timeout:.0f}s")
    return (error_box[0] if error_box else None), bool(stopped_box)
```

- [ ] **Step 4: Run the tests**

Run: `.venv/bin/python -m unittest tests.test_model_sweep -v`
Expected: PASS

- [ ] **Step 5: Smoke the child by hand against one real model**

```bash
SCRATCH=$(mktemp -d)
.venv/bin/python - <<'PY'
import json, os, sys
sys.path.insert(0, os.getcwd())
sys.path.insert(0, os.path.join(os.getcwd(), "scripts"))
import model_sweep
scratch = os.environ["SCRATCH"]
data_dir, settings_path = model_sweep.prepare_scratch(
    os.path.join(scratch, "data"),
    models_dir=os.path.join(os.getcwd(), "models"),
    settings_src=os.path.join(os.getcwd(), "settings.json"),
)
clip = model_sweep.make_input_clip(os.path.join(scratch, "in.wav"))
job_dir = os.path.join(scratch, "job")
os.makedirs(job_dir, exist_ok=True)
spec = {
    "kind": "single", "method": "mdx",
    "model": "mel_band_roformer_inst_fullness_v8_gabox.ckpt",
    "overrides": {}, "settings_path": settings_path,
    "input_path": clip, "export_dir": os.path.join(job_dir, "out"),
    "cpu": False, "timeout": 300,
}
with open(os.path.join(job_dir, "spec.json"), "w") as fh:
    json.dump(spec, fh)
print(json.dumps(spec))
PY
```

Then run the child in a subprocess with the scratch env and inspect the result:

```bash
UVR_DATA_DIR=$SCRATCH/data UVR_SKIP_SEPARATE_WARMUP=1 \
  .venv/bin/python scripts/model_sweep.py --run-job $SCRATCH/job/spec.json
cat $SCRATCH/job/result.json
```

Expected: `"ok": true` with a non-empty `outputs` list. (`--run-job` is wired in Task 7; until then, call `model_sweep.run_child(path)` directly from the heredoc.)

- [ ] **Step 6: Commit**

```bash
git add scripts/model_sweep.py tests/test_model_sweep.py
git commit -m "$(cat <<'EOF'
feat(scripts): add sweep child worker

Runs exactly one job (single, ensemble, or Apollo tool) and writes
result.json. Unmapped flat override keys raise instead of silently no-opping,
and zero-byte exports do not count as output.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 7: Parent orchestrator, CLI, and CPU retry

**Files:**
- Modify: `scripts/model_sweep.py` (append)
- Test: `tests/test_model_sweep.py` (append a class)

**Interfaces:**
- Consumes: everything from Tasks 3-6.
- Produces:
  - `run_one(job: SweepJob, *, spawn: Callable[..., Any], job_dir: str, settings_path: str, input_path: str, data_dir: str, cpu: bool, cpu_retry: bool) -> tuple[str, str, float]` returning `(verdict, detail, elapsed_s)`
  - `sweep(jobs, *, spawn, ..., cpu_retry: bool, strict: bool) -> int`
  - `build_parser() -> argparse.ArgumentParser`
  - `main(argv: Optional[Sequence[str]] = None) -> int`

`spawn` is injected so the parent's control flow — including the CPU retry — is testable without launching anything.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_model_sweep.py`:

```python
class ParentControlFlowTests(unittest.TestCase):
    def _job(self, **kwargs):
        base = dict(id="mdx:a.ckpt", kind=model_sweep.KIND_SINGLE, method="mdx", model="a.ckpt")
        base.update(kwargs)
        return model_sweep.SweepJob(**base)

    def _spawner(self, results):
        """Returns a fake spawn that pops (exit_code, result_dict, timed_out)."""
        calls = []

        def spawn(*, spec, job_dir, env, timeout):
            calls.append(spec)
            return results.pop(0)

        return spawn, calls

    def test_passing_job_never_retries(self) -> None:
        ok = {"ok": True, "outputs": [["x.wav", 10]], "error_type": None, "message": ""}
        spawn, calls = self._spawner([(0, ok, False)])
        verdict, _, _ = model_sweep.run_one(
            self._job(), spawn=spawn, job_dir="/tmp/j", settings_path="/tmp/s.json",
            input_path="/tmp/in.wav", data_dir="/tmp/d", cpu=False, cpu_retry=True,
        )
        self.assertEqual(verdict, model_sweep.PASS)
        self.assertEqual(len(calls), 1)

    def test_oom_retries_on_cpu_and_reports_cpu_ok(self) -> None:
        oom = {
            "ok": False, "outputs": [], "error_type": "OutOfMemoryError",
            "message": "CUDA out of memory",
        }
        ok = {"ok": True, "outputs": [["x.wav", 10]], "error_type": None, "message": ""}
        spawn, calls = self._spawner([(1, oom, False), (0, ok, False)])
        verdict, _, _ = model_sweep.run_one(
            self._job(), spawn=spawn, job_dir="/tmp/j", settings_path="/tmp/s.json",
            input_path="/tmp/in.wav", data_dir="/tmp/d", cpu=False, cpu_retry=True,
        )
        self.assertEqual(verdict, model_sweep.OOM_CPU_OK)
        self.assertEqual(len(calls), 2)
        self.assertFalse(calls[0]["cpu"])
        self.assertTrue(calls[1]["cpu"])

    def test_oom_that_also_fails_on_cpu_reports_the_cpu_failure(self) -> None:
        oom = {
            "ok": False, "outputs": [], "error_type": "OutOfMemoryError",
            "message": "CUDA out of memory",
        }
        broken = {
            "ok": False, "outputs": [], "error_type": "RuntimeError",
            "message": "shape mismatch",
        }
        spawn, _ = self._spawner([(1, oom, False), (1, broken, False)])
        verdict, detail, _ = model_sweep.run_one(
            self._job(), spawn=spawn, job_dir="/tmp/j", settings_path="/tmp/s.json",
            input_path="/tmp/in.wav", data_dir="/tmp/d", cpu=False, cpu_retry=True,
        )
        self.assertEqual(verdict, "FAIL(RuntimeError)")
        self.assertIn("shape mismatch", detail)

    def test_cpu_retry_disabled_keeps_bare_oom(self) -> None:
        oom = {
            "ok": False, "outputs": [], "error_type": "OutOfMemoryError",
            "message": "CUDA out of memory",
        }
        spawn, calls = self._spawner([(1, oom, False)])
        verdict, _, _ = model_sweep.run_one(
            self._job(), spawn=spawn, job_dir="/tmp/j", settings_path="/tmp/s.json",
            input_path="/tmp/in.wav", data_dir="/tmp/d", cpu=False, cpu_retry=False,
        )
        self.assertEqual(verdict, model_sweep.OOM)
        self.assertEqual(len(calls), 1)

    def test_no_retry_when_already_on_cpu(self) -> None:
        oom = {
            "ok": False, "outputs": [], "error_type": "OutOfMemoryError",
            "message": "CUDA out of memory",
        }
        spawn, calls = self._spawner([(1, oom, False)])
        model_sweep.run_one(
            self._job(), spawn=spawn, job_dir="/tmp/j", settings_path="/tmp/s.json",
            input_path="/tmp/in.wav", data_dir="/tmp/d", cpu=True, cpu_retry=True,
        )
        self.assertEqual(len(calls), 1)

    def test_skip_jobs_are_not_spawned(self) -> None:
        spawn, calls = self._spawner([])
        verdict, detail, _ = model_sweep.run_one(
            self._job(id="composite:ensemble", kind=model_sweep.KIND_SKIP,
                      method=None, model=None, detail="needs two models"),
            spawn=spawn, job_dir="/tmp/j", settings_path="/tmp/s.json",
            input_path="/tmp/in.wav", data_dir="/tmp/d", cpu=False, cpu_retry=True,
        )
        self.assertTrue(verdict.startswith("SKIP"))
        self.assertEqual(calls, [])


class CliTests(unittest.TestCase):
    def test_parser_defaults(self) -> None:
        args = model_sweep.build_parser().parse_args([])
        self.assertEqual(args.timeout, 300.0)
        self.assertFalse(args.cpu)
        self.assertFalse(args.strict)
        self.assertTrue(args.cpu_retry)

    def test_method_filter_accepts_repeats(self) -> None:
        args = model_sweep.build_parser().parse_args(["--method", "mdx", "--method", "vr"])
        self.assertEqual(set(args.method), {"mdx", "vr"})

    def test_no_cpu_retry_flag(self) -> None:
        args = model_sweep.build_parser().parse_args(["--no-cpu-retry"])
        self.assertFalse(args.cpu_retry)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m unittest tests.test_model_sweep.ParentControlFlowTests -v`
Expected: FAIL — `AttributeError: module 'model_sweep' has no attribute 'run_one'`

- [ ] **Step 3: Append the parent implementation**

```python
def spawn_child(*, spec: Dict[str, Any], job_dir: str, env: Dict[str, str], timeout: float):
    """Run one job in a fresh process. Returns ``(exit_code, result, timed_out)``."""
    import json
    import subprocess

    os.makedirs(job_dir, exist_ok=True)
    spec_path = os.path.join(job_dir, "spec.json")
    with open(spec_path, "w") as handle:
        json.dump(spec, handle)

    result_path = os.path.join(job_dir, "result.json")
    if os.path.exists(result_path):
        os.remove(result_path)

    argv = [sys.executable, os.path.abspath(__file__), "--run-job", spec_path]
    timed_out = False
    try:
        completed = subprocess.run(argv, env=env, timeout=timeout + 30.0)
        exit_code = completed.returncode
    except subprocess.TimeoutExpired:
        return None, None, True

    result = None
    if os.path.isfile(result_path):
        with open(result_path) as handle:
            result = json.load(handle)
    return exit_code, result, timed_out


def run_one(
    job: SweepJob,
    *,
    spawn,
    job_dir: str,
    settings_path: str,
    input_path: str,
    data_dir: str,
    cpu: bool,
    cpu_retry: bool,
) -> tuple:
    """Run one job, retrying once on CPU when the GPU ran out of memory."""
    import time

    if job.kind == KIND_SKIP:
        return f"SKIP({job.detail})", "", 0.0

    def attempt(on_cpu: bool):
        spec = {
            "kind": job.kind,
            "method": job.method,
            "model": job.model,
            "overrides": job.overrides,
            "settings_path": settings_path,
            "input_path": input_path,
            "export_dir": os.path.join(job_dir, "cpu" if on_cpu else "gpu", "out"),
            "cpu": on_cpu,
            "timeout": job.timeout,
        }
        started = time.perf_counter()
        exit_code, result, timed_out = spawn(
            spec=spec,
            job_dir=os.path.join(job_dir, "cpu" if on_cpu else "gpu"),
            env=child_env(data_dir),
            timeout=job.timeout,
        )
        verdict, detail = classify(exit_code=exit_code, result=result, timed_out=timed_out)
        return verdict, detail, time.perf_counter() - started

    verdict, detail, elapsed = attempt(cpu)
    if verdict == OOM and cpu_retry and not cpu:
        retry_verdict, retry_detail, retry_elapsed = attempt(True)
        elapsed += retry_elapsed
        if retry_verdict == PASS:
            return OOM_CPU_OK, "out of VRAM at these settings; identical run passed on CPU", elapsed
        return retry_verdict, retry_detail, elapsed
    return verdict, detail, elapsed


def sweep(
    jobs: Sequence[SweepJob],
    *,
    spawn,
    root: str,
    settings_path: str,
    input_path: str,
    data_dir: str,
    cpu: bool,
    cpu_retry: bool,
    strict: bool,
    fail_fast: bool,
    json_path: Optional[str],
    keep_outputs: bool,
) -> int:
    """Run every job serially. One child alive at a time."""
    import json
    import shutil

    rows: List[Dict[str, Any]] = []
    verdicts: List[str] = []
    for index, job in enumerate(jobs, 1):
        print(f"[{index}/{len(jobs)}] {job.id}", flush=True)
        job_dir = os.path.join(root, f"job{index:03d}")
        verdict, detail, elapsed = run_one(
            job,
            spawn=spawn,
            job_dir=job_dir,
            settings_path=settings_path,
            input_path=input_path,
            data_dir=data_dir,
            cpu=cpu,
            cpu_retry=cpu_retry,
        )
        print(render_row(job.id, verdict, elapsed, detail), flush=True)
        rows.append(
            {"id": job.id, "verdict": verdict, "detail": detail, "elapsed_s": elapsed}
        )
        verdicts.append(verdict)
        if not keep_outputs:
            shutil.rmtree(job_dir, ignore_errors=True)
        if fail_fast and is_failure(verdict, strict=strict):
            break

    print("-" * 96)
    print(render_summary(verdicts))
    if json_path:
        with open(json_path, "w") as handle:
            json.dump({"results": rows}, handle, indent=2)
        print(f"json={json_path}")
    return 1 if any(is_failure(v, strict=strict) for v in verdicts) else 0


def build_parser():
    import argparse

    parser = argparse.ArgumentParser(
        description="Start a real run for every model installed on this machine."
    )
    parser.add_argument("--run-job", default=None, help=argparse.SUPPRESS)
    parser.add_argument(
        "--method",
        action="append",
        choices=("mdx", "vr", "demucs", "apollo", "composite"),
        help="Limit to these job groups (repeatable; default: all)",
    )
    parser.add_argument("--only", default="", help="Substring filter on model filename")
    parser.add_argument("--skip", default="", help="Comma-separated model filenames to skip")
    parser.add_argument("--cpu", action="store_true", help="Force CPU for every job")
    parser.add_argument(
        "--no-cpu-retry",
        dest="cpu_retry",
        action="store_false",
        help="Do not retry an OOM job on CPU",
    )
    parser.set_defaults(cpu_retry=True)
    parser.add_argument(
        "--stock-settings",
        action="store_true",
        help="Use default settings instead of a copy of the user's settings.json",
    )
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT)
    parser.add_argument("--json", dest="json_path", default=None)
    parser.add_argument("--list", action="store_true", help="Print the job list and exit")
    parser.add_argument("--fail-fast", action="store_true")
    parser.add_argument(
        "--strict", action="store_true", help="Treat UNRECOGNIZED as a failure"
    )
    parser.add_argument("--keep-outputs", action="store_true")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    import tempfile

    args = build_parser().parse_args(argv)
    if args.run_job:
        return run_child(args.run_job)

    from core import ModelRepository
    from core.settings import Settings
    from core import paths as core_paths

    repo = ModelRepository()
    repo.reload_mappers()
    settings = Settings.load(core_paths.SETTINGS_DATA_FILE)
    installed = collect_installed(repo, settings)

    methods = set(args.method) if args.method else {"mdx", "vr", "demucs", "apollo", "composite"}
    skip = frozenset(s for s in (args.skip or "").split(",") if s)
    jobs = discover_jobs(installed, methods=methods, only=args.only, skip=skip)
    jobs = [
        job if job.timeout != DEFAULT_TIMEOUT else SweepJob(**{**job.__dict__, "timeout": args.timeout})
        for job in jobs
    ]

    if args.list:
        for job in jobs:
            print(f"{job.id:<52} {job.kind}")
        print(f"{len(jobs)} jobs")
        return 0

    assert "torch" not in sys.modules, "the sweep parent must stay torch-free"

    root = tempfile.mkdtemp(prefix="uvr-sweep-")
    print(f"scratch={root}")
    data_dir, settings_path = prepare_scratch(
        os.path.join(root, "data"),
        models_dir=core_paths.MODELS_DIR,
        settings_src=None if args.stock_settings else core_paths.SETTINGS_DATA_FILE,
    )
    input_path = make_input_clip(os.path.join(root, "sweep-input.wav"))

    return sweep(
        jobs,
        spawn=spawn_child,
        root=root,
        settings_path=settings_path,
        input_path=input_path,
        data_dir=data_dir,
        cpu=args.cpu,
        cpu_retry=args.cpu_retry,
        strict=args.strict,
        fail_fast=args.fail_fast,
        json_path=args.json_path,
        keep_outputs=args.keep_outputs,
    )


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run the tests**

Run: `.venv/bin/python -m unittest tests.test_model_sweep -v`
Expected: PASS

- [ ] **Step 5: Verify the job list against the real model tree**

```bash
.venv/bin/python scripts/model_sweep.py --list
```
Expected: ~43 jobs — roughly 22 `mdx:`, 8 `vr:`, ~5 `demucs:`, 3 `apollo:`, 5 `composite:`. If a composite shows as `skip`, check that its models are installed before assuming a bug.

- [ ] **Step 6: Run one real job end to end**

```bash
.venv/bin/python scripts/model_sweep.py --method mdx --only mel_band_roformer_inst_fullness
```
Expected: one row, `PASS`, exit 0. This is the model from the original bug report.

- [ ] **Step 7: Run pyright**

```bash
.venv/bin/python -m pyright 2>&1 | tail -3
```
Expected: `0 errors`

- [ ] **Step 8: Commit**

```bash
git add scripts/model_sweep.py tests/test_model_sweep.py
git commit -m "$(cat <<'EOF'
feat(scripts): add sweep parent orchestrator and CLI

Runs jobs strictly serially, one child process at a time, with a single CPU
retry when a job runs out of VRAM so "segment size too big" is distinguishable
from "model is broken". Spawning is injected, so the control flow is tested
without launching anything.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 8: Opt-in test entry point and documentation

**Files:**
- Modify: `tests/test_model_sweep.py` (append the guarded class)
- Modify: `CLAUDE.md` (commands section)
- Modify: `docs/environment.md` (document `UVR_MODEL_SWEEP`)

**Interfaces:**
- Consumes: `main` from Task 7.
- Produces: no new code interfaces.

- [ ] **Step 1: Add the guarded full-sweep test**

Append to `tests/test_model_sweep.py`:

```python
@unittest.skipUnless(
    os.getenv("UVR_MODEL_SWEEP"),
    "local-only: set UVR_MODEL_SWEEP=1 to run every installed model (10-25 min)",
)
class FullSweepTests(unittest.TestCase):
    def test_every_installed_model_starts_and_finishes(self) -> None:
        self.assertEqual(model_sweep.main([]), 0)
```

- [ ] **Step 2: Verify it skips by default and is reachable when enabled**

```bash
.venv/bin/python -m unittest tests.test_model_sweep -v 2>&1 | tail -5
.venv/bin/python -m unittest tests.test_model_sweep.FullSweepTests -v 2>&1 | tail -5
```
Expected: first run reports the skip; second run without `UVR_MODEL_SWEEP` also skips. Do not run the enabled variant here — Step 4 does the real sweep.

- [ ] **Step 3: Document it**

In `CLAUDE.md`, under "Other:", add:

```bash
python scripts/model_sweep.py --list      # local-only: every installed model, one real run each
python scripts/model_sweep.py --method mdx --json /tmp/sweep.json
```

In `docs/environment.md`, add `UVR_MODEL_SWEEP=1` to the switch list: "enables the local-only full model sweep in `tests/test_model_sweep.py`; the sweep itself is `scripts/model_sweep.py` and never runs in CI."

- [ ] **Step 4: Run the real sweep**

```bash
.venv/bin/python scripts/model_sweep.py --json /tmp/sweep.json 2>&1 | tail -60
```
Expected: ~43 rows, 10-25 minutes. Investigate every `FAIL(...)`, `NO_OUTPUT`, `CRASH` and `TIMEOUT` — those are the bugs this exists to find. `OOM(cpu-ok)` and `SKIP(...)` rows are informational. Report the results rather than fixing model bugs inside this task; each one deserves its own change.

- [ ] **Step 5: Run the full suite and pyright one last time**

```bash
xvfb-run -a .venv/bin/python -m unittest discover -s tests 2>&1 | tail -3
.venv/bin/python -m pyright 2>&1 | tail -3
```
Expected: `OK`, `0 errors`

- [ ] **Step 6: Commit**

```bash
git add tests/test_model_sweep.py CLAUDE.md docs/environment.md
git commit -m "$(cat <<'EOF'
test(scripts): add opt-in full model sweep entry point and docs

UVR_MODEL_SWEEP=1 reaches the full sweep through unittest; without it the
suite is unchanged, so CI stays green on a machine with no weights.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

- [ ] **Step 7: Open the PR**

```bash
gh pr create --title "Local model sweep: start a real run for every installed model" \
  --body "$(cat <<'EOF'
## Summary
Adds `scripts/model_sweep.py`, a local-only sweep that starts a real separation
for every model installed on the machine and reports which ones fail. Motivated
by a beartype violation that made 12 of 22 installed MDX models unbuildable
without any test noticing — weights are gitignored, so CI structurally cannot
catch that class of bug.

- one subprocess per model, strictly serial (peak memory = one normal run)
- verdicts: PASS / FAIL(<Type>) / NO_OUTPUT / TIMEOUT / CRASH / OOM / UNRECOGNIZED
- OOM retries once on CPU so "segment size too big" is distinguishable from a real defect
- composites cover ensemble, secondary chain, vocal splitter, 4-stem
- supporting: `run_ensemble_sync` in `core.headless_run`; settings accessors and
  OOM matching moved into `core` so headless tools need neither GTK nor torch

## Test plan
- `python -m unittest discover -s tests` — unchanged, sweep helpers covered by fakes
- `python -m pyright` — 0 errors
- `python scripts/model_sweep.py --json /tmp/sweep.json` — full local sweep

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

---

## Self-Review

**Spec coverage:** every spec section maps to a task — deliverables table → Tasks 1-8; `run_ensemble_sync` → Task 2; `get_path`/`set_path` move → Task 1; job discovery table → Task 3; composites → Task 3; input clip → Task 5; verdict table → Task 4; OOM three layers → Task 4 (classification) + Task 7 (CPU retry); isolation → Task 5; CLI flags → Task 7; testing the tester → Tasks 3-7 (pure helpers) + Task 8 (opt-in); runtime expectation → Task 8 Step 4.

One addition beyond the spec: `build_settings(allow_ensemble=...)` in Task 2. The spec only named `run_ensemble_sync`, but `build_settings` rejects ensemble mode independently, so the composite could not be configured without it.

**Type consistency:** `SweepJob` / `Installed` field names are used identically in Tasks 3, 6 and 7. `classify` returns `(verdict, detail)` everywhere; `run_one` returns `(verdict, detail, elapsed_s)`. The `spawn` contract — keyword-only `spec`, `job_dir`, `env`, `timeout`, returning `(exit_code, result, timed_out)` — matches between `spawn_child` (Task 7) and the fakes in the tests.

**Placeholders:** none. Every code step carries the actual code; every test step carries the actual test.
