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
from core.model_display import format_tag_title

from ..help_text import (
    IS_DEVERB_OPT_HELP,
    IS_DEVERB_VOC_HELP,
    IS_VOC_SPLIT_INST_SAVE_SELECT_HELP,
    IS_VOC_SPLIT_MODEL_SELECT_HELP,
    VOC_SPLIT_MODEL_SELECT_HELP,
)
from ..option_summaries import OFF, vocal_split_summary
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
        self._models_ready = False
        self._stored_splitter = NO_MODEL
        self._defer_populate = False
        self._populate_idle_scheduled = False

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
        self.connect("notify::expanded", self._populate_models)

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
            if not self._models_ready:
                seed = (
                    [NO_MODEL]
                    if self._stored_splitter == NO_MODEL
                    else [NO_MODEL, self._stored_splitter]
                )
                set_combo_tag_values(self.splitter_row, seed)
            set_combo_value(self.splitter_row, self._stored_splitter)
        finally:
            self._syncing = False

        self._sync_dependents()
        self.refresh_summary()
        # Expand only -- never auto-collapse, or a section the user opened by
        # hand would be shut on them by an unrelated settings reload. Defer
        # the karaoke-model hash off the restore path (same F1 pattern as
        # MethodView._sync_expander_summaries).
        self._defer_populate = True
        try:
            if self.split_switch.get_active() or self.deverb_switch.get_active():
                self.set_expanded(True)
        finally:
            self._defer_populate = False

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
        if self._models_ready:
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

    def _populate_models(self, *_args: typing.Any) -> None:
        if self._models_ready or not self.get_expanded():
            return
        if self._defer_populate:
            if not self._populate_idle_scheduled:
                self._populate_idle_scheduled = True
                from ..dispatch import idle_on_main

                idle_on_main(self._run_deferred_populate)
            return
        self._populate_models_now()

    def _run_deferred_populate(self) -> None:
        self._populate_idle_scheduled = False
        if self._models_ready or not self.get_expanded():
            return
        self._populate_models_now()

    def _populate_models_now(self) -> None:
        if self._models_ready:
            return
        self._models_ready = True
        try:
            values = self._repo.karaoke_model_list(self._settings)
        except Exception:
            values = []
        self._syncing = True
        try:
            tag_items = []
            for tag in values:
                try:
                    friendly = format_tag_title(tag, self._repo)
                except Exception:
                    friendly = tag
                tag_items.append((tag, friendly))
            # A stored tag absent from the fresh list -- a deleted/renamed model,
            # an older catalogue, or ``karaoke_model_list`` raising -- must still
            # be selectable, or selecting it here would silently rewrite it to
            # ``NO_MODEL`` on the next persist. Keep it as its own entry rather
            # than dropping it.
            known_tags = {NO_MODEL, *(tag for tag, _ in tag_items)}
            if self._stored_splitter not in known_tags:
                try:
                    friendly = format_tag_title(self._stored_splitter, self._repo)
                except Exception:
                    friendly = self._stored_splitter
                tag_items.append((self._stored_splitter, friendly))
            set_combo_tag_values(self.splitter_row, [NO_MODEL, *tag_items])
            set_combo_value(self.splitter_row, self._stored_splitter)
        finally:
            self._syncing = False

    def refresh_models(self) -> None:
        """Re-list karaoke models after the installed set changed.

        Snapshotting the combo into ``_stored_splitter`` first is load-bearing:
        while ``_models_ready`` is True the combo is authoritative, and demoting
        it without capturing the value would revert the selection to whatever
        the last ``apply_from_settings`` stored. The snapshot is also what keeps
        ``_populate_models_now``'s "stored tag missing from the fresh list stays
        selectable" branch working across a refresh.

        Collapsed rows are left invalidated but unpopulated -- resolving the
        list hashes checkpoints, and the next expand will do it.
        """
        if self._models_ready:
            self._stored_splitter = get_combo_value(self.splitter_row) or NO_MODEL
        self._models_ready = False
        if self.get_expanded():
            self._populate_models()

    def _on_row_changed(self, *_args: typing.Any) -> None:
        if self._syncing:
            return
        self._sync_dependents()
        if self._settings is not None:
            if self._models_ready:
                self._stored_splitter = (
                    get_combo_value(self.splitter_row) or NO_MODEL
                )
            self.persist_to_settings(self._settings)
            self.refresh_summary()
        self._on_changed()
