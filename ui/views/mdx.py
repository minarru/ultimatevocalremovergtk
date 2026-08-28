"""MDX-Net method view.

Covers both classic MDX-Net (``.onnx`` / ``.ckpt``) and MDX23C / MDX-C
(``config_yaml``) models: the latter live in the same model directory and are
auto-detected by :class:`core.ModelConfig` (``is_mdx_c``), so the
:class:`core.JobRunner` selects ``SeperateMDXC`` vs ``SeperateMDX`` at run
time. There is therefore one MDX model dropdown here, exactly as in the Tk app.
"""

import typing

from bundled.constants import (
    ALL_STEMS,
    BASS_STEM,
    BATCH_SIZE,
    BATCH_SIZE_HELP,
    COMPENSATE_HELP,
    DEF_OPT,
    DRUM_STEM,
    INST_STEM,
    IS_DEMUCS_COMBINE_STEMS_HELP,
    IS_DENOISE_HELP,
    IS_FREQUENCY_MATCH_HELP,
    IS_INVERT_SPEC_HELP,
    MDX23_OVERLAP,
    MDX_ARCH_TYPE,
    MDX_DENOISE_OPTION,
    MDX_OVERLAP,
    MDX_SEGMENTS,
    OTHER_STEM,
    VOCAL_STEM,
    VOL_COMPENSATION,
)
from core.model_stem_semantics import (
    apply_karaoke_quick_export_default,
    recommended_export_note,
    shows_voc_inst_quick_export,
    stem_display_overrides,
)
from core.settings import Settings
from core.stems import StemId, resolve_in_sources

from ..help_text import MDX_INCLUDE_COMPLEMENT_HELP, MDX_OVERLAP_HINT, MDX_SEGMENT_SIZE_HINT
from ..settings_bind import get_flat, set_flat
from ..widget_state import fetch
from ..widgets.rows import (
    get_scale_row_value,
    make_discrete_scale_row,
    make_numeric_scale_row,
    reconfigure_discrete_scale,
    reconfigure_numeric_scale,
    set_scale_default_mark,
    set_scale_row_value,
)
from .base import MethodView, register_method_view

# Full stem universe presented in the UI. The backend intersects this with the
# selected model's actual stems, so checking a stem a model does not produce is
# simply ignored (resolving per-model stems here would require model hashing).
_MDX_STEM_OPTIONS = (
    VOCAL_STEM,
    INST_STEM,
    OTHER_STEM,
    BASS_STEM,
    DRUM_STEM,
    "Speech",
    "Music",
    "Sfx",
    "Effects",
)

_MDX_C_SEGMENT_VALUES = (DEF_OPT, *[str(v) for v in MDX_SEGMENTS])
_MDX_DEFAULTS = Settings.defaults().mdx


def mdx_c_default_segment_size(model: typing.Any) -> int | None:
    """Return MDX-C / MDX23C yaml ``inference.dim_t``, or ``None`` if unknown."""
    if not model or not getattr(model, "is_mdx_c", False):
        return None
    configs = getattr(model, "mdx_c_configs", None)
    if configs is None:
        return None
    inference = getattr(configs, "inference", None)
    dim_t = getattr(inference, "dim_t", None) if inference is not None else None
    if dim_t is None:
        return None
    try:
        value = int(dim_t)
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


def nearest_mdx_segment_size(dim_t: int) -> int:
    """Snap ``dim_t`` to the closest value on the Segment size slider."""
    if not MDX_SEGMENTS:
        return dim_t
    return min(MDX_SEGMENTS, key=lambda value: (abs(value - dim_t), value))


def mdx_stem_selection_is_stale(stems: typing.Sequence[str], stored: typing.Any) -> bool:
    """Whether a persisted ``mdx.stems`` value no longer names one of ``stems``.

    ``stored`` is written from canonical UVR stem labels (e.g. ``Vocals``) by
    the save-stems widget, while ``stems`` (a model's own ``mdx_model_stems``)
    carries a checkpoint's own yaml casing -- commonly lowercase (``vocals``)
    for community MDX-C multi-stem models. A raw membership check flags a
    merely differently-cased match as stale and resets the selection to
    ``ALL_STEMS``, silently discarding it.
    """
    if not stored or stored == ALL_STEMS:
        return False
    lookup = {str(stem): stem for stem in stems}
    return resolve_in_sources(lookup, StemId(str(stored))) is None


