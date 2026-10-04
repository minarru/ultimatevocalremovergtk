# Dialog Consistency Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every dialog follows one set of rules for wording, action placement, dismissal and sizing, with the named exceptions, pinned by tests and checked against before/after screenshots.

**Architecture:** The shared presentation helper `present_modal_dialog` in `ui/dialogs/utils.py` gains a `dismiss_on_backdrop` keyword and a width cap, and every `Adw.Dialog` routes through it. Commit dialogs get a Cancel / suggested-action header with no close button. Sizes move into each dialog's Blueprint. Wording is plain string edits, guarded by a scanning test.

**Tech Stack:** GTK4/libadwaita through PyGObject, Blueprint (`.blp` compiled by `./resources/compile_resources.sh`), stdlib `unittest`, basedpyright, ruff.

**Spec:** `docs/superpowers/specs/2026-10-03-dialog-consistency-design.md` (on `dev`). Read it first; it has the catalogue and the reason for each exception.

## Global Constraints

- Work on the branch `claude/dialog-consistency`, created from `claude/ui-consistency-fixes`, which touches `ui/dialogs/model_params.py` too. The plan and spec live on `dev` only. Never commit them on the feature branch.
- Title case for dialog titles, button labels and alert headings: capitalize each word, but keep these lowercase unless first: a, an, and, as, at, but, by, for, in, of, on, or, the, to, with. Body text, descriptions and row titles keep sentence case. Quoted names keep their own spelling.
- The three content widths are 440 (forms, short info), 600 (single-column lists and tools) and 800 (browsers, two-column sheets).
- Minimum size is 360×294 on every `Adw.Dialog`. Choose Model keeps a 480 minimum height and Review Processing Plan keeps 400.
- Window cap: `max(360, min(width, parent_width − 64))`.
- Exceptions to the sizing rules:
  - Settings (`Adw.PreferencesDialog`), About (`Adw.AboutDialog`) and Keyboard Shortcuts (`Adw.ShortcutsDialog`) keep libadwaita's sizing.
  - Download Center and Error Log are windows and keep their own sizes.
  - Review Processing Plan keeps its bottom pills.
- Run GTK tests only through the private display runner. Redirect output to a file and never pipe it:
  `T="$HOME/.claude/skills/testing-gtk-headless/scripts/run-private-wayland.sh"; $T -- env UVR_DISABLE_POLITREES=1 UVR_DISABLE_MVSEPLESS=1 .venv/bin/python -m unittest <targets> > /tmp/uvr-test.log 2>&1; tail -5 /tmp/uvr-test.log`
- New GTK test classes use `@unittest.skipUnless(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"), ...)` and `require_version` in `setUpClass`, as in `tests/test_control_types.py`. Wait for dialogs with `tests.gtk_layout_helpers.wait_for_dialog_open`. Never call `widget.destroy()`.
- After any `.blp` change, run `./resources/compile_resources.sh` and stage `ui/data/uvr.gresource` with it.
- Before each commit, run `.venv/bin/ruff format` and `.venv/bin/ruff check` on the touched Python files.

## Review Focus

1. **A dialog stacked over another dialog:** Custom Stems over Save Stems, Change Model Defaults over Model Options, Delete Stored Parameters over Change Model Defaults. A backdrop click closes only the top dialog. (Task 2, `test_stacked_backdrop_closes_only_the_top_dialog`.)
2. **A reused dialog presented again after the window was resized:** Model Options, Member Models and Compare Stems are kept and re-presented. They must return to their design width on a wide window after being capped on a narrow one. (Task 5, `test_cap_restores_design_width_on_wider_parent`.)
3. **Escape on a commit dialog:** Escape must discard edits exactly like Cancel. Blend Options must not apply, and parameter forms return `None`. (Task 3, `test_escape_discards_blend_edits`.)
4. **The Updates button label is also its state:** `_on_check_or_update` compares the label text. The new case "Check Again" must still trigger a re-check. (Task 4, existing `tests/test_update_view.py` cases with updated strings.)
5. **Python-built headings that only appear at run time:** the f-string run-failure heading, OOM headings and quit headings. The wording test scans source, so it must cover f-strings and `heading = ...` assignments. (Task 4, `test_python_dialog_strings_are_title_case`.)

