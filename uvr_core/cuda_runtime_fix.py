"""Let onnxruntime-gpu (a CUDA 12 build) find its runtime libs in a torch-cu13 venv.

``onnxruntime-gpu`` 1.26 is built against CUDA 12 and ``dlopen()``s sonames such as
``libcublasLt.so.12`` / ``libcublas.so.12`` / ``libcudart.so.12`` / ``libcufft.so.11``
/ ``libcurand.so.10``. ``torch`` 2.12 in this venv ships CUDA 13 (``libcublas.so.13``
etc.), so those CUDA-12 sonames are otherwise absent and the CUDAExecutionProvider
silently falls back to CPU with ``libcublasLt.so.12: cannot open shared object file``.

We install the matching ``nvidia-*-cu12`` PyPI wheels (see requirements.txt) and
ctypes-preload them with ``RTLD_GLOBAL`` *before* any onnxruntime InferenceSession is
created. The dynamic loader then satisfies onnxruntime's later dlopen-by-soname from
the already-loaded objects. The cu12 sonames differ from torch's cu13 sonames, so the
two CUDA runtimes coexist in one process and torch's GPU path is untouched.

cuDNN is the exception: both builds use soname ``libcudnn.so.9`` and the same
``nvidia/cudnn/lib`` directory, so only one can be resident per process. We keep
torch's cu13 cuDNN (``nvidia-cudnn-cu13``) and let it serve onnxruntime too; the
cuDNN 9 API is stable across the CUDA 12/13 builds.

This is best-effort: every step is guarded, so a missing/older runtime simply leaves
onnxruntime on CPU rather than breaking imports or torch.
"""

from __future__ import annotations

import ctypes
import os
import sysconfig

_PRELOADED = False

# (package subdir under site-packages/nvidia, soname) in load order. cuDNN is last
# because its own NEEDED libs (cu13 cublas/cudart) are normally already resident via
# torch; if torch has not been imported yet this entry just no-ops on OSError.
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
    """Preload the CUDA-12 runtime libs onnxruntime-gpu needs. Returns loaded paths."""
    global _PRELOADED
    loaded: list[str] = []
    if _PRELOADED:
        return loaded
    _PRELOADED = True

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
            # Leave onnxruntime to fall back to CPU rather than crash the app.
            pass
    return loaded
