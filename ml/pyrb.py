from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile

import numpy as np
import six
import soundfile as sf
from typing import Any

__all__ = ['time_stretch', 'pitch_shift']

if six.PY2:
    DEVNULL = open(os.devnull, 'w')
else:
    DEVNULL = subprocess.DEVNULL


def _resolve_rubberband() -> str | None:
    """Locate rubberband without importing ``core`` (see ``core.external_tools``)."""
    env = os.environ.get("UVR_RUBBERBAND", "").strip()
    if env and os.path.isfile(env):
        return env
    here = os.path.dirname(os.path.abspath(__file__))
    for candidate in (os.path.join(here, "rubberband"), shutil.which("rubberband")):
        if candidate and os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    return shutil.which("rubberband")


def __rubberband(y: np.ndarray, sr: int, **kwargs: Any) -> np.ndarray:

    assert sr > 0

    rubberband = _resolve_rubberband()
    if not rubberband:
        raise RuntimeError(
            'Failed to execute rubberband. Please verify that rubberband-cli '
            'is installed or set UVR_RUBBERBAND to the executable path.'
        )

    fd, infile = tempfile.mkstemp(suffix='.wav')
    os.close(fd)
    fd, outfile = tempfile.mkstemp(suffix='.wav')
    os.close(fd)

    sf.write(infile, y, sr)

    try:
        arguments = [rubberband, '-q']

        for key, value in six.iteritems(kwargs):
            arguments.append(str(key))
            arguments.append(str(value))

        arguments.extend([infile, outfile])

        subprocess.check_call(arguments, stdout=DEVNULL, stderr=DEVNULL)

        y_out, _ = sf.read(outfile, always_2d=True)

        if y.ndim == 1:
            y_out = np.squeeze(y_out)

    except OSError as exc:
        six.raise_from(RuntimeError('Failed to execute rubberband. '
                                    'Please verify that rubberband-cli '
                                    'is installed.'),
                       exc)

    finally:
        os.unlink(infile)
        os.unlink(outfile)

    return y_out

def time_stretch(
    y: np.ndarray, sr: int, rate: float, rbargs: dict[str, Any] | None = None
) -> np.ndarray:
    if rate <= 0:
        raise ValueError('rate must be strictly positive')

    if rate == 1.0:
        return y

    if rbargs is None:
        rbargs = dict()

    rbargs.setdefault('--tempo', rate)

    return __rubberband(y, sr, **rbargs)

def pitch_shift(
    y: np.ndarray, sr: int, n_steps: float, rbargs: dict[str, Any] | None = None
) -> np.ndarray:
    if n_steps == 0:
        return y

    if rbargs is None:
        rbargs = dict()

    rbargs.setdefault('--pitch', n_steps)

    return __rubberband(y, sr, **rbargs)