---

### Task 1: Capture "before" screenshots

**Files:**
- Create: `.superpowers/dialog-screenshots/capture.py` (local scratch; never staged)
- Output: `.superpowers/dialog-screenshots/before/*.png`

**Interfaces:**
- Produces: `capture.py --out before|after`. Task 6 reruns it unchanged with `--out after`.

- [ ] **Step 1: Write the capture script**

The script runs under the private display runner with `UVR_DATA_DIR=/tmp/uvr-shot/data`. Before launching, symlink the repo's `models/` into that directory so Choose Model lists real models. The script must `import tests` first so the network guard is armed.

It builds a `MainWindow` (`ui.window.MainWindow`) on an `Adw.Application` and sizes it with `tests.gtk_layout_helpers.resize_window`. For each entry it then:
1. opens the dialog;
2. waits with `wait_for_dialog_open`, or for an `Adw.Window`, until it is mapped with width > 0, then spins about 300 ms;
3. saves a PNG of the host window;
4. closes the dialog.

Use this capture code. It was verified headless on 2026-10-04: the window snapshot includes the open dialog.

```python
def shot(widget: Gtk.Widget, path: str) -> None:
    paintable = Gtk.WidgetPaintable.new(widget)
    snap = Gtk.Snapshot()
    paintable.snapshot(snap, widget.get_width(), widget.get_height())
    texture = widget.get_native().get_renderer().render_texture(snap.to_node(), None)
    texture.save_to_png(path)
```

Variants and names: `<name>-light.png` and `<name>-dark.png` at 1040×720, plus `<name>-narrow.png` at the window minimum of 640×560 in light. Switch themes with `Adw.StyleManager.get_default().set_color_scheme(Adw.ColorScheme.FORCE_LIGHT / FORCE_DARK)`.

Entries, with representative content. Patch anything that would reach the network or start a run:

| name | how to open |
|---|---|
| choose-model | `win._open_model_picker()` |
| member-models | `win._ensemble_page._open_models_dialog()` |
| model-options | `win._open_model_options(...)` (read its signature in `ui/window.py`) |
| save-stems | the Separation view's output-stems widget `_present()` (`ui/widgets/output_stems.py`) |
| custom-stems | the stem-only widget `_open_custom_stems_dialog()` (`ui/widgets/stem_only.py`); shot taken over its parent |
| verify-inputs | add three 1-second WAVs and one zero-byte `.wav` from `/tmp/uvr-shot/inputs` as inputs, then `open_view_inputs(...)` |
| input-pairs | `DualBatchDialog(win, labels, pairs, lambda *_: None).present()` with two pairs |
| blend-options | `show_blend_dialog(win, win.settings, members, lambda _o: None)` with two members, as in `tests/test_ensemble_blend_dialog.py` |
| review-plan | `ReviewPlanDialog(tests.test_plan_review.resolved_plan(ensemble=True))` presented over `win` |
| params-vr / params-mdx / params-mdxc / params-apollo | build each form as `tests/test_control_types.py` builds `_ParamDialog`, then call its `run()`. Use `GLib.timeout_add` to take the shot and close the dialog while the blocking loop runs |
| change-defaults | `show_change_defaults_dialog(win.context, win)` |
| compare-stems | `CompareDialog([...], FakeEngine())` using `_set` and `FakeEngine` from `tests/test_compare_dialog.py` |
| run-failure | `present_error_dialog(win, heading="Separation failed", exception=RuntimeError("CUDA error: device-side assert triggered"), formatted_log="Traceback …")` (use the current heading text on each run) |
| manual-downloads | `open_manual_downloads(center_window, win.context)`, shot of the center window |
| updates | `UpdateView(win, win.context)` with `download_manager.update_status` patched to `{"version": "5.6.x", "upstream_base": "5.6"}` and `_check` patched out |
| settings | `win._on_open_settings(None, None)` |
| about | `open_about(win)` |
| shortcuts | `present_shortcuts(win)` |
| download-center | `open_download_center(win, win.context)`, shot of that window |
| error-log | `open_error_log(win)`, shot of that window |
| alert-stop | `win._run_controller._present_stop_confirm()` |
| alert-quit-processing / alert-quit-downloads / alert-quit-both | `win._run_controller._present_shutdown_confirm()` with `_active_download_count` and the running state patched for each case |
| alert-not-stopped | `win._run_controller._on_stop_timeout(target)` with `_running_target = target` |
| alert-oom | `present_oom_choice_dialog(win, mock_oom_request(separation=False), on_choice=lambda _c: None)` |
| alert-profile-replace / load / remove / reset / save | the matching `PreferencesDialog` handlers (`_on_save_profile`, `_on_load_profile`, `_on_remove_profile`, `_on_reset_clicked`, `_on_save_profile_requested`) with a profile named "Live" |
| alert-download-missing | `win._ensemble_page._offer_download_missing([...])` with one missing tag |
| alert-save-ensemble | `win._ensemble_page._present_save_dialog(["mdx:a", "mdx:b"])` |
| alert-delete-ensemble | `win._ensemble_page._on_delete_clicked(None)` with a saved ensemble selected |
| alert-delete-params | the Delete row inside change-defaults with a model that has stored parameters |

