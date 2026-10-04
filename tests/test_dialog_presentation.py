"""Backdrop dismissal follows the dialog's kind.

Live, info and pick-one dialogs close on a backdrop click; commit dialogs
ignore it so a stray click cannot discard edits. Each dialog owns its own
"dimming" widget, so a dialog stacked over another must get its own handler.
"""

from __future__ import annotations

import os
import time
import unittest
from collections.abc import Callable
from typing import Any
from unittest import mock


def _descendants(widget: Any):
    yield widget
    child = widget.get_first_child()
    while child is not None:
        yield from _descendants(child)
        child = child.get_next_sibling()


def _backdrop(dialog: Any) -> Any:
    return next(w for w in _descendants(dialog) if w.get_css_name() == "dimming")


def _click(dimming: Any) -> None:
    from gi.repository import Gtk

    controllers = dimming.observe_controllers()
    for index in range(controllers.get_n_items()):
        controller = controllers.get_item(index)
        if isinstance(controller, Gtk.GestureClick):
            controller.emit("released", 1, 0.0, 0.0)
            return
    raise AssertionError("no backdrop gesture")


@unittest.skipUnless(
    os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"),
    "GTK widget construction needs a display",
)
class BackdropDismissTests(unittest.TestCase):
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
        from gi.repository import Adw

        from tests.gtk_layout_helpers import resize_window

        self.parent = Adw.Window()
        resize_window(self.parent, 900, 700)
        self.addCleanup(self.parent.close)
        self.closed: list[Any] = []

    def _dialog(self) -> Any:
        from gi.repository import Adw, Gtk

        dialog = Adw.Dialog(content_width=400, content_height=300)
        dialog.set_child(Gtk.Label(label="content"))
        dialog.connect("closed", self.closed.append)
        self.addCleanup(dialog.force_close)
        return dialog

    def _spin(self, seconds: float = 0.1) -> None:
        from gi.repository import GLib

        end = time.monotonic() + seconds
        while time.monotonic() < end:
            GLib.MainContext.default().iteration(False)
            time.sleep(0.005)

    def wait_for(self, predicate: Callable[[], bool]) -> None:
        from gi.repository import GLib

        deadline = time.monotonic() + 5
        while not predicate():
            self.assertLess(time.monotonic(), deadline)
            GLib.MainContext.default().iteration(False)
            time.sleep(0.005)

    def test_backdrop_click_closes_live_dialog(self) -> None:
        from tests.gtk_layout_helpers import wait_for_dialog_open
        from ui.dialogs.utils import present_modal_dialog

        dialog = self._dialog()
        present_modal_dialog(dialog, self.parent)
        wait_for_dialog_open(dialog)
        self._spin()
        _click(_backdrop(dialog))
        self.wait_for(lambda: self.closed == [dialog])

    def test_stacked_backdrop_closes_only_the_top_dialog(self) -> None:
        from tests.gtk_layout_helpers import wait_for_dialog_open
        from ui.dialogs.utils import present_modal_dialog
        from ui.widget_state import fetch

        lower, upper = self._dialog(), self._dialog()
        present_modal_dialog(lower, self.parent)
        wait_for_dialog_open(lower)
        present_modal_dialog(upper, self.parent)
        wait_for_dialog_open(upper)
        self._spin()
        self.assertIs(fetch(_backdrop(upper), "_uvr_backdrop_dialog", None), upper)
        _click(_backdrop(upper))
        self.wait_for(lambda: self.closed == [upper])
        self._spin(0.3)
        self.assertEqual(self.closed, [upper])
        self.assertTrue(lower.get_mapped())

    def test_backdrop_handler_is_ready_when_present_returns(self) -> None:
        # The dimming widget exists once present() returns; installing from an
        # idle callback left a window where a busy main loop delayed it.
        from ui.dialogs.utils import present_modal_dialog
        from ui.widget_state import fetch

        dialog = self._dialog()
        present_modal_dialog(dialog, self.parent)
        self.assertIs(fetch(_backdrop(dialog), "_uvr_backdrop_dialog", None), dialog)

    def test_backdrop_install_retries_when_dimming_is_late(self) -> None:
        # Should a libadwaita build create the dimming widget lazily, the
        # handler is installed on the next idle instead of being skipped.
        import ui.dialogs.utils as utils
        from ui.widget_state import fetch

        real = utils._find_dimming_widget
        calls: list[int] = []

        def late(root: Any) -> Any:
            calls.append(1)
            return None if len(calls) == 1 else real(root)

        dialog = self._dialog()
        with mock.patch.object(utils, "_find_dimming_widget", side_effect=late):
            utils.present_modal_dialog(dialog, self.parent)
            self.wait_for(lambda: len(calls) > 1)
        self.assertIs(fetch(_backdrop(dialog), "_uvr_backdrop_dialog", None), dialog)

    def test_commit_dialog_ignores_backdrop(self) -> None:
        from tests.gtk_layout_helpers import wait_for_dialog_open
        from ui.dialogs.utils import present_modal_dialog
        from ui.widget_state import fetch

        dialog = self._dialog()
        present_modal_dialog(dialog, self.parent, dismiss_on_backdrop=False)
        wait_for_dialog_open(dialog)
        self._spin()
        self.assertIsNone(fetch(_backdrop(dialog), "_uvr_backdrop_dialog", None))


