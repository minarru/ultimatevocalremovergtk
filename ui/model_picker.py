"""Installed-model dialog. Filters are local to this window, never settings."""

from __future__ import annotations

from collections.abc import Callable, Collection, Sequence
from dataclasses import dataclass, replace
from typing import TypeVar

from gi.repository import Adw, Gdk, GLib, GObject, Gtk

from core.model_identity import ARCH_BY_FAMILY, ModelIdentityService, ModelRecord
from core.model_repository import ModelRepository
from core.model_scores import (
    PURPOSE_INSTRUMENTAL,
    PURPOSE_PAGE_OPTIONS,
    PURPOSE_RESTORE,
    PURPOSE_VOCALS,
    load_model_scores,
)

from .download_presentation import ARCHITECTURE_LABELS, ARCHITECTURES
from .model_picker_state import PickerFilters, PickerModel, project_installed, visible_models
from .template import load_builder, object_from_builder

T = TypeVar('T', bound=GObject.Object)
# Restoration models belong to Audio Tools, not Separation.
PURPOSES = (
    ('all', 'All'),
    *(option for option in PURPOSE_PAGE_OPTIONS if option[0] != PURPOSE_RESTORE),
)
_SCORED_PURPOSES = (PURPOSE_VOCALS, PURPOSE_INSTRUMENTAL)


@dataclass(frozen=True)
class PickerConfig:
    """Per-page presentation. The default is Separation's single-model picker."""

    title: str = 'Choose Model'
    # An empty tuple hides the purpose tabs and lists every model.
    purposes: tuple[tuple[str, str], ...] = PURPOSES
    search_placeholder: str = 'Search installed models'
    # Heading above the list; empty derives it from the purpose.
    list_label: str = ''
    # Details-page button in multi-select mode.
    add_label: str = 'Add to Ensemble'
    remove_label: str = 'Remove from Ensemble'


SEPARATION_PICKER = PickerConfig()


@dataclass(frozen=True)
class MemberCallbacks:
    """Multi-select mode: the page owns selection state and its persistence."""

    toggled: Callable[[Gtk.CheckButton | None], None]
    set_visible_active: Callable[[bool], None]
    # Called after the listed rows change (search, filters, members).
    filtered: Callable[[], None] | None = None


@dataclass
class _PickerRow:
    row: Adw.ActionRow
    check: Gtk.Image | None
    info: Gtk.Button
    toggle: Gtk.CheckButton | None = None
    handler: int = 0


