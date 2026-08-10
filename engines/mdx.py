from __future__ import annotations
import typing
from typing import Any, TYPE_CHECKING

import gc
import gzip
import inspect
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
from core.torch_checkpoint import as_model_state_dict, load_torch_checkpoint
from core.model_stem_semantics import is_vocal_target
from core.stems import StemId, resolve_in_sources
from ml import spec_utils
import ml.mdxnet as MdxnetSet

from .base import SeperateAttributes
from .mix import prepare_mix, gather_sources, rerun_mp3
from .export import save_format
from .mdx_classic_batch import (
    is_oom_message,
    mdx_hop_starts,
    next_batch_after_oom,
    resolve_mdx_effective_batch,
)
from .vr_utils import vr_denoiser, loading_mix

if TYPE_CHECKING:
    from core.model_config import ModelConfig

# onnxruntime reports CUDA OOM through its own exception types rather than
# torch.cuda.OutOfMemoryError, so the ORT-backed classic MDX path (the
# default whenever mdx_segment_size == dim_t) needs to catch these too or its
# batch-size backoff never fires and a VRAM-pressure OOM crashes the run.
_ORT_RUNTIME_EXCEPTIONS = tuple(
    cls
    for cls in (
        getattr(ort.capi.onnxruntime_pybind11_state, "Fail", None),
        getattr(ort.capi.onnxruntime_pybind11_state, "RuntimeException", None),
    )
    if cls is not None
)


def _is_batch_oom(exc: BaseException) -> bool:
    """Whether ``exc`` represents a GPU memory allocation failure worth retrying."""
    if isinstance(exc, torch.cuda.OutOfMemoryError):
        return True
    return is_oom_message(str(exc))

cpu = torch.device('cpu')
warnings.filterwarnings("ignore")

