"""Dialogs use three content widths, a minimum size, and never outgrow the window.

440 for forms and short info, 600 for single-column lists and tools, 800 for
browsers and two-column sheets. Every ``Adw.Dialog`` has a 360×294 minimum
(Choose Model and Review Processing Plan keep taller ones), and the shared
presentation helper shrinks a dialog presented over a narrow window.
"""

from __future__ import annotations

import os
import re
import unittest
from collections.abc import Iterator
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
UI = ROOT / "resources" / "ui"

TIERS = {
    "change-model-defaults": 440,
    "model-params-apollo": 440,
    "model-params-mdx": 440,
    "model-params-mdxc": 440,
    "model-params-vr": 440,
    "update-view": 440,
    "stem_only": 440,
    "output-stems": 600,
    "verify-inputs": 600,
    "dual-batch-dialog": 600,
    "ensemble-blend": 600,
    "plan-review": 600,
    "compare-stems-dialog": 600,
    "error-dialog": 600,
    "manual-downloads": 600,
    "model-picker": 800,
    "model_options_sheet": 800,
}
# Lists and browsers that would otherwise open short. Save Stems, Verify
# Inputs and Compare Stems grow with their content inside scroller bounds.
OPENING = {
    "model-picker": 640,
    "dual-batch-dialog": 560,
    "ensemble-blend": 560,
    "plan-review": 560,
    "manual-downloads": 560,
}
# The run-failure dialog has no minimum height: its content is shorter than
# 294, and a minimum collapsed its summary TextView to nothing.
MIN_HEIGHT = {"model-picker": 480, "plan-review": 400, "error-dialog": 0}
# Model Options bounds its height to the window in Python.
PYTHON_HEIGHT = {"model_options_sheet"}

_DIALOG = re.compile(r"(?:(?<![\w.])Adw\.Dialog\s+\w+|template\s+\$\w+\s*:\s*Adw\.Dialog)\s*\{")


def dialog_properties(source: str) -> dict[str, str]:
    """Properties set on the first ``Adw.Dialog`` object, before its ``child:``."""
    match = _DIALOG.search(source)
    if match is None:
        return {}
    body = source[match.end() :]
    head = re.split(r"\bchild\s*:", body, maxsplit=1)[0]
    head = re.split(r"\n\s*[A-Z]\w*\.\w+", head, maxsplit=1)[0]
    return dict(re.findall(r"([\w-]+)\s*:\s*([^;{}]+?)\s*;", head))


def _descendants(widget: Any) -> Iterator[Any]:
    yield widget
    child = widget.get_first_child()
    while child is not None:
        yield from _descendants(child)
        child = child.get_next_sibling()


def dialog_blueprints() -> dict[str, dict[str, str]]:
    found = {}
    for path in sorted(UI.glob("*.blp")):
        source = path.read_text(encoding="utf-8")
        if _DIALOG.search(source):
            found[path.stem] = dialog_properties(source)
    return found


class DialogBlueprintSizingTests(unittest.TestCase):
    maxDiff = None

    def setUp(self) -> None:
        self.dialogs = dialog_blueprints()

    def test_every_dialog_blueprint_has_a_tier(self) -> None:
        self.assertEqual(set(self.dialogs), set(TIERS))

    def test_content_widths_match_tiers(self) -> None:
        widths = {stem: int(props.get("content-width", 0)) for stem, props in self.dialogs.items()}
        self.assertEqual(widths, TIERS)

    def test_minimum_sizes(self) -> None:
        for stem, props in self.dialogs.items():
            with self.subTest(dialog=stem):
                self.assertGreaterEqual(int(props.get("width-request", 0)), 360)
                self.assertEqual(int(props.get("height-request", 0)), MIN_HEIGHT.get(stem, 294))

    def test_opening_heights(self) -> None:
        for stem, props in self.dialogs.items():
            if stem in PYTHON_HEIGHT:
                continue
            with self.subTest(dialog=stem):
                height = int(props.get("content-height", -1))
                self.assertEqual(height, OPENING.get(stem, -1))

    def test_no_dialog_follows_content_size(self) -> None:
        # With follows-content-size libadwaita ignores content-width entirely.
        following = [s for s, p in self.dialogs.items() if p.get("follows-content-size") == "true"]
        self.assertEqual(following, [])


class CappedWidthTests(unittest.TestCase):
    def test_capped_dialog_width(self) -> None:
        from ui.dialogs.utils import capped_dialog_width

        class Parent:
            def __init__(self, width: int) -> None:
                self.width = width

            def get_width(self) -> int:
                return self.width

            def get_default_size(self) -> tuple[int, int]:
                return (self.width, 700)

        self.assertEqual(capped_dialog_width(600, None), 600)
        self.assertEqual(capped_dialog_width(600, Parent(1400)), 600)
        self.assertEqual(capped_dialog_width(600, Parent(480)), 416)
        self.assertEqual(capped_dialog_width(800, Parent(300)), 360)


@unittest.skipUnless(
    os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"),
    "GTK widget construction needs a display",
)
class PresentedWidthTests(unittest.TestCase):
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

        self.parent = Adw.Window()
        self.addCleanup(self.parent.close)

    def _present(self, dialog: Any, width: int) -> None:
        from tests.gtk_layout_helpers import resize_window, wait_for_dialog_open
        from ui.dialogs.utils import present_modal_dialog

        resize_window(self.parent, width, 600)
        present_modal_dialog(dialog, self.parent)
        wait_for_dialog_open(dialog)

    def _dialog(self) -> Any:
        from gi.repository import Adw, Gtk

        dialog = Adw.Dialog(content_width=600)
        dialog.set_child(Gtk.Label(label="content"))
        self.addCleanup(dialog.force_close)
        return dialog

    def test_cap_shrinks_dialog_on_narrow_parent(self) -> None:
        dialog = self._dialog()
        self._present(dialog, 480)
        self.assertEqual(dialog.get_content_width(), 416)

    def test_cap_restores_design_width_on_wider_parent(self) -> None:
        dialog = self._dialog()
        self._present(dialog, 480)
        dialog.force_close()
        self._present(dialog, 1000)
        self.assertEqual(dialog.get_content_width(), 600)

    def test_run_failure_summary_gets_its_height(self) -> None:
        # A minimum dialog height collapsed the summary TextView to 0 px.
        from gi.repository import Gtk

        import ui.errorlog as errorlog
        from tests.gtk_layout_helpers import resize_window, wait_for_dialog_open

        resize_window(self.parent, 1040, 720)
        errorlog.present_error_dialog(
            self.parent,
            heading="Separation Failed",
            exception=RuntimeError("CUDA error: device-side assert triggered"),
            formatted_log="Traceback",
        )
        dialog = errorlog._ACTIVE_ERROR_DIALOG
        assert dialog is not None
        self.addCleanup(dialog.force_close)
        wait_for_dialog_open(dialog)
        view = next(w for w in _descendants(dialog) if isinstance(w, Gtk.TextView))
        minimum, _natural, _b, _nb = view.measure(Gtk.Orientation.VERTICAL, view.get_width())
        self.assertGreater(minimum, 0)
        self.assertGreaterEqual(view.get_height(), minimum)

    def test_libadwaita_sized_dialogs_are_not_capped(self) -> None:
        from gi.repository import Adw

        dialog = Adw.PreferencesDialog()
        self.addCleanup(dialog.force_close)
        before = dialog.get_content_width()
        self._present(dialog, 480)
        self.assertEqual(dialog.get_content_width(), before)


if __name__ == "__main__":
    unittest.main()
