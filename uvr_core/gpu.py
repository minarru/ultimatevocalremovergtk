"""Cheap, dependency-free CUDA GPU detection for the settings UI.

The GTK settings dialog needs to know which CUDA device indices actually exist
so it can offer a realistic "GPU device" dropdown instead of a fixed ``0..8``
list. Detection has to satisfy two hard constraints:

* **No heavy imports.** The UI is intentionally ``torch``-free at startup, and
  ``torch`` may not even be installed yet (deferred-install scenarios). So we
  query ``nvidia-smi`` over a subprocess rather than importing any ML library.
* **Never raise or hang.** Any failure (no ``nvidia-smi`` binary, non-zero
  exit, timeout, unexpected output) is swallowed and reported as "no devices",
  letting callers fall back to the static option list so behaviour can only
  improve, never regress.
"""

import subprocess

__all__ = ["available_cuda_devices"]


def available_cuda_devices():
    """Return detected CUDA devices as ``[(index_str, name), ...]``.

    Uses ``nvidia-smi`` (stdlib subprocess only, no ``torch``). Returns an empty
    list on any failure, so callers can fall back to a static option list.
    """
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=index,name", "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            timeout=2,
        )
    except Exception:
        # FileNotFoundError (no nvidia-smi), TimeoutExpired, OSError, etc.
        return []

    if result.returncode != 0:
        return []

    devices = []
    try:
        for line in result.stdout.splitlines():
            line = line.strip()
            if not line:
                continue
            index, _, name = line.partition(",")
            index = index.strip()
            name = name.strip()
            if index:
                devices.append((index, name))
    except Exception:
        return []

    return devices
