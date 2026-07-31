"""Live-merge the noblebarkrr/mvsepless_resources catalogue into Download Center.

Fetches ``models.json`` from Hugging Face (Politrees-style disk cache), converts
entries into UVR download-list shape, and classifies which models this fork can
actually run. Unsupported entries are exposed separately so the UI can show them
grayed out without offering a download.
"""

from __future__ import annotations

import json
import os
import time
from typing import Any, Dict, List, Mapping, Optional, Tuple
from urllib.parse import unquote, urlparse

from bundled.constants import (
    DEMUCS_ARCH_TYPE,
    MDX_ARCH_TYPE,
    MVSEPLESS_MODELS_JSON_URL,
    VR_ARCH_TYPE,
)

from . import paths
from .catalog_dedupe import normalize_catalogue_label
from .debug_log import debug
from .mdx_config_fetch import _urlopen
from .politrees_catalog import merge_supplemental_list

_MVSEPLESS_CACHE_TTL_SECONDS = 24 * 60 * 60

#: MDX-family list keys that flatten into the Download Center MDX tab.
_MVSEPLESS_MDX_SOURCE_KEYS = (
    "mdx_download_list",
    "mdx23c_download_list",
    "roformer_download_list",
    "scnet_download_list",
    "bandit_download_list",
)

#: model_type values we can download + run via existing MDX-C / Bandit paths.
_SUPPORTED_MODEL_TYPES = frozenset(
    {
        "mel_band_roformer",
        "bs_roformer",
        "mdx23c",
        "scnet",
        "bandit",
        "bandit_v2",
    }
)

#: model_type → short UI reason (always unsupported in first pass).
_UNSUPPORTED_MODEL_TYPES: Dict[str, str] = {
    "medley_vox": "Medley-Vox engine not ported",
    "scnet_masked": "SCNet Masked not ported",
    "scnet_tran": "SCNet Tran not ported",
    "htdemucs": "MSST Demucs single-ckpt format not supported",
    "vr": "needs VR .ckpt+yaml hash bridge",
    "mdxnet": "needs MDX-Net ONNX yaml→hash bridge",
}

#: Known entry ids whose yaml needs features we do not implement.
_UNSUPPORTED_ENTRY_IDS: Dict[str, str] = {
    "mbr_wsa": "Windowed Sink Attention Mel-Band not ported",
    "bs_cr_4stem_zf_turbo": "BS Conformer not ported",
    "mbr_syhft_4stem": "Mel-Band skip_connection not ported",
    "mbr_syhft_4stem2": "Mel-Band skip_connection not ported",
    "mbr_4stemlarge1_aname": "Mel-Band skip_connection not ported",
    "mbr_4stemlarge2_aname": "Mel-Band skip_connection not ported",
    "mbr_4stemxl1_aname": "Mel-Band skip_connection not ported",
}

_MODEL_TYPE_TO_LIST_KEY: Dict[str, str] = {
    "mel_band_roformer": "roformer_download_list",
    "bs_roformer": "roformer_download_list",
    "mdx23c": "mdx23c_download_list",
    "scnet": "scnet_download_list",
    "bandit": "bandit_download_list",
    "bandit_v2": "bandit_download_list",
    "mdxnet": "mdx_download_list",
    "vr": "vr_download_list",
    "htdemucs": "demucs_download_list",
    "medley_vox": "mdx_download_list",
    "scnet_masked": "scnet_download_list",
    "scnet_tran": "scnet_download_list",
}

_MODEL_TYPE_TO_ARCH: Dict[str, str] = {
    "mel_band_roformer": MDX_ARCH_TYPE,
    "bs_roformer": MDX_ARCH_TYPE,
    "mdx23c": MDX_ARCH_TYPE,
    "scnet": MDX_ARCH_TYPE,
    "bandit": MDX_ARCH_TYPE,
    "bandit_v2": MDX_ARCH_TYPE,
    "mdxnet": MDX_ARCH_TYPE,
    "medley_vox": MDX_ARCH_TYPE,
    "scnet_masked": MDX_ARCH_TYPE,
    "scnet_tran": MDX_ARCH_TYPE,
    "vr": VR_ARCH_TYPE,
    "htdemucs": DEMUCS_ARCH_TYPE,
}

_cached_models: Optional[Dict[str, Any]] = None
_cached_loaded_at: float = 0.0
_cached_converted: Optional[Dict[str, Any]] = None


def mvsepless_enabled() -> bool:
    return os.environ.get("UVR_DISABLE_MVSEPLESS", "").strip().lower() not in (
        "1",
        "true",
        "yes",
    )


def clear_mvsepless_cache() -> None:
    global _cached_models, _cached_loaded_at, _cached_converted
    _cached_models = None
    _cached_loaded_at = 0.0
    _cached_converted = None


def _cache_path() -> str:
    return paths.migrate_cache_file("mvsepless_models.json", paths.MVSEPLESS_CACHE_FILE)


