# Listening Tools 1: Shared Compare Component Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Split the Compare Stems dialog into a reusable `CompareView` (rows, waveforms, transport, keys) and `PlaybackSurface` (header, dialog/window hosting, pop-out). Compare Stems is rebuilt from those two parts with no change in behaviour.

**Architecture:** `CompareView` is a `Gtk.Box` template that owns engine wiring and the track list. `PlaybackSurface` is a plain Python object that owns an `Adw.Dialog` built from Blueprint. It can move its `Adw.ToolbarView` into a `FadingWindow`, and its capture-phase key controller forwards to `view.handle_key`. `CompareStemsDialog` composes the two and adds the folder button and input picker. The pop-out work already in the working tree, which is uncommitted, lands first under the renamed setting.

**Tech Stack:** Python 3.12+, GTK4/libadwaita via PyGObject, Blueprint, stdlib unittest, basedpyright, ruff.

**Spec:** `docs/superpowers/specs/2026-10-07-listening-tools-design.md` (section 1 only)

## Global Constraints

- Compare Stems behaviour must not change. Existing assertions pass with only path or name changes.
- Setting `ui.listening_in_window: bool = False` is added to the model, defaults, flat map and the coerce bool set. `ui.compare_in_window` is removed with no migration; a stale key is dropped silently on load.
- Preferences → General has a group "Listening tools" with switch "Open in a separate window" and subtitle "Applies to Compare Stems, sample trim and algorithm audition".
- Window minimum is 360×294 and the default width is 600. The surface's `Adw.Dialog` blueprint keeps `content-width: 600; width-request: 360; height-request: 294;`.
- Present the dialog through `present_modal_dialog`. Escape closes the popped-out window (`close_on_escape`).
- The engine error toast text is exactly `Couldn't start playback. {message}`.
- Blueprint changes need `./resources/compile_resources.sh`. Commit the rebuilt `ui/data/uvr.gresource` with them. Generated `.ui` files are not committed.
- Search with `rg`. Stage files explicitly; never use `git add -A`. Plans and specs stay on `dev` (`git add -f`).
- **Headless runner.** Every GTK test command below means this prefix followed by `-m unittest <modules>`:
  `env -u DISPLAY -u WAYLAND_DISPLAY -u DBUS_SESSION_BUS_ADDRESS -u DBUS_SYSTEM_BUS_ADDRESS -u XDG_RUNTIME_DIR -u XAUTHORITY -u SESSION_MANAGER -u UVR_REQUIRE_PRIVATE_GTK GDK_BACKEND=x11 GSK_RENDERER=cairo xvfb-run -a -s "-screen 0 1920x1080x24" .venv/bin/python`

## Review Focus

1. **Switching input while popped out.** Rows rebuild inside the window, and number keys reach the new rows. Test: Task 3, `test_switching_input_in_popped_out_window_rebuilds_rows`.
2. **A run starts or the app quits while the window is popped out.** `RunController` calls `close()`. The window closes, the engine unloads exactly once, and `on_closed` fires once. Test: Task 3, `test_close_when_popped_out_unloads_once`.
3. **Peaks that arrive after the view shut down** must not touch the widgets. Test: Task 2, `test_late_peaks_after_shutdown_are_ignored`.
4. **An empty track list** must not raise. The transport goes insensitive and the engine is not loaded. Test: Task 2, `test_empty_tracks_leave_transport_insensitive`.
5. **A user whose settings.json still has `compare_in_window`** loads cleanly with the new setting off. Test: Task 1, `test_stale_compare_window_key_is_dropped`.

---

### Task 1: Land the pop-out under `ui.listening_in_window`

The working tree already contains the pop-out button, `open_in_window`, the `uvr-pop-out-symbolic` icon and the `compare_in_window` setting, all uncommitted. This task renames the setting and its Preferences copy, then commits everything together.