If an entry cannot be opened without heavy setup, log it as `SKIPPED <name>: <reason>` and continue. The run must not stop on one failure. The before and after runs share the same skip list.

- [ ] **Step 2: Run on the unchanged branch**

Run: `$T -- env UVR_DATA_DIR=/tmp/uvr-shot/data UVR_DISABLE_POLITREES=1 UVR_DISABLE_MVSEPLESS=1 .venv/bin/python .superpowers/dialog-screenshots/capture.py --out before > /tmp/uvr-shot/before.log 2>&1`
Expected: one PNG per entry and variant in `before/`, and no `Traceback` in the log except for logged `SKIPPED` lines.

- [ ] **Step 3: Spot-check three images with the Read tool**

Check `choose-model-light.png`, `alert-stop-dark.png` and `review-plan-narrow.png`. Each must show the dialog over the window. Nothing to commit.

---

### Task 2: Dismissal

**Files:**
- Modify: `ui/dialogs/utils.py` (`_install_backdrop_dismiss`, `_try_install_backdrop_dismiss`, `present_modal_dialog`, `run_blocking_dialog`)
- Modify: `ui/model_picker.py:249`, `ui/window.py:1229`, `ui/about.py:133`, `ui/shortcuts.py:109`: present through the helper (default backdrop close)
- Modify: `ui/audio_tools/dual_batch.py:234`, `ui/ensemble/blend_dialog.py:76`, `ui/run_control.py:404`: present through the helper with `dismiss_on_backdrop=False`
- Test: `tests/test_dialog_presentation.py` (new)

**Interfaces:**
- Produces: `present_modal_dialog(dialog: Adw.Dialog, parent: Gtk.Window | None = None, *, dismiss_on_backdrop: bool = True) -> None`
- Produces: the widget-state key `_uvr_backdrop_dialog` on a dimming widget. It holds the dialog that a backdrop click closes, and replaces the boolean `_uvr_backdrop_dismiss`.

- [ ] **Step 1: Write the failing tests**

Helper: `_backdrop(dialog)` returns the `Gtk.Widget` whose `get_css_name() == "dimming"` inside `dialog`'s own subtree. `_click(dimming)` finds the `Gtk.GestureClick` in `dimming.observe_controllers()` and emits `"released"` with `(1, 0.0, 0.0)`. Each test presents dialogs over an `Adw.Window` sized 900×700 with `resize_window`.

