"""Neutral construction and bundled loading for catalogue membership sources.

Source state, network/cache policy, and refresh coalescing remain owned by
RemoteJsonSource and CatalogueCoordinator. This module has no manager dependency.
"""

from __future__ import annotations

import json
import os
import ssl
import urllib.request
from typing import Any, Mapping

from bundled.constants import DOWNLOAD_CHECKS

from . import paths
from .catalogue_types import SourceId
from .remote_catalog_cache import RemoteJsonSource


def ssl_context() -> ssl.SSLContext:
    """Preserve the shared catalogue/download TLS opt-out."""
    if os.environ.get("UVR_INSECURE_DOWNLOADS") == "1":
        return ssl._create_unverified_context()
    return ssl.create_default_context()


def open_upstream(target: str | urllib.request.Request) -> Any:
    return urllib.request.urlopen(target, context=ssl_context(), timeout=30)


def load_bundled_upstream(path: str | None = None) -> dict:
    """Read shipped upstream membership, returning the legacy empty fallback."""
    try:
        with open(paths.DOWNLOAD_MODEL_CACHE_PATH if path is None else path, "r") as cache_file:
            return json.load(cache_file)
    except (OSError, ValueError):
        return {}


def default_sources() -> dict[SourceId, RemoteJsonSource]:
    from bundled.constants import MVSEPLESS_MODELS_JSON_URL, POLITREES_MODEL_LINKS_URL

    from . import extra_catalog, mvsepless_catalog, paths, politrees_catalog

    def politrees_open(target: str | Any) -> Any:
        return politrees_catalog._urlopen(target)

    def mvsepless_open(target: str | Any) -> Any:
        return mvsepless_catalog._urlopen(target)

    def extras_loader() -> Mapping[str, Any] | None:
        data = extra_catalog.load_extra_models()
        return data or None

    return {
        SourceId.UPSTREAM: RemoteJsonSource(
            source_id=SourceId.UPSTREAM,
            url=DOWNLOAD_CHECKS,
            cache_filename="upstream_download_checks.json",
            cache_path=paths.UPSTREAM_CATALOGUE_CACHE_FILE,
            opener=open_upstream,
            bundled_fallback=lambda: load_bundled_upstream() or None,
        ),
        SourceId.POLITREES: RemoteJsonSource(
            source_id=SourceId.POLITREES,
            url=POLITREES_MODEL_LINKS_URL,
            cache_filename="politrees_model_links.json",
            cache_path=paths.POLITREES_CACHE_FILE,
            opener=politrees_open,
            enabled=politrees_catalog.politrees_enabled,
        ),
        SourceId.EXTRAS: RemoteJsonSource(
            source_id=SourceId.EXTRAS,
            local_loader=extras_loader,
            enabled=extra_catalog.extra_catalog_enabled,
        ),
        SourceId.MVSEPLESS: RemoteJsonSource(
            source_id=SourceId.MVSEPLESS,
            url=MVSEPLESS_MODELS_JSON_URL,
            cache_filename="mvsepless_models.json",
            cache_path=paths.MVSEPLESS_CACHE_FILE,
            opener=mvsepless_open,
            enabled=mvsepless_catalog.mvsepless_enabled,
        ),
    }
