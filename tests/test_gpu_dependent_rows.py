"""FP16 autocast is only meaningful when GPU conversion is on."""

from __future__ import annotations

import os
import unittest
from unittest.mock import Mock

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

    def _window(self, *, gpu_on: bool, ensemble: bool = False):
        """A bare MainWindow with only the two rows the sync method touches.

        Constructing a real MainWindow would build the whole AppContext, read
        ``data.pkl`` and spawn the download-queue UI — far too much for a
        sensitivity check.
        """
        from gi.repository import Adw

        from ui.ensemble.window import EnsemblePage
        from ui.window import MainWindow

        page_type = EnsemblePage if ensemble else MainWindow
        window = page_type.__new__(page_type)
        window.gpu_row = Adw.SwitchRow(title="GPU conversion")
        window.gpu_row.set_active(gpu_on)
        window.autocast_row = Adw.SwitchRow(title="FP16 autocast")
        return window

    def test_autocast_dimmed_when_gpu_off(self):
        window = self._window(gpu_on=False)
        window._sync_gpu_dependent_rows()
        self.assertFalse(window.autocast_row.get_sensitive())

    def test_autocast_editable_when_gpu_on(self):
        window = self._window(gpu_on=True)
        window._sync_gpu_dependent_rows()
        self.assertTrue(window.autocast_row.get_sensitive())

    def test_gpu_toggle_explains_dependency_without_clearing_saved_autocast(self):
        for ensemble in (False, True):
            with self.subTest(ensemble=ensemble):
                window = self._window(gpu_on=False, ensemble=ensemble)
                window.autocast_row.set_active(True)
                window._sync_gpu_dependent_rows()
                self.assertFalse(window.autocast_row.get_sensitive())
                self.assertEqual(
                    window.autocast_row.get_subtitle(),
                    "Enable GPU conversion to use FP16 autocast.",
                )
                self.assertTrue(window.autocast_row.get_active())
                window.gpu_row.set_active(True)
                window._sync_gpu_dependent_rows()
                self.assertTrue(window.autocast_row.get_sensitive())
                self.assertEqual(
                    window.autocast_row.get_subtitle(),
                    "Faster VR/MDX/Roformer on modern NVIDIA GPUs",
                )
                self.assertTrue(window.autocast_row.get_active())

    def test_device_detection_preserves_disabled_explanation_and_selection(self):
        from gi.repository import Adw

        from core.settings import Settings
        from ui.lifetime import UiLifetime
        from ui.preferences import PreferencesDialog
        from ui.widgets.rows import configure_combo_row, get_combo_value, set_combo_value

        dialog = PreferencesDialog.__new__(PreferencesDialog)
        dialog.settings = Settings()
        dialog.settings.process.use_gpu = False
        dialog.settings.process.device = "0"
        dialog._lifetime = UiLifetime()
        dialog._loading = False
        dialog._persist = Mock()
        dialog.device_row = configure_combo_row(Adw.ComboRow(title="GPU device"), ["Default", "0"])
        set_combo_value(dialog.device_row, "0")
        dialog.device_row.connect("notify::selected", dialog._on_combo_changed, "device_set")
        before = dialog.settings.to_json_dict()
        dialog._device_detection_subtitle = "Detecting…"
        dialog._sync_gpu_device_row()
        self.assertFalse(dialog.device_row.get_sensitive())
        self.assertEqual(
            dialog.device_row.get_subtitle(),
            "Enable GPU conversion on Separation or Ensemble to choose a device.\nDetecting…",
        )
        for devices, detection in (
            ([("0", "Test GPU")], "Detected: 0: Test GPU"),
            ([], "No GPU detected"),
        ):
            with self.subTest(devices=devices):
                dialog._apply_gpu_devices(devices)
                self.assertEqual(
                    dialog.device_row.get_subtitle(),
                    "Enable GPU conversion on Separation or Ensemble to choose a device.\n"
                    + detection,
                )
                self.assertEqual(get_combo_value(dialog.device_row), "0")
                self.assertEqual(dialog.settings.to_json_dict(), before)
                dialog._persist.assert_not_called()
                dialog.settings.process.use_gpu = True
                dialog._sync_gpu_device_row()
                self.assertTrue(dialog.device_row.get_sensitive())
                self.assertEqual(dialog.device_row.get_subtitle(), detection)
                dialog.settings.process.use_gpu = False
                dialog._sync_gpu_device_row()


if __name__ == "__main__":
    unittest.main()
