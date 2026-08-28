from __future__ import annotations
import typing

import os
from typing import Any, TYPE_CHECKING

from bundled.constants import *
from core.debug_log import trace_phase
from ml import spec_utils

from . import separator_factory
from .mix import gather_sources

if TYPE_CHECKING:
    from core.model_config import ModelConfig


def _run_seperator(seperator: typing.Any) -> Any:
    from core.separator_run import run_separate_pass

    return run_separate_pass(seperator)


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
        model=(
            getattr(secondary_model, "model_display_label", None)
            or getattr(secondary_model, "model_name", None)
            or secondary_model.model_basename
        ),
        method=secondary_model.process_method,
    ):
        if not is_pre_proc_model:
            process_iteration = process_data.process_iteration
            process_iteration()

        seperator = separator_factory.build_seperator(
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

    seperator = separator_factory.build_seperator(
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
