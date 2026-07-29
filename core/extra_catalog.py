"""Fork-curated catalogue additions merged on top of the upstream lists.

``DownloadManager.refresh`` replaces ``online_data`` wholesale with TRvlvr's
``download_checks.json``, so anything added to the bundled
``model_manual_download.json`` cache is lost the moment the app goes online.
Entries curated by this fork therefore live in ``bundled/extra_models.json``
and are merged after both the upstream rebuild and the Politrees supplement.

Upstream always wins: a label already present in the TRvlvr or Politrees
catalogues is never overwritten here.
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict, Mapping, Optional, Tuple

from .debug_log import debug

_EXTRA_MODELS_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "bundled",
    "extra_models.json",
)

#: Extra-catalogue keys whose entries resolve through the MDX download path
#: (same compact ``{selectable: {checkpoint: config}}`` schema).
_EXTRA_MDX_SOURCE_KEYS = (
    "mdx_download_list",
    "mdx23c_download_list",
    "roformer_download_list",
    "scnet_download_list",
    "bandit_download_list",
)

APOLLO_LIST_KEY = "apollo_download_list"

_cached: Optional[Dict] = None


def extra_catalog_enabled() -> bool:
    return os.environ.get("UVR_DISABLE_EXTRA_MODELS", "").strip().lower() not in (
        "1",
        "true",
        "yes",
    )


def clear_extra_catalog_cache() -> None:
    global _cached
    _cached = None


def load_extra_models() -> Dict:
    """Return the bundled fork catalogue, or ``{}`` when missing/disabled."""
    global _cached

    if not extra_catalog_enabled():
        return {}
    if _cached is not None:
        return _cached

    try:
        with open(_EXTRA_MODELS_FILE, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, ValueError) as exc:
        debug("download", f"extra catalogue load failed err={type(exc).__name__}: {exc}")
        payload = {}

    if not isinstance(payload, dict):
        payload = {}
    # Drop the ``_comment`` documentation block and any non-dict entries.
    _cached = {
        key: value
        for key, value in payload.items()
        if isinstance(value, dict) and not key.startswith("_")
    }
    return _cached


def _merge_missing(
    base: Mapping[str, Any], extra: Mapping[str, Any]
) -> Dict[str, Any]:
    """Add entries from ``extra`` that ``base`` does not already define."""
    merged = dict(base)
    added = 0
    for key, value in extra.items():
        if key not in merged:
            merged[key] = value
            added += 1
    if added:
        debug("download", f"extra catalogue merged {added} entries")
    return merged


def merge_extra_catalogues(
    vr: Mapping[str, Any],
    mdx: Mapping[str, Any],
    demucs: Mapping[str, Any],
    extra: Optional[Dict] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Merge fork-curated VR / MDX-family / Demucs entries into the catalogues."""
    data = load_extra_models() if extra is None else extra
    if not data:
        return dict(vr), dict(mdx), dict(demucs)

    vr = _merge_missing(vr, data.get("vr_download_list", {}))
    demucs = _merge_missing(demucs, data.get("demucs_download_list", {}))
    for key in _EXTRA_MDX_SOURCE_KEYS:
        mdx = _merge_missing(mdx, data.get(key, {}))
    return dict(vr), dict(mdx), dict(demucs)


def apollo_download_list(extra: Optional[Dict] = None) -> Dict[str, Any]:
    """Return the curated Apollo restoration catalogue."""
    data = load_extra_models() if extra is None else extra
    entries = data.get(APOLLO_LIST_KEY, {})
    return dict(entries) if isinstance(entries, dict) else {}
