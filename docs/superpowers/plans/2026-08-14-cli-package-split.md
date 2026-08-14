# CLI Package Split Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extract the headless front end into a top-level `cli/` package (sibling of `ui/`), then grow its product surface with shared process flags, an `ensemble` command, and `list-models`.

**Architecture:** `cli/` is a presentation layer exactly like `ui/`: it talks to `core`, never the reverse. `core/headless_run.py` stays the GTK-free library that `scripts/model_sweep.py` and tests import. Named CLI flags do **not** become new `build_settings` keyword parameters — they compile to validated `(path, value)` override pairs and flow through one `apply_settings_overrides` entry point shared with `--set`.

**Tech Stack:** Python 3.14, stdlib `argparse`, stdlib `unittest`, basedpyright (`standard` mode), no new third-party dependencies.

## Global Constraints

- **No tkinter, anywhere.** Not in `core`, not in `cli`.
- **`cli/__init__.py` must not import** GTK, `gi`, `torch`, `onnxruntime`, or `engines`. It is a docstring and nothing else. Unlike `ui/__init__.py`, it pins no GI versions.
- **`core` must never import `cli` at module scope.** The two trampolines (`core/cli.py`, `core/__main__.py`) import `cli.main` *inside a function body*. This is the only permitted `core → cli` reference in the tree and it exists solely to keep `python -m core.cli` working.
- **Enum settings are `str, Enum`; never stringify them.** Route any value that reaches a filename, path, or log line through `enum_value` (`core/settings/coerce.py`). `str(v)` yields `"SaveFormat.WAV"`, not `"WAV"`.
- **`--json` owns stdout.** A JSON invocation emits exactly one document,
  including failures (`{"ok": false, "error": {"type": ..., "message": ...}}`)
  and interrupts (`"stopped": true`, exit 130). Engine console text is
  suppressed, progress stays on stderr, human `error:` lines stay on stderr
  next to the document, and `--print-settings` becomes a nested object rather
  than a second document. Argparse usage errors (missing `-o`, unknown flags)
  stay argparse-shaped — they happen before `func()`.
- **Ctrl-C is a first-class stop.** First SIGINT/SIGTERM calls
  `JobRunner.stop(force=False)` so the worker unwinds through `ProcessStopped`.
  A second signal (or a 5s hang) calls `stop(force=True)`. `_run_job` returns
  `HeadlessResult(stopped=True)` and does **not** re-raise `KeyboardInterrupt`.
  CLI commands map that to `fail(..., exit_code=130)`. This lands in Task 4.5;
  Task 1 copies the old re-raise so the extract stays behaviour-preserving.
- **Never accept and ignore a flag.** In particular, `bench-ab` must forward
  every separation/process option to both child legs, and both run commands
  must resolve `--vocal-split` before applying the final `--set` layer.
- **Ensemble member source is explicit.** `ensemble` requires `--ensemble NAME`
  or `--model`/`--models`. It does not inherit `selected_models` from the last
  GUI session. Ad-hoc members also require `--main-stem` and clear any
  saved-preset name before output paths are built.
- **Curated recipes are first-class.** `--ensemble` accepts a user-saved name,
  a curated preset id, or the GUI label `Curated: …`. `list-models --method ensemble`
  lists both, with `kind: saved|curated`.
- **`--vocal-split` resolution is offline by default.** `karaoke_model_list`
  reaches `_merged_for_display()` the same way `list-models` does. Wrap it in
  `catalogue_offline` (created in Task 3, reused by Tasks 6–7).
- **Tests must not touch the live network.** `tests/net_guard.py` raises `BlockedNetworkAccess` on any non-loopback TCP connect. Any test that reaches `core.model_display._merged_for_display()` must neutralise **both** `UVR_DISABLE_POLITREES` and `UVR_DISABLE_MVSEPLESS`, or it leaks a background refresh thread into later modules under bare `unittest discover`.
- **Search with `rg`**, not `grep` or `git grep`.
- **Never run unscoped `git checkout -- .` / `git restore .` / `git reset --hard` / `git stash` / `git clean`.** This tree carries long-lived uncommitted edits under `models/*/model_data/`. Stage exact paths; never `git add -A`.
- Upstream's `Seperate*` misspelling is the real class-name prefix. Keep it.
- Every task ends with the full suite green: `.venv/bin/python -m unittest discover -s tests -v` and `.venv/bin/python -m basedpyright`.

---

## File Structure

**Created:**

| File | Responsibility |
| --- | --- |
| `cli/__init__.py` | Docstring only. No imports. |
| `cli/__main__.py` | `raise SystemExit(main())` |
| `cli/main.py` | argparse root, subparser registration, `main()` |
| `cli/process_flags.py` | Shared process flags → validated `(path, value)` override pairs |
| `cli/reporting.py` | TTY progress printer, `--quiet` handling, `--json` result payloads |
| `cli/separate.py` | `separate` command (moved from `core/cli.py`) |
| `cli/bench.py` | `bench-ab` command (moved from `core/cli.py`) |
| `cli/ensemble.py` | `ensemble` command |
| `cli/list_models.py` | `list-models` command |
| `cli/offline.py` | Catalogue-network guard shared by `--vocal-split`, `ensemble`, and `list-models` (created in Task 3) |
| `tests/test_headless_run.py` | Library-level tests moved out of `tests/test_cli_headless.py` |
| `tests/test_cli.py` | Parser, trampoline, `separate`/`bench-ab` wiring |
| `tests/test_cli_process_flags.py` | Flag → override-pair mapping |
| `tests/test_settings_overrides.py` | `validate_setting_path` / `apply_settings_overrides` |
| `tests/test_cli_ensemble.py` | Saved vs ad-hoc members, member resolution |
| `tests/test_cli_list_models.py` | Listing shape, `--json`, method filter, offline default |

**Modified:**

| File | Change |
| --- | --- |
| `core/cli.py` | Replaced wholesale by a lazy trampoline |
| `core/settings/access.py` | Add `validate_setting_path`, `apply_settings_overrides`, `parse_setting_assignment` |
| `core/headless_run.py` | `overrides=` param; ensemble aliases; `apply_saved_ensemble`; `resolve_ensemble_members`; progress plumbing |
| `pyrightconfig.json` | Add `"cli"` to `include` |
| `tests/test_cli_headless.py` | Deleted (contents split into the two new test modules) |
| `CLAUDE.md`, `README.md`, `docs/environment.md`, `docs/tracked-issues.md` | Documentation |

**Deliberately unchanged:** `core/__main__.py` (its `from .cli import main` picks up the new lazy wrapper for free), `core/bench_metrics.py`, `scripts/model_sweep.py`.

**Explicitly out of scope:** `audio-tools`, `download`, aggression/window/overlap named flags, any `console_scripts` entry point (this tree is not an installed package; `python -m cli` matches `python -m ui`).

---

### Task 1: Extract the `cli/` package

Behaviour-preserving move of `separate` and `bench-ab`, plus trampolines and the test split. This has to land atomically: the moment `core/cli.py` stops defining `run_separation_sync`, the existing `mock.patch("core.cli.run_separation_sync")` tests break.

**Files:**
- Create: `cli/__init__.py`, `cli/__main__.py`, `cli/main.py`, `cli/separate.py`, `cli/bench.py`
- Modify: `core/cli.py` (replace entirely), `pyrightconfig.json`
- Create: `tests/test_headless_run.py`, `tests/test_cli.py`
- Delete: `tests/test_cli_headless.py`

**Interfaces:**
- Consumes: `core.headless_run.build_settings`, `run_separation_sync`, `settings_summary`; `core.bench_metrics.compare_stem_dirs`, `parse_env_assignment`, `sanitize_env_label`
- Produces:
  - `cli.main.build_parser() -> argparse.ArgumentParser`
  - `cli.main.main(argv: Optional[Sequence[str]] = None) -> int`
  - `cli.separate.add_separate_args(parser: argparse.ArgumentParser) -> None`
  - `cli.separate.cmd_separate(args: argparse.Namespace) -> int`
  - `cli.separate.check_runtime_deps() -> Optional[str]`
  - `cli.bench.cmd_bench_ab(args: argparse.Namespace) -> int`
  - `core.cli.main(argv: Optional[Sequence[str]] = None) -> int` (lazy delegate)

- [ ] **Step 1: Create the package skeleton**

`cli/__init__.py`:

```python
"""Headless command-line front end for Ultimate Vocal Remover GTK.

A presentation layer, exactly like :mod:`ui`: it drives the Tk-free backend in
:mod:`core` and nothing in ``core`` may import it. Unlike :mod:`ui`, this
package pins no GI versions and must stay importable without GTK, torch or
onnxruntime present.
"""
```

`cli/__main__.py`:

```python
"""Allow ``python -m cli`` to run the headless CLI."""

from .main import main

raise SystemExit(main())
```

- [ ] **Step 2: Move `separate` into `cli/separate.py`**

Move `_check_runtime_deps`, `_add_common_separate_args` and `_cmd_separate` from `core/cli.py` verbatim, renamed to their public names. Only three things change: the module docstring, the `python -m core.cli` hint inside the dependency error, and the imports becoming absolute.

```python
"""The ``separate`` command: one method, one or more input files."""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Optional

from core.headless_run import build_settings, run_separation_sync, settings_summary
from core.settings import Settings

_REQUIRED_RUNTIME_MODULES = ("kthread", "soundfile")


def check_runtime_deps() -> Optional[str]:
    """Return a short error message if core runtime packages are missing."""
    missing = []
    for name in _REQUIRED_RUNTIME_MODULES:
        try:
            __import__(name)
        except ImportError:
            missing.append(name)
    if not missing:
        return None
    return (
        f"missing Python packages: {', '.join(missing)}. "
        f"Use the project venv, e.g. "
        f"`./.venv/bin/python -m cli ...` "
        f"(current interpreter: {sys.executable})"
    )


def add_separate_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("inputs", nargs="+", help="Input audio file path(s)")
    parser.add_argument(
        "-o", "--output", required=True, help="Export directory for stem outputs"
    )
    parser.add_argument(
        "--method",
        choices=("mdx", "demucs", "vr"),
        default=None,
        help="Process method (default: value from settings / last GUI session)",
    )
    parser.add_argument(
        "--model",
        default=None,
        help=(
            "Model display name, on-disk basename, or weight filename/path "
            "(e.g. 'v4 | hdemucs_mmi' or hdemucs_mmi.yaml); default: settings"
        ),
    )
    parser.add_argument(
        "--settings",
        default=None,
        help="Path to settings.json (default: UVR data dir settings file)",
    )
    parser.add_argument(
        "--cpu", action="store_true", help="Force CPU (sets is_gpu_conversion=False)"
    )
    parser.add_argument(
        "--stems",
        default=None,
        help=(
            "Which stems to save for this run only: both|primary|secondary|"
            "vocals|instrumental|bass|drums|other "
            "(or vocals,instrumental). Default: settings / last GUI session"
        ),
    )
    parser.add_argument(
        "--print-settings",
        action="store_true",
        help="Print resolved method/model/export knobs before running",
    )
    parser.add_argument(
        "--long-chunk-seconds",
        type=float,
        default=None,
        help="Whole-file chunk length in seconds (0/omit = off)",
    )
    parser.add_argument(
        "--long-chunk-overlap",
        type=float,
        default=None,
        help="Crossfade overlap between long-file chunks in seconds",
    )


def cmd_separate(args: argparse.Namespace) -> int:
    dep_err = check_runtime_deps()
    if dep_err:
        print(f"error: {dep_err}", file=sys.stderr)
        return 2

    os.makedirs(args.output, exist_ok=True)
    try:
        settings: Settings = build_settings(
            settings_path=args.settings,
            export_path=os.path.abspath(args.output),
            method=args.method,
            model=args.model,
            stems=args.stems,
            use_gpu=False if args.cpu else None,
            stable_names=True,
            long_chunk_seconds=args.long_chunk_seconds,
            long_chunk_overlap=args.long_chunk_overlap,
        )
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if args.print_settings:
        print(json.dumps(settings_summary(settings), indent=2))

    missing = [p for p in args.inputs if not os.path.isfile(p)]
    if missing:
        print(f"error: input not found: {missing[0]}", file=sys.stderr)
        return 2

    result = run_separation_sync(settings, [os.path.abspath(p) for p in args.inputs])
    if result.error is not None:
        print(f"error: {type(result.error).__name__}: {result.error}", file=sys.stderr)
        return 1
    if result.stopped:
        print("error: separation stopped", file=sys.stderr)
        return 1
    print(f"elapsed_s={result.elapsed_s:.3f}")
    print(f"export_path={result.export_path}")
    return 0
```

- [ ] **Step 3: Move `bench-ab` into `cli/bench.py`**

Two substantive changes from the original: the subprocess argv becomes `-m cli`, and the child gets an explicit `PYTHONPATH` pointing at the repo root. The old `-m core.cli` worked only because the child inherited a cwd that happened to be the repo root; `cli` is a more collision-prone top-level name, so make the path explicit rather than relying on cwd.

```python
"""The ``bench-ab`` command: two env legs, subprocess separates, null metrics."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from typing import Optional, Sequence

from core.bench_metrics import (
    compare_stem_dirs,
    parse_env_assignment,
    sanitize_env_label,
)

from .separate import check_runtime_deps

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _clear_dir_files(path: str) -> None:
    """Remove files directly under ``path`` (not recursive) so A/B legs stay clean."""
    if not os.path.isdir(path):
        return
    for name in os.listdir(path):
        file_path = os.path.join(path, name)
        if os.path.isfile(file_path) or os.path.islink(file_path):
            try:
                os.remove(file_path)
            except OSError:
                pass


def _child_env(base: dict[str, str]) -> dict[str, str]:
    """Ensure the child can import ``cli`` regardless of the inherited cwd."""
    env = base.copy()
    existing = env.get("PYTHONPATH", "")
    parts = [_REPO_ROOT] + [p for p in existing.split(os.pathsep) if p]
    env["PYTHONPATH"] = os.pathsep.join(parts)
    return env


def build_separate_argv(
    *,
    inputs: Sequence[str],
    output: str,
    method: Optional[str],
    model: Optional[str],
    settings: Optional[str],
    cpu: bool,
    stems: Optional[str] = None,
    print_settings: bool = False,
    long_chunk_seconds: Optional[float] = None,
    long_chunk_overlap: Optional[float] = None,
) -> list[str]:
    argv = [sys.executable, "-m", "cli", "separate", *inputs, "-o", output]
    if method:
        argv.extend(["--method", method])
    if model:
        argv.extend(["--model", model])
    if settings:
        argv.extend(["--settings", settings])
    if stems:
        argv.extend(["--stems", stems])
    if cpu:
        argv.append("--cpu")
    if print_settings:
        argv.append("--print-settings")
    if long_chunk_seconds is not None:
        argv.extend(["--long-chunk-seconds", str(long_chunk_seconds)])
    if long_chunk_overlap is not None:
        argv.extend(["--long-chunk-overlap", str(long_chunk_overlap)])
    return argv
```

Then move `_cmd_bench_ab` as `cmd_bench_ab`, call `build_separate_argv` (not
`_build_separate_argv`), pass the three new arguments from `args`, and build the
leg env as `env = _child_env(base_env); env[key] = value`. This closes an
existing hole where `bench-ab` accepted the print/chunk flags but silently
dropped them in its child runs.

- [ ] **Step 4: Write `cli/main.py`**

```python
"""argparse root for the headless CLI (``python -m cli``)."""

from __future__ import annotations

import argparse
from typing import Optional, Sequence

from .bench import cmd_bench_ab
from .separate import add_separate_args, cmd_separate


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m cli",
        description="Headless Ultimate Vocal Remover GTK runner",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    separate = sub.add_parser("separate", help="Run a single-method separation job")
    add_separate_args(separate)
    separate.set_defaults(func=cmd_separate)

    bench = sub.add_parser(
        "bench-ab",
        help="A/B two env configurations via subprocess separate runs + stem null metrics",
    )
    add_separate_args(bench)
    bench.add_argument(
        "--env",
        action="append",
        required=True,
        metavar="KEY=VALUE",
        help="Env assignment for leg A then B (exactly two required)",
    )
    bench.add_argument(
        "--json",
        default=None,
        help="Optional path to write a JSON summary",
    )
    bench.set_defaults(func=cmd_bench_ab)

    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    return int(args.func(args))
```

