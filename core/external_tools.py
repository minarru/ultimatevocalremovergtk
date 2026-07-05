"""Resolve external CLI tools (ffmpeg, rubberband) across platforms."""

from __future__ import annotations

import os
import shutil
import sys
from typing import Optional

from .paths import BASE_PATH

__all__ = [
    "configure_pydub_ffmpeg",
    "external_tools_status",
    "resolve_ffmpeg",
    "resolve_rubberband",
]


def _bundled_tool(name: str) -> Optional[str]:
    """Return a bundled executable next to lib_v5 or the PyInstaller bundle root."""
    if getattr(sys, "frozen", False):
        base = sys._MEIPASS
    else:
        base = os.path.join(BASE_PATH, "lib_v5")
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
        "rubberband": resolve_rubberband(),
    }
