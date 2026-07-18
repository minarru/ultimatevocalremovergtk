"""MDX-Net method view.

Covers both classic MDX-Net (``.onnx`` / ``.ckpt``) and MDX23C / MDX-C
(``config_yaml``) models: the latter live in the same model directory and are
auto-detected by :class:`core.ModelData` (``is_mdx_c``), so the
:class:`core.JobRunner` selects ``SeperateMDXC`` vs ``SeperateMDX`` at run
time. There is therefore one MDX model dropdown here, exactly as in the Tk app.
"""

from bundled.constants import (
    ALL_STEMS,
    BASS_STEM,
    BATCH_SIZE,
    BATCH_SIZE_HELP,
    COMPENSATE_HELP,
    DEFAULT_DATA,
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

from .base import MethodView, register_method_view
from ..help_text import MDX_INCLUDE_COMPLEMENT_HELP, MDX_OVERLAP_HINT, MDX_SEGMENT_SIZE_HINT
from ..widgets.rows import (
    get_scale_row_value,
    make_discrete_scale_row,
    make_numeric_scale_row,
    reconfigure_discrete_scale,
    reconfigure_numeric_scale,
    set_scale_default_mark,
    set_scale_row_value,
)

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

    def build_options(self, group):
        # Segment / overlap both follow the selected model type: classic MDX-Net
        # uses a numeric segment size and a small discrete overlap set, while
        # MDX-C exposes "Default" (yaml dim_t) on the segment slider and a 2-50
        # overlap range.
        self._segment_is_mdx_c = False
        self._overlap_is_mdx_c = False

        self.segment_row = make_numeric_scale_row("Segment size", 32, 4000, step=32, digits=0)
        self.segment_row._uvr_scale.connect("value-changed", self._on_segment_changed)
        group.add(self.segment_row)
        self.hints.register(self.segment_row, MDX_SEGMENT_SIZE_HINT)

        self.overlap_row = make_discrete_scale_row("Overlap", [str(v) for v in MDX_OVERLAP])
        self.overlap_row._uvr_scale.connect("value-changed", self._on_overlap_changed)
        group.add(self.overlap_row)
        self.hints.register(self.overlap_row, MDX_OVERLAP_HINT)

    def _overlap_key(self):
        return "overlap_mdx23" if self._overlap_is_mdx_c else "overlap_mdx"

    def _persist_segment_value(self, value) -> None:
        """Write segment slider state without clearing MDX-C Default across models."""
        if value is None:
            return
        if self._segment_is_mdx_c:
            if value == DEF_OPT:
                self.settings.set("is_mdx_c_seg_def", True)
            else:
                self.settings.set("is_mdx_c_seg_def", False)
                self.settings.set("mdx_segment_size", value)
        elif value != DEF_OPT:
            self.settings.set("mdx_segment_size", value)

    def _on_segment_changed(self, *_args):
        if self._loading:
            return
        self._persist_segment_value(get_scale_row_value(self.segment_row))
        self._on_settings_changed()

    def _on_overlap_changed(self, *_args):
        if self._loading:
            return
        value = get_scale_row_value(self.overlap_row)
        if value is not None:
            self.settings.set(self._overlap_key(), value)
            self._on_settings_changed()

    def _refresh_segment(self):
        """Reconfigure the segment slider for the current model type."""
        was_loading = self._loading
        self._loading = True
        try:
            if self._segment_is_mdx_c:
                reconfigure_discrete_scale(self.segment_row, _MDX_C_SEGMENT_VALUES)
                set_scale_default_mark(self.segment_row, DEF_OPT)
                if self.settings.get("is_mdx_c_seg_def"):
                    set_scale_row_value(self.segment_row, DEF_OPT)
                else:
                    stored = str(self.settings.get("mdx_segment_size", DEFAULT_DATA["mdx_segment_size"]))
                    if not set_scale_row_value(self.segment_row, stored):
                        set_scale_row_value(self.segment_row, str(DEFAULT_DATA["mdx_segment_size"]))
            else:
                reconfigure_numeric_scale(self.segment_row, 32, 4000, step=32, digits=0)
                set_scale_default_mark(self.segment_row, DEFAULT_DATA["mdx_segment_size"])
                stored = self.settings.get("mdx_segment_size", DEFAULT_DATA["mdx_segment_size"])
                if not set_scale_row_value(self.segment_row, stored):
                    set_scale_row_value(self.segment_row, DEFAULT_DATA["mdx_segment_size"])
        finally:
            self._loading = was_loading

    def _refresh_overlap(self):
        """Reconfigure the overlap slider for the current model type."""
        stored = self.settings.get(self._overlap_key())
        was_loading = self._loading
        self._loading = True
        try:
            if self._overlap_is_mdx_c:
                reconfigure_numeric_scale(self.overlap_row, 2, max(MDX23_OVERLAP), step=1, digits=0)
                set_scale_default_mark(self.overlap_row, DEFAULT_DATA["overlap_mdx23"])
            else:
                reconfigure_discrete_scale(self.overlap_row, [str(v) for v in MDX_OVERLAP])
                set_scale_default_mark(self.overlap_row, DEFAULT_DATA["overlap_mdx"])
            if stored is None or not set_scale_row_value(self.overlap_row, str(stored)):
                if self._overlap_is_mdx_c:
                    set_scale_row_value(self.overlap_row, str(DEFAULT_DATA["overlap_mdx23"]))
                else:
                    set_scale_row_value(self.overlap_row, str(MDX_OVERLAP[0]))
        finally:
            self._loading = was_loading

    def _configure_save_stems(self, model) -> None:
        stems = list(getattr(model, "mdx_model_stems", []) or []) if model else []
        ordered = [s for s in _MDX_STEM_OPTIONS if s in stems]
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
            )
        else:
            super()._configure_save_stems(model)

    def _on_model_resolved(self, model):
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
            self.settings.set("mdx_stems", stems[0])
        elif len(stems) >= 3 and self.settings.get("mdx_stems") not in (*stems, ALL_STEMS):
            self.settings.set("mdx_stems", ALL_STEMS)
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
            set_scale_row_value(self.overlap_row, str(self.settings.get(self._overlap_key(), overlap_value)))

    def save_options(self):
        super().save_options()
        if self.save_stems.mode == "subset":
            self.save_stems.persist_to_settings()
        self._persist_segment_value(get_scale_row_value(self.segment_row))
        overlap_value = get_scale_row_value(self.overlap_row)
        if overlap_value is not None:
            self.settings.set(self._overlap_key(), overlap_value)

    def build_advanced(self, group):
        self.add_advanced_scale("mdx_batch_size", "Batch size", values=BATCH_SIZE, hint=BATCH_SIZE_HELP)
        self.add_option_combo(group, "denoise_option", "Denoise", MDX_DENOISE_OPTION, hint=IS_DENOISE_HELP)
        self.add_option_scale(group, "compensate", "Volume compensation", values=VOL_COMPENSATION, hint=COMPENSATE_HELP)
        self.add_option_switch(group, "is_match_frequency_pitch", "Match frequency cut-off", hint=IS_FREQUENCY_MATCH_HELP)
        self.add_option_switch(group, "is_invert_spec", "Spectral inversion", hint=IS_INVERT_SPEC_HELP)
        self.add_option_switch(group, "is_mdx23_combine_stems", "Combine stems (MDX23C)", hint=IS_DEMUCS_COMBINE_STEMS_HELP)
        self.add_advanced_switch(
            "is_mdx_include_stem_complement",
            "Include complement (No X)",
            hint=MDX_INCLUDE_COMPLEMENT_HELP,
        )
