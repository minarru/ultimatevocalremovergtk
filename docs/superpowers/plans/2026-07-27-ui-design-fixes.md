# UI/Design Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the 13 UI/UX defects found in the GTK4 layer — collapsing input list, undismissable "Done" bar, dead-end data-folder banner, ungated dependent controls, four-surface setting duplication, over-eager Preferences resync, and a batch of a11y/CSS polish items.

**Architecture:** All changes live in `ui/` (plus `resources/style.css`). Two new focused modules are added: `ui/widgets/format_row.py` (the combined Output-format widget) and a set of pure helper functions placed next to the widgets they serve so the logic is unit-testable without a display. Where behaviour genuinely needs a live widget, tests use the repo's existing display-guarded pattern.

**Tech Stack:** Python 3.13+, PyGObject (GTK 4 / libadwaita 1), stdlib `unittest`.

## Global Constraints

- **No tkinter anywhere**, and no new imports from `ui/` into `core/`. `core` stays framework-agnostic.
- **Settings are one flat dict.** Never invent new setting keys in this plan — every key used here (`save_format`, `wav_type_set`, `mp3_bit_set`, `flac_bit_set`, `is_gpu_conversion`, `is_autocast`, `device_set`) already exists in `DEFAULT_DATA`.
- **GTK only on the main loop.** No change here touches worker threads; do not add `GLib.idle_add` where it isn't already used.
- Tests are **stdlib unittest**. Run with `.venv/bin/python -m unittest discover -s tests -v`. There is no pytest config — never write `pytest` invocations.
- Tests that construct real GTK widgets MUST use this exact guard (copied from `tests/test_scale_default_marks.py`):
  ```python
  @unittest.skipUnless(
      os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"),
      "GTK widget construction needs a display",
  )
  class SomeTests(unittest.TestCase):
      @classmethod
      def setUpClass(cls) -> None:
          import gi

          gi.require_version("Gtk", "4.0")
          gi.require_version("Adw", "1")
          from gi.repository import Adw

          cls._app = Adw.Application(application_id="org.uvr.test.<unique-id>")
          cls._app.register()
  ```
  Every such class needs a **unique** `application_id`.
- Search with `rg`, never `grep`/`git grep`.
- Type checking is pyright `basic` over `ui/ core/ engines/ tests/ bundled/`. Run `.venv/bin/python -m pyright` if available; do not chase errors in `ml/`, `models/`, `vendor/`.
- Push to `origin` (Codeberg) only. Never push to the `github` remote.
- Upstream's `Seperate*` misspelling and the verbatim strings in `bundled/error_handling.py` are intentional — do not "fix" them.
- Commit after every task. Branch off `main` first; do not commit directly to `main`.

## File Structure

**Created:**
- `ui/widgets/format_row.py` — `OutputFormatRow` (an `Adw.ActionRow` holding two side-by-side `Gtk.DropDown`s) plus the pure `quality_spec()` lookup. One responsibility: presenting and persisting `save_format` + its per-format quality key.
- `tests/test_file_chooser_expansion.py`, `tests/test_log_panel_done_collapse.py`, `tests/test_data_dir_banner.py`, `tests/test_format_row.py`, `tests/test_gpu_dependent_rows.py`, `tests/test_switch_dependents.py`

**Modified:**
- `ui/widgets/file_chooser.py` — expander-state fix, output-row error styling
- `ui/widgets/log_panel.py` — "Done" auto-collapse
- `ui/window.py` — data banner, autocast gating, format row adoption, light prefs sync, window-level drop target, `_toast` dedupe
- `ui/views/base.py` — activate-switch dependent gating
- `ui/preferences.py` — remove Audio page + GPU/autocast duplicates, gate device row, split reload callbacks
- `ui/ensemble/window.py`, `ui/audio_tools/window.py` — autocast gating, format row adoption, column-balance removal
- `ui/shared_settings.py` — format-row protocol change, GPU-dependency helper
- `ui/model_options/sheet.py` — drop the redundant non-applicable toast
- `ui/widgets/download_queue_indicator.py` — accessible label
- `resources/style.css` — colour-syntax corrections
- `tests/test_shared_settings.py` — update the format-row fake

---

### Task 1: Input list stops collapsing on every removal

Removing one file from an expanded multi-file selection currently snaps the whole expander shut, because `_refresh()` unconditionally calls `set_expanded(False)`.

**Files:**
- Modify: `ui/widgets/file_chooser.py:129-165`
- Test: `tests/test_file_chooser_expansion.py` (create)

**Interfaces:**
- Produces: `ui.widgets.file_chooser.expander_state(path_count: int, *, was_expanded: bool, preserve: bool) -> tuple[bool, bool]` returning `(enable_expansion, expanded)`.
- Produces: `InputFilesRow.set_paths(paths, notify=True, *, preserve_expansion=False)`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_file_chooser_expansion.py`:

```python
"""Expander state for the input-files row."""

from __future__ import annotations

import unittest

from ui.widgets.file_chooser import expander_state


class ExpanderStateTests(unittest.TestCase):
    def test_single_file_never_expands(self):
        self.assertEqual(
            expander_state(1, was_expanded=True, preserve=True), (False, False)
        )

    def test_empty_selection_never_expands(self):
        self.assertEqual(
            expander_state(0, was_expanded=True, preserve=True), (False, False)
        )

    def test_new_multi_selection_starts_collapsed(self):
        self.assertEqual(
            expander_state(4, was_expanded=True, preserve=False), (True, False)
        )

    def test_removal_preserves_open_expander(self):
        self.assertEqual(
            expander_state(4, was_expanded=True, preserve=True), (True, True)
        )

    def test_removal_preserves_closed_expander(self):
        self.assertEqual(
            expander_state(4, was_expanded=False, preserve=True), (True, False)
        )

    def test_dropping_to_one_file_forces_collapse(self):
        self.assertEqual(
            expander_state(1, was_expanded=True, preserve=True), (False, False)
        )


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m unittest tests.test_file_chooser_expansion -v`
Expected: FAIL with `ImportError: cannot import name 'expander_state'`

- [ ] **Step 3: Add the pure helper**

In `ui/widgets/file_chooser.py`, directly after the `merge_input_paths` function:

```python
def expander_state(
    path_count: int, *, was_expanded: bool, preserve: bool
) -> tuple[bool, bool]:
    """Return ``(enable_expansion, expanded)`` for a ``path_count``-file selection.

    One file is fully summarized by the header, so expansion is disabled below
    two files. ``preserve`` keeps an already-open list open — set when the list
    is being edited in place (removing a file) rather than replaced wholesale.
    """
    if path_count <= 1:
        return False, False
    return True, (was_expanded if preserve else False)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m unittest tests.test_file_chooser_expansion -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Wire the helper into the row**

In `ui/widgets/file_chooser.py`, replace `set_paths` (currently lines 129-142) and `_refresh` (lines 157-165) with:

```python
    def set_paths(
        self,
        paths: Sequence[str],
        notify: bool = True,
        *,
        preserve_expansion: bool = False,
    ) -> None:
        cleaned, result = sanitize_input_paths(paths)
        self.paths = cleaned
        self._refresh(preserve_expansion=preserve_expansion)
        if notify:
            from core.debug_log import debug

            debug("ui", f"inputs count={len(self.paths)}")
            for message in format_input_sanitize_toasts(
                result,
                include_missing=result.removed_missing > 0,
            ):
                self._emit_toast(message)
            self._on_changed()
```

```python
    def _refresh(self, *, preserve_expansion: bool = False) -> None:
        was_expanded = self.get_expanded()
        self._refresh_subtitle()
        self._rebuild_file_rows()
        self._clear_button.set_sensitive(bool(self.paths))
        enable, expanded = expander_state(
            len(self.paths), was_expanded=was_expanded, preserve=preserve_expansion
        )
        self.set_enable_expansion(enable)
        self.set_expanded(expanded)
```

- [ ] **Step 6: Preserve expansion on per-file removal**

In the same file, change `_on_remove_clicked` (line 204):

```python
    def _on_remove_clicked(self, _button: Gtk.Button, path: str) -> None:
        self.set_paths(
            [p for p in self.paths if p != path], preserve_expansion=True
        )
```

Leave `_on_clear_clicked`, `_on_open_finished` and `_on_drop` untouched — those replace or extend the selection, where collapsing to the header summary is correct.

- [ ] **Step 7: Run the full suite**

Run: `.venv/bin/python -m unittest discover -s tests -v`
Expected: PASS, no new failures.

- [ ] **Step 8: Commit**

```bash
git add ui/widgets/file_chooser.py tests/test_file_chooser_expansion.py
git commit -m "fix(ui): keep the input list open while removing files"
```

---

### Task 2: Auto-collapse the finished progress bar

After a run, `_on_complete` leaves the bar at 100% / "Done" forever; the only escape is clearing the log. Collapse it ~5s after completion instead.

**Files:**
- Modify: `ui/widgets/log_panel.py:40-64,244-266`
- Modify: `ui/run_control.py:477-491`
- Test: `tests/test_log_panel_done_collapse.py` (create)

