"""Per-method option views and their registry.

Each processing method (VR Architecture, MDX-Net, Demucs) contributes one
:class:`MethodView`. A view owns the method's model dropdown plus the
main-window options that the Tk app shows for that method
(``update_main_widget_states``), and knows how to read/write its slice of the
typed :class:`~core.settings.Settings`.

The window builds a ``Gtk.Stack`` from :data:`METHOD_VIEWS` and a "Process
method" ``Adw.ComboRow`` to choose between them, so additional method panels can
be registered by appending to the registry without touching the window assembly.
"""
import typing

from typing import Callable, List, Optional, Type

from gi.repository import Adw, Gio, Gtk

from bundled.constants import (
    BASS_STEM,
    CHOOSE_MODEL,
    CHOOSE_MODEL_HELP,
    CLEAR_CACHE_HELP,
    DEMUCS_ARCH_TYPE,
    DRUM_STEM,
    INST_STEM,
    MDX_ARCH_TYPE,
    NO_MODEL,
    OTHER_STEM,
    PRE_PROC_MODEL_ACTIVATE_HELP,
    PRE_PROC_MODEL_HELP,
    PRE_PROC_MODEL_INST_MIX_HELP,
    SAVE_STEM_ONLY_HELP,
    SECONDARY_MODEL_ACTIVATE_HELP,
    SECONDARY_MODEL_HELP,
    SECONDARY_MODEL_SCALE_HELP,
    SECONDARY_STEM,
    VOCAL_STEM,
    VR_ARCH_TYPE,
)
from core.settings import Settings
from core.stems import EnsemblePair, StemBucket, model_stem_count, ui_label

from ..hints import HelpHintManager
from ..widgets.rows import (
    get_combo_value,
    get_scale_row_float,
    get_scale_row_value,
    make_combo_row,
    make_switch_row,
    set_combo_tag_values,
    set_combo_value,
    set_combo_values,
    set_scale_row_float,
    set_scale_row_value,
    use_wrapping_list,
)
from core.model_display import map_basenames_to_display
from core.model_identity import FAMILY_BY_ARCH, ModelIdentityService, parse_stored_model_id
from core.model_scores import parse_sdr_score
from ..widgets.lazy_populate import LazyPopulator
from ..widgets.stem_only import SaveStemsSection
from core.model_stem_semantics import recommended_export_note, stem_display_overrides
from core.run_estimate import compose_stem_group_tooltip, estimate_workload, format_workload_line
from ..help_text import RUN_WORKLOAD_HINT
from ..option_summaries import (
    four_stem_secondaries_apply,
    preproc_summary,
    secondary_models_summary,
)
from ..settings_bind import get_flat, set_flat, setting_for_combo
from ..widget_state import fetch, stash

_DEFAULT_SETTINGS = Settings.defaults()

# Per-stem secondary-model slots: (settings-key slot, EnsemblePair, primary stem,
# secondary stem) used to build the four secondary-model selectors UVR exposes.
_SECONDARY_SLOTS = (
    ("voc_inst", EnsemblePair.VOCALS_INSTRUMENTAL, VOCAL_STEM, INST_STEM),
    ("other", EnsemblePair.OTHER, OTHER_STEM, "No Other"),
    ("bass", EnsemblePair.BASS, BASS_STEM, "No Bass"),
    ("drums", EnsemblePair.DRUMS, DRUM_STEM, "No Drums"),
)


def apply_name_mapper(names: typing.Any, name_mapper: typing.Any, *, catalogue_index: typing.Any=None, arch: typing.Any=None, repo: typing.Any=None) -> List[str]:
    """Map on-disk basenames to runtime display labels."""
    if arch and repo:
        return map_basenames_to_display(names, arch, repo)
    if not name_mapper and not catalogue_index:
        return list(names)
    from core.model_display import display_name_for_basename

    return [
        display_name_for_basename(name, name_mapper, catalogue_index=catalogue_index)
        for name in names
    ]


