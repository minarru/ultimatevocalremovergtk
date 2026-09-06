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
from typing import Any

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
        from core.settings import Settings
        from ui.widgets.file_chooser import InputFilesRow, OutputFolderRow
        from ui.widgets.format_row import OutputFormatRow
        from ui.widgets.rows import make_switch_row
        from ui.widgets.vocal_split_row import VocalSplitRow
        from ui.window import MainWindow

        window: Any = MainWindow.__new__(MainWindow)
        window.settings = Settings.defaults()
        window.content_stack = _StubContentStack(visible_tab)

        stub_view = _StubView()
        window._views = [stub_view]
        window._current_view = stub_view

        window.input_row = InputFilesRow(lambda: None)
        window.output_row = OutputFolderRow(lambda: None)
        # The stale Separation-page format row: still on the WAV/PCM_16
        # defaults, as it would be if the user never revisited Separation
        # after switching to another tab.
        window._shared_session = None
        window.format_row = OutputFormatRow(window._on_format_changed)
        window.format_row.apply_from_settings(window.settings)
        window.gpu_row = make_switch_row("GPU conversion")
        window.autocast_row = make_switch_row("FP16 autocast")
        window.sample_row = make_switch_row("Sample mode")
        # Leave these switch signals disconnected to exercise defensive flush.
        window.vocal_split_row = VocalSplitRow(None, lambda _event: None)
        window._install_shared_session()
        from ui.shared_settings import SharedSettingsSession
        assert isinstance(window._shared_session, SharedSettingsSession)
        window._shared_session.refresh(lambda: None)
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
        # Same for the vocal-split row: a regression that dropped its
        # ``persist_to_settings`` call from inside the "separation" guard
        # would leave this at the settings default and go uncaught by the
        # format-only assertion below.
        window.vocal_split_row.split_switch.set_active(True)

        MainWindow._flush_settings(window)

        self.assertEqual(window.settings.get("wav_type_set"), "PCM_24")
        self.assertTrue(window.settings.get("is_set_vocal_splitter"))



