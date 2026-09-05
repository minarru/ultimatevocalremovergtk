from __future__ import annotations

from typing import TYPE_CHECKING

from bundled.constants import (
    ALL_STEMS,
    DEF_OPT,
    DEMUCS_2_SOURCE,
    DEMUCS_2_SOURCE_MAPPER,
    DEMUCS_4_SOURCE,
    DEMUCS_4_SOURCE_MAPPER,
    DEMUCS_6_SOURCE,
    DEMUCS_6_SOURCE_MAPPER,
    DEMUCS_V1,
    DEMUCS_V2,
    DEMUCS_V3,
    DEMUCS_V4,
    INST_STEM,
    PRIMARY_STEM,
    VOCAL_STEM,
    secondary_stem,
)

from .inputs import ModelBuildInputs

if TYPE_CHECKING:
    from ..config import ModelConfig


def build_demucs_options(model: ModelConfig, inputs: ModelBuildInputs) -> None:
    is_secondary_model = inputs.is_secondary_model
    demucs = inputs.settings.demucs

    model.is_secondary_model_activated = (
        demucs.is_secondary_model_activate if not is_secondary_model else False
    )
    if not model.is_ensemble_mode:
        model.pre_proc_model_activated = (
            demucs.is_pre_proc_model_activate
            if demucs.stems not in [VOCAL_STEM, INST_STEM]
            else False
        )
    model.shifts = int(demucs.shifts)
    model.is_split_mode = demucs.is_split_mode
    # Engine ``demucs_segments`` expects the legacy ``Default`` label.
    model.segment = DEF_OPT if demucs.segment is None else str(demucs.segment)
    model.get_demucs_model_data()
    model.get_demucs_model_path()


def resolve_demucs_layout(model: ModelConfig) -> None:
    spec = model.demucs if getattr(model, "demucs", None) is not None else None
    if spec is None:
        raise ValueError(f"{model.canonical_id} is missing Demucs version/layout metadata")
    model.demucs_version = {
        "v1": DEMUCS_V1,
        "v2": DEMUCS_V2,
        "v3": DEMUCS_V3,
        "v4": DEMUCS_V4,
    }[spec.version]
    if spec.source_layout == "2_stem":
        model.demucs_source_list, model.demucs_source_map, model.demucs_stem_count = (
            DEMUCS_2_SOURCE,
            DEMUCS_2_SOURCE_MAPPER,
            2,
        )
    elif spec.source_layout == "6_stem":
        model.demucs_source_list, model.demucs_source_map, model.demucs_stem_count = (
            DEMUCS_6_SOURCE,
            DEMUCS_6_SOURCE_MAPPER,
            6,
        )
    else:
        model.demucs_source_list, model.demucs_source_map, model.demucs_stem_count = (
            DEMUCS_4_SOURCE,
            DEMUCS_4_SOURCE_MAPPER,
            4,
        )
    if not model.is_ensemble_mode:
        model.primary_stem = PRIMARY_STEM if model.demucs_stems == ALL_STEMS else model.demucs_stems
        model.secondary_stem = secondary_stem(str(model.primary_stem or ""))
