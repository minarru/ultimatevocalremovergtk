"""Demucs method view."""
import typing

from bundled.constants import (
    ALL_STEMS,
    DEMUCS_4_STEM_OPTIONS,
    DEMUCS_6_STEM_MODEL,
    DEMUCS_6_STEM_OPTIONS,
    DEMUCS_ARCH_TYPE,
    DEMUCS_OVERLAP,
    DEMUCS_SEGMENTS,
    DEMUCS_SHIFTS,
    DEMUCS_UVR_MODEL,
    IS_DEMUCS_COMBINE_STEMS_HELP,
    IS_SPLIT_MODE_HELP,
    OVERLAP_HELP,
    SEGMENT_HELP,
    SHIFTS_HELP,
    VOCAL_STEM,
)

from core.model_stem_semantics import recommended_export_note

from core.stem_selection import _FOCUS_INSTRUMENTAL, _FOCUS_VOCALS
from .base import MethodView, register_method_view


def _demucs_focus_entries(model: typing.Any, model_name: str) -> list:
    if DEMUCS_6_STEM_MODEL in model_name or getattr(model, "demucs_stem_count", 4) == 6:
        options = DEMUCS_6_STEM_OPTIONS
    else:
        options = DEMUCS_4_STEM_OPTIONS
    entries = []
    for entry in options:
        if entry == ALL_STEMS:
            entries.append(ALL_STEMS)
        elif entry == VOCAL_STEM:
            entries.extend([_FOCUS_INSTRUMENTAL, _FOCUS_VOCALS])
        else:
            entries.append(entry)
    return entries


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

    def build_options(self, group: typing.Any):
        self.add_option_scale(group, "segment", "Segment", values=DEMUCS_SEGMENTS, hint=SEGMENT_HELP)

    def _configure_save_stems(self, model: typing.Any) -> None:
        model_name = self.selected_model() or ""
        if model and (DEMUCS_UVR_MODEL in model_name or getattr(model, "demucs_stem_count", 4) == 2):
            super()._configure_save_stems(model)
            return
        stem_count = getattr(model, "demucs_stem_count", 4) if model else 4
        self.save_stems.configure_demucs(
            focus_stems=_demucs_focus_entries(model, model_name),
            primary_key=self.primary_only_key,
            secondary_key=self.secondary_only_key,
            has_model=True,
            demucs_stem_count=stem_count,
            export_semantics_note=recommended_export_note(model),
        )

    def save_options(self):
        super().save_options()
        if self.save_stems.mode == "demucs":
            self.save_stems.persist_to_settings()

    def build_advanced(self, group: typing.Any):
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
        # Legacy "Enable chunks" (is_chunk_demucs) is unused by the engine; omit from UI.
        self.add_advanced_switch("is_demucs_combine_stems", "Combine stems", hint=IS_DEMUCS_COMBINE_STEMS_HELP)