@unittest.skipUnless(
    os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"),
    "GTK widget construction needs a display",
)
class ConnectedSharedSettingsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from tests.private_gtk import require_private_gtk
        require_private_gtk()
        from gi.repository import Adw
        cls.app = Adw.Application(application_id="org.uvr.test.shared-sessions")
        cls.app.register()

    def setUp(self):
        import tempfile
        from unittest.mock import patch

        from core.settings import Settings
        from ui.window import MainWindow
        self.settings = Settings.defaults()
        self.settings.process.save_format = self.SaveFormat.WAV
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        with patch.object(Settings, "load", return_value=self.settings):
            self.window = MainWindow()
        self.addCleanup(self.window.set_visible, False)
        self.addCleanup(self.window._unsubscribe_model_events)
        # Keep the real close/save path, but direct persistence to a test file.
        save = self.settings.save
        self.saved_path = os.path.join(self.tmp.name, "settings.json")
        self.save_patch = patch.object(self.settings, "save", side_effect=lambda: save(self.saved_path))
        self.save_patch.start()
        self.addCleanup(self.save_patch.stop)

    from core.types import SaveFormat

    def test_ensemble_callbacks_activation_and_close_preserve_edits(self):
        from core.settings import Settings
        from core.types.settings_enums import WavType
        from ui.widgets.format_row import quality_spec
        window = self.window
        window.content_stack.set_visible_child_name("ensemble")
        page = window._ensemble_page
        page.format_row._select_quality_value("PCM_24", quality_spec("WAV"))
        page.gpu_row.set_active(True)
        page.autocast_row.set_active(True)
        page.sample_row.set_active(True)
        self.settings.process.vocal_splitter = "vr:unavailable-newer"
        page.vocal_split_row.split_switch.set_active(True)
        page.vocal_split_row.save_inst_switch.set_active(True)
        page.vocal_split_row.deverb_switch.set_active(True)
        self.assertIs(self.settings.process.wav_type, WavType.PCM_24)
        self.assertTrue(self.settings.process.use_gpu)
        self.assertEqual(self.settings.process.vocal_splitter, "vr:unavailable-newer")
        window._finalize_close(False)
        saved = Settings.load(self.saved_path)
        self.assertIs(saved.process.wav_type, WavType.PCM_24)
        self.assertTrue(saved.process.use_gpu)
        self.assertTrue(saved.process.autocast)
        self.assertTrue(saved.process.sample_mode)
        self.assertTrue(saved.process.vocal_splitter_enabled)
        self.assertTrue(saved.process.save_inst_vocal_splitter)
        self.assertTrue(saved.process.deverb_vocals)
        self.assertEqual(saved.process.vocal_splitter, "vr:unavailable-newer")
        window.content_stack.set_visible_child_name("separation")
        self.assertEqual(window.format_row.quality_value, "PCM_24")
        self.assertTrue(window.gpu_row.get_active())
        self.assertTrue(window.sample_row.get_active())
        self.assertTrue(window.vocal_split_row.deverb_switch.get_active())

    def test_audio_callbacks_close_and_switch_back(self):
        from core.settings import Settings
        from core.types.settings_enums import OpusBitrate
        from ui.widgets.format_row import quality_spec
        window = self.window
        window.content_stack.set_visible_child_name("audio_tools")
        page = window._audio_tools_page
        page.format_row.set_save_format("OPUS")
        page.format_row._select_quality_value("256k", quality_spec("OPUS"))
        page.apollo_gpu_row.set_active(True)
        self.assertIs(self.settings.process.save_format, self.SaveFormat.OPUS)
        self.assertIs(self.settings.process.opus_bitrate, OpusBitrate.K256)
        self.assertTrue(self.settings.process.use_gpu)
        window._finalize_close(False)
        saved = Settings.load(self.saved_path)
        self.assertIs(saved.process.save_format, self.SaveFormat.OPUS)
        self.assertIs(saved.process.opus_bitrate, OpusBitrate.K256)
        self.assertTrue(saved.process.use_gpu)
        window.content_stack.set_visible_child_name("separation")
        self.assertEqual(window.format_row.save_format, "OPUS")
        self.assertEqual(window.format_row.quality_value, "256k")
        self.assertTrue(window.gpu_row.get_active())

    def test_refresh_and_inactive_connected_callbacks_cannot_persist(self):
        from unittest.mock import patch
        window = self.window
        window.content_stack.set_visible_child_name("ensemble")
        page = window._ensemble_page
        # An inactive surface cannot write even when notify signals arrive.
        window.gpu_row.set_active(True)
        window.sample_row.set_active(True)
        window.format_row.set_save_format("MP3")
        window.vocal_split_row.deverb_switch.set_active(True)
        self.assertFalse(self.settings.process.use_gpu)
        self.assertFalse(self.settings.process.sample_mode)
        self.assertFalse(self.settings.process.deverb_vocals)
        self.assertIs(self.settings.process.save_format, self.SaveFormat.WAV)
        # Active refresh may emit switch signals; metadata work must stay suppressed.
        self.settings.process.use_gpu = True
        self.settings.process.sample_mode = True
        with patch.object(page, "_update_stems_group_metadata") as metadata:
            page._sync_shared_from_settings()
        metadata.assert_not_called()
        self.settings.process.use_gpu = False
        page._flush_run_settings()
        self.assertFalse(self.settings.process.use_gpu)
        window.content_stack.set_visible_child_name("separation")
        self.assertFalse(window.gpu_row.get_active())
        self.assertTrue(window.sample_row.get_active())
        self.assertFalse(window.vocal_split_row.deverb_switch.get_active())
        self.assertEqual(window.format_row.save_format, "WAV")

    def test_verify_inputs_retains_global_authority_on_another_tab(self):
        from pathlib import Path
        window = self.window
        path = str(Path(self.tmp.name) / "input.wav")
        Path(path).touch()
        window.context.set_unreadable_input_paths([path, "/old.wav"])
        window.content_stack.set_visible_child_name("ensemble")
        window._on_external_inputs_changed([path])
        self.assertEqual(self.settings.process.input_paths, [path])
        self.assertEqual(window.context.unreadable_input_paths, {path})
        self.assertEqual(window.input_row.paths, [path])
        # External update is adopted; a newer global edit cannot be replayed.
        self.settings.process.input_paths = []
        window._flush_settings()
        self.assertEqual(self.settings.process.input_paths, [])

    def test_audio_spec_and_start_flush_pending_shared_edits(self):
        from unittest.mock import Mock, patch
        window = self.window
        window.content_stack.set_visible_child_name("audio_tools")
        page = window._audio_tools_page
        # Use notify=False to exercise defensive preflight capture, not a mock session.
        page.output_row.set_path(self.tmp.name, notify=False)
        spec = page.build_job_spec()
        self.assertEqual(spec.settings.process.export_path, self.tmp.name)
        self.assertEqual(self.settings.process.export_path, self.tmp.name)
        second = os.path.join(self.tmp.name, "second")
        os.mkdir(second)
        page.output_row.set_path(second, notify=False)
        observed = []
        page._runner = Mock()
        page._runner.start.side_effect = lambda *_args, **_kw: observed.append(self.settings.process.export_path)
        with patch.object(window, "begin_run"):
            page.start(Mock())
        self.assertEqual(observed, [second])
        self.assertEqual(self.settings.process.export_path, second)

if __name__ == "__main__":
    unittest.main()
