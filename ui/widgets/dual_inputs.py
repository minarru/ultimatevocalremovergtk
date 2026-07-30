"""Read-only summary + editor entry point for align / matchering input pairs."""

from __future__ import annotations
import typing

import os
from typing import Callable, List, Sequence, Tuple

from gi.repository import Adw, Gtk

from ..help_text import DUAL_INPUTS_HINT
from ..hints import set_tooltip
from ..markup import set_row_subtitle, set_row_title
from .rows import add_row_icon


class DualInputsRow(Adw.ExpanderRow):
    """Expandable row summarising paired inputs with a button to open the editor.

    Empty-state affordances match :class:`InputFilesRow`: expansion is disabled
    until pairs exist; the pair-editor suffix remains the primary action.
    """

    def __init__(self, on_edit: Callable[[], None]):
        super().__init__(title="Input pairs")
        if hasattr(self, "set_use_markup"):
            self.set_use_markup(False)
        self._on_edit = on_edit
        self._labels = ("File 1", "File 2")
        self._pairs: List[Tuple[str, str]] = []
        self._detail_rows: List[Adw.ActionRow] = []

        add_row_icon(self, "audio-x-generic-symbolic")
        set_tooltip(self, DUAL_INPUTS_HINT)

        self._edit_button = Gtk.Button(label="Pair editor\u2026", valign=Gtk.Align.CENTER)
        self._edit_button.add_css_class("flat")
        set_tooltip(self._edit_button, DUAL_INPUTS_HINT)
        self._edit_button.connect("clicked", self._open_editor)
        self.add_suffix(self._edit_button)

        self.connect("activate", self._open_editor)
        self._refresh()

    def set_pairs(
        self,
        pairs: Sequence[Tuple[str, str]],
        labels: Tuple[str, str],
    ) -> None:
        self._pairs = [(str(a), str(b)) for a, b in pairs]
        self._labels = labels
        self._refresh()

    def _open_editor(self, *_args: typing.Any) -> None:
        self._on_edit()

    def _refresh(self) -> None:
        for row in self._detail_rows:
            self.remove(row)
        self._detail_rows = []

        if self._pairs:
            first = self._pairs[0]
            extra = len(self._pairs) - 1
            batch_note = f" (+{extra} more pair(s) in batch)" if extra else ""
            set_row_subtitle(
                self,
                f"{self._labels[0]}: {os.path.basename(first[0])} · "
                f"{self._labels[1]}: {os.path.basename(first[1])}{batch_note}",
            )
            self._append_detail_row(self._labels[0], first[0])
            self._append_detail_row(self._labels[1], first[1])
            if extra:
                self._append_batch_row(extra)
            self.set_enable_expansion(True)
        else:
            set_row_subtitle(self, "No pairs selected — open the pair editor to choose files")
            self.set_expanded(False)
            self.set_enable_expansion(False)

    def _append_detail_row(self, label: str, path: str) -> None:
        row = Adw.ActionRow()
        set_row_title(row, label)
        if path:
            set_row_subtitle(row, os.path.basename(path))
            row.set_tooltip_text(path)
        else:
            set_row_subtitle(row, "Not set")
        row.set_activatable(True)
        row.connect("activated", self._open_editor)
        self.add_row(row)
        self._detail_rows.append(row)

    def _append_batch_row(self, extra: int) -> None:
        row = Adw.ActionRow(title=f"{extra} additional pair(s) in batch")
        row.set_activatable(True)
        row.connect("activated", self._open_editor)
        self.add_row(row)
        self._detail_rows.append(row)