**Files:**
- Modify: `core/settings/model.py`, `core/settings/defaults.py`, `core/settings/flat_map.py`, `core/settings/coerce.py` (rename the field)
- Modify: `resources/ui/preferences.blp` (group and row), `ui/preferences.py:283-288,576`
- Modify: `ui/run_control.py:1052`
- Test: `tests/test_settings_typed.py`, `tests/test_preferences_design.py`, `tests/test_compare_run_integration.py`
- Already modified, committed as-is: `resources/ui/compare-stems-dialog.blp`, `ui/playback/dialog.py`, `tests/test_compare_dialog.py`, `resources/icons/scalable/actions/uvr-pop-out-symbolic.svg` (untracked), `ui/data/uvr.gresource`

**Interfaces:**
- Produces: `settings.ui.listening_in_window: bool` (default False), flat key `"listening_in_window"`, `PreferencesDialog.listening_in_window_row: Adw.SwitchRow`.

- [ ] **Step 1: Update the tests**

In `tests/test_settings_typed.py`, rename `test_compare_window_defaults_off_and_round_trips` to `test_listening_window_defaults_off_and_round_trips` and use `ui.listening_in_window` throughout. Add:

```python
def test_stale_compare_window_key_is_dropped(self):
    settings = Settings.from_json_dict(coerce_json_dict({"ui": {"compare_in_window": True}}))
    self.assertFalse(settings.ui.listening_in_window)
    self.assertNotIn("compare_in_window", settings.to_json_dict()["ui"])
```

In `tests/test_preferences_design.py`, rename the test to `test_listening_window_switch_writes_and_reloads`. Use `dialog.listening_in_window_row` and `settings.ui.listening_in_window`, and add:

```python
self.assertEqual(dialog.listening_in_window_row.get_title(), "Open in a separate window")
self.assertEqual(
    dialog.listening_in_window_row.get_subtitle(),
    "Applies to Compare Stems, sample trim and algorithm audition",
)
```

In `tests/test_compare_run_integration.py` `test_open_compare_presents_one_dialog`, set `controller._host.settings.ui.listening_in_window = True` before opening, and assert `dialog_cls.call_args.kwargs["open_in_window"] is True`.

- [ ] **Step 2: Run them and confirm they fail**

Run: `.venv/bin/python -m unittest tests.test_settings_typed tests.test_compare_run_integration`, plus `tests.test_preferences_design` through the headless runner.
Expected: FAIL. `UiSettings` has no attribute `listening_in_window`.

- [ ] **Step 3: Rename the setting and the copy**

Rename the field in all four settings files to `listening_in_window`. In `preferences.blp`, the group title becomes `"Listening tools"`, the row id becomes `listening_in_window_row`, and the subtitle becomes `"Applies to Compare Stems, sample trim and algorithm audition"`. Rename the attribute, the flat key and the reload line in `ui/preferences.py`. In `run_control.py`, pass `open_in_window=self._host.settings.ui.listening_in_window`. Rebuild the resources.

- [ ] **Step 4: Run the tests and confirm they pass**

Run: the Step 2 modules plus `tests.test_compare_dialog` through the headless runner, then `rg -n compare_in_window` (expected: no hits outside `docs/`).
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add core/settings/model.py core/settings/defaults.py core/settings/flat_map.py core/settings/coerce.py \
  resources/ui/preferences.blp resources/ui/compare-stems-dialog.blp ui/preferences.py ui/run_control.py \
  ui/playback/dialog.py ui/data/uvr.gresource resources/icons/scalable/actions/uvr-pop-out-symbolic.svg \
  tests/test_settings_typed.py tests/test_preferences_design.py tests/test_compare_run_integration.py \
  tests/test_compare_dialog.py
git commit -m "feat(ui): pop Compare Stems out into its own window"
```

---

### Task 2: Extract `CompareView`

**Files:**
- Create: `ui/playback/view.py`, `resources/ui/compare-view.blp`, `tests/playback_fakes.py`, `tests/test_compare_view.py`
- Modify: `ui/playback/dialog.py` (compose the view), `resources/ui/compare-stems-dialog.blp` (drop the scroller and transport), `tests/test_compare_dialog.py` (drop the moved tests; import the fakes)

**Interfaces:**
- Produces, in `ui/playback/view.py`:

```python
RowSuffix = Callable[[int, Track], Gtk.Widget | None]

