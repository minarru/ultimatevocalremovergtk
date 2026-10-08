# Listening Tools 2: Sample Trim Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the user choose which N seconds of each input sample mode processes. Inputs with no chosen start keep today's "first N seconds" clip.

**Architecture:**
- Core stores a start per input in `process.sample_starts` and decodes clips from that offset. A start of 0 keeps the existing cache file.
- The UI adds a `TrimDialog`, built from plan 1's `CompareView` and `PlaybackSurface`, plus a movable fixed-width range on `WaveformView`.
- A GTK-free `RangeLoop` sits between the view and the engine. It keeps playback inside the range without changing the engine.
- A "Choose sample range…" button on the Sample mode row opens the dialog. It appears on both the Separation and Ensemble pages.

**Tech Stack:** Python 3.12+, GTK4/libadwaita (PyGObject), Blueprint, soundfile/FFmpeg decode, stdlib unittest, basedpyright, ruff.

**Spec:** `docs/superpowers/specs/2026-10-07-listening-tools-design.md` (section 2). This plan builds on plan 1 (`docs/superpowers/plans/2026-10-08-listening-shared-component.md`, committed on `dev`).

## Global Constraints

- An input with no start uses 0:00. Its clip is today's "first N seconds" with **the same cache file**.
- `process.sample_starts: dict[str, float]` is keyed by absolute input path. It lives in the model, defaults, flat map (`model_sample_starts`) and coercion. Coercion keeps only non-negative finite floats; invalid entries are dropped.
- Entries for paths that are no longer inputs are pruned whenever the input list is saved.
- `--profile gui` inherits the starts through settings. There is **no new CLI flag**.
- Sample mode row subtitle: `"First 30 s"` when no input has a start, `"30 s, custom range"` when any does.
- Plan review Sample row: `"First 30 s"`; `"30 s from 1:15"` when every input shares one start; `"30 s, custom ranges"` plus per-input detail when they differ. `"Full tracks"` is unchanged.
- Trim dialog:
  - Dragging the range moves it. A click without a drag seeks, clamped to the range.
  - Playback loops inside the range.
  - Apply commits edited inputs and closes. Reset sets the current input back to 0:00. Closing without Apply discards edits.
  - An input shorter than the duration shows the whole file as its range.
- The playback engine (`ui/playback/engine.py`) is unchanged.
- Dialogs that hold edits until Apply follow `ui/AGENTS.md`:
  - Cancel at the header start and the suggested action at the end.
  - No title buttons.
  - `dismiss_on_backdrop=False`.
- Title case for dialog titles and button labels; sentence case for tooltips and row text.
- Rebuild resources after Blueprint changes and commit `ui/data/uvr.gresource`. Use `rg`. Stage explicitly. Plans and specs stay on `dev`.
- **Headless runner:** same prefix as plan 1, i.e. `env -u DISPLAY -u WAYLAND_DISPLAY -u DBUS_SESSION_BUS_ADDRESS -u DBUS_SYSTEM_BUS_ADDRESS -u XDG_RUNTIME_DIR -u XAUTHORITY -u SESSION_MANAGER -u UVR_REQUIRE_PRIVATE_GTK GDK_BACKEND=x11 GSK_RENDERER=cairo xvfb-run -a -s "-screen 0 1920x1080x24" .venv/bin/python -m unittest <modules>`. Display-free modules can use plain `.venv/bin/python -m unittest`.

## Review Focus

1. **Switching inputs keeps pending edits.** Edit input A, switch to B, switch back: A still shows its edited range, and Apply writes both. Test: Task 7, `test_picker_switches_inputs_keeping_pending_edits`.
2. **A range ending at the end of the file** keeps looping when the file ends, instead of stopping. Test: Task 5, `test_end_of_file_inside_the_range_keeps_looping`.
3. **Arrow keys or a seek before the range start** stay inside the range. Test: Task 5, `test_seeks_are_clamped_to_the_range`.
4. **The input list changes while the dialog is open.** Apply must not write starts for files that are no longer inputs. Test: Task 8, `test_apply_drops_edits_for_removed_inputs`.
5. **GStreamer is missing.** The range button is insensitive and its tooltip gives the reason, instead of opening a dialog that cannot play. Test: Task 8, `test_range_button_explains_missing_playback`.

---

### Task 1: Decode from an offset

**Files:**
- Modify: `core/audio_decode.py` (`load_audio`, `_decode_ffmpeg`, `_decode_damaged`, `_pcm_command`)
- Test: `tests/test_audio_decode.py`

**Interfaces:**
- Produces: `load_audio(source, *, sr=None, duration=None, offset: float = 0.0, res_type=..., force_ffmpeg=False, on_warning=None)`.

- [ ] **Step 1: Write the failing tests**

Each test builds a 2 s mono float ramp at 8000 Hz and writes it as a WAV with `subtype='FLOAT'` in a temp dir:

```python
def test_offset_reads_from_the_offset(self):
    data, rate = load_audio(path, offset=0.5, duration=1.0)
    self.assertEqual(rate, 8000)
    np.testing.assert_array_equal(data, ramp[4000:12000])

@unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'FFmpeg required')
def test_offset_through_ffmpeg(self):
    data, _rate = load_audio(path, offset=0.5, duration=1.0, force_ffmpeg=True)
    self.assertEqual(len(data), 8000)
    np.testing.assert_allclose(data, ramp[4000:12000], atol=1e-6)

def test_negative_offset_is_rejected(self):
    with self.assertRaises(AudioDecodeError):
        load_audio(path, offset=-1.0)

def test_offset_does_not_seed_whole_file_peaks(self):
    with patch('core.audio_decode._seed_peaks') as seed:
        load_audio(path, offset=0.5)
    seed.assert_not_called()
```

