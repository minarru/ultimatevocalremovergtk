"""Demucs method view."""

from data.constants import (
    DEMUCS_4_STEM_OPTIONS,
    DEMUCS_ARCH_TYPE,
    DEMUCS_OVERLAP,
    DEMUCS_SEGMENTS,
    DEMUCS_SHIFTS,
    DEMUCS_STEMS_HELP,
    IS_DEMUCS_COMBINE_STEMS_HELP,
    IS_SPLIT_MODE_HELP,
    OVERLAP_HELP,
    SEGMENT_HELP,
    SHIFTS_HELP,
)

from .base import MethodView, register_method_view

_CHUNK_DEMUCS_HELP = "Process the audio in chunks to reduce memory usage (legacy option)"


@register_method_view
class DemucsView(MethodView):
    method_key = DEMUCS_ARCH_TYPE
    model_key = "demucs_model"
    stack_name = "demucs"
    title = "Demucs"
    secondary_prefix = "demucs"
    has_preproc = True
    # Demucs has its own pair of stem-only keys on the main window.
    primary_only_key = "is_primary_stem_only_Demucs"
    secondary_only_key = "is_secondary_stem_only_Demucs"

    def list_models(self):
        return self.context.repo.list_demucs_models()

    def name_mapper(self):
        return self.context.repo.demucs_name_select_MAPPER

    def build_options(self, group):
        # Phase 3 keeps the static option set; per-model 4/6/2-stem refinement is
        # handled by the engines via the selected Demucs model.
        self.add_option_combo(group, "demucs_stems", "Stem", DEMUCS_4_STEM_OPTIONS, hint=DEMUCS_STEMS_HELP)
        self.add_option_scale(group, "segment", "Segment", values=DEMUCS_SEGMENTS, hint=SEGMENT_HELP)

    def build_advanced(self, expander):
        self.add_advanced_scale(
            "shifts",
            "Shifts",
            lower=min(DEMUCS_SHIFTS),
            upper=max(DEMUCS_SHIFTS),
            step=1,
            hint=SHIFTS_HELP,
        )
        self.add_advanced_scale(
            "overlap",
            "Overlap",
            values=[str(v) for v in DEMUCS_OVERLAP],
            hint=OVERLAP_HELP,
        )
        self.add_advanced_switch("is_split_mode", "Split mode", hint=IS_SPLIT_MODE_HELP)
        self.add_advanced_switch("is_chunk_demucs", "Enable chunks", hint=_CHUNK_DEMUCS_HELP)
        self.add_advanced_switch("is_demucs_combine_stems", "Combine stems", hint=IS_DEMUCS_COMBINE_STEMS_HELP)