class CompareView(Gtk.Box):            # __gtype_name__ = "UvrCompareView"
    def __init__(self, engine: PlaybackControls, *, peaks: PeakLoading | None = None,
                 row_suffix: RowSuffix | None = None) -> None: ...
    def show_tracks(self, tracks: Sequence[Track], *, selected: int | None = None,
                    position: float = 0.0) -> None: ...
    def handle_key(self, keyval: int) -> bool: ...
    def shutdown(self) -> None: ...     # cancel peaks, then engine.unload()
    on_error: Callable[[str], None]     # receives the full toast text
    # inspectable: rows, titles, waveforms, key_hints, checks, track_list,
    # play_button, back_button, forward_button, elapsed_label, total_label
```

- Produces, in `tests/playback_fakes.py`: `FakeEngine`, `FakeLoader` and `comparison_set(name, *labels) -> ComparisonSet`. These are moved from `test_compare_dialog.py` without changes; `_set` becomes `comparison_set`.

- [ ] **Step 1: Move the tests and the fakes**

Move `FakeEngine`, `FakeLoader` and `_set` into `tests/playback_fakes.py`, which is not a test module. In `tests/test_compare_view.py` (same skip guard and `setUpClass`), use a `_view(*, loader=False, row_suffix=None) -> tuple[CompareView, FakeEngine]` helper. It builds `CompareView(engine, peaks=self.loader, row_suffix=row_suffix)` without showing anything, so each moved test first calls `view.show_tracks(comparison_set(...).tracks)`. `_deliver` moves over unchanged. Move every test that covers rows, keys, waveforms, peaks, timeline, transport or engine callbacks. Leave the header, dropdown, folder, pop-out, closed-signal and "many tracks scroll" tests in `test_compare_dialog.py`. Rename the moved tests as follows:
- "switching input resets timeline" and "reloads peaks" become `test_show_tracks_again_resets_timeline` and `test_show_tracks_again_reloads_peaks`.
- "close cancels peaks before unload" becomes `test_shutdown_cancels_peaks_before_unload`.
- "engine error disables transport and toasts" becomes `test_engine_error_disables_transport_and_reports`. Its assertion is `errors == ["Couldn't start playback. No audio sink"]`, collected through `view.on_error = errors.append`.

Add these tests:

```python
def test_selected_overrides_the_default_track(self) -> None:
    view, engine = self._view()
    view.show_tracks(comparison_set("song", "Vocals", "Instrumental").tracks, selected=2)
    self.assertEqual(engine.calls[-1][2], 2)
    self.assertEqual([c.get_active() for c in view.checks], [False, False, True])

def test_row_suffix_is_added_and_rebuilt(self) -> None:
    made: list[int] = []
    def suffix(index: int, _track: Track) -> Gtk.Widget | None:
        made.append(index)
        return Gtk.Button(label="Keep") if index else None
    view, _ = self._view(row_suffix=suffix)
    tracks = comparison_set("song", "Vocals").tracks
    view.show_tracks(tracks)
    view.show_tracks(tracks)
    self.assertEqual(made, [0, 1, 0, 1])
    self.assertEqual(len(_buttons_in(view.rows[0])), 0)
    self.assertEqual(len(_buttons_in(view.rows[1])), 1)

def test_late_peaks_after_shutdown_are_ignored(self) -> None:
    view, _ = self._view(loader=True)
    view.show_tracks(comparison_set("song", "Vocals").tracks)
    view.shutdown()
    self._deliver(0, 8.0)
    self.assertIsNone(view.waveforms[0].peaks)

def test_empty_tracks_leave_transport_insensitive(self) -> None:
    view, engine = self._view()
    view.show_tracks(())
    self.assertEqual(view.rows, [])
    self.assertFalse(view.play_button.get_sensitive())
    self.assertNotIn("load", [c[0] for c in engine.calls])
