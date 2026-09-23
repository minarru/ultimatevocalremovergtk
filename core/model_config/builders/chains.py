from __future__ import annotations

from typing import TYPE_CHECKING

from bundled.constants import (
    ALL_STEMS,
    DEMUCS_4_SOURCE_LIST,
    DEMUCS_ARCH_TYPE,
)

from .inputs import ModelBuildInputs

if TYPE_CHECKING:
    from ..config import ModelConfig
from ..determine import process_determine_demucs_pre_proc_model


def build_secondary_chain(model: ModelConfig, inputs: ModelBuildInputs) -> None:
    is_secondary_model = inputs.is_secondary_model
    demucs = inputs.settings.demucs

    is_secondary_activated_and_status = model.is_secondary_model_activated and model.model_status
    is_demucs = model.process_method == DEMUCS_ARCH_TYPE
    is_all_stems = demucs.stems == ALL_STEMS
    # The four per-stem Demucs secondary slots only exist on a model that
    # actually emits four (or six) sources. ``active_model_paths`` widens to
    # them on exactly that condition (``4_stem``/``6_stem`` layout), so a
    # 2-source model here would resolve slots planning never declared.
    is_valid_ensemble = (
        not model.is_ensemble_mode and is_all_stems and is_demucs and model.demucs_stem_count >= 4
    )
    is_multi_stem_ensemble_demucs = model.is_multi_stem_ensemble and is_demucs

    if is_secondary_activated_and_status:
        if is_valid_ensemble or model.is_4_stem_ensemble or is_multi_stem_ensemble_demucs:
            for key in DEMUCS_4_SOURCE_LIST:
                model.secondary_model_data(key)
                model.secondary_model_4_stem.append(model.secondary_model)
                model.secondary_model_4_stem_scale.append(model.secondary_model_scale)
                model.secondary_model_4_stem_names.append(key)
            model.demucs_4_stem_added_count = sum(
                i is not None for i in model.secondary_model_4_stem
            )
            model.is_secondary_model_activated = any(
                i is not None for i in model.secondary_model_4_stem
            )
            model.demucs_4_stem_added_count -= 1 if model.is_secondary_model_activated else 0
            if model.is_secondary_model_activated:
                model.secondary_model_4_stem_model_names_list = [
                    (getattr(i, "backend_name", None) or getattr(i, "model_basename", None))
                    if i is not None
                    else None
                    for i in model.secondary_model_4_stem
                ]
                model.is_demucs_4_stem_secondaries = True
        else:
            primary_stem = (
                model.ensemble_primary_stem
                if model.is_ensemble_mode and is_demucs
                else model.primary_stem
            )
            model.secondary_model_data(primary_stem)

    if model.process_method == DEMUCS_ARCH_TYPE and not is_secondary_model:
        if model.demucs_stem_count >= 3 and model.pre_proc_model_activated:
            model.pre_proc_model = process_determine_demucs_pre_proc_model(
                model.settings,
                model.repo,
                model.primary_stem,
                model.model_dependencies,
            )
            model.pre_proc_model_activated = True if model.pre_proc_model else False
            model.is_demucs_pre_proc_model_inst_mix = (
                demucs.is_pre_proc_model_inst_mix if model.pre_proc_model else False
            )
