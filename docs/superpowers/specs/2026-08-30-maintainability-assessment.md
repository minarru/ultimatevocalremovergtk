# Maintainability assessment

**Assessed:** 2026-08-30

**Branch:** `dev`

**Commit:** `3424f64`

**Comparison point:** `origin/main` (`dev` is 23 commits ahead, 0 behind)

**Retention:** `dev` and branches derived from `dev`; strip before merging to
`main`, following `docs/superpowers/README.md`

**Assessment type:** current-tree architecture, complexity, testability, typing,
tooling, documentation, and operational-maintenance review

## Executive verdict

The codebase is **healthy enough to evolve safely, but expensive to change in a
small number of concentrated areas**. Its strongest qualities are unusually
deep regression coverage, typed and immutable domain contracts, hermetic
network behavior in tests, atomic data publication, detailed architectural
guidance, and an import structure that avoids module-load cycles. The current
tree also shows meaningful refactoring progress: runner callbacks, run hooks,
model repository work, model configuration, stem-selection state, and engine
writing have already moved behind clearer module boundaries.

The main maintainability risk is no longer one universal god object. It is the
combination of:

- legacy flat engine configuration assembled by one very large constructor;
- engine entry points that load models, infer, route stems, apply secondaries,
  and construct exports in one control flow;
- several 1,000-1,600 line GTK controllers that own construction, mutable
  state, persistence, background work, and presentation;
- a documented layer rule that has two confirmed `core -> ui` runtime escapes
  and an intentionally bidirectional `core <-> engines` runtime relationship;
- excellent but oversized and very noisy tests; and
- a deliberate local-only Ruff backlog, with no current lint, coverage, or
  shell-script quality gate in CI.

Overall assessment: **B / moderate maintainability risk**. This is not a case
for a broad rewrite. A responsibility-based extraction sequence can improve
change cost while keeping the existing 3,400-test safety net intact.

## Scope and evidence

Generated catalogue documents, model weights, JSON/TSV model metadata, and
binary assets were excluded from source-line metrics. Ported `ml/` code and the
vendored Demucs fork were measured separately from application-owned code.

| Area | Python files | Physical lines | Interpretation |
| --- | ---: | ---: | --- |
| First-party runtime (`core`, `cli`, `ui`, `engines`, `bundled`) | 220 | 68,369 | Primary maintainability scope |
| Maintenance tooling (`scripts`) | 8 | 8,128 | Separate command/tool surface |
| Ported ML (`ml`) | 44 | 11,795 | Architecture-specific, higher-cost code |
| Vendored Demucs (`vendor/demucs`) | 17 | 6,221 | Third-party fork; deliberately excluded from type/lint policy |
| Tests | 235 | 76,103 | More test code than first-party runtime code |

Current verification:

- private Wayland focused GTK run: 15 tests passed;
- private Wayland full discovery: **3,400 tests passed, 6 skipped, 123.155 s**;
- basedpyright: **0 errors, 0 warnings, 0 notes**;
- configured Ruff audit: **326 findings**;
- separate Ruff McCabe audit at `> 20`: **20 complex functions**;
- Ruff format audit: **220 files would be reformatted, 298 already formatted**;
- `bash -n` passed for the installer, launcher, resource compiler, desktop
  helper, and `uvr` launcher.

The full GTK suite ran on `GdkWaylandDisplay codex-gtk` through a private
Mutter/D-Bus session. No host display was used. Remote Politrees and mvsepless
catalogues were disabled; bundled extras remained enabled as required by the
test contract.

## Maintainability scorecard

| Dimension | Verdict | Evidence |
| --- | --- | --- |
| Architecture | Good with boundary debt | No module-level import cycles; clean CLI/UI entry separation; two runtime `core -> ui` imports and bidirectional core/engine calls |
| Modularity | Mixed | Many successful extractions, but six GTK classes exceed 1,000 lines and key engine/config paths remain very complex |
| Testability | Strong | 3,400 passing tests, network guard, private GTK validation, extensive contract/AST tests |
| Type safety | Good at contracts, weaker in adapters | basedpyright is clean; frozen dataclasses/enums/protocols are common; `Any` and duck-typed fields remain concentrated in UI, engines, and `ModelConfig` |
| Tooling and CI | Adequate | Unit tests and basedpyright run in CI; lint/format debt is local-only; no coverage or shell quality job; duplicated test/release setup |
| Documentation | Strong | Root and layer guidance explain non-obvious invariants; some rules still exist only as prose |
| Operational maintainability | Good but complex | Atomic writes, offline policies, structured logging, and pinned dependencies are strong; install/launcher and catalogue workflows have many branches |

