"""Cross-platform user data and cache directory resolution.

Centralizes OS-specific defaults so :mod:`core.paths` and
:mod:`core.debug_log` do not assume Linux XDG layout.
"""

from __future__ import annotations

import os
import platform

_APP_NAME = "ultimatevocalremover"
_CACHE_SUBDIR = "uvr"


def system_name() -> str:
    """Return ``platform.system()`` (Linux, Windows, Darwin, …)."""
    return platform.system()


def default_user_data_dir(app_name: str = _APP_NAME) -> str:
    """OS-default writable application data root (no env overrides)."""
    system = system_name()
    home = os.path.expanduser("~")

    if system == "Windows":
        local = os.environ.get("LOCALAPPDATA") or os.path.join(home, "AppData", "Local")
        return os.path.join(local, "UltimateVocalRemover")

    if system == "Darwin":
        return os.path.join(home, "Library", "Application Support", app_name)

    # Linux and other Unix-like systems.
    xdg = os.environ.get("XDG_DATA_HOME") or os.path.join(home, ".local", "share")
    return os.path.join(xdg, app_name)


def user_data_dir(base_path: str | None = None) -> str:
    """Resolve the writable application data root.

    Priority:
    1. ``$UVR_DATA_DIR`` when set
    2. ``base_path`` when provided and writable (portable install)
    3. :func:`default_user_data_dir`
    """
    env_dir = os.environ.get("UVR_DATA_DIR")
    if env_dir:
        return os.path.abspath(os.path.expanduser(env_dir))
    if base_path is not None and os.access(base_path, os.W_OK):
        return base_path
    return default_user_data_dir()


def default_user_cache_dir(cache_subdir: str = _CACHE_SUBDIR) -> str:
    """OS-default cache directory for debug logs and temp artifacts."""
    system = system_name()
    home = os.path.expanduser("~")

    if system == "Windows":
        local = os.environ.get("LOCALAPPDATA") or os.path.join(home, "AppData", "Local")
        return os.path.join(local, cache_subdir)

    if system == "Darwin":
        return os.path.join(home, "Library", "Caches", cache_subdir)

    xdg = os.environ.get("XDG_CACHE_HOME") or os.path.join(home, ".cache")
    return os.path.join(xdg, cache_subdir)


def user_cache_dir() -> str:
    """Resolve the cache directory (``$UVR_CACHE_DIR`` override supported)."""
    env_dir = os.environ.get("UVR_CACHE_DIR")
    if env_dir:
        return os.path.abspath(os.path.expanduser(env_dir))
    return default_user_cache_dir()
