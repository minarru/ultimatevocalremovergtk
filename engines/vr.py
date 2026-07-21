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
from core.torch_checkpoint import load_torch_checkpoint
from ml import spec_utils
import ml.mdxnet as MdxnetSet

from .base import SeperateAttributes
from .mix import prepare_mix, gather_sources, rerun_mp3
from .export import save_format
from .vr_utils import (
    loading_mix,
    multiband_waves_to_spectrogram,
    scale_mag_pad_inplace,
    vr_denoiser,
)

if TYPE_CHECKING:
    from core.model_data import ModelData

cpu = torch.device('cpu')
warnings.filterwarnings("ignore")

from ml.vr_network import nets, nets_new
from ml.vr_network.model_param_init import ModelParameters
from core.paths import VR_PARAM_DIR
from .orchestration import process_secondary_model

class SeperateVR(SeperateAttributes):        

    def seperate(self):
        if self.primary_model_name == self.model_basename and isinstance(self.primary_sources, tuple):
            y_spec, v_spec = self.primary_sources
            self.load_cached_sources()
        else:
            with trace_phase("separate", "seperate", engine="SeperateVR", model=self.model_basename):
                self.start_inference_console_write()
                self.write_to_console(LOADING_MODEL)

                device = self.device

                nn_arch_sizes = [
                    31191, # default
                    33966, 56817, 123821, 123812, 129605, 218409, 537238, 537227]
                vr_5_1_models = [56817, 218409]
                model_size = math.ceil(os.stat(self.model_path).st_size / 1024)
                nn_arch_size = min(nn_arch_sizes, key=lambda x:abs(x-model_size))

                from engines.model_weight_cache import (
                    get_weight_cache,
                    materialize_module,
                    weight_cache_key,
                )

                key = weight_cache_key(
                    "vr",
                    self.model_path,
                    device,
                    nn_arch_size,
                    bool(self.is_vr_51_model),
                    tuple(self.model_capacity),
                )
                self._weight_cache_key = key
                cached = get_weight_cache().get(key)
                if cached and cached.module is not None:
                    self.model_run = materialize_module(cached.module, device)
                    if nn_arch_size in vr_5_1_models or self.is_vr_51_model:
                        self.is_vr_51_model = True
                elif nn_arch_size in vr_5_1_models or self.is_vr_51_model:
                    self.model_run = nets_new.CascadedNet(self.mp.param['bins'] * 2, 
                                                          nn_arch_size, 
                                                          nout=self.model_capacity[0], 
                                                          nout_lstm=self.model_capacity[1])
                    self.is_vr_51_model = True
                    self.model_run.load_state_dict(load_torch_checkpoint(self.model_path, map_location=cpu)) 
                    self.model_run.to(device) 
                else:
                    self.model_run = nets.determine_model_capacity(self.mp.param['bins'] * 2, nn_arch_size)
                    self.model_run.load_state_dict(load_torch_checkpoint(self.model_path, map_location=cpu)) 
                    self.model_run.to(device) 

                self.running_inference_console_write()
                            
                self.check_run_control()
                y_spec, v_spec = self.inference_vr(self.loading_mix(), device, self.aggressiveness)
                if not self.is_vocal_split_model:
                    self.cache_source((y_spec, v_spec))
                self.write_to_console(DONE, base_text='')
            
        if self.is_secondary_model_activated and self.secondary_model:
            self.secondary_source_primary, self.secondary_source_secondary = process_secondary_model(self.secondary_model, self.process_data, main_process_method=self.process_method, main_model_primary=self.primary_stem)

        self.begin_save_phase(
            int(not self.is_primary_stem_only) + int(not self.is_secondary_stem_only) or 1
        )
        if not self.is_secondary_stem_only:
            primary_stem_path = self.stem_export_wav_path(self.primary_stem)
            if not isinstance(self.primary_source, np.ndarray):
                self.primary_source = self.spec_to_wav(y_spec).T
                if not self.model_samplerate == 44100:
                    self.primary_source = librosa.resample(self.primary_source.T, orig_sr=self.model_samplerate, target_sr=44100).T
                
            self.primary_source_map = self.final_process(primary_stem_path, self.primary_source, self.secondary_source_primary, self.primary_stem, 44100)  

        if not self.is_primary_stem_only:
            secondary_stem_path = self.stem_export_wav_path(self.secondary_stem)
            if not isinstance(self.secondary_source, np.ndarray):
                self.secondary_source = self.spec_to_wav(v_spec).T
                if not self.model_samplerate == 44100:
                    self.secondary_source = librosa.resample(self.secondary_source.T, orig_sr=self.model_samplerate, target_sr=44100).T
            
            self.secondary_source_map = self.final_process(secondary_stem_path, self.secondary_source, self.secondary_source_secondary, self.secondary_stem, 44100)
            
        secondary_sources = {**self.primary_source_map, **self.secondary_source_map}
        
        self.process_vocal_split_chain(secondary_sources)
        
        if self.is_secondary_model:
            return secondary_sources
            
    def loading_mix(self):

        self.check_run_control()
        bands_n = len(self.mp.param['band'])
        bp = self.mp.param['band'][bands_n]
        wav_resolution = (
            'polyphase' if SYSTEM_PROC == ARM or ARM in SYSTEM_ARCH else bp['res_type']
        ) if OPERATING_SYSTEM == 'Darwin' else bp['res_type']

        if isinstance(self.audio_file, np.ndarray):
            # Vocal-split / chain paths already provide decoded audio — skip WAV round-trip.
            wave = np.asarray(self.audio_file, dtype=np.float32)
            if wave.ndim == 1:
                wave = np.asarray([wave, wave])
            elif wave.shape[0] != 2 and wave.shape[-1] == 2:
                wave = wave.T
            target_sr = bp['sr']
            if target_sr != 44100:
                wave = librosa.resample(wave, orig_sr=44100, target_sr=target_sr, res_type=wav_resolution)
            X_wave = {bands_n: wave}
        else:
            audio_file = spec_utils.write_array_to_mem(self.audio_file, subtype=self.wav_type_set)
            is_mp3 = audio_file.endswith('.mp3') if isinstance(audio_file, str) else False
            X_wave = {
                bands_n: librosa.load(
                    audio_file,
                    sr=bp['sr'],
                    mono=False,
                    dtype=np.float32,
                    res_type=wav_resolution,
                )[0],
            }
            if not np.any(X_wave[bands_n]) and is_mp3:
                X_wave[bands_n] = rerun_mp3(audio_file, bp['sr'])
            if X_wave[bands_n].ndim == 1:
                X_wave[bands_n] = np.asarray([X_wave[bands_n], X_wave[bands_n]])
            del audio_file

        X_spec, X_spec_s, _ = multiband_waves_to_spectrogram(
            X_wave,
            self.mp,
            is_v51_model=self.is_vr_51_model,
            use_model_res_type=True,
        )

        if self.high_end_process != 'none':
            bp = self.mp.param['band'][bands_n]
            self.input_high_end_h = (bp['n_fft'] // 2 - bp['crop_stop']) + (
                self.mp.param['pre_filter_stop'] - self.mp.param['pre_filter_start']
            )
            self.input_high_end = X_spec_s[bands_n][
                :, bp['n_fft'] // 2 - self.input_high_end_h:bp['n_fft'] // 2, :
            ]

        del X_wave, X_spec_s
        return X_spec

    def inference_vr(self, X_spec, device, aggressiveness):
        with trace_phase("separate", "inference_vr", engine="SeperateVR", model=self.model_basename):
            def _execute(X_mag_pad, roi_size):
                patches = (X_mag_pad.shape[2] - 2 * self.model_run.offset) // roi_size
                total_iterations = patches//self.batch_size if not self.is_tta else (patches//self.batch_size)*2
                self.model_run.eval()
                with torch.inference_mode():
                    mask_parts = []
                    for i in range(0, patches, self.batch_size):
                        self.check_run_control()
                        self.progress_value += 1
                        if self.progress_value >= total_iterations:
                            self.progress_value = total_iterations
                        self.set_progress_bar(0.1, 0.8/total_iterations*self.progress_value)
                        end = min(i + self.batch_size, patches)
                        # Stream patches per batch instead of materializing all windows.
                        X_batch = np.stack(
                            [
                                X_mag_pad[:, :, j * roi_size : j * roi_size + self.window_size]
                                for j in range(i, end)
                            ],
                            axis=0,
                        )
                        X_batch = torch.from_numpy(X_batch).to(device)
                        pred = self.model_run.predict_mask(X_batch)
                        if not pred.size()[3] > 0:
                            raise Exception(ERROR_MAPPER[WINDOW_SIZE_ERROR])
                        # Fold batch windows into time on-device before the host sync.
                        mask_parts.append(torch.cat([pred[b] for b in range(pred.shape[0])], dim=2))
                    if len(mask_parts) == 0:
                        raise Exception(ERROR_MAPPER[WINDOW_SIZE_ERROR])

                    mask = torch.cat(mask_parts, dim=2).detach().cpu().numpy()
                return mask

            def postprocess(mask, X_mag, X_phase):
                is_non_accom_stem = False
                for stem in NON_ACCOM_STEMS:
                    if stem == self.primary_stem:
                        is_non_accom_stem = True
                        
                mask = spec_utils.adjust_aggr(mask, is_non_accom_stem, aggressiveness)

                if self.is_post_process:
                    mask = spec_utils.merge_artifacts(mask, thres=self.post_process_threshold)

                y_spec = mask * X_mag * np.exp(1.j * X_phase)
                v_spec = (1 - mask) * X_mag * np.exp(1.j * X_phase)
            
                return y_spec, v_spec
            
            X_mag, X_phase = spec_utils.preprocess(X_spec)
            n_frame = X_mag.shape[2]
            pad_l, pad_r, roi_size = spec_utils.make_padding(n_frame, self.window_size, self.model_run.offset)
            X_mag_pad = np.pad(X_mag, ((0, 0), (0, 0), (pad_l, pad_r)), mode='constant')
            scale_mag_pad_inplace(X_mag_pad)
            mask = _execute(X_mag_pad, roi_size)
            
            if self.is_tta:
                pad_l += roi_size // 2
                pad_r += roi_size // 2
                X_mag_pad = np.pad(X_mag, ((0, 0), (0, 0), (pad_l, pad_r)), mode='constant')
                scale_mag_pad_inplace(X_mag_pad)
                mask_tta = _execute(X_mag_pad, roi_size)
                mask_tta = mask_tta[:, :, roi_size // 2:]
                mask = (mask[:, :, :n_frame] + mask_tta[:, :, :n_frame]) * 0.5
            else:
                mask = mask[:, :, :n_frame]

            y_spec, v_spec = postprocess(mask, X_mag, X_phase)
            
            return y_spec, v_spec

    def spec_to_wav(self, spec):
        if self.high_end_process.startswith('mirroring') and isinstance(self.input_high_end, np.ndarray) and self.input_high_end_h:        
            input_high_end_ = spec_utils.mirroring(self.high_end_process, spec, self.input_high_end, self.mp)
            wav = spec_utils.cmb_spectrogram_to_wave(spec, self.mp, self.input_high_end_h, input_high_end_, is_v51_model=self.is_vr_51_model)       
        else:
            wav = spec_utils.cmb_spectrogram_to_wave(spec, self.mp, is_v51_model=self.is_vr_51_model)
            
        return wav