- [ ] **Step 2: Run them and confirm they fail**

Run: `.venv/bin/python -m unittest tests.test_audio_decode`
Expected: FAIL with `TypeError: load_audio() got an unexpected keyword argument 'offset'`.

- [ ] **Step 3: Implement the offset**
- Validation: reject an offset that is not finite or is negative with `ValueError('Offset must be finite and non-negative')`. The existing `except` wraps it as `AudioDecodeError`.
- soundfile path: when `offset > 0`, call `audio.seek(int(offset * rate))` before the read.
- FFmpeg path: `_pcm_command(..., offset: float = 0.0)` adds `['-ss', str(offset)]` **before** `-i` when `offset > 0`. Thread `offset` through `_decode_ffmpeg` and `_decode_damaged`.
- Peaks: `_seed_peaks` runs only when `duration is None and offset == 0`.

- [ ] **Step 4: Run them and confirm they pass**

Run: `.venv/bin/python -m unittest tests.test_audio_decode tests.test_audio_decoder_integration`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add core/audio_decode.py tests/test_audio_decode.py
git commit -m "feat(core): decode audio from an offset"
```

---

### Task 2: Per-input sample starts in settings and clips

**Files:**
- Modify: `core/settings/model.py`, `core/settings/defaults.py`, `core/settings/flat_map.py`, `core/settings/coerce.py`
- Modify: `core/sample_mode.py`
- Test: `tests/test_settings_typed.py`, `tests/test_core_sample_mode.py`

**Interfaces:**
- Consumes: `load_audio(..., offset=)` (Task 1).
- Produces, in `core/sample_mode.py`:

```python
def sample_start(starts: Mapping[str, float], path: str) -> float          # 0.0 when unset
def has_custom_start(starts: Mapping[str, float], paths: Iterable[str]) -> bool
def prune_sample_starts(starts: Mapping[str, float], paths: Iterable[str]) -> dict[str, float]
def _clip_cache_path(source: str, duration: int, start: float = 0.0) -> str
```

All three helpers look paths up by `os.path.abspath(path)`.
- Produces, in `core/settings/coerce.py`: `as_sample_starts(value: Any) -> dict[str, float]`.

- [ ] **Step 1: Write the failing tests**

In `tests/test_settings_typed.py`:

```python
def test_sample_starts_default_empty_and_round_trip(self):
    settings = Settings.from_json_dict({"process": {}})
    self.assertEqual(settings.process.sample_starts, {})
    settings.process.sample_starts = {"/in/a.wav": 75.0}
    restored = Settings.from_json_dict(json.loads(json.dumps(settings.to_json_dict())))
    self.assertEqual(restored.process.sample_starts, {"/in/a.wav": 75.0})

def test_sample_starts_coercion_drops_invalid_entries(self):
    raw = {"/a.wav": 75, "/b.wav": -1, "/c.wav": "x", "/d.wav": float("nan"), 3: 1.0, "/e.wav": 0}
    self.assertEqual(coerce_field("process", "sample_starts", raw), {"/a.wav": 75.0})
    self.assertEqual(coerce_field("process", "sample_starts", "oops"), {})
```

In `tests/test_core_sample_mode.py`, using the existing fixture: a 2 s source at 8000 Hz with a duration of 1. `abs_source = str(self.source.resolve())`.

```python
def test_start_offsets_the_clip(self):
    self.settings.process.sample_starts = {abs_source: 0.5}
    [clip] = prepare_input_paths(self.settings, [str(self.source)])
    expected, _ = sf.read(self.source, start=4000, frames=8000, dtype='float32')
    np.testing.assert_array_equal(sf.read(clip, dtype='float32')[0], expected)

def test_start_is_pulled_back_to_fit_the_file(self):
    self.settings.process.sample_starts = {abs_source: 1.5}
    [clip] = prepare_input_paths(self.settings, [str(self.source)])
    expected, _ = sf.read(self.source, start=8000, frames=8000, dtype='float32')
    np.testing.assert_array_equal(sf.read(clip, dtype='float32')[0], expected)

def test_zero_start_keeps_the_original_cache_name(self):
    digest = hashlib.md5(b'/tmp/music.m4a:5', usedforsecurity=False).hexdigest()[:12]
    self.assertTrue(_clip_cache_path('/tmp/music.m4a', 5, 0.0).endswith(f'music_5s_v2_{digest}.wav'))
    self.assertEqual(_clip_cache_path('/tmp/music.m4a', 5, 0.0), _clip_cache_path('/tmp/music.m4a', 5))

def test_each_start_gets_its_own_clip(self):
    first = prepare_input_paths(self.settings, [str(self.source)])
    self.settings.process.sample_starts = {abs_source: 0.5}
    second = prepare_input_paths(self.settings, [str(self.source)])
    self.assertNotEqual(first, second)
    self.assertEqual(len(list(self.cache.iterdir())), 2)

def test_relative_input_path_finds_its_start(self):
    self.addCleanup(os.chdir, os.getcwd())
    os.chdir(self.root)
    self.settings.process.sample_starts = {abs_source: 0.5}
    [clip] = prepare_input_paths(self.settings, ['input.flac'])
    expected, _ = sf.read(self.source, start=4000, frames=8000, dtype='float32')
    np.testing.assert_array_equal(sf.read(clip, dtype='float32')[0], expected)

