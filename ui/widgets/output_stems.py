"""Separation's output summary and direct stem-selection dialog."""

from collections.abc import Callable

from gi.repository import Adw, Gtk

from core.stem_selection import _TOGGLE_ALL

from ..dialogs.utils import present_modal_dialog
from ..gtk_narrow import root_window
from ..markup import set_row_subtitle
from ..stem_controls import StemControlsSnapshot
from ..template import load_builder, object_from_builder
from .rows import configure_combo_row, get_combo_value, set_combo_tag_values, set_combo_value
from .stem_only import SaveStemsSection


class OutputStemsSection:
    """Render one selection owner; edits use the method page's settings guard."""

    def __init__(
        self,
        section: SaveStemsSection,
        host: Adw.PreferencesGroup,
        *,
        use_direct_controls: bool = True,
    ):
        self.section = section
        self.controls = section.enable_direct_controls() if use_direct_controls else None
        self._rendering = False
        self._row_revision = -1
        self._output_rows: dict[str, tuple[Adw.ActionRow, Gtk.CheckButton]] = {}
        self._row_signature: tuple[tuple[str, bool], ...] = ()
        self._preset_signature: tuple[tuple[str, str], ...] = ()
        self._mode_items: tuple[tuple[str, str], ...] = ()
        self._focus_items: tuple[tuple[str, str], ...] = ()
        builder = load_builder("output-stems")
        self.row = object_from_builder(builder, "summary_row", Adw.ActionRow)
        self.count = object_from_builder(builder, "file_count", Gtk.Label)
        self.dialog = object_from_builder(builder, "dialog", Adw.Dialog)
        self._scroll = object_from_builder(builder, "scroll", Gtk.ScrolledWindow)
        self._model_name = object_from_builder(builder, "model_name", Gtk.Label)
        self.result_count = object_from_builder(builder, "result_count", Gtk.Label)
        self._result_names = object_from_builder(builder, "result_names", Gtk.Label)
        self._additional = object_from_builder(builder, "additional_outputs", Gtk.Label)
        self._workload = object_from_builder(builder, "workload", Gtk.Label)
        self._output_list = object_from_builder(builder, "output_list", Gtk.ListBox)
        self._search = object_from_builder(builder, "search", Gtk.SearchEntry)
        self._no_matches = object_from_builder(builder, "no_matches", Adw.StatusPage)
        self._review = object_from_builder(builder, "review", Gtk.Label)
        self._select_all = object_from_builder(builder, "select_all", Gtk.Button)
        self._presets = object_from_builder(builder, "presets", Gtk.Box)
        self._mode_group = object_from_builder(builder, "mode_group", Adw.PreferencesGroup)
        self._mode = configure_combo_row(
            object_from_builder(builder, "export_mode", Adw.ComboRow), []
        )
        self._focus = configure_combo_row(
            object_from_builder(builder, "stem_focus", Adw.ComboRow), []
        )
        selection_group = object_from_builder(builder, "selection_group", Adw.PreferencesGroup)
        selection_group.set_visible(self.controls is None)
        if self.controls is None:
            section.attach_to(selection_group)
        self._search.connect("search-changed", self._filter_outputs)
        self._select_all.connect("clicked", self._all_clicked)
        self._mode.connect("notify::selected", self._mode_changed)
        self._focus.connect("notify::selected", self._focus_changed)
        host.add(self.row)
        self.row.connect("activated", self._present)
        self.refresh()

    def refresh(self, *, model_name: str | None = None, workload: str | None = None) -> None:
        if self.controls is None:
            self._refresh_legacy()
        else:
            self.controls.refresh_options(self.section.settings)
            self._rendering = True
            try:
                self._render(self.controls.snapshot())
            finally:
                self._rendering = False
        if model_name is not None:
            self._model_name.set_label(model_name)
            self._model_name.set_tooltip_text(model_name)
            self._model_name.set_visible(bool(model_name))
        if workload is not None:
            self._workload.set_label(workload)
            self._workload.set_visible(bool(workload))
        if self.dialog.get_mapped():
            if not self.row.get_sensitive():
                self.dialog.close()
            else:
                self._resize()

    def _refresh_legacy(self) -> None:
        presentation = self.section.presentation()
        summary = presentation.export_summary.removeprefix("Exporting ")
        summary = summary[:1].upper() + summary[1:]
        if presentation.mode == "exclusive" and presentation.expected_count > 1:
            summary = (
                ", ".join(
                    option.display_label
                    for option in presentation.choices
                    if option.name != _TOGGLE_ALL
                )
                or summary
            )
        set_row_subtitle(self.row, summary)
        count = presentation.expected_count
        count_text = f"{count} file" if count == 1 else f"{count} files"
        self.count.set_label(count_text)
        self.count.set_visible(count > 0)
        self.result_count.set_label(f"{count_text} per input" if count else "Choose stems to save")
        self._result_names.set_label(summary)
        self.row.set_sensitive(bool(presentation.visible_rows))
        self.row.set_tooltip_text(presentation.hint)
        for widget in (
            self._output_list,
            self._search,
            self._no_matches,
            self._review,
            self._mode_group,
            self._select_all,
            self._presets,
            self._additional,
        ):
            widget.set_visible(False)

    def _render(self, snapshot: StemControlsSnapshot) -> None:
        count = snapshot.main_count
        count_text = f"{count} stem" if count == 1 else f"{count} stems"
        set_row_subtitle(self.row, snapshot.summary)
        self.count.set_label(count_text)
        self.count.set_visible(count > 0)
        self.count.set_tooltip_text("Main outputs per input before additional processing")
        self.result_count.set_label(f"{count_text} per input" if count else "Choose stems to save")
        self._result_names.set_label(snapshot.summary)
        self._result_names.set_tooltip_text(snapshot.summary)
        self._result_names.set_visible(False)
        self._additional.set_label(snapshot.additional_output_note)
        self._additional.set_visible(bool(snapshot.additional_output_note))
        self.row.set_sensitive(snapshot.mode != "unavailable")
        self.row.set_tooltip_text(self.section.active_hint())
        self._review.set_visible(snapshot.review_required)
        self._mode.set_visible(bool(snapshot.modes))
        self._focus.set_visible(len(snapshot.focus_choices) > 1)
        self._mode_group.set_visible(bool(snapshot.modes) or len(snapshot.focus_choices) > 1)
        if self._mode_items != snapshot.modes:
            self._mode_items = snapshot.modes
            set_combo_tag_values(self._mode, list(snapshot.modes))
        if self._focus_items != snapshot.focus_choices:
            self._focus_items = snapshot.focus_choices
            set_combo_tag_values(self._focus, list(snapshot.focus_choices))
        set_combo_value(self._mode, snapshot.active_mode_id)
        set_combo_value(self._focus, snapshot.active_focus_id)
        revision_changed = self._row_revision != snapshot.revision
        # Short lists need only the checkboxes and header Select All. Preserve
        # useful one-click presets for large inventories without duplicating All.
        presets = (
            tuple(p for p in snapshot.presets if p[0] != "all")
            if len(snapshot.choices) >= 8
            else ()
        )
        if revision_changed or self._preset_signature != presets:
            self._preset_signature = presets
            while (child := self._presets.get_first_child()) is not None:
                self._presets.remove(child)
            for preset_id, label in presets:
                button = Gtk.Button(label=label)
                button.connect("clicked", self._preset_clicked, preset_id, snapshot.revision)
                self._presets.append(button)
        self._presets.set_visible(bool(presets))
        review_all = snapshot.review_required and bool(snapshot.focus_choices)
        self._select_all.set_visible(
            review_all
            or (
                snapshot.mode in ("pair", "native_subset", "demucs_focus")
                and (
                    snapshot.mode != "demucs_focus"
                    or all(choice.enabled for choice in snapshot.choices)
                )
            )
        )
        self._select_all.set_label("Use All Stems" if review_all else "Select All")
        self._select_all.set_sensitive(
            review_all or any(choice.editable for choice in snapshot.choices)
        )
        signature = tuple((choice.id, choice.editable) for choice in snapshot.choices)
        if revision_changed or signature != self._row_signature:
            self._row_revision = snapshot.revision
            self._row_signature = signature
            self._output_list.remove_all()
            self._output_rows.clear()
            for choice in snapshot.choices:
                builder = load_builder("output-stem-row")
                row = object_from_builder(builder, "row", Adw.ActionRow)
                check = object_from_builder(builder, "selected", Gtk.CheckButton)
                fixed = object_from_builder(builder, "fixed_selection", Gtk.Image)
                check.set_visible(choice.editable)
                fixed.set_visible(not choice.editable)
                if choice.editable:
                    row.set_activatable_widget(check)
                check.connect("toggled", self._toggled, choice.id, snapshot.revision)
                self._output_rows[choice.id] = row, check
                self._output_list.append(row)
            if revision_changed:
                self._search.set_text("")
        for choice in snapshot.choices:
            row, check = self._output_rows[choice.id]
            check.set_sensitive(choice.enabled)
            row.set_title(choice.route.label)
            set_row_subtitle(row, choice.explanation)
            check.update_property([Gtk.AccessibleProperty.LABEL], [f"Save {choice.route.label}"])
            check.update_property(
                [Gtk.AccessibleProperty.DESCRIPTION], ["At least one output is required."]
            )
            check.set_active(choice.selected)
        self._search.set_visible(len(snapshot.choices) >= 8)
        self._filter_outputs()

    def _filter_outputs(self, *_args: object) -> None:
        if self.controls is None:
            return
        query = self._search.get_text().strip().casefold() if self._search.get_visible() else ""
        visible = 0
        for row, _check in self._output_rows.values():
            matches = query in (row.get_title() or "").casefold()
            row.set_visible(matches)
            visible += matches
        self._no_matches.set_visible(bool(query) and not visible)
        self._output_list.set_visible(visible > 0)

    def _apply(self, command: Callable[[], bool]) -> None:
        if self._rendering or self.controls is None:
            return
        if command():
            self.section.controls_changed()
        self.refresh()

    def _toggled(self, check: Gtk.CheckButton, output_id: str, revision: int) -> None:
        if (controls := self.controls) is not None:
            self._apply(
                lambda: controls.toggle_output(output_id, check.get_active(), revision=revision)
            )

    def _all_clicked(self, *_args: object) -> None:
        if (controls := self.controls) is not None:
            snapshot = controls.snapshot()
            if snapshot.review_required and snapshot.focus_choices:
                self._apply(lambda: controls.choose_focus(snapshot.focus_choices[0][0]))
            else:
                self._apply(controls.select_all)

    def _preset_clicked(self, _button: Gtk.Button, preset_id: str, revision: int) -> None:
        if (controls := self.controls) is not None:
            self._apply(lambda: controls.choose_preset(preset_id, revision=revision))

    def _mode_changed(self, *_args: object) -> None:
        if (controls := self.controls) is not None:
            self._apply(lambda: controls.choose_mode(get_combo_value(self._mode) or ""))

    def _focus_changed(self, *_args: object) -> None:
        if (controls := self.controls) is not None:
            self._apply(lambda: controls.choose_focus(get_combo_value(self._focus) or ""))

    def _resize(self) -> None:
        parent = root_window(self.row)
        height = parent.get_height() if parent is not None else 700
        self._scroll.set_max_content_height(min(440, max(120, height - 340)))
        self.dialog.set_content_height(-1)

    def _present(self, *_args: object) -> None:
        if not self.row.get_sensitive():
            return
        self._resize()
        present_modal_dialog(self.dialog, root_window(self.row))
