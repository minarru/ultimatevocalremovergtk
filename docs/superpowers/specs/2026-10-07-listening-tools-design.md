# Listening tools: shared compare component, sample trim, ensemble audition

Date: 2026-10-07
Status: approved

## Intent

The Compare Stems dialog (with its new pop-out window) is the first in-app
listening surface. Two more tools should reuse it:

- **Sample trim** — choose *which* N seconds of each input sample mode uses,
  instead of always the first N seconds.
- **Ensemble audition** — produce an ensemble's output with several algorithms
  in one run and keep the one that sounds best.

The shared component is a goal in its own right: all three tools must look,
sound and behave the same (rows, waveforms, transport, shortcuts, pop-out).

Decisions made during design:

- Each tool is its own surface built from shared parts, not one window with modes.
- Sample trim and ensemble audition are independent features. Audition does not
  depend on sample mode.
- Each tool has a single entry point.
- `CompareDialog` and the `ui.compare_in_window` setting are new and unreleased;
  they may be renamed without migration.
- Choosing an audition output does not change the default algorithm.

## Delivery

Three implementation plans, built in order. Each leaves the app working:

1. Shared component (behaviour of Compare Stems unchanged).
2. Sample trim.
3. Ensemble audition.

## 1. Shared component

### `CompareView` — `ui/playback/view.py`, `resources/ui/compare-view.blp`

Owns the track list (one row per track: radio, title, badge, number-key hint,
waveform), the bottom transport bar, and engine wiring (position → waveforms,
state → play button, track error → insensitive row with tooltip, duration and
peak-based shared timeline).

```python
class CompareView(Gtk.Box):
    def __init__(
        self,
        engine: PlaybackControls,
        *,
        peaks: PeakLoading | None = None,
        row_suffix: Callable[[int, Track], Gtk.Widget | None] | None = None,
    ) -> None: ...
    def show_tracks(
        self, tracks: Sequence[Track], *, selected: int | None = None, position: float = 0.0
    ) -> None: ...
    def handle_key(self, keyval: int) -> bool: ...   # Space, Left/Right, 1–9
    def shutdown(self) -> None: ...                   # cancel peaks, then unload
    on_error: Callable[[str], None]                   # engine-level failure text
```

- `selected=None` keeps today's default (first output, else the reference).
- `row_suffix` lets a tool add a widget at the end of a row header (audition's
  "Keep this"). Rebuilt rows call it again.
- Rows, titles, waveforms and key hints remain inspectable attributes for tests.

### `PlaybackSurface` — `ui/playback/surface.py`

Owns the `Adw.ToolbarView` and header bar around a `CompareView`, and all
dialog/window hosting. It absorbs the pop-out logic currently in
`CompareDialog`:

- `present(parent)`: raises an existing window, else opens a window when
  `ui.listening_in_window` is set, else presents the dialog via
  `present_modal_dialog`.
- `pop_out()`: moves the toolbar view into a `FadingWindow` (transient for the
  parent, Escape closes, size carried over, minimum 360×294), moves the key
  controller with it, routes toasts to an in-window `Adw.ToastOverlay`, and
  hides the pop-out button. The dialog's `closed` handler is disconnected
  first so the handover does not unload playback.
- `close()`, `toast(message)`.
- Header: always provides the pop-out and keyboard-shortcuts buttons at the
  end. Tools add `pack_start(widget)` and `set_title_widget(widget)`.
- One capture-phase key controller calls `view.handle_key`.
- On dialog `closed` or window `close-request`: `view.shutdown()`, then the
  tool's `on_closed`.

### Compare Stems after the split

`CompareDialog` is renamed `CompareStemsDialog` (`ui/playback/compare_stems.py`)
and composes a surface and a view, plus its own folder button and input picker.
Switching inputs calls `view.show_tracks(..., position=...)` after pausing.
`RunController.open_compare` changes only the class name and setting name.

### Setting

