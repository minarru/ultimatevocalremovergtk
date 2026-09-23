"""Optional pinned BSS Eval v4 backend; no implicit audio preparation."""

from __future__ import annotations

import importlib
from collections import Counter
from importlib.metadata import version
from pathlib import Path
from typing import Any

from .common import GROUPS, audio_info, metric, require_same_audio

NAMES = ('bss_sdr', 'bss_isr', 'bss_sir', 'bss_sar')


def require_backend() -> Any:
    try:
        backend = importlib.import_module('museval.metrics')
        installed = version('museval')
    except ImportError as exc:
        raise ValueError(
            'BSS Eval requires optional dependencies: .venv/bin/python -m pip install -r requirements-score.txt; or use --metrics basic'
        ) from exc
    if installed != '0.4.1':
        raise ValueError(
            f'BSS Eval requires museval 0.4.1, found {installed}; install requirements-score.txt'
        )
    return backend


def protocol() -> dict[str, Any]:
    require_backend()
    return {
        'backend': 'museval',
        'backend_version': version('museval'),
        'version': 4,
        'images': True,
        'filters_len': 512,
        'framewise_filters': False,
        'window_seconds': 1,
        'hop_seconds': 1,
        'compute_permutation': False,
        'padding': False,
        'cpu_threads': 1,
        'song_aggregation': 'median of finite windows',
        'numpy_version': version('numpy'),
        'scipy_version': version('scipy'),
    }


def score_bss(
    references: dict[str, Path], estimates: dict[str, Path], group: str
) -> dict[str, Any]:
    import numpy as np
    import soundfile as sf

    stems = GROUPS.get(group)
    if stems is None:
        return {'status': 'unsupported_group', 'stems': {}}
    if set(references) != set(stems) or set(estimates) != set(stems):
        return {'status': 'incomplete_group', 'stems': {}}
    info = audio_info(references[stems[0]])
    ref, est = [], []
    for stem in stems:
        for path, arrays in ((references[stem], ref), (estimates[stem], est)):
            require_same_audio(info, audio_info(path))
            samples, _ = sf.read(str(path), dtype='float64', always_2d=True)
            if not np.isfinite(samples).all():
                raise ValueError('BSS Eval audio contains non-finite samples')
            arrays.append(samples)
    if any(not np.any(x) for x in ref):
        return {'status': 'silent_reference', 'stems': {}}
    if any(not np.any(x) for x in est):
        return {'status': 'silent_estimate', 'stems': {}}
    backend = require_backend()
    try:
        threadpool_limits = importlib.import_module('threadpoolctl').threadpool_limits
        with threadpool_limits(limits=1):
            scores = backend.bss_eval(
                np.stack(ref),
                np.stack(est),
                window=info['sample_rate'],
                hop=info['sample_rate'],
                filters_len=512,
                compute_permutation=False,
                framewise_filters=False,
                bsseval_sources_version=False,
            )
    except (ValueError, np.linalg.LinAlgError) as exc:
        return {'status': 'backend_unavailable', 'reason': str(exc), 'stems': {}}
    result = {}
    for i, stem in enumerate(stems):
        result[stem] = {}
        for j, name in enumerate(NAMES):
            windows = [metric(float(x)) for x in scores[j][i]]
            finite = [x['value'] for x in windows if x['status'] == 'finite']
            summary = (
                metric(float(np.median(finite))) if finite else metric(status='no_finite_windows')
            )
            result[stem][name] = {
                **summary,
                'windows': windows,
                'finite_windows': len(finite),
                'nonfinite_windows': len(windows) - len(finite),
                'window_status_counts': dict(Counter(w['status'] for w in windows)),
            }
    return {'status': 'success', 'stems': result}
