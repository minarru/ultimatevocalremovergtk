"""RowSlot: swap a run of rows inside an Adw.PreferencesGroup."""

from __future__ import annotations

import os
import unittest
from typing import Any

from tests.gtk_layout_helpers import iter_descendants


def _order(group: Any) -> list[Any]:
    """Rows of ``group`` in display order (libadwaita hosts them in a ListBox)."""
    from gi.repository import Gtk

    box = next((w for w in iter_descendants(group) if isinstance(w, Gtk.ListBox)), None)
    rows: list[Any] = []
    if box is None:
        return rows
    child = box.get_first_child()
    while child is not None:
        rows.append(child)
        child = child.get_next_sibling()
    return rows


@unittest.skipUnless(
    os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"),
    "GTK widget construction needs a display",
)
class RowSlotTests(unittest.TestCase):
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

        from ui.widgets.row_slot import RowSlot

        self.group = Adw.PreferencesGroup()
        self.lead = Adw.ActionRow(title="L")
        self.group.add(self.lead)
        self.t1 = Adw.ActionRow(title="T1")
        self.t2 = Adw.ActionRow(title="T2")
        self.a = Adw.ActionRow(title="A")
        self.b = Adw.ActionRow(title="B")
        self.slot = RowSlot(self.group, trailing=(self.t1, self.t2))

    def test_replace_places_rows_before_trailing(self) -> None:
        self.slot.replace([self.a, self.b])
        self.assertEqual(_order(self.group), [self.lead, self.a, self.b, self.t1, self.t2])

    def test_replace_swaps_contents(self) -> None:
        from gi.repository import Adw

        c = Adw.ActionRow(title="C")
        self.slot.replace([self.a, self.b])
        self.slot.replace([c])
        self.assertEqual(_order(self.group), [self.lead, c, self.t1, self.t2])
        self.assertIsNone(self.a.get_parent())
        self.assertEqual(self.slot.rows, (c,))

    def test_empty_slot(self) -> None:
        self.slot.replace([self.a])
        self.slot.replace([])
        self.assertEqual(_order(self.group), [self.lead, self.t1, self.t2])
        self.assertEqual(self.slot.rows, ())

    def test_moves_row_from_another_group(self) -> None:
        from gi.repository import Adw

        other = Adw.PreferencesGroup()
        other.add(self.a)
        self.slot.replace([self.a])
        self.assertIn(self.a, _order(self.group))
        self.assertNotIn(self.a, _order(other))

    def test_append_trailing_goes_last(self) -> None:
        from gi.repository import Adw

        t3 = Adw.ActionRow(title="T3")
        self.slot.replace([self.a])
        self.slot.append_trailing(t3)
        self.assertEqual(_order(self.group), [self.lead, self.a, self.t1, self.t2, t3])
        self.slot.replace([self.b])
        self.assertEqual(_order(self.group), [self.lead, self.b, self.t1, self.t2, t3])


if __name__ == "__main__":
    unittest.main()
