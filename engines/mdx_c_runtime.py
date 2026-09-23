"""MDX-C native inference and explicit weight acquisition phases."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Callable

import librosa
import torch

from bundled.constants import DONE, LOADING_MODEL
from core.debug_log import trace_phase
from core.model_stem_semantics import is_vocal_target
from ml.tfc_tdf_v3 import TFC_TDF_net

from .mdx_c import _load_torch_checkpoint, build_mdx_c_model
from .mdx_c_export import MDXCNativeResult
from .model_weight_cache import materialize_module, weight_cache_key
from .runtime_compat import EngineLegacyOptions

if TYPE_CHECKING:
    from .mdx_c_engine import SeperateMDXC


@dataclass(frozen=True)
class MDXCAcquisitionRequest:
    """Effective pass values shared by checkpoint loading and cache identity."""

    model_path: str
    config: Any
    roformer: bool
    variants: tuple[Any, ...]

    @classmethod
    def from_separator(
        cls, separator: EngineLegacyOptions, *, roformer: bool
    ) -> MDXCAcquisitionRequest:
        dim_t = getattr(separator.mdx_c_configs.inference, "dim_t", None)
        return cls(
            separator.model_path,
            separator.roformer_config if roformer else separator.mdx_c_configs,
            roformer,
            (bool(separator.is_roformer), dim_t) if roformer else (dim_t,),
        )

    def cache_key(self, device: Any) -> Any:
        return weight_cache_key(
            "mdx_roformer" if self.roformer else "mdx_c", self.model_path, device, *self.variants
        )


def acquire_mdx_c_model(
    request: MDXCAcquisitionRequest, device: Any, *, weight_cache: Any, cache_key: Any
) -> Any:
    model_path = request.model_path
    cached = weight_cache.get(cache_key)
    if cached and cached.module is not None:
        return materialize_module(cached.module, device)
    if request.roformer:
        # Checkpoint keys decide HyperACE before construction, just as before.
        checkpoint = _load_torch_checkpoint(model_path)
        model = build_mdx_c_model(request.config, state_dict_keys=list(checkpoint.keys()))
        model = model if not isinstance(model, torch.nn.DataParallel) else model.module
        model.load_state_dict(checkpoint)
        del checkpoint
        model.to(device).eval()
    else:
        model = TFC_TDF_net(request.config, device=device)
        model.load_state_dict(_load_torch_checkpoint(model_path))
        model.to(device).eval()
    return model


def infer_mdx_c_native(self: SeperateMDXC, *, prepare_mix: Callable[..., Any]) -> MDXCNativeResult:
    # A *roformer* model whose single target_instrument is the vocal stem is
    # treated as a vocals+instrumental model: ``demix`` derives the
    # instrumental as ``mixture - vocals``. Classic (non-roformer) MDX-C
    # models are excluded so their original single-stem output is preserved.
    target = str(getattr(self.mdx_c_configs.training, "target_instrument", None) or "")
    self.is_vocal_main_target = self.is_roformer and is_vocal_target(target)
    samplerate = 44100
    sources = None

    if self.primary_model_name == self.model_cache_key and isinstance(self.primary_sources, tuple):
        mix, sources = self.primary_sources
        self.load_cached_sources()
    else:
        with trace_phase(
            "separate", "seperate", engine="SeperateMDXC", model=self.model_display_label
        ):
            self.start_inference_console_write()
            self.write_to_console(LOADING_MODEL)
            mix = prepare_mix(self.audio_file)
            export_mix = mix
            export_rate = samplerate
            model_rate = int(
                getattr(self.mdx_c_configs.audio, 'sample_rate', export_rate) or export_rate
            )
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

    stem_list = (
        [self.mdx_c_configs.training.target_instrument]
        if self.mdx_c_configs.training.target_instrument and not self.is_vocal_main_target
        else [i for i in self.mdx_c_configs.training.instruments]
    )

    return MDXCNativeResult(mix, sources, samplerate, tuple(stem_list))
