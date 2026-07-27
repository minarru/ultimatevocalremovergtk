"""``_finalize_close`` must not clobber another tab's shared settings.

``MainWindow._flush_settings`` always ran (via ``_finalize_close``) on window
close, unconditionally pushing the Separation page's format/quality/GPU/
autocast/sample-mode widgets into settings. Those widgets are only kept in
sync with settings while Separation is the visible tab (see
``_activate_separation`` / ``_sync_shared_from_settings``); while Ensemble or
Audio Tools is visible they go stale. Closing the app from another tab would
silently revert whatever format/quality choice the user just made there back
to the last value Separation happened to hold.
"""

from __future__ import annotations

import os
import unittest

from bundled.constants import WAV


class _StubView:
    """Minimal per-view stand-in: only ``save`` / ``method_key`` are touched."""

    method_key = "VR Architecture"

    def __init__(self):
        self.save_calls = []

    def save(self, *, include_stem_only: bool = True) -> None:
        self.save_calls.append(include_stem_only)


class _StubContentStack:
    """Stands in for ``Adw.ViewStack``; only ``get_visible_child_name`` is used."""

    def __init__(self, visible_child_name: str) -> None:
        self._name = visible_child_name

    def get_visible_child_name(self) -> str:
        return self._name


@unittest.skipUnless(
    os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"),
    "GTK widget construction needs a display",
)
class FlushSettingsTabGuardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        import gi

        gi.require_version("Gtk", "4.0")
        gi.require_version("Adw", "1")
        from gi.repository import Adw

        cls._app = Adw.Application(application_id="org.uvr.test.flush-settings-tab-guard")
        cls._app.register()

    def _window(self, *, visible_tab: str):
        """A bare MainWindow with only the widgets ``_flush_settings`` touches."""
        from core.settings import SettingsModel
        from ui.widgets.file_chooser import InputFilesRow, OutputFolderRow
        from ui.widgets.format_row import OutputFormatRow
        from ui.widgets.rows import make_switch_row
        from ui.window import MainWindow

        window = MainWindow.__new__(MainWindow)
        window.settings = SettingsModel()
        window.content_stack = _StubContentStack(visible_tab)

        stub_view = _StubView()
        window._views = [stub_view]
        window._current_view = stub_view

        window.input_row = InputFilesRow(lambda: None)
        window.output_row = OutputFolderRow(lambda: None)
        # The stale Separation-page format row: still on the WAV/PCM_16
        # defaults, as it would be if the user never revisited Separation
        # after switching to another tab.
        window.format_row = OutputFormatRow(lambda: None)
        window.format_row.apply_from_settings(window.settings)
        window.gpu_row = make_switch_row("GPU conversion")
        window.autocast_row = make_switch_row("FP16 autocast")
        window.sample_row = make_switch_row("Sample mode")
        return window

    def test_ensemble_edit_survives_close_while_ensemble_visible(self):
        window = self._window(visible_tab="ensemble")
        # Simulate an edit made on the Ensemble tab's own (separate) format
        # row: the shared setting key changes, but the stale Separation
        # ``format_row`` still holds PCM_16.
        window.settings.set("save_format", WAV)
        window.settings.set("wav_type_set", "PCM_24")

        from ui.window import MainWindow

        MainWindow._flush_settings(window)

        self.assertEqual(
            window.settings.get("wav_type_set"),
            "PCM_24",
            "closing while Ensemble is visible must not revert the quality "
            "choice made there back to the stale Separation row's value",
        )

    def test_audio_tools_edit_survives_close_while_audio_tools_visible(self):
        from bundled.constants import MP3

        window = self._window(visible_tab="audio_tools")
        # Simulate an edit made on the Audio Tools tab's own format row.
        window.settings.set("save_format", MP3)

        from ui.window import MainWindow

        MainWindow._flush_settings(window)

        self.assertEqual(
            window.settings.get("save_format"),
            MP3,
            "closing while Audio Tools is visible must not revert the "
            "format choice made there back to the stale Separation row's "
            "WAV default",
        )

    def test_separation_visible_still_flushes_its_own_widgets(self):
        from ui.widgets.format_row import quality_spec
        from ui.window import MainWindow

        window = self._window(visible_tab="separation")
        window.format_row.set_save_format(WAV)
        # Drive the row's quality dropdown to PCM_24 directly (as the user
        # interacting with the live Separation row would), then flush while
        # Separation is the visible tab: this must still persist normally.
        window.format_row._select_quality_value("PCM_24", quality_spec(WAV))

        MainWindow._flush_settings(window)

        self.assertEqual(window.settings.get("wav_type_set"), "PCM_24")


if __name__ == "__main__":
    unittest.main()