**Interfaces:**
- Consumes: existing `LogPanel.clear_progress()`, `LogPanel.prepare_for_run()`.
- Produces: `LogPanel.mark_run_complete() -> None`, `LogPanel.DONE_COLLAPSE_MS = 5000`, `LogPanel._cancel_done_collapse() -> None`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_log_panel_done_collapse.py`:

```python
"""The finished progress bar collapses on a timer, not only on Clear log."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from ui.widgets.log_panel import LogPanel


def _panel() -> LogPanel:
    """A LogPanel with just the attributes the collapse path touches.

    ``_sync_progress_section_visible`` reads back the fraction and the label's
    visibility, so those two mocks have to actually round-trip their setters —
    otherwise a bare MagicMock reads as truthy and the revealer never closes.
    """
    panel = LogPanel.__new__(LogPanel)
    panel._done_collapse_id = None
    panel._pulse_source_id = None
    panel._progress_status = ""

    panel._progressbar = MagicMock()
    panel._progressbar.get_fraction.return_value = 1.0
    panel._progressbar.set_fraction.side_effect = lambda value: setattr(
        panel._progressbar.get_fraction, "return_value", value
    )

    panel._progress_label = MagicMock()
    panel._progress_label.get_visible.return_value = True
    panel._progress_label.set_visible.side_effect = lambda value: setattr(
        panel._progress_label.get_visible, "return_value", value
    )

    panel._progress_revealer = MagicMock()
    panel.console = MagicMock()
    panel._log_stack = MagicMock()
    panel._log_revealer = MagicMock()
    return panel


class DoneCollapseTests(unittest.TestCase):
    def test_mark_run_complete_schedules_a_timeout(self):
        panel = _panel()
        with patch(
            "ui.widgets.log_panel.GLib.timeout_add", return_value=77
        ) as timeout_add:
            panel.mark_run_complete()
        timeout_add.assert_called_once()
        self.assertEqual(timeout_add.call_args[0][0], LogPanel.DONE_COLLAPSE_MS)
        self.assertEqual(panel._done_collapse_id, 77)

    def test_second_completion_replaces_the_pending_timeout(self):
        panel = _panel()
        with patch("ui.widgets.log_panel.GLib.timeout_add", return_value=77):
            panel.mark_run_complete()
        with patch(
            "ui.widgets.log_panel.GLib.timeout_add", return_value=88
        ), patch("ui.widgets.log_panel.GLib.source_remove") as source_remove:
            panel.mark_run_complete()
        source_remove.assert_called_once_with(77)
        self.assertEqual(panel._done_collapse_id, 88)

    def test_firing_the_timeout_clears_progress(self):
        panel = _panel()
        panel._done_collapse_id = 77
        panel._on_done_collapse()
        self.assertIsNone(panel._done_collapse_id)
        panel._progressbar.set_fraction.assert_called_with(0.0)
        panel._progress_revealer.set_reveal_child.assert_called_with(False)

    def test_starting_a_new_run_cancels_the_pending_collapse(self):
        panel = _panel()
        panel._done_collapse_id = 77
        with patch("ui.widgets.log_panel.GLib.source_remove") as source_remove:
            panel.prepare_for_run()
        source_remove.assert_called_once_with(77)
        self.assertIsNone(panel._done_collapse_id)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m unittest tests.test_log_panel_done_collapse -v`
Expected: FAIL with `AttributeError: 'LogPanel' object has no attribute 'mark_run_complete'`

- [ ] **Step 3: Implement the collapse timer**

In `ui/widgets/log_panel.py`, add the constant next to `_PROGRESS_DONE_LABEL` (line 40):

```python
#: Delay before a finished run's 100% / "Done" bar collapses on its own.
_DONE_COLLAPSE_MS = 5000
```

Add the public alias as the first line of the `LogPanel` class body, before `__init__` (line 44):

```python
class LogPanel(Gtk.Box):
    #: Public alias so callers don't reach for the module-private constant.
    DONE_COLLAPSE_MS = _DONE_COLLAPSE_MS

    def __init__(
```

In `LogPanel.__init__`, alongside `self._pulse_source_id` (line 62), add:

```python
        self._done_collapse_id: Optional[int] = None
```

Add these methods immediately after `clear_progress` (after line 251):

```python
    def mark_run_complete(self) -> None:
        """Collapse the finished progress block after a short grace period.

        The completion toast and the log both persist the result, so the 100% /
        "Done" bar only needs to be visible long enough to be read. Collapsing
        it also returns ``_PROGRESS_SECTION_RESERVE`` px of scroll clearance to
        the option columns (see :meth:`options_overlay_clearance`).
        """
        self._cancel_done_collapse()
        self._done_collapse_id = GLib.timeout_add(
            _DONE_COLLAPSE_MS, self._on_done_collapse
        )

    def _on_done_collapse(self) -> bool:
        self._done_collapse_id = None
        self.clear_progress()
        return GLib.SOURCE_REMOVE

    def _cancel_done_collapse(self) -> None:
        if self._done_collapse_id is not None:
            GLib.source_remove(self._done_collapse_id)
            self._done_collapse_id = None
```

- [ ] **Step 4: Cancel the timer when a new run starts**

In the same file, add the cancel as the first line of `prepare_for_run` (line 266):

```python
    def prepare_for_run(self) -> None:
        """Show the console and reset scroll before worker output arrives."""
        self._cancel_done_collapse()
        revealed = self._log_revealer.get_child_revealed()
```

- [ ] **Step 5: Run test to verify it passes**

Run: `.venv/bin/python -m unittest tests.test_log_panel_done_collapse -v`
Expected: PASS (4 tests)

- [ ] **Step 6: Trigger it from run completion**

In `ui/run_control.py`, inside `_on_complete`, immediately after the `set_progress_text(_PROGRESS_DONE)` call (line 485):

```python
        self._window.log_panel.set_progress_fraction(1.0)
        self._window.log_panel.set_progress_text(_PROGRESS_DONE)
        self._window.log_panel.mark_run_complete()
```

Leave `_on_stopped` and `_on_error` alone: stop already calls `clear_progress()` via `_finish_run_ui`, and a failed run's "Failed" label should stay until the next run.

- [ ] **Step 7: Run the clearance + run-control tests**

Run: `.venv/bin/python -m unittest tests.test_log_panel_clearance tests.test_run_control tests.test_core_run_control -v`
Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add ui/widgets/log_panel.py ui/run_control.py tests/test_log_panel_done_collapse.py
git commit -m "fix(ui): auto-collapse the progress bar after a finished run"
```

---

### Task 3: Make the data-folder banner actionable

The banner tells the user to "Choose a writable location" but offers no button and no path, and it is evaluated once in `__init__` and never re-checked.

**Files:**
- Modify: `ui/window.py:227-240,443-471,840-845,894-908`
- Test: `tests/test_data_dir_banner.py` (create)

**Interfaces:**
- Produces: `ui.window.data_dir_banner_state(data_dir: str) -> tuple[bool, str]` returning `(revealed, title)`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_data_dir_banner.py`:

```python
"""Banner shown when the application data folder is not writable."""

from __future__ import annotations

import os
import stat
import tempfile
import unittest

from ui.window import data_dir_banner_state


class DataDirBannerStateTests(unittest.TestCase):
    def test_writable_folder_hides_the_banner(self):
        with tempfile.TemporaryDirectory() as tmp:
            revealed, _title = data_dir_banner_state(tmp)
            self.assertFalse(revealed)

    def test_read_only_folder_reveals_the_banner(self):
        with tempfile.TemporaryDirectory() as tmp:
            os.chmod(tmp, stat.S_IRUSR | stat.S_IXUSR)
            try:
                revealed, _title = data_dir_banner_state(tmp)
            finally:
                os.chmod(tmp, stat.S_IRWXU)
            self.assertTrue(revealed)

    def test_title_names_the_offending_folder(self):
        with tempfile.TemporaryDirectory() as tmp:
            os.chmod(tmp, stat.S_IRUSR | stat.S_IXUSR)
            try:
                _revealed, title = data_dir_banner_state(tmp)
            finally:
                os.chmod(tmp, stat.S_IRWXU)
            self.assertIn(tmp, title)

    def test_title_does_not_promise_a_chooser(self):
        # There is no in-app data-folder picker, so the copy must not tell the
        # user to "choose a writable location".
        with tempfile.TemporaryDirectory() as tmp:
            os.chmod(tmp, stat.S_IRUSR | stat.S_IXUSR)
            try:
                _revealed, title = data_dir_banner_state(tmp)
            finally:
                os.chmod(tmp, stat.S_IRWXU)
            self.assertNotIn("Choose", title)


if __name__ == "__main__":
    unittest.main()
```

Note: if the suite is ever run as root, `os.access(..., os.W_OK)` returns `True` regardless of mode and two of these tests fail. That is acceptable — CI does not run as root.

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m unittest tests.test_data_dir_banner -v`
Expected: FAIL with `ImportError: cannot import name 'data_dir_banner_state'`

- [ ] **Step 3: Add the pure helper**

In `ui/window.py`, add after the `_METHOD_SETTING_ALIASES` block (after line 104):

```python
#: Banner copy for a non-writable data folder. There is no in-app picker for
#: the data directory (it is resolved by ``core.paths`` from ``$UVR_DATA_DIR``,
#: the repo root, or the OS user-data dir), so the copy asks the user to fix
#: permissions rather than to choose a location.
_DATA_DIR_BANNER_TITLE = (
    "Can't write to the application data folder ({path}) — "
    "settings and downloads will fail. Fix its permissions to continue."
)


def data_dir_banner_state(data_dir: str) -> tuple[bool, str]:
    """Return ``(revealed, title)`` for the non-writable data-folder banner."""
    revealed = not os.access(data_dir, os.W_OK)
    return revealed, _DATA_DIR_BANNER_TITLE.format(path=data_dir)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m unittest tests.test_data_dir_banner -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Give the banner a button**

In `ui/window.py`, replace the `_data_banner` construction (lines 227-233) with:

```python
        self._data_banner = Adw.Banner(button_label="Show Folder", revealed=False)
        self._data_banner.connect("button-clicked", self._on_data_banner_clicked)
```

The title is now set by `_reveal_data_dir_banner_if_needed`, which already runs at line 240 immediately after the toast overlay is installed.

- [ ] **Step 6: Use the helper and add the button handler**

Replace `_reveal_data_dir_banner_if_needed` (lines 464-471) with:

```python
    def _reveal_data_dir_banner_if_needed(self) -> None:
        """Surface a non-writable data dir as a banner (not only a debug log line)."""
        banner = getattr(self, "_data_banner", None)
        if banner is None:
            return
        from core import paths

        revealed, title = data_dir_banner_state(paths.DATA_DIR)
        banner.set_title(title)
        banner.set_revealed(revealed)

    def _on_data_banner_clicked(self, _banner: Adw.Banner) -> None:
        from core import paths

        open_folder_in_file_manager(self, paths.DATA_DIR, on_error=self.toast)
```

Add the import at the top of `ui/window.py`, next to the other `.` imports (after line 63):

```python
from .files import open_folder_in_file_manager
```

- [ ] **Step 7: Re-check the banner on map and after save failures**

In `_on_window_mapped` (line 443), add the re-check inside the existing `refresh` closure, after `self._sync_options_bottom_clearance()`:

```python
        def refresh() -> None:
            if self._current_view is not None:
                self._populate_columns()
                self._refresh_separation_layout()
            self._sync_options_bottom_clearance()
            self._reveal_data_dir_banner_if_needed()
```

Add a shared handler next to `toast` (before line 1054):

```python
    def _handle_settings_error(self, error: Optional[str]) -> None:
        """Toast a settings-save failure and re-check the data-folder banner."""
        if not error:
            return
        self.toast(error)
        self._reveal_data_dir_banner_if_needed()
```

Then route the two existing save-error sites through it. In `_finalize_close` (lines 840-845):

```python
    def _finalize_close(self, deferred: bool) -> None:
        self._flush_settings()
        self._save_geometry()
        self._handle_settings_error(self.context.try_save_settings(trigger="close"))
```

And in `_start_separation` (lines 901-903):

```python
        try:
            self._handle_settings_error(
                self.context.try_save_settings(trigger="start")
            )
```

- [ ] **Step 8: Run the suite**

Run: `.venv/bin/python -m unittest discover -s tests -v`
Expected: PASS, no new failures.

- [ ] **Step 9: Commit**

```bash
git add ui/window.py tests/test_data_dir_banner.py
git commit -m "fix(ui): make the non-writable data-folder banner actionable"
```

---

### Task 4: Dim FP16 autocast when GPU conversion is off

`is_autocast` drives CUDA `torch.autocast` (`engines/amp_runtime.py`); with `is_gpu_conversion` off the switch does nothing but stays fully interactive on both the Separation and Ensemble pages.

**Files:**
- Modify: `ui/shared_settings.py` (add helper)
- Modify: `ui/window.py:567-595,639-680,821-823`
- Modify: `ui/ensemble/window.py:366-396,438-455,505-512`
- Test: `tests/test_gpu_dependent_rows.py` (create)

**Interfaces:**
- Produces: `ui.shared_settings.gpu_dependent_enabled(is_gpu_conversion: bool) -> bool`
- Produces: `MainWindow._sync_gpu_dependent_rows() -> None`, `EnsemblePage._sync_gpu_dependent_rows() -> None`

- [ ] **Step 1: Write the failing test**

Create `tests/test_gpu_dependent_rows.py`:

```python
"""FP16 autocast is only meaningful when GPU conversion is on."""

from __future__ import annotations

import os
import unittest

from ui.shared_settings import gpu_dependent_enabled


class GpuDependencyRuleTests(unittest.TestCase):
    def test_enabled_when_gpu_conversion_on(self):
        self.assertTrue(gpu_dependent_enabled(True))

    def test_disabled_when_gpu_conversion_off(self):
        self.assertFalse(gpu_dependent_enabled(False))


@unittest.skipUnless(
    os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"),
    "GTK widget construction needs a display",
)
class AutocastRowSensitivityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        import gi

        gi.require_version("Gtk", "4.0")
        gi.require_version("Adw", "1")
        from gi.repository import Adw

        cls._app = Adw.Application(application_id="org.uvr.test.gpu-dependents")
        cls._app.register()

    def _window(self, *, gpu_on: bool):
        """A bare MainWindow with only the two rows the sync method touches.

        Constructing a real MainWindow would build the whole AppContext, read
        ``data.pkl`` and spawn the download-queue UI — far too much for a
        sensitivity check.
        """
        from gi.repository import Adw

        from ui.window import MainWindow

        window = MainWindow.__new__(MainWindow)
        window.gpu_row = Adw.SwitchRow(title="GPU conversion")
        window.gpu_row.set_active(gpu_on)
        window.autocast_row = Adw.SwitchRow(title="FP16 autocast")
        return window

    def test_autocast_dimmed_when_gpu_off(self):
        from ui.window import MainWindow

        window = self._window(gpu_on=False)
        MainWindow._sync_gpu_dependent_rows(window)
        self.assertFalse(window.autocast_row.get_sensitive())

    def test_autocast_editable_when_gpu_on(self):
        from ui.window import MainWindow

        window = self._window(gpu_on=True)
        MainWindow._sync_gpu_dependent_rows(window)
        self.assertTrue(window.autocast_row.get_sensitive())


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m unittest tests.test_gpu_dependent_rows -v`
Expected: FAIL with `ImportError: cannot import name 'gpu_dependent_enabled'`

- [ ] **Step 3: Add the shared rule**

In `ui/shared_settings.py`, after `sample_mode_subtitle` (line 30):

```python
def gpu_dependent_enabled(is_gpu_conversion: bool) -> bool:
    """Whether GPU-only options (FP16 autocast, device pick) should be editable.

    ``is_autocast`` wraps CUDA ``torch.autocast`` (see ``engines/amp_runtime.py``)
    and has no effect on CPU runs, so its row is dimmed rather than hidden —
    per the GNOME HIG, an inapplicable control stays discoverable.
    """
    return bool(is_gpu_conversion)
```

- [ ] **Step 4: Run rule test to verify it passes**

Run: `.venv/bin/python -m unittest tests.test_gpu_dependent_rows.GpuDependencyRuleTests -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Apply it on the Separation page**

In `ui/window.py`, add the import to the existing `.shared_settings` import block (lines 66-73):

```python
from .shared_settings import (
    SAMPLE_MODE_TITLE,
    apply_sample_mode_label,
    apply_shared_file_options,
    format_input_sanitize_toasts,
    gpu_dependent_enabled,
    sample_mode_subtitle,
    sanitize_input_paths,
)
```

Add the sync method next to `_refresh_active_stem_metadata` (before line 832):

```python
    def _sync_gpu_dependent_rows(self) -> None:
        """Dim GPU-only options while GPU conversion is off."""
        self.autocast_row.set_sensitive(
            gpu_dependent_enabled(self.gpu_row.get_active())
        )
```

Call it from `_on_gpu_changed` (line 821):

```python
    def _on_gpu_changed(self, *_args) -> None:
        self.settings.set("is_gpu_conversion", self.gpu_row.get_active())
        self._sync_gpu_dependent_rows()
        self._refresh_active_stem_metadata()
```

And for the initial state, in `_load_from_settings` immediately after `self.autocast_row.set_active(...)` (line 654):

```python
        self.autocast_row.set_active(bool(self.settings.get("is_autocast")))
        self._sync_gpu_dependent_rows()
```

Also call it at the end of `_sync_shared_from_settings` (after line 717) so cross-tab syncing keeps the dimming right:

```python
        self._sync_gpu_dependent_rows()
```

- [ ] **Step 6: Apply the same on the Ensemble page**

In `ui/ensemble/window.py`, import `gpu_dependent_enabled` from `..shared_settings` alongside the existing imports from that module, then add:

```python
    def _sync_gpu_dependent_rows(self) -> None:
        """Dim GPU-only options while GPU conversion is off."""
        self.autocast_row.set_sensitive(
            gpu_dependent_enabled(self.gpu_row.get_active())
        )
```

Call it from `_on_gpu_changed` (line 505):

```python
    def _on_gpu_changed(self, *_args) -> None:
        if not self._loading:
            self.settings.set("is_gpu_conversion", self.gpu_row.get_active())
            self._update_stems_group_metadata()
        self._sync_gpu_dependent_rows()
```

Note the call sits **outside** the `_loading` guard so the initial `load()` pass also applies the dimming. Add the same call at the end of `load()` (after the `_loading = False` block, around line 455).

Audio Tools has an `apollo_gpu_row` but no autocast row — leave it unchanged.

- [ ] **Step 7: Run the tests**

Run: `.venv/bin/python -m unittest tests.test_gpu_dependent_rows tests.test_shared_settings -v`
Expected: PASS (the widget test skips without a display)

- [ ] **Step 8: Commit**

```bash
git add ui/shared_settings.py ui/window.py ui/ensemble/window.py tests/test_gpu_dependent_rows.py
git commit -m "fix(ui): dim FP16 autocast when GPU conversion is off"
```

---

### Task 5: Gate "Activate…" switches over their dependent rows

In `Extra models`, "Activate secondary model" leaves 8 dependent rows editable when off; "Activate pre-process model" leaves 2; "Enable vocal split mode" leaves 3. `ui/ensemble/window.py:882-890` already establishes the dim-dependents pattern in this codebase.

**Files:**
- Modify: `ui/views/base.py:626-702` (and `load`, line 363)
- Test: `tests/test_switch_dependents.py` (create)

**Interfaces:**
- Produces: `MethodView._bind_switch_dependents(switch_row, dependents: Sequence) -> None`

- [ ] **Step 1: Write the failing test**

Create `tests/test_switch_dependents.py`:

```python
"""Activate switches dim the rows they gate."""

from __future__ import annotations

import os
import unittest
from unittest.mock import MagicMock


@unittest.skipUnless(
    os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"),
    "GTK widget construction needs a display",
)
class SwitchDependentsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        import gi

        gi.require_version("Gtk", "4.0")
        gi.require_version("Adw", "1")
        from gi.repository import Adw

        cls._app = Adw.Application(application_id="org.uvr.test.switch-dependents")
        cls._app.register()

    def _view(self):
        from ui.views.base import MethodView

        view = MethodView.__new__(MethodView)
        return view

    def test_dependents_follow_the_switch(self):
        from gi.repository import Adw

        from ui.views.base import MethodView

        view = self._view()
        switch = Adw.SwitchRow(title="Activate secondary model")
        dependent = Adw.ActionRow(title="Vocals/Instrumental")

        MethodView._bind_switch_dependents(view, switch, [dependent])

        switch.set_active(False)
        self.assertFalse(dependent.get_sensitive())
        switch.set_active(True)
        self.assertTrue(dependent.get_sensitive())

    def test_initial_state_is_applied_immediately(self):
        from gi.repository import Adw

        from ui.views.base import MethodView

        view = self._view()
        switch = Adw.SwitchRow(title="Enable vocal split mode")
        switch.set_active(False)
        dependent = Adw.ActionRow(title="Vocal splitter model")
        dependent.set_sensitive(True)

        MethodView._bind_switch_dependents(view, switch, [dependent])

        self.assertFalse(dependent.get_sensitive())


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m unittest tests.test_switch_dependents -v`
Expected: FAIL with `AttributeError: type object 'MethodView' has no attribute '_bind_switch_dependents'`

- [ ] **Step 3: Add the binding helper**

In `ui/views/base.py`, add this method to `MethodView` immediately before `_build_secondary_section` (before line 626):

```python
    def _bind_switch_dependents(self, switch_row, dependents) -> None:
        """Dim ``dependents`` whenever ``switch_row`` is off.

        Mirrors the pattern already used for the Ensemble algorithm rows: an
        inapplicable control stays visible but non-interactive, so the section's
        shape doesn't change as switches flip.
        """
        rows = [row for row in dependents if row is not None]

        def apply(*_args) -> None:
            active = switch_row.get_active()
            for row in rows:
                row.set_sensitive(active)

        switch_row.connect("notify::active", apply)
        apply()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m unittest tests.test_switch_dependents -v`
Expected: PASS (2 tests; skipped without a display)

- [ ] **Step 5: Bind the secondary-models section**

In `_build_secondary_section`, replace the secondary-models block (lines 639-660) with a version that captures the rows it creates:

```python
        # Secondary models (one selector + scale per stem pair).
        if self.secondary_prefix:
            prefix = self.secondary_prefix
            self.secondary_expander = Adw.ExpanderRow(title="Secondary models")
            self.secondary_expander.connect("notify::expanded", self._ensure_model_combos_populated)
            activate = self.add_option_switch(
                self.secondary_expander,
                f"{prefix}_is_secondary_model_activate",
                "Activate secondary model",
                hint=SECONDARY_MODEL_ACTIVATE_HELP,
            )
            dependents = []
            for slot, pair, primary, secondary in _SECONDARY_SLOTS:
                model_key = f"{prefix}_{slot}_secondary_model"
                scale_key = f"{prefix}_{slot}_secondary_model_scale"
                provider = (lambda p=primary, s=secondary: repo.model_list(settings, p, s))
                dependents.append(
                    self._add_model_combo(self.secondary_expander, model_key, provider, pair, hint=SECONDARY_MODEL_HELP)
                )
                dependents.append(
                    self.add_option_scale(
                        self.secondary_expander,
                        scale_key,
                        f"{pair} influence",
                        lower=0.01,
                        upper=0.99,
                        step=0.01,
                        digits=2,
                        hint=SECONDARY_MODEL_SCALE_HELP,
                        store_float=True,
                    )
                )
            self._bind_switch_dependents(activate, dependents)
            group.add(self.secondary_expander)
```

`add_option_switch`, `add_option_scale` and `_add_model_combo` all already return their row (via `_hint`), so no signature changes are needed.

- [ ] **Step 6: Bind the pre-process section**

Replace the pre-process block (lines 663-675) with:

```python
        # Demucs pre-process model.
        if self.has_preproc:
            self.preproc_expander = Adw.ExpanderRow(title="Pre-process model")
            self.preproc_expander.connect("notify::expanded", self._ensure_model_combos_populated)
            activate = self.add_option_switch(self.preproc_expander, "is_demucs_pre_proc_model_activate", "Activate pre-process model", hint=PRE_PROC_MODEL_ACTIVATE_HELP)
            model_row = self._add_model_combo(
                self.preproc_expander,
                "demucs_pre_proc_model",
                lambda: repo.model_list(settings, VOCAL_STEM, INST_STEM, is_no_demucs=True),
                "Pre-process model",
                hint=SECONDARY_MODEL_HELP,
            )
            inst_mix_row = self.add_option_switch(self.preproc_expander, "is_demucs_pre_proc_model_inst_mix", "Save instrumental mixture", hint=PRE_PROC_MODEL_INST_MIX_HELP)
            self._bind_switch_dependents(activate, [model_row, inst_mix_row])
            group.add(self.preproc_expander)
```

- [ ] **Step 7: Bind the vocal-splitter section**

Replace the vocal-splitter block (lines 678-691) with:

```python
        # Vocal splitter and deverb (shared global options, surfaced per method).
        self.voc_split_expander = Adw.ExpanderRow(title="Vocal splitter and deverb")
        self.voc_split_expander.connect("notify::expanded", self._ensure_model_combos_populated)
        split_activate = self.add_option_switch(self.voc_split_expander, "is_set_vocal_splitter", "Enable vocal split mode", hint=IS_VOC_SPLIT_MODEL_SELECT_HELP)
        splitter_row = self._add_model_combo(
            self.voc_split_expander,
            "set_vocal_splitter",
            lambda: repo.karaoke_model_list(settings),
            "Vocal splitter model",
            hint=VOC_SPLIT_MODEL_SELECT_HELP,
        )
        save_inst_row = self.add_option_switch(self.voc_split_expander, "is_save_inst_set_vocal_splitter", "Save split vocal instrumentals", hint=IS_VOC_SPLIT_INST_SAVE_SELECT_HELP)
        self._bind_switch_dependents(split_activate, [splitter_row, save_inst_row])

        deverb_activate = self.add_option_switch(self.voc_split_expander, "is_deverb_vocals", "Deverb vocals", hint=IS_DEVERB_VOC_HELP)
        deverb_type_row = self.add_option_combo(self.voc_split_expander, "deverb_vocal_opt", "Deverb vocal type", list(DEVERB_MAPPER.keys()), hint=IS_DEVERB_OPT_HELP)
        self._bind_switch_dependents(deverb_activate, [deverb_type_row])
        group.add(self.voc_split_expander)
```

Note the deverb pair is bound separately: "Deverb vocals" gates only "Deverb vocal type", and is independent of vocal-split mode.

- [ ] **Step 8: Re-apply the dimming after settings load**

The switches are constructed before their stored values are read: `_load_switches` calls `row.set_active(...)`, but that fires `notify::active` while `self._loading` is `True` — and more importantly the initial `apply()` in Step 3 ran against pre-load state. So `load()` must re-apply every binding once settings are in.

Three edits, in this order.

**(a)** In `__init__`, next to `self._model_combos = []` (line 150), add the collector:

```python
        self._switch_dependent_appliers = []
```

**(b)** In `_bind_switch_dependents` (added in Step 3), register each closure. Replace its last two lines with:

```python
        switch_row.connect("notify::active", apply)
        # Guarded: tests exercise this method on a bare ``__new__`` instance.
        appliers = getattr(self, "_switch_dependent_appliers", None)
        if appliers is not None:
            appliers.append(apply)
        apply()
```

**(c)** Add the re-sync method next to `_bind_switch_dependents`:

```python
    def _sync_switch_dependents(self) -> None:
        """Re-apply every activate-switch's dimming after settings are loaded."""
        for apply in getattr(self, "_switch_dependent_appliers", ()):
            apply()
