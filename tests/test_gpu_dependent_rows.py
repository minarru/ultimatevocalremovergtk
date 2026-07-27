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
