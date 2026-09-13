"""Blend edits are transactional and use exact role/model identities."""

import importlib.util
import unittest
from collections.abc import Iterator
from types import SimpleNamespace
from typing import Any

from tests.private_gtk import require_private_gtk


@unittest.skipUnless(importlib.util.find_spec("gi"), "GTK unavailable")
class EnsembleBlendDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        import gi

        gi.require_version("Gtk", "4.0")
        gi.require_version("Adw", "1")
        from gi.repository import Adw, Gtk

        if not Gtk.init_check():
            raise unittest.SkipTest("GTK display unavailable")
        require_private_gtk()
        Adw.init()

    def test_edits_apply_only_after_apply_button(self) -> None:
        from gi.repository import Adw, Gtk

        from core.settings import Settings
        from core.stem_roles import StemRoleId
        from ui.ensemble.blend_dialog import show_blend_dialog

        settings = Settings.defaults()
        parent = Gtk.Window()
        received = []
        dialog = show_blend_dialog(
            parent,
            settings,
            [
                (
                    "mdx:a",
                    "Model A",
                    [SimpleNamespace(role=StemRoleId("vocal.vocals"), label="Vocals")],
                )
            ],
            received.append,
        )

        def descendants(widget: Any) -> Iterator[Any]:
            yield widget
            child = widget.get_first_child()
            while child is not None:
                yield from descendants(child)
                child = child.get_next_sibling()

        children = list(descendants(dialog))
        weight = next(
            w for w in children if isinstance(w, Adw.SpinRow) and w.get_title() == "Model A"
        )
        smoothing = next(
            w
            for w in children
            if isinstance(w, Adw.SpinRow) and w.get_title() == "Min Spec smoothing"
        )
        self.assertEqual(smoothing.get_value(), 0)
        smoothing.set_value(0.75)
        weight.set_value(2.5)
        self.assertEqual(settings.ensemble.member_weights, {})
        self.assertEqual(received, [])
        button = next(w for w in children if isinstance(w, Gtk.Button) and w.get_label() == "Apply")
        button.emit("clicked")
        self.assertEqual(received[0]["smoothing"], 0.75)
        self.assertEqual(received[0]["member_weights"], {"vocal.vocals": {"mdx:a": 2.5}})
        parent.set_visible(False)
