from __future__ import annotations
import typing
from typing import Any, cast, TYPE_CHECKING

import gc
import gzip
import math
import os
from pathlib import Path

import librosa
import numpy as np
import onnxruntime as ort
import pydub
import soundfile as sf
import torch
import torch.nn as nn
import warnings
from onnx import load
from onnx2pytorch import ConvertModel

from bundled.constants import *
from bundled.error_handling import *
from core.debug_log import debug, trace_phase
from core.demucs_registry import validate_demucs_inference_layouts
from core.demucs_models import demucs_pretrained_load_name
from core.stems import (
    StemBucket,
    StemRouteKind,
    exports_named_stem,
    route_matches_stem,
    run_export_routes,
    stem_concept,
)
from core.torch_checkpoint import load_torch_checkpoint
from ml import spec_utils
import ml.mdxnet as MdxnetSet

from .base import SeperateAttributes
from .mix import prepare_mix, gather_sources, rerun_mp3
from .vr_utils import vr_denoiser, loading_mix

if TYPE_CHECKING:
    from core.model_config import ModelConfig
    from engines.stem_writer import ExportPlan

cpu = torch.device('cpu')
warnings.filterwarnings("ignore")

from vendor.demucs.apply import apply_model, demucs_segments
from vendor.demucs.hdemucs import HDemucs
from vendor.demucs.model_v2 import auto_load_demucs_model_v2
from vendor.demucs.pretrained import get_model as _gm
from vendor.demucs.utils import apply_model_v1, apply_model_v2
from .orchestration import process_secondary_model


def secondary_4_stem_slot(
    secondary_models: Any,
    secondary_scales: Any,
    stem_value: int,
) -> tuple[Any, Any]:
    """Return ``(model, scale)`` for one 4-stem slot, or ``(None, None)``.

    Each stem resolves independently. Secondary models are configured per stem
    and ``is_secondary_model_activated`` is true when *any* stem has one, so a
    stem with no model of its own must come back empty rather than inherit the
    previous stem's model or blend scale — otherwise it gets mixed with another
    stem's audio. Out-of-range slots (guitar/piano in 6-stem output) are empty
    too; only the four base stems have secondary entries.
    """
    if not secondary_models or stem_value < 0 or stem_value >= len(secondary_models):
        return None, None
    model = secondary_models[stem_value]
    if not model:
        return None, None
    scale = (
        secondary_scales[stem_value]
        if secondary_scales is not None and stem_value < len(secondary_scales)
        else None
    )
    return model, scale


