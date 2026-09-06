from __future__ import annotations

import typing
from typing import TYPE_CHECKING, Any

import numpy as np
import onnxruntime as ort
import torch
from onnx import load
from onnx2pytorch import ConvertModel

import ml.mdxnet as MdxnetSet
from bundled.constants import *
from bundled.error_handling import *
from core.debug_log import trace_phase
from core.stems import exports_named_stem
from core.torch_checkpoint import load_torch_checkpoint
from ml import spec_utils

from .base import SeperateAttributes
from .mdx_classic_batch import (
    is_oom_message,
    mdx_hop_starts,
    mdx_oom_reduce_batch_message,
    next_batch_after_oom,
    resolve_mdx_effective_batch,
)
from .mix import prepare_mix
from .orchestration import process_secondary_model
from .vr_utils import vr_denoiser

if TYPE_CHECKING:
    from engines.stem_writer import ExportPlan

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

# Preserve the existing engine/vendor import order during preload.
from ml.tfc_tdf_v3 import STFT  # noqa: E402


class SeperateMDX(SeperateAttributes):
    def seperate(self) -> ExportPlan:
        samplerate = 44100
        self.model_run: Any

        if self.primary_model_name == self.model_cache_key and isinstance(
            self.primary_sources, tuple
        ):
            mix, source = self.primary_sources
            self.load_cached_sources()
        else:
            with trace_phase(
                "separate", "seperate", engine="SeperateMDX", model=self.model_display_label
            ):
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
                        # Checkpoints retain the upstream "l" key for layer count.
                        self.model_run = (
                            MdxnetSet.ConvTDFNet.load_from_checkpoint(
                                self.model_path, num_layers=model_params["l"]
                            ).to(self.device).eval()
                        )
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

        mdx_net_cut = (
            True
            if self.primary_stem in MDX_NET_FREQ_CUT and self.is_match_frequency_pitch
            else False
        )

        if self.is_secondary_model_activated and self.secondary_model:
            self.secondary_source_primary, self.secondary_source_secondary = (
                process_secondary_model(
                    self.secondary_model,
                    self.process_data,
                    main_process_method=self.process_method,
                    main_model_primary=self.primary_stem,
                )
            )

        sources: dict[str, Any] = {}
        if exports_named_stem(self, self.secondary_stem):
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
            sources[self.secondary_stem] = self.process_secondary_stem(
                self.secondary_source, self.secondary_source_secondary
            )

        if exports_named_stem(self, self.primary_stem):
            if not isinstance(self.primary_source, np.ndarray):
                self.primary_source = source.T
            sources[self.primary_stem] = self.process_secondary_stem(
                self.primary_source, self.secondary_source_primary
            )

        from engines.stem_writer import ExportPlan

        return ExportPlan(sources=sources, samplerate=samplerate)

    def initialize_model_settings(self):
        self.n_bins = self.n_fft // 2 + 1
        self.trim = self.n_fft // 2
        self.chunk_size = self.hop * (self.mdx_segment_size - 1)
        self.gen_size = self.chunk_size - 2 * self.trim
        self.stft = STFT(self.n_fft, self.hop, self.dim_f, self.device)

    def demix(self, mix: typing.Any, is_match_mix: typing.Any = False):
        with trace_phase(
            "separate",
            "demix",
            engine="SeperateMDX",
            model=self.model_display_label,
            match_mix=is_match_mix,
        ):
            self.initialize_model_settings()

            org_mix = mix
            tar_waves_ = []
            # Only read back under ``is_pitch_change``, which is also the only
            # branch that reassigns it; seeded so the name is always bound.
            sr_pitched = 44100

            if is_match_mix:
                chunk_size = self.hop * (256 - 1)
                overlap = 0.02
            else:
                chunk_size = self.chunk_size
                overlap = self.overlap_mdx

                if self.is_pitch_change:
                    mix, sr_pitched = spec_utils.change_pitch_semitones(
                        mix, 44100, semitone_shift=-self.semitone_shift
                    )

            gen_size = chunk_size - 2 * self.trim

            pad = gen_size + self.trim - ((mix.shape[-1]) % gen_size)
            mixture = np.concatenate(
                (
                    np.zeros((2, self.trim), dtype='float32'),
                    mix,
                    np.zeros((2, pad), dtype='float32'),
                ),
                1,
            )
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
                hop_weight = (
                    2 if self.is_denoise and not self.is_denoise_model and not is_match_mix else 1
                )
                progress_units = max(1, n_chunks * hop_weight)
                if not is_match_mix:
                    self.progress_total = progress_units
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
                            mdx_oom_reduce_batch_message(effective_batch)
                        )
                        continue

                    for _ in range(take):
                        for _unit in range(hop_weight):
                            self.running_inference_progress_bar(
                                progress_units, is_match_mix=is_match_mix
                            )
                    _scatter_ola(tar_waves, meta)
                    hop_idx += take

            tar_waves = (result / divider).detach().cpu().numpy()
            tar_waves_.append(tar_waves)

            tar_waves_ = np.vstack(tar_waves_)[:, :, self.trim : -self.trim]
            tar_waves = np.concatenate(tar_waves_, axis=-1)[:, : mix.shape[-1]]

            source = tar_waves[:, 0:None]

            if self.is_pitch_change and not is_match_mix:
                source = self.pitch_fix(source, sr_pitched, org_mix)

            source = source if is_match_mix else source * self.compensate

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
                        on_batch=self.denoise_progress_callback(),
                        check_run_control=self.check_run_control,
                    )
                else:
                    source = vr_denoiser(
                        source,
                        self.device,
                        model_path=self.DENOISER_MODEL,
                        settings=self.settings,
                        on_batch=self.denoise_progress_callback(),
                        check_run_control=self.check_run_control,
                    )

            return source

    def run_model(self, mix: typing.Any, is_match_mix: typing.Any = False):
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
        return self.stft.inverse(
            torch.as_tensor(spec_pred, device=self.device, dtype=torch.float32)
        )
