# Stem comparison playback — design

**Status:** approved in brainstorming, awaiting spec review
**Date:** 2026-09-28
**Branch:** `dev`

## Goal

Let users hear the result of a run inside the app and compare stems **at the
same moment**: switch between Original, Vocals, Instrumental (or any other
outputs) mid-playback with no gap, to judge bleed and artefacts before trying
another model.

Success means: after any GUI run finishes, one click opens a dialog in which
every output of every successfully processed input can be played, and
switching tracks is sample-accurate and click-free.

## Decisions (from brainstorming)

| Question | Decision |
|---|---|
| Primary purpose | Compare stems at the same playhead position (A/B switching), original included as reference |
| Scope of v1 | The **latest run only**, from all three run pages (separation, Ensemble, Audio Tools), grouped per input file; replaced when the next run starts |
| Switching quality | Instant and gapless (sample-accurate) |
| Engine | One GStreamer pipeline with `audiomixer`; per-track `volume` crossfade |
| Surface | `Adw.Dialog` ("Compare stems"), not a permanent main-window pane |

### Out of scope for v1

Waveform display, A/B loop points, loudness matching between stems, comparing
across runs, previewing inputs before a run, opening an arbitrary folder of
stems.

## Architecture

The GTK UI and CLI remain peers over core. Output reporting and the comparison
data model are framework-independent and live in `core/`; everything that
touches GStreamer or GTK lives in `ui/playback/`.

```
worker thread                           main loop
─────────────                           ─────────
run_models_on_files ──input_finished──▶ RunController.on_input_finished
AudioToolRunner     ──input_finished──▶   └─ ListeningSession.add(ComparisonSet)
                                        RunController._on_complete / _on_stopped
                                          └─ toast "Compare" ─▶ CompareDialog
                                                                  └─ PlaybackEngine (Gst)
```

### Core: explicit output reporting

`JobCallbacks.input_finished(paths, generated, error)` already exists and is
already called by `core/audio_tools.py`. Separation and ensemble runs do not
call it, and the GTK layer does not consume it.

1. **`core/run_loop.run_models_on_files`** calls
   `callbacks.input_finished((original_path,), outputs, error)` once per input
   after that input's models (and, for ensembles, the combine step) finish:
   - `original_path` is the user's input path, mapped back through
     `runner._run_path_map` when sample mode rewrote it.
   - `outputs` are the paths of the input's `PlannedOutput`s that exist on
     disk, in plan order. Ensemble runs report only the final combined outputs,
     never per-member files in the ensemble temp folder.
   - A skipped input (file not found) or a failed input reports `outputs=()`
     with the error (or `None` for a skip).
   - The existence check is factored out of `JobRunner` (the CLI's
     `core/job_runner.py` per-input block) into one helper shared by both
     paths, so GUI and CLI agree on "what was written".
   - When the run has no plan (`_run_planned is None`), `outputs=()`; the
     GUI will then simply have nothing to compare for that input.
2. The **reference track** is the audio the models actually processed: the
   prepared input path (the sample clip in sample mode, otherwise the input
   itself). It is reported alongside the outputs; see `ComparisonSet` below.
   To carry it without widening the callback signature, `input_finished`
   gains an optional keyword `reference: str | None = None`; existing
   Audio Tools callers are unchanged (their reference defaults to the input).

### Core: comparison data model — `core/listening.py`

Pure data, no GTK, no GStreamer.

```python
@dataclass(frozen=True)
class Track:
    label: str          # "Original", "Vocals", "Instrumental", …
    path: str
    role: str | None    # stem role id when known, else None
    is_reference: bool = False

@dataclass(frozen=True)
class ComparisonSet:
    source: str                 # user-visible input path
    tracks: tuple[Track, ...]   # reference first, then outputs in plan order

def build_comparison_set(source, reference, outputs, planned=None) -> ComparisonSet | None
```

- Labels are `core.stems.ui_label(PlannedOutput.stem)` (core must not import
  `ui.stem_labels`). Without a plan (Audio Tools), the label is
  the output filename with the input's base name and separators stripped,
  falling back to the basename.
- Returns `None` when there are no outputs, so failed inputs never appear.
- Duplicate paths are dropped; order is stable.

### UI: playback engine — `ui/playback/engine.py`

The only module that imports `Gst`. Imported lazily when the dialog opens.

Pipeline, one branch per track:

```
uridecodebin → audioconvert → audioresample → volume ─┐
uridecodebin → audioconvert → audioresample → volume ─┼─▶ audiomixer → audioconvert → autoaudiosink
…                                                     ─┘
```

Interface (all callbacks delivered on the GLib main loop):

```python
class PlaybackEngine:
    @staticmethod
    def availability() -> str | None      # None if usable, else a user-facing reason
    def load(self, tracks: Sequence[Track], *, selected: int, position: float = 0.0) -> None
    def play(self) -> None
    def pause(self) -> None
    def seek(self, seconds: float) -> None   # flushing, accurate seek on the pipeline
    def select(self, index: int) -> None     # ~5 ms volume ramp; playback continues
    def unload(self) -> None                 # pipeline to NULL, release devices
    on_position: Callable[[float], None]     # ~10 Hz while playing
    on_duration: Callable[[float], None]     # longest track
    on_state: Callable[[bool], None]         # playing?
    on_track_error: Callable[[int, str], None]
    on_error: Callable[[str], None]          # pipeline-level failure
```

- All branches decode continuously so switching never waits on a decoder; only
  the selected branch has volume 1.0. The ramp uses `GstController`
  (`InterpolationControlSource` on `volume`) or, if unavailable, an immediate
  switch — either is gapless, the ramp only removes clicks.
- Tracks of different sample rates, channel counts and formats are normalised
  by `audioconvert`/`audioresample` before the mixer.
- Shorter tracks end early and contribute silence; the pipeline ends at the
  longest track (EOS → pause at end, position kept).
- A branch whose decoder errors is removed from the pipeline and reported via
  `on_track_error`; the remaining branches keep playing. A pipeline-level error
  (no audio sink, etc.) goes to `on_error` and the engine unloads.
- `availability()` returns a reason when `gi.require_version("Gst", "1.0")`
  fails or the `audiomixer`, `uridecodebin` or `volume` factories are missing.
- The audio sink is injectable (`sink_factory="autoaudiosink"`) so tests can
  use `fakesink sync=true`.

### UI: comparison dialog — `ui/playback/dialog.py`

An `Adw.Dialog` titled "Compare stems", built from a Blueprint
(`resources/ui/compare-stems-dialog.blp`) and depending only on the engine
interface (a fake engine is injected in tests).

Layout, top to bottom:

1. **Input dropdown** — shown only when the session has more than one
   `ComparisonSet`; label "`<basename>`  N of M". Switching input reloads the
   engine with the new set, keeps the position if within the new duration,
   and leaves playback paused.
2. **Track list** — a single-selection list of radio rows: Original (with a
   muted "reference" suffix) first, then outputs. The selected row is audible.
   Rows for tracks that failed to load are insensitive with the reason as
   tooltip.
3. **Transport** — play/pause button, elapsed time, seek scale, total time.
4. **Footer** — shortcut hint ("Space play · 1–9 switch · ← → 5 s") and an
   "Open folder" button using the existing `open_folder_in_file_manager`.

Keyboard: Space toggles play/pause; `1`–`9` select tracks by position; Left /
Right seek ∓5 s. Closing the dialog calls `engine.unload()`.

The dialog follows `ui/AGENTS.md`: widget state through `ui/widget_state.py`,
nullable GTK returns narrowed through `ui/gtk_narrow.py`, callbacks on the
main loop, and no `destroy()` in tests.

### UI: run integration

- **`ListeningSession`** (small, no GTK, in `ui/playback/session.py`): holds the
  latest run's `ComparisonSet`s keyed by source in arrival order;
  `clear()`, `add()`, `sets()`, `__bool__`.
- **`RunController`** wires `on_input_finished` through the existing
  `ui.dispatch` main-thread marshalling (lossless, not the latest-value
  dispatcher, since every input matters). It clears the session in
  `begin_run` and adds a set per successful input.
- **Completion:** `_show_complete_toast` adds a "Compare" action alongside
  "Open folder" when the session is non-empty and
  `PlaybackEngine.availability()` is `None`. `Adw.Toast` has a single button,
  so the toast's button becomes "Compare" and "Open folder" moves into the
  dialog footer; when comparison is unavailable the toast keeps "Open folder"
  as today.
- **Stopped runs** with at least one finished input get the same Compare
  toast.
