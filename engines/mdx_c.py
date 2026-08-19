"""MDX-C / Roformer / SCNet / Bandit separation engine."""
from __future__ import annotations
import typing
from typing import Any, TYPE_CHECKING

import inspect

import librosa
import numpy as np
import torch
import torch.nn as nn
import warnings

from bundled.constants import *
from bundled.error_handling import *
from core.debug_log import trace_phase
from core.torch_checkpoint import as_model_state_dict, load_torch_checkpoint
from core.model_stem_semantics import (
    is_vocal_target,
    vocal_inst_from_sources,
    vocal_split_source_roles,
)
from core.stems import (
    StemBucket,
    StemId,
    StemRouteKind,
    exports_named_stem,
    resolve_in_sources,
    run_export_routes,
)
from ml import spec_utils

from .base import SeperateAttributes
from .mix import prepare_mix
from .mdx_classic_batch import next_batch_after_oom
from .vr_utils import vr_denoiser
from .orchestration import process_secondary_model

if TYPE_CHECKING:
    from core.model_config import ModelConfig
    from engines.stem_writer import ExportPlan

warnings.filterwarnings("ignore")

from ml.tfc_tdf_v3 import TFC_TDF_net
from ml.mel_band_roformer import MelBandRoformer
from ml.bs_roformer import BSRoformer


def _load_torch_checkpoint(path: str):
    return as_model_state_dict(load_torch_checkpoint(path, map_location="cpu"))


def _mdx_c_hop_length(config: typing.Any) -> int:
    model_cfg = getattr(config, 'model', None)
    if model_cfg is not None:
        if hasattr(model_cfg, 'hop_size'):
            return int(model_cfg.hop_size)
        # Roformer yaml files often keep a legacy audio.hop_length that does not
        # match the model STFT hop used for chunk sizing (see chunk_size).
        if hasattr(model_cfg, 'stft_hop_length'):
            return int(model_cfg.stft_hop_length)
    kwargs = getattr(config, 'kwargs', None)
    if kwargs is not None and hasattr(kwargs, 'hop_length'):
        return int(kwargs.hop_length)
    audio_cfg = getattr(config, 'audio', None)
    if audio_cfg is not None and hasattr(audio_cfg, 'hop_length'):
        return int(audio_cfg.hop_length)
    raise ValueError('MDX-C config is missing hop_length / hop_size.')


def _filter_init_kwargs(model_cls: typing.Any, cfg: typing.Any) -> dict:
    """Drop YAML keys that are not accepted by a model class ``__init__``."""
    params = inspect.signature(model_cls.__init__).parameters
    if any(p.kind == inspect.Parameter.VAR_KEYWORD for p in params.values()):
        return dict(cfg)
    allowed = {name for name in params if name != 'self'}
    return {key: cfg[key] for key in cfg if key in allowed}


def scnet_variant_from_state_dict(keys: typing.Sequence[str]) -> typing.Optional[str]:
    """Return ``'masked'`` if ``keys`` look like SCNet Masked, else ``None``.

    ``mask_layer`` and ``pos_embed_f`` are SCNet Masked-only parameters that a
    plain ``SCNet``/``SCNetTran`` checkpoint never carries.
    """
    joined = "\n".join(keys)
    if "mask_layer" in joined or "pos_embed_f" in joined:
        return "masked"
    return None


_SCNET_MASKED_HINTS = {"scnet_masked", "SCNet Masked"}


class UnknownMDXCArchitecture(ValueError):
    """The config's ``model``/``cls`` section matches no known MDX-C variant.

    A distinct type from a plain ``ValueError`` so callers that try a
    fallback build path on "not this architecture" don't also catch a
    genuine ``ValueError`` raised by a variant's own constructor.
    """