```

and call it from `MethodView.load` (line 363), after the `finally` block and before `self.update_stem_labels()`:

```python
        finally:
            self._loading = False
        self._sync_switch_dependents()
        self.update_stem_labels()
```

- [ ] **Step 9: Run the tests**

Run: `.venv/bin/python -m unittest tests.test_switch_dependents tests.test_views_base -v`
Expected: PASS

- [ ] **Step 10: Commit**

```bash
git add ui/views/base.py tests/test_switch_dependents.py
git commit -m "fix(ui): dim rows gated by their Activate switch"
```

---

### Task 6: Remove the duplicated settings from Preferences

`save_format`, `wav_type_set`, `mp3_bit_set`, `flac_bit_set`, `is_gpu_conversion` and `is_autocast` are all editable on the three processing pages already. Delete the whole Audio page and the two Hardware duplicates; `device_set` stays in Preferences and gains the GPU dependency.

**Files:**
- Modify: `ui/preferences.py:1-30 (docstring), 171-173, 261-284, 340-369, 461-476, 595-604`

**Interfaces:**
- Consumes: `ui.shared_settings.gpu_dependent_enabled` (Task 4).
- Produces: `PreferencesDialog` with two pages (`General`, `Processing`); attributes `format_row`, `wav_type_row`, `mp3_bit_row`, `flac_bit_row`, `gpu_row`, `autocast_row` no longer exist.

- [ ] **Step 1: Find every reference that must go**

Run: `rg -n 'format_row|wav_type_row|mp3_bit_row|flac_bit_row|_sync_format_rows|_build_audio_page|self\.gpu_row|self\.autocast_row' ui/preferences.py tests/`
Expected: hits only in `ui/preferences.py` (the `tests/test_shared_settings.py` hits are its own `_FakeFormatRow`, unrelated to Preferences). Record the line numbers before editing.

- [ ] **Step 2: Delete the Audio page**

In `ui/preferences.py`, delete the entire `_build_audio_page` method (lines 261-284) and its registration in `__init__` (line 172, `self.add(self._build_audio_page())`).

Delete `_on_format_changed` (lines 595-598) and `_sync_format_rows` (lines 600-604).

In `_reload_widgets`, delete the four `set_combo_value` calls and the `_sync_format_rows()` call (lines 471-475).

- [ ] **Step 3: Delete the Hardware duplicates**

In `_build_processing_page`, delete the `self.gpu_row` block (lines 341-347) and the `self.autocast_row` block (lines 349-356). `hardware_group` keeps `device_row` and (on Windows) `directml_row`.

Delete any now-unused imports flagged by the next step.

- [ ] **Step 4: Gate the GPU device row**

`is_gpu_conversion` is no longer editable in this dialog, so read it once at load. In `_reload_widgets`, where `device_set` is restored, add:

```python
            from ui.shared_settings import gpu_dependent_enabled

            self.device_row.set_sensitive(
                gpu_dependent_enabled(self.settings.get("is_gpu_conversion"))
            )
