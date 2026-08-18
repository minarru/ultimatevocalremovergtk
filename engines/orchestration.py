from __future__ import annotations
import typing

import os
from typing import Any, TYPE_CHECKING

from bundled.constants import *
from core.debug_log import trace_phase
from core.inference_cleanup import release_separator
from ml import spec_utils

from .mix import gather_sources

if TYPE_CHECKING:
    from core.model_config import ModelConfig


def _engine_classes():
    from .demucs_engine import SeperateDemucs
    from .mdx import SeperateMDX
    from .mdx_c import SeperateMDXC
    from .vr import SeperateVR

    return SeperateVR, SeperateMDX, SeperateMDXC, SeperateDemucs


def _build_seperator(
    model: Any,
    process_data: typing.Any,
    *,
    main_model_primary_stem_4_stem: typing.Any=None,
    main_process_method: typing.Any=None,
    is_return_dual: typing.Any=True,
    main_model_primary: typing.Any=None,
    vocal_stem_path: typing.Any=None,
    master_inst_source: typing.Any=None,
    master_vocal_source: typing.Any=None,
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


def _run_seperator(seperator: typing.Any) -> Any:
    try:
        return seperator.seperate()
    finally:
        release_separator(seperator)


def process_secondary_model(
    secondary_model: ModelConfig,
    process_data: typing.Any,
    main_model_primary_stem_4_stem: typing.Any=None,
    is_source_load: typing.Any=False,
    main_process_method: typing.Any=None,
    is_pre_proc_model: typing.Any=False,
    is_return_dual: typing.Any=True,
    main_model_primary: typing.Any=None,
) -> Any:
    with trace_phase(
        "separate",
        "secondary_model",
        model=secondary_model.model_basename,
        method=secondary_model.process_method,
    ):
        if not is_pre_proc_model:
            process_iteration = process_data.process_iteration
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
            primary_stem = str(secondary_model.primary_model_primary_stem or "")
            return gather_sources(
                primary_stem, secondary_stem(primary_stem), secondary_sources
            )
        return secondary_sources


def process_chain_model(
    secondary_model: ModelConfig,
    process_data: typing.Any,
    vocal_stem_path: typing.Any,
    master_vocal_source: typing.Any,
    master_inst_source: typing.Any=None,
    *,
    vocal_stem_base: str | None = None,
):
    process_iteration = process_data.process_iteration
    process_iteration()

    if secondary_model.bv_model_rebalance:
        vocal_source = spec_utils.reduce_mix_bv(master_inst_source, master_vocal_source, reduction_rate=secondary_model.bv_model_rebalance)
    else:
        vocal_source = master_vocal_source

    if vocal_stem_base is not None:
        vocal_base = vocal_stem_base
    elif vocal_stem_path:
        vocal_base = os.path.splitext(os.path.basename(vocal_stem_path))[0]
    else:
        vocal_base = "audio"
    vocal_stem_path = [vocal_source, vocal_base]

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