def _build_mdx_c_model(
    config: typing.Any,
    state_dict_keys: typing.Optional[typing.Sequence[str]] = None,
    model_type_hint: typing.Optional[str] = None,
):
    if getattr(config, 'cls', None) == 'Bandit':
        from ml.bandit import Bandit

        kwargs = _filter_init_kwargs(Bandit, config.kwargs)
        if 'fs' not in kwargs and hasattr(config.audio, 'sample_rate'):
            kwargs['fs'] = int(config.audio.sample_rate)
        return Bandit(**kwargs)

    model_cfg = getattr(config, 'model', None)
    if model_cfg is None:
        raise UnknownMDXCArchitecture('Unknown MDX-C architecture in configuration.')

    if 'num_bands' in model_cfg:
        kwargs = _filter_init_kwargs(MelBandRoformer, model_cfg)
        kwargs['match_input_audio_length'] = True
        return MelBandRoformer(**kwargs)
    # Most BS-Roformer yamls declare freqs_per_bands explicitly, but some
    # (e.g. the "BS Roformer SW" shared-weight variant) omit it and rely on
    # BSRoformer's own DEFAULT_FREQS_PER_BANDS. Without this fallback such a
    # config falls through every other architecture check below and gets
    # built as TFC_TDF_net instead, which crashes on the first field it reads
    # (``model.norm``) that a Roformer config never had.
    is_bs_roformer_without_declared_bands = (
        'freqs_per_bands' not in model_cfg
        and 'stereo' in model_cfg
        and 'depth' in model_cfg
        and 'band_SR' not in model_cfg
        and 'sources' not in model_cfg
        and 'band_specs' not in model_cfg
    )
    if 'freqs_per_bands' in model_cfg or is_bs_roformer_without_declared_bands:
        kwargs = _filter_init_kwargs(BSRoformer, model_cfg)
        # HyperACE attaches a segm branch to every mask estimator. Prefer the
        # checkpoint's own keys: only the packaged v2-instrumental yaml carries
        # a ``hyperace2`` flag, and that flag is top-level so it never reaches
        # the kwarg filter anyway. Upstream's own configs declare nothing.
        from ml.hyperace import hyperace_variant_from_state_dict

        variant = hyperace_variant_from_state_dict(state_dict_keys or ())
        if variant is None and getattr(config, 'hyperace2', False):
            variant = 'v2'
        if variant is not None:
            kwargs['hyperace'] = variant
        # Value Residual Learning checkpoints (e.g. Inst-EXP-Value-Residual)
        # carry a to_value_residual_mix subtree that plain BSRoformer lacks;
        # detect it the same way as the hyperace/SCNet variant checks above.
        if any('to_value_residual_mix' in key for key in (state_dict_keys or ())):
            kwargs['value_residual'] = True
        return BSRoformer(**kwargs)
    if 'band_SR' in model_cfg or 'sources' in model_cfg:
        has_tran_kwargs = any(str(key).startswith('tran_') for key in model_cfg)
        if has_tran_kwargs:
            from ml.scnet import SCNetTran

            return SCNetTran(**_filter_init_kwargs(SCNetTran, model_cfg))

        variant = scnet_variant_from_state_dict(state_dict_keys or ())
        if variant == 'masked' or model_type_hint in _SCNET_MASKED_HINTS:
            from ml.scnet import SCNetMasked

            return SCNetMasked(**_filter_init_kwargs(SCNetMasked, model_cfg))

        from ml.scnet import SCNet

        return SCNet(**_filter_init_kwargs(SCNet, model_cfg))
    if 'band_specs' in model_cfg:
        from ml.bandit import MultiMaskMultiSourceBandSplitRNN

        return MultiMaskMultiSourceBandSplitRNN(**_filter_init_kwargs(MultiMaskMultiSourceBandSplitRNN, model_cfg))
    raise UnknownMDXCArchitecture('Unknown MDX-C architecture in configuration.')

def _mdx_pitch_reference_sr() -> int:
    return 44100