```

- [ ] **Step 5: Update the module docstring**

Line 13 currently reads:

```
* Audio format: ``save_format`` and the WAV bit-depth / MP3 bitrate / FLAC bit-depth sub-options.
```

Replace it with:

```
* Output format and its quality sub-option live on the Separation / Ensemble /
  Audio Tools pages (``ui/widgets/format_row.py``), not here — this dialog only
  holds settings with no per-run meaning.
```

- [ ] **Step 6: Verify no dangling references**

Run: `rg -n 'format_row|wav_type_row|mp3_bit_row|flac_bit_row|_sync_format_rows|_build_audio_page' ui/preferences.py`
Expected: no output.

Run: `.venv/bin/python -c "import ui.preferences"`
Expected: no output (clean import; catches unused-name typos).

- [ ] **Step 7: Run the suite**

Run: `.venv/bin/python -m unittest discover -s tests -v`
Expected: PASS, no new failures.

- [ ] **Step 8: Commit**

```bash
git add ui/preferences.py
git commit -m "refactor(ui): drop format and GPU duplicates from Preferences"
```

---

### Task 7: New combined Output-format row widget

One `Adw.ActionRow` carrying two side-by-side `Gtk.DropDown`s: the format, and the quality option that belongs to that format.

**Files:**
- Create: `ui/widgets/format_row.py`
- Test: `tests/test_format_row.py` (create)

**Interfaces:**
- Produces: `ui.widgets.format_row.quality_spec(save_format: str) -> QualitySpec`
- Produces: `ui.widgets.format_row.QualitySpec` — a frozen dataclass with fields `label: str`, `values: tuple[str, ...]`, `setting_key: str`, `default: str`
- Produces: `ui.widgets.format_row.OutputFormatRow(on_changed: Callable[[], None])` with:
  - `save_format -> str` (property)
  - `apply_from_settings(settings) -> None`
  - `persist_to_settings(settings) -> None`

- [ ] **Step 1: Write the failing test**

Create `tests/test_format_row.py`:

```python
"""Combined output-format + quality row."""

