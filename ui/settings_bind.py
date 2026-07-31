"""Small typed-settings access helpers for dynamic UI bindings.

The implementations live in :mod:`core.settings.access` so headless callers can
use them without importing GTK. Re-exported here for existing UI call sites.
"""

from __future__ import annotations

from core.settings.access import _MISSING, get_flat, get_path, set_flat, set_path
from core.settings.coerce import setting_for_combo

__all__ = [
    "_MISSING",
    "get_flat",
    "get_path",
    "set_flat",
    "set_path",
    "setting_for_combo",
]
