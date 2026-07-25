"""Pure helpers for classic MDX hop-index batching.

Kept free of torch / ORT imports so unit tests can cover grouping without
loading the full separation stack.
"""

from __future__ import annotations

from typing import List, Optional, Tuple


def mdx_hop_starts(mix_len: int, step: int) -> List[int]:
    """Return hop start indices for a padded mixture of length ``mix_len``."""
    if mix_len <= 0 or step <= 0:
        return []
    return list(range(0, mix_len, step))


def mdx_batch_ranges(n_chunks: int, batch_size: int) -> List[Tuple[int, int]]:
    """Return half-open ``(start_idx, end_idx)`` ranges over hop indices."""
    if n_chunks <= 0:
        return []
    batch = max(1, int(batch_size))
    return [(start, min(start + batch, n_chunks)) for start in range(0, n_chunks, batch)]


def resolve_mdx_effective_batch(requested: int, fixed_batch: Optional[int] = None) -> int:
    """Clamp the UI batch size against an ORT-declared fixed leading dim.

    When the ONNX input batch dim is fixed to ``1``, real stacking is impossible
    so the effective batch stays ``1``. Dynamic / unknown dims leave the
    requested size unchanged (clamped to ≥ 1).
    """
    batch = max(1, int(requested or 1))
    if fixed_batch is None:
        return batch
    try:
        fixed = int(fixed_batch)
    except (TypeError, ValueError):
        return batch
    if fixed <= 0:
        return batch
    if fixed == 1:
        return 1
    return max(1, min(batch, fixed))


def next_batch_after_oom(current: int) -> Optional[int]:
    """Halve the batch after CUDA OOM, or return ``None`` when already at 1."""
    batch = max(1, int(current or 1))
    if batch <= 1:
        return None
    return max(1, batch // 2)


_OOM_MARKERS = (
    "out of memory",
    "cuda_error_out_of_memory",
    "cudamalloc failed",
    "failed to allocate memory",
)


def is_oom_message(text: str) -> bool:
    """Whether an exception message indicates a GPU memory allocation failure.

    ``onnxruntime`` reports CUDA OOM through its own ``Fail``/``RuntimeException``
    types rather than ``torch.cuda.OutOfMemoryError``, so callers that also run
    ORT sessions need a message-based check to trigger the batch-size backoff
    without swallowing unrelated ORT errors.
    """
    lowered = (text or "").lower()
    return any(marker in lowered for marker in _OOM_MARKERS)