def test_start_helpers(self):
    starts = {'/in/a.wav': 12.0}
    self.assertEqual(sample_start(starts, '/in/a.wav'), 12.0)
    self.assertEqual(sample_start(starts, '/in/b.wav'), 0.0)
    self.assertTrue(has_custom_start(starts, ['/in/b.wav', '/in/a.wav']))
    self.assertFalse(has_custom_start(starts, ['/in/b.wav']))
    self.assertEqual(prune_sample_starts(starts, ['/in/b.wav']), {})
    self.assertEqual(prune_sample_starts(starts, ['/in/a.wav']), starts)
```

- [ ] **Step 2: Run them and confirm they fail**

Run: `.venv/bin/python -m unittest tests.test_settings_typed tests.test_core_sample_mode`
Expected: FAIL. There is no `sample_starts` attribute, and `sample_start` cannot be imported.

- [ ] **Step 3: Add the setting**
- Field: `sample_starts: dict[str, float] = field(default_factory=dict)`, after `sample_mode_duration`.
- Defaults: `"sample_starts": {}`.
- Flat map: `"model_sample_starts": ("process", "sample_starts")`.
- Coercion: `coerce_field` routes `("process", "sample_starts")` to `as_sample_starts`. It keeps `str` keys whose values convert to finite floats `> 0`; a start of 0 means "unset". A value that is not a `dict` becomes `{}`.

- [ ] **Step 4: Use the start in `prepare_input_paths`**
- Read `start = sample_start(settings.process.sample_starts, path)`.
- When `start > 0`, get `total = audio_duration_seconds(path)` from `core.audio_probe`. If it is known, set `start = max(0.0, min(start, total - duration))`.
- Decode with `load_audio(path, duration=duration, offset=start)`.
- The cache key is `f"{source}:{duration}"` when `start == 0`, else `f"{source}:{duration}:{start:.3f}"`. The file name format is otherwise unchanged.
- Add `start` to the existing debug lines.

- [ ] **Step 5: Run them and confirm they pass**

Run: `.venv/bin/python -m unittest tests.test_settings_typed tests.test_core_sample_mode tests.test_audio_decoder_integration tests.test_settings_overrides`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add core/settings/model.py core/settings/defaults.py core/settings/flat_map.py core/settings/coerce.py \
  core/sample_mode.py tests/test_settings_typed.py tests/test_core_sample_mode.py
git commit -m "feat(core): per-input sample start for sample mode"
```

---

### Task 3: Plan review wording

**Files:**
- Modify: `ui/plan_review.py` (`_technical_plan`, `review_presentation`)
- Test: `tests/test_plan_review.py`

**Interfaces:**
- Consumes: `sample_start` (Task 2).

- [ ] **Step 1: Write the failing tests**

```python
def _sampled(plan, starts):
    plan.settings.process.sample_mode = True
    plan.settings.process.sample_mode_duration = 30
    plan.settings.process.sample_starts = starts
    return plan

def test_sample_without_starts_reads_first_seconds(self):
    view = review_presentation(_sampled(resolved_plan(), {}))
    self.assertEqual(view.sample, "First 30 s")
    self.assertEqual(view.processing, "CPU · First 30 s")

def test_shared_start_reads_from_its_clock(self):
    plan = _sampled(resolved_plan(), {"/music/A & B.wav": 75.0})
    view = review_presentation(plan)
    self.assertEqual(view.sample, "30 s from 1:15")
    details = json.loads(view.technical.split("\n\n", 1)[1])
    self.assertEqual(details["processing"]["sample_starts"], {"/music/A & B.wav": 75.0})

def test_differing_starts_list_each_input(self):
    plan = resolved_plan()
    second = PlannedInput("/music/C.wav", plan.inputs[0].naming, plan.inputs[0].outputs)
    plan = _sampled(replace(plan, inputs=plan.inputs + (second,)), {"/music/A & B.wav": 75.0})
    view = review_presentation(plan)
    self.assertEqual(view.sample, "30 s, custom ranges")
    self.assertIn("Sample starts: A & B.wav 1:15, C.wav 0:00", view.additional)

def test_sample_off_reads_full_tracks(self):
    self.assertEqual(review_presentation(resolved_plan()).sample, "Full tracks")
```

- [ ] **Step 2: Run them and confirm they fail**

Run: `.venv/bin/python -m unittest tests.test_plan_review`
Expected: FAIL. `'30-second sample' != 'First 30 s'`.

- [ ] **Step 3: Implement the wording in `ui/plan_review.py`**
- Add a private `_clock(seconds: float) -> str` that returns `m:ss`.
- Collect `starts = [sample_start(process.sample_starts, item.path) for item in plan.inputs]` and choose the summary:
  - all 0: `"First {d} s"`
  - all equal and non-zero: `"{d} s from {clock}"`
  - otherwise: `"{d} s, custom ranges"`, plus an `additional` line `"Sample starts: " + ", ".join(f"{basename} {clock}")` in input order.
- In `_technical_plan`, when sample mode is on, set `processing["sample_starts"]` to `{path: start}` for inputs whose start is greater than 0.
- Leave the existing warning sentence as it is.

- [ ] **Step 4: Run them and confirm they pass**

