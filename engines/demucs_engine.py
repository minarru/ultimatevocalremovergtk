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
from core.demucs_models import demucs_pretrained_load_name
from core.torch_checkpoint import load_torch_checkpoint
from ml import spec_utils
import ml.mdxnet as MdxnetSet

from .base import SeperateAttributes
from .mix import prepare_mix, gather_sources, rerun_mp3
from .export import save_format
from .vr_utils import vr_denoiser, loading_mix

if TYPE_CHECKING:
    from core.model_data import ModelData

cpu = torch.device('cpu')
warnings.filterwarnings("ignore")

from vendor.demucs.apply import apply_model, demucs_segments
from vendor.demucs.hdemucs import HDemucs
from vendor.demucs.model_v2 import auto_load_demucs_model_v2
from vendor.demucs.pretrained import get_model as _gm
from vendor.demucs.utils import apply_model_v1, apply_model_v2
from .orchestration import process_secondary_model

class SeperateDemucs(SeperateAttributes):
    def seperate(self):
        samplerate = 44100
        source = None
        model_scale = None
        stem_source = None
        stem_source_secondary = None
        inst_mix = None
        inst_source = None
        is_no_write = False
        is_no_piano_guitar = False
        is_no_cache = False
        
        if self.primary_model_name == self.model_basename and isinstance(self.primary_sources, np.ndarray) and not self.pre_proc_model:
            source = self.primary_sources
            self.load_cached_sources()
        else:
            self.start_inference_console_write()
            is_no_cache = True

        # Defer decode on stem-cache hits; load only if invert/combine needs the mix.
        mix = prepare_mix(self.audio_file) if is_no_cache else None

        if is_no_cache:
            with trace_phase(
                "separate",
                "seperate",
                engine="SeperateDemucs",
                model=self.model_basename,
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
                    if str(self.model_path).endswith(".gz"):
                        self.model_path = gzip.open(self.model_path, "rb")
                    klass, args, kwargs, state = load_torch_checkpoint(self.model_path)
                    self.demucs = klass(*args, **kwargs)
                    self.demucs.to(self.device) 
                    self.demucs.load_state_dict(state)
                elif self.demucs_version == DEMUCS_V2:
                    self.demucs = auto_load_demucs_model_v2(self.demucs_source_list, self.model_path)
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

                if self.pre_proc_model:
                    if self.primary_stem not in [VOCAL_STEM, INST_STEM]:
                        is_no_write = True
                        self.write_to_console(DONE, base_text='')
                        mix_no_voc = process_secondary_model(self.pre_proc_model, self.process_data, is_pre_proc_model=True)
                        inst_mix = prepare_mix(mix_no_voc[INST_STEM])
                        self.process_iteration()
                        self.running_inference_console_write(is_no_write=is_no_write)
                        inst_source = self.demix_demucs(inst_mix)
                        self.process_iteration()

                self.running_inference_console_write(is_no_write=is_no_write) if not self.pre_proc_model else None
                
                if self.primary_model_name == self.model_basename and isinstance(self.primary_sources, np.ndarray) and self.pre_proc_model:
                    source = self.primary_sources
                else:
                    source = self.demix_demucs(mix)
                
                self.write_to_console(DONE, base_text='')
            
        if isinstance(inst_source, np.ndarray):
            source_reshape = spec_utils.reshape_sources(inst_source[self.demucs_source_map[VOCAL_STEM]], source[self.demucs_source_map[VOCAL_STEM]])
            inst_source[self.demucs_source_map[VOCAL_STEM]] = source_reshape
            source = inst_source

        if isinstance(source, np.ndarray):
            
            if len(source) == 2:
                self.demucs_source_map = DEMUCS_2_SOURCE_MAPPER
            else:
                self.demucs_source_map = DEMUCS_6_SOURCE_MAPPER if len(source) == 6 else DEMUCS_4_SOURCE_MAPPER

                if len(source) == 6 and self.process_data['is_ensemble_master'] or len(source) == 6 and self.is_secondary_model:
                    is_no_piano_guitar = True
                    six_stem_other_source = list(source)
                    six_stem_other_source = [i for n, i in enumerate(source) if n in [self.demucs_source_map[OTHER_STEM], self.demucs_source_map[GUITAR_STEM], self.demucs_source_map[PIANO_STEM]]]
                    other_source = np.zeros_like(six_stem_other_source[0])
                    for i in six_stem_other_source:
                        other_source += i
                    source_reshape = spec_utils.reshape_sources(source[self.demucs_source_map[OTHER_STEM]], other_source)
                    source[self.demucs_source_map[OTHER_STEM]] = source_reshape
                    
        if not self.is_vocal_split_model:
            self.cache_source(source)
        
        if (self.demucs_stems == ALL_STEMS and not self.process_data['is_ensemble_master']) or self.is_4_stem_ensemble and not self.is_return_dual:
            self.begin_save_phase(len(self.demucs_source_map))
            for stem_name, stem_value in self.demucs_source_map.items():
                if self.is_secondary_model_activated and not self.is_secondary_model and not stem_value >= 4:
                    if self.secondary_model_4_stem[stem_value]:
                        model_scale = self.secondary_model_4_stem_scale[stem_value]
                        stem_source_secondary = process_secondary_model(self.secondary_model_4_stem[stem_value], self.process_data, main_model_primary_stem_4_stem=stem_name, is_source_load=True, is_return_dual=False)
                        if isinstance(stem_source_secondary, np.ndarray):
                            stem_source_secondary = stem_source_secondary[1 if self.secondary_model_4_stem[stem_value].demucs_stem_count == 2 else stem_value].T
                        elif type(stem_source_secondary) is dict:
                            stem_source_secondary = stem_source_secondary[stem_name]
                            
                stem_source_secondary = None if stem_value >= 4 else stem_source_secondary
                stem_path = self.stem_export_wav_path(stem_name)
                stem_source = source[stem_value].T
                
                stem_source = self.process_secondary_stem(stem_source, secondary_model_source=stem_source_secondary, model_scale=model_scale)
                self.write_audio(stem_path, stem_source, samplerate, stem_name=stem_name)
                
                if stem_name == VOCAL_STEM and not self.is_sec_bv_rebalance:
                    self.process_vocal_split_chain({VOCAL_STEM:stem_source})
                
            if self.is_secondary_model:    
                return source
        else:
            if self.is_secondary_model_activated and self.secondary_model:
                    self.secondary_source_primary, self.secondary_source_secondary = process_secondary_model(self.secondary_model, self.process_data, main_process_method=self.process_method)
                    
            save_writes = int(not self.is_primary_stem_only) + int(not self.is_secondary_stem_only)
            if self.is_demucs_pre_proc_model_inst_mix and self.pre_proc_model and not self.is_4_stem_ensemble:
                save_writes += int(not self.is_primary_stem_only)
            self.begin_save_phase(max(1, save_writes))

            if not self.is_primary_stem_only:
                def secondary_save(sec_stem_name, source, raw_mixture=None, is_inst_mixture=False):
                    nonlocal mix
                    secondary_source = self.secondary_source if not is_inst_mixture else None
                    secondary_stem_path = self.stem_export_wav_path(sec_stem_name)
                    secondary_source_secondary = None
                    
                    if not isinstance(secondary_source, np.ndarray):
                        if self.is_demucs_combine_stems:
                            source = list(source)
                            if is_inst_mixture:
                                source = [i for n, i in enumerate(source) if not n in [self.demucs_source_map[self.primary_stem], self.demucs_source_map[VOCAL_STEM]]]
                            else:
                                source.pop(self.demucs_source_map[self.primary_stem])
                                
                            source = source[:len(source) - 2] if is_no_piano_guitar else source
                            secondary_source = np.zeros_like(source[0])
                            for i in source:
                                secondary_source += i
                            secondary_source = secondary_source.T
                        else:
                            if not isinstance(raw_mixture, np.ndarray):
                                if mix is None:
                                    mix = prepare_mix(self.audio_file)
                                raw_mixture = mix
       
                            secondary_source = source[self.demucs_source_map[self.primary_stem]]
                            
                            if self.is_invert_spec:
                                secondary_source = spec_utils.invert_stem(raw_mixture, secondary_source)
                            else:
                                raw_mixture = spec_utils.reshape_sources(secondary_source, raw_mixture)
                                secondary_source = (-secondary_source.T+raw_mixture.T)
                            
                    if not is_inst_mixture:
                        self.secondary_source = secondary_source
                        secondary_source_secondary = self.secondary_source_secondary
                        self.secondary_source = self.process_secondary_stem(secondary_source, secondary_source_secondary)
                        self.secondary_source_map = {self.secondary_stem: self.secondary_source}

                    self.write_audio(secondary_stem_path, secondary_source, samplerate, stem_name=sec_stem_name)

                secondary_save(self.secondary_stem, source, raw_mixture=mix)
                
                if self.is_demucs_pre_proc_model_inst_mix and self.pre_proc_model and not self.is_4_stem_ensemble:
                    secondary_save(f"{self.secondary_stem} {INST_STEM}", source, raw_mixture=inst_mix, is_inst_mixture=True)

            if not self.is_secondary_stem_only:
                primary_stem_path = self.stem_export_wav_path(self.primary_stem)
                if not isinstance(self.primary_source, np.ndarray):
                    self.primary_source = source[self.demucs_source_map[self.primary_stem]].T
                
                self.primary_source_map = self.final_process(primary_stem_path, self.primary_source, self.secondary_source_primary, self.primary_stem, samplerate)

            secondary_sources = {**self.primary_source_map, **self.secondary_source_map}
            
            self.process_vocal_split_chain(secondary_sources)
            
            if self.is_secondary_model:    
                return secondary_sources
    
    def demix_demucs(self, mix):
        with trace_phase("separate", "demix_demucs", engine="SeperateDemucs", model=self.model_basename):
            org_mix = mix

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
                    sources = apply_model(
                        self.demucs,
                        mix_infer[None],
                        self.shifts,
                        self.is_split_mode,
                        self.overlap,
                        static_shifts=1 if self.shifts == 0 else self.shifts,
                        set_progress_bar=self.set_progress_bar,
                        device=self.device,
                    )[0]

            sources = (sources.float() * ref.std() + ref.mean()).cpu().numpy()
            sources[[0, 1]] = sources[[1, 0]]

            if self.is_pitch_change:
                sources = np.stack([self.pitch_fix(stem, sr_pitched, org_mix) for stem in sources])

            return sources