@unittest.skipUnless(
    os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"),
    "GTK widget construction needs a display",
)
class DialogKindWiringTests(unittest.TestCase):
    """Each opener passes its kind's backdrop behaviour to the shared helper."""

    @classmethod
    def setUpClass(cls) -> None:
        from tests.private_gtk import require_private_gtk

        require_private_gtk()
        import gi

        gi.require_version("Gtk", "4.0")
        gi.require_version("Adw", "1")
        from gi.repository import Adw

        cls.app = Adw.Application(application_id="org.uvr.test.dialog-presentation")
        cls.app.register()

    def setUp(self) -> None:
        from gi.repository import Adw

        self.parent = Adw.ApplicationWindow(application=self.app)
        self.addCleanup(self.parent.set_application, None)

    def assert_backdrop(self, present: mock.Mock, expected: bool) -> None:
        present.assert_called_once()
        self.assertEqual(present.call_args.kwargs.get("dismiss_on_backdrop", True), expected)

    def test_input_pairs_ignores_backdrop(self) -> None:
        from ui.audio_tools.dual_batch import DualBatchDialog

        with mock.patch("ui.audio_tools.dual_batch.present_modal_dialog") as present:
            DualBatchDialog(self.parent, ("File 1", "File 2"), [], lambda _p: None).present()
        self.assert_backdrop(present, False)

    def test_blend_options_ignores_backdrop(self) -> None:
        from core.settings import Settings
        from ui.ensemble.blend_dialog import show_blend_dialog

        with mock.patch("ui.ensemble.blend_dialog.present_modal_dialog") as present:
            show_blend_dialog(self.parent, Settings.defaults(), [], lambda _o: None)
        self.assert_backdrop(present, False)

    def test_parameter_forms_ignore_backdrop(self) -> None:
        from gi.repository import Adw, GLib, Gtk

        from ui.dialogs.utils import run_blocking_dialog

        with (
            mock.patch("ui.dialogs.utils.present_modal_dialog") as present,
            mock.patch.object(GLib, "MainLoop"),
        ):
            run_blocking_dialog(Adw.Dialog(), self.parent, content=Gtk.Label())
        self.assert_backdrop(present, False)

    def test_review_plan_ignores_backdrop(self) -> None:
        from tests.test_plan_review import resolved_plan
        from ui.run_control import RunController

        controller = RunController(mock.Mock(dialog_parent=self.parent))
        controller._operation_id = "current"
        with mock.patch("ui.run_control.present_modal_dialog") as present:
            controller._present_plan_confirmation(mock.Mock(), "fingerprint", resolved_plan())
        self.assert_backdrop(present, False)

    def test_choose_model_closes_on_backdrop(self) -> None:
        from core.model_repository import ModelRepository
        from ui.model_picker import ModelPicker

        with mock.patch("core.model_identity.ModelIdentityService.records", return_value=()):
            picker = ModelPicker(ModelRepository(), lambda: "", mock.Mock(), mock.Mock())
            with mock.patch("ui.model_picker.present_modal_dialog") as present:
                picker.present(self.parent)
        self.assert_backdrop(present, True)

    def test_about_closes_on_backdrop(self) -> None:
        from ui.about import open_about

        with mock.patch("ui.about.present_modal_dialog") as present:
            open_about(self.parent)
        self.assert_backdrop(present, True)

    def test_shortcuts_close_on_backdrop(self) -> None:
        from gi.repository import Adw

        from ui.shortcuts import present_shortcuts

        if not hasattr(Adw, "ShortcutsDialog"):
            self.skipTest("libadwaita has no ShortcutsDialog")
        with mock.patch("ui.shortcuts.present_modal_dialog") as present:
            present_shortcuts(self.parent)
        self.assert_backdrop(present, True)

    def test_settings_close_on_backdrop(self) -> None:
        from ui.window import MainWindow

        # A stub host: building a real MainWindow here makes a later
        # test_output_stems run crash inside GTK (it does so on the base commit
        # too, with test_control_types), and the wiring is all this test checks.
        host = mock.Mock()
        with (
            mock.patch("ui.preferences.PreferencesDialog") as dialog_class,
            mock.patch("ui.window.present_modal_dialog") as present,
        ):
            MainWindow._on_open_settings(host, mock.Mock(), None)
        self.assert_backdrop(present, True)
        self.assertEqual(present.call_args.args, (dialog_class.return_value, host))


if __name__ == "__main__":
    unittest.main()