`bench-ab` keeps its path-valued `--json` for now. Task 4 renames it to `--json-out` when the shared boolean `--json` arrives; doing it here would be an unrelated behaviour change in a move-only task.

- [ ] **Step 5: Replace `core/cli.py` with a lazy trampoline**

The import sits inside the function body on purpose. A module-level `from cli.main import main` would make `import core.cli` pull in `cli`, inverting the documented one-directional layering.

```python
"""Deprecated location for the headless CLI — it now lives in :mod:`cli`.

``python -m core.cli`` and ``python -m core`` keep working; new callers should
use ``python -m cli``. :mod:`cli` is imported lazily inside :func:`main` so that
importing this module never inverts the ``cli -> core`` layering.
"""

from __future__ import annotations

from typing import Optional, Sequence


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Delegate to :func:`cli.main.main`."""
    from cli.main import main as _main

    return _main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
```

Leave `core/__main__.py` alone — its `from .cli import main` now binds this wrapper.

- [ ] **Step 6: Add `cli` to the pyright include list**

In `pyrightconfig.json`, the `include` array becomes:

```json
  "include": [
    "ui",
    "cli",
    "core",
    "engines",
    "tests",
    "bundled",
    "ml",
    "scripts",
    "__version__.py"
  ],
```

- [ ] **Step 7: Split the test module — library half**

Create `tests/test_headless_run.py` and move these classes over from `tests/test_cli_headless.py` **unchanged**: `ResolveCliModelArgTests`, `ApplyStemsOverrideTests`, `ResolveMethodTests`, `BuildSettingsTests`, `BenchMetricsTests`, `SettingsSummaryTests`. They already import only from `core.*`, so no patch target changes. Carry over the file's existing imports, dropping `from core.cli import build_parser, main`.

- [ ] **Step 8: Split the test module — CLI half**

Create `tests/test_cli.py` with `CliArgparseTests` moved over, repointing every patch target from `core.cli.*` to the module that now owns the name:

| Old target | New target |
| --- | --- |
| `core.cli.run_separation_sync` | `cli.separate.run_separation_sync` |
| `core.cli.build_settings` | `cli.separate.build_settings` |
| `core.cli.subprocess.run` | `cli.bench.subprocess.run` |
| `core.cli.compare_stem_dirs` | `cli.bench.compare_stem_dirs` |

Add the trampoline test:

```python
class TrampolineTests(unittest.TestCase):
    def test_core_cli_delegates_to_cli_main(self) -> None:
        import core.cli

        with mock.patch("cli.main.main", return_value=7) as delegate:
            self.assertEqual(core.cli.main(["separate", "x", "-o", "y"]), 7)
        delegate.assert_called_once_with(["separate", "x", "-o", "y"])

    def test_importing_core_does_not_import_cli(self) -> None:
        script = (
            "import sys; import core; "
            "print('cli' in sys.modules or 'cli.main' in sys.modules)"
        )
        proc = subprocess.run(
            [sys.executable, "-c", script],
            cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            capture_output=True,
            text=True,
            check=True,
        )
        self.assertEqual(proc.stdout.strip(), "False")
```

Import the parser and entry point from the new package, not the trampoline
(the trampoline no longer exports `build_parser`):

```python
from cli.main import build_parser, main
from core.headless_run import HeadlessResult
```

Add `import os`, `import subprocess`, `import sys` and `from unittest import mock`
to the module's imports. Keep `HeadlessResult` and `Settings` — `CliArgparseTests`
still constructs a fake run result.

- [ ] **Step 9: Delete the old module and run everything**

```bash
git rm tests/test_cli_headless.py
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python -m basedpyright
```

Expected: all tests pass, zero pyright diagnostics. Then confirm both entry points still work:

```bash
.venv/bin/python -m cli separate --help
.venv/bin/python -m core.cli separate --help
.venv/bin/python -m core separate --help
```

Expected: the first prints `usage: python -m cli separate …`; the other two print the same help (they delegate, so the `prog` reads `python -m cli` — that is intended and is the only user-visible change in this task).

- [ ] **Step 10: Commit**

```bash
git add cli tests/test_cli.py tests/test_headless_run.py core/cli.py pyrightconfig.json
git rm --cached tests/test_cli_headless.py 2>/dev/null || true
git commit -m "refactor(cli): extract headless front end into a top-level cli/ package

python -m cli is now canonical; python -m core.cli and python -m core stay
as lazy trampolines so existing docs and scripts keep working."
```

---

### Task 2: Validated settings overrides in `core`

`set_path` does **not** reject unknown fields — the settings sections are plain `@dataclass` (no `slots=True`), so `setattr(settings.process, "use_gpau", False)` silently invents an attribute, and `coerce_field` returns unknown paths unchanged. Every later task depends on `--set` and the named flags failing loudly, so build that guarantee first, in `core`, with no CLI surface attached.

**Files:**
- Modify: `core/settings/access.py`
- Test: `tests/test_settings_overrides.py`

**Interfaces:**
- Consumes: `core.settings.access.set_path`, `core.settings.Settings`
- Produces:
  - `core.settings.access.validate_setting_path(settings: Settings, path: str) -> tuple[str, str]`
  - `core.settings.access.apply_settings_overrides(settings: Settings, overrides: Iterable[tuple[str, Any]]) -> None`
  - `core.settings.access.parse_setting_assignment(text: str) -> tuple[str, str]`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_settings_overrides.py`:

```python
"""Validated (path, value) settings overrides shared by --set and named flags."""

from __future__ import annotations

import unittest

from core.settings import Settings
from core.settings.access import (
    apply_settings_overrides,
    parse_setting_assignment,
    validate_setting_path,
)


