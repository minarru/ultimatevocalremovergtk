"""Load and merge Politrees UVR_resources download catalogues."""

from __future__ import annotations

import json
import os
import time
from typing import Dict, List, Optional, Tuple

from bundled.constants import POLITREES_MODEL_LINKS_URL

from . import paths
from .debug_log import debug
from .mdx_config_fetch import _urlopen, fetch_mdx_config_url

_POLITREES_CACHE_PATH = os.path.join(paths.DATA_DIR, "politrees_model_links.json")
_POLITREES_CACHE_TTL_SECONDS = 24 * 60 * 60

_POLITREES_MDX_SOURCE_KEYS = (
    "mdx_download_list",
    "mdx23c_download_list",
    "roformer_download_list",
    "scnet_download_list",
    "bandit_download_list",
)

_cached_links: Optional[Dict] = None
_cached_weight_index: Optional[Dict[str, str]] = None
_cached_loaded_at: float = 0.0


def politrees_enabled() -> bool:
    return os.environ.get("UVR_DISABLE_POLITREES", "").strip().lower() not in (
        "1",
        "true",
        "yes",
    )


def is_remote_ref(value: object) -> bool:
    return isinstance(value, str) and value.startswith(("http://", "https://"))


def clear_politrees_cache() -> None:
    global _cached_links, _cached_weight_index, _cached_loaded_at
    _cached_links = None
    _cached_weight_index = None
    _cached_loaded_at = 0.0


