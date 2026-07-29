"""GLib log emission shim for :mod:`core.debug_log`."""

from __future__ import annotations

import warnings
from typing import Any, Callable, Optional

_EMIT_HOOK: Optional[Callable[[str, str, int], None]] = None
_INITIALIZED = False
_GLIB: Any = None
_WARNED_NO_GLIB = False


def set_emit_hook(
    hook: Optional[Callable[[str, str, int], None]],
) -> None:
    """Replace GLib emit (tests only). ``hook(domain, message, level)``."""
    global _EMIT_HOOK
    _EMIT_HOOK = hook


def init() -> None:
    """Load GLib once; call from the UI entry point before worker threads log."""
    global _INITIALIZED, _GLIB
    if _INITIALIZED:
        return
    from .debug_log import normalize_g_messages_debug_env

    normalize_g_messages_debug_env()
    _INITIALIZED = True
    try:
        import gi

        gi.require_version("GLib", "2.0")
        from gi.repository import GLib

        _GLIB = GLib
    except Exception:  # noqa: BLE001 - optional until first emit
        _GLIB = None


def _warn_no_glib_once() -> None:
    global _WARNED_NO_GLIB
    if _WARNED_NO_GLIB:
        return
    _WARNED_NO_GLIB = True
    warnings.warn(
        "UVR debug logging requires PyGObject/GLib; messages were dropped",
        RuntimeWarning,
        stacklevel=4,
    )


def emit(domain: str, message: str, *, level: str = "debug") -> None:
    """Emit one log line via ``GLib.log_variant`` (stderr / journald)."""
    if _EMIT_HOOK is not None:
        glib_level = _level_flag(level)
        _EMIT_HOOK(domain, message, glib_level)
        return

    if _GLIB is None:
        init()
    glib = _GLIB
    if glib is None:
        _warn_no_glib_once()
        return

    fields = glib.Variant("a{sv}", {"MESSAGE": glib.Variant("s", message)})
    glib.log_variant(domain, _level_flag(level), fields)


def _level_flag(level: str) -> int:
    glib = _GLIB
    if glib is None:
        init()
        glib = _GLIB
    if glib is None:
        return 0
    flags = glib.LogLevelFlags
    mapping = {
        "debug": flags.LEVEL_DEBUG,
        "message": flags.LEVEL_MESSAGE,
        "info": flags.LEVEL_INFO,
        "warning": flags.LEVEL_WARNING,
        "error": flags.LEVEL_ERROR,
    }
    return mapping.get(level, flags.LEVEL_DEBUG)
