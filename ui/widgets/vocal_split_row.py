"""Vocal splitter + deverb section as a self-contained expander row.

These five settings -- ``is_set_vocal_splitter``, ``set_vocal_splitter``,
``is_save_inst_set_vocal_splitter``, ``is_deverb_vocals`` and
``deverb_vocal_opt`` -- are **unprefixed globals**. They used to be built once
per architecture view, so three copies edited one set of values and changing the
section on the VR tab silently changed MDX-Net and Demucs. They now live on the
pages that actually run separations (Separation and Ensemble), which both
consume the same globals, exactly as ``OutputFormatRow`` already does for
``save_format``.

The row owns its own settings binding rather than reusing ``MethodView``'s row
helpers: those register each row into per-view registries (``_option_rows``,
``_switch_rows``, ``_model_combos``) that ``MethodView.load`` / ``.save``
iterate, so they only work inside a view.
"""

from __future__ import annotations
import typing

from typing import Callable

from gi.repository import Adw

from bundled.constants import DEVERB_MAPPER, NO_MODEL
from ..help_text import (
    IS_DEVERB_OPT_HELP,
    IS_DEVERB_VOC_HELP,
    IS_VOC_SPLIT_INST_SAVE_SELECT_HELP,
    IS_VOC_SPLIT_MODEL_SELECT_HELP,
    VOC_SPLIT_MODEL_SELECT_HELP,
)
from ..option_summaries import OFF, vocal_split_summary
from .lazy_populate import LazyPopulator
from .rows import (
    get_combo_value,
    make_combo_row,
    make_switch_row,
    set_combo_tag_values,
    set_combo_value,
    use_wrapping_list,
)

_DEFAULT_DEVERB = "Main Vocals Only"


