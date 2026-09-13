"""Strict, bounded-memory waveform SDR and stereo SI-SDR."""

from __future__ import annotations

import math
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from .common import audio_info, energy_ratio, file_signature, metric, require_same_audio, sha256

BASIC_PROTOCOL = {
    'version': 1,
    'waveform_sdr': '10log10(sum(reference^2)/sum((estimate-reference)^2)); whole track; no centering',
    'si_sdr': 'per-channel mean removal; shared stereo projection; whole track',
    'precision': 'float64',
    'alignment': 'strict; no resampling, shift, padding, or truncation',
    'silent_target_window_seconds': 1,
    'silent_target_threshold_dbfs': -80,
    'silent_target_tail': 'include partial final window',
}


def paired_blocks(reference: Path, estimate: Path, frames: int) -> Iterator[tuple[Any, Any]]:
    import numpy as np
    import soundfile as sf

    try:
        with sf.SoundFile(str(reference)) as ref, sf.SoundFile(str(estimate)) as est:
            while True:
                x = ref.read(frames, dtype='float64', always_2d=True)
                y = est.read(frames, dtype='float64', always_2d=True)
                if x.shape != y.shape:
                    raise ValueError('Audio changed length while scoring')
                if not x.size:
                    break
                if not np.isfinite(x).all() or not np.isfinite(y).all():
                    raise ValueError('Audio contains non-finite samples')
                yield x, y
    except (OSError, RuntimeError) as exc:
        raise ValueError(f'Cannot decode audio: {exc}') from exc


def score_pair(reference: Path, estimate: Path) -> dict[str, Any]:
    import numpy as np

    signatures = (file_signature(reference), file_signature(estimate))
    ref_info = audio_info(reference)
    require_same_audio(ref_info, audio_info(estimate))
    rate = ref_info['sample_rate']
    frames = ref_info['frames']
    channels = ref_info['channels']
    ref_energy = error_energy = silent_energy = 0.0
    silent_samples = silent_windows = seen = 0
    silent_details = []
    xsum, ysum = np.zeros(channels), np.zeros(channels)
    for x, y in paired_blocks(reference, estimate, rate):
        seen += len(x)
        xsum += x.sum(axis=0)
        ysum += y.sum(axis=0)
        energy = float(np.sum(x * x))
        ref_energy += energy
        error_energy += float(np.sum((y - x) ** 2))
        if energy / x.size < 1e-8:
            silent_windows += 1
            silent_samples += x.size
            window_energy = float(np.sum(y * y))
            silent_energy += window_energy
            window_rms = math.sqrt(window_energy / y.size)
            silent_details.append(
                {
                    'start_seconds': (seen - len(x)) / rate,
                    'duration_seconds': len(x) / rate,
                    'output_rms_dbfs': metric(
                        20 * math.log10(window_rms) if window_rms else float('-inf')
                    ),
                }
            )
    if seen != frames:
        raise ValueError('Decoded frame count differs from the audio header')
    xmean, ymean = xsum / frames, ysum / frames
    xx = xy = 0.0
    for x, y in paired_blocks(reference, estimate, rate):
        xc, yc = x - xmean, y - ymean
        xx += float(np.sum(xc * xc))
        xy += float(np.sum(xc * yc))
    if xx == 0:
        si = metric(status='silent_reference' if ref_energy == 0 else 'constant_reference')
    else:
        alpha = xy / xx
        target_energy = residual_energy = 0.0
        # A direct residual pass avoids catastrophic subtraction for near-perfect estimates.
        for x, y in paired_blocks(reference, estimate, rate):
            target = alpha * (x - xmean)
            residual = (y - ymean) - target
            target_energy += float(np.sum(target * target))
            residual_energy += float(np.sum(residual * residual))
        si = energy_ratio(target_energy, residual_energy)
    if silent_samples:
        rms = math.sqrt(silent_energy / silent_samples)
        silent_rms = metric(20 * math.log10(rms) if rms else float('-inf'))
    else:
        silent_rms = metric(status='no_silent_windows')
    reference_hash, estimate_hash = sha256(reference), sha256(estimate)
    if signatures != (file_signature(reference), file_signature(estimate)):
        raise ValueError('Audio changed during scoring')
    return {
        'waveform_sdr': energy_ratio(ref_energy, error_energy)
        if ref_energy
        else metric(status='silent_reference'),
        'si_sdr': si,
        'silent_target': {
            'windows': silent_windows,
            'window_results': silent_details,
            'samples': silent_samples,
            'output_rms_dbfs': silent_rms,
        },
        'audio': ref_info,
        'reference_sha256': reference_hash,
        'estimate_sha256': estimate_hash,
    }