from __future__ import annotations

import os
import unittest

from bundled.constants import FLAC, MP3, WAV
from ui.widgets.format_row import quality_spec


class QualitySpecTests(unittest.TestCase):
    def test_wav_maps_to_wav_type(self):
        spec = quality_spec(WAV)
        self.assertEqual(spec.setting_key, "wav_type_set")
        self.assertEqual(spec.label, "WAV type")
        self.assertIn("PCM_16", spec.values)
        self.assertEqual(spec.default, "PCM_16")

    def test_mp3_maps_to_bitrate(self):
        spec = quality_spec(MP3)
        self.assertEqual(spec.setting_key, "mp3_bit_set")
        self.assertEqual(spec.label, "MP3 bitrate")
        self.assertIn("320k", spec.values)
        self.assertEqual(spec.default, "320k")

    def test_flac_maps_to_bit_depth(self):
        spec = quality_spec(FLAC)
        self.assertEqual(spec.setting_key, "flac_bit_set")
        self.assertEqual(spec.label, "FLAC bit depth")
        self.assertIn("24-bit", spec.values)
        self.assertEqual(spec.default, "16-bit")

    def test_unknown_format_falls_back_to_wav(self):
        self.assertEqual(quality_spec("OGG").setting_key, "wav_type_set")

    def test_every_default_is_a_valid_choice(self):
        for fmt in (WAV, MP3, FLAC):
            spec = quality_spec(fmt)
            self.assertIn(spec.default, spec.values)


@unittest.skipUnless(
    os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"),
    "GTK widget construction needs a display",
)
class OutputFormatRowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        import gi

        gi.require_version("Gtk", "4.0")
        gi.require_version("Adw", "1")
        from gi.repository import Adw

        cls._app = Adw.Application(application_id="org.uvr.test.format-row")
        cls._app.register()

    def _settings(self, **overrides):
        from core.settings import SettingsModel

        settings = SettingsModel()
        for key, value in overrides.items():
            settings.set(key, value)
        return settings

    def test_applies_stored_format_and_quality(self):
        from ui.widgets.format_row import OutputFormatRow

        row = OutputFormatRow(lambda: None)
        row.apply_from_settings(self._settings(save_format=MP3, mp3_bit_set="128k"))
        self.assertEqual(row.save_format, MP3)
        self.assertEqual(row.quality_value, "128k")

    def test_switching_format_swaps_the_quality_model(self):
        from ui.widgets.format_row import OutputFormatRow

        row = OutputFormatRow(lambda: None)
        row.apply_from_settings(self._settings(save_format=WAV))
        row.set_save_format(FLAC)
        self.assertEqual(row.quality_key, "flac_bit_set")
        self.assertIn(row.quality_value, quality_spec(FLAC).values)

    def test_persist_writes_both_keys(self):
        from ui.widgets.format_row import OutputFormatRow

        settings = self._settings(save_format=WAV)
        row = OutputFormatRow(lambda: None)
        row.apply_from_settings(settings)
        row.set_save_format(MP3)
        row.persist_to_settings(settings)
        self.assertEqual(settings.get("save_format"), MP3)
        self.assertIn(settings.get("mp3_bit_set"), quality_spec(MP3).values)

    def test_switching_away_and_back_keeps_the_other_format_setting(self):
        from ui.widgets.format_row import OutputFormatRow

        settings = self._settings(save_format=WAV, wav_type_set="PCM_24")
        row = OutputFormatRow(lambda: None)
        row.apply_from_settings(settings)
        row.set_save_format(MP3)
        row.persist_to_settings(settings)
        self.assertEqual(settings.get("wav_type_set"), "PCM_24")

    def test_on_changed_fires_for_both_dropdowns(self):
        from ui.widgets.format_row import OutputFormatRow

        calls = []
        row = OutputFormatRow(lambda: calls.append(1))
        row.apply_from_settings(self._settings(save_format=WAV))
        before = len(calls)
        row.set_save_format(FLAC)
        self.assertGreater(len(calls), before)

    def test_each_dropdown_has_an_accessible_label(self):
        from gi.repository import Gtk

        from ui.widgets.format_row import OutputFormatRow

        row = OutputFormatRow(lambda: None)
        row.apply_from_settings(self._settings(save_format=MP3))
        # The row title only names the first control, so the quality dropdown
        # must carry its own label for screen readers.
        for drop in (row._format_drop, row._quality_drop):
            self.assertIsInstance(drop, Gtk.DropDown)
            self.assertTrue(drop.get_tooltip_text())


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m unittest tests.test_format_row -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'ui.widgets.format_row'`

- [ ] **Step 3: Write the widget**

Create `ui/widgets/format_row.py`:

```python
"""Combined output-format row: format + its per-format quality option.

A single :class:`Adw.ActionRow` carrying two side-by-side :class:`Gtk.DropDown`
widgets. The second dropdown's model, label and settings key swap with the
selected format (WAV type / MP3 bitrate / FLAC bit depth), so the three
processing pages expose the complete export choice in one row instead of
sending the user to a separate Preferences page.

The unselected formats' settings keys are left untouched, so switching WAV ->
MP3 -> WAV restores the previously chosen WAV type.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional

from gi.repository import Adw, Gtk

from bundled.constants import (
    FLAC,
    FLAC_BIT_DEPTHS,
    MP3,
    MP3_BIT_RATES,
    WAV,
    WAV_TYPE,
)

from .rows import set_row_icon

#: Minimum width for the quality dropdown so it doesn't resize when the model
#: swaps between short ("320k") and long ("32-bit Float") values.
_QUALITY_MIN_WIDTH = 132
_FORMAT_MIN_WIDTH = 96

FORMATS = (WAV, FLAC, MP3)


@dataclass(frozen=True)
class QualitySpec:
    """The quality dropdown's configuration for one output format."""

    label: str
    values: tuple[str, ...]
    setting_key: str
    default: str


_QUALITY_SPECS = {
    WAV: QualitySpec("WAV type", tuple(WAV_TYPE), "wav_type_set", "PCM_16"),
    MP3: QualitySpec("MP3 bitrate", tuple(MP3_BIT_RATES), "mp3_bit_set", "320k"),
    FLAC: QualitySpec("FLAC bit depth", tuple(FLAC_BIT_DEPTHS), "flac_bit_set", "16-bit"),
}


def quality_spec(save_format: str) -> QualitySpec:
    """Return the quality-dropdown spec for ``save_format`` (WAV when unknown)."""
    return _QUALITY_SPECS.get(save_format, _QUALITY_SPECS[WAV])


def _dropdown(values, min_width: int) -> Gtk.DropDown:
    drop = Gtk.DropDown.new_from_strings(list(values))
    drop.set_valign(Gtk.Align.CENTER)
    drop.set_size_request(min_width, -1)
    return drop


def _selected_string(drop: Gtk.DropDown) -> Optional[str]:
    item = drop.get_selected_item()
    return item.get_string() if item is not None else None


def _select_string(drop: Gtk.DropDown, value: str) -> bool:
    model = drop.get_model()
    for index in range(model.get_n_items()):
        if model.get_string(index) == value:
            drop.set_selected(index)
            return True
    return False