```python
def test_backdrop_click_closes_live_dialog(self):
    a = self._dialog()
    present_modal_dialog(a, self.parent)
    wait_for_dialog_open(a)
    self._spin()  # idle install
    _click(_backdrop(a))
    self.wait_for(lambda: self.closed == [a])

def test_stacked_backdrop_closes_only_the_top_dialog(self):
    a, b = self._dialog(), self._dialog()
    present_modal_dialog(a, self.parent)
    wait_for_dialog_open(a)
    present_modal_dialog(b, self.parent)
    wait_for_dialog_open(b)
    self._spin()
    self.assertIs(fetch(_backdrop(b), "_uvr_backdrop_dialog", None), b)
    _click(_backdrop(b))
    self.wait_for(lambda: self.closed == [b])
    self.assertTrue(a.get_mapped())

def test_commit_dialog_ignores_backdrop(self):
    a = self._dialog()
    present_modal_dialog(a, self.parent, dismiss_on_backdrop=False)
    wait_for_dialog_open(a)
    self._spin()
    self.assertIsNone(fetch(_backdrop(a), "_uvr_backdrop_dialog", None))
```

Call-site tests patch each module's own `present_modal_dialog` name:
- `test_commit_dialogs_disable_backdrop`: `DualBatchDialog.present()`, `show_blend_dialog(...)`, `run_blocking_dialog(...)` (also patch `GLib.MainLoop` with a `Mock` so `run()` returns) and `RunController._present_plan_confirmation` (set up as in `tests/test_plan_review.py:153`). Each must be called once with `dismiss_on_backdrop=False`.
- `test_live_dialogs_use_shared_helper`: `ModelPicker.present`, `open_about`, `present_shortcuts` and `MainWindow._on_open_settings`. Each calls the patched helper once without `dismiss_on_backdrop=False`.

- [ ] **Step 2: Run them to see them fail**

Run: `$T -- … -m unittest tests.test_dialog_presentation`
Expected: FAIL. The stacked test fails on the `_uvr_backdrop_dialog` assertion, and the call-site tests fail on unexpected keywords or missing calls.

- [ ] **Step 3: Implement**

In `ui/dialogs/utils.py`:
- `_try_install_backdrop_dismiss(dialog)` searches only `dialog`'s subtree. libadwaita puts each dialog's dimming widget inside that dialog's own tree, as verified in the spec.
- `_install_backdrop_dismiss(dimming, dialog)` stashes `_uvr_backdrop_dialog`, adds the gesture once, and closes `fetch(dimming, "_uvr_backdrop_dialog")` on release.
- `present_modal_dialog` schedules the install only when `dismiss_on_backdrop` is true. Update its docstring.
- `run_blocking_dialog` passes `dismiss_on_backdrop=False`.

At the call sites:
- Replace the direct `.present(parent)` calls listed under Files with the helper.
- `ModelPicker.present(parent)` keeps its signature.
- `open_about` and `present_shortcuts` use the helper only on the `Adw.AboutDialog` / `Adw.ShortcutsDialog` branch; the window fallbacks are unchanged.
- In `show_blend_dialog`, narrow `parent` to `Gtk.Window | None` with `ui.gtk_narrow.root_window` if its type does not fit.

- [ ] **Step 4: Run tests to verify they pass**

Run: `$T -- … -m unittest tests.test_dialog_presentation tests.test_plan_review tests.test_ensemble_blend_dialog tests.test_model_picker_ui tests.test_output_stems`
Expected: OK.

- [ ] **Step 5: Commit**

```bash
git add ui/dialogs/utils.py ui/model_picker.py ui/window.py ui/about.py ui/shortcuts.py ui/audio_tools/dual_batch.py ui/ensemble/blend_dialog.py ui/run_control.py tests/test_dialog_presentation.py
git commit -m "fix(ui): backdrop clicks close live dialogs only, including stacked ones"
```

---

### Task 3: Commit-dialog actions

**Files:**
- Modify: `resources/ui/form-dialog-content.blp`, `resources/ui/dual-batch-dialog.blp`, `resources/ui/ensemble-blend.blp`
- Modify: `ui/dialogs/utils.py` (`set_form_dialog_content`), `ui/audio_tools/dual_batch.py`, `ui/ensemble/blend_dialog.py`
- Test: `tests/test_dialog_actions.py` (new)