def select_roformer_ola_window(start: typing.Any, chunk_size: typing.Any, mix_length: typing.Any, window_start: typing.Any, window_middle: typing.Any, window_finish: typing.Any):
    """Pick the OLA fade window for one Roformer chunk.

    The final inference flush can contain several chunk starts; only a chunk
    whose own range reaches the mix end uses the finish window.
    """
    if start == 0:
        return window_start
    if start + chunk_size >= mix_length:
        return window_finish
    return window_middle


def mdx_export_routing_flags(
    *,
    stem_list: typing.Any,
    export_routes: typing.Any,
    mdxnet_stem_select: typing.Any,
    is_secondary_model: typing.Any,
    is_pre_proc_model: typing.Any,
    is_ensemble_master: typing.Any,
    is_4_stem_ensemble: typing.Any,
    include_stem_complement: typing.Any,
):
    routes = tuple(export_routes or ())
    natives = tuple(route for route in routes if route.native is not None)
    derived = tuple(
        route for route in routes if route.kind is StemRouteKind.DERIVED
    )
    native_names = [
        route.native.raw for route in natives if route.native is not None
    ]
    has_derived_inst = any(
        route.concept == StemBucket.INSTRUMENTAL.value for route in derived
    )
    has_other_derived = any(
        route.concept != StemBucket.INSTRUMENTAL.value for route in derived
    )
    is_full_selection = (not native_names) or set(
        name.casefold() for name in native_names
    ) == set(str(stem).casefold() for stem in stem_list)
    is_all_stems = (
        mdxnet_stem_select == ALL_STEMS
        and not derived
        and (not native_names or is_full_selection)
    )
    is_not_ensemble_master = not is_ensemble_master
    is_not_single_stem = not len(stem_list) <= 2
    is_not_secondary_model = not is_secondary_model
    is_ensemble_4_stem = is_4_stem_ensemble and is_not_single_stem
    is_vocals_quick_export = (
        len(natives) == 1
        and is_vocal_target(native_names[0])
        and not derived
        and not bool(include_stem_complement)
    )
    is_complement_export = (
        # 1-2 stem models (incl. target-instrument ``other``) demix to an
        # ndarray, not a stem-keyed dict. Their derived pair complement is
        # the pair-export path, not this multi-stem index-by-name branch.
        is_not_single_stem
        and len(natives) == 1
        and not has_derived_inst
        and (
            bool(include_stem_complement)
            or has_other_derived
        )
        and not is_vocals_quick_export
    )
    is_native_pick = (
        len(natives) == 1
        and is_not_ensemble_master
        and is_not_single_stem
        and is_not_secondary_model
        and not is_pre_proc_model
        and not is_complement_export
        and not has_derived_inst
    )
    is_stem_subset = (
        len(natives) >= 2 and not is_full_selection
        and is_not_ensemble_master and is_not_single_stem
        and is_not_secondary_model and not is_pre_proc_model
    )
    multi_stem_export = (
        (is_all_stems and is_not_ensemble_master and is_not_single_stem and is_not_secondary_model)
        or (is_ensemble_4_stem and not is_pre_proc_model)
        or is_stem_subset
        or is_native_pick
    )
    return {
        "is_complement_export": is_complement_export,
        "is_native_pick": is_native_pick,
        "is_stem_subset": is_stem_subset,
        "multi_stem_export": multi_stem_export,
        "export_stems": (
            mdx_selected_stems(stem_list, native_names)
            if (is_stem_subset or is_native_pick)
            else stem_list
        ),
    }


def mdx_selected_stems(stem_list: typing.Any, stems_selected: typing.Any) -> typing.List[str]:
    """Model-native stem names from ``stem_list`` matching the saved subset pick.

    ``stems_selected`` is persisted using canonical UVR stem labels (e.g.
    ``Vocals``), while ``stem_list`` carries a checkpoint's own yaml casing --
    commonly lowercase (``vocals``) for community MDX-C multi-stem models. A
    raw membership check between the two matches nothing whenever they
    disagree, silently discarding the user's stem-subset/quick-export choice
    and falling back to exporting every stem.
    """
    lookup = {str(stem): stem for stem in (stems_selected or [])}
    return [
        stem for stem in stem_list if resolve_in_sources(lookup, StemId(str(stem))) is not None
    ]