class OutputFormatRow(Adw.ActionRow):
    """Output format plus its quality sub-option, side by side in one row."""

    def __init__(self, on_changed: Callable[[], None]):
        super().__init__(title="Output format")
        set_row_icon(self, "waveform-symbolic")
        self._on_changed = on_changed
        self._syncing = False

        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        box.set_valign(Gtk.Align.CENTER)

        self._format_drop = _dropdown(FORMATS, _FORMAT_MIN_WIDTH)
        self._format_drop.set_tooltip_text("Output format")
        self._format_drop.update_property(
            [Gtk.AccessibleProperty.LABEL], ["Output format"]
        )
        self._format_drop.connect("notify::selected", self._on_format_selected)
        box.append(self._format_drop)

        self._quality_drop = _dropdown(quality_spec(WAV).values, _QUALITY_MIN_WIDTH)
        self._quality_drop.connect("notify::selected", self._on_quality_selected)
        box.append(self._quality_drop)

        self.add_suffix(box)
        self._apply_quality_labels(WAV)

    # -- State ------------------------------------------------------------------

    @property
    def save_format(self) -> str:
        return _selected_string(self._format_drop) or WAV

    @property
    def quality_key(self) -> str:
        return quality_spec(self.save_format).setting_key

    @property
    def quality_value(self) -> str:
        spec = quality_spec(self.save_format)
        return _selected_string(self._quality_drop) or spec.default

    def set_save_format(self, value: str) -> None:
        if not _select_string(self._format_drop, value):
            _select_string(self._format_drop, WAV)

    # -- Settings ---------------------------------------------------------------

    def apply_from_settings(self, settings) -> None:
        """Restore both dropdowns from ``settings`` without emitting changes."""
        self._syncing = True
        try:
            self.set_save_format(settings.get("save_format", WAV))
            self._reload_quality(settings)
        finally:
            self._syncing = False

    def persist_to_settings(self, settings) -> None:
        """Write the format and *only its own* quality key back to ``settings``."""
        settings.set("save_format", self.save_format)
        settings.set(self.quality_key, self.quality_value)

    # -- Internals --------------------------------------------------------------

    def _reload_quality(self, settings) -> None:
        spec = quality_spec(self.save_format)
        self._quality_drop.set_model(Gtk.StringList.new(list(spec.values)))
        stored = settings.get(spec.setting_key, spec.default)
        if not _select_string(self._quality_drop, str(stored)):
            _select_string(self._quality_drop, spec.default)
        self._apply_quality_labels(self.save_format)

    def _apply_quality_labels(self, save_format: str) -> None:
        spec = quality_spec(save_format)
        self._quality_drop.set_tooltip_text(spec.label)
        self._quality_drop.update_property(
            [Gtk.AccessibleProperty.LABEL], [spec.label]
        )

    def _on_format_selected(self, *_args) -> None:
        if self._syncing:
            return
        spec = quality_spec(self.save_format)
        self._syncing = True
        try:
            self._quality_drop.set_model(Gtk.StringList.new(list(spec.values)))
            _select_string(self._quality_drop, spec.default)
            self._apply_quality_labels(self.save_format)
        finally:
            self._syncing = False
        self._on_changed()

    def _on_quality_selected(self, *_args) -> None:
        if self._syncing:
            return
        self._on_changed()
```

Note: `_on_format_selected` resets the quality dropdown to the format's default because the widget has no settings reference at that moment. Callers restore the stored value on the next `apply_from_settings`; `persist_to_settings` only ever writes the *active* format's key, so the other formats' stored values survive (covered by `test_switching_away_and_back_keeps_the_other_format_setting`).

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m unittest tests.test_format_row -v`
Expected: PASS (5 pure tests always; 6 widget tests when a display is present)

- [ ] **Step 5: Commit**

```bash
git add ui/widgets/format_row.py tests/test_format_row.py
git commit -m "feat(ui): add combined output format + quality row"
```

---

### Task 8: Adopt the combined format row on all three pages

**Files:**
- Modify: `ui/shared_settings.py:169-252`
- Modify: `ui/window.py:567-595,639-680,818-819,857-868`
- Modify: `ui/ensemble/window.py:366-372,438-455,501-503`
- Modify: `ui/audio_tools/window.py:422-434,505-520,645-657`
- Modify: `tests/test_shared_settings.py:270-300`

**Interfaces:**
- Consumes: `ui.widgets.format_row.OutputFormatRow` (Task 7).
- Produces: `apply_shared_file_options(..., format_row=...)` now calls `format_row.apply_from_settings(settings)` instead of `set_combo_value`.

- [ ] **Step 1: Update the failing shared-settings test first**

In `tests/test_shared_settings.py`, replace the `_FakeFormatRow` class with one matching the new protocol, and update the assertion at line 299:

```python
class _FakeFormatRow:
    def __init__(self):
        self.applied_from = None

    def apply_from_settings(self, settings):
        self.applied_from = settings.get("save_format")
```

```python
            self.assertEqual(format_row.applied_from, FLAC)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m unittest tests.test_shared_settings -v`
Expected: FAIL — `apply_shared_file_options` still calls `set_combo_value`, so `applied_from` stays `None`.

- [ ] **Step 3: Update the shared-settings protocol**

In `ui/shared_settings.py`, replace the `format_row` handling in `apply_shared_file_options` (line 242-243) with:

```python
    if format_row is not None:
        format_row.apply_from_settings(settings)
```

Add the protocol next to the other `_*Row` protocols (after line 179):

```python
class _FormatRow(Protocol):
    def apply_from_settings(self, settings) -> None: ...
```

and type the parameter `format_row: Optional[_FormatRow] = None`.

`set_combo_value` was imported solely for this call site. Run `rg -n 'set_combo_value' ui/shared_settings.py`; if the only remaining hit is the import at line 17, delete that import.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m unittest tests.test_shared_settings -v`
Expected: PASS

- [ ] **Step 5: Swap the row on the Separation page**

In `ui/window.py`:

Add the import next to the other widget imports (after line 85):

```python
from .widgets.format_row import OutputFormatRow
```

In `_build_shared_group` (line 570), replace the `format_row` construction:

```python
        self.format_row = OutputFormatRow(self._on_format_changed)
        group.add(self.format_row)
```

Replace `_on_format_changed` (line 818):

```python
    def _on_format_changed(self, *_args) -> None:
        self.format_row.persist_to_settings(self.settings)
```

In `_load_from_settings` (line 652), replace `set_combo_value(self.format_row, ...)`:

```python
        self.format_row.apply_from_settings(self.settings)
```

In `_flush_settings` (line 864), replace the `save_format` write:

```python
        self.format_row.persist_to_settings(self.settings)
```

Remove `OUTPUT_FORMAT_HINT` from the `_register_hints` registration for `format_row` — the two dropdowns carry their own tooltips now, and a row-level tooltip would fight them. Delete line 624 (`self._hint_manager.register(self.format_row, OUTPUT_FORMAT_HINT)`) and drop `OUTPUT_FORMAT_HINT` from the `.hints` import if unused elsewhere in the file (check with `rg -n 'OUTPUT_FORMAT_HINT' ui/window.py`).

- [ ] **Step 6: Swap the row on the Ensemble page**

In `ui/ensemble/window.py`, apply the same four changes:
- `_build_output_group` (line 369): `self.format_row = OutputFormatRow(self._on_format_changed)`, drop the `set_tooltip(self.format_row, OUTPUT_FORMAT_HINT)` line.
- `load()` (line 449): `self.format_row.apply_from_settings(self.settings)`
- `_on_format_changed` (line 501):
  ```python
      def _on_format_changed(self, *_args) -> None:
          if not self._loading:
              self.format_row.persist_to_settings(self.settings)
  ```
- Any `_flush`/save path that writes `save_format` (line 503 area) becomes `self.format_row.persist_to_settings(self.settings)`.

- [ ] **Step 7: Swap the row on the Audio Tools page**

`ui/audio_tools/window.py` already has a separate `wav_type_row`; the new widget subsumes it.

- In `_build_shared_group` (lines 425-433), replace **both** `self.format_row` and `self.wav_type_row` with a single:
  ```python
          self.format_row = OutputFormatRow(self._on_format_changed)
          group.add(self.format_row)
  ```
  Delete the `self.hints.register(self.format_row, OUTPUT_FORMAT_HINT)` and `self.hints.register(self.wav_type_row, WAV_TYPE_HINT)` lines.
- In `load` (lines 513-514), replace both `set_combo_value` calls with `self.format_row.apply_from_settings(self.settings)`.
- Replace `_on_format_changed` / `_sync_format_rows` (lines 651-657) with:
  ```python
      def _on_format_changed(self, *_args) -> None:
          if self._loading:
              return
          self.format_row.persist_to_settings(self.settings)
  ```
  Delete `_sync_format_rows` entirely and remove its call site in `load` (line 543).
- Fix line 653's `self._set("save_format", ...)` — it is replaced by `persist_to_settings`.
- Drop the now-unused `WAV_TYPE` / `WAV_TYPE_HINT` imports (verify with `rg -n 'WAV_TYPE' ui/audio_tools/window.py`).

- [ ] **Step 8: Verify no page still uses a bare format combo**

Run: `rg -n 'set_combo_value\(self\.format_row|make_combo_row\("Output format"' ui/`
Expected: no output.

Run: `rg -n 'wav_type_row|mp3_bit_row|flac_bit_row' ui/`
Expected: no output.

- [ ] **Step 9: Run the suite**

Run: `.venv/bin/python -m unittest discover -s tests -v`
Expected: PASS, no new failures.

- [ ] **Step 10: Smoke-test the real app**

Run: `python -m ui`
Check: on each of Separation / Ensemble / Audio Tools, the Processing group shows one "Output format" row with two dropdowns; switching WAV → MP3 → FLAC swaps the right-hand dropdown's contents; the choice survives an app restart. Narrow the window past the 880sp breakpoint and confirm the pair still fits in the single column.

- [ ] **Step 11: Commit**

```bash
git add ui/shared_settings.py ui/window.py ui/ensemble/window.py ui/audio_tools/window.py tests/test_shared_settings.py
git commit -m "feat(ui): use the combined format row on all processing pages"
```

---

### Task 9: Stop rebuilding the whole window on every Preferences toggle

`_flush_persist` calls `MainWindow._load_from_settings`, which re-hashes and re-lists every model and reparents every option group — ~400ms after each switch flip. Profile load and Reset genuinely need the full reload; ordinary edits do not.

**Files:**
- Modify: `ui/preferences.py:156-176,622-629`
- Modify: `ui/window.py:929-936`

**Interfaces:**
- Produces: `PreferencesDialog(context, on_settings_reloaded=None, on_settings_applied=None)`
- Produces: `MainWindow._sync_after_preferences() -> None`

- [ ] **Step 1: Add the light callback parameter**

In `ui/preferences.py`, change the constructor signature (line 159) and store the new callback:

```python
    def __init__(self, context, on_settings_reloaded=None, on_settings_applied=None):
        super().__init__()
        self.context = context
        self.settings = context.settings
        self._on_settings_reloaded = on_settings_reloaded
        self._on_settings_applied = on_settings_applied