Run: `.venv/bin/python -m unittest tests.test_plan_review`, plus `tests.test_plan_review_dialog` through the headless runner if that module exists (`ls tests | rg plan_review`).
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add ui/plan_review.py tests/test_plan_review.py
git commit -m "feat(ui): show sample ranges in plan review"
```

---

### Task 4: A movable range on `WaveformView`

**Files:**
- Modify: `ui/widgets/waveform.py`
- Test: `tests/test_waveform_view.py` (the display-guarded `WaveformViewTests`)

**Interfaces:**
- Produces, on `WaveformView`:

```python
def set_range(self, start: float, length: float) -> None   # length <= 0 turns the range off
range_start: float        # property
range_length: float       # property, 0.0 when off
on_range_moved: Callable[[float], None]   # fired once, when a drag ends
def begin_range_drag(self) -> None
def update_range_drag(self, dx: float, width: float) -> None
def end_range_drag(self, x: float, width: float) -> None
```

- [ ] **Step 1: Write the failing tests**

```python
def _ranged(self, timeline: float, start: float, length: float):
    view = WaveformView("Song")
    view.set_timeline(timeline)
    view.set_range(start, length)
    self.seeks: list[float] = []
    self.moved: list[float] = []
    view.on_seek = self.seeks.append
    view.on_range_moved = self.moved.append
    return view

def test_range_drag_moves_the_start(self):
    view = self._ranged(100.0, 10.0, 30.0)
    view.begin_range_drag()
    view.update_range_drag(50, 200)
    self.assertEqual(view.range_start, 35.0)
    view.end_range_drag(150, 200)
    self.assertEqual((self.moved, self.seeks), ([35.0], []))

def test_range_drag_is_clamped_to_the_track(self):
    view = self._ranged(100.0, 10.0, 30.0)
    view.begin_range_drag()
    view.update_range_drag(1000, 200)
    self.assertEqual(view.range_start, 70.0)
    view.update_range_drag(-1000, 200)
    self.assertEqual(view.range_start, 0.0)

def test_click_in_range_mode_seeks_within_the_range(self):
    view = self._ranged(100.0, 10.0, 30.0)
    view.begin_range_drag()
    view.update_range_drag(1, 200)
    view.end_range_drag(180, 200)
    self.assertEqual((self.seeks, self.moved), ([40.0], []))

def test_short_track_range_cannot_move(self):
    view = self._ranged(20.0, 0.0, 30.0)
    view.begin_range_drag()
    view.update_range_drag(50, 200)
    self.assertEqual(view.range_start, 0.0)

def test_zero_length_turns_the_range_off(self):
    view = self._ranged(100.0, 10.0, 0.0)
    self.assertEqual(view.range_length, 0.0)
```

- [ ] **Step 2: Run them and confirm they fail**

Run: `tests.test_waveform_view` through the headless runner.
Expected: FAIL. `'WaveformView' object has no attribute 'set_range'`.

- [ ] **Step 3: Implement the range**
- A drag is a click when the total `|dx|` stays below `_CLICK_SLOP = 4.0` px. A click seeks to `x_to_seconds(x)`, clamped to `[range_start, range_start + range_length]`. A drag fires `on_range_moved(range_start)`.
- Clamp the start to `[0, max(0, timeline - length)]`.
- In range mode, `_on_drag_begin` claims the sequence and calls `begin_range_drag()` without seeking. `_on_drag_update` and `GestureDrag`'s `drag-end` dispatch to the update and end methods. Without a range, behaviour is unchanged.
- Drawing: before the bars, fill the range span with the widget colour at `_RANGE_ALPHA = 0.12`.

- [ ] **Step 4: Run them and confirm they pass**

Run: `tests.test_waveform_view tests.test_compare_view` through the headless runner.
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add ui/widgets/waveform.py tests/test_waveform_view.py
git commit -m "feat(ui): movable fixed-width range on the waveform"
```

---

### Task 5: `RangeLoop`

**Files:**
- Create: `ui/playback/range_loop.py` (no GTK import)
- Test: `tests/test_range_loop.py` (display-free; uses `tests.playback_fakes.FakeEngine`)

**Interfaces:**
- Produces:

```python
class RangeLoop:          # satisfies ui.playback.engine.PlaybackControls
    def __init__(self, engine: PlaybackControls) -> None: ...
    def set_range(self, start: float, length: float) -> None: ...   # length <= 0: no range
    range_start: float     # property
    range_end: float       # property: start + length, capped at engine.duration when > 0
```

- [ ] **Step 1: Write the failing tests**

```python
def _loop(self, start=10.0, length=30.0):
    engine = FakeEngine()
    loop = RangeLoop(engine)
    loop.set_range(start, length)
    self.positions: list[float] = []
    loop.on_position = self.positions.append
    return loop, engine

def test_seeks_are_clamped_to_the_range(self):
    loop, engine = self._loop()
    loop.seek(5.0)
    loop.seek(100.0)
    self.assertEqual([c for c in engine.calls if c[0] == "seek"], [("seek", 10.0), ("seek", 40.0)])

def test_load_position_is_clamped(self):
    loop, engine = self._loop()
    loop.load(comparison_set("song").tracks, selected=0, position=0.0)
    self.assertEqual(engine.calls[-1][3], 10.0)

def test_passing_the_end_loops_to_the_start(self):
    loop, engine = self._loop()
    loop.play()
    engine.on_position(40.02)
    self.assertEqual(engine.calls[-1], ("seek", 10.0))
    self.assertNotIn(40.02, self.positions)

def test_end_of_file_inside_the_range_keeps_looping(self):
    loop, engine = self._loop()
    engine._duration = 35.0
    loop.play()
    engine._playing = False
    engine.on_state(False)          # end of stream: not a pause through the loop
    engine.on_position(35.0)
    self.assertEqual(engine.calls[-2:], [("seek", 10.0), ("play",)])

def test_user_pause_at_the_end_does_not_resume(self):
    loop, engine = self._loop()
    loop.play()
    loop.pause()
    engine.on_position(40.0)
    self.assertEqual(engine.calls[-1], ("seek", 10.0))

def test_without_a_range_everything_passes_through(self):
    loop, engine = self._loop(length=0.0)
    loop.seek(5.0)
    engine.on_position(99.0)
    self.assertEqual((engine.calls[-1], self.positions), (("seek", 5.0), [99.0]))

def test_engine_callbacks_reach_the_listener(self):
    loop, engine = self._loop()
    states: list[bool] = []
    loop.on_state = states.append
    loop.play()
    self.assertEqual(states, [True])
```