```

`_buttons_in(widget)` is a local helper that walks descendants (`tests.gtk_layout_helpers.iter_descendants`) and collects `Gtk.Button`s.

- [ ] **Step 2: Run them and confirm they fail**

Run: `tests.test_compare_view` through the headless runner.
Expected: FAIL. `ModuleNotFoundError: ui.playback.view`.

- [ ] **Step 3: Write `compare-view.blp`**

`template $UvrCompareView: Gtk.Box` with `orientation: vertical`. Its children are the `Gtk.ScrolledWindow` (`vexpand: true`, ids, properties and comments moved verbatim) holding `track_list`, then the transport `Gtk.Box` moved verbatim from `compare-stems-dialog.blp`. That blueprint keeps only the dialog, the toolbar and the header. Rebuild the resources and run `blueprint-compiler lint resources/ui/compare-view.blp`.

- [ ] **Step 4: Implement `CompareView` in `ui/playback/view.py`**

Use the `@Gtk.Template` idiom from `ui/widgets/log_panel.py`: call `require_resource_bundle` before the decorator, and call `Adw.init()` before `super().__init__()`. Move the code over from `CompareDialog`:
- `_add_row`, `_select`, `_skip`, the check/row/peak/timeline handlers, the engine callbacks and `handle_key`
- the constants `_SEEK_STEP`, `_PLAY_ICON`, `_PAUSE_ICON`, `_NUMBER_KEYS` and `_mmss`

`show_tracks` is the old `_show_set` taking tracks directly:
- `selected=None` means `1 if len(tracks) > 1 else 0`.
- With no tracks, it clears the rows, makes the play button insensitive and returns before `load`.

`row_suffix(index, track)` is appended at the end of the row header, after the key hint, whenever it returns a widget. `shutdown()` sets a flag that makes `_on_peaks` a no-op until the next `show_tracks`. The default `on_error` is a no-op.

- [ ] **Step 5: Make `CompareDialog` compose the view**

`self.view = CompareView(engine, peaks=waveforms)`, set as `self._toolbar` content. The dialog wires the following to the view:
- `view.on_error = self._toast`
- the key controller calls `self.view.handle_key`
- `_finish` and `close` call `view.shutdown()`
- the input switch calls `view.show_tracks(self._sets[i].tracks, position=position)`

The remaining tests in `test_compare_dialog.py` reach rows through `dialog.view`.

- [ ] **Step 6: Run the tests and confirm they pass**

Run: `tests.test_compare_view tests.test_compare_dialog tests.test_dialog_sizing tests.test_dialog_wording tests.test_compare_run_integration` through the headless runner. Then run `./resources/compile_resources.sh --check`.
Expected: PASS, and the bundle matches.

- [ ] **Step 7: Commit**

```bash
git add ui/playback/view.py ui/playback/dialog.py resources/ui/compare-view.blp \
  resources/ui/compare-stems-dialog.blp ui/data/uvr.gresource \
  tests/playback_fakes.py tests/test_compare_view.py tests/test_compare_dialog.py
git commit -m "refactor(ui): extract the compare track list into CompareView"
```

---

### Task 3: `PlaybackSurface` and `CompareStemsDialog`

**Files:**
- Create: `ui/playback/surface.py`, `resources/ui/playback-surface.blp`, `ui/playback/compare_stems.py`, `resources/ui/compare-stems.blp`, `tests/test_playback_surface.py`
- Rename: `tests/test_compare_dialog.py` → `tests/test_compare_stems_dialog.py` (`git mv`)
- Delete: `ui/playback/dialog.py`, `resources/ui/compare-stems-dialog.blp`, and the stale generated `resources/ui/compare-stems-dialog.ui`
- Modify: `ui/run_control.py:1041-1053`, `tests/test_compare_run_integration.py:164` (patch target), `tests/test_dialog_sizing.py` (the `TIERS` key `"compare-stems-dialog"` becomes `"playback-surface"`, and the comment says "Compare Stems' surface")

**Interfaces:**
- Consumes: `CompareView` (Task 2).
- Produces, in `ui/playback/surface.py`:

```python
class PlaybackSurface:
    def __init__(self, view: CompareView, *, title: str, open_in_window: bool = False,
                 on_toast: Callable[[str], None] | None = None,
                 on_closed: Callable[[], None] | None = None) -> None: ...
    dialog: Adw.Dialog
    window: FadingWindow | None
    popout_button: Gtk.Button
    keys: Gtk.EventControllerKey
    def present(self, parent: Gtk.Window | None) -> None: ...
    def pop_out(self) -> None: ...
    def close(self) -> None: ...
    def toast(self, message: str) -> None: ...
    def pack_start(self, widget: Gtk.Widget) -> None: ...
    def set_title_widget(self, widget: Gtk.Widget) -> None: ...
    def toplevel(self) -> Gtk.Window | None: ...   # window, else parent, else root_window(dialog)
