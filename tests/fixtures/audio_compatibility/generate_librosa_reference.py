"""Run from the repository root with PYTHONPATH=. and librosa==0.11.0."""

import json
from importlib.metadata import version
from pathlib import Path

import numpy as np

from tests.test_librosa_compatibility import _measurements

if version('librosa') != '0.11.0':
    raise SystemExit('Reference generation requires librosa==0.11.0')

output = Path(__file__).parent
np.savez_compressed(output / 'librosa_0_11.npz', allow_pickle=False, **_measurements())
(output / 'versions.json').write_text(
    json.dumps(
        {
            name: version(name)
            for name in ('librosa', 'numpy', 'scipy', 'soxr', 'resampy', 'samplerate')
        },
        indent=2,
    )
    + '\n'
)