- [ ] **Step 2: Run them and confirm they fail**

Run: `.venv/bin/python -m unittest tests.test_range_loop`
Expected: FAIL. `ModuleNotFoundError: ui.playback.range_loop`.

- [ ] **Step 3: Implement `RangeLoop`**
- Forwarding: it forwards every `PlaybackControls` member. It installs its own handlers on the wrapped engine's five `on_*` callbacks and forwards them to its public `on_*` attributes, which default to no-ops.
- Ending (`_LOOP_EPSILON = 0.05` s):
  - A position at or past `range_end - _LOOP_EPSILON` seeks to `range_start` and is not forwarded.
  - It then calls `play()` only if the engine reported `on_state(False)` without a `pause()` or `toggle()` through the loop. That is the end-of-stream case. A loop that is still playing just seeks.
- Before the start: while playing, a position before `range_start - _LOOP_EPSILON` seeks to `range_start`.

- [ ] **Step 4: Run them and confirm they pass**

Run: `.venv/bin/python -m unittest tests.test_range_loop`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add ui/playback/range_loop.py tests/test_range_loop.py
git commit -m "feat(ui): keep playback looping inside a range"
```

---

### Task 6: Shared input picker and commit surfaces

**Files:**
- Create: `ui/playback/input_picker.py`, `resources/ui/input-picker.blp`, `tests/test_input_picker.py`
- Modify: `resources/ui/compare-stems.blp` (drop `title_box`; keep `folder_button`), `ui/playback/compare_stems.py` (use the picker)
- Modify: `resources/ui/playback-surface.blp`, `ui/playback/surface.py`
- Test: `tests/test_playback_surface.py`, `tests/test_compare_stems_dialog.py` (unchanged assertions must still pass)

**Interfaces:**
- Produces, in `ui/playback/input_picker.py`:

```python
class InputPicker:
    def __init__(self, title: str, names: Sequence[str], on_changed: Callable[[int], None]) -> None: ...
    widget: Gtk.Box
    window_title: Adw.WindowTitle
    dropdown: Gtk.DropDown
    selected: int       # property
```

  - With one name, it shows the title with the name as subtitle and hides the dropdown.
  - With several, it hides the title and shows the dropdown, labelled `f"{name}  {i} of {n}"` with the existing ellipsizing factories. `on_changed(index)` fires when the selection changes.
- Produces, on `PlaybackSurface`:
  - new keyword arguments `commit: bool = False` and `track_keys: bool = True`
  - `pack_end(widget) -> None`
  - `track_key_rows: tuple[Gtk.Widget, Gtk.Widget]`

- [ ] **Step 1: Write the failing tests**

`tests/test_input_picker.py`:
- `test_single_name_is_the_subtitle`: subtitle is `"a.wav"` and the dropdown is hidden.
- `test_several_names_use_the_dropdown`: the title is hidden; the model strings are `["a.wav  1 of 2", "b.wav  2 of 2"]`; `set_selected(1)` makes `on_changed` receive `1`; `selected == 1`.

`tests/test_playback_surface.py`:

```python
def test_commit_surface_hides_title_buttons(self):
    surface, _ = self._surface(commit=True)
    header = surface._header
    self.assertFalse(header.get_show_start_title_buttons())
    self.assertFalse(header.get_show_end_title_buttons())

def test_commit_surface_ignores_backdrop_clicks(self):
    surface, _ = self._surface(commit=True)
    with mock.patch("ui.playback.surface.present_modal_dialog") as present:
        surface.present(None)
    self.assertIs(present.call_args.kwargs["dismiss_on_backdrop"], False)

def test_track_keys_can_be_hidden(self):
    surface, _ = self._surface(track_keys=False)
    self.assertEqual([w.get_visible() for w in surface.track_key_rows], [False, False])

def test_pack_end_puts_tool_widgets_last(self):
    surface, _ = self._surface()
    button = Gtk.Button(label="Apply")
    surface.pack_end(button)
    self.assertIs(button.get_prev_sibling(), surface.end_box)
