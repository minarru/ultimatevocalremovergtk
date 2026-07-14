"""Mix preparation helpers."""
import os
import audioread
import librosa
import numpy as np
from scipy import signal

from core.debug_log import trace_phase

def gather_sources(primary_stem_name, secondary_stem_name, secondary_sources: dict):
    
    source_primary = False
    source_secondary = False

    for key, value in secondary_sources.items():
        if key == primary_stem_name:
            source_primary = value
        elif key == secondary_stem_name:
            source_secondary = value
        elif source_primary is False and key in primary_stem_name:
            source_primary = value
        elif source_secondary is False and key in secondary_stem_name:
            source_secondary = value

    return source_primary, source_secondary
def prepare_mix(mix):
    with trace_phase("separate", "prepare_mix"):
        audio_path = mix

        if not isinstance(mix, np.ndarray):
            mix, sr = librosa.load(mix, mono=False, sr=44100)
        else:
            mix = mix.T

        if isinstance(audio_path, str):
            if not np.any(mix) and audio_path.endswith('.mp3'):
                mix = rerun_mp3(audio_path)

        if mix.ndim == 1:
            mix = np.asfortranarray([mix,mix])

        return mix

def rerun_mp3(audio_file, sample_rate=44100):

    with audioread.audio_open(audio_file) as f:
        track_length = int(f.duration)

    return librosa.load(audio_file, duration=track_length, mono=False, sr=sample_rate)[0]
def pitch_shift(mix):
    new_sr = 31183

    # Resample audio file
    resampled_audio = signal.resample_poly(mix, new_sr, 44100)
    
    return resampled_audio

def list_to_dictionary(lst):
    dictionary = {item: index for index, item in enumerate(lst)}
    return dictionary
