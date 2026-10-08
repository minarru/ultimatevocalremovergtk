"""The Sample mode row opens one trim dialog and applies its edits to settings."""

from __future__ import annotations

import os
import unittest
from typing import Any, Mapping
from unittest import mock

from core.settings import Settings


@unittest.skipUnless(
    os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"),
    "GTK widget construction needs a display",
)
class SampleRangeControllerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        from tests.private_gtk import require_private_gtk

        require_private_gtk()
        import gi

        gi.require_version("Gtk", "4.0")
        gi.require_version("Adw", "1")
        from gi.repository import Adw

        Adw.init()

    def setUp(self) -> None:
        self.settings = Settings.defaults()
        self.settings.process.sample_mode_duration = 30
        self.settings.process.input_paths = ["/in/a.wav", "/in/b.wav"]
        self.save = mock.Mock(return_value=None)
        self.toast = mock.Mock()
        self.applied = mock.Mock()
        self.TrimDialog = self._patch("ui.sample_range.TrimDialog")
        self._patch("ui.playback.engine.PlaybackEngine")
        self._patch("ui.playback.waveforms.WaveformLoader")

    def _patch(self, target: str) -> mock.MagicMock:
        patcher = mock.patch(target)
        self.addCleanup(patcher.stop)
        return patcher.start()

    def _controller(self) -> Any:
        from ui.sample_range import SampleRangeController

        return SampleRangeController(
            lambda: self.settings,
            parent=lambda: None,
            save=self.save,
            toast=self.toast,
            on_applied=self.applied,
        )

    def _kwargs(self) -> Mapping[str, Any]:
        return self.TrimDialog.call_args.kwargs

    def test_open_builds_one_dialog_from_settings(self) -> None:
        self.settings.ui.listening_in_window = True
        controller = self._controller()
        controller.open(["/in/a.wav"])
        controller.open(["/in/a.wav"])
        self.TrimDialog.assert_called_once()
        self.assertEqual(self.TrimDialog.return_value.present.call_count, 2)
        kwargs = self._kwargs()
        self.assertEqual(kwargs["duration"], 30)
        self.assertIs(kwargs["starts"], self.settings.process.sample_starts)
        self.assertIs(kwargs["open_in_window"], True)
        self.assertEqual(self.TrimDialog.call_args.args[0], ["/in/a.wav"])

    def test_apply_writes_saves_and_notifies(self) -> None:
        a, b = os.path.abspath("/in/a.wav"), os.path.abspath("/in/b.wav")
        self.settings.process.sample_starts = {b: 4.0}
        controller = self._controller()
        controller.open(["/in/a.wav", "/in/b.wav"])
        self._kwargs()["on_apply"]({a: 12.5, b: None})
        self.assertEqual(self.settings.process.sample_starts, {a: 12.5})
        self.save.assert_called_once_with()
        self.applied.assert_called_once_with()
        self.toast.assert_not_called()

    def test_save_error_is_toasted(self) -> None:
        self.save.return_value = "Could not save settings"
        controller = self._controller()
        controller.open(["/in/a.wav"])
        self._kwargs()["on_apply"]({os.path.abspath("/in/a.wav"): 3.0})
        self.toast.assert_called_once_with("Could not save settings")

    def test_apply_drops_edits_for_removed_inputs(self) -> None:
        self.settings.process.input_paths = ["/in/a.wav"]
        controller = self._controller()
        controller.open(["/in/a.wav"])
        self._kwargs()["on_apply"]({os.path.abspath("/in/gone.wav"): 9.0})
        self.assertEqual(self.settings.process.sample_starts, {})

    def test_closed_dialog_is_rebuilt_on_next_open(self) -> None:
        controller = self._controller()
        controller.open(["/in/a.wav"])
        self._kwargs()["on_closed"]()
        controller.open(["/in/a.wav"])
        self.assertEqual(self.TrimDialog.call_count, 2)

    def test_close_closes_the_open_dialog(self) -> None:
        controller = self._controller()
        controller.open(["/in/a.wav"])
        controller.close()
        self.TrimDialog.return_value.close.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
