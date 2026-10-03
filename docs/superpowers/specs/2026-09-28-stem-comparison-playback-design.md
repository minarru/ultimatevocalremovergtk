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

A/B loop points, loudness matching between stems, comparing
across runs, previewing inputs before a run, opening an arbitrary folder of
stems. (Waveform display was added afterwards; see the addendum at the end.)

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
  - Debian/Ubuntu/Mint: `gir1.2-gstreamer-1.0 gir1.2-gst-plugins-base-1.0 gstreamer1.0-plugins-base gstreamer1.0-plugins-good`
  - Fedora: `gstreamer1 gstreamer1-plugins-base gstreamer1-plugins-good`
  - Arch family: `gstreamer gst-plugins-base gst-plugins-good`
  - openSUSE: `typelib-1_0-Gst-1_0 typelib-1_0-GstPbutils-1_0 gstreamer-plugins-base gstreamer-plugins-good`
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

## Addendum: per-stem waveforms

**Date:** 2026-09-29
**Status:** approved in brainstorming, awaiting spec review

### Goal

Show every track's waveform in its row so bleed and artefacts are visible as
well as audible, and let the waveforms replace the seek slider.

### Decisions (from brainstorming)

| Question | Decision |
|---|---|
| Layout | A waveform strip under each track row; one playhead shared by all rows |
| Seeking | Click or drag on any waveform seeks; the seek `Gtk.Scale` is removed |
| Track switching | Unchanged: radio button or `1`–`9`. A waveform click never switches tracks |
| Amplitude | Shared absolute linear scale: 0 dBFS fills the row height in every row; no per-row normalisation |
| Peak source | New `core/waveform.py` over `core/audio_decode`, run on a worker thread |

Rejected peak sources: decoding with GStreamer (`appsink` / `level`) in
`ui/playback` adds a second Gst decode path that can only be tested under Gst;
computing peaks while the run writes outputs slows every run and misses the
reference track.

### Core: peak extraction — `core/waveform.py`

Pure numpy; no GTK, no GStreamer.

```python
@dataclass(frozen=True)
class Peaks:
    duration: float                 # seconds
    mins: NDArray[np.float32]       # per bucket, in [-1, 1]
    maxs: NDArray[np.float32]       # per bucket, in [-1, 1]

class WaveformCancelled(Exception): ...

def compute_peaks(
    path: str, *, buckets: int = 2048, cancel: threading.Event | None = None
) -> Peaks
```

- Bucket count is `min(buckets, frames)`; each bucket covers an equal share of
  the file's frames. Channels fold to the per-bucket extreme (min of mins, max
  of maxs), so a stereo file is one envelope.
- Values are raw sample values, clipped to [-1, 1]. Nothing is normalised;
  the widget scales every row by the same full scale.
- SoundFile-readable files whose frame count is known stream in blocks of
  65 536 frames, so memory stays bounded. Anything else (FFmpeg-only formats,
  unknown length) goes through `core.audio_decode.load_audio` once and is
  reduced in one pass. The fallback therefore uses the same decoder the
  models used.
- `cancel` is checked between blocks (and before the fallback decode); a set
  event raises `WaveformCancelled`.
- Decode failures raise `core.audio_decode.AudioDecodeError`. An empty file
  raises the same error.

### UI: peak loading — `ui/playback/waveforms.py`

GTK-free apart from main-loop delivery, which is injected.

```python
class PeakCache:                    # owned by ListeningSession
    def get(self, path: str) -> Peaks | None
    def put(self, path: str, peaks: Peaks) -> None
    def clear(self) -> None

class WaveformLoader:
    def __init__(self, cache: PeakCache, *,
                 compute=compute_peaks, dispatch=idle_on_main) -> None
    def load(self, paths: Sequence[str], first: int,
             on_peaks: Callable[[int, Peaks | None], None]) -> None
    def cancel(self) -> None
```

- The cache key is `(abspath, st_mtime_ns, st_size)`. `ListeningSession`
  owns one `PeakCache` and clears it in `clear()`. Closing and reopening the
  dialog, or switching inputs, therefore never decodes the same file twice
  within a run's session.
- `load` cancels any previous job, bumps a generation counter, and serves cache
  hits at once (still through `dispatch`, so callbacks are always on the main
  loop). Misses go to one daemon thread that computes the tracks one at a
  time, starting with index `first` (the audible track) and then in display
  order.
- Each result goes through `dispatch`. The main-loop side drops it when its
  generation is no longer current. A failure delivers `None` and logs
  `log_event("playback", "waveform_error", path=…, error=…)`. Cancellation
  delivers nothing.
- `cancel()` sets the job's event and bumps the generation. It does not join
  the thread; a cancelled worker exits at its next block boundary.

### UI: waveform widget — `ui/widgets/waveform.py`

A `Gtk.DrawingArea` drawn with cairo, following
`ui/widgets/progress_ring.py`.

```python
class WaveformView(Gtk.DrawingArea):
    def set_peaks(self, peaks: Peaks | None) -> None      # None = placeholder
    def set_timeline(self, duration: float) -> None       # shared axis length
    def set_position(self, seconds: float) -> None
    def set_active(self, active: bool) -> None            # audible track?
    on_seek: Callable[[float], None]

def x_to_seconds(x: float, width: float, duration: float) -> float
def seconds_to_x(seconds: float, width: float, duration: float) -> float
```

