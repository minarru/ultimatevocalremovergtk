from __future__ import annotations

import typing
from dataclasses import replace
from typing import TYPE_CHECKING, Any, cast

import numpy as np
import torch

from bundled.constants import *
from bundled.error_handling import *
from core.debug_log import trace_phase
from core.stems import (
    StemRouteKind,
    exports_named_stem,
    route_matches_stem,
    run_export_routes,
)
from ml import spec_utils

from .base import SeperateAttributes
from .demucs_export import DemucsExportRequest, plan_demucs_export
from .mix import prepare_mix

if TYPE_CHECKING:
    from engines.stem_writer import ExportPlan

cpu = torch.device('cpu')

from vendor.demucs.apply import apply_model  # noqa: E402
from vendor.demucs.utils import apply_model_v1, apply_model_v2  # noqa: E402

from .demucs_runtime import infer_demucs_native, run_demucs_secondaries  # noqa: E402
from .orchestration import process_secondary_model  # noqa: E402


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
    demucs: Any
    _weight_cache_key: Any

    def seperate(
        self,
    ) -> ExportPlan:
        native = infer_demucs_native(
            self,
            prepare_mix=prepare_mix,
            process_secondary_model=process_secondary_model,
        )
        source, mix = native.sources, native.mix
        export_routes = run_export_routes(self)
        native_export = tuple(route for route in export_routes if route.native is not None)
        if native_export:
            write_all_sources = (
                len(native_export) == len(self.demucs_source_map)
                and not self.process_data.is_ensemble_master
            ) or (self.is_4_stem_ensemble and not self.is_return_dual)
        else:
            write_all_sources = (
                self.demucs_stems == ALL_STEMS and not self.process_data.is_ensemble_master
            ) or (self.is_4_stem_ensemble and not self.is_return_dual)

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
            blended = run_demucs_secondaries(
                self,
                source,
                process_secondary_model=process_secondary_model,
                secondary_4_stem_slot=secondary_4_stem_slot,
            )
            return plan_demucs_export(
                DemucsExportRequest(
                    native=native,
                    routes=export_routes,
                    write_all_sources=True,
                    blend=self.process_secondary_stem,
                    blended_sources=blended,
                    is_secondary_model=self.is_secondary_model,
                    is_pre_proc_model=self.is_pre_proc_model,
                    is_sec_bv_rebalance=self.is_sec_bv_rebalance,
                )
            )

        secondary_source_primary = secondary_source_secondary = None
        if self.is_secondary_model_activated and self.secondary_model:
            secondary_source_primary, secondary_source_secondary = process_secondary_model(
                self.secondary_model,
                self.process_data,
                main_process_method=self.process_method,
            )
        write_secondary = any(
            route.kind is StemRouteKind.DERIVED for route in export_routes
        ) or exports_named_stem(self, self.secondary_stem)
        # Decode remains lazy on cache hits, after the pair secondary invocation.
        if write_secondary and not self.is_demucs_combine_stems and mix is None:
            mix = prepare_mix(self.audio_file)
        native = replace(native, mix=mix)
        return plan_demucs_export(
            DemucsExportRequest(
                native=native,
                routes=export_routes,
                write_all_sources=False,
                blend=self.process_secondary_stem,
                primary_stem=self.primary_stem,
                secondary_stem=self.secondary_stem,
                is_secondary_model=self.is_secondary_model,
                is_pre_proc_model=self.is_pre_proc_model,
                is_sec_bv_rebalance=self.is_sec_bv_rebalance,
                is_demucs_combine_stems=self.is_demucs_combine_stems,
                is_invert_spec=self.is_invert_spec,
                is_demucs_pre_proc_model_inst_mix=self.is_demucs_pre_proc_model_inst_mix,
                has_pre_proc_model=bool(self.pre_proc_model),
                is_4_stem_ensemble=self.is_4_stem_ensemble,
                write_secondary=write_secondary,
                exports_primary=exports_named_stem(self, self.primary_stem),
                secondary_matching_routes=tuple(
                    route
                    for route in native_export
                    if route_matches_stem(route, self.secondary_stem, self)
                ),
                secondary_source_primary=secondary_source_primary,
                secondary_source_secondary=secondary_source_secondary,
            )
        )

    def demix_demucs(self, mix: typing.Any):
        with trace_phase(
            "separate", "demix_demucs", engine="SeperateDemucs", model=self.model_display_label
        ):
            org_mix = mix
            sources: Any = None
            # See SeperateMDX.demix: bound unconditionally, reassigned and read
            # back only under ``is_pitch_change``.
            sr_pitched = 44100

            if self.is_pitch_change:
                mix, sr_pitched = spec_utils.change_pitch_semitones(
                    mix, 44100, semitone_shift=-self.semitone_shift
                )

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
                    sources = cast(
                        Any,
                        apply_model(
                            self.demucs,
                            mix_infer[None],
                            self.shifts,
                            self.is_split_mode,
                            self.overlap,
                            static_shifts=1 if self.shifts == 0 else self.shifts,
                            set_progress_bar=self.set_progress_bar,
                            device=self.device,
                        ),
                    )[0]

            sources = (sources.float() * ref.std() + ref.mean()).cpu().numpy()
            sources[[0, 1]] = sources[[1, 0]]

            if self.is_pitch_change:
                sources = np.stack([self.pitch_fix(stem, sr_pitched, org_mix) for stem in sources])

            return sources
