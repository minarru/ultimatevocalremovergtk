"""Resolve external CLI tools (ffmpeg, rubberband) across platforms."""

from __future__ import annotations

import os
import shutil
import sys
from typing import Optional, Protocol, cast

from .paths import BASE_PATH

__all__ = [
    "configure_pydub_ffmpeg",
    "external_tools_status",
    "log_external_tools_once",
    "resolve_ffmpeg",
    "resolve_ffprobe",
    "resolve_rubberband",
]


class _FrozenRuntime(Protocol):
    _MEIPASS: str


_TOOLS_LOGGED = False


def _bundled_tool(name: str) -> Optional[str]:
    """Return a bundled executable next to ml or the PyInstaller bundle root."""
    if getattr(sys, "frozen", False):
        base = cast(_FrozenRuntime, sys)._MEIPASS
    else:
        base = os.path.join(BASE_PATH, "ml")
    for candidate in (
        os.path.join(base, name),
        os.path.join(base, name + (".exe" if os.name == "nt" else "")),
    ):
        if os.path.isfile(candidate) and (os.name == "nt" or os.access(candidate, os.X_OK)):
            return candidate
    return None


def resolve_ffmpeg() -> Optional[str]:
    """Return path to ffmpeg or None when not found."""
    env = os.environ.get("UVR_FFMPEG", "").strip()
    if env and os.path.isfile(env):
        return env
    bundled = _bundled_tool("ffmpeg")
    if bundled:
        return bundled
    return shutil.which("ffmpeg")


def resolve_ffprobe() -> Optional[str]:
    """Resolve ffprobe from override, ffmpeg sibling, bundle, then PATH."""
    override = os.environ.get("UVR_FFPROBE", "").strip()
    if override and os.path.isfile(override):
        return override
    ffmpeg = resolve_ffmpeg()
    if ffmpeg:
        sibling = os.path.join(
            os.path.dirname(ffmpeg), "ffprobe" + (".exe" if os.name == "nt" else "")
        )
        if os.path.isfile(sibling) and (os.name == "nt" or os.access(sibling, os.X_OK)):
            return sibling
    return _bundled_tool("ffprobe") or shutil.which("ffprobe")


def resolve_rubberband() -> Optional[str]:
    """Return path to rubberband CLI or None when not found."""
    env = os.environ.get("UVR_RUBBERBAND", "").strip()
    if env and os.path.isfile(env):
        return env
    bundled = _bundled_tool("rubberband")
    if bundled:
        return bundled
    return shutil.which("rubberband")


def configure_pydub_ffmpeg() -> Optional[str]:
    """Point pydub at ffmpeg when found; return the path or None."""
    path = resolve_ffmpeg()
    if not path:
        return None
    try:
        import pydub

        pydub.AudioSegment.converter = path
    except Exception:
        return None
    return path


def external_tools_status() -> dict[str, Optional[str]]:
    """Return resolved paths for dependency diagnostics."""
    return {
        "ffmpeg": resolve_ffmpeg(),
        "ffprobe": resolve_ffprobe(),
        "rubberband": resolve_rubberband(),
    }


def log_external_tools_once() -> None:
    """Log resolved ffmpeg/rubberband paths once per process."""
    global _TOOLS_LOGGED
    if _TOOLS_LOGGED:
        return
    _TOOLS_LOGGED = True
    from .debug_log import debug

    status = external_tools_status()
    ffmpeg = status.get("ffmpeg")
    rubberband = status.get("rubberband")
    debug(
        "audio",
        "external_tools "
        f"ffmpeg={'ok' if ffmpeg else 'missing'} "
        f"rubberband={'ok' if rubberband else 'missing'}",
    )
