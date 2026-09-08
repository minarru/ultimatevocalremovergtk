"""Exact native Demucs subset selection shared by model construction and planning."""

from __future__ import annotations

from typing import Sequence

from .stems import StemRoute


def select_demucs_native_subset(
    routes: Sequence[StemRoute], selected: object
) -> tuple[tuple[StemRoute, ...], tuple[str, ...]]:
    """Return routes in inventory order and unmatched native keys, without aliases.

    A stale subset falls back as a whole to the default native inventory; plan
    diagnostics explain the unavailable keys before a run can be accepted.
    """
    native = tuple(route for route in routes if route.native is not None)
    if not isinstance(selected, (list, tuple)):
        return native, (repr(selected),)
    keys = {route.native.raw for route in native if route.native is not None}
    invalid = tuple(
        str(token) for token in selected if not isinstance(token, str) or token not in keys
    )
    wanted = {token for token in selected if isinstance(token, str)}
    if invalid or not wanted:
        return native, invalid
    return tuple(
        route for route in native if route.native is not None and route.native.raw in wanted
    ), ()
