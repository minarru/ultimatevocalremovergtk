"""Let onnxruntime-gpu (a CUDA 12 build) find its runtime libs in a torch-cu13 venv.

Linux-only ctypes preload; other platforms no-op via :func:`preload_onnxruntime_gpu`.
See module docstring in the original ``preload_onnxruntime_cuda12`` implementation.
"""

from __future__ import annotations

import ctypes
import os
import sys
import sysconfig

_PRELOADED = False

_CUDA12_LIBS = (
    ("cuda_runtime", "libcudart.so.12"),
    ("cublas", "libcublasLt.so.12"),
    ("cublas", "libcublas.so.12"),
    ("cufft", "libcufft.so.11"),
    ("curand", "libcurand.so.10"),
    ("cuda_nvrtc", "libnvrtc.so.12"),
    ("cudnn", "libcudnn.so.9"),
)


def preload_onnxruntime_cuda12() -> list[str]:
    """Preload Linux CUDA-12 sonames for onnxruntime-gpu. Returns loaded paths."""
    global _PRELOADED
    loaded: list[str] = []
    if _PRELOADED:
        return loaded
    _PRELOADED = True

    if sys.platform != "linux":
        return loaded

    nvidia_dir = os.path.join(sysconfig.get_paths()["purelib"], "nvidia")
    if not os.path.isdir(nvidia_dir):
        return loaded

    for subdir, soname in _CUDA12_LIBS:
        lib_path = os.path.join(nvidia_dir, subdir, "lib", soname)
        if not os.path.exists(lib_path):
            continue
        try:
            ctypes.CDLL(lib_path, mode=ctypes.RTLD_GLOBAL)
            loaded.append(lib_path)
        except OSError:
            pass

    if loaded:
        from .debug_log import debug

        debug("model", f"onnxruntime cuda preload libs={len(loaded)}")
    return loaded


def preload_onnxruntime_gpu() -> list[str]:
    """Platform dispatch for ONNX GPU runtime preload (best-effort)."""
    if sys.platform == "linux":
        return preload_onnxruntime_cuda12()
    return []
