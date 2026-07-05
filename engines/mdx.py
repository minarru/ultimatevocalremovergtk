from __future__ import annotations
from typing import TYPE_CHECKING

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
from core.gpu_backend import clear_torch_cache, resolve_inference_backend
from ml import spec_utils
import ml.mdxnet as MdxnetSet

from .base import SeperateAttributes
from .gpu_cache import clear_gpu_cache
from .mix import prepare_mix, gather_sources, rerun_mp3
from .export import save_format
from .vr_utils import vr_denoiser, loading_mix

if TYPE_CHECKING:
    from core.model_data import ModelData

cpu = torch.device('cpu')
warnings.filterwarnings("ignore")

from ml.tfc_tdf_v3 import TFC_TDF_net, STFT
from ml.mel_band_roformer import MelBandRoformer
from ml.bs_roformer import BSRoformer
from .orchestration import process_secondary_model

class SeperateMDX(SeperateAttributes):        

    def seperate(self):
        samplerate = 44100
    
        if self.primary_model_name == self.model_basename and isinstance(self.primary_sources, tuple):
            mix, source = self.primary_sources
            self.load_cached_sources()
        else:
            with trace_phase("separate", "seperate", engine="SeperateMDX", model=self.model_basename):
                self.start_inference_console_write()
                self.write_to_console(LOADING_MODEL)

                if self.is_mdx_ckpt:
                    model_params = torch.load(self.model_path, map_location=lambda storage, loc: storage)['hyper_parameters']
                    self.dim_c, self.hop = model_params['dim_c'], model_params['hop_length']
                    separator = MdxnetSet.ConvTDFNet(**model_params)
                    self.model_run = separator.load_from_checkpoint(self.model_path).to(self.device).eval()
                else:
                    if self.mdx_segment_size == self.dim_t and not self.is_other_gpu:
                        ort_ = ort.InferenceSession(self.model_path, providers=self.run_type)
                        self.model_run = lambda spek:ort_.run(None, {'input': spek.cpu().numpy()})[0]
                    else:
                        self.model_run = ConvertModel(load(self.model_path))
                        self.model_run.to(self.device).eval()

                self.running_inference_console_write()
                mix = prepare_mix(self.audio_file)
                
                source = self.demix(mix)
                
                if not self.is_vocal_split_model:
                    self.cache_source((mix, source))
                self.write_to_console(DONE, base_text='')            

        mdx_net_cut = True if self.primary_stem in MDX_NET_FREQ_CUT and self.is_match_frequency_pitch else False

        if self.is_secondary_model_activated and self.secondary_model:
            self.secondary_source_primary, self.secondary_source_secondary = process_secondary_model(self.secondary_model, self.process_data, main_process_method=self.process_method, main_model_primary=self.primary_stem)
        
        if not self.is_primary_stem_only:
            secondary_stem_path = os.path.join(self.export_path, f'{self.audio_file_base}_({self.secondary_stem}).wav')
            if not isinstance(self.secondary_source, np.ndarray):
                raw_mix = self.demix(self.match_frequency_pitch(mix), is_match_mix=True) if mdx_net_cut else self.match_frequency_pitch(mix)
                self.secondary_source = spec_utils.invert_stem(raw_mix, source) if self.is_invert_spec else mix.T-source.T
            
            self.secondary_source_map = self.final_process(secondary_stem_path, self.secondary_source, self.secondary_source_secondary, self.secondary_stem, samplerate)
        
        if not self.is_secondary_stem_only:
            primary_stem_path = os.path.join(self.export_path, f'{self.audio_file_base}_({self.primary_stem}).wav')

            if not isinstance(self.primary_source, np.ndarray):
                self.primary_source = source.T
                
            self.primary_source_map = self.final_process(primary_stem_path, self.primary_source, self.secondary_source_primary, self.primary_stem, samplerate)
        
        clear_gpu_cache()

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

    def demix(self, mix, is_match_mix=False):
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

            step = self.chunk_size - self.n_fft if overlap == DEFAULT else int((1 - overlap) * chunk_size)
            result = np.zeros((1, 2, mixture.shape[-1]), dtype=np.float32)
            divider = np.zeros((1, 2, mixture.shape[-1]), dtype=np.float32)
            total = 0
            total_chunks = (mixture.shape[-1] + step - 1) // step

            for i in range(0, mixture.shape[-1], step):
                self.check_run_control()
                total += 1
                start = i
                end = min(i + chunk_size, mixture.shape[-1])

                chunk_size_actual = end - start

                if overlap == 0:
                    window = None
                else:
                    window = np.hanning(chunk_size_actual)
                    window = np.tile(window[None, None, :], (1, 2, 1))

                mix_part_ = mixture[:, start:end]
                if end != i + chunk_size:
                    pad_size = (i + chunk_size) - end
                    mix_part_ = np.concatenate((mix_part_, np.zeros((2, pad_size), dtype='float32')), axis=-1)

                mix_part = torch.tensor([mix_part_], dtype=torch.float32).to(self.device)
                mix_waves = mix_part.split(self.mdx_batch_size)
                
                with torch.no_grad():
                    for mix_wave in mix_waves:
                        self.running_inference_progress_bar(total_chunks, is_match_mix=is_match_mix)

                        tar_waves = self.run_model(mix_wave, is_match_mix=is_match_mix)
                        
                        if window is not None:
                            tar_waves[..., :chunk_size_actual] *= window 
                            divider[..., start:end] += window
                        else:
                            divider[..., start:end] += 1

                        result[..., start:end] += tar_waves[..., :end-start]
                
            tar_waves = result / divider
            tar_waves_.append(tar_waves)

            tar_waves_ = np.vstack(tar_waves_)[:, :, self.trim:-self.trim]
            tar_waves = np.concatenate(tar_waves_, axis=-1)[:, :mix.shape[-1]]
            
            source = tar_waves[:,0:None]

            if self.is_pitch_change and not is_match_mix:
                source = self.pitch_fix(source, sr_pitched, org_mix)

            source = source if is_match_mix else source*self.compensate

            if self.is_denoise_model and not is_match_mix:
                if NO_STEM in self.primary_stem_native or self.primary_stem_native == INST_STEM:
                    if org_mix.shape[1] != source.shape[1]:
                        source = spec_utils.match_array_shapes(source, org_mix)
                    source = org_mix - vr_denoiser(org_mix-source, self.device, model_path=self.DENOISER_MODEL)
                else:
                    source = vr_denoiser(source, self.device, model_path=self.DENOISER_MODEL)

            return source

    def run_model(self, mix, is_match_mix=False):
        
        spek = self.stft(mix.to(self.device))*self.adjust
        spek[:, :, :3, :] *= 0 

        if is_match_mix:
            spec_pred = spek.cpu().numpy()
        else:
            spec_pred = -self.model_run(-spek)*0.5+self.model_run(spek)*0.5 if self.is_denoise else self.model_run(spek)

        return self.stft.inverse(torch.tensor(spec_pred).to(self.device)).cpu().detach().numpy()

