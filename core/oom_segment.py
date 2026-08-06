"""Segment-size backoff helpers for CUDA OOM recovery (torch-free)."""

from __future__ import annotations

from typing import Any, Optional

from bundled.constants import MDX_SEGMENTS

_DEFAULT_DIM_T = 256
_MIN_SEGMENT = 32


def snap_segment_down(value: int) -> int:
    """Snap ``value`` down to the nearest MDX slider stop (step 32), min 32."""
    try:
        size = int(value)
    except (TypeError, ValueError):
        return _MIN_SEGMENT
    if size < _MIN_SEGMENT:
        return _MIN_SEGMENT
    if not MDX_SEGMENTS:
        return max(_MIN_SEGMENT, size - (size % 32) if size % 32 else size)
    # Largest stop that is <= size; fall back to min stop.
    candidates = [stop for stop in MDX_SEGMENTS if stop <= size]
    return candidates[-1] if candidates else MDX_SEGMENTS[0]


def yaml_dim_t(model: Any) -> Optional[int]:
    """Return MDX-C / Roformer yaml ``inference.dim_t``, or ``None``."""
    configs = getattr(model, "mdx_c_configs", None)
    if configs is None:
        configs = getattr(model, "roformer_config", None)
    if configs is None:
        return None
    inference = getattr(configs, "inference", None)
    dim_t = getattr(inference, "dim_t", None) if inference is not None else None
    if dim_t is None:
        return None
    try:
        value = int(dim_t)
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


def default_segment(model: Any = None) -> int:
    """Model yaml default segment, or 256 when unknown."""
    dim_t = yaml_dim_t(model) if model is not None else None
    if dim_t is None:
        return _DEFAULT_DIM_T
    return snap_segment_down(dim_t)


def effective_segment(model: Any) -> int:
    """Segment size the engine would use for ``model`` right now."""
    if model is None:
        return _DEFAULT_DIM_T
    if bool(getattr(model, "is_mdx_c_seg_def", False)):
        return default_segment(model)
    try:
        size = int(getattr(model, "mdx_segment_size", _DEFAULT_DIM_T) or _DEFAULT_DIM_T)
    except (TypeError, ValueError):
        size = _DEFAULT_DIM_T
    return snap_segment_down(size) if size > 0 else _DEFAULT_DIM_T


def backoff_candidates(current: int, default: int) -> list[int]:
    """Segment sizes to try after OOM, largest first.

    Candidates are ``{half(current), default}`` that are strictly less than
    ``current``, at least 32, snapped to the MDX slider grid.
    """
    try:
        cur = int(current)
    except (TypeError, ValueError):
        return []
    try:
        def_size = int(default)
    except (TypeError, ValueError):
        def_size = _DEFAULT_DIM_T

    half = snap_segment_down(cur // 2)
    def_snapped = snap_segment_down(def_size)
    out: list[int] = []
    for candidate in (half, def_snapped):
        if candidate < cur and candidate >= _MIN_SEGMENT and candidate not in out:
            out.append(candidate)
    out.sort(reverse=True)
    return out


def supports_segment_backoff(model: Any) -> bool:
    """Whether Retry-with-segment is meaningful for this model/separator."""
    if model is None:
        return False
    if bool(getattr(model, "is_mdx_c", False)) or bool(getattr(model, "is_roformer", False)):
        return True
    process_method = str(getattr(model, "process_method", "") or "")
    if "MDX" in process_method.upper():
        return True
    # Live MDX separators expose segment size + demix without process_method.
    return hasattr(model, "mdx_segment_size") and hasattr(model, "demix")
