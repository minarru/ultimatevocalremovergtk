"""Demucs acquisition, native inference and ordered secondary work.

Array grafting, six-source folding and export-level adjustments deliberately
retain the legacy cache-shared references. The export planner only reads them.
"""

from __future__ import annotations

import gzip
import os
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, cast

import numpy as np

from bundled.constants import (
    DEMUCS_V1,
    DEMUCS_V2,
    DONE,
    GUITAR_STEM,
    INST_STEM,
    LOADING_MODEL,
    OTHER_STEM,
    PIANO_STEM,
    VOCAL_STEM,
)
from core.debug_log import trace_phase
from core.demucs_models import demucs_pretrained_load_name
from core.demucs_registry import validate_demucs_inference_layouts
from core.torch_checkpoint import load_torch_checkpoint
from ml import spec_utils
from vendor.demucs.apply import demucs_segments
from vendor.demucs.model_v2 import auto_load_demucs_model_v2
from vendor.demucs.pretrained import get_model as _gm

from .model_weight_cache import materialize_module
from .runtime import EngineRunContext

if TYPE_CHECKING:
    from .demucs_engine import SeperateDemucs

from .demucs_export import DemucsNativeResult


def acquire_demucs_model(
    context: EngineRunContext, device: Any, *, weight_cache: Any, cache_key: Any
) -> Any:
    options = context.demucs
    model_path = cast(str, context.identity.model_path)
    cached = weight_cache.get(cache_key)
    if cached and cached.module is not None:
        model = materialize_module(cached.module, device)
    elif options.demucs_version == DEMUCS_V1:
        checkpoint_source: Any = model_path
        if str(checkpoint_source).endswith(".gz"):
            checkpoint_source = gzip.open(model_path, "rb")
        klass, args, kwargs, state = load_torch_checkpoint(checkpoint_source)
        model = klass(*args, **kwargs)
        model.to(device)
        model.load_state_dict(state)
        model.eval()
    elif options.demucs_version == DEMUCS_V2:
        model = auto_load_demucs_model_v2(context.routing._demucs_source_list, model_path)
        model.to(device)
        model.load_state_dict(load_torch_checkpoint(model_path))
        model.eval()
    else:
        load_name = demucs_pretrained_load_name(model_path)
        model = _gm(
            name=load_name,
            repo=Path(os.path.dirname(model_path)),
        )
        model = demucs_segments(options.segment, model)
        model.to(device)
        model.eval()

    return model


