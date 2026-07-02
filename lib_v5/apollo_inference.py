import gc

import torch
import librosa
import numpy as np

import lib_v5.apollo_model_data as models
from data.constants import CPU, CUDA_DEVICE, DEFAULT

import warnings
warnings.filterwarnings("ignore")

cuda_available = torch.cuda.is_available()


def clear_gpu_cache():
    gc.collect()
    if cuda_available:
        torch.cuda.empty_cache()


def load_audio(file_path):
    audio, samplerate = librosa.load(file_path, mono=False, sr=44100)
    return torch.from_numpy(audio), samplerate


def _getWindowingArray(window_size, fade_size):
    # IMPORTANT NOTE :
    # no fades here in the end, only removing the failed ending of the chunk
    fadein = torch.linspace(1, 1, fade_size)
    fadeout = torch.linspace(0, 0, fade_size)
    window = torch.ones(window_size)
    window[-fade_size:] *= fadeout
    window[:fade_size] *= fadein
    return window


def dBgain(audio, volume_gain_dB):
    gain = 10 ** (volume_gain_dB / 20)
    gained_audio = audio * gain
    return gained_audio


def check_gpu_availability(is_gpu_conversion, device_set):
    """Resolve the inference device using the local CUDA/CPU convention.

    Mirrors ``separate.py``'s device selection: a negative ``is_gpu_conversion``
    forces CPU, otherwise CUDA is used when available. ``device_set`` is the bare
    device number (or ``"Default"``); a specific number yields ``cuda:N``.
    """
    if is_gpu_conversion >= 0 and cuda_available:
        if device_set != DEFAULT:
            return f"{CUDA_DEVICE}:{device_set}"
        return CUDA_DEVICE
    return CPU


def restore_process(input_wav, ckpt_path, overlap=2, chunk_size=10, set_progress_bar=None, is_gpu_conversion=0, device_set=DEFAULT, extracted_params=None, config=None):

    device = check_gpu_availability(is_gpu_conversion, device_set)

    global progress_value
    progress_value = 0

    def process_chunk(chunk):
        chunk = chunk.unsqueeze(0).to(device)
        with torch.no_grad():
            return model(chunk).squeeze(0).squeeze(0).cpu()

    def progress_bar_ui(length):
        global progress_value
        progress_value += 1

        # Avoid division by zero
        if length <= 0:
            length = 1

        iter_val = (0.90 / length * progress_value)
        iter_val = 0.99 if iter_val >= 1.0 else iter_val
        set_progress_bar(0.1, iter_val)

    model = models.BaseModel.from_pretrain(ckpt_path, **extracted_params).to(device)

    audio_data, samplerate = load_audio(input_wav)

    C = chunk_size * samplerate  # chunk_size seconds to samples
    N = overlap

    step = C // N if overlap else C
    step_ui = int(step)

    fade_sec = 3 if chunk_size >= 3 else chunk_size

    fade_size = fade_sec * 44100 # 3 seconds
    border = C - step

    # handle mono inputs correctly
    if len(audio_data.shape) == 1:
        audio_data = audio_data.unsqueeze(0)

    # Pad the input if necessary
    if audio_data.shape[1] > 2 * border and (border > 0):
        audio_data = torch.nn.functional.pad(audio_data, (border, border), mode='reflect')

    windowingArray = _getWindowingArray(C, fade_size)

    result = torch.zeros((1,) + tuple(audio_data.shape), dtype=torch.float32)
    counter = torch.zeros((1,) + tuple(audio_data.shape), dtype=torch.float32)

    i = 0

    batch_len = max(1, int(audio_data.shape[1] / step_ui))  # Ensure batch_len is at least 1

    while i < audio_data.shape[1]:
        part = audio_data[:, i:i + C]
        length = part.shape[-1]
        if length < C:
            if length > C // 2 + 1:
                part = torch.nn.functional.pad(input=part, pad=(0, C - length), mode='reflect')
            else:
                part = torch.nn.functional.pad(input=part, pad=(0, C - length, 0, 0), mode='constant', value=0)

        out = process_chunk(part)

        window = windowingArray
        if i == 0:  # First audio chunk, no fadein
            window[:fade_size] = 1
        elif i + C >= audio_data.shape[1]:  # Last audio chunk, no fadeout
            window[-fade_size:] = 1

        result[..., i:i+length] += out[..., :length] * window[..., :length]
        counter[..., i:i+length] += window[..., :length]

        i += step

        if set_progress_bar:
            progress_bar_ui(batch_len)

    final_output = result / counter
    final_output = final_output.squeeze(0).numpy()
    np.nan_to_num(final_output, copy=False, nan=0.0)

    # Remove padding if added earlier
    if audio_data.shape[1] > 2 * border and (border > 0):
        final_output = final_output[..., border:-border]

    # Memory clearing
    model.cpu()
    del model
    clear_gpu_cache()

    return final_output