def mdx_combined_secondary_key(sources: typing.Any, stem_list: typing.Any, secondary_stem_label: typing.Any):
    """Key in ``sources`` holding the complement of a 2-stem MDX-C model.

    ``secondary_stem_label`` is a UVR pair name, which for a model trained on
    stems outside the pair table (``center``/``wide``) matches no source key at
    all. Fall back to the model's own other instrument.
    """
    key = resolve_in_sources(sources, StemId(str(secondary_stem_label or "")))
    if key is None and len(stem_list) == 2:
        key = resolve_in_sources(sources, StemId(str(stem_list[1])))
    if key is None:
        available = sorted(map(str, sources.keys())) if isinstance(sources, dict) else []
        raise KeyError(
            f"stem {str(secondary_stem_label)!r} not in sources {available}"
        )
    return key


def _channel_last_for_write(arr: typing.Any) -> typing.Any:
    data = np.asarray(arr)
    if data.ndim == 2 and data.shape[0] == 2:
        return data.T
    return data


def mdx_vocal_split_chain_sources(
    maps: dict[str, typing.Any],
    demix_sources: typing.Any,
) -> dict[str, typing.Any]:
    """Prefer exported maps; fill vocals/inst from community yaml demix keys."""
    merged = dict(maps)
    mapped_vocal, mapped_inst = vocal_inst_from_sources(merged)
    demix_vocal, demix_inst = vocal_inst_from_sources(
        demix_sources if isinstance(demix_sources, dict) else None
    )
    if not isinstance(mapped_vocal, np.ndarray) and isinstance(demix_vocal, np.ndarray):
        merged[VOCAL_STEM] = _channel_last_for_write(demix_vocal)
    if not isinstance(mapped_inst, np.ndarray) and isinstance(demix_inst, np.ndarray):
        merged[INST_STEM] = _channel_last_for_write(demix_inst)
    return merged


def derive_mdx_complement(native_source: typing.Any, mix: typing.Any, *, invert_spec: typing.Any=False, match_frequency_pitch: typing.Any=None):
    raw_mix = match_frequency_pitch(mix) if match_frequency_pitch is not None else mix
    shaped = spec_utils.to_shape(native_source, raw_mix.shape)
    if invert_spec:
        return spec_utils.invert_stem(raw_mix, shaped)
    return (-shaped.T + raw_mix.T)


def derive_mdx_multi_complement(
    sources: dict[str, typing.Any],
    primary_stem: str,
    mix: typing.Any,
    *,
    combine_stems: bool,
    invert_spec: bool = False,
    match_frequency_pitch: typing.Any = None,
) -> typing.Any:
    """Derive a multi-source primary complement using the configured recipe."""
    primary_key = resolve_in_sources(sources, StemId(primary_stem))
    if primary_key is None:
        raise KeyError(
            f"stem {primary_stem!r} not in sources {sorted(map(str, sources))}"
        )
    if combine_stems:
        remaining = [value for key, value in sources.items() if key != primary_key]
        if not remaining:
            raise ValueError("cannot combine a complement without remaining stems")
        combined = np.zeros_like(remaining[0])
        for value in remaining:
            combined += value
        return combined.T
    return derive_mdx_complement(
        sources[primary_key],
        mix,
        invert_spec=invert_spec,
        match_frequency_pitch=match_frequency_pitch,
    )