- Height request is 40 px; it expands horizontally.
- **Time axis:** x spans `timeline` (the set's longest duration, from the
  engine's `on_duration`), not the track's own duration. A shorter track's
  envelope ends early and stays aligned with the shared playhead. Until a
  timeline is known the track's own duration is used.
- **Drawing:** for each pixel column, take the min/max over the buckets that
  fall in it and draw a vertical line centred on the row's midline, scaled so
  that ±1.0 reaches the top and bottom edges. Columns past the track's end are
  empty.
- **Colour:** everything is drawn from `widget.get_color()` (GTK 4.10+), so
  light, dark and high-contrast themes need no code. `set_active(True)` adds
  libadwaita's `accent` style class, which makes that colour the accent colour
  on every supported libadwaita (Ubuntu 24.04 ships 1.5, which predates
  `StyleManager.get_accent_color_rgba`). Inactive rows draw the foreground at
  reduced alpha. The
  already-played part (left of the playhead) is drawn at full strength, the
  rest at lower strength. The playhead is a 1 px foreground line.
- **Placeholder:** with no peaks (loading or failed), a faint 1 px midline.
- **Seeking:** a `Gtk.GestureClick` seeks on press, and a `Gtk.GestureDrag`
  seeks continuously while dragging. Both call `on_seek(x_to_seconds(...))`,
  clamped to `[0, timeline]`, and claim the event sequence so the row's radio
  is not activated.
- `x_to_seconds` / `seconds_to_x` are module functions so the mapping is
  testable without a display.

### UI: dialog changes — `ui/playback/dialog.py`, `compare-stems-dialog.blp`

- `CompareDialog.__init__` gains `waveforms: WaveformLoader | None = None`.
  With `None` no waveforms are built, so tests that don't care stay as they
  are. `RunController.open_compare` passes
  `WaveformLoader(self.listening.peak_cache)`.
- Each row becomes a `Gtk.ListBoxRow` whose child is a vertical box:
  - a header line with the radio `Gtk.CheckButton`, the title label and, for
    the reference, a dim "Reference" caption;
  - a `WaveformView` under it, aligned to the title's left edge.

  The row stays activatable (activating it toggles the radio), sensitivity and
  tooltips on track errors stay as they are, and `self.rows` keeps one entry
  per track.
- Blueprint: the `seek_scale` is removed. The transport is play/pause, elapsed
  label, an expanding spacer and the total label. `content-width` grows from
  480 to 560. The footer hint text is unchanged.
- Engine callbacks: `_on_position` updates the elapsed label and calls
  `set_position` on every waveform. `_on_duration` updates the total label and
  calls `set_timeline` on every waveform. Changing the selection (check
  toggled, `1`–`9`, or the engine falling back after a load failure) calls
  `set_active` so exactly the audible row is accented.
- `WaveformView.on_seek` goes to `engine.seek`. Left/Right keep seeking by 5 s.
  With the slider gone these keys are the keyboard route to seeking.
- `_show_set` calls `waveforms.load([t.path for t in tracks], first=selected,
  on_peaks=...)` after building the rows. Closing the dialog (both `close()`
  and the `closed` signal) calls `waveforms.cancel()` before
  `engine.unload()`.

### Error handling

| Situation | Behaviour |
|---|---|
| A track's peaks fail to decode | Its waveform keeps the placeholder midline; playback unaffected; logged once as `playback.waveform_error` |
| Peaks arrive after the input was switched or the dialog closed | Dropped by generation check |
| Track fails in the engine but decodes for peaks | Row insensitive as before; waveform still drawn (dimmed by insensitivity) |
| Output file changed on disk after peaks were cached | Cache key includes mtime and size, so it is recomputed |

### Testing

1. **`tests/test_waveform.py`** (core, no GTK): a 1 kHz sine at 0.5 amplitude
   gives maxs ≈ 0.5 and mins ≈ −0.5 (no normalisation); silence gives zeros;
   a stereo file with one silent channel folds to the loud channel; bucket
   count clamps to frame count for tiny files; a set cancel event raises
   `WaveformCancelled`; a corrupt file raises `AudioDecodeError`; an
   FFmpeg-only path (patched SoundFile failure) still produces peaks through
   `load_audio`.
2. **`tests/test_waveform_loader.py`** (no GTK; `dispatch` runs inline or is
   queued by the test): the first index is computed first; cache hits skip
   `compute`; a changed mtime misses; `cancel()` suppresses delivery; results
   from an older generation are dropped after a second `load`; a compute error
   delivers `None`.
3. **Widget mapping**: `x_to_seconds` / `seconds_to_x` round-trip, clamp
   outside `[0, width]`, and handle `duration == 0`.
4. **Dialog** (extends `tests/test_compare_dialog.py`, fake engine and a fake
   loader): one `WaveformView` per row; delivered peaks reach the right row;
   `on_seek` from a waveform calls `engine.seek` and not `engine.select`;
   `on_position` / `on_duration` reach every waveform; exactly the selected
   row is active after `1`–`9` and after an engine fallback; switching input
   calls `load` again; closing calls `cancel` before `unload`; the seek scale
   no longer exists. Existing seek-scale assertions are updated accordingly.
5. **Session**: `ListeningSession.clear()` clears its `PeakCache`.

### Files

New:
- `core/waveform.py`
- `ui/playback/waveforms.py`
- `ui/widgets/waveform.py`
- `tests/test_waveform.py`, `tests/test_waveform_loader.py`

Changed:
- `ui/playback/dialog.py`, `ui/playback/session.py`, `ui/run_control.py`
- `resources/ui/compare-stems-dialog.blp` (+ compiled resource bundle)
- `tests/test_compare_dialog.py`, `tests/test_compare_run_integration.py`
- `docs/tracked-issues.md` if it lists waveform display as a gap
