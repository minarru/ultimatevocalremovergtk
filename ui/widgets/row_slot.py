"""A swappable run of rows inside an ``Adw.PreferencesGroup``.

``Adw.PreferencesGroup`` only appends, so replacing a middle run of rows (one
method's output rows, one tool's settings) while keeping rows that belong
*below* it in place means removing and re-adding the tail. ``RowSlot`` owns that
bookkeeping: rows already in the group when the slot is created stay above it,
the slot's rows come next, and the ``trailing`` rows always come last.
"""

from __future__ import annotations

from typing import Sequence

from gi.repository import Adw, Gtk


def _detach(row: Gtk.Widget) -> None:
    """Remove ``row`` from whichever preferences group currently owns it."""
    owner = row.get_ancestor(Adw.PreferencesGroup)
    if isinstance(owner, Adw.PreferencesGroup):
        owner.remove(row)


class RowSlot:
    def __init__(
        self,
        group: Adw.PreferencesGroup,
        *,
        trailing: Sequence[Gtk.Widget] = (),
    ) -> None:
        self._group = group
        self._rows: tuple[Gtk.Widget, ...] = ()
        self._trailing: list[Gtk.Widget] = list(trailing)
        for row in self._trailing:
            _detach(row)
            self._group.add(row)

    @property
    def rows(self) -> tuple[Gtk.Widget, ...]:
        return self._rows

    def replace(self, rows: Sequence[Gtk.Widget]) -> None:
        """Make ``rows`` the slot's contents, between the leading and trailing rows."""
        new_rows = tuple(rows)
        for row in (*self._rows, *self._trailing):
            _detach(row)
        for row in new_rows:
            _detach(row)
            self._group.add(row)
        self._rows = new_rows
        for row in self._trailing:
            self._group.add(row)

    def append_trailing(self, row: Gtk.Widget) -> None:
        """Add ``row`` after every other row, and keep it there across ``replace``."""
        _detach(row)
        self._trailing.append(row)
        self._group.add(row)
