"""Mix preparation helpers."""
import typing

import audioread
import librosa
import numpy as np
from scipy import signal

from core.debug_log import trace_phase


def gather_sources(primary_stem_name: typing.Any, secondary_stem_name: typing.Any, secondary_sources: dict):
    
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


def _as_channel_first(mix: np.ndarray) -> np.ndarray:
    """Normalize decoded / stem arrays to librosa layout ``(2, samples)``."""
    arr = np.asarray(mix, dtype=np.float32)
    if arr.ndim == 1:
        return np.asfortranarray([arr, arr])
    if arr.shape[0] == 2:
        # Already channel-first (including rare 2-sample stereo edge case).
        return arr
    if arr.shape[-1] == 2:
        return arr.T
    if arr.shape[1] == 2 and arr.shape[0] > 2:
        return arr.T
    raise ValueError(f"unsupported mix shape for prepare_mix: {arr.shape}")


def prepare_mix(mix: typing.Any):
    """Decode a path to stereo float32 at 44.1 kHz, or normalize an ndarray.

    Idempotent for already-decoded ``(2, N)`` mixes so ensemble / secondary /
    preprocess paths can reuse one decode from ``process_data``.
    """
    with trace_phase("separate", "prepare_mix"):
        if isinstance(mix, np.ndarray):
            return _as_channel_first(mix)

        audio_path = mix
        mix, _sr = librosa.load(mix, mono=False, sr=44100)

        if isinstance(audio_path, str):
            if not np.any(mix) and audio_path.endswith('.mp3'):
                mix = rerun_mp3(audio_path)

        return _as_channel_first(mix)

def rerun_mp3(audio_file: typing.Any, sample_rate: typing.Any=44100):

    with audioread.audio_open(audio_file) as f:
        track_length = int(f.duration)

    return librosa.load(audio_file, duration=track_length, mono=False, sr=sample_rate)[0]
def pitch_shift(mix: typing.Any):
    new_sr = 31183

    # Resample audio file
    resampled_audio = signal.resample_poly(mix, new_sr, 44100)
    
    return resampled_audio

def list_to_dictionary(lst: typing.Any):
    dictionary = {item: index for index, item in enumerate(lst)}
    return dictionary