@register_method_view
class MDXView(MethodView):
    method_key = MDX_ARCH_TYPE
    model_key = "mdx_net_model"
    stack_name = "mdx"
    title = "MDX-Net"
    secondary_prefix = "mdx"

    def list_models(self):
        return self.context.repo.list_mdx_models()

    def name_mapper(self):
        return self.context.repo.mdx_name_select_MAPPER

    def build_options(self, group: typing.Any):
        # Segment / overlap both follow the selected model type: classic MDX-Net
        # uses a numeric segment size and a small discrete overlap set, while
        # MDX-C exposes "Default" (yaml dim_t) on the segment slider and a 2-50
        # overlap range.
        self._segment_is_mdx_c = False
        self._overlap_is_mdx_c = False

        self.segment_row = make_numeric_scale_row("Segment size", 32, 4000, step=32, digits=0)
        fetch(self.segment_row, "_uvr_scale").connect("value-changed", self._on_segment_changed)
        group.add(self.segment_row)
        self.hints.register(self.segment_row, MDX_SEGMENT_SIZE_HINT)

        self.overlap_row = make_discrete_scale_row("Overlap", [str(v) for v in MDX_OVERLAP])
        fetch(self.overlap_row, "_uvr_scale").connect("value-changed", self._on_overlap_changed)
        group.add(self.overlap_row)
        self.hints.register(self.overlap_row, MDX_OVERLAP_HINT)

    def _overlap_key(self):
        return "overlap_mdx23" if self._overlap_is_mdx_c else "overlap_mdx"

    def _persist_segment_value(self, value: typing.Any) -> None:
        """Write segment slider state without clearing MDX-C Default across models."""
        if value is None:
            return
        if self._segment_is_mdx_c:
            if value == DEF_OPT:
                self.settings.mdx.is_mdx_c_seg_def = True
            else:
                self.settings.mdx.is_mdx_c_seg_def = False
                self.settings.mdx.segment_size = value
        elif value != DEF_OPT:
            self.settings.mdx.segment_size = value

    def _on_segment_changed(self, *_args: typing.Any):
        if self._loading:
            return
        self._persist_segment_value(get_scale_row_value(self.segment_row))
        self._touch_settings()

    def _on_overlap_changed(self, *_args: typing.Any):
        if self._loading:
            return
        value = get_scale_row_value(self.overlap_row)
        if value is not None:
            set_flat(self.settings, self._overlap_key(), value)
            self._touch_settings()

    def _apply_mdx_c_segment_default_mark(self) -> None:
        """Tick the nearest slider stop to the model's yaml segment size."""
        dim_t = mdx_c_default_segment_size(self._resolved_model)
        if dim_t is None:
            set_scale_default_mark(self.segment_row, DEF_OPT)
            return
        set_scale_default_mark(self.segment_row, str(nearest_mdx_segment_size(dim_t)))

    def _refresh_segment(self):
        """Reconfigure the segment slider for the current model type."""
        was_loading = self._loading
        self._loading = True
        try:
            if self._segment_is_mdx_c:
                reconfigure_discrete_scale(self.segment_row, _MDX_C_SEGMENT_VALUES)
                self._apply_mdx_c_segment_default_mark()
                if self.settings.mdx.is_mdx_c_seg_def:
                    set_scale_row_value(self.segment_row, DEF_OPT)
                else:
                    stored = str(self.settings.mdx.segment_size)
                    if not set_scale_row_value(self.segment_row, stored):
                        set_scale_row_value(self.segment_row, str(_MDX_DEFAULTS.segment_size))
            else:
                reconfigure_numeric_scale(self.segment_row, 32, 4000, step=32, digits=0)
                set_scale_default_mark(self.segment_row, _MDX_DEFAULTS.segment_size)
                stored = self.settings.mdx.segment_size
                if not set_scale_row_value(self.segment_row, stored):
                    set_scale_row_value(self.segment_row, _MDX_DEFAULTS.segment_size)
        finally:
            self._loading = was_loading

    def _refresh_overlap(self):
        """Reconfigure the overlap slider for the current model type."""
        from ..settings_bind import setting_for_combo

        key = self._overlap_key()
        stored = setting_for_combo(key, get_flat(self.settings, key))
        was_loading = self._loading
        self._loading = True
        try:
            if self._overlap_is_mdx_c:
                reconfigure_numeric_scale(self.overlap_row, 2, max(MDX23_OVERLAP), step=1, digits=0)
                set_scale_default_mark(self.overlap_row, _MDX_DEFAULTS.overlap_mdx23)
            else:
                reconfigure_discrete_scale(self.overlap_row, [str(v) for v in MDX_OVERLAP])
                set_scale_default_mark(self.overlap_row, DEF_OPT)
            if stored is None or not set_scale_row_value(self.overlap_row, str(stored)):
                if self._overlap_is_mdx_c:
                    set_scale_row_value(self.overlap_row, str(_MDX_DEFAULTS.overlap_mdx23))
                else:
                    set_scale_row_value(self.overlap_row, DEF_OPT)
        finally:
            self._loading = was_loading

    def _configure_save_stems(self, model: typing.Any) -> None:
        routes = tuple(getattr(self, "_resolved_routes", ()) or ())
        stems: list[str] = [route.native.raw for route in routes if route.native is not None] or (
            list(getattr(model, "mdx_model_stems", []) or []) if model else []
        )
        ordered: list[str] = [s for s in _MDX_STEM_OPTIONS if s in stems]
        ordered += [s for s in stems if s not in _MDX_STEM_OPTIONS]
        if len(ordered) > 2:
            self.save_stems.configure_subset(
                stems=ordered,
                show_quick_export=shows_voc_inst_quick_export(model, ordered),
                primary_key=self.primary_only_key,
                secondary_key=self.secondary_only_key,
                has_model=True,
                stem_label_overrides=stem_display_overrides(model),
                export_semantics_note=recommended_export_note(model),
                routes=routes,
            )
        else:
            super()._configure_save_stems(model)

    def _on_model_resolved(self, model: typing.Any):
        is_mdx_c = bool(model and getattr(model, "is_mdx_c", False))
        self._segment_is_mdx_c = is_mdx_c
        self._overlap_is_mdx_c = is_mdx_c
        self._refresh_segment()
        self._refresh_overlap()
        stems = list(getattr(model, "mdx_model_stems", []) or []) if model else []
        # Match upstream UVR ``update_button_states_mdx``: 2-stem models use the
        # primary stem name in ``mdx_stems``, not ``All Stems`` (that value is
        # only meaningful for 3+ stem MDX23C models).
        if 0 < len(stems) < 3:
            self.settings.mdx.stems = stems[0]
        elif len(stems) >= 3 and mdx_stem_selection_is_stale(stems, self.settings.mdx.stems):
            self.settings.mdx.stems = ALL_STEMS
        apply_karaoke_quick_export_default(
            self.settings,
            model,
            primary_key=self.primary_only_key,
            secondary_key=self.secondary_only_key,
        )

    def load_options(self):
        super().load_options()
        self._refresh_segment()
        overlap_value = get_scale_row_value(self.overlap_row)
        if overlap_value is not None:
            set_scale_row_value(
                self.overlap_row,
                str(get_flat(self.settings, self._overlap_key(), overlap_value)),
            )

    def save_options(self):
        super().save_options()
        self._persist_segment_value(get_scale_row_value(self.segment_row))
        overlap_value = get_scale_row_value(self.overlap_row)
        if overlap_value is not None:
            set_flat(self.settings, self._overlap_key(), overlap_value)

    def build_advanced(self, group: typing.Any):
        self.add_advanced_scale(
            "mdx_batch_size", "Batch size", values=BATCH_SIZE, hint=BATCH_SIZE_HELP
        )
        self.add_option_combo(
            group, "denoise_option", "Denoise", MDX_DENOISE_OPTION, hint=IS_DENOISE_HELP
        )
        self.add_option_scale(
            group,
            "compensate",
            "Volume compensation",
            values=VOL_COMPENSATION,
            hint=COMPENSATE_HELP,
        )
        self.add_option_switch(
            group,
            "is_match_frequency_pitch",
            "Match frequency cut-off",
            hint=IS_FREQUENCY_MATCH_HELP,
        )
        self.add_option_switch(
            group, "is_invert_spec", "Spectral inversion", hint=IS_INVERT_SPEC_HELP
        )
        self.add_option_switch(
            group,
            "is_mdx23_combine_stems",
            "Combine stems (MDX23C)",
            hint=IS_DEMUCS_COMBINE_STEMS_HELP,
        )
        self.add_advanced_switch(
            "is_mdx_include_stem_complement",
            "Include complement (No X)",
            hint=MDX_INCLUDE_COMPLEMENT_HELP,
        )