class SeperateMDXC(SeperateAttributes):        

    def seperate(self) -> ExportPlan:
        # A *roformer* model whose single target_instrument is the vocal stem is
        # treated as a vocals+instrumental model: ``demix`` derives the
        # instrumental as ``mixture - vocals``. Classic (non-roformer) MDX-C
        # models are excluded so their original single-stem output is preserved.
        target = str(getattr(self.mdx_c_configs.training, "target_instrument", None) or "")
        self.is_vocal_main_target = self.is_roformer and is_vocal_target(target)
        samplerate = 44100
        sources = None

        if self.primary_model_name == self.model_basename and isinstance(self.primary_sources, tuple):
            mix, sources = self.primary_sources
            self.load_cached_sources()
        else:
            with trace_phase("separate", "seperate", engine="SeperateMDXC", model=self.model_basename):
                self.start_inference_console_write()
                self.write_to_console(LOADING_MODEL)
                mix = prepare_mix(self.audio_file)
                export_mix = mix
                export_rate = samplerate
                model_rate = int(getattr(self.mdx_c_configs.audio, 'sample_rate', export_rate) or export_rate)
                if model_rate != export_rate:
                    mix = librosa.resample(mix, orig_sr=export_rate, target_sr=model_rate, axis=1)
                sources = self.demix(mix)
                if model_rate != export_rate:
                    if isinstance(sources, dict):
                        for key, stem_audio in list(sources.items()):
                            sources[key] = librosa.resample(
                                stem_audio, orig_sr=model_rate, target_sr=export_rate, axis=1
                            )
                    else:
                        sources = librosa.resample(
                            sources, orig_sr=model_rate, target_sr=export_rate, axis=1
                        )
                    # Downstream subtraction, level matching, caching, and the
                    # splitter complement must share the exported source rate.
                    mix = export_mix
                if not self.is_vocal_split_model:
                    self.cache_source((mix, sources))
                self.write_to_console(DONE, base_text='')

        stem_list = [self.mdx_c_configs.training.target_instrument] if self.mdx_c_configs.training.target_instrument and not self.is_vocal_main_target else [i for i in self.mdx_c_configs.training.instruments]

        from engines.stem_writer import ExportPlan

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
            export_sources = self._vocal_split_pair_sources(working_split, mix)
            return ExportPlan(
                sources=export_sources,
                samplerate=samplerate,
                split_sources={},
            )

        if self.is_secondary_model and not self.is_vocal_split_model:
            if self.is_pre_proc_model:
                self.mdxnet_stem_select = stem_list[0]
            else:
                self.mdxnet_stem_select = self.main_model_primary_stem_4_stem if self.main_model_primary_stem_4_stem else self.primary_model_primary_stem
            self.primary_stem = str(self.mdxnet_stem_select or "")
            self.secondary_stem = secondary_stem(str(self.mdxnet_stem_select or ""))

        export_routes = run_export_routes(self)
        selected_stems = mdx_selected_stems(
            stem_list,
            [
                route.native.raw
                for route in export_routes
                if route.native is not None
            ],
        )
        if not self.is_secondary_model and len(selected_stems) == 1:
            self.mdxnet_stem_select = selected_stems[0]

        routing = mdx_export_routing_flags(
            stem_list=stem_list,
            export_routes=export_routes,
            mdxnet_stem_select=self.mdxnet_stem_select,
            is_secondary_model=self.is_secondary_model,
            is_pre_proc_model=self.is_pre_proc_model,
            is_ensemble_master=self.process_data.is_ensemble_master,
            is_4_stem_ensemble=self.is_4_stem_ensemble,
            include_stem_complement=getattr(self, "is_mdx_include_stem_complement", False),
        )
        is_complement_export = routing["is_complement_export"]
        export_sources: dict[str, Any] = {}

        if is_complement_export:
            stem = selected_stems[0]
            complement_stem = secondary_stem(stem)
            export_sources[stem] = sources[stem].T
            export_sources[complement_stem] = derive_mdx_complement(
                sources[stem],
                mix,
                invert_spec=self.is_invert_spec,
                match_frequency_pitch=self.match_frequency_pitch,
            )
        elif routing["multi_stem_export"]:
            export_stems = routing["export_stems"]
            if isinstance(sources, dict):
                # Match-mix only when exporting the model's full stem set so a
                # partial selection is not forced to reconstruct the whole mix.
                allow_match = set(export_stems) == set(stem_list)
                self.apply_export_stem_levels(
                    sources,
                    mix,
                    stem_keys=export_stems,
                    allow_match_mix=allow_match,
                )
            for stem in export_stems:
                self.primary_source = sources[stem].T
                export_sources[stem] = self.primary_source
        else:
            working_sources: Any = dict(sources) if isinstance(sources, dict) else sources
            if len(stem_list) == 1:
                source_primary = working_sources  
            else:
                select = str(self.mdxnet_stem_select or "")
                primary = str(self.primary_stem or "")
                if self.is_multi_stem_ensemble or len(stem_list) == 2:
                    stem_key = str(stem_list[0])
                elif select == ALL_STEMS:
                    stem_key = primary
                elif isinstance(working_sources, dict) and resolve_in_sources(
                    working_sources, StemId(select)
                ) is not None:
                    stem_key = select
                else:
                    stem_key = primary
                if isinstance(working_sources, dict):
                    resolved = resolve_in_sources(working_sources, StemId(stem_key))
                    if resolved is None:
                        raise KeyError(
                            f"stem {stem_key!r} not in sources "
                            f"{sorted(map(str, working_sources.keys()))}"
                        )
                    source_primary = working_sources[resolved]
                else:
                    source_primary = working_sources[stem_key]
            if self.is_secondary_model_activated and self.secondary_model:
                self.secondary_source_primary, self.secondary_source_secondary = process_secondary_model(self.secondary_model, 
                                                                                                         self.process_data, 
                                                                                                         main_process_method=self.process_method, 
                                                                                                         main_model_primary=self.primary_stem)

            if exports_named_stem(self, self.secondary_stem):
                if not isinstance(self.secondary_source, np.ndarray):
                    
                    if isinstance(working_sources, dict) and len(stem_list) > 2:
                        self.secondary_source = derive_mdx_multi_complement(
                            working_sources,
                            str(self.primary_stem or ""),
                            mix,
                            combine_stems=bool(self.is_mdx_combine_stems),
                            invert_spec=bool(self.is_invert_spec),
                            match_frequency_pitch=self.match_frequency_pitch,
                        )
                    elif self.is_mdx_combine_stems and len(stem_list) == 2:
                        if isinstance(working_sources, dict):
                            sec_key = mdx_combined_secondary_key(
                                working_sources, stem_list, self.secondary_stem
                            )
                            secondary_source = working_sources[sec_key]
                        else:
                            secondary_source = working_sources

                        self.secondary_source = secondary_source.T 
                    elif isinstance(working_sources, dict) and resolve_in_sources(
                        working_sources, StemId(self.secondary_stem)
                    ):
                        sec_key = resolve_in_sources(
                            working_sources, StemId(self.secondary_stem)
                        )
                        self.secondary_source = working_sources[sec_key].T
                    else:
                        self.secondary_source, raw_mix = source_primary, self.match_frequency_pitch(mix)
                        self.secondary_source = spec_utils.to_shape(self.secondary_source, raw_mix.shape)
                    
                        if self.is_invert_spec:
                            self.secondary_source = spec_utils.invert_stem(raw_mix, self.secondary_source)
                        else:
                            self.secondary_source = (-self.secondary_source.T+raw_mix.T)
                export_sources[self.secondary_stem] = self.process_secondary_stem(
                    self.secondary_source, self.secondary_source_secondary
                )

            if exports_named_stem(self, self.primary_stem):
                if not isinstance(self.primary_source, np.ndarray):
                    self.primary_source = source_primary.T

                export_sources[self.primary_stem] = self.process_secondary_stem(
                    self.primary_source, self.secondary_source_primary
                )

        secondary_sources = mdx_vocal_split_chain_sources(
            export_sources,
            sources,
        )
        plan = ExportPlan(
            sources=export_sources,
            samplerate=samplerate,
            split_sources=secondary_sources,
        )
        if self.is_secondary_model or self.is_pre_proc_model:
            plan.return_sources = secondary_sources
        return plan

    def _vocal_split_pair_sources(
        self, sources: dict[str, Any], mix: Any
    ) -> dict[str, Any]:
        """Build lead/backing from yaml-keyed demix output for export."""
        lead_key, backing_key = vocal_split_source_roles(
            sources, is_bv_model=bool(self.is_bv_model)
        )
        lead = sources[lead_key] if lead_key is not None else None
        backing = sources[backing_key] if backing_key is not None else None
        mix_arr = np.asarray(mix) if mix is not None else None
        if lead is None and backing is not None and mix_arr is not None:
            lead = mix_arr - spec_utils.to_shape(np.asarray(backing), mix_arr.shape)
        if backing is None and lead is not None and mix_arr is not None:
            backing = mix_arr - spec_utils.to_shape(np.asarray(lead), mix_arr.shape)
        export_sources: dict[str, Any] = {}
        if lead is not None:
            export_sources[LEAD_VOCAL_STEM_LABEL] = _channel_last_for_write(lead)
        if backing is not None:
            export_sources[BV_VOCAL_STEM_LABEL] = _channel_last_for_write(backing)
        return export_sources

    def overlap_add(self, result: typing.Any, counter: typing.Any, x: typing.Any, l: typing.Any, j: typing.Any, start: typing.Any, window: typing.Any):
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
            model=self.model_basename,
            roformer=False,
        ):
            sr_pitched = _mdx_pitch_reference_sr()
            org_mix = mix
            if self.is_pitch_change:
                mix, sr_pitched = spec_utils.change_pitch_semitones(mix, 44100, semitone_shift=-self.semitone_shift)

            from engines.model_weight_cache import (
                get_weight_cache,
                materialize_module,
                weight_cache_key,
            )

            key = weight_cache_key(
                "mdx_c",
                self.model_path,
                self.device,
                getattr(self.mdx_c_configs.inference, "dim_t", None),
            )
            self._weight_cache_key = key
            cached = get_weight_cache().get(key)
            if cached and cached.module is not None:
                model: Any = materialize_module(cached.module, self.device)
            else:
                model = TFC_TDF_net(self.mdx_c_configs, device=self.device)
                model.load_state_dict(_load_torch_checkpoint(self.model_path))
                model.to(self.device).eval()
            self._inference_model = model
            mix = torch.as_tensor(mix, dtype=torch.float32, device=self.device)

            try:
                try:
                    S = model.num_target_instruments
                except Exception:
                    S = model.module.num_target_instruments

                mdx_segment_size = self.mdx_c_configs.inference.dim_t if self.is_mdx_c_seg_def else self.mdx_segment_size
                
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

                X = torch.zeros(S, *mix.shape, device=self.device) if S > 1 else torch.zeros_like(mix)

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
                                f"CUDA OOM — reducing MDX batch size to {batch_size}"
                            )
                            continue
                        if torch.is_tensor(x) and x.dtype != torch.float32:
                            x = x.float()

                        for w in x:
                            self.running_inference_progress_bar(max(1, n_chunks))
                            X[..., cnt * hop_size : cnt * hop_size + chunk_size] += w
                            cnt += 1

                estimated_sources = X[..., chunk_size - hop_size:-(pad_size + chunk_size - hop_size)] / overlap
                del X
                pitch_fix = lambda s:self.pitch_fix(s, sr_pitched, org_mix)

                if S > 1:
                    sources = {k: pitch_fix(v) if self.is_pitch_change else v for k, v in zip(self.mdx_c_configs.training.instruments, estimated_sources.cpu().detach().numpy())}
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
                                sources[VOCAL_STEM] = spec_utils.match_array_shapes(sources[VOCAL_STEM], org_mix)
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
            model=self.model_basename,
        ):
            sr_pitched = _mdx_pitch_reference_sr()
            org_mix = mix
            if self.is_pitch_change:
                mix, sr_pitched = spec_utils.change_pitch_semitones(mix, 44100, semitone_shift=-self.semitone_shift)

            device = self.device

            from engines.model_weight_cache import (
                get_weight_cache,
                materialize_module,
                weight_cache_key,
            )

            key = weight_cache_key(
                "mdx_roformer",
                self.model_path,
                device,
                bool(self.is_roformer),
                getattr(self.mdx_c_configs.inference, "dim_t", None),
            )
            self._weight_cache_key = key
            cached = get_weight_cache().get(key)
            if cached and cached.module is not None:
                model: Any = materialize_module(cached.module, device)
            else:
                # Load first: the checkpoint's keys decide whether this is a
                # HyperACE variant, which upstream configs do not declare.
                checkpoint = _load_torch_checkpoint(self.model_path)
                model = _build_mdx_c_model(
                    self.roformer_config, state_dict_keys=list(checkpoint.keys())
                )
                model = model if not isinstance(model, torch.nn.DataParallel) else model.module
                model.load_state_dict(checkpoint)
                del checkpoint
                model.to(device).eval()
            self._inference_model = model
            mix = torch.as_tensor(mix, dtype=torch.float32, device=device)

            result = counter = estimated_sources = None
            try:
                segment_size = self.mdx_c_configs.inference.dim_t if self.is_mdx_c_seg_def else self.mdx_segment_size
                S = 1 if self.roformer_config.training.target_instrument else len(self.roformer_config.training.instruments)
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
                    req_shape = (S, ) + tuple(mix.shape)
                    result = torch.zeros(req_shape, dtype=torch.float32, device=device)
                    counter = torch.zeros(req_shape, dtype=torch.float32, device=device)
                    batch_data = []
                    batch_locations = []

                    i = 0

                    while i < mix.shape[1]:
                        self.check_run_control()
                        part = mix[:, i:i + C]
                        length = part.shape[-1]
                        if length < C:
                            if length > C // 2 + 1:
                                part = nn.functional.pad(part, (0, C - length), mode='reflect')
                            else:
                                part = nn.functional.pad(part, (0, C - length, 0, 0), mode='constant', value=0)

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
                                        f"CUDA OOM — reducing MDX batch size to {batch_size}"
                                    )
                                    continue
                                if torch.is_tensor(x) and x.dtype != torch.float32:
                                    x = x.float()

                                for j, (start, l) in enumerate(chunk_locations):
                                    self.running_inference_progress_bar(batch_len)
                                    window = select_roformer_ola_window(
                                        start,
                                        C,
                                        mix.shape[1],
                                        window_start,
                                        window_middle,
                                        window_finish,
                                    )
                                    result = self.overlap_add(result, counter, x, l, j, start, window)
                                idx += take

                            batch_data = []
                            batch_locations = []

                    # Normalize by the overlap counter and remove padding
                    estimated_sources = result / counter.clamp(min=1e-10)

                    if length_init > 2 * (C - step) and (C - step > 0):
                        estimated_sources = estimated_sources[..., (C - step):-(C - step)]

                pitch_fix = lambda s:self.pitch_fix(s, sr_pitched, org_mix)

                if S > 1 or self.is_vocal_main_target:
                    sources = {k: pitch_fix(v) if self.is_pitch_change else v for k, v in zip(self.mdx_c_configs.training.instruments, estimated_sources.cpu().detach().numpy())}
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
                    sources = {k: v.cpu().detach().numpy() for k, v in zip([self.mdx_c_configs.training.target_instrument], estimated_sources)}
                    est_s = sources[self.mdx_c_configs.training.target_instrument]

                    return pitch_fix(est_s) if self.is_pitch_change else est_s
            finally:
                for tensor in (result, counter, mix, estimated_sources):
                    if tensor is not None:
                        del tensor
                # Keep weights on self._inference_model for release_separator / weight cache.