**Interfaces:**
- Consumes: `present_modal_dialog(..., dismiss_on_backdrop=False)` from Task 2.
- Produces: the Blueprint object id `cancel_button` in all three headers. `set_form_dialog_content` keeps its signature and return value (the Save button).

- [ ] **Step 1: Write the failing tests**

Helper: `_header(dialog) -> Adw.HeaderBar` returns the first `Adw.HeaderBar` descendant. `_button(dialog, label) -> Gtk.Button` finds the descendant button with that label.

For each commit dialog, built as in the existing tests (`set_form_dialog_content` on a bare `Adw.Dialog`, `DualBatchDialog`, `show_blend_dialog`):

```python
def test_commit_header_has_cancel_start_action_end_and_no_close(self):
    header = _header(dialog)
    self.assertFalse(header.get_show_start_title_buttons())
    self.assertFalse(header.get_show_end_title_buttons())
    cancel, action = _button(dialog, "Cancel"), _button(dialog, action_label)
    ok, point = cancel.compute_point(action, Graphene.Point())
    self.assertTrue(ok)
    self.assertLess(point.x, 0)  # Cancel sits left of the action
    self.assertTrue(action.has_css_class("suggested-action"))

def test_cancel_discards_blend_edits(self):
    # change a weight, click Cancel: on_apply never called, dialog closed

def test_escape_discards_blend_edits(self):
    # change a weight, dialog.close() (what Escape does): on_apply never called
```

`action_label` is "Save" for the form and Input Pairs, and "Apply" for Blend Options. Present over a 900×700 window and wait before measuring positions.

- [ ] **Step 2: Run them to see them fail**

Run: `$T -- … -m unittest tests.test_dialog_actions`
Expected: FAIL. No "Cancel" button is found, and the end title buttons are shown.

- [ ] **Step 3: Implement**

In each of the three Blueprint headers:
- set `show-start-title-buttons: false;` and `show-end-title-buttons: false;`
- add `[start] Gtk.Button cancel_button { label: "Cancel"; }`
- keep the existing suggested action at `[end]`

In Python, connect `cancel_button` `clicked` to `dialog.close()`. `run_blocking_dialog` already returns `None` when the dialog closes without saving.

Rebuild the resources.

- [ ] **Step 4: Run tests to verify they pass**

Run: `./resources/compile_resources.sh && $T -- … -m unittest tests.test_dialog_actions tests.test_ensemble_blend_dialog tests.test_control_types`
Expected: OK.

- [ ] **Step 5: Commit**

```bash
git add resources/ui/form-dialog-content.blp resources/ui/dual-batch-dialog.blp resources/ui/ensemble-blend.blp ui/data/uvr.gresource ui/dialogs/utils.py ui/audio_tools/dual_batch.py ui/ensemble/blend_dialog.py tests/test_dialog_actions.py
git commit -m "feat(ui): commit dialogs get Cancel and drop the close button"
```

---

### Task 4: Wording

**Files:**
- Modify Blueprints:
  - `compare-stems-dialog.blp`: the dialog title and the `window_title` WindowTitle become "Compare Stems"
  - `dual-batch-dialog.blp`: "Input Pairs"
  - `ensemble-blend.blp`: "Blend Options"
  - `manual-downloads.blp`: "Manual Downloads"
  - `model_options_sheet.blp`: "Model Options"
  - `output-stems.blp`: the dialog title (line 21) becomes "Save Stems"; the row title stays as is
  - `plan-review.blp`: "Review Processing Plan"
  - `stem_only.blp`: the `custom_dialog` title becomes "Custom Stems"; the row title stays as is
  - `update-view.blp`: "Check Again"
  - `preferences.blp`: the `save_profile_dialog` heading becomes "Save Current Settings"
