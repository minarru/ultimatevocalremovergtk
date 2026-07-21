"""Optional CUDA autocast and ONNX Runtime feed helpers.

Defaults stay full FP32. Set ``UVR_AUTOCAST=1`` to enable CUDA autocast around
model forwards only (OLA / post-processing remain float32). Demucs inference
intentionally ignores this flag — hybrid Demucs nets emit NaNs under fp16
autocast.
"""

from __future__ import annotations

import os
from contextlib import contextmanager, nullcontext
from typing import Any, Callable, Iterator

import numpy as np
import torch


def env_flag(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def autocast_enabled() -> bool:
    return env_flag("UVR_AUTOCAST")


@contextmanager
def maybe_autocast(device: Any) -> Iterator[None]:
    """Yield under ``torch.autocast`` only when opted in and running on CUDA."""
    if not autocast_enabled():
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


def build_ort_runner(session: Any, torch_device: Any) -> Callable[[torch.Tensor], torch.Tensor]:
    """Return ``spek_tensor -> spek_pred_tensor`` for an ORT session.

    Uses CUDA IOBinding when the session's primary provider is CUDA so the
    spectrogram does not round-trip through host numpy. Falls back to a
    contiguous numpy feed otherwise (CPU / DirectML / etc.).
    """
    input_name = session.get_inputs()[0].name
    output_name = session.get_outputs()[0].name
    providers = list(session.get_providers() or ())
    primary = providers[0] if providers else "CPUExecutionProvider"
    device_obj = torch.device(torch_device) if not isinstance(torch_device, torch.device) else torch_device
    use_cuda_iobind = primary == "CUDAExecutionProvider" and device_obj.type == "cuda"

    if use_cuda_iobind:

        def run_cuda(spek: torch.Tensor) -> torch.Tensor:
            spek = spek.contiguous().to(dtype=torch.float32)
            if spek.device != device_obj:
                spek = spek.to(device_obj, non_blocking=False)
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


def forward_with_autocast(device: Any, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    """Call ``fn`` under optional CUDA autocast."""
    with maybe_autocast(device):
        return fn(*args, **kwargs)


# Silence unused-import lint for nullcontext re-export convenience in callers.
_ = nullcontext