## Confirmed strengths

### 1. Domain contracts are substantially better than the legacy engine API

The newer core uses frozen records and closed vocabularies for job plans, model
identity, catalogue state, settings, stem routes, output naming, device
selection, and download status. `ResolvedJob`, `ModelDescriptor`,
`PlannedInput`, and `PlannedOutput` make planning inspectable before execution.
Exact `family:basename` identities and immutable manifest projections reduce
the stringly-typed inversion risk common in the upstream-style code.

These contracts are backed by architectural tests such as
`tests/test_no_runtime_display_inversion.py`, settings validation tests, replay
identity tests, and import-safety subprocess tests.

### 2. Import-time behavior is disciplined

An AST import-graph pass found **no module-level strongly connected
components** in the application/ML packages. Heavy `torch`, `onnxruntime`, and
engine imports are generally delayed until execution or warmup. This is a
meaningful strength for both GTK startup and the headless CLI.

Runtime imports do form cycles because `core` launches engines while engines
consume core services, but those cycles do not execute at module import time.
That distinction should be preserved in future refactors.

### 3. Regression protection is unusually broad

Tests cover UI state and layout, CLI machine-readable contracts, safe batch
promotion, cancellation, model identity, catalogue/offline behavior, download
transactions, settings migration, stem routing, engine exports, generated
artifacts, and lazy imports. The suite blocks accidental outbound TCP access
and can run GTK against a private display.

The high test-to-runtime ratio is an asset. The recommendation below is to
improve test organization and signal, not reduce behavioral coverage.

### 4. Repository guidance captures real failure modes

`CLAUDE.md`, `cli/CLAUDE.md`, `ui/CLAUDE.md`, `docs/environment.md`, and
`docs/tracked-issues.md` contain concrete, current invariants rather than generic
style advice. Several of the hardest rules—identity direction, lazy imports,
network isolation, settings validation, and GTK thread crossing—have executable
tests.

## Prioritized findings

### M1 — Remove the remaining core-to-UI error-log dependency

**Priority:** P1

**Type:** confirmed architectural boundary violation
**Effort:** small to medium

The framework-agnostic core lazily imports GTK-facing error storage in two
failure paths:

- `core/job_runner.py:537` imports `ui.errorlog` when sample clip preparation
  falls back;
- `core/download_queue.py:334` imports `ui.errorlog` when a transfer fails.

The lazy placement prevents an import-time GTK dependency, so headless startup
still works. It does not preserve the stated `ui -> core` direction at runtime:
headless error handling attempts to load a module whose top-level imports
include `Adw`, `Gtk`, `Gdk`, `Pango`, and `PangoCairo`. The surrounding broad
`except` hides the dependency when GTK is unavailable, which also means the
headless path silently loses the shared error-log record.

Move formatting/storage or an error-report callback into core, then let the UI
subscribe and present it. Add an AST boundary test that forbids runtime
`core -> ui` imports. Treat `bundled.constants.__getattr__ -> ui.help_text` as a
separate compatibility escape: document/allowlist it temporarily or remove it
after confirming no legacy caller needs it.

### M2 — Decompose the legacy configuration and engine execution seams

**Priority:** P1

**Type:** architectural risk; current tests pass
**Effort:** medium to large, staged

The highest-risk production functions from a Ruff McCabe audit are:

| Function | Lines | McCabe complexity |
| --- | ---: | ---: |
| `engines/demucs_engine.py:SeperateDemucs.seperate` | 413 | 52 |
| `engines/mdx_c_engine.py:SeperateMDXC.seperate` | 357 | 50 |
| `core/model_config/config.py:ModelConfig.__init__` | 467 | 42 |
| `core/job_plan.py:JobResolver.resolve` | 225 | 31 |
| `cli/execution.py:_promote_locked` | 145 | 32 |

`ModelConfig.__init__` is the central compatibility pressure point. It copies
typed settings into a large flat attribute surface, resolves paths and hashes,
loads metadata/config YAML, handles each architecture, derives stem semantics,
and attaches secondary/pre-process/vocal-split chains. The typed nested groups
are valuable, but the legacy flat duck-typed engine API still dictates the
constructor's shape.

The Demucs and MDX-C `seperate` methods similarly combine cache lookup/model
loading, input preparation, inference, secondary-model blending, native and
derived route construction, normalization, vocal splitting, and `ExportPlan`
assembly. A change to one phase must be understood in the context of all the
others.

Refactor by pipeline phase, not by line count:

1. Keep `ModelConfig` as the compatibility facade, but have architecture-
   specific builders return typed group/state records.
