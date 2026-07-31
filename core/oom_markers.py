"""GPU out-of-memory message matching, free of torch / ORT imports.

Lives in ``core`` so tools that must not import the engine stack (and with it
torch) can classify an OOM failure. ``engines.mdx_classic_batch`` re-exports it
for the batch-size backoff.
"""

from __future__ import annotations

_OOM_MARKERS = (
    "out of memory",
    "cuda_error_out_of_memory",
    "cudamalloc failed",
    "failed to allocate memory",
)


def is_oom_message(text: str | None) -> bool:
    """Whether an exception message indicates a GPU memory allocation failure.

    ``onnxruntime`` reports CUDA OOM through its own ``Fail``/``RuntimeException``
    types rather than ``torch.cuda.OutOfMemoryError``, so callers that also run
    ORT sessions need a message-based check to trigger the batch-size backoff
    without swallowing unrelated ORT errors.
    """
    lowered = (text or "").lower()
    return any(marker in lowered for marker in _OOM_MARKERS)