class ValidateSettingPathTests(unittest.TestCase):
    def setUp(self) -> None:
        self.settings = Settings()

    def test_accepts_known_path(self) -> None:
        self.assertEqual(
            validate_setting_path(self.settings, "process.use_gpu"),
            ("process", "use_gpu"),
        )

    def test_unknown_field_raises_value_error(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            validate_setting_path(self.settings, "process.use_gpau")
        self.assertIn("use_gpau", str(ctx.exception))

    def test_unknown_section_raises_value_error(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            validate_setting_path(self.settings, "nosuchsection.field")
        self.assertIn("nosuchsection", str(ctx.exception))

    def test_missing_dot_raises_value_error(self) -> None:
        with self.assertRaises(ValueError):
            validate_setting_path(self.settings, "use_gpu")

    def test_container_field_rejected(self) -> None:
        with self.assertRaises(ValueError):
            validate_setting_path(self.settings, "process.input_paths")


class ApplySettingsOverridesTests(unittest.TestCase):
    def setUp(self) -> None:
        self.settings = Settings()

    def test_applies_and_coerces(self) -> None:
        apply_settings_overrides(
            self.settings,
            [("process.use_gpu", "true"), ("process.sample_mode_duration", "45")],
        )
        self.assertIs(self.settings.process.use_gpu, True)
        self.assertEqual(self.settings.process.sample_mode_duration, 45)

    def test_coerces_enum_field_to_enum(self) -> None:
        apply_settings_overrides(self.settings, [("process.save_format", "FLAC")])
        self.assertEqual(self.settings.process.save_format, "FLAC")
        self.assertEqual(f"{self.settings.process.save_format.value}", "FLAC")

    def test_unknown_path_raises_before_any_write(self) -> None:
        with self.assertRaises(ValueError):
            apply_settings_overrides(
                self.settings, [("process.use_gpau", "true")]
            )
        self.assertFalse(hasattr(self.settings.process, "use_gpau"))

    def test_later_override_wins(self) -> None:
        apply_settings_overrides(
            self.settings, [("process.use_gpu", True), ("process.use_gpu", False)]
        )
        self.assertIs(self.settings.process.use_gpu, False)


class ParseSettingAssignmentTests(unittest.TestCase):
    def test_splits_on_first_equals(self) -> None:
        self.assertEqual(
            parse_setting_assignment("process.export_path=/tmp/a=b"),
            ("process.export_path", "/tmp/a=b"),
        )

    def test_missing_equals_raises(self) -> None:
        with self.assertRaises(ValueError):
            parse_setting_assignment("process.use_gpu")

    def test_empty_path_raises(self) -> None:
        with self.assertRaises(ValueError):
            parse_setting_assignment("=true")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m unittest tests.test_settings_overrides -v`
Expected: FAIL with `ImportError: cannot import name 'apply_settings_overrides' from 'core.settings.access'`

- [ ] **Step 3: Implement the helpers**

Append to `core/settings/access.py`, and add `from dataclasses import fields, is_dataclass` plus `Iterable` to the module imports:

```python
def _section_names(settings: Settings) -> list[str]:
    return sorted(
        f.name
        for f in fields(settings)
        if is_dataclass(getattr(settings, f.name, None))
    )


def validate_setting_path(settings: Settings, path: str) -> tuple[str, str]:
    """Split ``section.field`` and reject anything :class:`Settings` lacks.

    :func:`set_path` cannot do this itself: the settings sections are plain
    dataclasses without ``slots``, so ``setattr`` happily invents an unknown
    attribute instead of raising. Every caller that accepts a user-supplied
    path must come through here first.
    """
    section_name, sep, field_name = path.partition(".")
    if not sep or not section_name or not field_name:
        raise ValueError(f"invalid setting path {path!r}; expected 'section.field'")

    section = getattr(settings, section_name, None)
    if section is None or not is_dataclass(section):
        known = ", ".join(_section_names(settings))
        raise ValueError(
            f"unknown settings section {section_name!r}; known sections: {known}"
        )

    if field_name not in {f.name for f in fields(section)}:
        raise ValueError(
            f"unknown setting {path!r}; section {section_name!r} has no field "
            f"{field_name!r}"
        )

    if isinstance(getattr(section, field_name), (list, dict)):
        raise ValueError(
            f"setting {path!r} is a container and cannot be set from a single value"
        )

    return section_name, field_name


def apply_settings_overrides(
    settings: Settings, overrides: Iterable[tuple[str, Any]]
) -> None:
    """Apply validated ``(path, value)`` pairs in order (does not persist).

    Every path is validated before the first write, so a typo aborts the run
    instead of silently dropping the override.
    """
    pairs = list(overrides)
    for path, _value in pairs:
        validate_setting_path(settings, path)
    for path, value in pairs:
        set_path(settings, path, value)


def parse_setting_assignment(text: str) -> tuple[str, str]:
    """Parse one ``section.field=value`` token into a ``(path, value)`` pair."""
    path, sep, value = str(text).partition("=")
    path = path.strip()
    if not sep or not path:
        raise ValueError(
            f"invalid setting override {text!r}; expected section.field=value"
        )
    return path, value
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m unittest tests.test_settings_overrides -v`
Expected: PASS (12 tests)

- [ ] **Step 5: Run the full suite and the type checker**

```bash
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python -m basedpyright
```

Expected: all pass, zero diagnostics.

- [ ] **Step 6: Commit**

```bash
git add core/settings/access.py tests/test_settings_overrides.py
git commit -m "feat(settings): validated (path, value) overrides

set_path cannot reject unknown fields on its own — the sections are plain
dataclasses, so setattr invents attributes instead of raising. Validate
every user-supplied path up front."
```

---

### Task 3: Shared process flags

Named flags compile to the `(path, value)` pairs Task 2 validates. `build_settings` gains exactly one new parameter, not fifteen.

**Files:**
- Create: `cli/process_flags.py`, `cli/offline.py`
- Modify: `core/headless_run.py` (add `overrides=` to `build_settings`), `cli/separate.py`, `cli/bench.py`, `cli/main.py`
- Test: `tests/test_cli_process_flags.py`, `tests/test_cli.py` (benchmark forwarding, vocal-split offline)

**Interfaces:**
- Consumes: `core.settings.access.apply_settings_overrides`, `parse_setting_assignment`
- Produces:
  - `cli.process_flags.add_process_args(parser: argparse.ArgumentParser) -> None`
  - `cli.process_flags.collect_overrides(args: argparse.Namespace, *, resolved_vocal_splitter: Optional[str] = None) -> list[tuple[str, Any]]`
  - `cli.process_flags.overrides_to_argv(overrides: Sequence[tuple[str, Any]]) -> list[str]`
  - `cli.offline.catalogue_offline(enabled: bool) -> ContextManager[None]`
  - `core.headless_run.build_settings(..., overrides: Optional[Sequence[tuple[str, Any]]] = None)`
  - `core.headless_run.resolve_vocal_splitter(model_arg: str, settings: Settings, repo: Any) -> str`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_cli_process_flags.py`:

```python
"""Named process flags compile to validated (path, value) override pairs."""

from __future__ import annotations

import argparse
import unittest

from cli.process_flags import add_process_args, collect_overrides
from core.settings import Settings
from core.settings.access import apply_settings_overrides


def _parse(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="test")
    add_process_args(parser)
    return parser.parse_args(argv)


class CollectOverridesTests(unittest.TestCase):
    def test_no_flags_yields_no_overrides(self) -> None:
        self.assertEqual(collect_overrides(_parse([])), [])

    def test_cpu_and_gpu_are_mutually_exclusive(self) -> None:
        with self.assertRaises(SystemExit):
            _parse(["--cpu", "--gpu"])

    def test_gpu_maps_to_use_gpu_true(self) -> None:
        self.assertIn(("process.use_gpu", True), collect_overrides(_parse(["--gpu"])))

    def test_cpu_maps_to_use_gpu_false(self) -> None:
        self.assertIn(("process.use_gpu", False), collect_overrides(_parse(["--cpu"])))

    def test_no_autocast_maps_to_false(self) -> None:
        self.assertIn(
            ("process.autocast", False), collect_overrides(_parse(["--no-autocast"]))
        )

    def test_format_is_case_insensitive(self) -> None:
        self.assertIn(
            ("process.save_format", "FLAC"), collect_overrides(_parse(["--format", "flac"]))
        )

    def test_sample_seconds_maps_to_duration_and_enables_sample_mode(self) -> None:
        overrides = collect_overrides(_parse(["--sample-seconds", "12"]))
        self.assertIn(("process.sample_mode_duration", 12), overrides)
        self.assertIn(("process.sample_mode", True), overrides)

    def test_set_is_repeatable_and_last_wins(self) -> None:
        overrides = collect_overrides(
            _parse(["--set", "process.use_gpu=true", "--set", "process.use_gpu=false"])
        )
        settings = Settings()
        apply_settings_overrides(settings, overrides)
        self.assertIs(settings.process.use_gpu, False)

    def test_set_runs_after_named_flags(self) -> None:
        overrides = collect_overrides(
            _parse(["--cpu", "--set", "process.use_gpu=true"])
        )
        settings = Settings()
        apply_settings_overrides(settings, overrides)
        self.assertIs(settings.process.use_gpu, True)

    def test_set_runs_after_resolved_vocal_splitter(self) -> None:
        args = _parse([
            "--vocal-split", "Splitter X",
            "--set", "process.vocal_splitter_enabled=false",
        ])
        overrides = collect_overrides(
            args, resolved_vocal_splitter="MDX-Net: Splitter X"
        )
        settings = Settings()
        apply_settings_overrides(settings, overrides)
        self.assertEqual(settings.process.vocal_splitter, "MDX-Net: Splitter X")
        self.assertIs(settings.process.vocal_splitter_enabled, False)

    def test_bad_set_token_raises(self) -> None:
        with self.assertRaises(ValueError):
            collect_overrides(_parse(["--set", "nonsense"]))

    def test_every_named_flag_targets_a_real_setting(self) -> None:
        argv = [
            "--gpu", "--autocast", "--normalize", "--match-mix", "--sample",
            "--save-split-inst", "--format", "mp3", "--wav-type", "PCM_24",
            "--mp3-bitrate", "256k", "--flac-depth", "24-bit", "--device", "0",
            "--sample-seconds", "20",
        ]
        settings = Settings()
        apply_settings_overrides(settings, collect_overrides(_parse(argv)))
        self.assertIs(settings.process.use_gpu, True)
        self.assertEqual(settings.process.save_format, "MP3")
        self.assertEqual(settings.process.mp3_bitrate, "256k")
        self.assertEqual(settings.process.device, "0")


if __name__ == "__main__":
    unittest.main()
```

The last test is the important one: it round-trips every named flag through `apply_settings_overrides`, so a typo in the flag → path table fails the suite instead of silently no-opping in production.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m unittest tests.test_cli_process_flags -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'cli.process_flags'`

- [ ] **Step 3: Implement `cli/process_flags.py`**

```python
"""Process flags shared by ``separate`` and ``ensemble``.

Every named flag compiles to a ``(settings path, value)`` pair rather than a
``build_settings`` keyword argument, so named flags and ``--set`` share one
validation path (``core.settings.access.apply_settings_overrides``) and
``build_settings`` keeps a small signature.
"""

from __future__ import annotations

import argparse
from typing import Any, Optional, Sequence

from core.settings.coerce import enum_value
from core.settings.access import parse_setting_assignment
from core.types import FlacBitDepth, Mp3Bitrate, SaveFormat, WavType

# dest -> (settings path, value written when the flag is present)
_BOOL_FLAG_PATHS: dict[str, tuple[str, Any]] = {
    "cpu": ("process.use_gpu", False),
    "gpu": ("process.use_gpu", True),
    "autocast": ("process.autocast", True),
    "no_autocast": ("process.autocast", False),
    "normalize": ("process.normalization", True),
    "match_mix": ("process.match_mix_level", True),
    "sample": ("process.sample_mode", True),
    "save_split_inst": ("process.save_inst_vocal_splitter", True),
    "no_vocal_split": ("process.vocal_splitter_enabled", False),
}

# dest -> settings path, for flags whose value is written straight through
_VALUE_FLAG_PATHS: dict[str, str] = {
    "format": "process.save_format",
    "wav_type": "process.wav_type",
    "mp3_bitrate": "process.mp3_bitrate",
    "flac_depth": "process.flac_bit_depth",
    "device": "process.device",
    "sample_seconds": "process.sample_mode_duration",
}


def add_process_args(parser: argparse.ArgumentParser) -> None:
    """Attach the shared process flags to a subcommand parser."""
    gpu_group = parser.add_mutually_exclusive_group()
    gpu_group.add_argument(
        "--cpu", action="store_true", help="Force CPU (process.use_gpu=False)"
    )
    gpu_group.add_argument(
        "--gpu", action="store_true", help="Force GPU (process.use_gpu=True)"
    )

    autocast_group = parser.add_mutually_exclusive_group()
    autocast_group.add_argument(
        "--autocast", action="store_true", help="Enable autocast (UVR_AUTOCAST still wins)"
    )
    autocast_group.add_argument(
        "--no-autocast", action="store_true", help="Disable autocast"
    )

    parser.add_argument(
        "--device",
        default=None,
        metavar="ID",
        help="GPU device id from list_gpu_devices (e.g. 0, mps, directml)",
    )
    parser.add_argument(
        "--format",
        type=str.upper,
        choices=[fmt.value for fmt in SaveFormat],
        default=None,
        help="Export format (case-insensitive)",
    )
    parser.add_argument(
        "--wav-type",
        choices=[wav.value for wav in WavType],
        default=None,
        help="WAV sample format",
    )
    parser.add_argument(
        "--mp3-bitrate",
        choices=[rate.value for rate in Mp3Bitrate],
        default=None,
        help="MP3 bitrate",
    )
    parser.add_argument(
        "--flac-depth",
        choices=[depth.value for depth in FlacBitDepth],
        default=None,
        help="FLAC bit depth",
    )
    parser.add_argument(
        "--normalize", action="store_true", help="Normalize outputs"
    )
    parser.add_argument(
        "--match-mix", action="store_true", help="Match the mix level"
    )
    parser.add_argument(
        "--sample", action="store_true", help="Sample mode (short excerpt only)"
    )
    parser.add_argument(
        "--sample-seconds",
        type=int,
        default=None,
        metavar="N",
        help="Sample-mode duration in seconds",
    )

    split_group = parser.add_mutually_exclusive_group()
    split_group.add_argument(
        "--vocal-split",
        default=None,
        metavar="MODEL",
        help=(
            "Enable the vocal splitter with this karaoke/BV model. The value is "
            "required — `--vocal-split MODEL`, never a bare flag."
        ),
    )
    split_group.add_argument(
        "--no-vocal-split",
        action="store_true",
        help="Disable the vocal splitter for this run",
    )
    parser.add_argument(
        "--save-split-inst",
        action="store_true",
        help="Also save the vocal splitter's instrumental",
    )

    parser.add_argument(
        "--set",
        action="append",
        default=None,
        dest="set_items",
        metavar="section.field=value",
        help=(
            "Escape hatch for any typed setting; repeatable. Applied after the "
            "named flags above, so a later --set wins."
        ),
    )


def collect_overrides(
    args: argparse.Namespace,
    *,
    resolved_vocal_splitter: Optional[str] = None,
) -> list[tuple[str, Any]]:
    """Compile parsed flags into ordered ``(path, value)`` override pairs.

    ``--set`` is appended last so it can override every named flag, including
    the resolved ``--vocal-split`` pair supplied by the command module.
    """
    overrides: list[tuple[str, Any]] = []

    for dest, (path, value) in _BOOL_FLAG_PATHS.items():
        if getattr(args, dest, False):
            overrides.append((path, value))

    for dest, path in _VALUE_FLAG_PATHS.items():
        value = getattr(args, dest, None)
        if value is not None:
            overrides.append((path, value))

    if resolved_vocal_splitter is not None:
        overrides.extend([
            ("process.vocal_splitter", resolved_vocal_splitter),
            ("process.vocal_splitter_enabled", True),
        ])

    if getattr(args, "sample_seconds", None) is not None:
        # Duration without --sample would otherwise be stored and ignored.
        if not getattr(args, "sample", False):
            overrides.append(("process.sample_mode", True))

    for item in getattr(args, "set_items", None) or []:
        overrides.append(parse_setting_assignment(item))

    return overrides


def overrides_to_argv(overrides: Sequence[tuple[str, Any]]) -> list[str]:
    """Serialize override pairs for a ``separate`` subprocess."""
    argv: list[str] = []
    for path, raw_value in overrides:
        value = enum_value(raw_value)
        text = str(value).lower() if isinstance(value, bool) else str(value)
        argv.extend(["--set", f"{path}={text}"])
    return argv
```

Update the function signature to accept the keyword-only
`resolved_vocal_splitter: Optional[str] = None`. Note `--vocal-split MODEL`
takes a required value. A bare `nargs="?"` form in front of the `inputs`
positional (`nargs="+"`) would let `separate --vocal-split song.wav` swallow
the input file as the model name.

- [ ] **Step 4: Add `overrides=` to `build_settings`**

In `core/headless_run.py`, add the parameter to the signature after `long_chunk_overlap`:

```python
    overrides: Optional[Sequence[tuple[str, Any]]] = None,
```

and apply it at the very end of the body, immediately before `return settings`:

```python
    if overrides:
        from .settings.access import apply_settings_overrides

        apply_settings_overrides(settings, overrides)

    return settings
```

Applying last means explicit CLI flags beat both the loaded `settings.json` and the `stable_names` block. Keep the import local — `core.settings.access` imports `core.settings.flat_map`, and `headless_run` should stay cheap to import.

- [ ] **Step 5: Create `cli/offline.py`**

`karaoke_model_list` → `list_vr_model_tags` / `list_mdx_model_tags` → `map_basenames_to_display` → `_merged_for_display()` is a live catalogue fetch (30s timeout each). `--vocal-split` must not pay that cost by default. Tasks 6 and 7 reuse this helper.

Both disable flags are read at call time (`os.environ.get` inside a function), so setting them before the repository is touched works; `scripts/model_sweep.py:347` already relies on the same property.

```python
"""Catalogue-network guard for read-only CLI resolution.

``core.model_display._merged_for_display()`` fetches the politrees and
mvsepless catalogues over the network (30s timeout each). Commands that only
need display labels default to offline so they stay fast and hermetic; both
disable flags are read at call time, so setting them here takes effect.

``--online`` means "do not force these flags on". It does **not** clear
``UVR_DISABLE_POLITREES`` / ``UVR_DISABLE_MVSEPLESS`` if the caller already
set them.
"""

from __future__ import annotations

import contextlib
import os
from typing import Iterator

_OFFLINE_ENV = ("UVR_DISABLE_POLITREES", "UVR_DISABLE_MVSEPLESS")


@contextlib.contextmanager
def catalogue_offline(enabled: bool = True) -> Iterator[None]:
    """Disable both catalogue network sources for the duration of the block."""
    if not enabled:
        yield
        return
    previous = {name: os.environ.get(name) for name in _OFFLINE_ENV}
    for name in _OFFLINE_ENV:
        os.environ[name] = "1"
    try:
        yield
    finally:
        for name, value in previous.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
```

- [ ] **Step 6: Wire the flags into `separate`**

In `cli/separate.py`, remove the `--cpu` argument from `add_separate_args` (it now comes from `add_process_args`, as half of the `--cpu`/`--gpu` group), add `from .process_flags import add_process_args, collect_overrides`, and call `add_process_args(parser)` at the end of `add_separate_args`.

`bench-ab` also calls `add_separate_args`, so it intentionally exposes the
same process flags. Do not leave those accepted flags inert. Extend
`cli.bench.build_separate_argv` with `overrides` and `vocal_split` parameters;
append `overrides_to_argv(overrides)` and then `--vocal-split MODEL` when set.
In `cmd_bench_ab`, pass `collect_overrides(args)` plus `args.vocal_split` into
both child legs. The child command resolves the splitter, while every other
named flag and repeatable `--set` retains the documented ordering. Add a parser
and subprocess-argv test covering at least `--gpu`, `--format flac`, a
repeatable `--set`, `--vocal-split`, and the two long-chunk flags. The test must
assert that every accepted option appears in each child argv; parsing without
forwarding is a failure.

In `cmd_separate`, remove the `use_gpu=False if args.cpu else None,` line. Build
the base settings first without process overrides, resolve the optional vocal
splitter against those settings **inside** `catalogue_offline`, then apply
**one final ordered override list**:

```python
    try:
        resolved_splitter = None
        if args.vocal_split:
            from core.model_data import ModelRepository

            from .offline import catalogue_offline

            with catalogue_offline(True):
                resolved_splitter = resolve_vocal_splitter(
                    args.vocal_split, settings, ModelRepository()
                )
        apply_settings_overrides(
            settings,
            collect_overrides(
                args, resolved_vocal_splitter=resolved_splitter
            ),
        )
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
```

Import `apply_settings_overrides` from `core.settings.access`. This ordering is
intentional: named flags, including the resolved splitter, come first and
repeatable `--set` pairs come last. Thus
`--vocal-split X --set process.vocal_splitter_enabled=false` really does leave
the splitter disabled, matching the help text. Add tests for both splitter
pairs and this precedence case.

Also add a command-level test that `--vocal-split` resolution sees both
disable flags set to `"1"` (spy `karaoke_model_list` or the env from inside a
patched `resolve_vocal_splitter`). `karaoke_model_list` reaches
`_merged_for_display()`; leaving this unguarded is a 30s stall on a machine
with no local catalogue cache.

- [ ] **Step 7: Add `resolve_vocal_splitter` to `core/headless_run.py`**

```python
def resolve_vocal_splitter(model_arg: str, settings: Settings, repo: Any) -> str:
    """Resolve a CLI vocal-splitter token against the karaoke/BV model pool."""
    raw = str(model_arg).strip()
    if not raw:
        raise ValueError("--vocal-split value is empty")

    pool = list(repo.karaoke_model_list(settings))
    if not pool:
        raise ValueError(
            "no karaoke or backing-vocal models are installed; "
            "download one before using --vocal-split"
        )
    if raw in pool:
        return raw

    query = _normalize_model_query(raw)
    matches = [tag for tag in pool if query and query in _normalize_model_query(tag)]
    unique = list(dict.fromkeys(matches))
    if len(unique) == 1:
        return unique[0]
    if len(unique) > 1:
        preview = ", ".join(repr(name) for name in unique[:6])
        raise ValueError(f"ambiguous --vocal-split {raw!r}; matches: {preview}")
    raise ValueError(
        f"unknown --vocal-split {raw!r}; installed splitters: "
        f"{', '.join(repr(t) for t in pool[:6])}"
    )
```

- [ ] **Step 8: Run the tests to verify they pass**

```bash
.venv/bin/python -m unittest tests.test_cli_process_flags -v
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python -m basedpyright
```

Expected: all pass, zero diagnostics.

- [ ] **Step 9: Verify the argparse footgun is closed**

```bash
.venv/bin/python -m cli separate --vocal-split song.wav -o /tmp/x
```

Expected: argparse errors on the missing `-o` value or the missing `inputs` positional — **not** a run that treats `song.wav` as a model name.

- [ ] **Step 10: Commit**

```bash
git add cli/process_flags.py cli/offline.py cli/separate.py cli/bench.py cli/main.py \
  core/headless_run.py tests/test_cli_process_flags.py tests/test_cli.py
git commit -m "feat(cli): shared process flags via validated override pairs"
```

---

### Task 4: Progress, `--quiet`, and `--json`

**Files:**
- Create: `cli/reporting.py`
- Modify: `core/headless_run.py` (progress plumbing), `cli/separate.py`, `cli/main.py`, `cli/bench.py`
- Test: `tests/test_cli.py` (extend)

**Interfaces:**
- Consumes: `core.job_runner.JobCallbacks.on_progress`
- Produces:
  - `cli.reporting.make_progress_printer(stream) -> Optional[Callable[..., None]]`
  - `cli.reporting.add_reporting_args(parser: argparse.ArgumentParser) -> None`
  - `cli.reporting.emit_json(payload: dict[str, Any]) -> None`
  - `cli.reporting.fail(args, message: str, *, exit_code: int, exc: Optional[BaseException] = None) -> int`
  - `core.headless_run.run_separation_sync(..., on_progress=None)` and the same on `run_ensemble_sync` / `_run_job`

- [ ] **Step 1: Resolve the `--json` collision**

`bench-ab` already defines `--json PATH`. Adding a shared `--json` to the same parser raises `argparse.ArgumentError: conflicting option string: --json` at parser-construction time, killing every invocation. Make `--json` a uniform boolean across all subcommands and rename bench-ab's file output:

In `cli/main.py`, change the bench-ab argument from `--json` to:

```python
    bench.add_argument(
        "--json-out",
        default=None,
        metavar="PATH",
        help="Optional path to write the JSON summary (was --json before v5.7)",
    )
```

In `cli/bench.py`, change `if args.json:` to `if args.json_out:` and both `args.json` references in the trailing print to `args.json_out`.

Then wire the now-boolean `args.json` and `args.quiet` into benchmark reporting;
do not merely let the parser accept them:

- Extend `build_separate_argv` with a `quiet` parameter and append `--quiet`
  for quiet or JSON benchmark legs.
- Suppress the per-leg banners and the human summary when `args.json` is true.
  Run child subprocesses with `stdout=subprocess.DEVNULL` in that mode so their
  own success summaries cannot contaminate the parent document; leave stderr
  inherited so failures remain visible.
- Print `json.dumps(payload, indent=2)` once on stdout for `args.json`.
  Independently write the same payload to `args.json_out` when requested.
- `--quiet` without `--json` suppresses engine chatter in each child but keeps
  the benchmark's final human summary, matching the reporting help text.

Add a command-level test that captures the complete stdout of `bench-ab
--json`, parses it with `json.loads`, asserts both child argvs contain
`--quiet`, and asserts both subprocess calls use `stdout=subprocess.DEVNULL`.
Retain the existing `--json-out` file test as a separate assertion so the two
meanings cannot regress into another option collision.

- [ ] **Step 2: Write the failing tests**

Append to `tests/test_cli.py`:

```python
class ReportingFlagTests(unittest.TestCase):
    def test_json_is_boolean_on_separate(self) -> None:
        from cli.main import build_parser

        args = build_parser().parse_args(["separate", "a.wav", "-o", "/tmp/o", "--json"])
        self.assertIs(args.json, True)

    def test_bench_ab_uses_json_out_for_the_file(self) -> None:
        from cli.main import build_parser

        args = build_parser().parse_args(
            ["bench-ab", "a.wav", "-o", "/tmp/o", "--env", "A=1", "--env", "B=2",
             "--json-out", "/tmp/s.json"]
        )
        self.assertEqual(args.json_out, "/tmp/s.json")
        self.assertIs(args.json, False)

    def test_parser_builds_without_conflicts(self) -> None:
        from cli.main import build_parser

        build_parser()  # raises argparse.ArgumentError on a duplicate option string

class ProgressPrinterTests(unittest.TestCase):
    def test_none_when_not_a_tty(self) -> None:
        import io

        from cli.reporting import make_progress_printer

        self.assertIsNone(make_progress_printer(io.StringIO()))

    def test_writes_carriage_returned_line_on_a_tty(self) -> None:
        from cli.reporting import make_progress_printer

        class _Tty(io.StringIO):
            def isatty(self) -> bool:
                return True

        stream = _Tty()
        printer = make_progress_printer(stream)
        self.assertIsNotNone(printer)
        assert printer is not None
        printer(0.5, detail="MDX pass 1/2")
        written = stream.getvalue()
        self.assertIn("50%", written)
        self.assertIn("MDX pass 1/2", written)
        self.assertTrue(written.startswith("\r"))

    def test_combine_kwargs_appear_in_the_line(self) -> None:
        import io

        from cli.reporting import make_progress_printer

        class _Tty(io.StringIO):
            def isatty(self) -> bool:
                return True

        stream = _Tty()
        printer = make_progress_printer(stream)
        assert printer is not None
        printer(0.8, combine_index=1, combine_total=3, detail="stems")
        self.assertIn("combine 1/3", stream.getvalue())
```

Add `import io` to the module imports.

Also add a command-level test for
`separate ... --json --print-settings`: patch dependency checking, filesystem,
`build_settings`, and `run_separation_sync`; capture stdout; assert that
`json.loads(stdout)` succeeds on the whole stream, the result contains a
nested `settings` object, and `run_separation_sync` received
`print_console=False`. This test guards both sources of JSON contamination
(engine console text and a second settings document).

And a failure-path test: `separate missing.wav -o /tmp/o --json` (patch
`isfile` to False, or use a path that does not exist); captured stdout is one
JSON object with `ok is False` and `error.message` mentioning the path; stderr
still contains `error:`.

- [ ] **Step 3: Run the tests to verify they fail**

Run: `.venv/bin/python -m unittest tests.test_cli -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'cli.reporting'`

- [ ] **Step 4: Implement `cli/reporting.py`**

```python
"""Console reporting for the headless CLI: progress line, --quiet, --json."""

from __future__ import annotations

import argparse
import sys
from typing import Any, Callable, Optional, TextIO


def add_reporting_args(parser: argparse.ArgumentParser) -> None:
    """Attach --quiet and --json to a subcommand parser."""
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress engine console output; errors and the summary still print",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print a machine-readable result object on stdout",
    )


def make_progress_printer(
    stream: Optional[TextIO] = None,
) -> Optional[Callable[..., None]]:
    """Return an ``on_progress`` callback, or ``None`` when not on a TTY.

    Progress goes to stderr so ``--json`` stdout stays parseable. The callback
    runs on the JobRunner worker thread; it only touches a stream, never a
    widget.
    """
    out = stream if stream is not None else sys.stderr
    if not getattr(out, "isatty", lambda: False)():
        return None

    def on_progress(fraction: float, **meta: Any) -> None:
        pct = max(0.0, min(1.0, float(fraction))) * 100.0
        detail = str(meta.get("detail") or "")
        pass_index = meta.get("pass_index")
        pass_total = meta.get("pass_total")
        if pass_index is not None and pass_total:
            detail = f"pass {pass_index}/{pass_total} {detail}".strip()
        combine_index = meta.get("combine_index")
        combine_total = meta.get("combine_total")
        if combine_index is not None and combine_total:
            detail = f"combine {combine_index}/{combine_total} {detail}".strip()
        out.write(f"\r{pct:5.1f}%  {detail[:60]:<60}")
        out.flush()

    return on_progress


def finish_progress(stream: Optional[TextIO] = None) -> None:
    """Close out the in-place progress line with a newline."""
    out = stream if stream is not None else sys.stderr
    if getattr(out, "isatty", lambda: False)():
        out.write("\n")
        out.flush()


def emit_json(payload: dict[str, Any]) -> None:
    """Write one JSON document to stdout. The only function allowed to print there under ``--json``."""
    import json

    print(json.dumps(payload, indent=2))


def fail(
    args: argparse.Namespace,
    message: str,
    *,
    exit_code: int,
    exc: Optional[BaseException] = None,
) -> int:
    """Print a human error on stderr; under ``--json`` also emit one failure document."""
    print(f"error: {message}", file=sys.stderr)
    if getattr(args, "json", False):
        error: dict[str, Any] = {"message": message}
        if exc is not None:
            error["type"] = type(exc).__name__
        emit_json({"ok": False, "error": error})
    return exit_code
```

`fail` is the only return-2 / return-1 helper the run commands should use after `args` exists. Argparse usage errors still happen before `func()` and stay argparse-shaped.

Add a test: `separate ... --json` with a missing input file; captured stdout is one JSON object with `ok is False` and `error.message` mentioning the path; stderr still contains `error:`.

Also extend `ProgressPrinterTests` so a TTY callback invoked with `combine_index=1, combine_total=3` writes `combine 1/3`.

- [ ] **Step 5: Plumb `on_progress` through `core/headless_run.py`**

Add `on_progress: Optional[Callable[..., None]] = None` to the keyword-only parameters of `_run_job`, `run_separation_sync` and `run_ensemble_sync`, pass it down from both public wrappers, and include it in the `JobCallbacks` construction inside `_run_job`:

```python
    callbacks = JobCallbacks(
        on_progress=on_progress,
        on_console=on_console,
        on_complete=on_complete,
        on_stopped=on_stopped,
        on_error=on_error,
    )
```

Add `Callable` to the `typing` import. Leave `on_oom_choice` unset: `JobCallbacks.request_oom_choice` already returns `OOM_CHOICE_AUTO` when it is unbound, which is the behaviour headless runs want.

- [ ] **Step 6: Wire reporting into `separate`**

In `cli/separate.py`, call `add_reporting_args(parser)` from `add_separate_args`, then in `cmd_separate`:

```python
    machine_output = bool(args.json)
    on_progress = None if args.quiet else make_progress_printer()
    result = run_separation_sync(
        settings,
        [os.path.abspath(p) for p in args.inputs],
        # JSON owns stdout. Engine console text would corrupt the document.
        print_console=not (args.quiet or machine_output),
        on_progress=on_progress,
    )
    if on_progress is not None:
        finish_progress()
```

and replace the two trailing `print` lines **and** the existing error returns
(`result.error`, `result.stopped`, missing input, `ValueError` from
`build_settings` / overrides) with `fail(...)` / `emit_json(...)`:

```python
    if result.error is not None:
        return fail(
            args,
            f"{type(result.error).__name__}: {result.error}",
            exit_code=1,
            exc=result.error,
        )
    if result.stopped:
        return fail(args, "separation stopped", exit_code=1)

    if args.json:
        payload = {
            "ok": True,
            "elapsed_s": result.elapsed_s,
            "export_path": result.export_path,
        }
        if args.print_settings:
            payload["settings"] = settings_summary(settings)
        emit_json(payload)
    else:
        print(f"elapsed_s={result.elapsed_s:.3f}")
        print(f"export_path={result.export_path}")
    return 0
```

Human `error:` lines stay on stderr regardless of `--quiet`. Under `--json`,
stdout is still exactly one parseable document — success *or* failure.
Move the earlier standalone `if args.print_settings: print(...)` behind
`if args.print_settings and not args.json`. `--json` implies quiet engine-console
output but may still show TTY progress on stderr. Add a command-level test that
runs `json.loads()` over the **entire** captured stdout for both the success
path and a missing-input failure, not merely a parser test.

- [ ] **Step 7: Run the tests to verify they pass**

```bash
.venv/bin/python -m unittest tests.test_cli -v
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python -m basedpyright
```

Expected: all pass, zero diagnostics.

- [ ] **Step 8: Commit**

```bash
git add cli/reporting.py cli/separate.py cli/main.py cli/bench.py core/headless_run.py tests/test_cli.py
git commit -m "feat(cli): TTY progress, --quiet, and a uniform boolean --json

bench-ab's file output moves to --json-out; a shared boolean --json would
otherwise collide with it at parser-construction time."
```

---

### Task 4.5: Cooperative Ctrl-C / SIGTERM

Task 1 copied `_run_job`'s `except KeyboardInterrupt: stop(force=True); raise`. That force-kills the worker, dumps a traceback, skips `fail()`, and leaves `--json` with empty stdout. Replace it with a two-stage stop that returns `HeadlessResult(stopped=True)`.

`scripts/model_sweep.py` already reads `outcome.stopped` and treats it as `FAIL(stopped)`. It does **not** need a code change. Do not re-raise; a propagating `KeyboardInterrupt` is what the sweep's `except BaseException` used to record as `error_type`, and `stopped=True` is the better signal.

**Files:**
- Modify: `core/headless_run.py` (`HeadlessResult`, `_run_job`), `cli/reporting.py` (`fail` gains `extra=`), `cli/separate.py`, `cli/bench.py`
- Test: `tests/test_headless_run.py` (extend), `tests/test_cli.py` (extend)

**Interfaces:**
- Consumes: `JobRunner.stop(force=...)`, `signal.SIGINT` / `signal.SIGTERM`
- Produces:
  - `HeadlessResult.interrupted: bool` (True when the stop came from a signal / KeyboardInterrupt)
  - `cli.reporting.fail(..., extra: Optional[dict[str, Any]] = None) -> int`
  - `_run_job` returns normally on interrupt; it does not raise `KeyboardInterrupt`

- [ ] **Step 1: Write the failing library tests**

Append to `tests/test_headless_run.py`:

```python
class _InterruptRunner:
    """JobRunner stand-in: start hangs until stop() fires on_stopped."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._thread = None
        self._alive = True
        self.stops: list[bool] = []
        self._callbacks: Any = None

    def is_running(self) -> bool:
        return self._alive

    def start(self, input_paths: Sequence[str], callbacks: Any) -> None:
        self._callbacks = callbacks

    def stop(self, *, force: bool = False) -> None:
        self.stops.append(force)
        self._alive = False
        if self._callbacks is not None:
            self._callbacks.stopped()

    def release_inference_memory(self, **kwargs: Any) -> None:
        pass


class InterruptTests(unittest.TestCase):
    def setUp(self) -> None:
        self.settings = Settings()
        self.settings.process.export_path = "/tmp/out"

    def test_keyboard_interrupt_returns_stopped_not_raised(self) -> None:
        runner = _InterruptRunner(self.settings)

        def fake_event() -> Any:
            class _Evt:
                def __init__(self) -> None:
                    self._set = False
                    self.waits = 0

                def set(self) -> None:
                    self._set = True

                def is_set(self) -> bool:
                    return self._set

                def wait(self, timeout: Any = None) -> bool:
                    self.waits += 1
                    if self._set:
                        return True
                    if self.waits == 1:
                        raise KeyboardInterrupt()
                    return True

            return _Evt()

        with mock.patch("core.headless_run.JobRunner", lambda settings: runner), \
             mock.patch("core.headless_run.threading.Event", fake_event):
            result = run_separation_sync(
                self.settings, ["/tmp/in.wav"], print_console=False
            )
        self.assertTrue(result.stopped)
        self.assertTrue(result.interrupted)
        self.assertTrue(result.ok is False)
        self.assertEqual(runner.stops, [False])

    def test_second_interrupt_forces_stop(self) -> None:
        runner = _InterruptRunner(self.settings)

        def fake_event() -> Any:
            class _Evt:
                def __init__(self) -> None:
                    self._set = False
                    self.waits = 0

                def set(self) -> None:
                    self._set = True

                def is_set(self) -> bool:
                    return self._set

                def wait(self, timeout: Any = None) -> bool:
                    self.waits += 1
                    if self._set:
                        return True
                    if self.waits == 1:
                        raise KeyboardInterrupt()
                    if self.waits == 2:
                        raise KeyboardInterrupt()
                    return True

            return _Evt()

        with mock.patch("core.headless_run.JobRunner", lambda settings: runner), \
             mock.patch("core.headless_run.threading.Event", fake_event):
            result = run_separation_sync(
                self.settings, ["/tmp/in.wav"], print_console=False
            )
        self.assertTrue(result.stopped)
        self.assertEqual(runner.stops, [False, True])

    def test_signal_handler_is_restored(self) -> None:
        import signal as signalmod

        previous = signalmod.getsignal(signalmod.SIGINT)
        runner = _InterruptRunner(self.settings)
        with mock.patch("core.headless_run.JobRunner", lambda settings: runner):
            # Completes immediately via the fake start → we still need
            # on_complete. Use the existing complete-on-start fake for restore.
            runner.start = (  # type: ignore[method-assign]
                lambda paths, callbacks: callbacks.complete()
            )
            run_separation_sync(self.settings, ["/tmp/in.wav"], print_console=False)
        self.assertEqual(signalmod.getsignal(signalmod.SIGINT), previous)
```

Import `run_separation_sync` if the module does not already (Task 1 moved `BuildSettingsTests` here; add the name to that import). `_InterruptRunner.start` must not call `complete()` — the wait loop is what receives the interrupt.

The third test uses a start-that-completes so the wait loop may not run; the `finally` that restores `SIGINT` must still run. If `test_signal_handler_is_restored` is awkward to wire through `_InterruptRunner`, a one-off fake whose `start` calls `callbacks.complete()` immediately is enough — the assertion is only that `signal.getsignal(SIGINT)` after `run_separation_sync` equals the value from before the call.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m unittest tests.test_headless_run.InterruptTests -v`
Expected: FAIL — `KeyboardInterrupt` escapes, or `interrupted` is missing on `HeadlessResult`.

- [ ] **Step 3: Change `_run_job`**

Add `interrupted: bool = False` to `HeadlessResult`. In `_run_job`, after `runner = JobRunner(settings)` and **before** `start`, install handlers and swallow KeyboardInterrupt:

```python
    interrupts = {"count": 0}

    def _request_stop(*, force: bool) -> None:
        interrupts["count"] += 1
        use_force = force or interrupts["count"] >= 2
        hint = "forcing stop" if use_force else "stopping… (Ctrl-C again to force)"
        print(f"\n{hint}", file=sys.stderr)
        try:
            runner.stop(force=use_force)
        except Exception:
            pass

    def _on_signal(signum: int, frame: Any) -> None:
        _request_stop(force=False)

    prev_int = signal.getsignal(signal.SIGINT)
    prev_term: Any = None
    signal.signal(signal.SIGINT, _on_signal)
    if hasattr(signal, "SIGTERM"):
        prev_term = signal.getsignal(signal.SIGTERM)
        try:
            signal.signal(signal.SIGTERM, _on_signal)
        except (OSError, ValueError, AttributeError):
            prev_term = None

    try:
        getattr(runner, start_attr)(list(input_paths), callbacks)
        while not done.wait(timeout=0.25):
            if not runner.is_running() and not done.is_set():
                done.set()
                break
            if join_timeout is not None and (time.perf_counter() - started) > join_timeout:
                runner.stop(force=True)
                raise TimeoutError(f"separation exceeded {join_timeout:.0f}s")
    except KeyboardInterrupt:
        _request_stop(force=False)
        try:
            if not done.wait(timeout=5.0):
                _request_stop(force=True)
                done.wait(timeout=2.0)
        except KeyboardInterrupt:
            _request_stop(force=True)
            done.wait(timeout=2.0)
    finally:
        try:
            signal.signal(signal.SIGINT, prev_int)
            if prev_term is not None:
                signal.signal(signal.SIGTERM, prev_term)
        except (OSError, ValueError, AttributeError):
            pass
        thread = getattr(runner, "_thread", None)
        if thread is not None and thread.is_alive():
            thread.join(timeout=join_timeout if join_timeout else None)
        try:
            runner.release_inference_memory(clear_weight_cache=False)
        except Exception:
            pass

    if interrupts["count"]:
        outcome["stopped"] = True
```

Pass `interrupted=bool(interrupts["count"])` into `HeadlessResult`. Add `import signal` next to the existing `sys` / `threading` imports in `core/headless_run.py`.

The signal handler only sets the stop flag via `JobRunner.stop`. It does not raise. Python's default SIGINT handler (which raises `KeyboardInterrupt`) is replaced for the duration of the run, then restored. The `except KeyboardInterrupt` branch is the fallback for tests and for any nested code that restores the default handler.

Do **not** `raise` after the wait. The CLI (and model_sweep) must observe `result.stopped`.

- [ ] **Step 4: Extend `fail()` and wire the CLI**

In `cli/reporting.py`, add `extra: Optional[dict[str, Any]] = None` to `fail`. Merge it into the JSON payload after `error`:

```python
        payload: dict[str, Any] = {"ok": False, "error": error}
        if extra:
            payload.update(extra)
        emit_json(payload)
```

In `cli/separate.py`, change the stopped branch to:

```python
    if result.stopped:
        return fail(
            args,
            "separation stopped",
            exit_code=130,
            extra={"stopped": True},
        )
```

In `cli/bench.py`, treat a child exit of 130 as an interrupt, and catch `KeyboardInterrupt` around `subprocess.run`:

```python
        try:
            proc = subprocess.run(argv, env=env, check=False, **run_kwargs)
        except KeyboardInterrupt:
            return fail(
                args,
                "bench-ab interrupted",
                exit_code=130,
                extra={"stopped": True},
            )
        if proc.returncode == 130:
            return fail(
                args,
                f"{label} interrupted",
                exit_code=130,
                extra={"stopped": True},
            )
```

(`run_kwargs` is `{"stdout": subprocess.DEVNULL}` in JSON mode from Task 4; empty otherwise.) Ctrl-C is delivered to the foreground process group, so the child `separate` performs the two-stage stop and exits 130; the parent must not start leg B and must not emit a success document.

- [ ] **Step 5: CLI tests**

In `tests/test_cli.py`:

```python
    def test_stopped_run_exits_130_and_emits_json(self) -> None:
        from cli.main import main
        from core.headless_run import HeadlessResult

        result = HeadlessResult(
            ok=False,
            elapsed_s=0.5,
            export_path="/tmp/o",
            stopped=True,
            interrupted=True,
        )
        buf = io.StringIO()
        err = io.StringIO()
        with mock.patch("cli.separate.check_runtime_deps", return_value=None), \
             mock.patch("cli.separate.os.path.isfile", return_value=True), \
             mock.patch("cli.separate.os.makedirs"), \
             mock.patch("cli.separate.build_settings", return_value=Settings()), \
             mock.patch("cli.separate.run_separation_sync", return_value=result), \
             mock.patch("sys.stdout", buf), \
             mock.patch("sys.stderr", err):
            code = main(["separate", "a.wav", "-o", "/tmp/o", "--json"])
        self.assertEqual(code, 130)
        payload = json.loads(buf.getvalue())
        self.assertFalse(payload["ok"])
        self.assertTrue(payload["stopped"])
        self.assertIn("stopped", err.getvalue().lower())
```

Add a parser-level test that `bench-ab` child returncode 130 does not run the second leg: patch `subprocess.run` so the first call returns `returncode=130`, assert `call_count == 1` and `main(...) == 130`.

- [ ] **Step 6: Run the tests to verify they pass**

```bash
.venv/bin/python -m unittest tests.test_headless_run.InterruptTests tests.test_cli -v
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python -m basedpyright
```

Expected: all pass, zero diagnostics.

- [ ] **Step 7: Commit**

```bash
git add core/headless_run.py cli/reporting.py cli/separate.py cli/bench.py \
  tests/test_headless_run.py tests/test_cli.py
git commit -m "feat(cli): cooperative Ctrl-C, JSON-safe, exit 130

First SIGINT/SIGTERM asks JobRunner to unwind through ProcessStopped;
a second forces the worker thread. run_separation_sync returns
HeadlessResult(stopped=True) instead of raising KeyboardInterrupt."
```

---

### Task 5: Ensemble library helpers in `core`

No CLI surface yet — just the `core` helpers the `ensemble` command needs, tested against a fake repository.

**Files:**
- Modify: `core/headless_run.py`
- Test: `tests/test_headless_ensemble.py` (extend)

**Interfaces:**
- Consumes: `core.model_data.load_ensemble`, `list_saved_ensembles`; `core.ensemble_presets.load_curated_ensemble`, `list_curated_ensembles`, `curated_combo_label`, `curated_id_from_combo_label`, `resolve_member_tags`; `core.stems.coerce_ensemble_pair`; `ModelRepository.all_model_tags`
- Produces:
  - `core.headless_run.apply_saved_ensemble(settings: Settings, name: str, *, repo: Optional[Any] = None) -> None`
  - `core.headless_run.resolve_ensemble_members(tokens: Sequence[str], repo: Optional[Any] = None) -> list[str]`
  - `METHOD_ALIASES` gains `"ensemble"` and `"ensemble mode"`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_headless_ensemble.py`:

```python
from bundled.constants import MAX_MIN, MDX_ARCH_TYPE, ENSEMBLE_PARTITION, VR_ARCH_TYPE
from core.headless_run import (
    apply_saved_ensemble,
    resolve_ensemble_members,
    resolve_method,
)
from core.stems import EnsemblePair


class _FakeRepo:
    """Minimal stand-in for ModelRepository — no disk, no network."""

    def all_model_tags(self) -> list[str]:
        return [
            f"{MDX_ARCH_TYPE}{ENSEMBLE_PARTITION}Kim Vocal 2",
            f"{MDX_ARCH_TYPE}{ENSEMBLE_PARTITION}Inst HQ 3",
            f"{VR_ARCH_TYPE}{ENSEMBLE_PARTITION}UVR-DeEcho-DeReverb",
        ]


class ResolveEnsembleMembersTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repo = _FakeRepo()

    def test_exact_tag_passes_through(self) -> None:
        tag = f"{MDX_ARCH_TYPE}{ENSEMBLE_PARTITION}Kim Vocal 2"
        self.assertEqual(resolve_ensemble_members([tag], self.repo), [tag])

    def test_unique_substring_resolves(self) -> None:
        self.assertEqual(
            resolve_ensemble_members(["kimvocal2"], self.repo),
            [f"{MDX_ARCH_TYPE}{ENSEMBLE_PARTITION}Kim Vocal 2"],
        )

    def test_ambiguous_token_raises(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            resolve_ensemble_members(["a"], self.repo)
        self.assertIn("ambiguous", str(ctx.exception))

    def test_unknown_token_raises(self) -> None:
        with self.assertRaises(ValueError):
            resolve_ensemble_members(["no-such-model"], self.repo)

    def test_duplicates_collapse_preserving_order(self) -> None:
        members = resolve_ensemble_members(["kimvocal2", "insthq3", "kimvocal2"], self.repo)
        self.assertEqual(
            members,
            [
                f"{MDX_ARCH_TYPE}{ENSEMBLE_PARTITION}Kim Vocal 2",
                f"{MDX_ARCH_TYPE}{ENSEMBLE_PARTITION}Inst HQ 3",
            ],
        )


class ApplySavedEnsembleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.settings = Settings()

    def test_applies_every_field(self) -> None:
        data = {
            "ensemble_main_stem": "vocals_instrumental",
            "ensemble_type": MAX_MIN,
            "selected_models": ["MDX-Net: A", "MDX-Net: B"],
        }
        with mock.patch("core.model_data.load_ensemble", return_value=data):
            apply_saved_ensemble(self.settings, "My Mix")
        self.assertEqual(self.settings.ensemble.main_stem, EnsemblePair.VOCALS_INSTRUMENTAL)
        self.assertEqual(self.settings.ensemble.type, MAX_MIN)
        self.assertEqual(self.settings.ensemble.selected_models, ["MDX-Net: A", "MDX-Net: B"])
        self.assertEqual(self.settings.ensemble.chosen_ensemble, "My Mix")

    def test_missing_preset_raises(self) -> None:
        with mock.patch("core.model_data.load_ensemble", return_value=None), \
             mock.patch("core.model_data.list_saved_ensembles", return_value=["Other"]), \
             mock.patch("core.ensemble_presets.list_curated_ensembles", return_value=["kim_vocal"]), \
             mock.patch("core.ensemble_presets.load_curated_ensemble", return_value=None):
            with self.assertRaises(ValueError) as ctx:
                apply_saved_ensemble(self.settings, "Nope")
        self.assertIn("Nope", str(ctx.exception))

    def test_curated_gui_label_resolves_member_tags(self) -> None:
        data = {
            "ensemble_main_stem": "vocals_instrumental",
            "ensemble_type": MAX_MIN,
            "selected_models": ["MDX-Net: old name"],
        }
        repo = mock.Mock()
        with mock.patch("core.ensemble_presets.load_curated_ensemble", return_value=data), \
             mock.patch(
                 "core.ensemble_presets.resolve_member_tags",
                 return_value=["MDX-Net: New Name"],
             ) as resolve:
            apply_saved_ensemble(self.settings, "Curated: Kim Vocal Inst", repo=repo)
        resolve.assert_called_once()
        self.assertEqual(self.settings.ensemble.selected_models, ["MDX-Net: New Name"])
        self.assertTrue(
            self.settings.ensemble.chosen_ensemble.startswith("Curated:")
        )

    def test_curated_id_without_prefix(self) -> None:
        data = {
            "ensemble_main_stem": "karaoke",
            "ensemble_type": MAX_MIN,
            "selected_models": ["MDX-Net: A", "MDX-Net: B"],
        }
        with mock.patch("core.model_data.load_ensemble", return_value=None), \
             mock.patch("core.ensemble_presets.list_curated_ensembles",
                        return_value=["kim_vocal"]), \
             mock.patch("core.ensemble_presets.load_curated_ensemble", return_value=data), \
             mock.patch("core.ensemble_presets.resolve_member_tags",
                        side_effect=lambda tags, repo: list(tags)):
            apply_saved_ensemble(self.settings, "kim_vocal")
        self.assertEqual(
            self.settings.ensemble.chosen_ensemble, "Curated: kim vocal"
        )

    def test_user_saved_wins_when_name_equals_a_curated_id(self) -> None:
        saved = {
            "ensemble_main_stem": "drums",
            "ensemble_type": MAX_MIN,
            "selected_models": ["VR Arch: A", "VR Arch: B"],
        }
        with mock.patch("core.model_data.load_ensemble", return_value=saved):
            apply_saved_ensemble(self.settings, "kim_vocal")
        self.assertEqual(self.settings.ensemble.chosen_ensemble, "kim_vocal")
        self.assertEqual(self.settings.ensemble.main_stem, EnsemblePair.DRUMS)


class EnsembleMethodAliasTests(unittest.TestCase):
    def test_ensemble_alias_resolves(self) -> None:
        self.assertEqual(resolve_method("ensemble"), ENSEMBLE_MODE)
        self.assertEqual(resolve_method("Ensemble Mode"), ENSEMBLE_MODE)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m unittest tests.test_headless_ensemble -v`
Expected: FAIL with `ImportError: cannot import name 'apply_saved_ensemble'`

- [ ] **Step 3: Extend `METHOD_ALIASES` and `resolve_method`**

In `core/headless_run.py`, add to `METHOD_ALIASES`:

```python
    "ensemble": ENSEMBLE_MODE,
    "ensemble mode": ENSEMBLE_MODE,
```

and add `ENSEMBLE_MODE` to the exact-value loop in `resolve_method`:

```python
    for value in (MDX_ARCH_TYPE, DEMUCS_ARCH_TYPE, VR_ARCH_PM, ENSEMBLE_MODE):
```

Update the `allow_ensemble` guard message in `build_settings` to point at the new command:

```python
        raise ValueError(
            "ensemble runs use their own command: python -m cli ensemble "
            "(separate --method takes mdx|demucs|vr)"
        )
```

- [ ] **Step 4: Implement the two helpers**

Append to `core/headless_run.py`:

```python
def apply_saved_ensemble(
    settings: Settings, name: str, *, repo: Optional[Any] = None
) -> None:
    """Load a user-saved or curated ensemble into ``settings.ensemble`` (does not persist).

    Resolution order: GUI ``Curated: …`` label, then a user-saved file of that
    exact name, then a curated preset id. User-saved wins when the token matches
    both a saved file and a curated id. Curated members go through
    ``resolve_member_tags`` the same way the GUI does.
    """
    from .ensemble_presets import (
        curated_combo_label,
        curated_id_from_combo_label,
        list_curated_ensembles,
        load_curated_ensemble,
        resolve_member_tags,
    )
    from .model_data import ModelRepository, list_saved_ensembles, load_ensemble
    from .stems import coerce_ensemble_pair

    raw = str(name).strip()
    if not raw:
        raise ValueError("ensemble name is empty")

    data = None
    is_curated = False
    chosen = raw

    curated_id = curated_id_from_combo_label(raw)
    if curated_id is not None:
        data = load_curated_ensemble(curated_id)
        if data is not None:
            is_curated = True
            chosen = curated_combo_label(curated_id)

    if data is None:
        data = load_ensemble(raw)
        if data is not None:
            is_curated = False
            chosen = raw

    if data is None:
        cid = raw.replace(" ", "_")
        if cid in list_curated_ensembles():
            data = load_curated_ensemble(cid)
            if data is not None:
                is_curated = True
                chosen = curated_combo_label(cid)

    if data is None:
        curated = [curated_combo_label(i) for i in list_curated_ensembles()[:6]]
        saved = list(list_saved_ensembles()[:6])
        known = ", ".join(repr(n) for n in [*curated, *saved]) or "(none)"
        raise ValueError(f"unknown ensemble {raw!r}; available: {known}")

    members = list(data.get("selected_models") or [])
    if is_curated:
        members = resolve_member_tags(members, repo or ModelRepository())

    settings.ensemble.selected_models = members
    settings.ensemble.type = str(data.get("ensemble_type") or "") or settings.ensemble.type
    settings.ensemble.main_stem = coerce_ensemble_pair(data.get("ensemble_main_stem"))
    settings.ensemble.chosen_ensemble = chosen


def resolve_ensemble_members(
    tokens: Sequence[str], repo: Optional[Any] = None
) -> list[str]:
    """Resolve CLI member tokens to ``{arch}: {display}`` ensemble tags.

    Accepts a full tag, or a unique substring of one, using the same
    normalize-and-match rules as ``--model``. Duplicates collapse, order is
    preserved.
    """
    from .model_data import ModelRepository

    repository = repo or ModelRepository()
    available = list(repository.all_model_tags())

    resolved: list[str] = []
    for token in tokens:
        raw = str(token).strip()
        if not raw:
            raise ValueError("ensemble member token is empty")
        if raw in available:
            resolved.append(raw)
            continue

        query = _normalize_model_query(raw)
        if not query:
            raise ValueError(f"unknown ensemble member {raw!r}")
        matches = [
            tag for tag in available if query in _normalize_model_query(tag)
        ]
        unique = list(dict.fromkeys(matches))
        if len(unique) == 1:
            resolved.append(unique[0])
            continue
        if len(unique) > 1:
            preview = ", ".join(repr(name) for name in unique[:6])
            more = "" if len(unique) <= 6 else f", … (+{len(unique) - 6} more)"
            raise ValueError(
                f"ambiguous ensemble member {raw!r}; matches: {preview}{more}"
            )
        raise ValueError(
            f"unknown ensemble member {raw!r}; pass a full "
            f"'{{arch}}: {{display}}' tag or a unique substring"
        )

    return list(dict.fromkeys(resolved))
```

- [ ] **Step 5: Run the tests to verify they pass**

```bash
.venv/bin/python -m unittest tests.test_headless_ensemble -v
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python -m basedpyright
```

Expected: all pass, zero diagnostics.

- [ ] **Step 6: Commit**

```bash
git add core/headless_run.py tests/test_headless_ensemble.py
git commit -m "feat(core): saved-ensemble and member-resolution helpers for headless runs"
```

---

### Task 6: The `ensemble` command

A separate subcommand, not `separate --method ensemble` — member selection is a different flag set.

**Files:**
- Create: `cli/ensemble.py`
- Modify: `cli/main.py`
- Test: `tests/test_cli_ensemble.py`

**Interfaces:**
- Consumes: everything Task 5 produced, plus `cli.process_flags`, `cli.reporting`, `cli.offline.catalogue_offline`, `core.ensemble_algorithms.parse_ensemble_type`, `core.stems.EnsemblePair`
- Produces:
  - `cli.ensemble.add_ensemble_args(parser: argparse.ArgumentParser) -> None`
  - `cli.ensemble.cmd_ensemble(args: argparse.Namespace) -> int`

- [ ] **Step 1: `cli/offline.py` already exists (Task 3)**

Do not recreate it. Import `catalogue_offline` from `.offline`. `--online` means "do not force the disable flags on"; it does not clear `UVR_DISABLE_*` if the caller already set them.

- [ ] **Step 2: Write the failing tests**

Create `tests/test_cli_ensemble.py`:

```python
"""The `ensemble` command: member sources, validation, and runner choice."""

from __future__ import annotations

import unittest
from unittest import mock

from bundled.constants import (
    CHOOSE_ENSEMBLE_OPTION,
    ENSEMBLE_PARTITION,
    MAX_MIN,
    MDX_ARCH_TYPE,
)
from cli.main import build_parser
from core.settings import Settings
from core.stems import EnsemblePair

_TAG_A = f"{MDX_ARCH_TYPE}{ENSEMBLE_PARTITION}Kim Vocal 2"
_TAG_B = f"{MDX_ARCH_TYPE}{ENSEMBLE_PARTITION}Inst HQ 3"


class _Result:
    ok = True
    elapsed_s = 1.5
    export_path = "/tmp/out"
    error = None
    stopped = False
    console: list[str] = []


class EnsembleMemberSourceTests(unittest.TestCase):
    def test_adhoc_models_populate_selected_models(self) -> None:
        parser = build_parser()
        args = parser.parse_args(
            ["ensemble", "a.wav", "-o", "/tmp/o", "--model", _TAG_A, "--model", _TAG_B]
        )
        self.assertEqual(args.models, [_TAG_A, _TAG_B])

    def test_comma_list_is_also_accepted(self) -> None:
        parser = build_parser()
        args = parser.parse_args(
            ["ensemble", "a.wav", "-o", "/tmp/o", "--models", f"{_TAG_A},{_TAG_B}"]
        )
        self.assertEqual(args.models_csv, f"{_TAG_A},{_TAG_B}")

    def test_fewer_than_two_members_exits_two(self) -> None:
        import io
        from contextlib import redirect_stderr
        from cli.ensemble import cmd_ensemble

        parser = build_parser()
        args = parser.parse_args([
            "ensemble", "a.wav", "-o", "/tmp/o", "--model", _TAG_A,
            "--main-stem", "vocals_instrumental",
        ])
        err = io.StringIO()
        with mock.patch("cli.ensemble.os.path.isfile", return_value=True), \
             mock.patch("cli.ensemble.os.makedirs"), \
             mock.patch("cli.ensemble.ModelRepository"), \
             mock.patch("cli.ensemble.build_settings", return_value=Settings()), \
             mock.patch("cli.ensemble.resolve_ensemble_members",
                        side_effect=lambda tokens, repo=None: list(tokens)), \
             redirect_stderr(err):
            self.assertEqual(cmd_ensemble(args), 2)
        self.assertIn("at least 2", err.getvalue())

    def test_missing_member_source_exits_two(self) -> None:
        import io
        from contextlib import redirect_stderr
        from cli.ensemble import cmd_ensemble

        settings = Settings()
        settings.ensemble.selected_models = [_TAG_A, _TAG_B]
        settings.ensemble.main_stem = EnsemblePair.VOCALS_INSTRUMENTAL
        args = build_parser().parse_args(["ensemble", "a.wav", "-o", "/tmp/o"])
        err = io.StringIO()
        with mock.patch("cli.ensemble.os.path.isfile", return_value=True), \
             mock.patch("cli.ensemble.os.makedirs"), \
             mock.patch("cli.ensemble.build_settings", return_value=settings), \
             redirect_stderr(err):
            self.assertEqual(cmd_ensemble(args), 2)
        self.assertIn("--ensemble", err.getvalue())

    def test_saved_preset_is_loaded_then_overridden_by_models(self) -> None:
        from cli.ensemble import cmd_ensemble

        settings = Settings()
        parser = build_parser()
        args = parser.parse_args(
            ["ensemble", "a.wav", "-o", "/tmp/o", "--ensemble", "My Mix",
             "--model", _TAG_A, "--model", _TAG_B]
        )

        def fake_apply(target: Settings, name: str, **_kwargs: object) -> None:
            target.ensemble.selected_models = ["from-preset"]
            target.ensemble.type = MAX_MIN
            target.ensemble.main_stem = EnsemblePair.VOCALS_INSTRUMENTAL

        with mock.patch("cli.ensemble.os.path.isfile", return_value=True), \
             mock.patch("cli.ensemble.os.makedirs"), \
             mock.patch("cli.ensemble.ModelRepository"), \
             mock.patch("cli.ensemble.build_settings", return_value=settings), \
             mock.patch("cli.ensemble.apply_saved_ensemble", side_effect=fake_apply), \
             mock.patch("cli.ensemble.resolve_ensemble_members",
                        side_effect=lambda tokens, repo=None: list(tokens)), \
             mock.patch("cli.ensemble.run_ensemble_sync", return_value=_Result()):
            self.assertEqual(cmd_ensemble(args), 0)
        self.assertEqual(settings.ensemble.selected_models, [_TAG_A, _TAG_B])
        self.assertEqual(settings.ensemble.chosen_ensemble, CHOOSE_ENSEMBLE_OPTION)


class EnsembleSettingsWiringTests(unittest.TestCase):
    def test_uses_run_ensemble_sync_not_run_separation_sync(self) -> None:
        from cli.ensemble import cmd_ensemble

        parser = build_parser()
        args = parser.parse_args(
            ["ensemble", "a.wav", "-o", "/tmp/o", "--model", _TAG_A,
             "--model", _TAG_B, "--main-stem", "vocals_instrumental"]
        )
        with mock.patch("cli.ensemble.os.path.isfile", return_value=True), \
             mock.patch("cli.ensemble.os.makedirs"), \
             mock.patch("cli.ensemble.ModelRepository"), \
             mock.patch("cli.ensemble.build_settings", return_value=Settings()), \
             mock.patch("cli.ensemble.resolve_ensemble_members",
                        side_effect=lambda tokens, repo=None: list(tokens)), \
             mock.patch("cli.ensemble.run_ensemble_sync", return_value=_Result()) as run:
            self.assertEqual(cmd_ensemble(args), 0)
        run.assert_called_once()

    def test_adhoc_members_require_explicit_main_stem(self) -> None:
        from cli.ensemble import cmd_ensemble

        args = build_parser().parse_args(
            ["ensemble", "a.wav", "-o", "/tmp/o", "--model", _TAG_A,
             "--model", _TAG_B]
        )
        with mock.patch("cli.ensemble.os.path.isfile", return_value=True), \
             mock.patch("cli.ensemble.os.makedirs"), \
             mock.patch("cli.ensemble.ModelRepository"), \
             mock.patch("cli.ensemble.build_settings", return_value=Settings()), \
             mock.patch("cli.ensemble.resolve_ensemble_members",
                        side_effect=lambda tokens, repo=None: list(tokens)):
            self.assertEqual(cmd_ensemble(args), 2)

    def test_adhoc_members_clear_stale_saved_name(self) -> None:
        from cli.ensemble import cmd_ensemble

        settings = Settings()
        settings.ensemble.chosen_ensemble = "Old GUI Preset"
        args = build_parser().parse_args(
            ["ensemble", "a.wav", "-o", "/tmp/o", "--model", _TAG_A,
             "--model", _TAG_B, "--main-stem", "vocals_instrumental"]
        )
        with mock.patch("cli.ensemble.os.path.isfile", return_value=True), \
             mock.patch("cli.ensemble.os.makedirs"), \
             mock.patch("cli.ensemble.ModelRepository"), \
             mock.patch("cli.ensemble.build_settings", return_value=settings), \
             mock.patch("cli.ensemble.resolve_ensemble_members",
                        side_effect=lambda tokens, repo=None: list(tokens)), \
             mock.patch("cli.ensemble.run_ensemble_sync", return_value=_Result()):
            self.assertEqual(cmd_ensemble(args), 0)
        self.assertEqual(settings.ensemble.chosen_ensemble, CHOOSE_ENSEMBLE_OPTION)

    def test_main_stem_and_algorithm_land_on_settings(self) -> None:
        from cli.ensemble import cmd_ensemble

        settings = Settings()
        parser = build_parser()
        args = parser.parse_args(
            ["ensemble", "a.wav", "-o", "/tmp/o", "--model", _TAG_A, "--model", _TAG_B,
             "--main-stem", "karaoke", "--algorithm", "Max Spec/Min Spec"]
        )
        with mock.patch("cli.ensemble.os.path.isfile", return_value=True), \
             mock.patch("cli.ensemble.os.makedirs"), \
             mock.patch("cli.ensemble.ModelRepository"), \
             mock.patch("cli.ensemble.build_settings", return_value=settings), \
             mock.patch("cli.ensemble.resolve_ensemble_members",
                        side_effect=lambda tokens, repo=None: list(tokens)), \
             mock.patch("cli.ensemble.run_ensemble_sync", return_value=_Result()):
            self.assertEqual(cmd_ensemble(args), 0)
        self.assertEqual(settings.ensemble.main_stem, EnsemblePair.KARAOKE)
        self.assertEqual(settings.ensemble.type, MAX_MIN)

class SeparateStillRejectsEnsembleTests(unittest.TestCase):
    def test_separate_method_choices_exclude_ensemble(self) -> None:
        parser = build_parser()
        with self.assertRaises(SystemExit):
            parser.parse_args(
                ["separate", "a.wav", "-o", "/tmp/o", "--method", "ensemble"]
            )


if __name__ == "__main__":
    unittest.main()
```

Add one more wiring test using
`--main-stem vocals_instrumental --set ensemble.main_stem=karaoke`; after the
mocked successful run, assert the final typed value is `EnsemblePair.KARAOKE`.
This prevents ensemble-specific assignments from accidentally moving after the
documented final `--set` layer.

Add `test_ineligible_member_warns`: two `--model`s, `--main-stem vocals_instrumental`,
a fake repo whose `ensemble_model_list` returns only `_TAG_A`. Capture stderr,
assert it contains `warning` and `_TAG_B`, and assert `run_ensemble_sync` was
still called (exit 0). Ineligible members warn; they do not abort.

Each test fakes the same collaborator set — `isfile`, `makedirs`, `ModelRepository`, `build_settings`, `resolve_ensemble_members`, `run_ensemble_sync` — so nothing touches disk, models, torch or the network. `_Result` stands in for `HeadlessResult`. `apply_saved_ensemble` is called with `repo=`; fake side effects must accept `**kwargs`.

- [ ] **Step 3: Run the tests to verify they fail**

Run: `.venv/bin/python -m unittest tests.test_cli_ensemble -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'cli.ensemble'`

- [ ] **Step 4: Implement `cli/ensemble.py`**

```python
"""The ``ensemble`` command: run several models and combine their stems."""

from __future__ import annotations

import argparse
import json
import os
import sys

from bundled.constants import CHOOSE_ENSEMBLE_OPTION, ENSEMBLE_ALGORITHMS
from core.ensemble_algorithms import format_ensemble_type, parse_ensemble_type
from core.headless_run import (
    apply_saved_ensemble,
    build_settings,
    resolve_ensemble_members,
    resolve_vocal_splitter,
    run_ensemble_sync,
    settings_summary,
)
from core.model_data import ModelRepository
from core.settings.access import apply_settings_overrides
from core.stems import EnsemblePair

from .offline import catalogue_offline
from .process_flags import add_process_args, collect_overrides
from .reporting import add_reporting_args, emit_json, fail, finish_progress, make_progress_printer
from .separate import check_runtime_deps

_MAIN_STEM_CHOICES = tuple(
    pair.value for pair in EnsemblePair if pair is not EnsemblePair.CHOOSE
)


def add_ensemble_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("inputs", nargs="+", help="Input audio file path(s)")
    parser.add_argument(
        "-o", "--output", required=True, help="Export directory for stem outputs"
    )
    parser.add_argument(
        "--ensemble",
        default=None,
        metavar="NAME",
        help="Load a saved ensemble preset by name",
    )
    parser.add_argument(
        "--model",
        action="append",
        default=None,
        dest="models",
        metavar="TAG",
        help=(
            "Ad-hoc member, repeatable. A full '{arch}: {display}' tag or a "
            "unique substring of one. Overrides a preset's member list."
        ),
    )
    parser.add_argument(
        "--models",
        default=None,
        dest="models_csv",
        metavar="TAG,TAG",
        help="Comma-separated members (convenience form of repeated --model)",
    )
    parser.add_argument(
        "--main-stem",
        choices=_MAIN_STEM_CHOICES,
        default=None,
        help="Ensemble main-stem pair id",
    )
    parser.add_argument(
        "--algorithm",
        default=None,
        metavar="PRIMARY/SECONDARY",
        help=(
            "Ensemble algorithm pair, e.g. 'Max Spec/Min Spec'. A single token "
            "is used for 4-stem and multi-stem runs. Atoms: "
            + ", ".join(ENSEMBLE_ALGORITHMS)
        ),
    )
    parser.add_argument(
        "--wav-ensemble",
        action="store_true",
        help="Combine in the time domain instead of spectrograms",
    )
    save_group = parser.add_mutually_exclusive_group()
    save_group.add_argument(
        "--save-all-outputs",
        action="store_true",
        help="Keep every member's stems alongside the combined result",
    )
    save_group.add_argument(
        "--no-save-all-outputs",
        action="store_true",
        help="Delete member stems after combining",
    )
    parser.add_argument(
        "--settings",
        default=None,
        help="Path to settings.json (default: UVR data dir settings file)",
    )
    parser.add_argument(
        "--stems",
        default=None,
        help="Which stems to save for this run only (see `separate --stems`)",
    )
    parser.add_argument(
        "--print-settings",
        action="store_true",
        help="Print resolved method/model/export knobs before running",
    )
    parser.add_argument(
        "--long-chunk-seconds",
        type=float,
        default=None,
        help="Whole-file chunk length in seconds (0/omit = off)",
    )
    parser.add_argument(
        "--long-chunk-overlap",
        type=float,
        default=None,
        help="Crossfade overlap between long-file chunks in seconds",
    )
    parser.add_argument(
        "--online",
        action="store_true",
        help=(
            "Do not force catalogue fetches off while resolving names. "
            "Does not clear UVR_DISABLE_POLITREES / UVR_DISABLE_MVSEPLESS if "
            "already set."
        ),
    )
    add_process_args(parser)
    add_reporting_args(parser)


def _member_tokens(args: argparse.Namespace) -> list[str]:
    tokens = list(args.models or [])
    if args.models_csv:
        tokens.extend(
            part.strip() for part in str(args.models_csv).split(",") if part.strip()
        )
    return tokens


def cmd_ensemble(args: argparse.Namespace) -> int:
    dep_err = check_runtime_deps()
    if dep_err:
        return fail(args, dep_err, exit_code=2)

    tokens = _member_tokens(args)
    if not args.ensemble and not tokens:
        return fail(
            args,
            "ensemble requires --ensemble NAME or --model/--models; "
            "do not inherit members from the last GUI session",
            exit_code=2,
        )

    os.makedirs(args.output, exist_ok=True)
    try:
        settings = build_settings(
            settings_path=args.settings,
            export_path=os.path.abspath(args.output),
            method="ensemble",
            stems=args.stems,
            stable_names=True,
            allow_ensemble=True,
            long_chunk_seconds=args.long_chunk_seconds,
            long_chunk_overlap=args.long_chunk_overlap,
        )
    except ValueError as exc:
        return fail(args, str(exc), exit_code=2, exc=exc)

    try:
        resolved_splitter = None
        repo = None
        with catalogue_offline(not args.online):
            repo = ModelRepository()
            if args.ensemble:
                apply_saved_ensemble(settings, args.ensemble, repo=repo)
            if tokens:
                settings.ensemble.selected_models = resolve_ensemble_members(
                    tokens, repo
                )
                # The members no longer exactly represent the named preset.
                settings.ensemble.chosen_ensemble = CHOOSE_ENSEMBLE_OPTION
            if args.vocal_split:
                resolved_splitter = resolve_vocal_splitter(
                    args.vocal_split, settings, repo
                )

        if args.main_stem is not None:
            settings.ensemble.main_stem = EnsemblePair(args.main_stem)
        if args.algorithm is not None:
            primary, secondary = parse_ensemble_type(args.algorithm)
            settings.ensemble.type = format_ensemble_type(primary, secondary)
    except ValueError as exc:
        return fail(args, str(exc), exit_code=2, exc=exc)

    if args.wav_ensemble:
        settings.ensemble.wav_ensemble = True
    if args.save_all_outputs:
        settings.ensemble.save_all_outputs = True
    elif args.no_save_all_outputs:
        settings.ensemble.save_all_outputs = False

    try:
        # Apply last: --set must beat process flags and ensemble-specific named
        # flags such as --main-stem, --algorithm, and --save-all-outputs.
        apply_settings_overrides(
            settings,
            collect_overrides(
                args, resolved_vocal_splitter=resolved_splitter
            ),
        )
    except ValueError as exc:
        return fail(args, str(exc), exit_code=2, exc=exc)

    if tokens and not args.ensemble and args.main_stem is None:
        return fail(
            args,
            "an ad-hoc ensemble requires --main-stem; "
            "do not inherit this semantic choice from the last GUI session",
            exit_code=2,
        )
    if settings.ensemble.main_stem == EnsemblePair.CHOOSE:
        return fail(args, "choose an ensemble --main-stem", exit_code=2)

    members = list(settings.ensemble.selected_models)
    if len(members) < 2:
        source = f"saved ensemble {args.ensemble!r}" if args.ensemble else "--model/--models"
        return fail(
            args,
            f"an ensemble needs at least 2 members, got {len(members)} from {source}",
            exit_code=2,
        )

    if repo is not None:
        with catalogue_offline(not args.online):
            try:
                raw_eligible = repo.ensemble_model_list(
                    settings, settings.ensemble.main_stem
                )
            except Exception:
                raw_eligible = None
        if isinstance(raw_eligible, (list, tuple, set)):
            eligible = set(raw_eligible)
            ineligible = [m for m in members if m not in eligible]
            if ineligible:
                preview = ", ".join(repr(m) for m in ineligible[:6])
                print(
                    f"warning: {len(ineligible)} member(s) are outside the "
                    f"{settings.ensemble.main_stem.value} pool and may not combine: "
                    f"{preview}",
                    file=sys.stderr,
                )

    missing = [p for p in args.inputs if not os.path.isfile(p)]
    if missing:
        return fail(args, f"input not found: {missing[0]}", exit_code=2)

    if args.print_settings and not args.json:
        print(json.dumps(settings_summary(settings), indent=2))

    on_progress = None if args.quiet else make_progress_printer()
    result = run_ensemble_sync(
        settings,
        [os.path.abspath(p) for p in args.inputs],
        print_console=not (args.quiet or args.json),
        on_progress=on_progress,
    )
    if on_progress is not None:
        finish_progress()

    if result.error is not None:
        return fail(
            args,
            f"{type(result.error).__name__}: {result.error}",
            exit_code=1,
            exc=result.error,
        )
    if result.stopped:
        return fail(
            args,
            "ensemble stopped",
            exit_code=130,
            extra={"stopped": True},
        )

    if args.json:
        payload = {
            "ok": True,
            "elapsed_s": result.elapsed_s,
            "export_path": result.export_path,
            "members": members,
        }
        if args.print_settings:
            payload["settings"] = settings_summary(settings)
        emit_json(payload)
    else:
        print(f"elapsed_s={result.elapsed_s:.3f}")
        print(f"export_path={result.export_path}")
        print(f"members={len(members)}")
    return 0
```

As with `separate`, `--json` reserves stdout for exactly one JSON document
(success or failure); engine console output is suppressed even when `--quiet`
was not passed. Extend `tests/test_cli_ensemble.py` with a command-level capture
test that parses the entire stdout and asserts `print_console=False` reached the
runner.

The ineligible-member warning uses `ensemble_model_list` after `--set` so it
sees the final pair. Guard the return with `isinstance(..., (list, tuple, set))`
so a test double that returns a `MagicMock` does not get iterated (that hangs)
and does not warn. Production `ModelRepository.ensemble_model_list` returns a
list. Wrap the call in `catalogue_offline` if you construct a fresh repo here;
reusing the repo from the resolution block is enough because the lister reads
already-built tags.

Note the `parse_ensemble_type` fallback: unknown atoms silently degrade to Max Spec / Min Spec rather than raising. That is existing library behaviour shared with the GUI — do not change it here.

- [ ] **Step 5: Register the subcommand**

In `cli/main.py`, add the import and the parser:

```python
from .ensemble import add_ensemble_args, cmd_ensemble
```

```python
    ensemble = sub.add_parser(
        "ensemble", help="Run several models and combine their stems"
    )
    add_ensemble_args(ensemble)
    ensemble.set_defaults(func=cmd_ensemble)
```

- [ ] **Step 6: Run the tests to verify they pass**

```bash
.venv/bin/python -m unittest tests.test_cli_ensemble -v
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python -m basedpyright
```

Expected: all pass, zero diagnostics.

- [ ] **Step 7: Confirm `separate` still refuses ensemble mode**

```bash
.venv/bin/python -m cli separate x.wav -o /tmp/o --method ensemble
```

Expected: argparse rejects it against `choices=("mdx", "demucs", "vr")`. Then confirm the settings-level guard message too:

```bash
UVR_DATA_DIR=/tmp/uvr-ens-check .venv/bin/python -c "
from core.headless_run import build_settings
from core.settings import Settings
from core.types import ProcessMethod
from bundled.constants import ENSEMBLE_MODE
from unittest import mock
s = Settings(); s.process.method = ProcessMethod(ENSEMBLE_MODE)
with mock.patch('core.headless_run.Settings.load', return_value=s):
    try: build_settings(export_path='/tmp/o')
    except ValueError as e: print(e)
"
```

Expected: `ensemble runs use their own command: python -m cli ensemble (separate --method takes mdx|demucs|vr)`

- [ ] **Step 8: Commit**

```bash
git add cli/ensemble.py cli/main.py tests/test_cli_ensemble.py
git commit -m "feat(cli): ensemble command with saved presets and ad-hoc members"
```

---

### Task 7: The `list-models` command

Read-only, offline by default. `map_basenames_to_display` reaches the network through `_merged_for_display()`, so the default path sets both disable flags and `--online` opts back in.

**Files:**
- Create: `cli/list_models.py`
- Modify: `cli/main.py`
- Test: `tests/test_cli_list_models.py`

**Interfaces:**
- Consumes: `ModelRepository.list_mdx_models` / `list_vr_models` / `list_demucs_models`, `core.model_display.map_basenames_to_display`, `core.model_data.list_saved_ensembles`, `core.ensemble_presets.list_curated_ensembles`, `curated_combo_label`, `cli.offline.catalogue_offline`
- Produces:
  - `cli.list_models.add_list_models_args(parser: argparse.ArgumentParser) -> None`
  - `cli.list_models.cmd_list_models(args: argparse.Namespace) -> int`
  - `cli.list_models.collect_rows(args, repo) -> list[dict[str, str]]`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_cli_list_models.py`:

```python
"""`list-models`: listing shape, method filter, --json, and the offline default."""

from __future__ import annotations

import io
import os
import unittest
from contextlib import redirect_stdout
from unittest import mock

from cli.main import build_parser


class _FakeRepo:
    def list_mdx_models(self) -> list[str]:
        return ["Kim_Vocal_2", "UVR-MDX-NET-Inst_HQ_3"]

    def list_vr_models(self) -> list[str]:
        return ["1_HP-UVR"]

    def list_demucs_models(self) -> list[str]:
        return ["hdemucs_mmi.yaml"]


def _run(argv: list[str]) -> tuple[int, str]:
    from cli.list_models import cmd_list_models

    args = build_parser().parse_args(argv)
    buf = io.StringIO()
    with mock.patch("cli.list_models.ModelRepository", _FakeRepo), \
         mock.patch("cli.list_models.map_basenames_to_display",
                    side_effect=lambda names, arch, repo: [f"D:{n}" for n in names]), \
         redirect_stdout(buf):
        code = cmd_list_models(args)
    return code, buf.getvalue()


class ListModelsTests(unittest.TestCase):
    def test_lists_all_three_families_by_default(self) -> None:
        code, out = _run(["list-models"])
        self.assertEqual(code, 0)
        self.assertIn("Kim_Vocal_2", out)
        self.assertIn("1_HP-UVR", out)
        self.assertIn("hdemucs_mmi.yaml", out)

    def test_method_filter(self) -> None:
        _code, out = _run(["list-models", "--method", "vr"])
        self.assertIn("1_HP-UVR", out)
        self.assertNotIn("Kim_Vocal_2", out)

    def test_json_shape(self) -> None:
        import json

        _code, out = _run(["list-models", "--method", "mdx", "--json"])
        rows = json.loads(out)
        self.assertEqual({"method", "basename", "display"}, set(rows[0]))
        self.assertEqual(rows[0]["method"], "mdx")

    def test_offline_by_default_sets_both_disable_flags(self) -> None:
        seen: dict[str, str | None] = {}

        def spy(names, arch, repo):
            seen["politrees"] = os.environ.get("UVR_DISABLE_POLITREES")
            seen["mvsepless"] = os.environ.get("UVR_DISABLE_MVSEPLESS")
            return list(names)

        args = build_parser().parse_args(["list-models", "--method", "mdx"])
        from cli.list_models import cmd_list_models

        with mock.patch("cli.list_models.ModelRepository", _FakeRepo), \
             mock.patch("cli.list_models.map_basenames_to_display", side_effect=spy), \
             redirect_stdout(io.StringIO()):
            cmd_list_models(args)
        self.assertEqual(seen["politrees"], "1")
        self.assertEqual(seen["mvsepless"], "1")

    def test_online_flag_restores_the_previous_env(self) -> None:
        seen: dict[str, str | None] = {}

        def spy(names, arch, repo):
            seen["politrees"] = os.environ.get("UVR_DISABLE_POLITREES")
            return list(names)

        args = build_parser().parse_args(["list-models", "--method", "mdx", "--online"])
        from cli.list_models import cmd_list_models

        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("UVR_DISABLE_POLITREES", None)
            with mock.patch("cli.list_models.ModelRepository", _FakeRepo), \
                 mock.patch("cli.list_models.map_basenames_to_display", side_effect=spy), \
                 redirect_stdout(io.StringIO()):
                cmd_list_models(args)
        self.assertIsNone(seen["politrees"])

    def test_ensemble_method_lists_saved_and_curated(self) -> None:
        from cli.list_models import cmd_list_models

        args = build_parser().parse_args(["list-models", "--method", "ensemble"])
        buf = io.StringIO()
        with mock.patch("cli.list_models.list_saved_ensembles", return_value=["My Mix"]), \
             mock.patch("cli.list_models.list_curated_ensembles", return_value=["kim_vocal"]), \
             redirect_stdout(buf):
            self.assertEqual(cmd_list_models(args), 0)
        out = buf.getvalue()
        self.assertIn("My Mix", out)
        self.assertIn("Curated:", out)

    def test_ensemble_json_shape(self) -> None:
        import json
        from cli.list_models import cmd_list_models

        args = build_parser().parse_args(["list-models", "--method", "ensemble", "--json"])
        buf = io.StringIO()
        with mock.patch("cli.list_models.list_saved_ensembles", return_value=["My Mix"]), \
             mock.patch("cli.list_models.list_curated_ensembles", return_value=["kim_vocal"]), \
             redirect_stdout(buf):
            self.assertEqual(cmd_list_models(args), 0)
        rows = json.loads(buf.getvalue())
        self.assertTrue(all(row["method"] == "ensemble" for row in rows))
        self.assertEqual({row["kind"] for row in rows}, {"saved", "curated"})
        self.assertIn("basename", rows[0])
        self.assertIn("display", rows[0])


if __name__ == "__main__":
    unittest.main()
```

Every test patches `map_basenames_to_display`, so nothing reaches `_merged_for_display()` and neither refresh thread starts. That satisfies the net-guard constraint whether or not the offline env is set.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m unittest tests.test_cli_list_models -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'cli.list_models'`

- [ ] **Step 3: Implement `cli/list_models.py`**

```python
"""The ``list-models`` command: what is installed on this machine."""

from __future__ import annotations

import argparse
import json
from typing import Any

from bundled.constants import DEMUCS_ARCH_TYPE, MDX_ARCH_TYPE, VR_ARCH_TYPE
from core.ensemble_presets import curated_combo_label, list_curated_ensembles
from core.model_data import ModelRepository, list_saved_ensembles
from core.model_display import map_basenames_to_display

from .offline import catalogue_offline

# CLI method token -> (repository lister attribute, architecture key)
_FAMILIES: dict[str, tuple[str, str]] = {
    "vr": ("list_vr_models", VR_ARCH_TYPE),
    "mdx": ("list_mdx_models", MDX_ARCH_TYPE),
    "demucs": ("list_demucs_models", DEMUCS_ARCH_TYPE),
}


def add_list_models_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--method",
        choices=(*_FAMILIES, "ensemble"),
        default=None,
        help="Limit to one family (default: all three). 'ensemble' lists saved and curated presets.",
    )
    parser.add_argument(
        "--json", action="store_true", help="Emit a JSON array instead of a table"
    )
    parser.add_argument(
        "--online",
        action="store_true",
        help=(
            "Do not force catalogue fetches off. Does not clear "
            "UVR_DISABLE_POLITREES / UVR_DISABLE_MVSEPLESS if already set. "
            "Off by default: each source has a 30s timeout."
        ),
    )


def collect_rows(args: argparse.Namespace, repo: Any) -> list[dict[str, str]]:
    """Build ``{method, basename, display}`` rows for the requested families."""
    wanted = [args.method] if args.method in _FAMILIES else list(_FAMILIES)
    rows: list[dict[str, str]] = []
    for method in wanted:
        lister, arch = _FAMILIES[method]
        basenames = list(getattr(repo, lister)())
        displays = list(map_basenames_to_display(basenames, arch, repo))
        for basename, display in zip(basenames, displays):
            rows.append({"method": method, "basename": basename, "display": display})
    return rows


def collect_ensemble_rows() -> list[dict[str, str]]:
    """Build ``{method, basename, display, kind}`` rows for saved and curated presets."""
    rows: list[dict[str, str]] = []
    for preset_id in list_curated_ensembles():
        label = curated_combo_label(preset_id)
        rows.append({
            "method": "ensemble",
            "basename": preset_id,
            "display": label,
            "kind": "curated",
        })
    for name in list_saved_ensembles():
        rows.append({
            "method": "ensemble",
            "basename": name,
            "display": name,
            "kind": "saved",
        })
    return rows


def cmd_list_models(args: argparse.Namespace) -> int:
    if args.method == "ensemble":
        rows = collect_ensemble_rows()
        if args.json:
            print(json.dumps(rows, indent=2))
            return 0
        for row in rows:
            print(f"ensemble\t{row['kind']}\t{row['display']}")
        if not rows:
            print("(no saved or curated ensembles)")
        return 0

    repo = ModelRepository()
    with catalogue_offline(not args.online):
        rows = collect_rows(args, repo)

    if args.json:
        print(json.dumps(rows, indent=2))
        return 0

    for row in rows:
        if row["display"] and row["display"] != row["basename"]:
            print(f"{row['method']}\t{row['basename']}\t{row['display']}")
        else:
            print(f"{row['method']}\t{row['basename']}")
    if not rows:
        print("(no models installed)")
    return 0
```

- [ ] **Step 4: Register the subcommand**

In `cli/main.py`:

```python
from .list_models import add_list_models_args, cmd_list_models
```

```python
    listing = sub.add_parser("list-models", help="List installed models and saved/curated ensembles")
    add_list_models_args(listing)
    listing.set_defaults(func=cmd_list_models)
```

- [ ] **Step 5: Run the tests to verify they pass**

```bash
.venv/bin/python -m unittest tests.test_cli_list_models -v
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python -m basedpyright
```

Expected: all pass, zero diagnostics.

- [ ] **Step 6: Verify the offline default is actually fast**

```bash
time .venv/bin/python -m cli list-models --method mdx
```

Expected: returns in roughly the time an interpreter start takes, with no multi-second stall. Compare against `--online`, which may pause while the catalogues load.

- [ ] **Step 7: Commit**

```bash
git add cli/list_models.py cli/main.py tests/test_cli_list_models.py
git commit -m "feat(cli): list-models, offline by default"
```

---

### Task 8: Documentation

**Files:**
- Modify: `CLAUDE.md`, `README.md`, `docs/environment.md`, `docs/tracked-issues.md`
- Optional: create `cli/CLAUDE.md`

- [ ] **Step 1: Update `CLAUDE.md`**

In the Commands block, replace the two `python -m core.cli` lines with:

```bash
python -m cli separate song.wav -o /tmp/out --method mdx --stems both   # headless separation
python -m cli ensemble song.wav -o /tmp/out --ensemble "My Mix"         # saved or curated
python -m cli ensemble song.wav -o /tmp/out --ensemble "Curated: kim vocal"
python -m cli list-models --method mdx                                  # what is installed
python -m cli bench-ab song.wav -o /tmp/ab --env UVR_AUTOCAST=0 --env UVR_AUTOCAST=1
```

In the Architecture section, change the layering line from `ui` → `core` → `engines` → `ml` to:

> Layers, strictly one-directional (`ui` → `core` → `engines` → `ml`, and `cli` → `core`; `bundled` is read by all)

and add a `cli/` bullet after the `core/` bullet:

> - **`cli/`** — headless front end (`python -m cli`), a presentation layer peer of `ui/`. `core/cli.py` and `core/__main__.py` remain as trampolines that import `cli.main` **lazily inside a function body** — the single permitted `core → cli` reference, and the reason importing `core` still never pulls in `cli`.

Add an invariant under "Invariants worth preserving":

> **`--set` and named CLI flags share one validated path.** `set_path` cannot reject an unknown field on its own — the settings sections are plain dataclasses without `slots`, so `setattr` invents the attribute instead of raising. Anything that accepts a user-supplied settings path must go through `validate_setting_path` / `apply_settings_overrides` in [core/settings/access.py](core/settings/access.py). Named `cli` flags compile to `(path, value)` pairs in `cli/process_flags.py` rather than growing `build_settings`' signature.

Add a Conventions bullet:

> - **Read-only CLI commands default to offline.** `map_basenames_to_display`, `all_model_tags`, and `karaoke_model_list` (used by `--vocal-split`) reach `_merged_for_display()`, which fetches the politrees and mvsepless catalogues (30s timeout each). `cli/offline.py`'s `catalogue_offline()` sets both disable flags; `--online` means "do not force them on" and does not clear flags the caller already set. The flags are read at call time, so setting them before the repository is touched works.

- [ ] **Step 2: Update `README.md`**

Add a row to the layout table after the `ui/` row:

```
| `cli/` | Headless command-line interface (`python -m cli`) |
```

Add a short section after the launch instructions:

```markdown
### Headless CLI

No GTK needed — the same engine, driven from a terminal:

```bash
python -m cli separate song.wav -o ~/stems --method mdx --stems both
python -m cli ensemble song.wav -o ~/stems --ensemble "My Mix"
python -m cli ensemble song.wav -o ~/stems --ensemble "Curated: kim vocal"
python -m cli ensemble song.wav -o ~/stems --model "MDX-Net: A" \
  --model "MDX-Net: B" --main-stem vocals_instrumental
python -m cli list-models --method ensemble
```

`python -m cli <command> --help` lists every flag. `--set section.field=value`
reaches any typed setting that has no dedicated flag.
```

- [ ] **Step 3: Rewrite the Headless CLI section of `docs/environment.md`**

Replace the four `python -m core.cli` examples with the `python -m cli` equivalents, then add:

```markdown
`python -m core.cli` and `python -m core` still work as trampolines to
`python -m cli`; they are kept for older scripts and will not gain new flags.

**Breaking change in this release:** `bench-ab --json PATH` is now
`bench-ab --json-out PATH`. `--json` is a boolean on every subcommand and
prints a machine-readable object on stdout.
```

Document the shared flags (`--cpu`/`--gpu`, `--device`, `--autocast`/`--no-autocast`, `--format`, `--wav-type`, `--mp3-bitrate`, `--flac-depth`, `--vocal-split MODEL`/`--no-vocal-split`, `--save-split-inst`, `--normalize`, `--match-mix`, `--sample`/`--sample-seconds`, `--set`, `--quiet`, `--json`), and note the karaoke default: instrumental-only output still applies unless `--stems both` is passed. That is engine behaviour and is not changed here.

Also document these deterministic-output rules:

- `--json` reserves stdout for one JSON document (success *or* failure) and
  therefore implies quiet engine-console output; progress and human `error:`
  lines remain on stderr. Failures are `{"ok": false, "error": {"type", "message"}}`.
  Argparse usage errors stay argparse-shaped (they happen before `func()`).
- Ctrl-C / SIGTERM is a first-class stop: first signal is cooperative
  (`JobRunner.stop(force=False)`), second (or a 5s hang) is `force=True`.
  Exit code 130. `--json` still emits one document with `"stopped": true`.
  There is no traceback. `bench-ab` does not start the other leg.
- `--print-settings --json` nests settings under the result's `settings` key
  instead of printing a second document.
- `ensemble` requires `--ensemble NAME` or `--model`/`--models`. It does not
  inherit `selected_models` from the last GUI session.
- `--ensemble` accepts a user-saved name, a curated preset id, or the GUI
  label `Curated: …`. Curated members go through `resolve_member_tags`.
- An ad-hoc ensemble (`--model` / `--models` without `--ensemble`) requires an
  explicit `--main-stem`. Ad-hoc members clear any saved-ensemble name so
  output naming cannot use a stale preset label.
- Members outside `ensemble_model_list` for the chosen `--main-stem` print a
  warning on stderr and still run.
- `--sample-seconds N` also enables sample mode.
- `bench-ab` forwards every process, splitter, stem, and long-chunk option to
  both child legs. `--json-out PATH` writes a file; boolean `--json` prints the
  single machine-readable benchmark payload.

- [ ] **Step 4: Update `docs/tracked-issues.md`**

In the P1 CLI row, change `Shipped as \`python -m core.cli separate\` / \`bench-ab\` ([core/cli.py](../core/cli.py))` to `Shipped as \`python -m cli\` — \`separate\`, \`ensemble\`, \`list-models\`, \`bench-ab\` ([cli/](../cli/))`.

- [ ] **Step 5: Optionally add `cli/CLAUDE.md`**

```markdown
# CLAUDE.md — `cli/`

The headless front end. A presentation layer, exactly like `ui/`.

- **`cli` → `core`, never the reverse.** `core/cli.py` and `core/__main__.py`
  are trampolines that import `cli.main` lazily *inside a function body*; that
  is the only `core → cli` reference in the tree and it must stay lazy.
- **No GTK, torch, onnxruntime or `engines` at import time.** `cli/__init__.py`
  is a docstring. Heavy work stays behind `core.headless_run`.
- **Named flags never become `build_settings` kwargs.** They compile to
  `(path, value)` pairs in `process_flags.py` and go through
  `core.settings.access.apply_settings_overrides`, the same validated path as
  `--set`.
- **Read-only commands default to offline** via `offline.catalogue_offline()`.
  Resolving display names otherwise fetches two catalogues with 30s timeouts.
  `--online` does not clear `UVR_DISABLE_*` already set in the environment.
- **`--json` failures still emit one document** via `reporting.fail()`.
  Interrupts use exit 130 and `"stopped": true`.
- **Ctrl-C is cooperative then forced.** `_run_job` must not re-raise
  `KeyboardInterrupt`. Restore the previous SIGINT/SIGTERM handlers in `finally`.
- **Ensemble member source is explicit.** `--ensemble` (saved or curated) or
  `--model`/`--models`. Ineligible members warn; they do not abort.
- Patch `cli.<module>.<name>` in tests, never `core.cli.*`.
```

- [ ] **Step 6: Verify every documented command actually runs**

```bash
.venv/bin/python -m cli --help
.venv/bin/python -m cli separate --help
.venv/bin/python -m cli ensemble --help
.venv/bin/python -m cli list-models --help
.venv/bin/python -m cli bench-ab --help
.venv/bin/python -m core.cli --help
```

Expected: all six exit 0. Then re-check every `python -m cli` line quoted in the docs against the real `--help` output — a flag documented but not registered is the failure mode this step exists to catch.

- [ ] **Step 7: Final full verification**

```bash
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python -m basedpyright
rg -n "core\.cli" --glob '!.venv*' --glob '!docs/superpowers' .
```

Expected: suite green, zero pyright diagnostics, and the `rg` sweep showing `core.cli` only in `core/cli.py`'s own docstring, `tests/test_cli.py`'s trampoline test, and the `docs/environment.md` compatibility note. Older plan documents under `docs/superpowers/` are historical records — leave them alone.

- [ ] **Step 8: Commit**

```bash
git add CLAUDE.md README.md docs/environment.md docs/tracked-issues.md cli/CLAUDE.md
git commit -m "docs: python -m cli is the headless entry point"
```

---

## Notes carried over from the review

Recorded so the implementer does not rediscover them:

1. **`--json` collided.** `bench-ab` already defined `--json PATH`; a shared `--json` on the same parser raises `argparse.ArgumentError` at construction time. Resolved in Task 4 by making `--json` a uniform boolean and renaming the file output to `--json-out`.
2. **`set_path` does not reject unknown fields.** Verified empirically: `set_path(s, "process.definitely_not_a_field", "x")` returns silently and the attribute exists afterwards. Only an unknown *section* raises, and as `AttributeError`, not `ValueError`. Task 2 exists solely to close this.
3. **`list-models` is not free.** `map_basenames_to_display` → `*_catalogue_display_index()` → `_merged_for_display()` → `load_politrees_links()` is a live fetch. Task 7 defaults it off.
4. **`--vocal-split` cannot take an optional value.** `nargs="?"` in front of the `inputs` positional (`nargs="+"`) lets `separate --vocal-split song.wav` swallow the input file as the model name. The value is required.
5. **`--models` had two syntaxes** in the source plan (`arch|name` vs `tag,tag`). The real tag format is `{arch}: {display}` — `ENSEMBLE_PARTITION` is `': '`. Repeatable `--model` is canonical; `--models` comma-splitting is the convenience form.
6. **`quiet` is not a setting.** It controls `print_console`, never `Settings`.
7. **Ensemble naming is coupled to export naming.** `Ensembler.get_files_to_ensemble` collects members by filename prefix/suffix (`{base} {model} ({stem}).wav`). Nothing in this plan touches `core/export_naming.py` — keep it that way, or ensembles silently produce single-member output.
8. **`as_bool` is lenient.** `--set process.use_gpu=maybe` coerces to `False` rather than raising. Path validation is strict; value coercion is not. Say so in the `--set` help text if it comes up in review.
9. **Machine JSON owns stdout.** `JobRunner` console callbacks normally write
   to stdout, and `--print-settings` used to print a separate JSON document.
   Every `--json` command now suppresses engine console output, keeps
   progress and human `error:` lines on stderr, and emits exactly one document
   for success *and* failure (`fail()` in `cli/reporting.py`). Settings are
   nested when requested. Argparse usage errors remain argparse-shaped.
10. **Accepted benchmark flags must reach both legs.** `bench-ab` reuses the
    separation parser, so process overrides, vocal splitting, print-settings,
    and long-chunk options are serialized into both child argvs. Command-level
    tests compare parser acceptance with the spawned arguments.
11. **The resolved vocal splitter is a named override, not a postscript.** It
    is inserted before repeatable `--set` pairs so the documented “`--set`
    wins” rule remains true. Both `separate` and `ensemble` perform resolution
    inside `catalogue_offline`; neither may accept and ignore the flag.
    `karaoke_model_list` hits `_merged_for_display()` — that is why Task 3
    creates `cli/offline.py` rather than waiting for Task 6.
12. **Ensemble member source is explicit.** `ensemble` requires `--ensemble` or
    `--model`/`--models`. It does not inherit GUI `selected_models`. Ad-hoc
    lists also require `--main-stem` and clear `chosen_ensemble`. `--ensemble`
    accepts user-saved names, curated ids, and the GUI `Curated: …` label;
    curated members go through `resolve_member_tags`. Members outside
    `ensemble_model_list` for the chosen pair warn on stderr and still run.
13. **`--sample-seconds` enables sample mode.** Storing a duration without
    flipping `process.sample_mode` would be stored-and-ignored. `--set` can
    still turn it back off.
14. **`--online` does not force the network on.** It skips `catalogue_offline`.
    Pre-set `UVR_DISABLE_POLITREES` / `UVR_DISABLE_MVSEPLESS` stay in effect.
15. **Ctrl-C used to re-raise.** `_run_job` did `stop(force=True); raise`, so
    `cmd_separate`'s `result.stopped` branch was dead and `--json` printed
    nothing. Task 4.5 returns `HeadlessResult(stopped=True, interrupted=True)`,
    exits 130, and restores the previous SIGINT/SIGTERM handlers in `finally`.
    `model_sweep.py` already classifies `outcome.stopped` as `FAIL(stopped)`
    — do not keep the re-raise to preserve its `except BaseException` path.