def _read_disk_cache() -> Optional[Dict]:
    try:
        with open(_POLITREES_CACHE_PATH, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
        if isinstance(payload, dict) and isinstance(payload.get("data"), dict):
            return payload["data"]
    except (OSError, ValueError, TypeError):
        pass
    return None


def _write_disk_cache(data: Dict) -> None:
    try:
        os.makedirs(os.path.dirname(_POLITREES_CACHE_PATH), exist_ok=True)
        with open(_POLITREES_CACHE_PATH, "w", encoding="utf-8") as handle:
            json.dump({"fetched_at": time.time(), "data": data}, handle)
    except OSError as exc:
        debug("download", f"politrees cache write failed err={exc}")


def load_politrees_links(*, force: bool = False) -> Optional[Dict]:
    """Return Politrees ``model_list_links.json`` or ``None`` when disabled/offline."""
    global _cached_links, _cached_weight_index, _cached_loaded_at

    if not politrees_enabled():
        return None

    now = time.time()
    if (
        not force
        and _cached_links is not None
        and (now - _cached_loaded_at) < _POLITREES_CACHE_TTL_SECONDS
    ):
        return _cached_links

    data: Optional[Dict] = None
    try:
        with _urlopen(POLITREES_MODEL_LINKS_URL) as response:
            data = json.load(response)
    except Exception as exc:
        debug("download", f"politrees fetch failed err={type(exc).__name__}: {exc}")
        data = _read_disk_cache()

    if not isinstance(data, dict):
        return None

    _cached_links = data
    _cached_weight_index = None
    _cached_loaded_at = now
    _write_disk_cache(data)
    return data


def merge_supplemental_list(base: Dict[str, object], extra: Dict[str, object]) -> Dict[str, object]:
    """Add catalogue entries present in ``extra`` but not in ``base``."""
    merged = dict(base)
    added = 0
    for key, value in extra.items():
        if key not in merged:
            merged[key] = value
            added += 1
    if added:
        debug("download", f"politrees merged {added} new catalogue entries")
    return merged


def merge_politrees_catalogues(
    vr: Dict[str, object],
    mdx: Dict[str, object],
    demucs: Dict[str, object],
    politrees: Optional[Dict],
) -> Tuple[Dict[str, object], Dict[str, object], Dict[str, object]]:
    if not politrees:
        return vr, mdx, demucs

    vr = merge_supplemental_list(vr, politrees.get("vr_download_list", {}))
    demucs = merge_supplemental_list(demucs, politrees.get("demucs_download_list", {}))

    for key in _POLITREES_MDX_SOURCE_KEYS:
        mdx = merge_supplemental_list(mdx, politrees.get(key, {}))

    return vr, mdx, demucs


def build_weight_url_index(links_data: Dict) -> Dict[str, str]:
    """Map checkpoint filename → direct download URL from Politrees lists."""
    index: Dict[str, str] = {}
    for catalog in links_data.values():
        if not isinstance(catalog, dict):
            continue
        for model in catalog.values():
            if isinstance(model, dict):
                for filename, ref in model.items():
                    if filename.endswith(".yaml"):
                        continue
                    if is_remote_ref(ref):
                        index[filename] = ref
    return index


def hf_fallback_url(url: str, index: Optional[Dict[str, str]] = None) -> Optional[str]:
    """Return a Hugging Face mirror URL for a TRvlvr ``NORMAL_REPO`` asset."""
    from bundled.constants import NORMAL_REPO

    if not url.startswith(NORMAL_REPO):
        return None
    filename = url[len(NORMAL_REPO) :]
    if not filename or "/" in filename:
        return None

    if index is None:
        links = load_politrees_links()
        if not links:
            return None
        index = build_weight_url_index(links)

    return index.get(filename)


def mdx_checkpoint_filename(model: object) -> str:
    if isinstance(model, dict):
        for name in model:
            if not name.endswith(".yaml"):
                return name
        return next(iter(model))
    return str(model)


def prefetch_mdx_catalog_entry(model: object) -> None:
    """Ensure local YAML exists for an MDX catalogue entry when possible."""
    if not isinstance(model, dict):
        return

    for name, ref in model.items():
        if name.endswith(".yaml"):
            if is_remote_ref(ref):
                if fetch_mdx_config_url(name, ref):
                    continue
            continue

        if not is_remote_ref(ref):
            from .mdx_config_fetch import ensure_mdx_c_config

            ensure_mdx_c_config(ref)


def resolve_vr_jobs(model: object, model_repo: str) -> List[Tuple[str, str]]:
    if isinstance(model, dict):
        jobs: List[Tuple[str, str]] = []
        for filename, ref in model.items():
            if is_remote_ref(ref):
                jobs.append((ref, os.path.join(paths.VR_MODELS_DIR, filename)))
            else:
                jobs.append((f"{model_repo}{filename}", os.path.join(paths.VR_MODELS_DIR, filename)))
        return jobs
    return [(f"{model_repo}{model}", os.path.join(paths.VR_MODELS_DIR, model))]


def resolve_mdx_jobs(model: object, model_repo: str) -> List[Tuple[str, str]]:
    if isinstance(model, dict):
        jobs: List[Tuple[str, str]] = []
        for name, ref in model.items():
            if name.endswith(".yaml"):
                if is_remote_ref(ref):
                    from .mdx_config_fetch import _safe_config_name

                    safe = _safe_config_name(name)
                    if safe:
                        jobs.append((ref, os.path.join(paths.MDX_C_CONFIG_PATH, safe)))
                continue
            if is_remote_ref(ref):
                jobs.append((ref, os.path.join(paths.MDX_MODELS_DIR, name)))
            else:
                jobs.append((f"{model_repo}{name}", os.path.join(paths.MDX_MODELS_DIR, name)))
                from .mdx_config_fetch import ensure_mdx_c_config

                ensure_mdx_c_config(ref)
        return jobs
    return [(f"{model_repo}{model}", os.path.join(paths.MDX_MODELS_DIR, model))]


def resolve_demucs_jobs(model: object, selection: str) -> List[Tuple[str, str]]:
    from bundled.constants import DEMUCS_NEWER_ARCH_TYPES

    if not isinstance(model, dict):
        return []
    is_newer = any(tag in selection for tag in DEMUCS_NEWER_ARCH_TYPES)
    directory = paths.DEMUCS_NEWER_REPO_DIR if is_newer else paths.DEMUCS_MODELS_DIR
    jobs: List[Tuple[str, str]] = []
    for file_name, ref in model.items():
        if is_remote_ref(ref):
            jobs.append((ref, os.path.join(directory, file_name)))
        else:
            jobs.append((ref, os.path.join(directory, file_name)))
    return jobs


def manual_links_for_model(arch_type: str, model: object, model_repo: str) -> List[Tuple[str, str]]:
    """Return browser links for manual download UI."""
    from bundled.constants import DEMUCS_ARCH_TYPE, MDX_ARCH_TYPE, VR_ARCH_TYPE

    links: List[Tuple[str, str]] = []
    if arch_type == VR_ARCH_TYPE:
        for url, _ in resolve_vr_jobs(model, model_repo):
            links.append(("Open Link to Model", url))
    elif arch_type == MDX_ARCH_TYPE:
        weight_jobs = [
            job for job in resolve_mdx_jobs(model, model_repo) if not job[1].endswith(".yaml")
        ]
        for url, _ in weight_jobs:
            links.append(("Open Link to Model", url))
    elif arch_type == DEMUCS_ARCH_TYPE and isinstance(model, dict):
        jobs = resolve_demucs_jobs(model, "")
        multi = len(jobs) > 1
        for number, (url, _) in enumerate(jobs, start=1):
            suffix = f" {number}" if multi else ""
            links.append((f"Open Link to Model{suffix}", url))
    return links
