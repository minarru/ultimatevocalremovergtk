"""VR denoiser and multi-band mix loading."""
import typing
import os

import numpy as np
import torch
import librosa

from bundled.constants import OPERATING_SYSTEM, SYSTEM_PROC, ARM, SYSTEM_ARCH
from core.paths import VR_PARAM_DIR
from core.torch_checkpoint import load_torch_checkpoint
from ml import spec_utils
from ml.vr_network import nets_new
from ml.vr_network.model_param_init import ModelParameters

cpu = torch.device('cpu')


def scale_mag_pad_inplace(mag_pad: np.ndarray) -> np.ndarray:
    """Divide a magnitude pad by its peak; no-op for silent / all-zero input."""
    peak = float(np.max(mag_pad)) if mag_pad.size else 0.0
    if peak > 0:
        mag_pad /= peak
    return mag_pad


def _band_res_type(bp: typing.Any):
    if OPERATING_SYSTEM == 'Darwin':
        return 'polyphase' if SYSTEM_PROC == ARM or ARM in SYSTEM_ARCH else bp['res_type']
    return bp['res_type']


def multiband_waves_to_spectrogram(
    X_wave: typing.Any,
    mp: typing.Any,
    *,
    is_v51_model: typing.Any=False,
    use_model_res_type: typing.Any=True,
):
    """Convert a multiband wave dict into a combined VR spectrogram."""
    X_spec_s = {}
    bands_n = len(mp.param['band'])
    for d in range(bands_n, 0, -1):
        bp = mp.param['band'][d]
        wav_resolution = _band_res_type(bp) if use_model_res_type else 'polyphase'
        if d != bands_n:
            X_wave[d] = librosa.resample(
                X_wave[d + 1],
                orig_sr=mp.param['band'][d + 1]['sr'],
                target_sr=bp['sr'],
                res_type=wav_resolution,
            )
        X_spec_s[d] = spec_utils.wave_to_spectrogram(
            X_wave[d],
            bp['hl'],
            bp['n_fft'],
            mp,
            band=d,
            is_v51_model=is_v51_model,
        )
    X_spec = spec_utils.combine_spectrograms(X_spec_s, mp, is_v51_model=is_v51_model)
    return X_spec, X_spec_s, X_wave


def vr_denoiser(
    X: typing.Any,
    device: typing.Any,
    hop_length: typing.Any=1024,
    n_fft: typing.Any=2048,
    cropsize: typing.Any=256,
    is_deverber: typing.Any=False,
    model_path: typing.Any=None,
    settings: typing.Any=None,
):
    batchsize = 4

    if is_deverber:
        nout, nout_lstm = 64, 128
        mp = ModelParameters(os.path.join(VR_PARAM_DIR, '4band_v3.json'))
        n_fft = mp.param['bins'] * 2
    else:
        mp = None
        hop_length=1024
        nout, nout_lstm = 16, 128

    from engines.model_weight_cache import (
        get_weight_cache,
        materialize_module,
        weight_cache_key,
    )

    key = weight_cache_key(
        "vr_deverber" if is_deverber else "vr_denoise",
        str(model_path),
        device,
        n_fft,
        nout,
        nout_lstm,
    )
    cache = get_weight_cache()
    cached = cache.get(key)
    if cached and cached.module is not None:
        model = materialize_module(cached.module, device)
    else:
        model = nets_new.CascadedNet(n_fft, nout=nout, nout_lstm=nout_lstm)
        model.load_state_dict(load_torch_checkpoint(model_path, map_location=cpu))
        model.to(device)
        cache.put(key, module=model)
        model = materialize_module(model, device)

    if mp is None:
        X_spec = spec_utils.wave_to_spectrogram_old(X, hop_length, n_fft)
    else:
        X_spec = loading_mix(X.T, mp)
   
    #PreProcess
    X_mag = np.abs(X_spec)
    X_phase = np.angle(X_spec)

    #Sep
    n_frame = X_mag.shape[2]
    pad_l, pad_r, roi_size = spec_utils.make_padding(n_frame, cropsize, model.offset)
    X_mag_pad = np.pad(X_mag, ((0, 0), (0, 0), (pad_l, pad_r)), mode='constant')
    scale_mag_pad_inplace(X_mag_pad)

    patches = (X_mag_pad.shape[2] - 2 * model.offset) // roi_size

    model.eval()

    with torch.inference_mode():
        mask_parts = []
        # Stream patches per batch instead of materializing all windows.
        for i in range(0, patches, batchsize):
            end = min(i + batchsize, patches)
            X_batch = np.stack(
                [
                    X_mag_pad[:, :, j * roi_size : j * roi_size + cropsize]
                    for j in range(i, end)
                ],
                axis=0,
            )
            X_batch = torch.from_numpy(X_batch).to(device)

            from engines.amp_runtime import maybe_autocast

            with maybe_autocast(device, settings):
                pred = model.predict_mask(X_batch)
            if torch.is_tensor(pred) and pred.dtype != torch.float32:
                pred = pred.float()
            mask_parts.append(torch.cat([pred[b] for b in range(pred.shape[0])], dim=2))

        mask = torch.cat(mask_parts, dim=2).detach().cpu().numpy()

    mask = mask[:, :, :n_frame]

    #Post Proc
    if is_deverber:
        v_spec = mask * X_mag * np.exp(1.j * X_phase)
        y_spec = (1 - mask) * X_mag * np.exp(1.j * X_phase)
    else:
        v_spec = (1 - mask) * X_mag * np.exp(1.j * X_phase)

    if mp is None:
        wave = spec_utils.spectrogram_to_wave_old(v_spec, hop_length=1024)
    else:
        wave = spec_utils.cmb_spectrogram_to_wave(v_spec, mp, is_v51_model=True).T

    wave = spec_utils.match_array_shapes(wave, X)

    if is_deverber:
        wave_2 = spec_utils.cmb_spectrogram_to_wave(y_spec, mp, is_v51_model=True).T
        wave_2 = spec_utils.match_array_shapes(wave_2, X)
        return wave, wave_2
    else:
        return wave

def loading_mix(X: typing.Any, mp: typing.Any):

    bands_n = len(mp.param['band'])
    X_wave = {bands_n: X}
    X_spec, _, _ = multiband_waves_to_spectrogram(
        X_wave,
        mp,
        is_v51_model=True,
        use_model_res_type=True,
    )
    return X_spec