```

`_surface` gains `commit` and `track_keys` keyword arguments that it passes through.

- [ ] **Step 2: Run them and confirm they fail**

Run: `tests.test_input_picker tests.test_playback_surface` through the headless runner.
Expected: FAIL. There is no module `ui.playback.input_picker`, and `commit` is an unexpected keyword.

- [ ] **Step 3: Implement**

`input-picker.blp`: move `title_box` here from `compare-stems.blp`, without the `title:` line; the title is set from Python.

`playback-surface.blp`:
- Wrap the pop-out and shortcuts buttons in `[end] Gtk.Box end_box { spacing: 6; … }`.
- Give the "1 – 9" keycap and its "Switch track" label the ids `track_keys_key` and `track_keys_label`.

`PlaybackSurface`:
- `pack_end` removes `end_box`, packs the widget, then packs `end_box` again.
- `commit=True` hides both title-button sides. `present` then passes `dismiss_on_backdrop=not commit`.
- `track_keys=False` hides both `track_key_rows`.

`CompareStemsDialog` builds an `InputPicker(_TITLE, [s.name for s in sets], self._on_input_changed)`. It sets `window_title` and `input_dropdown` from the picker as aliases, and `_on_input_changed(index)` receives the index.

Rebuild the resources and lint the changed blueprints.

- [ ] **Step 4: Run them and confirm they pass**

Run: `tests.test_input_picker tests.test_playback_surface tests.test_compare_stems_dialog tests.test_dialog_sizing tests.test_dialog_wording` through the headless runner. Then run `./resources/compile_resources.sh --check`.
Expected: PASS, and the bundle matches.

- [ ] **Step 5: Commit**

```bash
git add ui/playback/input_picker.py resources/ui/input-picker.blp resources/ui/compare-stems.blp \
  resources/ui/playback-surface.blp ui/playback/surface.py ui/playback/compare_stems.py ui/data/uvr.gresource \
  tests/test_input_picker.py tests/test_playback_surface.py
git commit -m "refactor(ui): share the input picker and support commit surfaces"
```

---

### Task 7: `TrimDialog`

**Files:**
- Create: `ui/playback/trim.py`, `resources/ui/trim-dialog.blp`, `tests/test_trim_dialog.py`

**Interfaces:**
- Consumes: `CompareView` (plan 1), `PlaybackSurface(commit=, track_keys=, pack_end)`, `InputPicker` (Task 6), `RangeLoop` (Task 5), and the `WaveformView` range API (Task 4).
- Produces:

```python
class TrimDialog:
    def __init__(self, inputs: Sequence[str], engine: PlaybackControls, *, duration: float,
                 starts: Mapping[str, float], on_apply: Callable[[dict[str, float | None]], None],
                 waveforms: PeakLoading | None = None, open_in_window: bool = False,
                 on_toast: Callable[[str], None] | None = None,
                 on_closed: Callable[[], None] | None = None) -> None: ...
    view: CompareView; surface: PlaybackSurface; loop: RangeLoop; picker: InputPicker
    cancel_button: Gtk.Button; reset_button: Gtk.Button; apply_button: Gtk.Button
    def present(self, parent: Gtk.Window | None) -> None: ...
    def close(self) -> None: ...
```

  `on_apply` receives only edited inputs, keyed by absolute path; `None` means "remove the start".

- [ ] **Step 1: Write the failing tests**

Build with `FakeEngine`, `duration=30`, and inputs `["/in/a.wav", "/in/b.wav"]` unless a test says otherwise. A local helper drags the only waveform:

```python
def _drag(dialog, dx, width=200.0):
    waveform = dialog.view.waveforms[0]
    waveform.set_timeline(100.0)
    waveform.begin_range_drag()
    waveform.update_range_drag(dx, width)
    waveform.end_range_drag(0.0, width)
```

Tests:
- `test_shows_the_input_from_its_stored_start`: with `starts={"/in/a.wav": 12.0}`, `engine.calls[0][3] == 12.0`, `range_start == 12.0` and `range_length == 30.0`.
- `test_range_drag_records_an_edit_and_seeks`: `_drag(dialog, 20)` → `("seek", 10.0)` in `engine.calls`; Apply → `applied == [{"/in/a.wav": 10.0}]`.
- `test_apply_writes_only_edited_inputs`: with `starts={"/in/b.wav": 5.0}`, edit a, Apply → `[{"/in/a.wav": 10.0}]`.
- `test_cancel_and_close_discard_edits`: edit, then click Cancel → `applied == []`. Do the same through `surface.close()`.
- `test_reset_removes_the_start`: with `starts={"/in/a.wav": 12.0}`, click Reset → `range_start == 0.0`; Apply → `[{"/in/a.wav": None}]`.
- `test_picker_switches_inputs_keeping_pending_edits`:
  - Edit a to 10.
  - `picker.dropdown.set_selected(1)` → the last load is for `/in/b.wav`.
  - `set_selected(0)` → the load position is `10.0` and `range_start == 10.0`.
  - Edit b, Apply → both appear.
- `test_short_input_range_covers_the_whole_file`: `engine._duration = 20.0`; `engine.on_duration(20.0)` → `dialog.loop.range_end == 20.0`.
- `test_trim_dialog_is_a_commit_surface`: the header shows no title buttons; `track_key_rows` are hidden; `surface.dialog.get_title() == "Choose Sample Range"`.
- `test_reset_is_insensitive_at_zero`: `starts={}` → `reset_button` is insensitive. After a drag it becomes sensitive.

- [ ] **Step 2: Run them and confirm they fail**

Run: `tests.test_trim_dialog` through the headless runner.
Expected: FAIL. `ModuleNotFoundError: ui.playback.trim`.

- [ ] **Step 3: Write `trim-dialog.blp`**

It has three top-level buttons:
- `cancel_button` with label "Cancel"
- `reset_button` with label "Reset" and tooltip "Start from 0:00"
- `apply_button` with label "Apply" and style `suggested-action`

Rebuild the resources and lint the file.

- [ ] **Step 4: Implement `TrimDialog`**

Wiring:
- `loop = RangeLoop(engine)` and `view = CompareView(loop, peaks=waveforms)`.
- The surface is `PlaybackSurface(view, title="Choose Sample Range", commit=True, track_keys=False, open_in_window=…, on_toast=…, on_closed=…)`.
- Header: `pack_start(cancel_button)`, `pack_start(reset_button)`, `pack_end(apply_button)`, and `set_title_widget(picker.widget)`.
- Each input shows as one non-reference track, `Track(os.path.basename(path), path)`.

Showing an input:
- Pause if playing.
- Set `start` to the pending edit, else the stored start.
- Call `loop.set_range(start, duration)` and `view.show_tracks((track,), selected=0, position=start)`.
- Then call `view.waveforms[0].set_range(start, duration)` and connect `on_range_moved`.

Moving or resetting:
- A range move records `pending[abspath] = start if start > 0 else None`, updates the loop range and calls `loop.seek(start)`.
- Reset records `None`, resets both ranges to 0 and seeks to 0.

Buttons:
- Apply calls `on_apply(dict(pending))`, then `surface.close()`. Cancel only closes.
- `reset_button` is sensitive when the current input's effective start is greater than 0.

- [ ] **Step 5: Run them and confirm they pass**

Run: `tests.test_trim_dialog tests.test_playback_surface tests.test_compare_view` through the headless runner.
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add ui/playback/trim.py resources/ui/trim-dialog.blp ui/data/uvr.gresource tests/test_trim_dialog.py
git commit -m "feat(ui): sample trim dialog"
```