def _read_disk_cache() -> Optional[Dict[str, Any]]:
    try:
        with open(_cache_path(), "r", encoding="utf-8") as handle:
            payload = json.load(handle)
        if isinstance(payload, dict) and isinstance(payload.get("data"), dict):
            return payload["data"]
    except (OSError, ValueError, TypeError):
        pass
    return None


def _write_disk_cache(data: Dict[str, Any]) -> None:
    try:
        cache_path = _cache_path()
        os.makedirs(os.path.dirname(cache_path) or ".", exist_ok=True)
        with open(cache_path, "w", encoding="utf-8") as handle:
            json.dump({"fetched_at": time.time(), "data": data}, handle)
    except OSError as exc:
        debug("download", f"mvsepless cache write failed err={exc}")


def load_mvsepless_models(*, force: bool = False) -> Optional[Dict[str, Any]]:
    """Return raw ``models.json`` dict, or ``None`` when disabled/unavailable."""
    global _cached_models, _cached_loaded_at, _cached_converted

    if not mvsepless_enabled():
        return None

    now = time.time()
    if (
        not force
        and _cached_models is not None
        and (now - _cached_loaded_at) < _MVSEPLESS_CACHE_TTL_SECONDS
    ):
        return _cached_models

    data: Optional[Dict[str, Any]] = None
    try:
        with _urlopen(MVSEPLESS_MODELS_JSON_URL) as response:
            data = json.load(response)
    except Exception as exc:
        debug("download", f"mvsepless fetch failed err={type(exc).__name__}: {exc}")
        data = _read_disk_cache()

    if not isinstance(data, dict):
        return None

    _cached_models = data
    _cached_loaded_at = now
    _cached_converted = None
    _write_disk_cache(data)
    return data


def url_basename(url: str) -> str:
    """Return the safe basename of a remote URL (strip query / fragment)."""
    path = urlparse(str(url)).path
    name = os.path.basename(unquote(path))
    return name


def classify_entry(entry_id: str, entry: Mapping[str, Any]) -> Tuple[bool, str]:
    """Return ``(supported, reason)``. Reason is empty when supported."""
    model_type = str(entry.get("model_type") or "")
    if entry_id in _UNSUPPORTED_ENTRY_IDS:
        return False, _UNSUPPORTED_ENTRY_IDS[entry_id]
    if model_type in _UNSUPPORTED_MODEL_TYPES:
        return False, _UNSUPPORTED_MODEL_TYPES[model_type]
    if model_type not in _SUPPORTED_MODEL_TYPES:
        return False, f"unknown model_type {model_type!r}"
    return True, ""


def _safe_remote_basename(url: str) -> Optional[str]:
    parsed = urlparse(str(url))
    if ".." in parsed.path.split("/"):
        return None
    name = os.path.basename(unquote(parsed.path))
    if not name or os.path.basename(name) != name or ".." in name:
        return None
    return name


def entry_files(entry: Mapping[str, Any]) -> Optional[Dict[str, str]]:
    """Build ``{local_filename: url}`` for one catalogue entry."""
    ckpt_url = entry.get("checkpoint_url")
    cfg_url = entry.get("config_url")
    if not isinstance(ckpt_url, str) or not isinstance(cfg_url, str):
        return None
    if not ckpt_url.startswith(("http://", "https://")):
        return None
    if not cfg_url.startswith(("http://", "https://")):
        return None
    ckpt_name = _safe_remote_basename(ckpt_url)
    cfg_name = _safe_remote_basename(cfg_url)
    if not ckpt_name or not cfg_name:
        return None
    return {ckpt_name: ckpt_url, cfg_name: cfg_url}


def entry_label(entry_id: str, entry: Mapping[str, Any]) -> str:
    name = str(entry.get("full_name") or "").strip()
    return name or entry_id