class ModelPicker:
    def __init__(
        self,
        repo: ModelRepository,
        current: Callable[[], str],
        choose: Callable[[str], bool],
        get_more: Callable[[], None],
        *,
        config: PickerConfig = SEPARATION_PICKER,
        members: MemberCallbacks | None = None,
    ):
        self.repo = repo
        self.current = current
        self.choose = choose
        self.get_more = get_more
        self.config = config
        self.members = members
        self.builder = load_builder('model-picker')
        self.dialog = self.get('picker', Adw.Dialog)
        self.pages = self.get('pages', Gtk.Stack)
        self.search = self.get('search', Gtk.SearchEntry)
        self.architecture = self.get('architecture', Gtk.DropDown)
        self.sort = self.get('sort', Gtk.DropDown)
        self.compact = self.get('purpose_compact', Gtk.DropDown)
        self.list = self.get('models', Gtk.ListBox)
        self.models: tuple[PickerModel, ...] = ()
        self.filters = PickerFilters(supported_only=members is None)
        self.detail_id: str | None = None
        self.syncing = False
        self.rows: dict[str, Adw.ActionRow] = {}
        self._row_cache: dict[str, _PickerRow] = {}
        self._row_order: dict[Gtk.ListBoxRow, int] = {}
        self._projection_inputs: tuple[object, object, object] | None = None
        self._member_records: tuple[ModelRecord, ...] = ()
        self._placeholder = ('', '')
        self._status: str | None = None
        empty = self.get('empty', Adw.StatusPage)
        self._empty_text = (empty.get_title(), empty.get_description() or '')
        self.dialog.set_title(config.title)
        self.search.set_placeholder_text(config.search_placeholder)
        self.list.set_filter_func(lambda row: row in self._row_order)
        self.list.set_sort_func(
            lambda left, right: self._row_order.get(left, -1) - self._row_order.get(right, -1)
        )
        self._reveal_tick = 0
        self.architecture.set_model(Gtk.StringList.new([label for _, label in ARCHITECTURES]))
        self.sort.set_model(Gtk.StringList.new(['Name']))
        self._purposes = config.purposes or (('all', 'All'),)
        self.compact.set_model(Gtk.StringList.new([label for _, label in self._purposes]))
        tabs = self.get('purpose_tabs', Gtk.Box)
        self.buttons: list[Gtk.ToggleButton] = []
        for i, (_, label) in enumerate(config.purposes):
            button = Gtk.ToggleButton(label=label)
            button.add_css_class('flat')
            if self.buttons:
                button.set_group(self.buttons[0])
            button.connect('toggled', self._purpose_toggled, i)
            self.buttons.append(button)
            tabs.append(button)
        if self.buttons:
            self.buttons[0].set_active(True)
        else:
            tabs.set_visible(False)
        for widget in (self.architecture, self.sort, self.compact):
            widget.connect('notify::selected', self._dropdown_changed)
        self.search.connect('search-changed', self._refresh)
        self.get('direction', Gtk.Button).connect('clicked', self._reverse)
        for name in ('reset', 'empty_reset'):
            self.get(name, Gtk.Button).connect('clicked', self.reset)
        if members is not None:
            for name, active in (('select_all', True), ('clear', False)):
                button = self.get(name, Gtk.Button)
                button.set_visible(True)
                button.connect('clicked', lambda *_, a=active: members.set_visible_active(a))
        self.get('back', Gtk.Button).connect('clicked', self._back)
        self.get('choose_detail', Gtk.Button).connect('clicked', self._detail_action)
        self.get('more', Gtk.Button).connect('clicked', self._more)
        keys = Gtk.EventControllerKey.new()
        keys.connect('key-pressed', self._key_pressed)
        self.dialog.add_controller(keys)
        self.dialog.connect('closed', self._closed)
        # Seven purpose buttons plus header actions need about 694 logical pixels
        # at the default text size; keep them visible down to 700sp.
        for width in (700, 512):
            if width == 700 and not self.buttons:
                continue
            condition = Adw.BreakpointCondition.parse(f'max-width: {width}sp')
            assert condition is not None
            breakpoint = Adw.Breakpoint.new(condition)
            if self.buttons:
                breakpoint.add_setter(tabs, 'visible', False)
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
        # Multi-select lists exactly the page's members, not the whole inventory.
        if self.members is None:
            records = ModelIdentityService(self.repo).records()
        else:
            records = self._member_records
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

    def set_members(
        self,
        records: Sequence[ModelRecord],
        selected_ids: Collection[str],
        *,
        placeholder: str = '',
        placeholder_description: str = '',
    ) -> dict[str, Gtk.CheckButton]:
        """List ``records`` as checkable rows and return their checks in order.

        Check buttons are reused per ID, and setting their state here never
        reaches the page's ``toggled`` callback.
        """
        self._member_records = tuple(records)
        self._placeholder = (placeholder, placeholder_description)
        self.refresh_models()
        checks: dict[str, Gtk.CheckButton] = {}
        for record in records:
            cached = self._row_cache.get(record.id)
            if cached is None or cached.toggle is None:
                continue
            cached.toggle.handler_block(cached.handler)
            try:
                cached.toggle.set_active(record.id in selected_ids)
            finally:
                cached.toggle.handler_unblock(cached.handler)
            checks[record.id] = cached.toggle
        if self.detail_id in checks:
            self._sync_detail_button()
        return checks

    def visible_ids(self) -> list[str]:
        """IDs passing the current search and filters, in display order."""
        return list(self.rows)

    def set_status(self, text: str) -> None:
        self._status = text
        self.get('count', Gtk.Label).set_label(text)

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
        if self.buttons:
            self.buttons[index].set_active(True)
        scored = self._purposes[index][0] in _SCORED_PURPOSES
        self.sort.set_model(Gtk.StringList.new(['Name', 'SDR'] if scored else ['Name']))
        self.syncing = False
        self.filters = PickerFilters(supported_only=self.members is None)
        self._refresh()

    def _dropdown_changed(self, widget: Gtk.DropDown, _param: GObject.ParamSpec) -> None:
        if self.syncing:
            return
        if widget is self.compact:
            self.set_purpose(widget.get_selected())
        else:
            if widget is self.sort:
                self.filters = replace(self.filters, descending=widget.get_selected() == 1)
            self._refresh()

    def _reverse(self, *_: object) -> None:
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
            self._purposes[self.compact.get_selected()][0],
            ARCHITECTURES[self.architecture.get_selected()][0],
            self.members is None,
            self.sort.get_selected() == 1,
            self.filters.descending,
        )
        installed_ids = {model.id for model in self.models}
        for model_id in self._row_cache.keys() - installed_ids:
            cached = self._row_cache.pop(model_id)
            self.list.remove(cached.row)
        if self.members is not None:
            # Every member needs its check, even while a search hides its row.
            for model in self.models:
                if model.id not in self._row_cache:
                    self._row_cache[model.id] = self._create_row(model.id)
                    self.list.append(self._row_cache[model.id].row)
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
            row.set_subtitle(self._subtitle(model))
            if cached.check is not None:
                row.set_activatable(not bool(model.reason))
                cached.check.set_opacity(1 if model.id == current else 0)
            cached.info.set_tooltip_text('Details for ' + model.record.display)
            self.rows[model.id] = row
            self._row_order[row] = index
        self.list.invalidate_filter()
        self.list.invalidate_sort()
        self.list.set_visible(bool(visible))
        self._sync_empty(bool(visible))
        count = self.get('count', Gtk.Label)
        if self.members is not None and self._status is not None:
            count.set_label(self._status)
        else:
            count.set_label(f'{len(visible)} models')
        if self.config.list_label:
            label = self.config.list_label
        elif self.filters.purpose == 'all':
            label = 'All installed models'
        else:
            label = dict(self._purposes)[self.filters.purpose] + ' models'
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
            if self.filters.purpose in _SCORED_PURPOSES
            else 'SDR sorting is available for Vocals and Instrumental'
        )
        if self.members is not None and self.members.filtered is not None:
            self.members.filtered()

    def _subtitle(self, model: PickerModel) -> str:
        subtitle = model.subtitle(self.filters.purpose)
        if self.members is None:
            return subtitle
        # Members can share a display name across families; name the architecture.
        if model.architecture == 'unknown':
            arch = ARCH_BY_FAMILY.get(model.record.family, model.record.family)
        else:
            arch = ARCHITECTURE_LABELS.get(model.architecture, model.architecture)
        return f'{arch} · {subtitle}' if subtitle else arch

    def _sync_empty(self, has_rows: bool) -> None:
        empty = self.get('empty', Adw.StatusPage)
        empty.set_visible(not has_rows)
        title, description = self._placeholder
        placeholder = not self.models and bool(title)
        if not placeholder:
            title, description = self._empty_text
        empty.set_title(title)
        empty.set_description(description or None)
        self.get('empty_reset', Gtk.Button).set_visible(not placeholder)

    def _create_row(self, model_id: str) -> _PickerRow:
        row = Adw.ActionRow(use_markup=False)
        row.set_title_lines(2)
        row.set_subtitle_lines(3)
        info = Gtk.Button.new_from_icon_name('uvr-info-outline-symbolic')
        info.add_css_class('flat')
        info.set_valign(Gtk.Align.CENTER)
        info.connect('clicked', lambda *_: self._show_details_by_id(model_id))
        if self.members is not None:
            toggle = Gtk.CheckButton(valign=Gtk.Align.CENTER)
            handler = toggle.connect('toggled', self._member_toggled, model_id)
            row.add_prefix(toggle)
            row.set_activatable_widget(toggle)
            row.add_suffix(info)
            return _PickerRow(row, None, info, toggle, handler)
        check = Gtk.Image.new_from_icon_name('object-select-symbolic')
        check.add_css_class('accent')
        row.add_prefix(check)
        row.add_suffix(info)
        row.connect('activated', lambda *_: self.select(model_id))
        return _PickerRow(row, check, info)

    def _member_toggled(self, toggle: Gtk.CheckButton, model_id: str) -> None:
        if model_id == self.detail_id:
            self._sync_detail_button()
        if self.members is not None:
            self.members.toggled(toggle)

    def _member_toggle(self, model_id: str | None) -> Gtk.CheckButton | None:
        cached = self._row_cache.get(model_id or '')
        return cached.toggle if cached is not None else None

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
        self._sync_detail_button(model)
        self.pages.set_visible_child_name('details')

    def _sync_detail_button(self, model: PickerModel | None = None) -> None:
        button = self.get('choose_detail', Gtk.Button)
        if self.members is not None:
            toggle = self._member_toggle(self.detail_id)
            button.set_sensitive(toggle is not None)
            active = toggle is not None and toggle.get_active()
            button.set_label(self.config.remove_label if active else self.config.add_label)
            return
        if model is None:
            return
        button.set_sensitive(not bool(model.reason))
        button.set_label('Current Model' if model.id == self.current() else 'Use This Model')

    def _detail_action(self, *_: object) -> None:
        if self.members is None:
            self.select(self.detail_id)
            return
        toggle = self._member_toggle(self.detail_id)
        if toggle is not None:
            toggle.set_active(not toggle.get_active())

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
