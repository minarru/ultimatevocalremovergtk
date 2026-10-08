"""Input, Output and Processing groups shared by the run pages.

Separation, Ensemble and Audio Tools all start with the same three groups: the
input files, the output folder and format, and the GPU / FP16 / sample-mode
switches. :func:`build_page_groups` builds them once, with one row order, one
set of tooltips and typed shared-settings bindings. Pages add their own rows
through ``add_input_row``, ``set_output_lead`` / ``add_output_tail`` and
``add_processing`` instead of assembling the groups themselves.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Collection, Literal, Sequence

from gi.repository import Adw, Gtk

from core.sample_mode import has_custom_start
from core.settings import Settings

from ..help_text import (
    INPUT_FOLDER_ENTRY_HELP,
    IS_AUTOCAST_HELP,
    IS_GPU_CONVERSION_HELP,
    MODEL_SAMPLE_MODE_HELP,
    OUTPUT_FOLDER_ENTRY_HELP,
    VIEW_INPUTS_BUTTON_HINT,
)
from ..hints import set_icon_button_a11y
from ..playback.engine import playback_unavailable_reason
from ..protocols import FormatEdit, ReadableVocalSplitRow
from ..shared_settings import (
    SAMPLE_MODE_TITLE,
    SharedFileOptions,
    SharedSettingsBindings,
    apply_shared_file_options,
    sample_mode_subtitle,
    shared_settings_bindings,
)
from ..template import load_builder, object_from_builder
from .file_chooser import InputFilesRow, OutputFolderRow
from .format_row import OutputFormatRow
from .row_slot import RowSlot

ProcessingRow = Literal["gpu", "autocast", "sample"]

_PROCESSING_ORDER: tuple[ProcessingRow, ...] = ("gpu", "autocast", "sample")
SAMPLE_RANGE_TOOLTIP = "Choose sample range…"


@dataclass(frozen=True)
class PageGroupCallbacks:
    on_inputs_changed: Callable[[], None]
    on_output_changed: Callable[[], None]
    on_format_changed: Callable[[FormatEdit], None]
    toast: Callable[[str], None]
    hint: Callable[[Gtk.Widget, str], object]
    accept_any_getter: Callable[[], bool]
    initial_folder_getter: Callable[[], str | None]
    sample_duration: int = 30
    view_inputs_action: str | None = "win.view_inputs"
    on_view_inputs: Callable[[], None] | None = None
    on_gpu_changed: Callable[[], None] | None = None
    on_autocast_changed: Callable[[], None] | None = None
    on_sample_changed: Callable[[], None] | None = None
    on_choose_sample_range: Callable[[], None] | None = None
    #: Live settings, read when the Sample mode row refreshes its range state.
    settings_getter: Callable[[], Settings] | None = None


class PageGroups:
    input_group: Adw.PreferencesGroup
    output_group: Adw.PreferencesGroup
    processing_group: Adw.PreferencesGroup
    input_row: InputFilesRow
    output_row: OutputFolderRow
    format_row: OutputFormatRow
    gpu_row: Adw.SwitchRow | None
    autocast_row: Adw.SwitchRow | None
    sample_row: Adw.SwitchRow | None
    sample_range_button: Gtk.Button | None
    view_inputs_button: Gtk.Button

    def __init__(
        self,
        *,
        input_group: Adw.PreferencesGroup,
        output_group: Adw.PreferencesGroup,
        processing_group: Adw.PreferencesGroup,
        input_row: InputFilesRow,
        output_row: OutputFolderRow,
        format_row: OutputFormatRow,
        gpu_row: Adw.SwitchRow | None,
        autocast_row: Adw.SwitchRow | None,
        sample_row: Adw.SwitchRow | None,
        view_inputs_button: Gtk.Button,
        sample_range_button: Gtk.Button | None = None,
        settings_getter: Callable[[], Settings] | None = None,
    ) -> None:
        self.input_group = input_group
        self.output_group = output_group
        self.processing_group = processing_group
        self.input_row = input_row
        self.output_row = output_row
        self.format_row = format_row
        self.gpu_row = gpu_row
        self.autocast_row = autocast_row
        self.sample_row = sample_row
        self.sample_range_button = sample_range_button
        self.view_inputs_button = view_inputs_button
        self._settings_getter = settings_getter
        self._output_slot = RowSlot(output_group, trailing=(format_row, output_row))

    def add_input_row(self, row: Gtk.Widget) -> None:
        """Append a page-specific row after the input-files row."""
        self.input_group.add(row)

    def set_output_lead(self, rows: Sequence[Gtk.Widget]) -> None:
        """Make ``rows`` the rows above the format and output-folder rows."""
        self._output_slot.replace(rows)

    def add_output_tail(self, row: Gtk.Widget) -> None:
        """Append a row below the output-folder row; it stays below any lead swap."""
        self._output_slot.append_trailing(row)

    def add_processing(self, row: Gtk.Widget) -> None:
        """Append a page-specific row after the processing switches."""
        self.processing_group.add(row)

    def bindings(self, *, vocal_row: ReadableVocalSplitRow | None = None) -> SharedSettingsBindings:
        return shared_settings_bindings(
            input_row=self.input_row,
            output_row=self.output_row,
            format_row=self.format_row,
            gpu_row=self.gpu_row,
            autocast_row=self.autocast_row,
            sample_row=self.sample_row,
            vocal_row=vocal_row,
        )

    def apply(self, settings: Settings) -> SharedFileOptions:
        """Push the shared settings into this page's rows (no persistence)."""
        options = apply_shared_file_options(
            settings,
            input_row=self.input_row,
            output_row=self.output_row,
            format_row=self.format_row,
            gpu_row=self.gpu_row,
            autocast_row=self.autocast_row,
            sample_row=self.sample_row,
        )
        self.sync_sample_range()
        return options

    def sync_sample_range(self) -> None:
        """Refresh the Sample mode subtitle and whether a range can be chosen."""
        row, button = self.sample_row, self.sample_range_button
        if row is None or button is None or self._settings_getter is None:
            return
        settings = self._settings_getter()
        paths = list(self.input_row.paths)
        custom = has_custom_start(settings.process.sample_starts, paths)
        row.set_subtitle(sample_mode_subtitle(settings.process.sample_mode_duration, custom=custom))
        reason = playback_unavailable_reason() if row.get_active() and paths else None
        button.set_sensitive(row.get_active() and bool(paths) and reason is None)
        button.set_tooltip_text(reason or SAMPLE_RANGE_TOOLTIP)