---

### Task 8: Entry point on the Sample mode row

**Files:**
- Create: `ui/sample_range.py`, `tests/test_sample_range.py`
- Modify: `resources/ui/page-groups.blp` (add `sample_range_button`), `ui/widgets/page_groups.py`
- Modify: `ui/shared_settings.py` (`sample_mode_subtitle`, `apply_sample_mode_label`, `_write_input_paths`)
- Modify: `ui/inputs.py` (`ViewInputs._commit_paths`)
- Modify: `ui/window.py` (controller, callbacks, external-input sync, close), `ui/ensemble/window.py` (callbacks)
- Test: `tests/test_page_groups.py`, `tests/test_shared_settings.py`, `tests/test_view_inputs.py`

**Interfaces:**
- Consumes: `TrimDialog` (Task 7); `has_custom_start` and `prune_sample_starts` (Task 2).
- Produces:

```python
# ui/shared_settings.py
def sample_mode_subtitle(duration: int, *, custom: bool = False) -> str   # "First 30 s" / "30 s, custom range"

# ui/widgets/page_groups.py
PageGroupCallbacks.on_choose_sample_range: Callable[[], None] | None = None
PageGroupCallbacks.settings_getter: Callable[[], Settings] | None = None
PageGroups.sample_range_button: Gtk.Button | None
PageGroups.sync_sample_range() -> None

# ui/sample_range.py
class SampleRangeController:
    def __init__(self, settings_getter: Callable[[], Settings], *,
                 parent: Callable[[], Gtk.Window | None], save: Callable[[], str | None],
                 toast: Callable[[str], None], on_applied: Callable[[], None]) -> None: ...
    def open(self, inputs: Sequence[str]) -> None: ...
    def close(self) -> None: ...
```

- [ ] **Step 1: Write the failing tests**

In `tests/test_page_groups.py`, patch `ui.widgets.page_groups.playback_unavailable_reason` to return `None` unless a test says otherwise. Build with `settings_getter=lambda: settings` and `on_choose_sample_range=mock`.

- `test_sample_row_label`: replaces the existing test. The subtitle is `"First 45 s"`.
- `test_range_button_sits_before_the_switch`: `button.get_next_sibling()` is a `Gtk.Switch`.
- `test_range_button_needs_sample_mode_and_inputs`:
  - It is insensitive at first.
  - After `sample_row.set_active(True)` it is still insensitive, because there are no inputs.
  - After `input_row.set_paths(["/in/a.wav"])` and `groups.sync_sample_range()`, it is sensitive.
  - Clicking it calls the callback.
- `test_custom_start_changes_the_subtitle`: with starts `{abspath("/in/a.wav"): 12.0}` and that input set, `sync_sample_range()` → `"45 s, custom range"`.
- `test_range_button_explains_missing_playback`: the patch returns `"GStreamer is not installed"`. Turn on sample mode, add inputs and sync → the button is insensitive with that tooltip.

In `tests/test_shared_settings.py`:
- `test_input_save_prunes_sample_starts`: committing the input binding with `["/in/a.wav"]`, when starts hold both a and b, leaves only a.

In `tests/test_view_inputs.py`:
- `test_commit_prunes_sample_starts`: same idea through `_commit_paths`, following that module's existing construction.

In `tests/test_sample_range.py`, which needs a display, patch `ui.sample_range.TrimDialog`, `ui.playback.engine.PlaybackEngine` and `ui.playback.waveforms.WaveformLoader`:
- `test_open_builds_one_dialog_from_settings`:
  - `open([...])` twice → the dialog is built once and `present` is called twice.
  - The keyword arguments include `duration=30`, `starts=settings.process.sample_starts` and `open_in_window=settings.ui.listening_in_window`.