```

Extend the class docstring (line 157):

```python
    """libadwaita settings dialog bound to the shared :class:`SettingsModel`.

    Two callbacks, deliberately asymmetric:

    * ``on_settings_applied`` — fired after every debounced edit. Must be cheap:
      the main window only needs to re-read the handful of keys it mirrors.
    * ``on_settings_reloaded`` — fired only when the settings model is replaced
      wholesale (profile load, reset to defaults), where a full rebuild of the
      window's widgets is the point.
    """
```

- [ ] **Step 2: Route ordinary edits to the light callback**

Replace `_flush_persist` (lines 622-629):

```python
    def _flush_persist(self) -> bool:
        self._persist_timeout_id = 0
        error = self.context.try_save_settings(trigger="preferences")
        if error:
            self.add_toast(Adw.Toast.new(error))
        elif self._on_settings_applied is not None:
            self._on_settings_applied()
        return GLib.SOURCE_REMOVE
```

Leave the two `_on_settings_reloaded()` call sites at lines ~746 (profile load) and ~809 (reset) exactly as they are — those replace the whole settings model.

- [ ] **Step 3: Add the light sync on the window**

In `ui/window.py`, add next to `_on_open_settings`:

```python
    def _sync_after_preferences(self) -> None:
        """Cheap re-read of the keys Preferences shares with the visible tab.

        Preferences only edits a handful of keys the processing pages mirror
        (format, GPU, sample mode), so a full ``_load_from_settings`` — which
        re-lists every model and reparents every option group — is far too
        heavy for a single switch flip.
        """
        target = self._targets.get(self.content_stack.get_visible_child_name())
        if target is not None:
            target.on_activated()
        self._refresh_start_readiness()
```

`on_activated` already runs the per-page shared sync: `_SeparationTarget.on_activated` → `_activate_separation` → `_sync_shared_from_settings`, and the Ensemble / Audio Tools pages do the equivalent.

- [ ] **Step 4: Pass both callbacks**

Replace `_on_open_settings` (lines 929-936):

```python
    def _on_open_settings(self, _action: Gio.SimpleAction, _param) -> None:
        from core.debug_log import debug

        debug("ui", "open settings")
        from .preferences import PreferencesDialog

        dialog = PreferencesDialog(
            self.context,
            on_settings_reloaded=self._load_from_settings,
            on_settings_applied=self._sync_after_preferences,
        )
        dialog.present(self)
```

- [ ] **Step 5: Verify with debug logging**

Run: `G_MESSAGES_DEBUG=uvr-ui,uvr-model python -m ui`
Open Settings, toggle "Normalize output" twice.
Expected: **no** `refresh_models view=...` lines in the output (those only appear on `_load_from_settings`). Then use Settings → Reset, and confirm the `refresh_models` lines *do* appear.

- [ ] **Step 6: Run the suite**

Run: `.venv/bin/python -m unittest discover -s tests -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add ui/preferences.py ui/window.py
git commit -m "perf(ui): use a light resync for ordinary Preferences edits"
```

---

### Task 10: Stop the Audio Tools column width from jumping

Matchering hides `_col_end` entirely, so the Files card snaps from half-width to the full clamp width and back as the tool changes.

**Files:**
- Modify: `ui/audio_tools/window.py:545-583`

- [ ] **Step 1: Delete the column-balance juggling**

In `ui/audio_tools/window.py`, delete `_sync_column_balance` entirely (lines 572-583) and its call site in `_sync_tool_visibility` (line 554).

`shared_group` is appended to `_col_end` at build time and now simply stays there for every tool. Matchering keeps a shorter left column instead of a full-width one — no reflow.

- [ ] **Step 2: Verify the group is still parented at build time**

Run: `rg -n 'shared_group' ui/audio_tools/window.py`
Expected: the build-time `self._col_end.append(self.shared_group)` (or equivalent) is present and no other code removes it. If `_build_*` relied on `_sync_column_balance` to do the initial append, add the explicit append there.

- [ ] **Step 3: Smoke-test**

Run: `python -m ui`
Switch to Audio Tools and cycle the tool picker through Matchering and back.
Expected: the Files card keeps a constant width; no visible reflow.

- [ ] **Step 4: Run the suite**

Run: `.venv/bin/python -m unittest discover -s tests -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add ui/audio_tools/window.py
git commit -m "fix(ui): keep Audio Tools column widths stable across tools"
```

---

### Task 11: Error styling for the output folder + a missing accessible label

**Files:**
- Modify: `ui/widgets/file_chooser.py:294-305`
- Modify: `ui/widgets/download_queue_indicator.py:408-412`
- Test: `tests/test_file_chooser_expansion.py` (extend from Task 1)

**Interfaces:**
- Produces: `ui.widgets.file_chooser.output_subtitle(path: str, reason: Optional[str]) -> tuple[str, bool]` returning `(subtitle, is_error)`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_file_chooser_expansion.py`:

```python
class OutputSubtitleTests(unittest.TestCase):
    def test_empty_path_is_not_an_error(self):
        from ui.widgets.file_chooser import output_subtitle

        subtitle, is_error = output_subtitle("", None)
        self.assertEqual(subtitle, "No folder selected")
        self.assertFalse(is_error)

    def test_valid_path_is_shown_plainly(self):
        from ui.widgets.file_chooser import output_subtitle

        subtitle, is_error = output_subtitle("/tmp/out", None)
        self.assertEqual(subtitle, "/tmp/out")
        self.assertFalse(is_error)

    def test_missing_folder_is_an_error(self):
        from ui.widgets.file_chooser import output_subtitle

        subtitle, is_error = output_subtitle(
            "/tmp/gone", "Output folder no longer exists — select a new folder"
        )
        self.assertTrue(is_error)
        self.assertIn("not found", subtitle)
        self.assertIn("/tmp/gone", subtitle)

    def test_read_only_folder_is_an_error(self):
        from ui.widgets.file_chooser import output_subtitle

        subtitle, is_error = output_subtitle(
            "/tmp/ro", "Output folder is not writable — choose another folder"
        )
        self.assertTrue(is_error)
        self.assertIn("not writable", subtitle)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m unittest tests.test_file_chooser_expansion -v`
Expected: FAIL with `ImportError: cannot import name 'output_subtitle'`

- [ ] **Step 3: Extract the helper**

In `ui/widgets/file_chooser.py`, add next to `expander_state`:

```python
def output_subtitle(path: str, reason: Optional[str]) -> tuple[str, bool]:
    """Return ``(subtitle, is_error)`` for the export-folder row."""
    if not path:
        return "No folder selected", False
    if not reason:
        return path, False
    if "writable" in reason.lower():
        return f"Folder not writable — {path}", True
    return f"Folder not found — {path}", True
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m unittest tests.test_file_chooser_expansion -v`
Expected: PASS (10 tests)

- [ ] **Step 5: Apply the error style**

Replace `OutputFolderRow._refresh_subtitle` (lines 294-305):

```python
    def _refresh_subtitle(self) -> None:
        subtitle, is_error = output_subtitle(
            self.path, export_path_blocked_reason(self.path) if self.path else None
        )
        set_row_subtitle(self, subtitle)
        # libadwaita's .error class tints the row so a stale or read-only export
        # folder reads as a failure instead of an ordinary path.
        if is_error:
            self.add_css_class("error")
        else:
            self.remove_css_class("error")
```

- [ ] **Step 6: Add the missing accessible label**

In `ui/widgets/download_queue_indicator.py` (line 412), replace the bare tooltip:

```python
        set_icon_button_a11y(action_button, "Cancel download")
```

