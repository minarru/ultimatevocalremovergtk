"""Optional CUDA autocast and ONNX Runtime feed helpers.

GUI/settings key ``is_autocast`` enables CUDA ``torch.autocast`` (fp16) around
model forwards only (OLA / post-processing remain float32). Demucs inference
intentionally ignores this flag — hybrid Demucs nets emit NaNs under fp16
autocast.

``UVR_AUTOCAST`` in the environment overrides the settings value when present
(used by headless ``bench-ab``).
"""

from __future__ import annotations

import os
from contextlib import contextmanager, nullcontext
from typing import Any, Callable, Iterator, Optional

import numpy as np
import torch

from bundled.constants import DEFAULT


def env_flag(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _cuda_device_index(device_set: Any) -> int:
    """Resolve a settings ``device_set`` value to a CUDA device index."""
    if device_set is None or device_set == DEFAULT:
        return 0
    text = str(device_set).split(":")[-1].strip()
    if not text or text == DEFAULT:
        return 0
    try:
        return int(text)
    except ValueError:
        return 0


def recommend_autocast(device_set: Any = DEFAULT) -> bool:
    """Return True when FP16 autocast is a safe default for ``device_set``.

    Enables only for CUDA devices with compute capability major >= 8 (Ampere+).
    DirectML / MPS / CPU and older NVIDIA GPUs stay False.
    """
    try:
        if not torch.cuda.is_available():
            return False
        index = _cuda_device_index(device_set)
        if index < 0 or index >= torch.cuda.device_count():
            return False
        major, _minor = torch.cuda.get_device_capability(index)
        return int(major) >= 8
    except Exception:  # noqa: BLE001 - recommendation must never break settings load
        return False


_cuda_inference_configured = False


def configure_cuda_inference(device_set: Any = DEFAULT) -> None:
    """Enable cudnn.benchmark and TF32 (Ampere+) once per process for CUDA jobs."""
    global _cuda_inference_configured
    if _cuda_inference_configured:
        return
    try:
        if not torch.cuda.is_available():
            return
        torch.backends.cudnn.benchmark = True
        index = _cuda_device_index(device_set)
        if 0 <= index < torch.cuda.device_count():
            major, _minor = torch.cuda.get_device_capability(index)
            if int(major) >= 8:
                torch.backends.cuda.matmul.allow_tf32 = True
                torch.backends.cudnn.allow_tf32 = True
        _cuda_inference_configured = True
    except Exception:  # noqa: BLE001 - never block backend resolution
        return


def make_ort_session_options() -> Any:
    """ORT session options for classic MDX ONNX loads (full graph opts + mem pattern)."""
    import onnxruntime as ort

    options = ort.SessionOptions()
    options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
    options.enable_mem_pattern = True
    return options


def autocast_enabled(settings: Any = None) -> bool:
    """Whether CUDA autocast should run for this process/job.

    If ``UVR_AUTOCAST`` is set in the environment, that value wins. Otherwise
    the ``is_autocast`` settings key is used when ``settings`` is provided.
    """
    if "UVR_AUTOCAST" in os.environ:
        return env_flag("UVR_AUTOCAST")
    if settings is not None:
        return bool(settings.get("is_autocast"))
    return False


@contextmanager
def maybe_autocast(device: Any, settings: Any = None) -> Iterator[None]:
    """Yield under ``torch.autocast`` only when opted in and running on CUDA."""
    if not autocast_enabled(settings):
        yield
        return
    device_obj = torch.device(device) if not isinstance(device, torch.device) else device
    if device_obj.type != "cuda" or not torch.cuda.is_available():
        yield
        return
    with torch.autocast(device_type="cuda", dtype=torch.float16):
        yield


def torch_device_index(device: Any) -> int:
    device_obj = torch.device(device) if not isinstance(device, torch.device) else device
    return int(device_obj.index or 0)


def ort_fixed_batch_size(session: Any) -> Optional[int]:
    """Return a fixed leading batch size from an ORT session input, if any.

    Classic MDX ONNX models often declare ``shape[0] == 1``. Dynamic dims
    (``None`` or symbolic names like ``"batch"``) return ``None`` so callers
    may stack freely.
    """
    try:
        shape = session.get_inputs()[0].shape
    except Exception:  # noqa: BLE001 - probe must never break demix
        return None
    if not shape:
        return None
    dim0 = shape[0]
    if dim0 is None or isinstance(dim0, str):
        return None
    try:
        value = int(dim0)
    except (TypeError, ValueError):
        return None
    if value <= 0:
        return None
    return value


def build_ort_runner(session: Any, torch_device: Any) -> Callable[[torch.Tensor], torch.Tensor]:
    """Return ``spek_tensor -> spek_pred_tensor`` for an ORT session.

    Uses CUDA IOBinding when the session's primary provider is CUDA so the
    spectrogram does not round-trip through host numpy. Falls back to a
    contiguous numpy feed otherwise (CPU / DirectML / etc.).
    """
    input_name = session.get_inputs()[0].name
    output_name = session.get_outputs()[0].name
    providers: list[str] = list(session.get_providers() or ())
    primary = providers[0] if providers else "CPUExecutionProvider"
    device_obj = torch.device(torch_device) if not isinstance(torch_device, torch.device) else torch_device
    use_cuda_iobind = primary == "CUDAExecutionProvider" and device_obj.type == "cuda"

    if use_cuda_iobind:

        def run_cuda(spek: torch.Tensor) -> torch.Tensor:
            # Hot path: STFT already produced contiguous float32 on the ORT device.
            # Skip host sync and rely on same-stream ordering. Sync only when we
            # materialize a new buffer ORT will read (H2D / dtype / contiguous).
            #
            # This relies on onnxruntime's CUDAExecutionProvider defaulting to
            # the current thread's active CUDA stream (no ``user_compute_stream``
            # provider option is set here) — not a documented cross-version ORT
            # guarantee. If a future onnxruntime release schedules CUDA EP work
            # on its own stream, ``run_with_iobinding`` could read this tensor
            # before PyTorch finishes writing it. Covered by
            # test_amp_runtime.py::test_ort_cuda_skips_sync_when_already_on_device;
            # if that assumption ever needs relaxing, re-add the synchronize()
            # here rather than silently trusting stream order.
            already_ready = (
                spek.device == device_obj
                and spek.dtype == torch.float32
                and spek.is_contiguous()
            )
            if not already_ready:
                if spek.device != device_obj:
                    spek = spek.to(device=device_obj, dtype=torch.float32, non_blocking=True)
                elif spek.dtype != torch.float32:
                    spek = spek.to(dtype=torch.float32)
                if not spek.is_contiguous():
                    spek = spek.contiguous()
                # ORT reads the binding pointer during run; keep spek alive.
                torch.cuda.synchronize(spek.device)
            binding = session.io_binding()
            binding.bind_input(
                input_name,
                "cuda",
                torch_device_index(spek.device),
                np.float32,
                tuple(spek.shape),
                spek.data_ptr(),
            )
            binding.bind_output(output_name, "cuda", torch_device_index(spek.device))
            session.run_with_iobinding(binding)
            ort_out = binding.get_outputs()[0]
            try:
                from torch.utils.dlpack import from_dlpack

                out = from_dlpack(ort_out.to_dlpack())
                if out.device != device_obj:
                    out = out.to(device_obj)
                return out.to(dtype=torch.float32)
            except Exception:  # noqa: BLE001 - fall back to host copy
                return torch.as_tensor(
                    np.ascontiguousarray(ort_out.numpy()),
                    device=device_obj,
                    dtype=torch.float32,
                )

        return run_cuda

    def run_numpy(spek: torch.Tensor) -> torch.Tensor:
        host = spek.detach()
        if host.device.type != "cpu":
            host = host.to(dtype=torch.float32, device="cpu")
        else:
            host = host.to(dtype=torch.float32)
        arr = np.ascontiguousarray(host.numpy())
        out = session.run(None, {input_name: arr})[0]
        return torch.as_tensor(
            np.ascontiguousarray(out),
            device=device_obj,
            dtype=torch.float32,
        )

    return run_numpy


def forward_with_autocast(
    device: Any,
    fn: Callable[..., Any],
    *args: Any,
    settings: Any = None,
    **kwargs: Any,
) -> Any:
    """Call ``fn`` under optional CUDA autocast."""
    with maybe_autocast(device, settings):
        return fn(*args, **kwargs)


# Silence unused-import lint for nullcontext re-export convenience in callers.
_ = nullcontext