class SeperateMDXC(SeperateAttributes):        

    def seperate(self):
        # A *roformer* model whose single target_instrument is the vocal stem is
        # treated as a vocals+instrumental model: ``demix`` derives the
        # instrumental as ``mixture - vocals``. Classic (non-roformer) MDX-C
        # models are excluded so their original single-stem output is preserved.
        self.is_vocal_main_target = self.is_roformer and self.mdx_c_configs.training.target_instrument == VOCAL_STEM
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
                sources = self.demix(mix)
                if not self.is_vocal_split_model:
                    self.cache_source((mix, sources))
                self.write_to_console(DONE, base_text='')

        stem_list = [self.mdx_c_configs.training.target_instrument] if self.mdx_c_configs.training.target_instrument and not self.is_vocal_main_target else [i for i in self.mdx_c_configs.training.instruments]

        if self.is_secondary_model:
            if self.is_pre_proc_model:
                self.mdxnet_stem_select = stem_list[0]
            else:
                self.mdxnet_stem_select = self.main_model_primary_stem_4_stem if self.main_model_primary_stem_4_stem else self.primary_model_primary_stem
            self.primary_stem = self.mdxnet_stem_select
            self.secondary_stem = secondary_stem(self.mdxnet_stem_select)
            self.is_primary_stem_only, self.is_secondary_stem_only = False, False

        # Restrict export to the user-chosen subset of this model's stems. The
        # selection is intersected with the model's actual stems, so checking a
        # stem the model does not produce is simply ignored. An empty selection
        # (or one covering every stem) keeps the original "all stems" behaviour.
        selected_stems = [stem for stem in stem_list if stem in (self.mdxnet_stems_selected or [])]
        is_full_selection = (not selected_stems) or set(selected_stems) == set(stem_list)
        if not self.is_secondary_model and len(selected_stems) == 1:
            self.mdxnet_stem_select = selected_stems[0]

        is_all_stems = self.mdxnet_stem_select == ALL_STEMS
        is_not_ensemble_master = not self.process_data['is_ensemble_master']
        is_not_single_stem = not len(stem_list) <= 2
        is_not_secondary_model = not self.is_secondary_model
        is_ensemble_4_stem = self.is_4_stem_ensemble and is_not_single_stem

        # A "true subset": 2..n-1 of the multi-stem model's stems, only on the
        # main (non-secondary, non-pre-proc, non-ensemble) export path.
        is_stem_subset = (
            len(selected_stems) >= 2 and not is_full_selection
            and is_not_ensemble_master and is_not_single_stem
            and is_not_secondary_model and not self.is_pre_proc_model
        )

        if (is_all_stems and is_not_ensemble_master and is_not_single_stem and is_not_secondary_model) or is_ensemble_4_stem and not self.is_pre_proc_model or is_stem_subset:
            export_stems = [stem for stem in stem_list if stem in selected_stems] if is_stem_subset else stem_list
            for stem in export_stems:
                primary_stem_path = os.path.join(self.export_path, f'{self.audio_file_base}_({stem}).wav')
                self.primary_source = sources[stem].T
                self.write_audio(primary_stem_path, self.primary_source, samplerate, stem_name=stem)
                
                if stem == VOCAL_STEM and not self.is_sec_bv_rebalance:
                    self.process_vocal_split_chain({VOCAL_STEM:stem})
        else:
            if len(stem_list) == 1:
                source_primary = sources  
            else:
                if self.is_multi_stem_ensemble or len(stem_list) == 2:
                    stem_key = stem_list[0]
                elif self.mdxnet_stem_select == ALL_STEMS:
                    stem_key = self.primary_stem
                elif isinstance(sources, dict) and self.mdxnet_stem_select in sources:
                    stem_key = self.mdxnet_stem_select
                else:
                    stem_key = self.primary_stem
                source_primary = sources[stem_key]
            if self.is_secondary_model_activated and self.secondary_model:
                self.secondary_source_primary, self.secondary_source_secondary = process_secondary_model(self.secondary_model, 
                                                                                                         self.process_data, 
                                                                                                         main_process_method=self.process_method, 
                                                                                                         main_model_primary=self.primary_stem)

            if not self.is_primary_stem_only:
                secondary_stem_path = os.path.join(self.export_path, f'{self.audio_file_base}_({self.secondary_stem}).wav')
                if not isinstance(self.secondary_source, np.ndarray):
                    
                    if self.is_mdx_combine_stems and len(stem_list) >= 2:
                        if len(stem_list) == 2:
                            secondary_source = sources[self.secondary_stem]
                        else:
                            sources.pop(self.primary_stem)
                            next_stem = next(iter(sources))
                            secondary_source = np.zeros_like(sources[next_stem])
                            for v in sources.values():
                                secondary_source += v
                                
                        self.secondary_source = secondary_source.T 
                    elif isinstance(sources, dict) and self.secondary_stem in sources:
                        self.secondary_source = sources[self.secondary_stem].T
                    else:
                        self.secondary_source, raw_mix = source_primary, self.match_frequency_pitch(mix)
                        self.secondary_source = spec_utils.to_shape(self.secondary_source, raw_mix.shape)
                    
                        if self.is_invert_spec:
                            self.secondary_source = spec_utils.invert_stem(raw_mix, self.secondary_source)
                        else:
                            self.secondary_source = (-self.secondary_source.T+raw_mix.T)
                            
                self.secondary_source_map = self.final_process(secondary_stem_path, self.secondary_source, self.secondary_source_secondary, self.secondary_stem, samplerate)    

            if not self.is_secondary_stem_only:
                primary_stem_path = os.path.join(self.export_path, f'{self.audio_file_base}_({self.primary_stem}).wav')
                if not isinstance(self.primary_source, np.ndarray):
                    self.primary_source = source_primary.T

                self.primary_source_map = self.final_process(primary_stem_path, self.primary_source, self.secondary_source_primary, self.primary_stem, samplerate)

        clear_gpu_cache()
        
        secondary_sources = {**self.primary_source_map, **self.secondary_source_map}
        self.process_vocal_split_chain(secondary_sources)
        
        if self.is_secondary_model or self.is_pre_proc_model:
            return secondary_sources

    def overlap_add(self, result, x, l, j, start, window):
        if self.device == 'mps' or self.is_other_gpu:
            x = x.to(self.device)
        result[..., start:start + l] += x[j][..., :l] * window[..., :l]
        return result

    def demix(self, mix):
        if self.is_roformer:
            return self.demix_roformer(mix)

        with trace_phase(
            "separate",
            "demix",
            engine="SeperateMDXC",
            model=self.model_basename,
            roformer=False,
        ):
            sr_pitched = 441000
            org_mix = mix
            if self.is_pitch_change:
                mix, sr_pitched = spec_utils.change_pitch_semitones(mix, 44100, semitone_shift=-self.semitone_shift)

            model = TFC_TDF_net(self.mdx_c_configs, device=self.device)
            model.load_state_dict(torch.load(self.model_path, map_location=cpu))
            model.to(self.device).eval()
            self._inference_model = model
            mix = torch.tensor(mix, dtype=torch.float32)

            try:
                try:
                    S = model.num_target_instruments
                except Exception as e:
                    S = model.module.num_target_instruments

                mdx_segment_size = self.mdx_c_configs.inference.dim_t if self.is_mdx_c_seg_def else self.mdx_segment_size
                
                batch_size = self.mdx_batch_size
                chunk_size = self.mdx_c_configs.audio.hop_length * (mdx_segment_size - 1)
                overlap = self.overlap_mdx23

                hop_size = chunk_size // overlap
                mix_shape = mix.shape[1]
                pad_size = hop_size - (mix_shape - chunk_size) % hop_size
                mix = torch.cat([torch.zeros(2, chunk_size - hop_size), mix, torch.zeros(2, pad_size + chunk_size - hop_size)], 1)

                chunks = mix.unfold(1, chunk_size, hop_size).transpose(0, 1)
                batches = [chunks[i : i + batch_size] for i in range(0, len(chunks), batch_size)]
                
                X = torch.zeros(S, *mix.shape) if S > 1 else torch.zeros_like(mix)
                X = X.to(self.device)

                self.running_inference_console_write()

                with torch.no_grad():
                    cnt = 0
                    for batch in batches:
                        self.check_run_control()
                        self.running_inference_progress_bar(len(batches))
                        x = model(batch.to(self.device))
                        
                        for w in x:
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
                            sources[VOCAL_STEM] = vr_denoiser(sources[VOCAL_STEM], self.device, model_path=self.DENOISER_MODEL)
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
                model.cpu()
                del model
                self._inference_model = None
                clear_gpu_cache()

    def demix_roformer(self, mix):
        with trace_phase(
            "separate",
            "demix_roformer",
            engine="SeperateMDXC",
            model=self.model_basename,
        ):
            sr_pitched = 441000
            org_mix = mix
            if self.is_pitch_change:
                mix, sr_pitched = spec_utils.change_pitch_semitones(mix, 44100, semitone_shift=-self.semitone_shift)

            device = self.device

            # Build the roformer architecture indicated by the model's yaml config.
            if 'num_bands' in self.roformer_config.model:
                model = MelBandRoformer(**self.roformer_config.model)
            elif 'freqs_per_bands' in self.roformer_config.model:
                model = BSRoformer(**self.roformer_config.model)
            else:
                raise ValueError('Unknown model type in the configuration.')

            checkpoint = torch.load(self.model_path, map_location='cpu')
            model = model if not isinstance(model, torch.nn.DataParallel) else model.module
            model.load_state_dict(checkpoint)
            del checkpoint
            model.to(device).eval()
            self._inference_model = model
            mix = torch.tensor(mix, dtype=torch.float32)

            result = counter = estimated_sources = None
            try:
                segment_size = self.mdx_c_configs.inference.dim_t if self.is_mdx_c_seg_def else self.mdx_segment_size
                S = 1 if self.roformer_config.training.target_instrument else len(self.roformer_config.training.instruments)
                C = self.roformer_config.audio.hop_length * (segment_size - 1)
                N = self.overlap_mdx23
                step = int(C // N)
                fade_size = C // 10
                batch_size = self.roformer_config.inference.batch_size
                length_init = mix.shape[-1]

                # Padding the mix to account for border effects
                if length_init > 2 * (C - step) and (C - step > 0):
                    mix = nn.functional.pad(mix, (C - step, C - step), mode='reflect')

                # Set up windows for fade-in/out
                fadein = torch.linspace(0, 1, fade_size).to(device)
                fadeout = torch.linspace(1, 0, fade_size).to(device)
                window_start = torch.ones(C).to(device)
                window_middle = torch.ones(C).to(device)
                window_finish = torch.ones(C).to(device)
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
                        part = mix[:, i:i + C].to(device)
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
                            arr = torch.stack(batch_data, dim=0)
                            x = model(arr)

                            for j in range(len(batch_locations)):
                                self.running_inference_progress_bar(batch_len)
                                start, l = batch_locations[j]
                                window = window_middle
                                if start == 0:
                                    window = window_start
                                elif i >= mix.shape[1]:
                                    window = window_finish

                                result = self.overlap_add(result, x, l, j, start, window)
                                counter[..., start:start + l] += window[..., :l]

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
                        if sources[VOCAL_STEM].shape[1] != org_mix.shape[1]:
                            sources[VOCAL_STEM] = spec_utils.match_array_shapes(sources[VOCAL_STEM], org_mix)
                        sources[INST_STEM] = org_mix - sources[VOCAL_STEM]

                    return sources
                else:
                    sources = {k: v.cpu().detach().numpy() for k, v in zip([self.mdx_c_configs.training.target_instrument], estimated_sources)}
                    est_s = sources[self.mdx_c_configs.training.target_instrument]

                    return pitch_fix(est_s) if self.is_pitch_change else est_s
            finally:
                for tensor in (result, counter, mix, estimated_sources):
                    if tensor is not None:
                        del tensor
                model.cpu()
                del model
                self._inference_model = None
                clear_gpu_cache()