def infer_demucs_native(
    self: SeperateDemucs,
    *,
    prepare_mix: Callable[..., Any],
    process_secondary_model: Callable[..., Any],
) -> DemucsNativeResult:

    source: Any = None
    inst_mix: Any = None
    inst_source: Any = None

    # Track the legacy 6-stem "fold piano/guitar into other" case so any
    # derived complement math avoids double counting.
    is_no_piano_guitar = False
    is_no_write = False
    is_no_cache = False

    if (
        self.primary_model_name == self.model_cache_key
        and isinstance(self.primary_sources, np.ndarray)
        and not self.pre_proc_model
    ):
        source = self.primary_sources
        self.load_cached_sources()
    else:
        self.start_inference_console_write()
        is_no_cache = True

    # Defer decode on stem-cache hits; load only if invert/combine needs the
    # mix in the dual/derived branch.
    mix = prepare_mix(self.audio_file) if is_no_cache else None

    if is_no_cache:
        with trace_phase(
            "separate",
            "seperate",
            engine="SeperateDemucs",
            model=self.model_display_label,
            version=self.demucs_version,
        ):
            self.write_to_console(LOADING_MODEL)
            from engines.model_weight_cache import get_weight_cache, weight_cache_key

            options = self.context.demucs
            key = weight_cache_key(
                "demucs",
                str(self.context.identity.model_path),
                self.device,
                options.demucs_version,
                options.segment,
            )
            self._weight_cache_key = key
            self.demucs = acquire_demucs_model(
                self.context,
                self.device,
                weight_cache=get_weight_cache(),
                cache_key=key,
            )

            # Pre-process instrumental-mixture: keep legacy behavior
            # (including muxing back into vocals slot) but defer any export.
            if self.pre_proc_model and self.primary_stem not in [
                VOCAL_STEM,
                INST_STEM,
            ]:
                is_no_write = True
                self.write_to_console(DONE, base_text="")
                mix_no_voc = process_secondary_model(
                    self.pre_proc_model,
                    self.process_data,
                    is_pre_proc_model=True,
                )
                inst_mix = prepare_mix(mix_no_voc[INST_STEM])
                self.process_iteration()
                self.running_inference_console_write(is_no_write=is_no_write)
                inst_source = self.demix_demucs(inst_mix)
                self.process_iteration()

            self.running_inference_console_write(
                is_no_write=is_no_write
            ) if not self.pre_proc_model else None

            if (
                self.primary_model_name == self.model_cache_key
                and isinstance(self.primary_sources, np.ndarray)
                and self.pre_proc_model
            ):
                source = self.primary_sources
            else:
                source = self.demix_demucs(mix)

            self.write_to_console(DONE, base_text="")

    if isinstance(source, np.ndarray):
        self.demucs_source_map = validate_demucs_inference_layouts(
            expected_count=self.demucs_stem_count,
            model_label=(
                self.model_display_label or self.model_name or self.model_basename or "Demucs model"
            ),
            source=source,
            inst_source=inst_source if isinstance(inst_source, np.ndarray) else None,
        )

    if isinstance(inst_source, np.ndarray):
        # Graft the pre-proc vocals slot into the main demix.
        source_reshape = spec_utils.reshape_sources(
            inst_source[self.demucs_source_map[VOCAL_STEM]],
            source[self.demucs_source_map[VOCAL_STEM]],
        )
        inst_source[self.demucs_source_map[VOCAL_STEM]] = source_reshape
        source = inst_source

    if isinstance(source, np.ndarray):
        if (
            len(source) == 6
            and self.process_data.is_ensemble_master
            or len(source) == 6
            and self.is_secondary_model
        ):
            is_no_piano_guitar = True
            six_stem_other_source = list(source)
            six_stem_other_source = [
                i
                for n, i in enumerate(source)
                if n
                in [
                    self.demucs_source_map[OTHER_STEM],
                    self.demucs_source_map[GUITAR_STEM],
                    self.demucs_source_map[PIANO_STEM],
                ]
            ]
            other_source = np.zeros_like(six_stem_other_source[0])
            for i in six_stem_other_source:
                other_source += i
            source_reshape = spec_utils.reshape_sources(
                source[self.demucs_source_map[OTHER_STEM]],
                other_source,
            )
            source[self.demucs_source_map[OTHER_STEM]] = source_reshape

    if not self.is_vocal_split_model:
        self.cache_source(source)

    return DemucsNativeResult(source, mix, self.demucs_source_map, is_no_piano_guitar, inst_mix)


def run_demucs_secondaries(
    self: SeperateDemucs,
    source: Any,
    *,
    process_secondary_model: Callable[..., Any],
    secondary_4_stem_slot: Callable[..., Any],
) -> dict[str, Any]:
    export_sources: dict[str, Any] = {}
    for stem_name, stem_value in self.demucs_source_map.items():
        slot_model, model_scale = secondary_4_stem_slot(
            self.secondary_model_4_stem,
            self.secondary_model_4_stem_scale,
            stem_value,
        )

        stem_source_secondary = None
        if self.is_secondary_model_activated and not self.is_secondary_model and slot_model:
            stem_source_secondary = process_secondary_model(
                slot_model,
                self.process_data,
                main_model_primary_stem_4_stem=stem_name,
                is_source_load=True,
                is_return_dual=False,
            )
            if isinstance(stem_source_secondary, np.ndarray):
                stem_source_secondary = stem_source_secondary[
                    1 if slot_model.demucs_stem_count == 2 else stem_value
                ].T
            elif type(stem_source_secondary) is dict:
                # 2-source Demucs secondary dicts must always take
                # Vocals (legacy ndarray index 1 behavior).
                if slot_model.demucs_stem_count == 2:
                    stem_source_secondary = stem_source_secondary.get(VOCAL_STEM)
                else:
                    stem_source_secondary = stem_source_secondary[stem_name]

        stem_source = source[stem_value].T
        export_sources[stem_name] = self.process_secondary_stem(
            stem_source,
            secondary_model_source=stem_source_secondary,
            model_scale=model_scale,
        )

    return export_sources