def convert_mvsepless_catalog(
    models: Mapping[str, Any],
) -> Dict[str, Any]:
    """Convert raw ``models.json`` into UVR list keys + unsupported metadata.

    Returns::

        {
          "vr_download_list": {...},
          "mdx_download_list": {...},  # flattened MDX-family supported entries
          "demucs_download_list": {...},
          "unsupported": {arch: [(label, reason), ...]},
          "unsupported_labels": {label: reason},
        }
    """
    lists: Dict[str, Dict[str, Any]] = {
        "vr_download_list": {},
        "mdx_download_list": {},
        "mdx23c_download_list": {},
        "roformer_download_list": {},
        "scnet_download_list": {},
        "bandit_download_list": {},
        "demucs_download_list": {},
    }
    unsupported: Dict[str, List[Tuple[str, str]]] = {
        VR_ARCH_TYPE: [],
        MDX_ARCH_TYPE: [],
        DEMUCS_ARCH_TYPE: [],
    }
    unsupported_labels: Dict[str, str] = {}

    for entry_id, entry in models.items():
        if not isinstance(entry, dict):
            continue
        model_type = str(entry.get("model_type") or "")
        label = entry_label(str(entry_id), entry)
        files = entry_files(entry)
        supported, reason = classify_entry(str(entry_id), entry)
        arch = _MODEL_TYPE_TO_ARCH.get(model_type, MDX_ARCH_TYPE)

        if not supported or files is None:
            if not reason:
                reason = "invalid catalogue entry"
            unsupported.setdefault(arch, []).append((label, reason))
            unsupported_labels[label] = reason
            continue

        list_key = _MODEL_TYPE_TO_LIST_KEY.get(model_type)
        if not list_key:
            unsupported.setdefault(arch, []).append(
                (label, f"unmapped model_type {model_type!r}")
            )
            unsupported_labels[label] = f"unmapped model_type {model_type!r}"
            continue
        # Upstream-wins within the converted set too (first label keeps files).
        if label in lists[list_key]:
            continue
        lists[list_key][label] = files

    # Flatten MDX-family lists the same way Politrees / extras do for the UI.
    mdx_flat: Dict[str, Any] = {}
    for key in _MVSEPLESS_MDX_SOURCE_KEYS:
        mdx_flat = merge_supplemental_list(mdx_flat, lists[key])

    return {
        "vr_download_list": lists["vr_download_list"],
        "mdx_download_list": mdx_flat,
        "demucs_download_list": lists["demucs_download_list"],
        "unsupported": unsupported,
        "unsupported_labels": unsupported_labels,
    }


def load_converted_mvsepless(*, force: bool = False) -> Optional[Dict[str, Any]]:
    """Fetch/convert with in-memory cache of the converted shape."""
    global _cached_converted

    if not mvsepless_enabled():
        return None
    if not force and _cached_converted is not None:
        return _cached_converted

    models = load_mvsepless_models(force=force)
    if not models:
        return None
    _cached_converted = convert_mvsepless_catalog(models)
    return _cached_converted


def merge_mvsepless_catalogues(
    vr: Mapping[str, Any],
    mdx: Mapping[str, Any],
    demucs: Mapping[str, Any],
    converted: Optional[Mapping[str, Any]] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Merge supported mvsepless entries; never overwrite existing labels."""
    data = load_converted_mvsepless() if converted is None else converted
    if not data:
        return dict(vr), dict(mdx), dict(demucs)

    vr_out = merge_supplemental_list(vr, data.get("vr_download_list", {}))
    mdx_out = merge_supplemental_list(mdx, data.get("mdx_download_list", {}))
    demucs_out = merge_supplemental_list(demucs, data.get("demucs_download_list", {}))
    added = (
        len(vr_out)
        - len(vr)
        + len(mdx_out)
        - len(mdx)
        + len(demucs_out)
        - len(demucs)
    )
    if added:
        debug("download", f"mvsepless merged {added} new catalogue entries")
    return dict(vr_out), dict(mdx_out), dict(demucs_out)


def unsupported_mvsepless_downloads(
    converted: Optional[Mapping[str, Any]] = None,
    *,
    existing_labels: Optional[Mapping[str, Any]] = None,
) -> Dict[str, List[Tuple[str, str]]]:
    """Return ``{arch: [(label, reason), ...]}`` for unsupported entries.

    Labels already present in ``existing_labels`` (any arch catalogue) are
    omitted so upstream-supported duplicates are not shown as broken. Matching
    is exact or via :func:`normalize_catalogue_label`.
    """
    data = load_converted_mvsepless() if converted is None else converted
    if not data:
        return {}

    taken = set(existing_labels or {})
    taken_norm = {
        normalize_catalogue_label(label)
        for label in taken
        if normalize_catalogue_label(label)
    }
    result: Dict[str, List[Tuple[str, str]]] = {}
    raw = data.get("unsupported") or {}
    if not isinstance(raw, dict):
        return {}
    for arch, rows in raw.items():
        if not isinstance(rows, list):
            continue
        filtered: List[Tuple[str, str]] = []
        for item in rows:
            if not (isinstance(item, (list, tuple)) and len(item) == 2):
                continue
            label, reason = str(item[0]), str(item[1])
            if label in taken:
                continue
            norm = normalize_catalogue_label(label)
            if norm and norm in taken_norm:
                continue
            filtered.append((label, reason))
        if filtered:
            # Stable order by label for the UI.
            filtered.sort(key=lambda pair: pair[0].casefold())
            result[str(arch)] = filtered
    return result


def unsupported_reason_for_label(
    label: str, converted: Optional[Mapping[str, Any]] = None
) -> Optional[str]:
    data = load_converted_mvsepless() if converted is None else converted
    if not data:
        return None
    reasons = data.get("unsupported_labels") or {}
    if not isinstance(reasons, dict):
        return None
    reason = reasons.get(label)
    return str(reason) if reason else None
