"""Commit dialogs: Cancel at the header start, the action at the end, no close button.

Closing a commit dialog by any route (Cancel, Escape) discards its edits.
"""

from __future__ import annotations

import os
import time
import unittest
from collections.abc import Callable, Iterator
from types import SimpleNamespace
from typing import Any


def _descendants(widget: Any) -> Iterator[Any]:
    yield widget
    child = widget.get_first_child()
    while child is not None:
        yield from _descendants(child)
        child = child.get_next_sibling()


def _header(dialog: Any) -> Any:
    from gi.repository import Adw

    return next(w for w in _descendants(dialog) if isinstance(w, Adw.HeaderBar))


def _button(dialog: Any, label: str) -> Any:
    from gi.repository import Gtk

    return next(
        w for w in _descendants(dialog) if isinstance(w, Gtk.Button) and w.get_label() == label
    )


@unittest.skipUnless(
    os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"),
    "GTK widget construction needs a display",
)
class CommitDialogActionTests(unittest.TestCase):
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

    def wait_for(self, predicate: Callable[[], bool]) -> None:
        from gi.repository import GLib

        deadline = time.monotonic() + 5
        while not predicate():
            self.assertLess(time.monotonic(), deadline)
            GLib.MainContext.default().iteration(False)
            time.sleep(0.005)

    def _form(self) -> Any:
        from gi.repository import Adw, Gtk

        from ui.dialogs.utils import present_modal_dialog, set_form_dialog_content

        dialog = Adw.Dialog()
        set_form_dialog_content(dialog, Gtk.Label(label="form"), on_save=lambda: None)
        present_modal_dialog(dialog, self.parent, dismiss_on_backdrop=False)
        return dialog

    def _input_pairs(self) -> Any:
        from ui.audio_tools.dual_batch import DualBatchDialog

        editor = DualBatchDialog(self.parent, ("File 1", "File 2"), [], lambda _p: None)
        editor.present()
        return editor.dialog

    def _blend(self, received: list[Any]) -> Any:
        from core.settings import Settings
        from core.stem_roles import StemRoleId
        from ui.ensemble.blend_dialog import show_blend_dialog

        route = SimpleNamespace(role=StemRoleId("vocal.vocals"), label="Vocals")
        self.settings = Settings.defaults()
        return show_blend_dialog(
            self.parent, self.settings, [("mdx:a", "Model A", [route])], received.append
        )

    def _assert_commit_header(self, dialog: Any, action_label: str) -> None:
        from gi.repository import Graphene

        from tests.gtk_layout_helpers import wait_for_dialog_open

        self.addCleanup(dialog.force_close)
        wait_for_dialog_open(dialog)
        header = _header(dialog)
        self.assertFalse(header.get_show_start_title_buttons())
        self.assertFalse(header.get_show_end_title_buttons())
        cancel, action = _button(dialog, "Cancel"), _button(dialog, action_label)
        ok, point = cancel.compute_point(action, Graphene.Point())
        self.assertTrue(ok)
        self.assertLess(point.x, 0)
        self.assertTrue(action.has_css_class("suggested-action"))

    def test_form_header_has_cancel_start_save_end_and_no_close(self) -> None:
        self._assert_commit_header(self._form(), "Save")

    def test_input_pairs_header_has_cancel_start_save_end_and_no_close(self) -> None:
        self._assert_commit_header(self._input_pairs(), "Save")

    def test_blend_header_has_cancel_start_apply_end_and_no_close(self) -> None:
        self._assert_commit_header(self._blend([]), "Apply")

    def test_form_cancel_closes_without_saving(self) -> None:
        from gi.repository import Adw, GLib, Gtk

        from tests.gtk_layout_helpers import wait_for_dialog_open
        from ui.dialogs.utils import run_blocking_dialog

        dialog = Adw.Dialog()

        def cancel() -> bool:
            wait_for_dialog_open(dialog)
            _button(dialog, "Cancel").emit("clicked")
            return GLib.SOURCE_REMOVE

        def give_up() -> bool:
            # Without a working Cancel the blocking loop would never end.
            missed.append(True)
            dialog.force_close()
            return GLib.SOURCE_REMOVE

        missed: list[bool] = []
        GLib.timeout_add(20, cancel)
        fallback = GLib.timeout_add(3000, give_up)
        result = run_blocking_dialog(
            dialog, self.parent, content=Gtk.Label(label="form"), collect=lambda: {"saved": True}
        )
        if not missed:
            GLib.source_remove(fallback)
        self.assertEqual(missed, [])
        self.assertIsNone(result)

    def _edit_blend(self, received: list[Any]) -> Any:
        from gi.repository import Adw

        from tests.gtk_layout_helpers import wait_for_dialog_open

        dialog = self._blend(received)
        self.addCleanup(dialog.force_close)
        wait_for_dialog_open(dialog)
        weight = next(
            w
            for w in _descendants(dialog)
            if isinstance(w, Adw.SpinRow) and w.get_title() == "Model A"
        )
        weight.set_value(2.5)
        closed: list[bool] = []
        dialog.connect("closed", lambda *_: closed.append(True))
        return dialog, closed

    def test_cancel_discards_blend_edits(self) -> None:
        received: list[Any] = []
        dialog, closed = self._edit_blend(received)
        _button(dialog, "Cancel").emit("clicked")
        self.wait_for(lambda: closed == [True])
        self.assertEqual(received, [])
        self.assertEqual(self.settings.ensemble.member_weights, {})

    def test_escape_discards_blend_edits(self) -> None:
        received: list[Any] = []
        dialog, closed = self._edit_blend(received)
        dialog.close()  # what Escape does on an Adw.Dialog
        self.wait_for(lambda: closed == [True])
        self.assertEqual(received, [])
        self.assertEqual(self.settings.ensemble.member_weights, {})


if __name__ == "__main__":
    unittest.main()