class VocalSplitRow(Adw.ExpanderRow):
    """The five global vocal-split/deverb settings in one collapsible row."""

    def __init__(
        self,
        repo: typing.Any,
        on_changed: Callable[[], None],
        hints: typing.Any=None,
    ):
        super().__init__(title="Vocal splitter and deverb")
        self._repo = repo
        self._on_changed = on_changed
        #: Cached from the last ``apply_from_settings`` so interactive edits can
        #: write straight through and keep the subtitle in step. ``None`` until
        #: the row has been applied at least once.
        self._settings = None
        self._syncing = False
        #: The karaoke model list is expensive (it hashes checkpoints), so the
        #: combo starts seeded with just the stored tag and is filled on first
        #: expansion. Until then its value must not be written back, or an
        #: unopened row would clobber the stored tag with ``NO_MODEL``.
        #: ``_populator.ready`` is that gate.
        self._stored_splitter = NO_MODEL
        self._splitter_write_gated = False
        self._splitter_ids: set[str] = set()
        self._populator = LazyPopulator(
            is_expanded=self.get_expanded,
            populate=self._populate_models_now,
        )

        self.split_switch = make_switch_row("Enable vocal split mode")
        self.splitter_row = make_combo_row("Vocal splitter model", [NO_MODEL])
        use_wrapping_list(self.splitter_row)
        self.save_inst_switch = make_switch_row("Save split vocal instrumentals")
        self.deverb_switch = make_switch_row("Deverb vocals")
        self.deverb_row = make_combo_row(
            "Deverb vocal type", list(DEVERB_MAPPER.keys())
        )

        for row in (
            self.split_switch,
            self.splitter_row,
            self.save_inst_switch,
            self.deverb_switch,
            self.deverb_row,
        ):
            self.add_row(row)

        if hints is not None:
            hints.register(self.split_switch, IS_VOC_SPLIT_MODEL_SELECT_HELP)
            hints.register(self.splitter_row, VOC_SPLIT_MODEL_SELECT_HELP)
            hints.register(self.save_inst_switch, IS_VOC_SPLIT_INST_SAVE_SELECT_HELP)
            hints.register(self.deverb_switch, IS_DEVERB_VOC_HELP)
            hints.register(self.deverb_row, IS_DEVERB_OPT_HELP)

        for row in (self.split_switch, self.save_inst_switch, self.deverb_switch):
            row.connect("notify::active", self._on_row_changed)
        for row in (self.splitter_row, self.deverb_row):
            row.connect("notify::selected", self._on_row_changed)
        self.connect("notify::expanded", self._on_expanded)

        self.set_subtitle(OFF)
        self._sync_dependents()

    # -- Settings ---------------------------------------------------------------

    def apply_from_settings(self, settings: typing.Any) -> None:
        """Restore every row from ``settings`` without emitting changes."""
        self._settings = settings
        process = settings.process
        self._stored_splitter = process.vocal_splitter or NO_MODEL
        self._syncing = True
        try:
            self.split_switch.set_active(bool(process.vocal_splitter_enabled))
            self.save_inst_switch.set_active(
                bool(process.save_inst_vocal_splitter)
            )
            self.deverb_switch.set_active(bool(process.deverb_vocals))
            set_combo_value(
                self.deverb_row, process.deverb_vocal_opt or _DEFAULT_DEVERB
            )
            if not self._populator.ready:
                seed = (
                    [NO_MODEL]
                    if self._stored_splitter == NO_MODEL
                    else [NO_MODEL, self._stored_splitter]
                )
                set_combo_tag_values(self.splitter_row, seed)
            self._splitter_write_gated = bool(
                self._populator.ready
                and self._stored_splitter not in (NO_MODEL, None, "")
                and (
                    not isinstance(self._stored_splitter, str)
                    or self._stored_splitter not in self._splitter_ids
                )
            )
            set_combo_value(
                self.splitter_row,
                NO_MODEL if self._splitter_write_gated else self._stored_splitter,
            )
        finally:
            self._syncing = False

        self._sync_dependents()
        self.refresh_summary()
        # Expand only -- never auto-collapse, or a section the user opened by
        # hand would be shut on them by an unrelated settings reload. Defer
        # the karaoke-model hash off the restore path (same F1 pattern as
        # MethodView._sync_expander_summaries).
        with self._populator.defer():
            if self.split_switch.get_active() or self.deverb_switch.get_active():
                self.set_expanded(True)

    def persist_to_settings(self, settings: typing.Any) -> None:
        """Write every global vocal-split key back to ``settings``."""
        process = settings.process
        process.vocal_splitter_enabled = self.split_switch.get_active()
        process.save_inst_vocal_splitter = self.save_inst_switch.get_active()
        process.deverb_vocals = self.deverb_switch.get_active()
        process.deverb_vocal_opt = (
            get_combo_value(self.deverb_row) or _DEFAULT_DEVERB
        )
        # Only trust the combo once its real list has loaded; before that it is
        # a seeded placeholder and the stored tag is authoritative.
        if self._populator.ready and not self._splitter_write_gated:
            process.vocal_splitter = get_combo_value(self.splitter_row)
        else:
            process.vocal_splitter = self._stored_splitter

    def refresh_summary(self) -> None:
        """Re-read the section's subtitle from the cached settings."""
        settings = self._settings
        self.set_subtitle(vocal_split_summary(settings) if settings is not None else OFF)

    # -- Internals --------------------------------------------------------------

    def _sync_dependents(self) -> None:
        """Dim each activate switch's dependants while it is off.

        Matches ``MethodView._bind_switch_dependents``: an inapplicable control
        stays visible but non-interactive, so the section's shape never changes
        as switches flip.
        """
        split_on = self.split_switch.get_active()
        self.splitter_row.set_sensitive(split_on)
        self.save_inst_switch.set_sensitive(split_on)
        self.deverb_row.set_sensitive(self.deverb_switch.get_active())

    def _on_expanded(self, *_args: typing.Any) -> None:
        self._populator.ensure()

    def _populate_models_now(self) -> None:
        try:
            values = self._repo.karaoke_model_list(self._settings)
        except Exception:
            values = []
        self._syncing = True
        try:
            from core.model_identity import ModelIdentityService

            eligible = set(values)
            records = sorted(
                (
                    record
                    for record in ModelIdentityService(self._repo).records()
                    if record.installed and record.id in eligible
                ),
                key=lambda record: (record.display.casefold(), record.id),
            )
            tag_items = [(record.id, record.display) for record in records]
            set_combo_tag_values(self.splitter_row, [NO_MODEL, *tag_items])
            ids = {record.id for record in records}
            self._splitter_ids = ids
            self._splitter_write_gated = bool(
                self._stored_splitter not in (NO_MODEL, None, "")
                and (
                    not isinstance(self._stored_splitter, str)
                    or self._stored_splitter not in ids
                )
            )
            set_combo_value(
                self.splitter_row,
                NO_MODEL if self._splitter_write_gated else self._stored_splitter,
            )
        finally:
            self._syncing = False

    def refresh_models(self) -> None:
        """Re-list karaoke models after the installed set changed.

        Snapshotting the combo into ``_stored_splitter`` first is load-bearing:
        while the list is populated the combo is authoritative, and invalidating
        without capturing the value would revert the selection to whatever the
        last ``apply_from_settings`` stored. The snapshot is also what keeps
        ``_populate_models_now``'s "stored tag missing from the fresh list stays
        selectable" branch working across a refresh.

        A collapsed row is invalidated but not repopulated -- resolving the list
        hashes checkpoints, and the next expand will do it.
        """
        if self._populator.ready and not self._splitter_write_gated:
            self._stored_splitter = get_combo_value(self.splitter_row) or NO_MODEL
        self._populator.invalidate()

    def _on_row_changed(self, *_args: typing.Any) -> None:
        if self._syncing:
            return
        self._sync_dependents()
        if self._settings is not None:
            if self._populator.ready:
                self._stored_splitter = (
                    get_combo_value(self.splitter_row) or NO_MODEL
                )
                self._splitter_write_gated = False
            self.persist_to_settings(self._settings)
            self.refresh_summary()
        self._on_changed()