`ui.compare_in_window` is renamed `ui.listening_in_window` (default false) in
the model, defaults, flat map and coercion, with no migration. Preferences →
General: group "Listening tools", switch "Open in a separate window", subtitle
"Applies to Compare Stems, sample trim and algorithm audition".

### Tests

- `tests/test_compare_view.py`: engine, row, highlighting, keyboard, peaks and
  timeline tests moved from `test_compare_dialog.py`, using `FakeEngine`.
- `tests/test_playback_surface.py`: pop-out, window open from the setting,
  re-present raises the same window, toasts in window, close unloads once.
- `tests/test_compare_dialog.py` → `tests/test_compare_stems_dialog.py`: input
  picker, folder button, header subtitle.
- Existing assertions must pass with only path/name changes.

## 2. Sample trim

### Behaviour

- Sample mode keeps its switch and its duration in Preferences. That duration
  is the default length; an input can have its own length, set in the trim
  dialog.
- An input with no chosen start and no length of its own uses 0:00 and the
  Preferences duration, so its clip is exactly today's "first N seconds",
  including the same cache file.
- Reset in the trim dialog removes that input's start and length.

### Entry point

The only entry point is a "Choose sample range…" button on the Sample mode row
(`page-groups.blp` `sample_row`). It is sensitive only when sample mode is on and
at least one input is set. The row subtitle reads "First 30 s" when no input has
a start or length of its own, "30 s, custom range" when any has a start, and
"Custom range" when any has its own length.

### `TrimDialog` — `ui/playback/trim.py`

- Surface plus view with a single row: the current input as the reference track.
- Several inputs: the same input picker as Compare Stems. Each input keeps its
  own start and length.
- The waveform frames the range, with a gripped trim handle just outside each
  edge. Dragging a handle changes the length in whole seconds, 5–120 s (the
  Preferences bounds) and never past the file; the other edge stays put.
  Dragging anywhere else moves the range; a click without drag inside the range
  seeks, and a click outside it moves the range to start there (pulled back to
  fit the file). The pointer shows a resize cursor over a handle and a grab
  cursor elsewhere while the range can move.
- Shift+Left / Shift+Right move the range by 1 s; Shift+Up / Shift+Down
  lengthen or shorten it by 1 s, pulling the start back at the file end. Both
  are listed in the keyboard shortcuts popover; plain Left/Right still skip 5 s
  inside the range.
- The row shows the range and its length as text ("1:15 – 1:45 · 30 s"),
  ending with the file for a short input, and follows a drag as it happens.
- A length equal to the Preferences duration is not stored, so that input
  keeps following Preferences. A Preferences change leaves inputs with their
  own length alone.
- Playback loops inside the range: when the position passes the range end, the
  dialog seeks to the range start. The engine is unchanged.
- Header: Apply (commits every edited input's start and length to settings and
  closes), Reset (current input back to 0:00 and the default length). Closing
  without Apply discards edits.
- Inputs too short for the duration show the whole file as the range. It cannot
  move, but its handles can shorten it.

### `WaveformView` addition

An optional range (`set_range(start, length)` / `range_start`,
`on_range_changed(start, length)`, `on_range_preview`, `range_movable`), made
resizable by `set_range_resizable(minimum, maximum, step)`. Off by default;
when off, drag seeks exactly as today.

### Core

- Setting `process.sample_starts: dict[str, float]` keyed by absolute input
  path, in model, defaults, flat map and coercion (non-negative floats; invalid
  entries dropped).
- Entries for paths that are no longer inputs are pruned whenever the input
  list is saved.
- `core.audio_decode.load_audio` gains `offset: float = 0.0`.
- Setting `process.sample_lengths: dict[str, float]`, the same shape and rules
  as the starts (positive finite seconds; pruned with the input list).
- `core.sample_mode.prepare_input_paths` reads each input's start and length,
  pulls the start back so start + length does not pass the end of the file, and
  includes the start in the clip cache key only when it is non-zero (0 keeps the
  current key). A whole-second length keeps the existing key form, so an input
  at the default length reuses its clip.