class SeperateDemucs(SeperateAttributes):
    def seperate(
        self,
    ) -> ExportPlan:
        self.demucs: Any
        samplerate = 44100

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
                from engines.model_weight_cache import (
                    get_weight_cache,
                    materialize_module,
                    weight_cache_key,
                )

                key = weight_cache_key(
                    "demucs",
                    str(self.model_path),
                    self.device,
                    self.demucs_version,
                    self.segment,
                )
                self._weight_cache_key = key
                cached = get_weight_cache().get(key)
                if cached and cached.module is not None:
                    self.demucs = materialize_module(cached.module, self.device)
                elif self.demucs_version == DEMUCS_V1:
                    checkpoint_source: Any = self.model_path
                    if str(checkpoint_source).endswith(".gz"):
                        checkpoint_source = gzip.open(self.model_path, "rb")
                    klass, args, kwargs, state = load_torch_checkpoint(
                        checkpoint_source
                    )
                    self.demucs = klass(*args, **kwargs)
                    self.demucs.to(self.device)
                    self.demucs.load_state_dict(state)
                    self.demucs.eval()
                elif self.demucs_version == DEMUCS_V2:
                    self.demucs = auto_load_demucs_model_v2(
                        self.demucs_source_list, self.model_path
                    )
                    self.demucs.to(self.device)
                    self.demucs.load_state_dict(load_torch_checkpoint(self.model_path))
                    self.demucs.eval()
                else:
                    load_name = demucs_pretrained_load_name(self.model_path)
                    self.demucs = _gm(
                        name=load_name,
                        repo=Path(os.path.dirname(self.model_path)),
                    )
                    self.demucs = demucs_segments(self.segment, self.demucs)
                    self.demucs.to(self.device)
                    self.demucs.eval()

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
                    self.model_display_label
                    or self.model_name
                    or self.model_basename
                    or "Demucs model"
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

        def _demucs_map_key(stem: str) -> str | None:
            if stem in self.demucs_source_map:
                return stem
            want = str(stem).casefold()
            for key in self.demucs_source_map:
                if str(key).casefold() == want:
                    return str(key)
            return None

        export_routes = run_export_routes(self)
        native_export = tuple(route for route in export_routes if route.native is not None)

        if native_export:
            write_all_sources = (
                (len(native_export) == len(self.demucs_source_map) and not self.process_data.is_ensemble_master)
                or (self.is_4_stem_ensemble and not self.is_return_dual)
            )
        else:
            write_all_sources = (
                (self.demucs_stems == ALL_STEMS and not self.process_data.is_ensemble_master)
                or (self.is_4_stem_ensemble and not self.is_return_dual)
            )

        # ---------------------------------------------------------------------
        # Write-all mode: build a full native-keyed, channel-last sources map.
        # ---------------------------------------------------------------------
        if write_all_sources:
            if isinstance(source, np.ndarray) and (
                self.is_match_mix_level or self.is_prevent_export_clipping
            ):
                if mix is None:
                    mix = prepare_mix(self.audio_file)
                stem_dict = {
                    stem_name: source[stem_value]
                    for stem_name, stem_value in self.demucs_source_map.items()
                }
                self.apply_export_stem_levels(stem_dict, mix)
                for stem_name, stem_value in self.demucs_source_map.items():
                    source[stem_value] = stem_dict[stem_name]

            export_sources: dict[str, Any] = {}
            for stem_name, stem_value in self.demucs_source_map.items():
                slot_model, model_scale = secondary_4_stem_slot(
                    self.secondary_model_4_stem,
                    self.secondary_model_4_stem_scale,
                    stem_value,
                )

                stem_source_secondary = None
                if (
                    self.is_secondary_model_activated
                    and not self.is_secondary_model
                    and slot_model
                ):
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

            # Derived instrumental complement is required by nested secondary
            # gather/pre-proc callers on 4/6-stem Demucs.
            if self.is_secondary_model or self.is_pre_proc_model:
                if isinstance(source, np.ndarray) and len(source) > 2:
                    vocals_idx = self.demucs_source_map[VOCAL_STEM]
                    stem_count = source.shape[0]
                    if stem_count == 6 and is_no_piano_guitar:
                        max_idx = stem_count - 2
                        indices = [i for i in range(max_idx) if i != vocals_idx]
                    else:
                        indices = [i for i in range(stem_count) if i != vocals_idx]
                    instrumental = np.zeros_like(source[0])
                    for i in indices:
                        instrumental += source[i]
                    export_sources[INST_STEM] = instrumental.T

            split_sources: dict[str, Any] = {}
            if not self.is_sec_bv_rebalance and VOCAL_STEM in export_sources:
                split_sources = {VOCAL_STEM: export_sources[VOCAL_STEM]}

            from engines.stem_writer import ExportPlan

            plan = ExportPlan(
                sources=export_sources,
                samplerate=samplerate,
                split_sources=split_sources,
            )
            if self.is_secondary_model or self.is_pre_proc_model:
                plan.return_sources = export_sources
            return plan

        # ---------------------------------------------------------------------
        # Focused/dual mode: build native + derived maps, then export.
        # ---------------------------------------------------------------------
        secondary_source_primary = None
        secondary_source_secondary = None
        if self.is_secondary_model_activated and self.secondary_model:
            (
                secondary_source_primary,
                secondary_source_secondary,
            ) = process_secondary_model(
                self.secondary_model,
                self.process_data,
                main_process_method=self.process_method,
            )

        write_secondary = any(
            route.kind is StemRouteKind.DERIVED for route in export_routes
        ) or exports_named_stem(self, self.secondary_stem)

        extra_sources: dict[str, Any] = {}
        extra_inst_mix = 0
        if (
            write_secondary
            and self.is_demucs_pre_proc_model_inst_mix
            and self.pre_proc_model
            and not self.is_4_stem_ensemble
        ):
            extra_inst_mix = 1

        native_route = next((route for route in export_routes if route.native is not None), None)
        primary_key = (
            native_route.native.raw
            if native_route is not None and native_route.native is not None
            else self.primary_stem
        )
        primary_map_key = (
            _demucs_map_key(primary_key)
            or _demucs_map_key(self.primary_stem)
            or self.primary_stem
        )

        def _derive_secondary_source(
            *,
            raw_mixture: Any,
            is_inst_mixture: bool,
        ) -> Any:
            """Mirror legacy `secondary_save`, but return an array."""
            assert isinstance(source, np.ndarray)
            if self.is_demucs_combine_stems:
                # Combine stems by summing everything except the chosen primary.
                source_list = list(source)
                if is_inst_mixture:
                    source_list = [
                        i
                        for n, i in enumerate(source_list)
                        if n
                        not in [
                            self.demucs_source_map[primary_map_key],
                            self.demucs_source_map[VOCAL_STEM],
                        ]
                    ]
                else:
                    source_list.pop(self.demucs_source_map[primary_map_key])

                if is_no_piano_guitar:
                    source_list = source_list[: len(source_list) - 2]

                derived = np.zeros_like(source_list[0])
                for i in source_list:
                    derived += i
                return derived.T

            # Subtract/mirror complements from the original mix.
            if not isinstance(raw_mixture, np.ndarray):
                if mix is None:
                    raw_mixture = prepare_mix(self.audio_file)
                else:
                    raw_mixture = mix
            stem_primary = source[self.demucs_source_map[primary_map_key]]

            if self.is_invert_spec:
                return spec_utils.invert_stem(raw_mixture, stem_primary)

            raw_mixture = spec_utils.reshape_sources(stem_primary, raw_mixture)
            return -stem_primary.T + raw_mixture.T

        dual_export_sources: dict[str, Any] = {}
        primary_source_map: dict[str, Any] = {}
        secondary_source_map: dict[str, Any] = {}

        if write_secondary:
            derived_label = next(
                (route.label for route in export_routes if route.kind is StemRouteKind.DERIVED),
                self.secondary_stem,
            )

            derived = _derive_secondary_source(raw_mixture=mix, is_inst_mixture=False)
            blended = self.process_secondary_stem(
                derived, secondary_source_secondary
            )
            secondary_source_map[self.secondary_stem] = blended
            dual_export_sources[derived_label] = blended
            dual_export_sources[self.secondary_stem] = blended

            if extra_inst_mix:
                sidecar_key = f"{self.secondary_stem} {INST_STEM}"
                extra_sources[sidecar_key] = _derive_secondary_source(
                    raw_mixture=inst_mix, is_inst_mixture=True
                )

        for route in native_export:
            if write_secondary and route_matches_stem(
                route, self.secondary_stem, self
            ):
                continue
            native_raw = route.native.raw if route.native is not None else self.primary_stem
            map_key = _demucs_map_key(native_raw)
            if map_key is None:
                continue
            primary_source = source[self.demucs_source_map[map_key]].T
            blended = self.process_secondary_stem(
                primary_source, secondary_source_primary
            )
            primary_source_map[map_key] = blended
            dual_export_sources[map_key] = blended

        if not native_export and exports_named_stem(self, self.primary_stem):
            primary_source = source[self.demucs_source_map[primary_map_key]].T
            blended = self.process_secondary_stem(
                primary_source, secondary_source_primary
            )
            primary_source_map[self.primary_stem] = blended
            dual_export_sources[self.primary_stem] = blended

        secondary_sources = {**primary_source_map, **secondary_source_map}

        from engines.stem_writer import ExportPlan

        plan = ExportPlan(
            sources=dual_export_sources,
            samplerate=samplerate,
            extra_sources=extra_sources,
            split_sources=secondary_sources,
        )
        if self.is_secondary_model or self.is_pre_proc_model:
            plan.return_sources = secondary_sources
        return plan
    
    def demix_demucs(self, mix: typing.Any):
        with trace_phase("separate", "demix_demucs", engine="SeperateDemucs", model=self.model_display_label):
            org_mix = mix
            sources: Any = None
            # See SeperateMDX.demix: bound unconditionally, reassigned and read
            # back only under ``is_pitch_change``.
            sr_pitched = 44100

            if self.is_pitch_change:
                mix, sr_pitched = spec_utils.change_pitch_semitones(mix, 44100, semitone_shift=-self.semitone_shift)

            mix = torch.as_tensor(mix, dtype=torch.float32, device=self.device)
            ref = mix.mean(0)
            mix_infer = (mix - ref.mean()) / ref.std()

            # Demucs hybrid nets are not fp16-safe under torch.autocast (NaN stems).
            # UVR_AUTOCAST still applies to VR / MDX / Roformer paths.
            with torch.inference_mode():
                self.check_run_control()
                if self.demucs_version == DEMUCS_V1:
                    sources = apply_model_v1(
                        self.demucs,
                        mix_infer,
                        self.shifts,
                        self.is_split_mode,
                        set_progress_bar=self.set_progress_bar,
                    )
                elif self.demucs_version == DEMUCS_V2:
                    sources = apply_model_v2(
                        self.demucs,
                        mix_infer,
                        self.shifts,
                        self.is_split_mode,
                        self.overlap,
                        set_progress_bar=self.set_progress_bar,
                    )
                else:
                    sources = cast(Any, apply_model(
                        self.demucs,
                        mix_infer[None],
                        self.shifts,
                        self.is_split_mode,
                        self.overlap,
                        static_shifts=1 if self.shifts == 0 else self.shifts,
                        set_progress_bar=self.set_progress_bar,
                        device=self.device,
                    ))[0]

            sources = (sources.float() * ref.std() + ref.mean()).cpu().numpy()
            sources[[0, 1]] = sources[[1, 0]]

            if self.is_pitch_change:
                sources = np.stack([self.pitch_fix(stem, sr_pitched, org_mix) for stem in sources])

            return sources
