"""Cheap, dependency-free GPU detection for the settings UI.

Re-exports :func:`available_cuda_devices` from :mod:`core.gpu_backend`.
Prefer :func:`core.gpu_backend.list_gpu_devices` for the unified settings UI.
"""

from .gpu_backend import available_cuda_devices, list_gpu_devices

__all__ = ["available_cuda_devices", "list_gpu_devices"]