- Plan review's Sample mode row: "First 30 s", or "30 s from 1:15" for one
  input, or "30 s, custom ranges" with per-input detail when several differ;
  with different lengths, "Custom ranges" and a "Sample ranges" detail line.
  The sample warning names the length only when every input shares it.
- `--profile gui` inherits the starts and lengths through settings. No new CLI
  flag; an explicit `--sample-seconds` clears inherited per-input lengths.

### Tests

- Core: offset decoding; pull-back at end of file; cache key unchanged at 0 and
  distinct for other starts; settings round-trip and coercion; pruning; plan
  review wording.
- UI (fake engine): range drag moves the start; click seeks within the range;
  loop seeks back at the end; Apply writes only edited inputs; Close discards;
  Reset removes the start; picker switches inputs; short-input case; entry
  button sensitivity.

## 3. Ensemble audition

### Before the run — ensemble page

- Switch "Audition algorithms" in the algorithm section, with an expander of
  one checkbox per algorithm atom (`ENSEMBLE_ALGORITHMS`, showing
  `ENSEMBLE_ALGORITHM_BLURBS`).
- The algorithm(s) currently configured are checked and insensitive: they
  produce the normal export.
- Settings: `ensemble.audition: bool = False`,
  `ensemble.audition_algorithms: list[str]` (unknown atoms dropped on coercion).
- Plan review shows "Audition: N algorithms" and an extra-disk estimate
  (float WAV, per input × stem × extra algorithm).

### During the run — core

- The job spec carries the extra algorithm list when audition is on.
- In `Ensembler.ensemble_outputs`, after the normal combine, the members (already
  in memory or on disk) are combined once per extra algorithm, written as float
  WAVs to `ENSEMBLE_TEMP_PATH/audition/<run id>/`, and reported through
  `JobCallbacks.report_phase(ProcessingPhase.COMBINING)`.
- The normal export is byte-for-byte what a run without audition produces.
- Variant paths are reported to the UI (per input, per stem, per algorithm)
  through the existing input-finished report path, extended with audition data.
- Cleanup: the audition folder is deleted when the next run starts and at app
  exit.

### After the run — `AuditionDialog` (`ui/playback/audition.py`)

- Entry point: the completion toast button reads "Choose Algorithm" for audition
  runs (instead of "Compare"); Compare Stems also gets a "Choose algorithm"
  header button for those runs. Both open the same dialog.
- Header: input picker (several inputs) and a stem switch (pair stems, or all
  stems for 4-stem ensembles).
- Rows: Original, then one row per algorithm produced. The exported one carries
  a "Kept" badge. Each row has a "Keep this" button via `row_suffix`.
- "Keep this" converts that variant to the configured output format and
  overwrites the exported file at the same path, then moves the badge. Choices
  are per input and stem. "Apply to all inputs" copies the current stem's
  choice to every input that has that variant.
- With "derive complement from mix" on, choosing the primary also keeps the
  matching mix-residual secondary.
- Inputs that failed have no variants and are left out of the picker.
- Closing without choosing loses nothing.
- Not included: changing the default algorithm, tuning algorithm parameters
  inside the dialog, auditioning after the temp folder is cleaned.

### Tests

- Core: each variant equals the combined waveform (before format conversion)
  of a normal run configured with that algorithm; the
  normal export is identical with audition on and off; variants land in the run
  folder; cleanup on next run; coercion of the algorithm list; plan review
  wording and disk estimate.
- UI (fake engine): locked current algorithm checkbox; toast and header entry
  points only for audition runs; "Keep this" replaces the file and moves the
  badge; Apply to all inputs; derive-from-mix pairing; failed inputs omitted.

## Out of scope

- Automatically choosing a sample range (e.g. loudest section).
- A CLI flag for sample start or audition.
- Re-running from Compare Stems.
- Remembering a kept algorithm as the default.