2. Extract pure route/source planning before moving inference code.
3. Split each engine independently into load/reuse, infer, post-process, and
   export-plan phases.
4. Preserve the misspelled public `Seperate*` classes and existing flat fields
   until all engine consumers migrate.

Do not combine the ModelConfig and engine refactors in one branch. Their tests
overlap heavily, so a sequential extraction keeps regressions attributable.

### M3 — Thin the largest GTK controllers around pure state/services

**Priority:** P1/P2

**Type:** architectural risk; no confirmed behavior defect
**Effort:** medium, incremental

| Class | Lines | Body members | Mixed responsibilities |
| --- | ---: | ---: | --- |
| `ui/ensemble/window.py:EnsemblePage` | 1,602 | 85 | construction, settings, saved presets, semantic planning, dialogs, model list, run target |
| `ui/download_center.py:DownloadCenterWindow` | 1,410 | 79 | filtering/sorting, row state, background refresh, evidence fetch, selection, queueing |
| `ui/run_control.py:RunController` | 1,198 | 62 | preflight, dialogs, run state, shutdown, cleanup, progress/ETA, notifications |
| `ui/window.py:MainWindow` | 1,138 | 89 | layout, settings, navigation, refresh spine, drag/drop, actions |
| `ui/widgets/stem_only.py:SaveStemsSection` | 1,120 | 96 | widget state, semantics projection, persistence, refresh recovery, custom dialog |
| `ui/views/base.py:MethodView` | 1,031 | 75 | model lifecycle, persistence, widget factories, dynamic options, secondary selectors |

Some size is legitimate GTK wiring. The problem is responsibility mixing and
state transition density, not the existence of long construction methods.

Recommended extraction order:

1. Download Center query/filter/selection/count state into a pure view model.
2. Ensemble member/pair/preset session state into a core or UI-neutral service.
3. RunController lifecycle into an explicit state machine, leaving dialogs and
   widget updates as effects.
4. Continue the existing `core/stem_selection.py` direction so
   `SaveStemsSection` only maps widgets to a pure state object.
5. Split `MethodView` only after shared option descriptors replace enough
   ad-hoc dictionaries to make the seam clear.

### M4 — Align the documented layer model with the actual runtime model

**Priority:** P2

**Type:** qualified architectural concern
**Effort:** small for documentation/tests; large for full re-layering

The prose describes strict `ui -> core -> engines -> ml` layering. Static
imports are cycle-free, but the runtime dependency graph is more accurately:

```text
ui / cli -> core orchestration -> engines -> ml
                    ^              |
                    |--------------|
```

Engine modules directly consume core stem, path, logging, GPU, checkpoint, and
export contracts, while core lazily invokes engine factories, caches, writers,
and inference helpers. This can be a sound plugin-style relationship, but it is
not literally one-directional.

Choose and encode one of two positions:

- document `core` as both shared domain contracts and orchestration, while
  forbidding only import-time cycles and UI dependencies; or
- move engine-facing contracts into a lower neutral package so orchestration
  depends on engines without engines depending on orchestration modules.

The first option is substantially cheaper and matches current behavior. Either
way, add an executable import-boundary test; the existing identity-specific AST
guard demonstrates the pattern.

### M5 — Improve test signal and test-code modularity

**Priority:** P2

**Type:** confirmed maintenance friction
**Effort:** small to medium

The full suite passes, but even `unittest ... -q` emits hundreds of lines of
expected warnings, CLI failures, generator publication messages, and portal
diagnostics. This makes unexpected warnings difficult to spot in CI logs.

One focused real-code test reliably emits two application-relevant
`ResourceWarning`s:

- `pydub.AudioSegment.from_wav` leaves the source WAV handle unclosed;
- `core/audio_io.py:160` ignores the file handle returned by the Opus export.

The suite also reports implicit cleanup of the process-wide test cache
`TemporaryDirectory` under explicit `ResourceWarning` mode. Close the audio
handles in production code, explicitly clean process-level test resources, and
capture/assert expected stderr/stdout in tests that intentionally exercise
failure reporting.

Test size is also concentrated: 17 test modules exceed 1,000 lines;
`tests/test_generate_models_catalogue.py` alone is 6,155 lines with 215 test
methods. Split it by collection, publication, check/read-only behavior,
manifest validation, reference rendering, and CLI contracts. Keep shared
fixtures small and immutable so the split does not become a new helper god
object.

### M6 — Ratchet quality tooling without converting backlog into churn

**Priority:** P2

**Type:** confirmed tooling debt
**Effort:** medium

