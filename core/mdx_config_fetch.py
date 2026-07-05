"""Fetch MDX-C / Roformer YAML configs from TRvlvr or Politrees mirrors."""

from __future__ import annotations

import os
import ssl
import urllib.error
import urllib.request
from typing import Iterable, Optional

from bundled.constants import MDX23_CONFIG_CHECKS, POLITREES_CONFIG_SUBDIRS, POLITREES_RAW_BASE

from . import paths
from .debug_log import debug


def _ssl_context() -> ssl.SSLContext:
    if os.environ.get("UVR_INSECURE_DOWNLOADS") == "1":
        return ssl._create_unverified_context()
    return ssl.create_default_context()


def _urlopen(url: str):
    return urllib.request.urlopen(url, context=_ssl_context())


def _safe_config_name(filename: str) -> Optional[str]:
    """Return a basename ``*.yaml`` or ``None`` if the name is unsafe."""
    if not filename or os.path.basename(filename) != filename:
        return None
    if ".." in filename or "/" in filename or "\\" in filename:
        return None
    if not filename.endswith(".yaml"):
        return None
    return filename


def _config_dest(filename: str) -> str:
    return os.path.join(paths.MDX_C_CONFIG_PATH, filename)


def _trvlvr_config_url(filename: str) -> str:
    return f"{MDX23_CONFIG_CHECKS}{filename}"


def _politrees_config_urls(filename: str) -> Iterable[str]:
    for subdir in POLITREES_CONFIG_SUBDIRS:
        yield f"{POLITREES_RAW_BASE}/UVR_resources/configs/{subdir}/{filename}"


def _fetch_url_to_file(url: str, dest: str) -> bool:
    try:
        with _urlopen(url) as response:
            data = response.read()
    except urllib.error.HTTPError as exc:
        debug("download", f"mdx_c_config http {exc.code} url={url}")
        return False
    except Exception as exc:
        debug("download", f"mdx_c_config error url={url} err={type(exc).__name__}: {exc}")
        return False

    if not data:
        debug("download", f"mdx_c_config empty body url={url}")
        return False

    os.makedirs(paths.MDX_C_CONFIG_PATH, exist_ok=True)
    with open(dest, "wb") as out_file:
        out_file.write(data)
    debug("download", f"mdx_c_config saved {os.path.basename(dest)} from {url}")
    return True


def config_source_urls(filename: str) -> list[str]:
    """Ordered remote URLs tried for ``filename`` (for tests and diagnostics)."""
    safe = _safe_config_name(filename)
    if not safe:
        return []
    urls = [_trvlvr_config_url(safe)]
    urls.extend(_politrees_config_urls(safe))
    return urls


def ensure_mdx_c_config(filename: str) -> bool:
    """Ensure ``filename`` exists under ``MDX_C_CONFIG_PATH``, fetching if needed."""
    safe = _safe_config_name(filename)
    if not safe:
        debug("download", f"mdx_c_config rejected unsafe name={filename!r}")
        return False

    dest = _config_dest(safe)
    if os.path.isfile(dest):
        return True

    for url in config_source_urls(safe):
        if _fetch_url_to_file(url, dest):
            return True

    debug("download", f"mdx_c_config unavailable name={safe}")
    return False


def fetch_mdx_config_url(filename: str, url: str) -> bool:
    """Download a remote YAML into ``MDX_C_CONFIG_PATH``."""
    safe = _safe_config_name(filename)
    if not safe or not url:
        return False
    dest = _config_dest(safe)
    if os.path.isfile(dest):
        return True
    return _fetch_url_to_file(url, dest)
