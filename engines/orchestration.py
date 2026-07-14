from __future__ import annotations

import os
from typing import TYPE_CHECKING

from bundled.constants import *
from core.debug_log import trace_phase
from core.inference_cleanup import release_separator
from ml import spec_utils

from .mix import gather_sources

if TYPE_CHECKING:
    from core.model_data import ModelData


def _engine_classes():
    from .demucs_engine import SeperateDemucs
    from .mdx import SeperateMDX, SeperateMDXC
    from .vr import SeperateVR

    return SeperateVR, SeperateMDX, SeperateMDXC, SeperateDemucs


def _build_seperator(
    model: ModelData,
    process_data,
    *,
    main_model_primary_stem_4_stem=None,
    main_process_method=None,
    is_return_dual=True,
    main_model_primary=None,
    vocal_stem_path=None,
    master_inst_source=None,
    master_vocal_source=None,
):
    SeperateVR, SeperateMDX, SeperateMDXC, SeperateDemucs = _engine_classes()
    method = model.process_method
    if method == VR_ARCH_TYPE:
        if vocal_stem_path is not None:
            return SeperateVR(
                model,
                process_data,
                vocal_stem_path=vocal_stem_path,
                master_inst_source=master_inst_source,
                master_vocal_source=master_vocal_source,
            )
        return SeperateVR(
            model,
            process_data,
            main_model_primary_stem_4_stem=main_model_primary_stem_4_stem,
            main_process_method=main_process_method,
            main_model_primary=main_model_primary,
        )
    if method == MDX_ARCH_TYPE:
        if vocal_stem_path is not None:
            if model.is_mdx_c:
                return SeperateMDXC(
                    model,
                    process_data,
                    vocal_stem_path=vocal_stem_path,
                    master_inst_source=master_inst_source,
                    master_vocal_source=master_vocal_source,
                )
            return SeperateMDX(
                model,
                process_data,
                vocal_stem_path=vocal_stem_path,
                master_inst_source=master_inst_source,
                master_vocal_source=master_vocal_source,
            )
        if model.is_mdx_c:
            return SeperateMDXC(
                model,
                process_data,
                main_model_primary_stem_4_stem=main_model_primary_stem_4_stem,
                main_process_method=main_process_method,
                is_return_dual=is_return_dual,
                main_model_primary=main_model_primary,
            )
        return SeperateMDX(
            model,
            process_data,
            main_model_primary_stem_4_stem=main_model_primary_stem_4_stem,
            main_process_method=main_process_method,
            main_model_primary=main_model_primary,
        )
    if method == DEMUCS_ARCH_TYPE:
        if vocal_stem_path is not None:
            return SeperateDemucs(
                model,
                process_data,
                vocal_stem_path=vocal_stem_path,
                master_inst_source=master_inst_source,
                master_vocal_source=master_vocal_source,
            )
        return SeperateDemucs(
            model,
            process_data,
            main_model_primary_stem_4_stem=main_model_primary_stem_4_stem,
            main_process_method=main_process_method,
            is_return_dual=is_return_dual,
            main_model_primary=main_model_primary,
        )
    raise NotImplementedError(f"engine for '{method}' is not available")


def _run_seperator(seperator) -> object:
    try:
        return seperator.seperate()
    finally:
        release_separator(seperator)


def process_secondary_model(
    secondary_model: ModelData,
    process_data,
    main_model_primary_stem_4_stem=None,
    is_source_load=False,
    main_process_method=None,
    is_pre_proc_model=False,
    is_return_dual=True,
    main_model_primary=None,
):
    with trace_phase(
        "separate",
        "secondary_model",
        model=secondary_model.model_basename,
        method=secondary_model.process_method,
    ):
        if not is_pre_proc_model:
            process_iteration = process_data['process_iteration']
            process_iteration()

        seperator = _build_seperator(
            secondary_model,
            process_data,
            main_model_primary_stem_4_stem=main_model_primary_stem_4_stem,
            main_process_method=main_process_method,
            is_return_dual=is_return_dual,
            main_model_primary=main_model_primary,
        )
        secondary_sources = _run_seperator(seperator)

        if type(secondary_sources) is dict and not is_source_load and not is_pre_proc_model:
            return gather_sources(secondary_model.primary_model_primary_stem, secondary_stem(secondary_model.primary_model_primary_stem), secondary_sources)
        return secondary_sources


def process_chain_model(
    secondary_model: ModelData,
    process_data,
    vocal_stem_path,
    master_vocal_source,
    master_inst_source=None,
):
    process_iteration = process_data['process_iteration']
    process_iteration()

    if secondary_model.bv_model_rebalance:
        vocal_source = spec_utils.reduce_mix_bv(master_inst_source, master_vocal_source, reduction_rate=secondary_model.bv_model_rebalance)
    else:
        vocal_source = master_vocal_source

    vocal_stem_path = [vocal_source, os.path.splitext(os.path.basename(vocal_stem_path))[0]]

    seperator = _build_seperator(
        secondary_model,
        process_data,
        vocal_stem_path=vocal_stem_path,
        master_inst_source=master_inst_source,
        master_vocal_source=master_vocal_source,
    )
    secondary_sources = _run_seperator(seperator)

    if type(secondary_sources) is dict:
        return secondary_sources
    return None