def _suffix_before_switch(row: Adw.SwitchRow, widget: Gtk.Widget) -> None:
    """Add ``widget`` as a suffix placed before the row's own switch.

    ``AdwSwitchRow`` adds its switch as the first suffix, so later suffixes land
    after it. Reorder inside the suffix box when the switch is found there.
    """
    row.add_suffix(widget)
    box = widget.get_parent()
    if not isinstance(box, Gtk.Box):
        return
    child = box.get_first_child()
    while child is not None and not isinstance(child, Gtk.Switch):
        child = child.get_next_sibling()
    if child is not None:
        box.reorder_child_after(widget, child.get_prev_sibling())


def _connect_switch(row: Adw.SwitchRow, callback: Callable[[], None] | None) -> None:
    if callback is not None:
        row.connect("notify::active", lambda *_args: callback())


def build_page_groups(
    callbacks: PageGroupCallbacks,
    *,
    processing: Collection[ProcessingRow] = _PROCESSING_ORDER,
) -> PageGroups:
    builder = load_builder("page-groups")
    input_group = object_from_builder(builder, "input_group", Adw.PreferencesGroup)
    output_group = object_from_builder(builder, "output_group", Adw.PreferencesGroup)
    processing_group = object_from_builder(builder, "processing_group", Adw.PreferencesGroup)

    view_inputs_button = object_from_builder(builder, "view_inputs_button", Gtk.Button)
    if callbacks.view_inputs_action is not None:
        view_inputs_button.set_action_name(callbacks.view_inputs_action)
    on_view_inputs = callbacks.on_view_inputs
    if on_view_inputs is not None:
        view_inputs_button.connect("clicked", lambda _button: on_view_inputs())
    set_icon_button_a11y(view_inputs_button, VIEW_INPUTS_BUTTON_HINT)

    groups: PageGroups | None = None

    def on_inputs_changed() -> None:
        callbacks.on_inputs_changed()
        if groups is not None:
            groups.sync_sample_range()

    input_row = InputFilesRow(
        on_inputs_changed,
        on_toast=callbacks.toast,
        accept_any_getter=callbacks.accept_any_getter,
        initial_folder_getter=callbacks.initial_folder_getter,
    )
    output_row = OutputFolderRow(callbacks.on_output_changed, on_toast=callbacks.toast)
    format_row = OutputFormatRow(callbacks.on_format_changed)
    input_group.add(input_row)
    callbacks.hint(input_row, INPUT_FOLDER_ENTRY_HELP)
    callbacks.hint(output_row, OUTPUT_FOLDER_ENTRY_HELP)

    wanted = set(processing)
    gpu_row = autocast_row = sample_row = None
    sample_range_button: Gtk.Button | None = None
    if "gpu" in wanted:
        gpu_row = object_from_builder(builder, "gpu_row", Adw.SwitchRow)
        _connect_switch(gpu_row, callbacks.on_gpu_changed)
        callbacks.hint(gpu_row, IS_GPU_CONVERSION_HELP)
        processing_group.add(gpu_row)
    if "autocast" in wanted:
        autocast_row = object_from_builder(builder, "autocast_row", Adw.SwitchRow)
        _connect_switch(autocast_row, callbacks.on_autocast_changed)
        callbacks.hint(autocast_row, IS_AUTOCAST_HELP)
        processing_group.add(autocast_row)
    if "sample" in wanted:
        sample_row = object_from_builder(builder, "sample_row", Adw.SwitchRow)
        sample_row.set_title(SAMPLE_MODE_TITLE)
        sample_row.set_subtitle(sample_mode_subtitle(callbacks.sample_duration))
        _connect_switch(sample_row, callbacks.on_sample_changed)
        callbacks.hint(sample_row, MODEL_SAMPLE_MODE_HELP)
        processing_group.add(sample_row)
        sample_range_button = object_from_builder(builder, "sample_range_button", Gtk.Button)
        _suffix_before_switch(sample_row, sample_range_button)
        on_choose = callbacks.on_choose_sample_range
        if on_choose is not None:
            sample_range_button.connect("clicked", lambda _button: on_choose())
        sample_row.connect(
            "notify::active", lambda *_args: groups.sync_sample_range() if groups else None
        )

    groups = PageGroups(
        input_group=input_group,
        output_group=output_group,
        processing_group=processing_group,
        input_row=input_row,
        output_row=output_row,
        format_row=format_row,
        gpu_row=gpu_row,
        autocast_row=autocast_row,
        sample_row=sample_row,
        view_inputs_button=view_inputs_button,
        sample_range_button=sample_range_button,
        settings_getter=callbacks.settings_getter,
    )
    groups.sync_sample_range()
    return groups
