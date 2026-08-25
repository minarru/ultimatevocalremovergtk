"""MDX-C helpers: model build, export routing, and complement math."""
from __future__ import annotations
import typing
from typing import Any

import inspect

import numpy as np
import warnings

from bundled.constants import *
from core.model_stem_semantics import (
    is_vocal_target,
)
from core.stem_roles import StemRoleId
from core.stems import (
    StemBucket,
    StemRouteKind,
)
from ml import spec_utils

warnings.filterwarnings("ignore")

from ml.mel_band_roformer import MelBandRoformer
from ml.bs_roformer import BSRoformer


def _load_torch_checkpoint(path: str):
    from core.torch_checkpoint import as_model_state_dict, load_torch_checkpoint

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


# Public on purpose: these helpers are built against from outside this module
# (the engine that runs MDX-C, and the architecture probe), so an underscore
# would falsely imply single-module ownership. Named without pointing at any
# consumer -- this module deliberately knows nothing about them.
def filter_init_kwargs(model_cls: typing.Any, cfg: typing.Any) -> dict:
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


def build_mdx_c_model(
    config: typing.Any,
    state_dict_keys: typing.Optional[typing.Sequence[str]] = None,
    model_type_hint: typing.Optional[str] = None,
):
    if getattr(config, 'cls', None) == 'Bandit':
        from ml.bandit import Bandit

        kwargs = filter_init_kwargs(Bandit, config.kwargs)
        if 'fs' not in kwargs and hasattr(config.audio, 'sample_rate'):
            kwargs['fs'] = int(config.audio.sample_rate)
        return Bandit(**kwargs)

    model_cfg = getattr(config, 'model', None)
    if model_cfg is None:
        raise UnknownMDXCArchitecture('Unknown MDX-C architecture in configuration.')

    if 'num_bands' in model_cfg:
        kwargs = filter_init_kwargs(MelBandRoformer, model_cfg)
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
        kwargs = filter_init_kwargs(BSRoformer, model_cfg)
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
        # "Large Inst v2" attaches a transformer stack to every mask estimator.
        # Declared by a top-level yaml flag, like hyperace2 above, so it never
        # reaches the kwarg filter on its own.
        if getattr(config, 'unwa_inst_large_2', False):
            kwargs['mask_estimator_transformer'] = True
        return BSRoformer(**kwargs)
    if 'band_SR' in model_cfg or 'sources' in model_cfg:
        has_tran_kwargs = any(str(key).startswith('tran_') for key in model_cfg)
        if has_tran_kwargs:
            from ml.scnet import SCNetTran

            return SCNetTran(**filter_init_kwargs(SCNetTran, model_cfg))

        variant = scnet_variant_from_state_dict(state_dict_keys or ())
        if variant == 'masked' or model_type_hint in _SCNET_MASKED_HINTS:
            from ml.scnet import SCNetMasked

            return SCNetMasked(**filter_init_kwargs(SCNetMasked, model_cfg))

        from ml.scnet import SCNet

        return SCNet(**filter_init_kwargs(SCNet, model_cfg))
    if 'band_specs' in model_cfg:
        from ml.bandit import MultiMaskMultiSourceBandSplitRNN

        return MultiMaskMultiSourceBandSplitRNN(**filter_init_kwargs(MultiMaskMultiSourceBandSplitRNN, model_cfg))
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
        stem for stem in stem_list if _exact_mdx_source_key(lookup, str(stem)) is not None
    ]


def _exact_mdx_source_key(
    sources: typing.Mapping[str, typing.Any], native: str
) -> str | None:
    """Resolve an MDX-C backend key by exact spelling or casing only."""
    if native in sources:
        return native
    wanted = str(native).casefold()
    for key in sources:
        if str(key).casefold() == wanted:
            return str(key)
    return None


def mdx_combined_secondary_key(sources: typing.Any, stem_list: typing.Any, secondary_stem_label: typing.Any):
    """Key in ``sources`` holding the complement of a 2-stem MDX-C model.

    ``secondary_stem_label`` is a UVR pair name, which for a model trained on
    stems outside the pair table (``center``/``wide``) matches no source key at
    all. Fall back to the model's own other instrument.
    """
    key = _exact_mdx_source_key(sources, str(secondary_stem_label or ""))
    if key is None and len(stem_list) == 2:
        key = _exact_mdx_source_key(sources, str(stem_list[1]))
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
    *,
    routes: typing.Sequence[typing.Any] | None = None,
) -> dict[str, typing.Any]:
    """Build a chain handoff from exact reviewed native dependencies only."""
    merged = dict(maps)
    demix = demix_sources if isinstance(demix_sources, dict) else {}
    if routes is None:
        for key, source in demix.items():
            merged.setdefault(str(key), _channel_last_for_write(source))
        return merged

    handoff: dict[str, typing.Any] = {}
    canonical_by_role = {
        "vocal.vocals": VOCAL_STEM,
        "mix.instrumental": INST_STEM,
    }
    for route in routes:
        if route.native is None or not isinstance(route.role, StemRoleId):
            continue
        canonical_key = canonical_by_role.get(route.role.value)
        if canonical_key is None:
            continue
        source_key = _exact_mdx_source_key(maps, route.native.raw)
        if source_key is not None and isinstance(maps[source_key], np.ndarray):
            handoff[canonical_key] = maps[source_key]
            continue
        source_key = _exact_mdx_source_key(demix, route.native.raw)
        if source_key is not None and isinstance(demix[source_key], np.ndarray):
            handoff[canonical_key] = _channel_last_for_write(demix[source_key])
    return handoff


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
    primary_key = _exact_mdx_source_key(sources, primary_stem)
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