class MethodView:
    """Base class for a processing-method option panel.

    Subclasses set the class attributes and implement :meth:`build_options`,
    :meth:`load_options` and :meth:`save_options` for their method-specific rows.
    The model dropdown and the primary/secondary stem-only switches are common
    to all three methods and handled here.
    """

    #: Settings value stored in ``chosen_process_method`` for this method.
    method_key: str = ""
    #: Settings key holding the selected model name.
    model_key: str = ""
    #: ``Adw.ViewStack`` page name.
    stack_name: str = ""
    title: str = ""
    #: Settings keys for the primary/secondary "save only" toggles.
    primary_only_key: str = "is_primary_stem_only"
    secondary_only_key: str = "is_secondary_stem_only"

    #: Per-arch prefix for the secondary-model settings keys
    #: (``vr`` / ``mdx`` / ``demucs``); also reused for the activate key.
    secondary_prefix: str = ""
    #: Whether this method exposes the Demucs pre-process model selector.
    has_preproc: bool = False

    def __init__(self, context: typing.Any, on_settings_changed: Callable[[], None]):
        self.context = context
        self.settings = context.settings
        self._on_settings_changed = on_settings_changed
        self._loading = False
        self._populator = LazyPopulator(
            is_expanded=self._model_combo_section_open,
            populate=self._populate_model_combos_now,
        )
        self._option_rows = {}
        self._scale_rows = {}
        self._switch_rows = {}
        self._spin_rows = {}
        self._model_combos = []
        self._model_write_gated = False
        self._secondary_slot_rows = {}
        self._switch_dependent_appliers = []
        self.hints = HelpHintManager()

        # The window distributes these groups across one or two responsive
        # columns (see ``MainWindow._populate_columns``); ``self.groups`` is the
        # ordered list of top-level groups this view contributes. There is no
        # single ``self.widget`` wrapper, so the groups can be reparented between
        # columns when the method or the window width changes.
        self.groups = []

        # No group title: the method combo directly above already names the
        # architecture (e.g. "MDX-Net"), so a per-arch header here was redundant
        # chrome. The group's first row ("Model") labels the content.
        self.group = Adw.PreferencesGroup()
        self.groups.append(self.group)

        self.model_row = make_combo_row("Model", [CHOOSE_MODEL], icon_name="applications-science-symbolic")
        use_wrapping_list(self.model_row)
        self.model_row.connect("notify::selected", self._on_model_changed)
        self.group.add(self.model_row)
        self.hints.register(self.model_row, CHOOSE_MODEL_HELP)

        self.build_options(self.group)

        # Advanced / inference options: standard preferences list without an expander.
        self.advanced_group = Adw.PreferencesGroup()
        self.build_advanced(self.advanced_group)
        self.groups.append(self.advanced_group)

        # Secondary / pre-process / vocal-splitter model selection
        # (appends ``self.secondary_group`` to ``self.groups``).
        self._build_secondary_section()

        self.stem_group = Adw.PreferencesGroup(title="Save stems")
        self.save_stems = SaveStemsSection(
            settings=self.settings,
            on_changed=self._on_save_stems_changed,
        )
        self._resolved_primary_stem = None
        self._resolved_secondary_stem = None
        self._resolved_model = None
        self.save_stems.attach_to(self.stem_group)
        self.hints.register(self.stem_group, SAVE_STEM_ONLY_HELP)
        self.build_stem_options(self.stem_group)
        self.groups.append(self.stem_group)

    # -- Model dropdown ---------------------------------------------------------

    def list_models(self) -> List[str]:
        """Return the on-disk model names for this method (no name mapping)."""
        raise NotImplementedError

    def has_any_models(self) -> bool:
        """Whether any model is installed for this method (excludes the picker placeholder)."""
        family = FAMILY_BY_ARCH[self.method_key_for_resolution]
        return any(
            record.installed and record.family == family
            for record in ModelIdentityService(self.context.repo).records()
        )

    def name_mapper(self):
        return None

    def populate_models(self) -> None:
        arch = self.method_key_for_resolution
        repo = self.context.repo
        family = FAMILY_BY_ARCH[arch]
        installed = tuple(
            record
            for record in ModelIdentityService(repo).records()
            if record.installed
        )
        records = [record for record in installed if record.family == family]

        def sort_key(record: typing.Any) -> tuple[int, float, str, str]:
            score = parse_sdr_score(record.display, record.basename)
            return (
                1 if score is None else 0,
                0.0 if score is None else -score,
                record.display.casefold(),
                record.id,
            )

        records.sort(key=sort_key)
        items = [(record.id, record.display) for record in records]
        set_combo_tag_values(self.model_row, [CHOOSE_MODEL, *items])
        stored = get_flat(self.settings, self.model_key, CHOOSE_MODEL)
        ids = {item[0] for item in items}
        self._model_write_gated = False
        stored_is_item = isinstance(stored, str) and stored in ids
        if stored not in (CHOOSE_MODEL, NO_MODEL, None, "") and not stored_is_item:
            try:
                parse_stored_model_id(str(stored))
            except ValueError:
                self._model_write_gated = True
                set_combo_value(self.model_row, CHOOSE_MODEL)
                return
            present = any(record.id == stored for record in installed)
            if not present:
                self._model_write_gated = True
                set_combo_value(self.model_row, CHOOSE_MODEL)
                return
            # A canonical ID installed under another family is likewise only
            # a visual no-selection state. It stays stored verbatim until the
            # user explicitly chooses one of this picker's installed IDs.
            self._model_write_gated = True
            set_combo_value(self.model_row, CHOOSE_MODEL)
            return
        set_combo_value(self.model_row, stored)

    def refresh_models(self) -> None:
        """Re-list on-disk models (e.g. after a Download Center download)."""
        self._loading = True
        try:
            self.populate_models()
        finally:
            self._loading = False
        self._invalidate_model_combos()
        self.update_stem_labels()

    def _invalidate_model_combos(self) -> None:
        """Drop the combo lists, repopulating any section already on screen.

        Collapsed sections stay lazy: they repopulate on the next
        ``notify::expanded``. Open ones cannot rely on that -- GObject emits
        ``notify`` only when the property changes, so an expander the user
        already opened would keep its stale list until collapsed and reopened.
        """
        for entry in self._model_combos:
            entry["ready"] = False
        # defer=True: this runs from the model refresh that follows a download,
        # right as the toast paints, and populating resolves every combo's
        # model list. A collapsed section repopulates on its next expand.
        self._populator.invalidate(defer=True)

    def _model_combo_section_open(self) -> bool:
        """One latch covers both expanders, so either being open counts."""
        return any(
            expander is not None and expander.get_expanded()
            for expander in (
                getattr(self, "secondary_expander", None),
                getattr(self, "preproc_expander", None),
            )
        )

    def selected_model(self) -> str:
        return get_combo_value(self.model_row) or CHOOSE_MODEL

    def has_model(self) -> bool:
        return self.selected_model() not in (CHOOSE_MODEL, None)

    def _on_model_changed(self, *_args: typing.Any) -> None:
        if self._loading:
            return
        from core.debug_log import debug, preview_text

        self._model_write_gated = False
        set_flat(self.settings, self.model_key, self.selected_model())
        name = self.selected_model()
        debug(
            "model",
            f"model selected name={preview_text(name)} arch={self.title or self.method_key}",
        )
        self._on_settings_changed()
        self.update_stem_labels()

    # -- Custom stem naming -----------------------------------------------------

    def update_stem_labels(self) -> None:
        """Rebuild the stem-only toggles for the selected model's stems."""
        model_name = self.selected_model()
        model = None
        if model_name not in (CHOOSE_MODEL, NO_MODEL, None):
            model = self.context.repo.resolve_model_dry(
                self.settings, self.method_key_for_resolution, model_name
            )
        primary_stem = model.primary_stem if model else None
        secondary = model.secondary_stem if model else None
        self._resolved_primary_stem = primary_stem
        self._resolved_secondary_stem = secondary
        self._resolved_model = model
        if not self.has_model():
            self.save_stems.configure_hidden(has_model=False)
        else:
            self._configure_save_stems(model)
        self._on_model_resolved(model)
        if self.has_model():
            self.save_stems.sync_from_settings()
        self._update_stem_group_metadata()
        self.sync_dynamic_option_state()

    def _configure_save_stems(self, model: typing.Any) -> None:
        """Default: exclusive export filter for <=2-stem / VR-style models."""
        self.save_stems.configure_exclusive(
            primary_stem=self._resolved_primary_stem,
            secondary_stem=self._resolved_secondary_stem,
            primary_key=self.primary_only_key,
            secondary_key=self.secondary_only_key,
            has_model=True,
            stem_label_overrides=stem_display_overrides(model),
            export_semantics_note=recommended_export_note(model),
                is_karaoke=bool(getattr(model, "is_karaoke", False)),
                is_karaoke_curated=bool(getattr(model, "is_karaoke_curated", False)),
                is_bv=bool(getattr(model, "is_bv_model", False)),
                stem_count=max(1, model_stem_count(model)),
            )

    def _update_stem_group_metadata(self) -> None:
        line1 = self.save_stems.export_summary()
        workload = estimate_workload(
            self.settings,
            method_key=self.method_key,
            save_stems=self.save_stems,
            repo=self.context.repo,
            model_name=self.selected_model() if self.has_model() else None,
            has_model=self.has_model(),
        )
        line2 = format_workload_line(workload)
        self.stem_group.set_description(f"{line1}\n{line2}" if line2 else line1)
        composed = compose_stem_group_tooltip(
            self.save_stems.active_hint(),
            workload,
            workload_hint=RUN_WORKLOAD_HINT,
        )
        # Re-register so HelpHintManager.refresh() keeps the composed tooltip.
        self.hints.register(self.stem_group, composed)

    def _touch_settings(self) -> None:
        self._update_stem_group_metadata()
        self._refresh_expander_subtitles()
        self._on_settings_changed()

    def _sync_stem_only_toggles(self) -> None:
        """Reflect stem export settings in the save-stems widget."""
        self.save_stems.sync_from_settings()
        self._update_stem_group_metadata()

    def _persist_stem_only(self) -> None:
        self.save_stems.persist_to_settings()

    def _on_save_stems_changed(self) -> None:
        if self._loading:
            return
        self._persist_stem_only()
        self._update_stem_group_metadata()
        self.sync_dynamic_option_state()
        self._on_settings_changed()

    # Backwards-compatible alias used when switching method tabs.
    def _sync_only_active(self) -> None:
        self._sync_stem_only_toggles()

    def _on_model_resolved(self, model: typing.Any) -> None:
        """Hook called after the selected model is dry-resolved (on change/load).

        ``model`` is a dry-check :class:`~core.ModelConfig` or ``None`` when no
        model is selected / it couldn't be resolved. Subclasses override to react
        to model-specific attributes (e.g. MDX-C vs classic MDX). Default no-op.
        """

    #: Arch type used to build ``ModelConfig`` (VR's panel key differs from its
    #: process method); defaults to :attr:`method_key`.
    resolution_method_key: str = ""

    @property
    def method_key_for_resolution(self) -> str:
        return self.resolution_method_key or self.method_key

    # -- Stem-only combo (mutually exclusive, like the Tk checkbuttons) --------

    # -- Persistence ------------------------------------------------------------

    def load(self) -> None:
        self._loading = True
        try:
            self.populate_models()
            # Active states are restored via ``update_stem_labels`` ->
            # ``_sync_only_active`` once each row is bound to its stem/key below.
            self.load_options()
            self._load_scales()
            self._load_switches()
            self._load_spins()
        finally:
            self._loading = False
        self._sync_switch_dependents()
        self.update_stem_labels()
        self._sync_expander_summaries()
        self.hints.refresh()

    def save(self, *, include_stem_only: bool = True) -> None:
        """Write this method view's widget state into ``settings``.

        Called from :meth:`~ui.window.MainWindow._flush_settings` for every
        separation architecture on preflight/start/close. ``include_stem_only``
        is ``True`` only for the **active** method (the one shown in the method
        combo).

        When ``False``, persisting method-local keys (``model_key``, option
        combos, scales, switches in ``vr.*`` / ``mdx.*`` / ``demucs.*``) is
        intentional — each architecture keeps its own snapshot in settings.

        When ``False``, the view **must not** write **shared** keys — especially
        ``process.stem_focus`` via Save Stems. Stem persist is owned by
        :meth:`_persist_stem_only`, gated by this flag. ``save_options()``
        overrides must **not** call ``save_stems.persist_to_settings()``; doing
        so from an inactive view (e.g. Demucs ``quick_all`` while MDX is active)
        clears the active view's export focus before plan review.
        """
        if not getattr(self, "_model_write_gated", False):
            set_flat(self.settings, self.model_key, self.selected_model())
        if include_stem_only:
            self._persist_stem_only()
        self.save_options()
        self._save_scales()
        self._save_switches()
        self._save_spins()

    # -- Method-specific option controls ---------------------------------------

    @staticmethod
    def _add_row(container: typing.Any, row: typing.Any) -> None:
        """Add ``row`` to a ``PreferencesGroup`` (``add``) or ``ExpanderRow`` (``add_row``)."""
        if isinstance(container, Adw.ExpanderRow):
            container.add_row(row)
        else:
            container.add(row)

    def _hint(self, row: typing.Any, hint: typing.Any):
        """Register ``row`` with the view's help-hint manager when ``hint`` is set."""
        if hint:
            self.hints.register(row, hint)
        return row

    def add_option_combo(self, group: typing.Any, key: typing.Any, title: typing.Any, values: typing.Any, subtitle: typing.Any=None, hint: typing.Any=None):
        """Add a combo row bound to settings ``key`` (stored as a string)."""
        row = make_combo_row(title, values, subtitle)
        row.connect("notify::selected", lambda *_a, k=key, r=row: self._on_option_combo(k, r))
        self._add_row(group, row)
        self._option_rows[key] = row
        return self._hint(row, hint)

    def add_option_scale(
        self,
        group: typing.Any,
        key: typing.Any,
        title: typing.Any,
        *,
        values: typing.Any=None,
        lower: Optional[float] = None,
        upper: Optional[float] = None,
        step: float = 1,
        digits: typing.Any=0,
        subtitle: typing.Any=None,
        hint: typing.Any=None,
        store_float: typing.Any=False,
    ):
        """Add a constrained slider row bound to settings ``key``."""
        from ..widgets.rows import (
            make_discrete_scale_row,
            make_numeric_scale_row,
            set_scale_default_mark,
        )

        if values is not None:
            row = make_discrete_scale_row(title, values, subtitle)
        else:
            if lower is None or upper is None:
                raise ValueError("lower and upper are required when values is None")
            row = make_numeric_scale_row(title, lower, upper, step=step, digits=digits, subtitle=subtitle)
        stash(row, "_uvr_store_float", store_float)
        default_value = _DEFAULT_SETTINGS.get(key)
        if default_value is not None:
            set_scale_default_mark(row, default_value)
        fetch(row, "_uvr_scale").connect(
            "value-changed",
            lambda *_a, k=key, r=row: self._on_option_scale(k, r),
        )
        self._add_row(group, row)
        self._scale_rows[key] = row
        return self._hint(row, hint)

    def add_option_switch(self, group: typing.Any, key: typing.Any, title: typing.Any, subtitle: typing.Any=None, hint: typing.Any=None):
        """Add a switch row bound to boolean settings ``key``."""
        row = make_switch_row(title, subtitle)
        row.connect("notify::active", lambda *_a, k=key, r=row: self._on_option_switch(k, r))
        self._add_row(group, row)
        self._switch_rows[key] = row
        return self._hint(row, hint)

    def add_option_spin(self, group: typing.Any, key: typing.Any, title: typing.Any, lower: typing.Any, upper: typing.Any, step: typing.Any, digits: typing.Any=2, subtitle: typing.Any=None, hint: typing.Any=None):
        """Add a spin row bound to a numeric settings ``key`` (stored as float)."""
        adjustment = Gtk.Adjustment(lower=lower, upper=upper, step_increment=step)
        row = Adw.SpinRow(title=title, adjustment=adjustment, digits=digits)
        if subtitle:
            row.set_subtitle(subtitle)
        row.connect("notify::value", lambda *_a, k=key, r=row: self._on_option_spin(k, r))
        self._add_row(group, row)
        self._spin_rows[key] = row
        return self._hint(row, hint)

    def _on_option_combo(self, key: typing.Any, row: typing.Any) -> None:
        if self._loading:
            return
        set_flat(self.settings, key, get_combo_value(row))
        self._touch_settings()

    def _on_option_scale(self, key: typing.Any, row: typing.Any) -> None:
        if self._loading:
            return
        if fetch(row, "_uvr_store_float", False):
            set_flat(self.settings, key, round(get_scale_row_float(row), 2))
        else:
            set_flat(self.settings, key, get_scale_row_value(row))
        self._touch_settings()

    def _on_option_switch(self, key: typing.Any, row: typing.Any) -> None:
        if self._loading:
            return
        set_flat(self.settings, key, row.get_active())
        self._touch_settings()

    def _on_option_spin(self, key: typing.Any, row: typing.Any) -> None:
        if self._loading:
            return
        set_flat(self.settings, key, round(row.get_value(), 2))
        self._touch_settings()

    def _load_scales(self) -> None:
        for key, row in self._scale_rows.items():
            value = setting_for_combo(key, get_flat(self.settings, key))
            if fetch(row, "_uvr_store_float", False):
                try:
                    set_scale_row_float(row, float(value))
                except (TypeError, ValueError):
                    pass
            else:
                set_scale_row_value(row, value)

    def _save_scales(self) -> None:
        for key, row in self._scale_rows.items():
            if fetch(row, "_uvr_store_float", False):
                set_flat(self.settings, key, round(get_scale_row_float(row), 2))
            else:
                set_flat(self.settings, key, get_scale_row_value(row))

    def _load_switches(self) -> None:
        for key, row in self._switch_rows.items():
            row.set_active(bool(get_flat(self.settings, key)))

    def _save_switches(self) -> None:
        for key, row in self._switch_rows.items():
            set_flat(self.settings, key, row.get_active())

    def _load_spins(self) -> None:
        for key, row in self._spin_rows.items():
            try:
                row.set_value(float(get_flat(self.settings, key)))
            except (TypeError, ValueError):
                pass

    def _save_spins(self) -> None:
        for key, row in self._spin_rows.items():
            set_flat(self.settings, key, round(row.get_value(), 2))

    # -- Subclass hooks ---------------------------------------------------------

    def build_options(self, group: Adw.PreferencesGroup) -> None:
        """Add the basic method-specific rows to ``group``."""

    def build_advanced(self, group: Adw.PreferencesGroup) -> None:
        """Add advanced method-specific rows to the model-options inference group."""

    def build_stem_options(self, group: Adw.PreferencesGroup) -> None:
        """Append method-specific rows to the shared "Save stems" group."""

    def load_options(self) -> None:
        """Set method-specific combo rows from settings."""
        for key, row in self._option_rows.items():
            set_combo_value(
                row, setting_for_combo(key, get_flat(self.settings, key))
            )

    def save_options(self) -> None:
        """Write method-specific combo rows back to settings."""
        for key, row in self._option_rows.items():
            set_flat(self.settings, key, get_combo_value(row))

    def add_advanced_combo(self, key: typing.Any, title: typing.Any, values: typing.Any, subtitle: typing.Any=None, hint: typing.Any=None):
        return self.add_option_combo(self.advanced_group, key, title, values, subtitle, hint=hint)

    def add_advanced_scale(self, key: typing.Any, title: typing.Any, *, values: typing.Any=None, lower: typing.Any=None, upper: typing.Any=None, step: typing.Any=1, digits: typing.Any=0, subtitle: typing.Any=None, hint: typing.Any=None, store_float: typing.Any=False):
        return self.add_option_scale(
            self.advanced_group,
            key,
            title,
            values=values,
            lower=lower,
            upper=upper,
            step=step,
            digits=digits,
            subtitle=subtitle,
            hint=hint,
            store_float=store_float,
        )

    def add_advanced_switch(self, key: typing.Any, title: typing.Any, subtitle: typing.Any=None, hint: typing.Any=None):
        return self.add_option_switch(self.advanced_group, key, title, subtitle, hint=hint)

    # -- Secondary / pre-process / vocal-splitter model selection --------------

    def _add_model_combo(self, container: typing.Any, key: typing.Any, provider: typing.Any, title: typing.Any, hint: typing.Any=None):
        """Add a model-picker combo (lazily populated to avoid startup hashing).

        The combo is registered separately from :attr:`_option_rows` so its value
        is only written back once the (expensive) model list has been resolved,
        avoiding clobbering the stored tag with ``NO_MODEL``.
        """
        stored = get_flat(self.settings, key, NO_MODEL)
        initial = [NO_MODEL] if stored in (NO_MODEL, None) else [NO_MODEL, stored]
        row = make_combo_row(title, initial)
        use_wrapping_list(row)
        set_combo_value(row, stored)
        row.connect("notify::selected", lambda *_a, k=key, r=row: self._on_model_combo(k, r))
        self._add_row(container, row)
        self._model_combos.append({"row": row, "key": key, "provider": provider, "ready": False})
        return self._hint(row, hint)

    def _on_model_combo(self, key: typing.Any, row: typing.Any) -> None:
        if self._loading or getattr(self, "_populating_models", False):
            return
        entry = next((e for e in self._model_combos if e["key"] == key), None)
        if entry and not entry["ready"]:
            return
        set_flat(self.settings, key, get_combo_value(row))
        self._touch_settings()

    def _ensure_model_combos_populated(self, *_args: typing.Any) -> None:
        self._populator.ensure()

    def _populate_model_combos_now(self) -> None:
        self._populating_models = True
        try:
            for entry in self._model_combos:
                try:
                    values = entry["provider"]()
                except Exception:
                    values = []
                eligible = set(values)
                records = sorted(
                    (
                        record
                        for record in ModelIdentityService(
                            self.context.repo
                        ).records()
                        if record.installed and record.id in eligible
                    ),
                    key=lambda record: (record.display.casefold(), record.id),
                )
                tag_items = [(record.id, record.display) for record in records]
                set_combo_tag_values(entry["row"], [NO_MODEL, *tag_items])
                set_combo_value(
                    entry["row"], get_flat(self.settings, entry["key"], NO_MODEL)
                )
                entry["ready"] = True
        finally:
            self._populating_models = False

    def _bind_switch_dependents(self, switch_row: typing.Any, dependents: typing.Any) -> None:
        """Dim ``dependents`` whenever ``switch_row`` is off.

        Mirrors the pattern already used for the Ensemble algorithm rows: an
        inapplicable control stays visible but non-interactive, so the section's
        shape doesn't change as switches flip.
        """
        rows = [row for row in dependents if row is not None]

        def apply(*_args: typing.Any) -> None:
            active = switch_row.get_active()
            for row in rows:
                row.set_sensitive(active)
            # Unconditional: ``_bind_switch_dependents`` is only ever called from
            # ``_build_secondary_section``, after ``__init__`` assigns
            # ``self.settings`` -- there is no real ``MethodView`` on which this
            # would run before settings exists. ``_refresh_expander_subtitles``
            # itself is a safe no-op on a bare instance with no expanders built
            # (both ``getattr(self, "..._expander", None)`` lookups return
            # ``None`` before touching ``self.settings``).
            self._refresh_expander_subtitles()

        switch_row.connect("notify::active", apply)
        # Guarded: tests exercise this method on a bare ``__new__`` instance.
        appliers = getattr(self, "_switch_dependent_appliers", None)
        if appliers is not None:
            appliers.append(apply)
        apply()

    def _sync_switch_dependents(self) -> None:
        """Re-apply every activate-switch's dimming after settings are loaded."""
        for apply in getattr(self, "_switch_dependent_appliers", ()):
            apply()

    def _sync_secondary_slot_visibility(self) -> None:
        """Hide the secondary slots that cannot affect this run.

        ``other`` / ``bass`` / ``drums`` only ever feed the engine's four-source
        branch. Hiding rather than dimming is deliberate: the height is the
        point, and stem count is a structural fact about the run rather than a
        toggle the user is expected to flip. Stored values are untouched, so the
        slots come back populated when a four-source run is selected again.
        """
        rows_by_slot = getattr(self, "_secondary_slot_rows", None)
        if not rows_by_slot:
            return
        four_stem = four_stem_secondaries_apply(self.settings, self.method_key)
        for slot, rows in rows_by_slot.items():
            visible = True if slot == "voc_inst" else four_stem
            for row in rows:
                row.set_visible(visible)

    def sync_dynamic_option_state(self) -> None:
        """Re-evaluate option state that depends on settings edited elsewhere.

        The options sheet reuses these view instances, so settings changed on
        another page (ensemble stem pair, Demucs stem focus) must be re-read
        when the sheet opens rather than only when this view is interacted with.
        """
        self._sync_secondary_slot_visibility()
        self._refresh_expander_subtitles()

    def _refresh_expander_subtitles(self) -> None:
        """Subtitle-only half of :meth:`_sync_expander_summaries` (no expanding)."""
        secondary = getattr(self, "secondary_expander", None)
        if secondary is not None and self.secondary_prefix:
            four_stem = four_stem_secondaries_apply(self.settings, self.method_key)
            secondary.set_subtitle(
                secondary_models_summary(
                    self.settings, self.secondary_prefix, four_stem=four_stem
                )
            )
        preproc = getattr(self, "preproc_expander", None)
        if preproc is not None:
            preproc.set_subtitle(preproc_summary(self.settings))

    def _sync_expander_summaries(self) -> None:
        """Refresh subtitles, then open whatever is switched on.

        Expand only -- never auto-collapse. A section the user opened by hand
        must not be shut on them by an unrelated settings reload.

        Population of model combos is deferred to an idle while restoring: the
        expand itself stays synchronous (visual), but hashing checkpoints must
        not block ``MainWindow`` construction (tracked issue F1).
        """
        self._refresh_expander_subtitles()
        # Load-time auto-expand must open the rows immediately without hashing
        # every checkpoint on the construction path (tracked issue F1).
        with self._populator.defer():
            if (
                getattr(self, "secondary_expander", None) is not None
                and self.secondary_prefix
                and get_flat(
                    self.settings,
                    f"{self.secondary_prefix}_is_secondary_model_activate"
                )
            ):
                self.secondary_expander.set_expanded(True)
            if (
                getattr(self, "preproc_expander", None) is not None
                and self.settings.demucs.is_pre_proc_model_activate
            ):
                self.preproc_expander.set_expanded(True)

    def _build_secondary_section(self) -> None:
        repo = self.context.repo
        settings = self.settings
        # "Extra models" is a titled group holding the secondary, pre-process
        # and vocal-split selectors as sibling expander rows (each collapsed by
        # default). Per the GNOME HIG these expanders live directly in the group
        # rather than nested inside another expander: nesting expander rows adds
        # indentation levels that read as confusing, so the section stays one
        # level deep (group -> expander -> rows).
        self.secondary_group = Adw.PreferencesGroup(title="Extra models")
        group = self.secondary_group

        # Secondary models (one selector + scale per stem pair).
        if self.secondary_prefix:
            prefix = self.secondary_prefix
            self.secondary_expander = Adw.ExpanderRow(title="Secondary models")
            self.secondary_expander.connect("notify::expanded", self._ensure_model_combos_populated)
            activate = self.add_option_switch(
                self.secondary_expander,
                f"{prefix}_is_secondary_model_activate",
                "Activate secondary model",
                hint=SECONDARY_MODEL_ACTIVATE_HELP,
            )
            dependents = []
            self._secondary_slot_rows = {}
            for slot, pair, primary, secondary in _SECONDARY_SLOTS:
                model_key = f"{prefix}_{slot}_secondary_model"
                scale_key = f"{prefix}_{slot}_secondary_model_scale"
                pair_label = ui_label(pair)
                wanted = {b for b in pair.buckets() if b is not StemBucket.UNKNOWN}
                # Pair request buckets — not stem_count=1 on the UI half names,
                # which turns Other/No Other into an Instrumental request.
                provider = (
                    lambda p=primary, s=secondary, w=wanted: repo.model_list(
                        settings,
                        p,
                        s,
                        wanted_buckets=w,
                    )
                )
                combo = self._add_model_combo(
                    self.secondary_expander,
                    model_key,
                    provider,
                    pair_label,
                    hint=SECONDARY_MODEL_HELP,
                )
                scale = self.add_option_scale(
                    self.secondary_expander,
                    scale_key,
                    f"{pair_label} influence",
                    lower=0.01,
                    upper=0.99,
                    step=0.01,
                    digits=2,
                    hint=SECONDARY_MODEL_SCALE_HELP,
                    store_float=True,
                )
                dependents.extend((combo, scale))
                self._secondary_slot_rows[slot] = [combo, scale]
            self._bind_switch_dependents(activate, dependents)
            group.add(self.secondary_expander)

        # Demucs pre-process model.
        if self.has_preproc:
            self.preproc_expander = Adw.ExpanderRow(title="Pre-process model")
            self.preproc_expander.connect("notify::expanded", self._ensure_model_combos_populated)
            activate = self.add_option_switch(self.preproc_expander, "is_demucs_pre_proc_model_activate", "Activate pre-process model", hint=PRE_PROC_MODEL_ACTIVATE_HELP)
            model_row = self._add_model_combo(
                self.preproc_expander,
                "demucs_pre_proc_model",
                lambda: repo.model_list(settings, VOCAL_STEM, INST_STEM, is_no_demucs=True),
                "Pre-process model",
                hint=PRE_PROC_MODEL_HELP,
            )
            inst_mix_row = self.add_option_switch(self.preproc_expander, "is_demucs_pre_proc_model_inst_mix", "Save instrumental mixture", hint=PRE_PROC_MODEL_INST_MIX_HELP)
            self._bind_switch_dependents(activate, [model_row, inst_mix_row])
            group.add(self.preproc_expander)

        self.groups.append(self.secondary_group)

        # Model maintenance: editing an architecture's stored model parameters
        # is not an "extra model", so it gets its own group rather than sitting
        # as a fourth sibling among the model selectors.
        self.maintenance_group = Adw.PreferencesGroup(title="Model maintenance")
        self.change_row = Adw.ActionRow(
            title="Change model defaults",
            subtitle="Edit or delete a model's stored parameters",
        )
        change_button = Gtk.Button(label="Edit\u2026", valign=Gtk.Align.CENTER)
        change_button.connect("clicked", self._on_change_defaults)
        self.change_row.add_suffix(change_button)
        self.change_row.set_activatable_widget(change_button)
        self.hints.register(self.change_row, CLEAR_CACHE_HELP)
        self.maintenance_group.add(self.change_row)
        self.groups.append(self.maintenance_group)

    # -- Dialog wiring (owned entirely by the method views) --------------------

    def _window_root(self):
        """Return the top-level window to parent dialogs on.

        The view's groups are reparented between the window's columns as the
        active method or window width changes, so the root is resolved from
        whichever of this view's groups is currently mounted, falling back to
        the application's active window when none of them are.
        """
        for group in self.groups:
            root = group.get_root()
            if root is not None:
                return root
        app = Gio.Application.get_default()
        return app.get_active_window() if isinstance(app, Gtk.Application) else None

    def _on_change_defaults(self, _button: typing.Any) -> None:
        from ..dialogs.model_params import show_change_defaults_dialog

        show_change_defaults_dialog(self.context, self._window_root())
        # Stored params may have changed; refresh stem labels and model lists.
        self._invalidate_model_combos()
        self.update_stem_labels()


METHOD_VIEWS: List[Type[MethodView]] = []


def register_method_view(view_cls: Type[MethodView]) -> Type[MethodView]:
    """Register a :class:`MethodView` subclass for the window to instantiate."""
    METHOD_VIEWS.append(view_cls)
    return view_cls