```

- Produces, in `ui/playback/compare_stems.py`: `CompareStemsDialog` with the same constructor as today's `CompareDialog`, the attributes `view`, `surface`, `window_title`, `input_dropdown` and `folder_button`, and the methods `present(parent)` and `close()`.

- [ ] **Step 1: Write the surface tests**

In `tests/test_playback_surface.py`, `_surface(open_in_window=False, loader=False) -> tuple[PlaybackSurface, FakeEngine]` records into `self.toasts` and `self.closed`. It builds `CompareView(FakeEngine(), peaks=...)`, calls `show_tracks(comparison_set("song", "Vocals").tracks)`, and wraps it in `PlaybackSurface(view, title="Compare Stems", on_toast=toasts.append, on_closed=...)`. Move the four pop-out tests from `test_compare_stems_dialog.py`, plus "shortcuts are captured before focused children" and "closed signal unloads and notifies". Each one targets `surface.window`, `surface.popout_button` and `surface.keys`. Add:

```python
def test_close_when_popped_out_unloads_once(self) -> None:
    surface, engine = self._surface()
    surface.pop_out()
    surface.close()
    self.assertEqual([c for c in engine.calls if c == ("unload",)], [("unload",)])
    self.assertEqual(self.closed, [True])

def test_close_in_dialog_mode_unloads_once(self) -> None:
    surface, engine = self._surface()
    surface.close()
    surface.dialog.emit("closed")
    self.assertEqual([c for c in engine.calls if c == ("unload",)], [("unload",)])
    self.assertEqual(self.closed, [True])

def test_engine_error_toasts_through_the_surface(self) -> None:
    surface, engine = self._surface()
    engine.on_error("No audio sink")
    self.assertEqual(self.toasts, ["Couldn't start playback. No audio sink"])

def test_tool_widgets_go_into_the_header(self) -> None:
    surface, _ = self._surface()
    start, title = Gtk.Button(), Gtk.Label()
    surface.pack_start(start)
    surface.set_title_widget(title)
    for widget in (start, title):
        self.assertIsNotNone(widget.get_ancestor(Adw.HeaderBar))
```

- [ ] **Step 2: Adapt the Compare Stems tests**

`git mv tests/test_compare_dialog.py tests/test_compare_stems_dialog.py`, then import `CompareStemsDialog` from `ui.playback.compare_stems` and the fakes from `tests.playback_fakes`. "Many tracks scroll" measures `dialog.surface.dialog.get_child()`. Add:

```python
def test_switching_input_in_popped_out_window_rebuilds_rows(self) -> None:
    dialog, engine = self._dialog(
        comparison_set("a", "Vocals"), comparison_set("b", "Vocals", "Drums")
    )
    dialog.surface.pop_out()
    dialog.input_dropdown.set_selected(1)
    self.assertIs(dialog.view.rows[2].get_root(), dialog.surface.window)
    self.assertTrue(dialog.view.handle_key(Gdk.KEY_3))
    self.assertEqual(engine.calls[-1], ("select", 2))
    dialog.close()

def test_folder_opens_over_the_popped_out_window(self) -> None:
    dialog, _ = self._dialog(comparison_set("song", "Vocals"), output_dir="/tmp")
    dialog.surface.pop_out()
    with mock.patch("ui.playback.compare_stems.open_folder_in_file_manager") as open_folder:
        dialog.folder_button.emit("clicked")
    self.assertIs(open_folder.call_args.args[0], dialog.surface.window)
    dialog.close()