The configured Ruff audit reports 326 findings, dominated by 149 import-order
and 80 unused-import findings. A separate complexity audit reports 20 functions
above McCabe 20, and the formatter would change 220 files. These are audit
counts, not 326 defects: several higher-severity-looking findings are qualified
false positives or intentional synchronous callback captures.

The repository deliberately keeps Ruff local-only while this backlog exists.
Preserve that policy unless a separate change approves a gate. A safe sequence
is:

1. record the current backlog by category;
2. clean one responsibility area at a time with focused tests;
3. require Ruff only for files touched by that cleanup locally;
4. consider a changed-files or baseline CI ratchet only after policy approval;
5. never bulk-format ported ML or unrelated application files as part of a
   behavior change.

Type checking is much stronger: basedpyright is clean and runs in CI. However,
the configuration intentionally disables most unknown-type diagnostics, and
the runtime packages contain roughly 1,736 `Any`/`typing.Any` occurrences.
Tighten types at new extraction seams—especially builders, state records, and
engine export plans—rather than attempting repository-wide strict mode.

### M7 — Reduce CI and installation workflow drift

**Priority:** P3

**Type:** qualified operational concern
**Effort:** small to medium

CI runs unit tests and basedpyright, which is a good minimum. Remaining drift
risks are:

- `test.yml` and `release.yml` duplicate system dependency and environment
  setup;
- the normal test workflow uses `discover -s tests -t .`, while the release
  workflow omits `-t .`;
- `ubuntu-latest` and its system `python3` are not pinned even though the
  project documents Python 3.13+, develops on 3.14, supports a 3.12 fallback,
  type-checks as 3.14, and formats/lints for 3.12;
- there is no coverage report, so the large test count cannot identify
  unexecuted production seams;
- the 465-line multi-distro installer and 190-line launcher have syntax and a
  small launcher test, but no ShellCheck job or option-level installer tests.

Use one reusable CI setup/test workflow for PRs and tags, make the tested OS and
Python version explicit, and add lightweight shell/static checks. Introduce
coverage first as information, not as an arbitrary failing percentage. The
native GTK/system-Python constraint makes a full Python matrix expensive; a
small pure-core/CLI compatibility smoke job is enough to validate the fallback
floor.

## Subsystem direction

| Area | Direction |
| --- | --- |
| `core` domain records, settings, identity, planning contracts | **Stay focused.** Preserve immutable typed contracts and exact identity rules. |
| `core` orchestration and `ModelConfig` | **Do less per object.** Extract builders/phases while keeping compatibility facades. |
| `engines` | **Do less per entry point.** Separate loading, inference, post-processing, and export planning. |
| `ui` | **Do less in GTK classes.** Move state transitions, filtering, selection, and lifecycle decisions into pure objects. |
| `cli` | **Stay focused.** It is already a peer presentation layer; split `discovery.py` by command family when next changed. |
| `scripts` | **Stay separate and narrow.** Continue internal package extraction; do not merge tool policy into runtime core. |
| `ml` / `vendor` | **Avoid cosmetic refactors.** Change only for supported-model correctness, compatibility, or measured performance. |
| tests | **Keep breadth, improve shape and signal.** Split giant modules, capture expected output, and make resource warnings actionable. |
| documentation | **Keep, then encode.** Turn stable architectural prose into small AST/contract tests where practical. |

## Recommended sequence

1. **Boundary and warning hygiene:** remove the two core-to-UI imports, add the
   boundary test, close Opus/WAV handles, and make focused warning checks clean.
2. **ModelConfig seam:** introduce typed per-architecture build results behind
   the current flat facade; no engine behavior changes.
3. **One engine pipeline at a time:** MDX-C, then Demucs, using existing export
   and stem-routing characterization tests.
4. **UI state extraction:** Download Center, Ensemble, RunController, then the
   remaining Save Stems adapter work.
5. **Test/tooling ratchet:** split generator tests, reduce captured-output
   noise, clean Ruff debt by area, and decide separately whether policy should
   add a baseline/changed-files gate.
6. **CI reuse and compatibility smoke:** consolidate PR/tag setup, make runtime
   versions explicit, and add shell/static and informational coverage checks.

Each step should land independently with focused tests plus the private-display
full suite. Do not mix formatting backlog, behavior changes, and structural
extractions in the same change.

## Bottom line

The repository is not fragile because it lacks tests or design intent; it is
fragile where modern typed contracts meet large legacy-compatible adapters.
The safest strategy is to preserve those contracts and shrink the adapters
from the outside in. The current test suite and recent successful extractions
make that a practical refactoring program rather than a rewrite.
