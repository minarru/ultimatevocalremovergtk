"""Unified GPU / ONNX backend resolution for separation and audio tools.

Resolves PyTorch devices and ONNX Runtime execution providers from user settings
and runtime capabilities (CUDA, MPS, DirectML, CPU).
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from typing import Any, List, Sequence, Tuple

from bundled.constants import CPU, CUDA_DEVICE, DEFAULT

from .platform import system_name

__all__ = [
    "InferenceBackend",
    "available_cuda_devices",
    "clear_torch_cache",
    "directml_available",
    "list_gpu_devices",
    "onnx_cpu_fallback_warning",
    "resolve_inference_backend",
]

_CPU_PROVIDERS = ["CPUExecutionProvider"]
_CPU_PROVIDER = "CPUExecutionProvider"

_ONNX_CPU_FALLBACK_PREFIX = (
    "Warning: GPU conversion is on, but ONNX Runtime could not use {provider} "
    "and is running this model on the CPU, which is much slower. "
)
ONNX_PROVIDER_NOT_INSTALLED_HINT = (
    "The installed onnxruntime package has no GPU support; run "
    "`./install_packages.sh --cuda` to install onnxruntime-gpu.\n"
)
ONNX_PROVIDER_LOAD_FAILED_HINT = (
    "onnxruntime-gpu is installed but its GPU libraries failed to load; "
    "start the app from a terminal to see which library ONNX Runtime could not find.\n"
)


@dataclass(frozen=True)
class InferenceBackend:
    """Resolved inference devices for one job."""

    torch_device: Any
    onnx_providers: List[str]
    backend_name: str
    is_other_gpu: bool = False


def _log_backend(backend: InferenceBackend) -> InferenceBackend:
    from .debug_log import debug

    providers = ",".join(backend.onnx_providers)
    debug(
        "model",
        f"backend {backend.backend_name} device={backend.torch_device} providers=[{providers}]",
    )
    return backend


def _nvidia_smi_devices() -> List[Tuple[str, str]]:
    """Return ``[(index, name), ...]`` via ``nvidia-smi`` (torch-free)."""
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=index,name", "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            timeout=2,
        )
    except Exception:
        return []

    if result.returncode != 0:
        return []

    devices: List[Tuple[str, str]] = []
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


def available_cuda_devices() -> List[Tuple[str, str]]:
    """Backward-compatible alias for NVIDIA device enumeration."""
    return _nvidia_smi_devices()


def directml_available() -> bool:
    """Return True when ``torch-directml`` is importable and reports a device."""
    if system_name() != "Windows":
        return False
    try:
        import torch_directml  # noqa: WPS433 - optional Windows extra

        return bool(torch_directml.is_available())
    except Exception:
        return False


def list_gpu_devices() -> List[Tuple[str, str]]:
    """Return GPU choices for settings UI as ``[(id, label), ...]``."""
    devices = list(_nvidia_smi_devices())
    if system_name() == "Darwin":
        try:
            import torch

            if torch.backends.mps.is_available():
                devices.append(("mps", "Apple Metal (MPS)"))
        except Exception:
            pass
    if directml_available():
        devices.append(("directml", "DirectML (AMD/Intel GPU)"))
    return devices


def _cuda_torch_device(device_set: str) -> str:
    if device_set != DEFAULT:
        return f"{CUDA_DEVICE}:{device_set}"
    return CUDA_DEVICE


def _directml_torch_device(device_set: str) -> Any:
    import torch_directml  # noqa: WPS433 - optional Windows extra

    if device_set != DEFAULT and device_set.isdigit():
        return torch_directml.device(int(device_set))
    return torch_directml.device()


def resolve_inference_backend(
    *,
    use_gpu: bool,
    device_set: str = DEFAULT,
    is_use_directml: bool = False,
    is_macos: bool = False,
) -> InferenceBackend:
    """Pick PyTorch device and ONNX providers from settings and runtime state."""
    if not use_gpu:
        return _log_backend(
            InferenceBackend(
                torch_device=CPU,
                onnx_providers=list(_CPU_PROVIDERS),
                backend_name="cpu",
            )
        )

    import torch

    if is_macos and torch.backends.mps.is_available():
        return _log_backend(
            InferenceBackend(
                torch_device="mps",
                onnx_providers=list(_CPU_PROVIDERS),
                backend_name="mps",
                is_other_gpu=True,
            )
        )

    if is_use_directml and directml_available():
        return _log_backend(
            InferenceBackend(
                torch_device=_directml_torch_device(device_set),
                onnx_providers=list(_CPU_PROVIDERS),
                backend_name="directml",
                is_other_gpu=True,
            )
        )

    if torch.cuda.is_available():
        from engines.amp_runtime import configure_cuda_inference

        # onnxruntime-gpu needs no library preload: torch and ORT share the
        # CUDA 13 wheels, and importing torch (above) already loaded them.
        configure_cuda_inference(device_set)
        providers: List[str] = ["CUDAExecutionProvider", "CPUExecutionProvider"]
        return _log_backend(
            InferenceBackend(
                torch_device=_cuda_torch_device(device_set),
                onnx_providers=providers,
                backend_name="cuda",
            )
        )

    return _log_backend(
        InferenceBackend(
            torch_device=CPU,
            onnx_providers=list(_CPU_PROVIDERS),
            backend_name="cpu",
        )
    )


def clear_torch_cache(*, is_macos: bool = False, backend_name: str = "cpu") -> None:
    """Release PyTorch GPU memory after a job."""
    import gc

    import torch

    gc.collect()
    if is_macos and backend_name == "mps":
        if torch.backends.mps.is_available():
            torch.mps.empty_cache()
        return
    if backend_name in {"cuda", "directml"} and torch.cuda.is_available():
        torch.cuda.synchronize()
        torch.cuda.empty_cache()
        ipc_collect = getattr(torch.cuda, "ipc_collect", None)
        if callable(ipc_collect):
            ipc_collect()


def onnx_cpu_fallback_warning(
    requested: Sequence[str],
    active: Sequence[str],
    available: Sequence[str] = (),
) -> str | None:
    """Return a console warning when ONNX Runtime dropped the requested GPU provider.

    ONNX Runtime falls back to the CPU without raising when a GPU provider is
    missing (CPU-only ``onnxruntime`` wheel) or fails to load (CUDA libraries
    not found), so compare what the session reports against what was asked for.
    ``available`` is ``onnxruntime.get_available_providers()`` and tells the two
    causes apart.
    """
    preferred = requested[0] if requested else _CPU_PROVIDER
    if preferred == _CPU_PROVIDER or preferred in active:
        return None
    hint = (
        ONNX_PROVIDER_LOAD_FAILED_HINT
        if preferred in available
        else ONNX_PROVIDER_NOT_INSTALLED_HINT
    )
    return _ONNX_CPU_FALLBACK_PREFIX.format(provider=preferred) + hint


def available_onnx_providers() -> Sequence[str]:
    """Return ONNX Runtime execution providers (empty when ORT is not installed)."""
    try:
        import onnxruntime as ort

        return ort.get_available_providers()
    except Exception:
        return []