- A header-bar button (`media-playback-start-symbolic`, tooltip "Compare
  stems") appears while the session is non-empty and playback is available,
  so the dialog can be reopened after the toast is gone. It hides when the
  next run starts.
- Ensemble and Audio Tools pages share the controller, so they get the same
  behaviour with no page-specific code beyond the callback wiring.

## Error handling

| Situation | Behaviour |
|---|---|
| GStreamer or required plugins missing | No Compare button/toast action; app behaves as today. A README troubleshooting row names the packages. Logged once via `log_event("playback", "unavailable", reason=…)` |
| One output fails to decode | That row is insensitive with the reason; others play |
| No audio output device / pipeline error | Toast "Couldn't start playback. <reason>"; dialog stays open, transport disabled |
| Output file deleted after the run | Treated as a decode failure for that row |
| New run starts while the dialog is open | Dialog closes and unloads before the session is cleared |
| App shutdown with dialog open | Existing close path closes dialogs; `unload()` sets the pipeline to `NULL` |

Diagnostics use `core/debug_log.py` named events (`playback.load`,
`playback.track_error`, `playback.error`); position ticks are not logged.

## Dependencies and packaging

- Runtime (optional): the GStreamer GI typelib plus base and good plugins.
  - Debian/Ubuntu/Mint: `gir1.2-gstreamer-1.0 gstreamer1.0-plugins-base gstreamer1.0-plugins-good`
  - Fedora: `gstreamer1 gstreamer1-plugins-base gstreamer1-plugins-good`
  - Arch family: `gstreamer gst-plugins-base gst-plugins-good`
  - openSUSE: `typelib-1_0-Gst-1_0 gstreamer-plugins-base gstreamer-plugins-good`
- Added to the README distro blocks and `install_packages.sh --system-deps`.
- No new Python packages. `PyGObject-stubs` already ships `Gst.pyi`, so the
  engine is type-checked under basedpyright; no `Any` shims.
- CI (`test.yml`) installs the same Ubuntu packages so engine tests run rather
  than skip.
- `Gst` is imported only inside `ui/playback/engine.py`, lazily, so startup
  cost and non-playback test runs are unchanged.

## Testing

stdlib `unittest`; GTK tests follow the isolated Xvfb flow in
`docs/environment.md`.

1. **Core output reporting** — a fake engine writing files under a temp dir:
   `input_finished` fires once per input with existing planned outputs in plan
   order; missing optional outputs are omitted; failed and skipped inputs
   report `()`; ensemble runs report only combined outputs; sample mode
   reports the clip as `reference` and the original as the source.
2. **`core/listening.py`** — labels from plan stems, reference first,
   Audio Tools filename labels without a plan, duplicates dropped, `None` for
   no outputs.
3. **Engine** — `skipUnless` Gst + `audiomixer` available; `fakesink
   sync=true`; two generated sine WAVs of different length: duration equals
   the longer; position advances after `play`; `seek` moves the shared
   position; `select` sets exactly one branch's volume to 1.0 without a state
   change; a corrupt file triggers `on_track_error` and the other branch
   continues; `unload` reaches `NULL`.
4. **Dialog** — fake engine: row activation calls `select`; `1`–`9`, Space,
   Left/Right map to the engine; dropdown hidden for one input and reloads on
   change; failed rows insensitive; close calls `unload`.
5. **Run integration** — session cleared on `begin_run`; `on_input_finished`
   marshalled and accumulated; Compare toast only when the session is
   non-empty and playback available, including stopped runs; the header
   button tracks session state; a new run closes an open dialog.

## Files

New:
- `core/listening.py`
- `ui/playback/__init__.py`, `engine.py`, `dialog.py`, `session.py`
- `resources/ui/compare-stems-dialog.blp` (+ compiled `.ui`, resource bundle)
- `tests/test_listening.py`, `tests/test_playback_engine.py`,
  `tests/test_compare_dialog.py`, `tests/test_run_output_reporting.py`

Changed:
- `core/run_loop.py`, `core/job_runner.py` (shared output-existence helper,
  `input_finished` calls), `core/job_callbacks.py` (`reference` keyword)
- `ui/run_control.py` (session, callback wiring, toast, dialog lifecycle)
- `ui/window.py` / `resources/ui/main-header.blp` (header button)
- `README.md` (distro blocks + troubleshooting row), `install_packages.sh`,
  `.github/workflows/test.yml`
- `docs/tracked-issues.md` (new product-gap row, updated on completion)
