"""MDX-C separation engine (``SeperateMDXC``)."""

from __future__ import annotations

import typing
from dataclasses import replace
from typing import TYPE_CHECKING, Any

import torch
import torch.nn as nn

from bundled.constants import *
from bundled.error_handling import *
from core.debug_log import trace_phase
from core.model_stem_semantics import is_vocal_target
from core.stems import (
    exports_named_stem,
    route_matches_stem,
    run_export_routes,
)
from ml import spec_utils

from .base import SeperateAttributes
from .mdx_c import (
    _mdx_c_hop_length,
    _mdx_pitch_reference_sr,
    mdx_selected_stems,
    select_roformer_ola_window,
)
from .mdx_c_export import (
    MDXCExportRequest,
    plan_mdx_c_export,
    prepare_mdx_c_export,
    resolve_mdx_c_export,
    select_mdx_c_primary,
    vocal_split_pair_sources,
)
from .mdx_c_runtime import MDXCAcquisitionRequest, acquire_mdx_c_model, infer_mdx_c_native
from .mdx_classic_batch import mdx_oom_reduce_batch_message, next_batch_after_oom
from .mix import prepare_mix
from .orchestration import process_secondary_model
from .vr_utils import vr_denoiser

if TYPE_CHECKING:
    from engines.stem_writer import ExportPlan