```

Point the `test_compare_run_integration.py` patch at `ui.playback.compare_stems.CompareStemsDialog`.

- [ ] **Step 3: Run them and confirm they fail**

Run: `tests.test_playback_surface tests.test_compare_stems_dialog tests.test_compare_run_integration` through the headless runner.
Expected: FAIL. `ModuleNotFoundError: ui.playback.surface`.

- [ ] **Step 4: Write the blueprints**

`playback-surface.blp` contains:
- `Adw.Dialog dialog` with `content-width: 600; width-request: 360; height-request: 294;` and no title (set from Python)
- `Adw.ToolbarView toolbar` with `[top] Adw.HeaderBar header` holding the `[end]` `popout_button` and the keyboard-shortcuts `Gtk.MenuButton`, both moved verbatim

`compare-stems.blp` has two top-level objects, moved verbatim:
- `Gtk.Button folder_button`
- `Gtk.Box title_box` holding `window_title` (title "Compare Stems") and `input_dropdown`

Delete `compare-stems-dialog.blp` and its stale `.ui`, rebuild, and lint both new files.

- [ ] **Step 5: Implement `PlaybackSurface`**

Move `present`, `pop_out`, the close handlers, `_finish` and toast routing from `CompareDialog`, along with the `_WINDOW_*` constants.

The constructor:
- sets the dialog title to `title`
- calls `toolbar.set_content(view)`
- sets `view.on_error = self.toast`
- attaches `keys` (capture phase, forwarding to `view.handle_key`) to the dialog
- connects `popout_button` to `pop_out`

The window is `FadingWindow(title=title)`. `_finish()` is guarded by a `_finished` flag: it runs `view.shutdown()` and then `on_closed` exactly once. `close()` closes the window, or force-closes the dialog, then calls `_finish()`.

- [ ] **Step 6: Implement `CompareStemsDialog`**

Move `_input_factory`, the picker setup, `_on_input_changed` and `_on_open_folder` from `dialog.py`; the folder parent is `surface.toplevel()`. Build the view, then the surface with `title=_TITLE`. Call `surface.pack_start(folder_button)` and `surface.set_title_widget(title_box)`, then `view.show_tracks(self._sets[0].tracks)` when sets exist. Delete `ui/playback/dialog.py`. In `run_control.py`, import and build `CompareStemsDialog` from `.playback.compare_stems`.

- [ ] **Step 7: Run the tests and confirm they pass**

Run: `tests.test_playback_surface tests.test_compare_stems_dialog tests.test_compare_view tests.test_compare_run_integration tests.test_dialog_sizing tests.test_dialog_wording tests.test_preferences_design` through the headless runner. Then run `./resources/compile_resources.sh --check` and `rg -n "CompareDialog|playback\.dialog|compare-stems-dialog" -g '!docs/**'`.
Expected: PASS, the bundle matches, and the search finds nothing.

- [ ] **Step 8: Commit**

```bash
git add ui/playback/surface.py ui/playback/compare_stems.py resources/ui/playback-surface.blp \
  resources/ui/compare-stems.blp ui/run_control.py ui/data/uvr.gresource \
  tests/test_playback_surface.py tests/test_compare_stems_dialog.py \
  tests/test_compare_run_integration.py tests/test_dialog_sizing.py
git rm ui/playback/dialog.py resources/ui/compare-stems-dialog.blp
git commit -m "refactor(ui): host compare tools in a shared PlaybackSurface"
```

`tests/test_compare_dialog.py` is already staged as a rename by `git mv`.

---

### Task 4: Whole-tree verification

- [ ] **Step 1: Run the full suite**

Run: `-m unittest discover -s tests -t .` through the headless runner.
Expected: OK. The count is the pre-plan 4461 plus the added tests, with 3 skipped.

- [ ] **Step 2: Type-check and lint**

Run: `.venv/bin/python -m basedpyright`, then `.venv/bin/ruff check` and `.venv/bin/ruff format --check` on every Python file touched by Tasks 1–3.
Expected: 0 errors, and ruff is clean.

- [ ] **Step 3: Smoke test by hand**

Run `./run_uvr.sh`, then do a short run and open Compare Stems from the toast. Check that:
- the pop-out button moves playback into a window without stopping it
- Escape closes the window
- the Preferences switch makes the next Compare Stems open as a window

Report what was observed. If there is no display, say the smoke test was skipped.