- Modify Python:
  - `ui/updates.py`: "Check Again" and "View Release Notes", including the comparison in `_on_check_or_update`
  - `ui/oom_dialog.py`: "GPU Out of Memory", "GPU Out of Memory (Debug Mock)", "Export Completed", "Retry with Smaller Segment"
  - `ui/run_control.py`: "Stop Processing and Downloads?", "Cancel Model Downloads and Quit?", "Processing Has Not Stopped", `f"{label} Failed"`; leave the console and log strings alone
  - `ui/preferences.py`: `'Replace Profile "{name}"?'`, `'Load Profile "{name}"?'`, "Remove Profile?", "Reset All Settings?"
  - `ui/ensemble/window.py`: "Download Missing Models?", "Not Now", "Download Missing", "Delete Ensemble?"
  - `ui/dialogs/model_params.py`: "Delete Stored Parameters?"
  - `bundled/constants/messages.py`: the `STOP_PROCESS_CONFIRM` heading becomes "Stop Processing?"; the body is unchanged
- Modify: `tests/test_update_view.py:54,63` to the new labels
- Test: `tests/test_dialog_wording.py` (new, no display needed)

**Interfaces:**
- Produces: `title_case_violations(text: str, *, first_is_start: bool = True) -> list[str]` in the test module. It strips `_` mnemonics, splits words with `[A-Za-z][A-Za-z'’]*`, and returns the words that break the rule. Small words are the list in Global Constraints.

- [ ] **Step 1: Write the failing tests**

```python
def test_rule(self):
    self.assertEqual(title_case_violations("Retry with Smaller Segment"), [])
    self.assertEqual(title_case_violations("GPU Out of Memory (Debug Mock)"), [])
    self.assertEqual(title_case_violations("Input pairs"), ["pairs"])
    self.assertEqual(title_case_violations("Stop And Quit"), ["And"])
    self.assertEqual(title_case_violations(" Failed", first_is_start=False), [])

def test_dialog_blueprint_strings_are_title_case(self):
    # For each resources/ui/*.blp containing Adw.Dialog, Adw.AlertDialog or Adw.Window:
    # the title:/heading: of those objects, every Adw.WindowTitle title,
    # and the label: of every Gtk.Button / Gtk.MenuButton (not tooltips or accessibility labels).
    # Collect "file: text -> violations" and assertEqual(found, []).

def test_python_dialog_strings_are_title_case(self):
    # ast-walk ui/**/*.py: the second argument of add_response(...);
    # the heading= keyword of AlertDialog(...) and present_error_dialog(...);
    # the right-hand side of `heading = ...`; the title= keyword of PickerConfig(...).
    # For an f-string, check only its constant parts; first_is_start is True only for a leading constant.
    # Also check STOP_PROCESS_CONFIRM[0], QUIT_WHILE_PROCESSING_CONFIRM[0],
    # APOLLO_MODEL_PARAMETERS_TEXT and CHANGE_MODEL_DEFAULTS_TEXT.
```

- [ ] **Step 2: Run them to see them fail**

Run: `.venv/bin/python -m unittest tests.test_dialog_wording > /tmp/uvr-test.log 2>&1; tail -40 /tmp/uvr-test.log`
Expected: FAIL. The output lists exactly the strings under Files, which matches a probe run on 2026-10-04.

- [ ] **Step 3: Make the string edits listed under Files**

Rebuild the resources.

- [ ] **Step 4: Run tests to verify they pass**

Run: `./resources/compile_resources.sh && $T -- … -m unittest tests.test_dialog_wording tests.test_update_view tests.test_run_control tests.test_plan_review > /tmp/uvr-test.log 2>&1; tail -5 /tmp/uvr-test.log`
Expected: OK. If another test pins an old string, update it to the new text; do not weaken the new test.

- [ ] **Step 5: Commit**

```bash
git add resources/ui/*.blp ui/data/uvr.gresource ui/updates.py ui/oom_dialog.py ui/run_control.py ui/preferences.py ui/ensemble/window.py ui/dialogs/model_params.py bundled/constants/messages.py tests/test_update_view.py tests/test_dialog_wording.py
git commit -m "fix(ui): title-case dialog titles, buttons and alert headings"
```

(Stage only the `.blp` files this task changed. Check with `git status --short` first.)

---

### Task 5: Sizing