class SeperateMDXC(SeperateAttributes):
    is_vocal_main_target: bool

    def seperate(self) -> ExportPlan:
        native = infer_mdx_c_native(self, prepare_mix=prepare_mix)
        mix, sources, samplerate = native.mix, native.sources, native.samplerate
        stem_list = native.stem_list

        from engines.stem_writer import ExportPlan, vocal_split_export_routes

        if self.is_vocal_split_model:
            if isinstance(sources, dict):
                working_split = dict(sources)
            else:
                native = str(
                    self.primary_stem_native
                    or getattr(self.mdx_c_configs.training, "target_instrument", None)
                    or VOCAL_STEM
                )
                working_split = {native: sources}
            export_sources = self._vocal_split_pair_sources(
                working_split,
                mix,
                routes=vocal_split_export_routes(self),
            )
            return ExportPlan(
                sources=export_sources,
                samplerate=samplerate,
                split_sources={},
            )

        if self.is_secondary_model and not self.is_vocal_split_model:
            if self.is_pre_proc_model:
                self.mdxnet_stem_select = stem_list[0]
            else:
                self.mdxnet_stem_select = (
                    self.main_model_primary_stem_4_stem
                    if self.main_model_primary_stem_4_stem
                    else self.primary_model_primary_stem
                )
            self.primary_stem = str(self.mdxnet_stem_select or "")
            self.secondary_stem = secondary_stem(str(self.mdxnet_stem_select or ""))

        export_routes = run_export_routes(self)
        selected_stems = mdx_selected_stems(
            stem_list,
            [route.native.raw for route in export_routes if route.native is not None],
        )
        if not self.is_secondary_model and len(selected_stems) == 1:
            self.mdxnet_stem_select = selected_stems[0]

        source_keys = {}
        for stem in (self.mdxnet_stem_select, self.primary_stem, self.secondary_stem):
            key = str(stem or "")
            route = next(
                (route for route in export_routes if route_matches_stem(route, key, self)), None
            )
            source_keys[key] = (
                key
                if route is None
                else (route.native.raw if route.native is not None else route.concept)
            )
        request = MDXCExportRequest(
            native=native,
            export_routes=export_routes,
            available_routes=tuple(getattr(self, "available_stem_routes", ()) or export_routes),
            selected_stems=tuple(selected_stems),
            source_keys=source_keys,
            mdxnet_stem_select=self.mdxnet_stem_select,
            primary_stem=self.primary_stem,
            secondary_stem=self.secondary_stem,
            is_secondary_model=self.is_secondary_model,
            is_pre_proc_model=self.is_pre_proc_model,
            is_ensemble_master=self.process_data.is_ensemble_master,
            is_4_stem_ensemble=self.is_4_stem_ensemble,
            is_multi_stem_ensemble=self.is_multi_stem_ensemble,
            is_mdx_include_stem_complement=getattr(self, "is_mdx_include_stem_complement", False),
            is_mdx_combine_stems=self.is_mdx_combine_stems,
            is_invert_spec=self.is_invert_spec,
            exports_primary=exports_named_stem(self, self.primary_stem),
            exports_secondary=exports_named_stem(self, self.secondary_stem),
            blend=self.process_secondary_stem,
            match_frequency_pitch=self.match_frequency_pitch,
            primary_source=self.primary_source,
            secondary_source=self.secondary_source,
            secondary_source_primary=self.secondary_source_primary,
            secondary_source_secondary=self.secondary_source_secondary,
        )
        prepared = prepare_mdx_c_export(request)
        if (
            not (prepared.is_reviewed_recipe_only and not prepared.is_reviewed_target_pair)
            and not prepared.is_complement_export
            and prepared.flags["multi_stem_export"]
        ):
            export_stems = prepared.flags["export_stems"]
            if isinstance(sources, dict):
                # Keep the original mapping and shared array mutation before planning.
                allow_match = set(export_stems) == set(stem_list)
                self.apply_export_stem_levels(
                    sources, mix, stem_keys=export_stems, allow_match_mix=allow_match
                )
        primary_selection = select_mdx_c_primary(request, prepared)
        if prepared.pair_export and self.is_secondary_model_activated and self.secondary_model:
            self.secondary_source_primary, self.secondary_source_secondary = (
                process_secondary_model(
                    self.secondary_model,
                    self.process_data,
                    main_process_method=self.process_method,
                    main_model_primary=self.primary_stem,
                )
            )
            request = replace(
                request,
                secondary_source_primary=self.secondary_source_primary,
                secondary_source_secondary=self.secondary_source_secondary,
            )
        resolved = resolve_mdx_c_export(request, prepared, primary_selection)
        self.primary_source = resolved.primary_source
        self.secondary_source = resolved.secondary_source
        return plan_mdx_c_export(resolved)

    def _vocal_split_pair_sources(
        self,
        sources: dict[str, Any],
        mix: Any,
        *,
        routes: typing.Sequence[Any] | None = None,
    ) -> dict[str, Any]:
        return vocal_split_pair_sources(sources, mix, routes=routes)

    def overlap_add(
        self,
        result: typing.Any,
        counter: typing.Any,
        x: typing.Any,
        l: typing.Any,  # noqa: E741 - checkpoint code uses l for chunk length
        j: typing.Any,
        start: typing.Any,
        window: typing.Any,
    ):
        if x.device != result.device:
            x = x.to(result.device)
        end = min(start + l, result.shape[-1])
        chunk_len = end - start
        if chunk_len <= 0:
            return result
        contrib = x[j][..., :chunk_len]
        window_chunk = window[..., :chunk_len]
        result[..., start:end] += contrib * window_chunk
        counter[..., start:end] += window_chunk
        return result

    def demix(self, mix: typing.Any):
        if self.is_roformer:
            return self.demix_roformer(mix)

        with trace_phase(
            "separate",
            "demix",
            engine="SeperateMDXC",
            model=self.model_display_label,
            roformer=False,
        ):
            sr_pitched = _mdx_pitch_reference_sr()
            org_mix = mix
            if self.is_pitch_change:
                mix, sr_pitched = spec_utils.change_pitch_semitones(
                    mix, 44100, semitone_shift=-self.semitone_shift
                )

            from engines.model_weight_cache import get_weight_cache

            request = MDXCAcquisitionRequest.from_separator(self, roformer=False)
            key = request.cache_key(self.device)
            self._weight_cache_key = key
            model = acquire_mdx_c_model(
                request, self.device, weight_cache=get_weight_cache(), cache_key=key,
            )
            self._inference_model = model
            mix = torch.as_tensor(mix, dtype=torch.float32, device=self.device)

            try:
                try:
                    S = model.num_target_instruments
                except Exception:
                    S = model.module.num_target_instruments

                mdx_segment_size = (
                    self.mdx_c_configs.inference.dim_t
                    if self.is_mdx_c_seg_def
                    else self.mdx_segment_size
                )

                batch_size = max(1, int(self.mdx_batch_size or 1))
                chunk_size = self.mdx_c_configs.audio.hop_length * (mdx_segment_size - 1)
                overlap = self.overlap_mdx23

                hop_size = chunk_size // overlap
                mix_shape = mix.shape[1]
                pad_size = hop_size - (mix_shape - chunk_size) % hop_size
                mix = torch.cat(
                    [
                        torch.zeros(2, chunk_size - hop_size, device=self.device),
                        mix,
                        torch.zeros(2, pad_size + chunk_size - hop_size, device=self.device),
                    ],
                    1,
                )

                n_chunks = 1 + (mix.shape[1] - chunk_size) // hop_size

                X = (
                    torch.zeros(S, *mix.shape, device=self.device)
                    if S > 1
                    else torch.zeros_like(mix)
                )

                self.running_inference_console_write()

                with torch.inference_mode():
                    from engines.amp_runtime import maybe_autocast

                    cnt = 0
                    while cnt < n_chunks:
                        self.check_run_control()
                        take = min(batch_size, n_chunks - cnt)
                        # Hop-index batching avoids materializing mix.unfold(...) for the full track.
                        batch = torch.stack(
                            [
                                mix[:, i * hop_size : i * hop_size + chunk_size]
                                for i in range(cnt, cnt + take)
                            ],
                            dim=0,
                        )
                        try:
                            with maybe_autocast(self.device, self.settings):
                                x = model(batch)
                        except torch.cuda.OutOfMemoryError:
                            del batch
                            if torch.cuda.is_available():
                                torch.cuda.empty_cache()
                            smaller = next_batch_after_oom(take)
                            if smaller is None:
                                raise
                            batch_size = smaller
                            self.write_to_console(
                                mdx_oom_reduce_batch_message(batch_size)
                            )
                            continue
                        if torch.is_tensor(x) and x.dtype != torch.float32:
                            x = x.float()

                        for w in x:
                            self.running_inference_progress_bar(max(1, n_chunks))
                            X[..., cnt * hop_size : cnt * hop_size + chunk_size] += w
                            cnt += 1

                estimated_sources = (
                    X[..., chunk_size - hop_size : -(pad_size + chunk_size - hop_size)] / overlap
                )
                del X
                pitch_fix = lambda s: self.pitch_fix(  # noqa: E731 - scoped callback
                    s, sr_pitched, org_mix
                )

                if S > 1:
                    sources = {
                        k: pitch_fix(v) if self.is_pitch_change else v
                        for k, v in zip(
                            self.mdx_c_configs.training.instruments,
                            estimated_sources.cpu().detach().numpy(),
                            strict=False,
                        )
                    }
                    del estimated_sources
                    if self.is_denoise_model:
                        if VOCAL_STEM in sources.keys() and INST_STEM in sources.keys():
                            sources[VOCAL_STEM] = vr_denoiser(
                                sources[VOCAL_STEM],
                                self.device,
                                model_path=self.DENOISER_MODEL,
                                settings=self.settings,
                                on_batch=self.denoise_progress_callback(),
                                check_run_control=self.check_run_control,
                            )
                            if sources[VOCAL_STEM].shape[1] != org_mix.shape[1]:
                                sources[VOCAL_STEM] = spec_utils.match_array_shapes(
                                    sources[VOCAL_STEM], org_mix
                                )
                            sources[INST_STEM] = org_mix - sources[VOCAL_STEM]

                    return sources
                else:
                    est_s = estimated_sources.cpu().detach().numpy()
                    del estimated_sources
                    return pitch_fix(est_s) if self.is_pitch_change else est_s
            finally:
                if isinstance(mix, torch.Tensor):
                    del mix
                # Keep weights on self._inference_model for release_separator / weight cache.

    def demix_roformer(self, mix: typing.Any):
        with trace_phase(
            "separate",
            "demix_roformer",
            engine="SeperateMDXC",
            model=self.model_display_label,
        ):
            sr_pitched = _mdx_pitch_reference_sr()
            org_mix = mix
            if self.is_pitch_change:
                mix, sr_pitched = spec_utils.change_pitch_semitones(
                    mix, 44100, semitone_shift=-self.semitone_shift
                )

            device = self.device

            from engines.model_weight_cache import get_weight_cache

            request = MDXCAcquisitionRequest.from_separator(self, roformer=True)
            key = request.cache_key(device)
            self._weight_cache_key = key
            model = acquire_mdx_c_model(
                request, device, weight_cache=get_weight_cache(), cache_key=key,
            )
            self._inference_model = model
            mix = torch.as_tensor(mix, dtype=torch.float32, device=device)

            result = counter = estimated_sources = None
            try:
                segment_size = (
                    self.mdx_c_configs.inference.dim_t
                    if self.is_mdx_c_seg_def
                    else self.mdx_segment_size
                )
                S = (
                    1
                    if self.roformer_config.training.target_instrument
                    else len(self.roformer_config.training.instruments)
                )
                C = _mdx_c_hop_length(self.roformer_config) * (segment_size - 1)
                N = self.overlap_mdx23
                step = int(C // N)
                fade_size = C // 10
                batch_size = self.roformer_config.inference.batch_size
                length_init = mix.shape[-1]

                # Padding the mix to account for border effects
                if length_init > 2 * (C - step) and (C - step > 0):
                    mix = nn.functional.pad(mix, (C - step, C - step), mode='reflect')

                # Set up windows for fade-in/out
                fadein = torch.linspace(0, 1, fade_size, device=device)
                fadeout = torch.linspace(1, 0, fade_size, device=device)
                window_start = torch.ones(C, device=device)
                window_middle = torch.ones(C, device=device)
                window_finish = torch.ones(C, device=device)
                window_start[-fade_size:] *= fadeout  # No fade-in at start
                window_finish[:fade_size] *= fadein  # No fade-out at end
                window_middle[:fade_size] *= fadein
                window_middle[-fade_size:] *= fadeout

                batch_len = int(mix.shape[1] / step)

                self.running_inference_console_write()

                with torch.inference_mode():
                    req_shape = (S,) + tuple(mix.shape)
                    result = torch.zeros(req_shape, dtype=torch.float32, device=device)
                    counter = torch.zeros(req_shape, dtype=torch.float32, device=device)
                    batch_data = []
                    batch_locations = []

                    i = 0

                    while i < mix.shape[1]:
                        self.check_run_control()
                        part = mix[:, i : i + C]
                        length = part.shape[-1]
                        if length < C:
                            if length > C // 2 + 1:
                                part = nn.functional.pad(part, (0, C - length), mode='reflect')
                            else:
                                part = nn.functional.pad(
                                    part, (0, C - length, 0, 0), mode='constant', value=0
                                )

                        batch_data.append(part)
                        batch_locations.append((i, length))
                        i += step

                        # Process in batches
                        if len(batch_data) >= batch_size or (i >= mix.shape[1]):
                            from engines.amp_runtime import maybe_autocast

                            pending_data = batch_data
                            pending_locations = batch_locations
                            sub_batch = len(pending_data)
                            idx = 0
                            while idx < len(pending_data):
                                take = min(sub_batch, len(pending_data) - idx)
                                chunk_data = pending_data[idx : idx + take]
                                chunk_locations = pending_locations[idx : idx + take]
                                arr = torch.stack(chunk_data, dim=0)
                                try:
                                    with maybe_autocast(device, self.settings):
                                        x = model(arr)
                                except torch.cuda.OutOfMemoryError:
                                    del arr
                                    if torch.cuda.is_available():
                                        torch.cuda.empty_cache()
                                    smaller = next_batch_after_oom(take)
                                    if smaller is None:
                                        raise
                                    sub_batch = smaller
                                    batch_size = smaller
                                    self.write_to_console(
                                        mdx_oom_reduce_batch_message(batch_size)
                                    )
                                    continue
                                if torch.is_tensor(x) and x.dtype != torch.float32:
                                    x = x.float()

                                for j, (start, l) in enumerate(  # noqa: E741 - chunk length
                                    chunk_locations
                                ):
                                    self.running_inference_progress_bar(batch_len)
                                    window = select_roformer_ola_window(
                                        start,
                                        C,
                                        mix.shape[1],
                                        window_start,
                                        window_middle,
                                        window_finish,
                                    )
                                    result = self.overlap_add(
                                        result, counter, x, l, j, start, window
                                    )
                                idx += take

                            batch_data = []
                            batch_locations = []

                    # Normalize by the overlap counter and remove padding
                    estimated_sources = result / counter.clamp(min=1e-10)

                    if length_init > 2 * (C - step) and (C - step > 0):
                        estimated_sources = estimated_sources[..., (C - step) : -(C - step)]

                pitch_fix = lambda s: self.pitch_fix(  # noqa: E731 - scoped callback
                    s, sr_pitched, org_mix
                )

                if S > 1 or self.is_vocal_main_target:
                    sources = {
                        k: pitch_fix(v) if self.is_pitch_change else v
                        for k, v in zip(
                            self.mdx_c_configs.training.instruments,
                            estimated_sources.cpu().detach().numpy(),
                            strict=False,
                        )
                    }
                    if self.is_vocal_main_target:
                        vocal_key = next(
                            (key for key in sources if is_vocal_target(key)),
                            None,
                        )
                        if vocal_key is not None:
                            if sources[vocal_key].shape[1] != org_mix.shape[1]:
                                sources[vocal_key] = spec_utils.match_array_shapes(
                                    sources[vocal_key], org_mix
                                )
                            sources[INST_STEM] = org_mix - sources[vocal_key]

                    return sources
                else:
                    sources = {
                        k: v.cpu().detach().numpy()
                        for k, v in zip(
                            [self.mdx_c_configs.training.target_instrument],
                            estimated_sources,
                            strict=False,
                        )
                    }
                    est_s = sources[self.mdx_c_configs.training.target_instrument]

                    return pitch_fix(est_s) if self.is_pitch_change else est_s
            finally:
                for tensor in (result, counter, mix, estimated_sources):
                    if tensor is not None:
                        del tensor
                # Keep weights on self._inference_model for release_separator / weight cache.