- `test_apply_writes_saves_and_notifies`: call the captured `on_apply({abspath("/in/a.wav"): 12.5, abspath("/in/b.wav"): None})`, with `b` holding 4.0 beforehand and both being inputs.
  - Starts become `{a: 12.5}`.
  - `save` and `on_applied` are called once.
  - A save error string is toasted.
- `test_apply_drops_edits_for_removed_inputs`: with inputs `["/in/a.wav"]`, `on_apply({abspath("/in/gone.wav"): 9.0})` → starts stay `{}`.
- `test_closed_dialog_is_rebuilt_on_next_open`: call the captured `on_closed()`, then `open` → a new dialog.

- [ ] **Step 2: Run them and confirm they fail**

Run: `tests.test_page_groups tests.test_shared_settings tests.test_view_inputs tests.test_sample_range` through the headless runner.
Expected: FAIL. The subtitle wording differs, `sample_range_button` is missing, and `ui.sample_range` does not exist.

- [ ] **Step 3: Implement the row button**

`page-groups.blp` gets a top-level `Gtk.Button sample_range_button` with:
- icon `edit-cut-symbolic`
- tooltip and accessible label "Choose sample range…"
- `valign: center` and the `flat` style

`build_page_groups` changes:
- Add the button with `sample_row.add_suffix(button)`.
- Move it before the row's `Gtk.Switch`. Walk the button's parent `Gtk.Box` for the switch and call `reorder_child_after(button, switch.get_prev_sibling())`. If there is no switch, leave the button where it is.
- Connect `clicked` to `on_choose_sample_range`.

`sync_sample_range()`:
- **Subtitle:** `sample_mode_subtitle(settings.process.sample_mode_duration, custom=has_custom_start(starts, input_row.paths))`.
- **Sensitivity:** sensitive when the sample row is active, there are inputs, and `playback_unavailable_reason()` is `None`.
- **Tooltip:** the reason when playback is unavailable, else "Choose sample range…".
- **When it runs:**
  - on `sample_row` `notify::active`
  - after the page's `on_inputs_changed` (wrap the callback passed to `InputFilesRow`)
  - at the end of `PageGroups.apply`

`apply_sample_mode_label` gains `custom: bool = False`.

- [ ] **Step 4: Prune on input save and add the controller**
- **Pruning:** in `_write_input_paths` and `ViewInputs._commit_paths`, set `settings.process.sample_starts = prune_sample_starts(settings.process.sample_starts, paths)` before saving.
- **`SampleRangeController.open`:**
  - If a dialog is open, present it.
  - Otherwise build `TrimDialog(inputs, PlaybackEngine(), waveforms=WaveformLoader(PeakCache()), …)` from settings and present it over `parent()`.
- **On apply:**
  - Keep only edits whose path is in `{abspath(p) for p in settings.process.input_paths}`.
  - `None` pops the entry; any other value stores `round(start, 3)`.
  - Then call `save()`, toast any error string, and call `on_applied()`.
- **`on_closed`:** clears the dialog.
- **`close()`:** closes any open dialog.

- [ ] **Step 5: Wire both pages**

In `MainWindow`:
- Build `self.sample_range = SampleRangeController(...)` before the page groups:
  - `parent=lambda: self`
  - `save=lambda: self.context.try_save_settings(trigger="sample-range")`
  - `toast=self.toast`
  - `on_applied=self._on_sample_range_applied`
- `_on_sample_range_applied` syncs `self._page_groups` and the ensemble page's groups through a new `EnsemblePage.sync_sample_range()`.
- `_on_external_inputs_changed` calls `self._page_groups.sync_sample_range()`.
- `_finalize_close` calls `self.sample_range.close()`.

On both pages, the callbacks pass `settings_getter=lambda: self.settings` and `on_choose_sample_range=lambda: <controller>.open(list(self.input_row.paths))`. The ensemble page reaches the controller through `self.window.sample_range`.

- [ ] **Step 6: Run them and confirm they pass**

Run: `tests.test_page_groups tests.test_shared_settings tests.test_view_inputs tests.test_sample_range tests.test_flush_settings_tab_guard` through the headless runner, plus every test module that names `sample_mode_subtitle` or `sample_row` (`rg -l "sample_row|sample_mode_subtitle" tests`).
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add resources/ui/page-groups.blp ui/widgets/page_groups.py ui/shared_settings.py ui/inputs.py \
  ui/sample_range.py ui/window.py ui/ensemble/window.py ui/data/uvr.gresource \
  tests/test_page_groups.py tests/test_shared_settings.py tests/test_view_inputs.py tests/test_sample_range.py
git commit -m "feat(ui): choose the sample range from the Sample mode row"
```

---

### Task 9: Whole-tree verification

- [ ] **Step 1: Run the full suite**

Run: `discover -s tests -t .` through the headless runner.
Expected: OK, with the plan 1 count (4479) plus the added tests and 3 skipped.

- [ ] **Step 2: Type-check, lint and check resources**

Run:
- `.venv/bin/python -m basedpyright`
- `.venv/bin/ruff check` and `.venv/bin/ruff format --check` on the touched `.py` files that still exist
- `./resources/compile_resources.sh --check`

Expected: 0 errors, ruff clean, and the bundle matches.

- [ ] **Step 3: Hand the manual check to the user**

List the manual check for the user to do:
- Turn on sample mode and open the range dialog.
- Drag the range; click to seek.
- Let playback loop past the range end.
- Apply, then run. The output starts at the chosen time.
- Reopen the dialog, use Reset, and confirm that the plan review reads "First 30 s".