**Files:**
- Modify Blueprints (content width / minimum / opening height):
  - `change-model-defaults.blp`: 440
  - `model-params-{apollo,mdx,mdxc,vr}.blp`: 440
  - `update-view.blp`: 440; drop `width-request: 425`
  - `stem_only.blp` `custom_dialog`: 440; drop `content-height: 480`
  - `output-stems.blp`: 600, opening height 560
  - `verify-inputs.blp`: 600, 560
  - `dual-batch-dialog.blp`: 600, 560
  - `ensemble-blend.blp`: 600, 560
  - `plan-review.blp`: 600, 560; keeps `height-request: 400`
  - `compare-stems-dialog.blp`: 600, 560
  - `error-dialog.blp`: 600
  - `manual-downloads.blp`: 600, 560
  - `model_options_sheet.blp`: 800
  - `model-picker.blp`: unchanged at 800×640, minimum 360×480
- Modify: `ui/dialogs/utils.py`: add the cap; remove `configure_dialog_width`, whose only caller is `ui/download.py:446`, and drop that call
- Modify: `ui/errorlog.py`: `_error_dialog_width` uses the shared cap; remove `_ERROR_DIALOG_MARGIN`
- Modify: `ui/model_options/sheet.py`: `_SHEET_WIDTH = 800`; `tests/test_model_options_sheet_layout.py:17` expects 800
- Test: `tests/test_dialog_sizing.py` (new)

**Interfaces:**
- Consumes: `present_modal_dialog` from Task 2.
- Produces, in `ui/dialogs/utils.py`:
  - `DIALOG_MIN_WIDTH = 360`
  - `DIALOG_WINDOW_MARGIN = 64`
  - `capped_dialog_width(width: int, parent: WindowSizing | None) -> int`, which returns `width` when `parent` is None. It uses `parent_window_width(parent, fallback=width)`.
  - the widget-state key `_uvr_design_width` on a dialog

Rules for every Blueprint with an `Adw.Dialog`:
- set `content-width` to its tier;
- set `width-request: 360;` and `height-request: 294;`, or the larger existing minimum (picker 480, plan 400);
- remove `follows-content-size: true`. With it set, libadwaita ignores `content-width` and sizes to the natural width.

For forms and short info dialogs, leave `content-height` unset so they follow their content. In Save Stems and Verify Inputs, replace the list scroller's `max-content-height` with `vexpand: true` so the list fills the opening height.

- [ ] **Step 1: Write the failing tests**

```python
TIERS = {"change-model-defaults": 440, "model-params-apollo": 440, "model-params-mdx": 440,
         "model-params-mdxc": 440, "model-params-vr": 440, "update-view": 440, "stem_only": 440,
         "output-stems": 600, "verify-inputs": 600, "dual-batch-dialog": 600, "ensemble-blend": 600,
         "plan-review": 600, "compare-stems-dialog": 600, "error-dialog": 600, "manual-downloads": 600,
         "model-picker": 800, "model_options_sheet": 800}
OPENING = {"model-picker": 640, **dict.fromkeys(("output-stems", "verify-inputs", "dual-batch-dialog",
           "ensemble-blend", "plan-review", "compare-stems-dialog", "manual-downloads"), 560)}
MIN_HEIGHT = {"model-picker": 480, "plan-review": 400}

def test_every_dialog_blueprint_has_a_tier(self):
    # the set of .blp stems containing an Adw.Dialog object == set(TIERS)
def test_content_widths_match_tiers(self): ...
def test_minimum_sizes(self):  # width-request >= 360, height-request == MIN_HEIGHT.get(stem, 294)
def test_opening_heights(self):  # content-height == OPENING[stem]; unset for the others
def test_no_dialog_follows_content_size(self): ...
```

Parse the property block of each `Adw.Dialog` object, up to its `child:`, with a small regex helper. In `stem_only.blp` the dialog is `custom_dialog`, not the first object.

GTK cases, over an `Adw.Window`:

```python
def test_cap_shrinks_dialog_on_narrow_parent(self):
    resize_window(self.parent, 480, 600)
    dialog = Adw.Dialog(content_width=600)
    present_modal_dialog(dialog, self.parent)
    self.assertEqual(dialog.get_content_width(), 416)

def test_cap_restores_design_width_on_wider_parent(self):
    # same dialog closed, parent resized to 1000, presented again -> 600

def test_libadwaita_sized_dialogs_are_not_capped(self):
    # Adw.PreferencesDialog presented over a 480 window keeps its content width
```

- [ ] **Step 2: Run them to see them fail**

Run: `$T -- … -m unittest tests.test_dialog_sizing`
Expected: FAIL on the widths of output-stems, verify-inputs and the others, on `follows-content-size`, and on the cap.

- [ ] **Step 3: Implement**

`present_modal_dialog` caps before presenting, unless the dialog is an `Adw.PreferencesDialog`, `Adw.AboutDialog` or `Adw.ShortcutsDialog` (use `getattr`, since `ShortcutsDialog` may be missing). It works in three steps:
1. Read `_uvr_design_width`. If it is not stashed yet, stash `get_content_width()`, but only when that is greater than 0.
2. Set `set_content_width(capped_dialog_width(design, parent))`.
3. Do nothing when no design width is known.

Other changes:
- `_error_dialog_width(parent)` returns `capped_dialog_width(_ERROR_DIALOG_WIDTH, parent)`. The existing `tests/test_errorlog.py` cases (600 wide, 416 narrow) must still pass.
- Make the Blueprint edits listed under Files, then rebuild the resources.

- [ ] **Step 4: Run tests to verify they pass**

Run: `./resources/compile_resources.sh && $T -- … -m unittest tests.test_dialog_sizing tests.test_errorlog tests.test_model_options_sheet_layout tests.test_output_stems tests.test_plan_review tests.test_compare_dialog tests.test_model_picker_ui > /tmp/uvr-test.log 2>&1; tail -5 /tmp/uvr-test.log`
Expected: OK.

- [ ] **Step 5: Commit**

```bash
git add <the .blp files above> ui/data/uvr.gresource ui/dialogs/utils.py ui/errorlog.py ui/download.py ui/model_options/sheet.py tests/test_dialog_sizing.py tests/test_model_options_sheet_layout.py
git commit -m "feat(ui): dialogs use three standard widths, a minimum size and a window cap"
```

---

### Task 6: "After" screenshots, review, and full checks

**Files:**
- Output: `.superpowers/dialog-screenshots/after/*.png`
- Modify: any file needing a visual fix found in this review (each fix gets its own commit, with a test where one fits)

- [ ] **Step 1: Capture**

Run Task 1 Step 2 with `--out after`, adjusting only the run-failure heading text to the new case.
Expected: the same file names as `before/`, and the same `SKIPPED` lines.

- [ ] **Step 2: Review every pair side by side**

Read each `before/X` and `after/X` with the Read tool and check:
- the title case;
- commit dialogs show Cancel at the left, the action at the right and no ✕;
- the widths follow the tiers;
- nothing is clipped, squeezed or overflowing at 640×560;
- the dark variants are legible.

Write a short table in the hand-off message with the dialog, what changed and whether it looks right.

- [ ] **Step 3: Fix and re-capture anything off**

- [ ] **Step 4: Full verification**

Run:
```bash
./resources/compile_resources.sh --check
$T -- env UVR_DISABLE_POLITREES=1 UVR_DISABLE_MVSEPLESS=1 .venv/bin/python -m unittest discover -s tests -t . > /tmp/uvr-full.log 2>&1; tail -5 /tmp/uvr-full.log
.venv/bin/python -m basedpyright > /tmp/uvr-pyright.log 2>&1; tail -3 /tmp/uvr-pyright.log
.venv/bin/ruff check <touched files> && .venv/bin/ruff format --check <touched files>
```
Expected:
- the resource check is clean;
- the suite reports `OK` (the earlier baseline was 4402 tests with 3 skipped, plus the new tests);
- basedpyright reports `0 errors`;
- ruff is clean.