from ml.tfc_tdf_v3 import TFC_TDF_net, STFT
from ml.mel_band_roformer import MelBandRoformer
from ml.bs_roformer import BSRoformer
from .orchestration import process_secondary_model


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
    selected_stems: typing.Any,
    mdxnet_stem_select: typing.Any,
    is_secondary_model: typing.Any,
    is_pre_proc_model: typing.Any,
    is_ensemble_master: typing.Any,
    is_4_stem_ensemble: typing.Any,
    is_primary_stem_only: typing.Any,
    is_secondary_stem_only: typing.Any,
    include_stem_complement: typing.Any,
):
    is_full_selection = (not selected_stems) or set(selected_stems) == set(stem_list)
    is_all_stems = mdxnet_stem_select == ALL_STEMS
    is_not_ensemble_master = not is_ensemble_master
    is_not_single_stem = not len(stem_list) <= 2
    is_not_secondary_model = not is_secondary_model
    is_ensemble_4_stem = is_4_stem_ensemble and is_not_single_stem
    is_vocals_quick_export = (
        len(selected_stems) == 1
        # A checkpoint's own yaml casing (often lowercase, e.g. ``vocals``)
        # rarely matches the canonical ``VOCAL_STEM`` constant a raw ``==``
        # would need -- is_vocal_target compares case/alias-insensitively.
        and is_vocal_target(selected_stems[0])
        and (is_primary_stem_only or is_secondary_stem_only)
    )
    is_complement_export = (
        len(selected_stems) == 1
        and bool(include_stem_complement)
        and not is_vocals_quick_export
    )
    is_native_pick = (
        len(selected_stems) == 1
        and is_not_ensemble_master
        and is_not_single_stem
        and is_not_secondary_model
        and not is_pre_proc_model
        and not is_vocals_quick_export
        and not is_complement_export
    )
    is_stem_subset = (
        len(selected_stems) >= 2 and not is_full_selection
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
            [stem for stem in stem_list if stem in selected_stems]
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


def derive_mdx_complement(native_source: typing.Any, mix: typing.Any, *, invert_spec: typing.Any=False, match_frequency_pitch: typing.Any=None):
    raw_mix = match_frequency_pitch(mix) if match_frequency_pitch is not None else mix
    shaped = spec_utils.to_shape(native_source, raw_mix.shape)
    if invert_spec:
        return spec_utils.invert_stem(raw_mix, shaped)
    return (-shaped.T + raw_mix.T)


class SeperateMDX(SeperateAttributes):        

    def seperate(self) -> dict[str, Any] | None:
        samplerate = 44100
        self.model_run: Any
    
        if self.primary_model_name == self.model_basename and isinstance(self.primary_sources, tuple):
            mix, source = self.primary_sources
            self.load_cached_sources()
        else:
            with trace_phase("separate", "seperate", engine="SeperateMDX", model=self.model_basename):
                self.start_inference_console_write()
                self.write_to_console(LOADING_MODEL)

                from engines.model_weight_cache import (
                    get_weight_cache,
                    materialize_module,
                    weight_cache_key,
                )

                cache = get_weight_cache()
                if self.is_mdx_ckpt:
                    key = weight_cache_key("mdx_ckpt", self.model_path, self.device)
                    self._weight_cache_key = key
                    cached = cache.get(key)
                    if cached and cached.module is not None:
                        self.model_run = materialize_module(cached.module, self.device)
                        self.dim_c = cached.meta.get("dim_c", self.dim_c)
                        self.hop = cached.meta.get("hop", self.hop)
                    else:
                        model_params = load_torch_checkpoint(
                            self.model_path, map_location=lambda storage, loc: storage
                        )["hyper_parameters"]
                        self.dim_c, self.hop = model_params['dim_c'], model_params['hop_length']
                        separator = MdxnetSet.ConvTDFNet(**model_params)
                        self.model_run = separator.load_from_checkpoint(self.model_path).to(self.device).eval()
                        self._weight_cache_meta = {"dim_c": self.dim_c, "hop": self.hop}
                else:
                    use_ort = self.mdx_segment_size == self.dim_t and not self.is_other_gpu
                    if use_ort:
                        from engines.amp_runtime import autocast_enabled

                        if autocast_enabled(self.settings):
                            self.write_to_console(
                                "Note: FP16 autocast has no effect on this ONNX Runtime "
                                "model; it only accelerates PyTorch-based models.\n"
                            )
                    key = weight_cache_key(
                        "mdx_ort" if use_ort else "mdx_convert",
                        self.model_path,
                        self.device,
                        self.mdx_segment_size,
                        self.dim_t,
                        bool(self.is_other_gpu),
                    )
                    self._weight_cache_key = key
                    cached = cache.get(key)
                    if use_ort:
                        if cached and cached.ort_session is not None:
                            self._ort_session = cached.ort_session
                        else:
                            from engines.amp_runtime import make_ort_session_options

                            # Cached ORT sessions already carry these options from first create.
                            self._ort_session = ort.InferenceSession(
                                self.model_path,
                                sess_options=make_ort_session_options(),
                                providers=self.run_type,
                            )
                        from engines.amp_runtime import build_ort_runner

                        self.model_run = build_ort_runner(self._ort_session, self.device)
                    else:
                        if cached and cached.module is not None:
                            self.model_run = materialize_module(cached.module, self.device)
                        else:
                            self.model_run = ConvertModel(load(self.model_path))
                            self.model_run.to(self.device).eval()

                self.running_inference_console_write()
                mix = prepare_mix(self.audio_file)
                
                source: Any = self.demix(mix)
                
                if not self.is_vocal_split_model:
                    self.cache_source((mix, source))
                self.write_to_console(DONE, base_text='')            

        mdx_net_cut = True if self.primary_stem in MDX_NET_FREQ_CUT and self.is_match_frequency_pitch else False

        if self.is_secondary_model_activated and self.secondary_model:
            self.secondary_source_primary, self.secondary_source_secondary = process_secondary_model(self.secondary_model, self.process_data, main_process_method=self.process_method, main_model_primary=self.primary_stem)
        
        self.begin_save_phase(
            int(not self.is_primary_stem_only) + int(not self.is_secondary_stem_only) or 1
        )
        if not self.is_primary_stem_only:
            secondary_stem_path = self.stem_export_wav_path(self.secondary_stem)
            if not isinstance(self.secondary_source, np.ndarray):
                # Match-mix demix only affects invert-spec; defaults use mix-source subtraction.
                if self.is_invert_spec:
                    raw_mix = (
                        self.demix(self.match_frequency_pitch(mix), is_match_mix=True)
                        if mdx_net_cut
                        else self.match_frequency_pitch(mix)
                    )
                    self.secondary_source = spec_utils.invert_stem(raw_mix, source)
                else:
                    self.secondary_source = mix.T - source.T
            
            self.secondary_source_map = self.final_process(secondary_stem_path, self.secondary_source, self.secondary_source_secondary, self.secondary_stem, samplerate)
        
        if not self.is_secondary_stem_only:
            primary_stem_path = self.stem_export_wav_path(self.primary_stem)

            if not isinstance(self.primary_source, np.ndarray):
                self.primary_source = source.T
                
            self.primary_source_map = self.final_process(primary_stem_path, self.primary_source, self.secondary_source_primary, self.primary_stem, samplerate)
        
        secondary_sources = {**self.primary_source_map, **self.secondary_source_map}
        
        self.process_vocal_split_chain(secondary_sources)

        if self.is_secondary_model or self.is_pre_proc_model:
            return secondary_sources

    def initialize_model_settings(self):
        self.n_bins = self.n_fft//2+1
        self.trim = self.n_fft//2
        self.chunk_size = self.hop * (self.mdx_segment_size-1)
        self.gen_size = self.chunk_size-2*self.trim
        self.stft = STFT(self.n_fft, self.hop, self.dim_f, self.device)

    def demix(self, mix: typing.Any, is_match_mix: typing.Any=False):
        with trace_phase(
            "separate",
            "demix",
            engine="SeperateMDX",
            model=self.model_basename,
            match_mix=is_match_mix,
        ):
            self.initialize_model_settings()
            
            org_mix = mix
            tar_waves_ = []
            # Only read back under ``is_pitch_change``, which is also the only
            # branch that reassigns it; seeded so the name is always bound.
            sr_pitched = 44100

            if is_match_mix:
                chunk_size = self.hop * (256-1)
                overlap = 0.02
            else:
                chunk_size = self.chunk_size
                overlap = self.overlap_mdx
                
                if self.is_pitch_change:
                    mix, sr_pitched = spec_utils.change_pitch_semitones(mix, 44100, semitone_shift=-self.semitone_shift)

            gen_size = chunk_size-2*self.trim

            pad = gen_size + self.trim - ((mix.shape[-1]) % gen_size)
            mixture = np.concatenate((np.zeros((2, self.trim), dtype='float32'), mix, np.zeros((2, pad), dtype='float32')), 1)
            mixture_t = torch.as_tensor(mixture, dtype=torch.float32, device=self.device)

            # ``overlap`` is always a float here: model_data resolves the
            # ``Default`` sentinel to 0.25 before it reaches the engine, so
            # upstream's ``chunk_size - n_fft`` branch is unreachable.
            step = int((1 - overlap) * chunk_size)
            mix_len = mixture_t.shape[-1]
            result = torch.zeros((1, 2, mix_len), dtype=torch.float32, device=self.device)
            divider = torch.zeros((1, 2, mix_len), dtype=torch.float32, device=self.device)

            from engines.amp_runtime import ort_fixed_batch_size

            hop_starts = mdx_hop_starts(mix_len, step)
            n_chunks = len(hop_starts)
            ort_session = getattr(self, "_ort_session", None)
            fixed_batch = ort_fixed_batch_size(ort_session) if ort_session is not None else None
            effective_batch = resolve_mdx_effective_batch(self.mdx_batch_size, fixed_batch)
            window_cache: dict[int, torch.Tensor] = {}

            def _hanning_window(length: int) -> torch.Tensor:
                cached = window_cache.get(length)
                if cached is None:
                    cached = torch.as_tensor(
                        np.hanning(length),
                        dtype=torch.float32,
                        device=self.device,
                    ).view(1, 1, -1)
                    window_cache[length] = cached
                return cached.expand(1, 2, -1)

            def _scatter_ola(tar_waves: typing.Any, meta: typing.Any) -> None:
                for item_idx, (start, end, chunk_size_actual) in enumerate(meta):
                    item = tar_waves[item_idx : item_idx + 1]
                    if overlap != 0:
                        window = _hanning_window(chunk_size_actual)
                        item[..., :chunk_size_actual] *= window
                        divider[..., start:end] += window
                    else:
                        divider[..., start:end] += 1
                    result[..., start:end] += item[..., : end - start]

            with torch.inference_mode():
                hop_idx = 0
                progress_units = max(1, n_chunks)
                while hop_idx < n_chunks:
                    self.check_run_control()
                    take = min(effective_batch, n_chunks - hop_idx)
                    windows = []
                    meta = []
                    for offset in range(take):
                        start = hop_starts[hop_idx + offset]
                        end = min(start + chunk_size, mix_len)
                        chunk_size_actual = end - start
                        mix_part = mixture_t[:, start:end]
                        if end != start + chunk_size:
                            mix_part = torch.nn.functional.pad(
                                mix_part, (0, (start + chunk_size) - end)
                            )
                        windows.append(mix_part)
                        meta.append((start, end, chunk_size_actual))

                    batch = torch.stack(windows, dim=0)
                    try:
                        tar_waves = self.run_model(batch, is_match_mix=is_match_mix)
                    except (torch.cuda.OutOfMemoryError, *_ORT_RUNTIME_EXCEPTIONS) as exc:
                        if not _is_batch_oom(exc):
                            raise
                        del batch, windows
                        if torch.cuda.is_available():
                            torch.cuda.empty_cache()
                        smaller = next_batch_after_oom(take)
                        if smaller is None:
                            raise
                        effective_batch = smaller
                        self.write_to_console(
                            f"CUDA OOM — reducing MDX batch size to {effective_batch}"
                        )
                        continue

                    for _ in range(take):
                        self.running_inference_progress_bar(
                            progress_units, is_match_mix=is_match_mix
                        )
                    _scatter_ola(tar_waves, meta)
                    hop_idx += take

            tar_waves = (result / divider).detach().cpu().numpy()
            tar_waves_.append(tar_waves)

            tar_waves_ = np.vstack(tar_waves_)[:, :, self.trim:-self.trim]
            tar_waves = np.concatenate(tar_waves_, axis=-1)[:, :mix.shape[-1]]

            source = tar_waves[:,0:None]

            if self.is_pitch_change and not is_match_mix:
                source = self.pitch_fix(source, sr_pitched, org_mix)

            source = source if is_match_mix else source*self.compensate

            if self.is_denoise_model and not is_match_mix:
                # ``primary_stem_native`` stays None when model resolution never
                # reached a branch that sets it; ``in`` would raise on None.
                native = str(self.primary_stem_native or "")
                if NO_STEM in native or native == INST_STEM:
                    if org_mix.shape[1] != source.shape[1]:
                        source = spec_utils.match_array_shapes(source, org_mix)
                    source = org_mix - vr_denoiser(
                        org_mix - source,
                        self.device,
                        model_path=self.DENOISER_MODEL,
                        settings=self.settings,
                    )
                else:
                    source = vr_denoiser(
                        source,
                        self.device,
                        model_path=self.DENOISER_MODEL,
                        settings=self.settings,
                    )

            return source

    def run_model(self, mix: typing.Any, is_match_mix: typing.Any=False):
        """Run STFT → model → iSTFT and return a device-resident waveform tensor."""
        from engines.amp_runtime import maybe_autocast

        if torch.is_tensor(mix):
            mix_device = mix if mix.device == self.device else mix.to(self.device)
        else:
            mix_device = torch.as_tensor(mix, device=self.device)
        spek = self.stft(mix_device) * self.adjust
        spek[:, :, :3, :] *= 0

        if is_match_mix:
            spec_pred = spek
        else:
            with maybe_autocast(self.device, self.settings):
                spec_pred = (
                    -self.model_run(-spek) * 0.5 + self.model_run(spek) * 0.5
                    if self.is_denoise
                    else self.model_run(spek)
                )

        if torch.is_tensor(spec_pred):
            # Keep OLA math in float32 even when autocast produced fp16 logits.
            return self.stft.inverse(spec_pred.float())
        return self.stft.inverse(torch.as_tensor(spec_pred, device=self.device, dtype=torch.float32))

class SeperateMDXC(SeperateAttributes):        

    def seperate(self) -> dict[str, Any] | None:
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
                if not self.is_vocal_split_model:
                    self.cache_source((mix, sources))
                self.write_to_console(DONE, base_text='')

        stem_list = [self.mdx_c_configs.training.target_instrument] if self.mdx_c_configs.training.target_instrument and not self.is_vocal_main_target else [i for i in self.mdx_c_configs.training.instruments]

        if self.is_secondary_model:
            if self.is_pre_proc_model:
                self.mdxnet_stem_select = stem_list[0]
            else:
                self.mdxnet_stem_select = self.main_model_primary_stem_4_stem if self.main_model_primary_stem_4_stem else self.primary_model_primary_stem
            self.primary_stem = str(self.mdxnet_stem_select or "")
            self.secondary_stem = secondary_stem(str(self.mdxnet_stem_select or ""))
            self.is_primary_stem_only, self.is_secondary_stem_only = False, False

        # Restrict export to the user-chosen subset of this model's stems. The
        # selection is intersected with the model's actual stems, so checking a
        # stem the model does not produce is simply ignored. An empty selection
        # (or one covering every stem) keeps the original "all stems" behaviour.
        selected_stems = mdx_selected_stems(stem_list, self.mdxnet_stems_selected)
        if not self.is_secondary_model and len(selected_stems) == 1:
            self.mdxnet_stem_select = selected_stems[0]

        routing = mdx_export_routing_flags(
            stem_list=stem_list,
            selected_stems=selected_stems,
            mdxnet_stem_select=self.mdxnet_stem_select,
            is_secondary_model=self.is_secondary_model,
            is_pre_proc_model=self.is_pre_proc_model,
            is_ensemble_master=self.process_data.is_ensemble_master,
            is_4_stem_ensemble=self.is_4_stem_ensemble,
            is_primary_stem_only=self.is_primary_stem_only,
            is_secondary_stem_only=self.is_secondary_stem_only,
            include_stem_complement=getattr(self, "is_mdx_include_stem_complement", False),
        )
        is_complement_export = routing["is_complement_export"]

        if is_complement_export:
            stem = selected_stems[0]
            complement_stem = secondary_stem(stem)
            self.begin_save_phase(2)
            native_path = self.stem_export_wav_path(stem)
            native_source = sources[stem].T
            self.write_audio(native_path, native_source, samplerate, stem_name=stem)
            complement_source = derive_mdx_complement(
                sources[stem],
                mix,
                invert_spec=self.is_invert_spec,
                match_frequency_pitch=self.match_frequency_pitch,
            )
            complement_path = self.stem_export_wav_path(complement_stem)
            self.write_audio(complement_path, complement_source, samplerate, stem_name=complement_stem)
            if stem == VOCAL_STEM and not self.is_sec_bv_rebalance:
                self.process_vocal_split_chain({VOCAL_STEM: stem})
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
            self.begin_save_phase(len(export_stems))
            for stem in export_stems:
                primary_stem_path = self.stem_export_wav_path(stem)
                self.primary_source = sources[stem].T
                self.write_audio(primary_stem_path, self.primary_source, samplerate, stem_name=stem)
                
                if stem == VOCAL_STEM and not self.is_sec_bv_rebalance:
                    self.process_vocal_split_chain({VOCAL_STEM:stem})
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

            self.begin_save_phase(
                int(not self.is_primary_stem_only) + int(not self.is_secondary_stem_only) or 1
            )
            if not self.is_primary_stem_only:
                secondary_stem_path = self.stem_export_wav_path(self.secondary_stem)
                if not isinstance(self.secondary_source, np.ndarray):
                    
                    if self.is_mdx_combine_stems and len(stem_list) >= 2:
                        if len(stem_list) == 2:
                            sec_key = mdx_combined_secondary_key(
                                working_sources, stem_list, self.secondary_stem
                            )
                            secondary_source = working_sources[sec_key]
                        else:
                            prim_key = resolve_in_sources(
                                working_sources, StemId(self.primary_stem)
                            )
                            if prim_key is not None:
                                working_sources.pop(prim_key, None)
                            next_stem = next(iter(working_sources))
                            secondary_source = np.zeros_like(working_sources[next_stem])
                            for v in working_sources.values():
                                secondary_source += v
                                
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
                            
                self.secondary_source_map = self.final_process(secondary_stem_path, self.secondary_source, self.secondary_source_secondary, self.secondary_stem, samplerate)    

            if not self.is_secondary_stem_only:
                primary_stem_path = self.stem_export_wav_path(self.primary_stem)
                if not isinstance(self.primary_source, np.ndarray):
                    self.primary_source = source_primary.T

                self.primary_source_map = self.final_process(primary_stem_path, self.primary_source, self.secondary_source_primary, self.primary_stem, samplerate)

        secondary_sources = {**self.primary_source_map, **self.secondary_source_map}
        self.process_vocal_split_chain(secondary_sources)
        
        if self.is_secondary_model or self.is_pre_proc_model:
            return secondary_sources

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
