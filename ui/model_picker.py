"""Installed-model dialog. Filters are local to this window, never settings."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TypeVar

from gi.repository import Adw, Gdk, GLib, GObject, Gtk

from core.model_identity import ModelIdentityService
from core.model_repository import ModelRepository
from core.model_scores import PURPOSE_PAGE_OPTIONS, PURPOSE_RESTORE, load_model_scores

from .download_presentation import ARCHITECTURE_LABELS, ARCHITECTURES
from .model_picker_state import PickerFilters, PickerModel, project_installed, visible_models
from .template import load_builder, object_from_builder

T = TypeVar('T', bound=GObject.Object)
# Restoration models belong to Audio Tools, not Separation.
PURPOSES = (
    ('all', 'All'),
    *(option for option in PURPOSE_PAGE_OPTIONS if option[0] != PURPOSE_RESTORE),
)


@dataclass
class _PickerRow:
    row: Adw.ActionRow
    check: Gtk.Image
    info: Gtk.Button


class ModelPicker:
    def __init__(
        self,
        repo: ModelRepository,
        current: Callable[[], str],
        choose: Callable[[str], bool],
        get_more: Callable[[], None],
    ):
        self.repo = repo
        self.current = current
        self.choose = choose
        self.get_more = get_more
        self.builder = load_builder('model-picker')
        self.dialog = self.get('picker', Adw.Dialog)
        self.pages = self.get('pages', Gtk.Stack)
        self.search = self.get('search', Gtk.SearchEntry)
        self.architecture = self.get('architecture', Gtk.DropDown)
        self.sort = self.get('sort', Gtk.DropDown)
        self.compact = self.get('purpose_compact', Gtk.DropDown)
        self.list = self.get('models', Gtk.ListBox)
        self.models: tuple[PickerModel, ...] = ()
        self.filters = PickerFilters()
        self.detail_id: str | None = None
        self.syncing = False
        self.rows: dict[str, Adw.ActionRow] = {}
        self._row_cache: dict[str, _PickerRow] = {}
        self._row_order: dict[Gtk.ListBoxRow, int] = {}
        self._projection_inputs: tuple[object, object, object] | None = None
        self.list.set_filter_func(lambda row: row in self._row_order)
        self.list.set_sort_func(
            lambda left, right: self._row_order.get(left, -1) - self._row_order.get(right, -1)
        )
        self._reveal_tick = 0
        self.architecture.set_model(Gtk.StringList.new([label for _, label in ARCHITECTURES]))
        self.sort.set_model(Gtk.StringList.new(['Name']))
        self.compact.set_model(Gtk.StringList.new([label for _, label in PURPOSES]))
        self.buttons: list[Gtk.ToggleButton] = []
        for i, (_, label) in enumerate(PURPOSES):
            button = Gtk.ToggleButton(label=label)
            button.add_css_class('flat')
            if self.buttons:
                button.set_group(self.buttons[0])
            button.connect('toggled', self._purpose_toggled, i)
            self.buttons.append(button)
            self.get('purpose_tabs', Gtk.Box).append(button)
        self.buttons[0].set_active(True)
        for widget in (self.architecture, self.sort, self.compact):
            widget.connect('notify::selected', self._dropdown_changed)
        self.search.connect('search-changed', self._refresh)
        self.get('direction', Gtk.Button).connect('clicked', self._reverse)
        for name in ('reset', 'empty_reset'):
            self.get(name, Gtk.Button).connect('clicked', self.reset)
        self.get('back', Gtk.Button).connect('clicked', self._back)
        self.get('choose_detail', Gtk.Button).connect(
            'clicked', lambda *_: self.select(self.detail_id)
        )
        self.get('more', Gtk.Button).connect('clicked', self._more)
        keys = Gtk.EventControllerKey.new()
        keys.connect('key-pressed', self._key_pressed)
        self.dialog.add_controller(keys)
        self.dialog.connect('closed', self._closed)
        # Seven purpose buttons plus header actions need about 694 logical pixels
        # at the default text size; keep them visible down to 700sp.
        for width in (700, 512):
            condition = Adw.BreakpointCondition.parse(f'max-width: {width}sp')
            assert condition is not None
            breakpoint = Adw.Breakpoint.new(condition)
            breakpoint.add_setter(self.get('purpose_tabs', Gtk.Box), 'visible', False)
            breakpoint.add_setter(self.compact, 'visible', True)
            if width == 512:
                breakpoint.add_setter(
                    self.get('filter_bar', Gtk.Box), 'orientation', Gtk.Orientation.VERTICAL
                )
                breakpoint.add_setter(self.get('sort_controls', Gtk.Box), 'halign', Gtk.Align.START)
            self.dialog.add_breakpoint(breakpoint)

    def get(self, name: str, kind: type[T]) -> T:
        return object_from_builder(self.builder, name, kind)

    def refresh_models(self) -> None:
        service = ModelIdentityService(self.repo)
        records = service.records()
        snapshot = getattr(self.repo.catalogue, 'latest_snapshot', None)
        scores = load_model_scores(allow_network=False)
        previous = self._projection_inputs
        # Identity records already track inventory, catalogue and naming revisions.
        # Snapshots and score maps are replaced when new evidence is published.
        if (
            previous is None
            or records != previous[0]
            or snapshot is not previous[1]
            or scores is not previous[2]
        ):
            self.models = project_installed(records, snapshot, scores)
            self._projection_inputs = (records, snapshot, scores)
        self._refresh()
        if self.detail_id:
            model = next((m for m in self.models if m.id == self.detail_id), None)
            if model:
                self.show_details(model)
            else:
                self.detail_id = None
                self.pages.set_visible_child_name('browser')

    def present(self, parent: Gtk.Widget) -> None:
        self.detail_id = None
        self.refresh_models()
        self.pages.set_visible_child_name('browser')
        self.dialog.present(parent)
        self.search.grab_focus()
        if self._reveal_tick:
            self.dialog.remove_tick_callback(self._reveal_tick)
        self._reveal_tick = self.dialog.add_tick_callback(self._reveal_current)

    def _reveal_current(self, _widget: Gtk.Widget, _clock: Gdk.FrameClock) -> bool:
        row = self.rows.get(self.current())
        if row is not None:
            if row.get_height() <= 0:
                return GLib.SOURCE_CONTINUE
            ok, bounds = row.compute_bounds(self.list)
            if ok:
                adjustment = self.get('model_scroll', Gtk.ScrolledWindow).get_vadjustment()
                adjustment.set_value(max(0, bounds.get_y() - 12))
        self._reveal_tick = 0
        return GLib.SOURCE_REMOVE

    def _back(self, *_: object) -> None:
        self.detail_id = None
        self.pages.set_visible_child_name('browser')

    def _closed(self, *_: object) -> None:
        if self._reveal_tick:
            self.dialog.remove_tick_callback(self._reveal_tick)
            self._reveal_tick = 0

    def _purpose_toggled(self, button: Gtk.ToggleButton, index: int) -> None:
        if button.get_active() and not self.syncing:
            self.set_purpose(index)

    def set_purpose(self, index: int) -> None:
        self.syncing = True
        self.compact.set_selected(index)
        self.buttons[index].set_active(True)
        self.sort.set_model(Gtk.StringList.new(['Name', 'SDR'] if index in (1, 2) else ['Name']))
        self.syncing = False
        self.filters = PickerFilters()
        self._refresh()

    def _dropdown_changed(self, widget: Gtk.DropDown, _param: GObject.ParamSpec) -> None:
        if self.syncing:
            return
        if widget is self.compact:
            self.set_purpose(widget.get_selected())
        else:
            if widget is self.sort:
                from dataclasses import replace

                self.filters = replace(self.filters, descending=widget.get_selected() == 1)
            self._refresh()

    def _reverse(self, *_: object) -> None:
        from dataclasses import replace

        self.filters = replace(self.filters, descending=not self.filters.descending)
        self._refresh()

    def reset(self, *_: object) -> None:
        self.syncing = True
        self.search.set_text('')
        self.architecture.set_selected(0)
        self.syncing = False
        self.set_purpose(0)

    def _refresh(self, *_: object) -> None:
        if self.syncing:
            return
        self.filters = PickerFilters(
            self.search.get_text(),
            PURPOSES[self.compact.get_selected()][0],
            ARCHITECTURES[self.architecture.get_selected()][0],
            True,
            self.sort.get_selected() == 1,
            self.filters.descending,
        )
        installed_ids = {model.id for model in self.models}
        for model_id in self._row_cache.keys() - installed_ids:
            cached = self._row_cache.pop(model_id)
            self.list.remove(cached.row)
        visible = visible_models(self.models, self.filters)
        self.rows = {}
        self._row_order = {}
        current = self.current()
        for index, model in enumerate(visible):
            cached = self._row_cache.get(model.id)
            if cached is None:
                cached = self._create_row(model.id)
                self._row_cache[model.id] = cached
                self.list.append(cached.row)
            row = cached.row
            row.set_title(model.record.display)
            row.set_subtitle(model.subtitle(self.filters.purpose))
            row.set_activatable(not bool(model.reason))
            cached.check.set_opacity(1 if model.id == current else 0)
            cached.info.set_tooltip_text('Details for ' + model.record.display)
            self.rows[model.id] = row
            self._row_order[row] = index
        self.list.invalidate_filter()
        self.list.invalidate_sort()
        self.list.set_visible(bool(visible))
        self.get('empty', Adw.StatusPage).set_visible(not visible)
        self.get('count', Gtk.Label).set_label(f'{len(visible)} models')
        label = (
            'All installed models'
            if self.filters.purpose == 'all'
            else dict(PURPOSES)[self.filters.purpose] + ' models'
        )
        self.get('context_label', Gtk.Label).set_label(label)
        descending = self.filters.descending
        direction = (
            ('High–Low ↓' if descending else 'Low–High ↑')
            if self.filters.by_score
            else ('Z–A ↑' if descending else 'A–Z ↓')
        )
        self.get('direction', Gtk.Button).set_label(direction)
        self.sort.set_tooltip_text(
            'Sort by name or purpose-specific SDR'
            if self.filters.purpose in ('vocals', 'instrumental')
            else 'SDR sorting is available for Vocals and Instrumental'
        )

    def _create_row(self, model_id: str) -> _PickerRow:
        row = Adw.ActionRow(use_markup=False)
        row.set_title_lines(2)
        row.set_subtitle_lines(3)
        check = Gtk.Image.new_from_icon_name('object-select-symbolic')
        check.add_css_class('accent')
        row.add_prefix(check)
        info = Gtk.Button.new_from_icon_name('info-outline-symbolic')
        info.add_css_class('flat')
        info.set_valign(Gtk.Align.CENTER)
        info.connect('clicked', lambda *_: self._show_details_by_id(model_id))
        row.add_suffix(info)
        row.connect('activated', lambda *_: self.select(model_id))
        return _PickerRow(row, check, info)

    def _show_details_by_id(self, model_id: str) -> None:
        # Retained buttons must resolve the latest projection, not a captured record.
        model = next((model for model in self.models if model.id == model_id), None)
        if model is not None:
            self.show_details(model)

    def show_details(self, model: PickerModel) -> None:
        self.detail_id = model.id
        self.get('detail_name', Gtk.Label).set_label(model.record.display)
        self.get('detail_arch', Gtk.Label).set_label(
            ARCHITECTURE_LABELS.get(model.architecture, model.architecture) + ' · Installed'
        )
        values = {
            'detail_outputs': model.outputs,
            'detail_score': ' · '.join(
                f'{key.title()}: {value:.2f} dB' for key, value in model.scores.items()
            )
            or 'No benchmark score available',
            'detail_support': model.reason or 'No known compatibility issue',
            'detail_file': '\n'.join(
                (
                    model.record.artifacts.primary_filename,
                    *model.record.artifacts.supporting_filenames,
                )
            ),
        }
        for name, text in values.items():
            row = self.get(name, Adw.ActionRow)
            row.set_use_markup(False)
            row.set_subtitle(text)
        button = self.get('choose_detail', Gtk.Button)
        button.set_sensitive(not bool(model.reason))
        button.set_label('Current Model' if model.id == self.current() else 'Use This Model')
        self.pages.set_visible_child_name('details')

    def select(self, model_id: str | None) -> None:
        # Refresh/revalidate exact identity at activation: a download or removal
        # can change the inventory while the dialog is open.
        self.refresh_models()
        model = next((m for m in self.models if m.id == model_id), None)
        if model is not None and not model.reason and self.choose(model.id):
            self.dialog.close()
        else:
            self.get('toasts', Adw.ToastOverlay).add_toast(
                Adw.Toast(title='This model cannot be selected right now.')
            )

    def _more(self, *_: object) -> None:
        self.dialog.close()
        self.get_more()

    def _key_pressed(
        self,
        _controller: Gtk.EventControllerKey,
        keyval: int,
        _keycode: int,
        _modifiers: Gdk.ModifierType,
    ) -> bool:
        if keyval == Gdk.KEY_Escape and self.pages.get_visible_child_name() == 'details':
            self._back()
            return True
        return False