Add the import if absent: `from ..hints import set_icon_button_a11y` (check the file's existing imports first with `rg -n '^from|^import' ui/widgets/download_queue_indicator.py`).

- [ ] **Step 7: Run the tests**

Run: `.venv/bin/python -m unittest tests.test_file_chooser_expansion tests.test_download_queue_indicator -v`
Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add ui/widgets/file_chooser.py ui/widgets/download_queue_indicator.py tests/test_file_chooser_expansion.py
git commit -m "fix(ui): flag a bad export folder and label the cancel button"
```

---

### Task 12: Correct the stylesheet colour syntax

`resources/style.css` mixes libadwaita's CSS-variable syntax (needs 1.6+) with the legacy named-colour syntax used everywhere else, and pairs a card foreground with a window background.

**Files:**
- Modify: `resources/style.css:31-33,120-127`
- Regenerate: `ui/data/uvr.gresource`

- [ ] **Step 1: Fix the mismatched colour pair**

In `.uvr-log-panel` (lines 31-33), the panel paints `@window_bg_color` but takes its foreground from `@card_fg_color`. Change the foreground to match the background it actually uses:

```css
    background-color: @window_bg_color;
    color: @window_fg_color;
```

- [ ] **Step 2: Fix the keyframe's colour syntax**

The `needs_attention_keyframes` rule (line 127) is the only place in the file using `var(--accent-bg-color)`; on libadwaita < 1.6 that resolves to nothing and the highlight silently never appears. Use the named colour the rest of the file uses:

```css
@keyframes needs_attention_keyframes {
    0% { }
    10% { background-color: @accent_bg_color; }
    100% { }
}
```

- [ ] **Step 3: Verify no other CSS-variable usage remains**

Run: `rg -n 'var\(--' resources/style.css`
Expected: no output.

- [ ] **Step 4: Recompile the GResource bundle**

The app loads the *compiled* stylesheet, so edits to `resources/style.css` are invisible until the bundle is rebuilt.

Run: `./resources/compile_resources.sh`
Expected: `ui/data/uvr.gresource` is rewritten (confirm with `git status --short ui/data/uvr.gresource`).

- [ ] **Step 5: Verify visually**

Run: `UVR_DEV_CSS=1 python -m ui`
Check: the floating log panel's text contrast is unchanged in both light and dark (toggle via Settings → Appearance → Color scheme), and queueing a download flashes the header chip.

- [ ] **Step 6: Run the suite**

Run: `.venv/bin/python -m unittest discover -s tests -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add resources/style.css ui/data/uvr.gresource
git commit -m "fix(ui): correct stylesheet colour syntax and pairing"
```

---

### Task 13: Drop the redundant non-applicable toast and the duplicate toast method

Each model-options tab already carries a subtitle explaining whether its architecture applies to the current run; toasting the same thing on the first edit is noise. Separately, `MainWindow.toast` and `MainWindow._toast` are identical.

**Files:**
- Modify: `ui/model_options/sheet.py:44-51,195-212,299-310,312-317,329-330`
- Modify: `ui/window.py:1054-1059` and all `_toast` call sites
- Modify: `tests/test_model_options_sheet_callbacks.py`

- [ ] **Step 1: Check what the sheet-callback test asserts**

Run: `.venv/bin/python -m unittest tests.test_model_options_sheet_callbacks -v` and read the file.
If it asserts the wrap/restore of `view._on_settings_changed`, that machinery exists *only* to drive the toast and goes away with it — update the test to assert the callbacks are left untouched instead. If it asserts something else, leave those cases alone.

- [ ] **Step 2: Remove the toast machinery from the sheet**

In `ui/model_options/sheet.py`, delete:
- `_maybe_toast_non_applicable` (lines 299-310)
- `_wrap_settings_callback` and `_restore_settings_callbacks` (lines 195-212)
- the `self._settings_wrappers` and `self._toast_shown` attributes (lines 50-51)
- the `for view in self._views: self._wrap_settings_callback(view)` loop in `present` (lines 329-330)
- the `_restore_settings_callbacks()` and `_toast_shown.clear()` calls in `_on_closed` (lines 315-317)
- the `self._toast_shown.clear()` line in `update_context` (line 228)

`_dialog_is_open` becomes unused — delete it too (lines 191-193).

- [ ] **Step 3: Keep the tab subtitle doing the work**

`_refresh_applicability` already sets `self._tab_subtitles[stack_name].set_label(subtitle)` from `applicability_subtitle(...)`. Leave that untouched — it is now the sole signal.

- [ ] **Step 4: Check whether `on_toast` is still needed**

Run: `rg -n '_on_toast|on_toast' ui/model_options/sheet.py ui/window.py`
If `_on_toast` has no remaining uses inside the sheet, remove the parameter from `ModelOptionsSheet.__init__` and `open_model_options_sheet`, and drop the `on_toast=self.toast` argument at `ui/window.py:1040`. Also remove `non_applicable_toast` from the `.applicability` import list if it is now unused (`rg -n 'non_applicable_toast' ui/`).

- [ ] **Step 5: Dedupe the toast method**

In `ui/window.py`, delete `_toast` (lines 1058-1059) and replace every internal call. Find them with:

Run: `rg -n '_toast\(' ui/`

Update each `self._toast(` → `self.toast(` in `ui/window.py`, and `window._toast(` → `window.toast(` in `ui/run_control.py` (lines 152, 651). Note `ui/files.py:_report_error` looks up `getattr(window, "_toast", None)` as a fallback — change that lookup to `"toast"`.

- [ ] **Step 6: Verify nothing still calls the removed method**

Run: `rg -n '_toast\b' ui/ tests/`
Expected: no output.

- [ ] **Step 7: Run the suite**

Run: `.venv/bin/python -m unittest discover -s tests -v`
Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add ui/model_options/sheet.py ui/window.py ui/run_control.py ui/files.py tests/test_model_options_sheet_callbacks.py
git commit -m "refactor(ui): drop the redundant applicability toast and _toast alias"
```

---

### Task 14: Accept dropped audio anywhere in the window

Drops currently only land on the two file rows; the rest of the window silently rejects them.

**Files:**
- Modify: `ui/window.py:210-216`
- Test: `tests/test_window_drop_routing.py` (create)

**Interfaces:**
- Produces: `ui.window.drop_target_row_name(tab_name: str, tool: Optional[str], dual_tools: Container[str]) -> Optional[str]` returning `"separation"`, `"ensemble"`, `"audio_tools"` or `None`.
- Produces: `MainWindow._input_row_for_drop() -> Optional[InputFilesRow]`

**Scope decision:** the drop routes to the visible tab's primary input row. Audio Tools' dual-input tools (Manual Ensemble / Align / Match) pair files positionally, so a window-level drop has no unambiguous meaning there — those return `None` and keep the existing per-row drop targets.

- [ ] **Step 1: Write the failing test**

Create `tests/test_window_drop_routing.py`:

```python
"""Which input row a window-level file drop is routed to."""

from __future__ import annotations

import unittest

from ui.window import drop_target_row_name

_DUAL = {"Manual Ensemble", "Align Inputs"}


class DropRoutingTests(unittest.TestCase):
    def test_separation_tab_routes_to_its_input_row(self):
        self.assertEqual(
            drop_target_row_name("separation", None, _DUAL), "separation"
        )

    def test_ensemble_tab_routes_to_its_input_row(self):
        self.assertEqual(drop_target_row_name("ensemble", None, _DUAL), "ensemble")

    def test_single_input_audio_tool_routes_to_its_input_row(self):
        self.assertEqual(
            drop_target_row_name("audio_tools", "Change Pitch", _DUAL), "audio_tools"
        )

    def test_dual_input_audio_tool_is_not_routed(self):
        self.assertIsNone(
            drop_target_row_name("audio_tools", "Manual Ensemble", _DUAL)
        )

    def test_unknown_tab_is_not_routed(self):
        self.assertIsNone(drop_target_row_name("mystery", None, _DUAL))

    def test_missing_tab_name_is_not_routed(self):
        self.assertIsNone(drop_target_row_name(None, None, _DUAL))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m unittest tests.test_window_drop_routing -v`
Expected: FAIL with `ImportError: cannot import name 'drop_target_row_name'`

- [ ] **Step 3: Add the routing rule**

In `ui/window.py`, next to `data_dir_banner_state`:

```python
def drop_target_row_name(tab_name, tool, dual_tools) -> Optional[str]:
    """Return which page's input row should receive a window-level file drop.

    Dual-input audio tools pair files positionally (left/right), so a drop with
    no drop point has no unambiguous meaning there — those keep their own
    per-row drop targets and are not routed.
    """
    if tab_name in ("separation", "ensemble"):
        return tab_name
    if tab_name == "audio_tools":
        return None if tool in dual_tools else "audio_tools"
    return None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m unittest tests.test_window_drop_routing -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Install the window-level drop target**

In `ui/window.py`, add these methods next to `_on_view_inputs`:

```python
    def _input_row_for_drop(self):
        """Resolve the visible tab's input row, or ``None`` when not routable."""
        from core.audio_tools import DUAL_INPUT_TOOLS

        tab = self.content_stack.get_visible_child_name()
        tool = (
            self._audio_tools_page._current_tool()
            if tab == "audio_tools"
            else None
        )
        name = drop_target_row_name(tab, tool, DUAL_INPUT_TOOLS)
        if name == "separation":
            return self.input_row
        if name == "ensemble":
            return self._ensemble_page.input_row
        if name == "audio_tools":
            return self._audio_tools_page.inputs_row
        return None

    def _on_window_drop(self, _target, value, _x, _y) -> bool:
        row = self._input_row_for_drop()
        if row is None:
            return False
        # Delegate to the row's own handler so path expansion, the accept-any
        # setting, dedupe and the toasts all stay in one place.
        return row._on_drop(_target, value, _x, _y)
```

Then wire the controller where the overlay root is built (after line 212):

```python
        window_drop = Gtk.DropTarget.new(Gdk.FileList, Gdk.DragAction.COPY)
        window_drop.connect("drop", self._on_window_drop)
        root.add_controller(window_drop)
```

Add `Gdk` to the `gi.repository` import at line 30:

```python
from gi.repository import Adw, Gdk, Gio, Gtk
```

The per-row `Gtk.DropTarget`s stay: GTK dispatches to the innermost controller first, so dropping directly on a file row still hits that row (and keeps its `.drop-highlight` feedback), while the window target only catches drops that miss every row.

- [ ] **Step 6: Confirm the row attribute names are right**

Run: `rg -n 'self\.input_row|self\.inputs_row' ui/ensemble/window.py ui/audio_tools/window.py`
Expected: confirms `EnsemblePage.input_row` and `AudioToolsPage.inputs_row`. Correct `_input_row_for_drop` if either differs.

- [ ] **Step 7: Smoke-test**

Run: `python -m ui`
Drag an audio file onto the middle of the options area on each tab.
Expected: Separation / Ensemble / single-input Audio Tools accept it and the input row updates; a dual-input tool ignores the drop except on the pair rows themselves.

- [ ] **Step 8: Run the suite**

Run: `.venv/bin/python -m unittest discover -s tests -v`
Expected: PASS

- [ ] **Step 9: Commit**

```bash
git add ui/window.py tests/test_window_drop_routing.py
git commit -m "feat(ui): accept dropped audio anywhere in the window"
```

---

## Final verification

- [ ] **Run the whole suite**

Run: `.venv/bin/python -m unittest discover -s tests -v`
Expected: PASS, zero failures, zero errors.

- [ ] **Type check**

Run: `.venv/bin/python -m pyright` (skip if pyright is not installed)
Expected: no new errors in `ui/`.

- [ ] **Full manual pass**

Run: `python -m ui` and walk through: pick 5 inputs → remove one (list stays open) → run a separation (progress collapses ~5s after "Done") → switch format to MP3 and confirm the bitrate dropdown follows → turn GPU conversion off (FP16 dims) → open Model options and confirm the secondary/pre-process/vocal-split rows dim with their Activate switches → open Settings (no Audio page, no GPU/FP16 duplicates; toggling a switch does not stall the window).

- [ ] **Push the branch to Codeberg**

```bash
git push -u origin <branch-name>
```

Do **not** push to the `github` remote — it is a Codeberg-maintained mirror.
