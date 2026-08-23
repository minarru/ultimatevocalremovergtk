"""Load and merge Politrees UVR_resources download catalogues."""

from __future__ import annotations

import json
import os
import threading
import time
from typing import Any, Dict, List, Mapping, Optional, Tuple

from bundled.constants import POLITREES_MODEL_LINKS_URL

from . import paths
from .debug_log import debug
from .mdx_config_fetch import _urlopen, fetch_mdx_config_url

_POLITREES_CACHE_TTL_SECONDS = 24 * 60 * 60

_source: Any = None


def _politrees_cache_path() -> str:
    return paths.POLITREES_CACHE_FILE


def _politrees_source() -> Any:
    """Module-level source store; tests patch ``_politrees_cache_path`` / ``_urlopen``."""
    global _source
    from .catalogue_types import SourceId
    from .remote_catalog_cache import RemoteJsonSource

    if _source is None:
        _source = RemoteJsonSource(
            source_id=SourceId.POLITREES,
            url=POLITREES_MODEL_LINKS_URL,
            cache_filename="politrees_model_links.json",
            cache_path=lambda: _politrees_cache_path(),
            ttl_seconds=_POLITREES_CACHE_TTL_SECONDS,
            opener=lambda target: _urlopen(target),
            enabled=politrees_enabled,
        )
    return _source

_POLITREES_MDX_SOURCE_KEYS = (
    "mdx_download_list",
    "mdx23_download_list",
    "mdx23c_download_list",
    "roformer_download_list",
    "scnet_download_list",
    "bandit_download_list",
)

_cached_links: Optional[Dict] = None
_cached_weight_index: Optional[Dict[str, str]] = None
_cached_loaded_at: float = 0.0
_refresh_lock = threading.Lock()
_refresh_in_flight = False


def politrees_enabled() -> bool:
    return os.environ.get("UVR_DISABLE_POLITREES", "").strip().lower() not in (
        "1",
        "true",
        "yes",
    )


def is_remote_ref(value: object) -> bool:
    return isinstance(value, str) and value.startswith(("http://", "https://"))


def clear_politrees_cache() -> None:
    global _cached_links, _cached_weight_index, _cached_loaded_at, _source
    _cached_links = None
    _cached_weight_index = None
    _cached_loaded_at = 0.0
    if _source is not None:
        _source.reset()
        _source = None
    # Local import: core.model_display imports this module for _display_base.
    from .model_display import clear_display_cache

    clear_display_cache()


def _read_disk_cache() -> Optional[Dict]:
    try:
        with open(_politrees_cache_path(), "r", encoding="utf-8") as handle:
            payload = json.load(handle)
        if isinstance(payload, dict) and isinstance(payload.get("data"), dict):
            return payload["data"]
    except (OSError, ValueError, TypeError):
        pass
    return None


def _read_disk_cache_entry() -> Optional[Tuple[Dict, float]]:
    """Return ``(data, fetched_at)`` from the on-disk cache, or ``None``."""
    try:
        with open(_politrees_cache_path(), "r", encoding="utf-8") as handle:
            payload = json.load(handle)
        if not isinstance(payload, dict) or not isinstance(payload.get("data"), dict):
            return None
        fetched_at = payload.get("fetched_at")
        if not isinstance(fetched_at, (int, float)):
            return None
        return payload["data"], float(fetched_at)
    except (OSError, ValueError, TypeError):
        return None


def _start_background_refresh() -> None:
    """Refresh the catalogue off the main loop; at most one in flight."""
    global _refresh_in_flight
    with _refresh_lock:
        if _refresh_in_flight:
            return
        _refresh_in_flight = True

    def run() -> None:
        global _refresh_in_flight
        try:
            load_politrees_links(force=True)
        except Exception as exc:  # noqa: BLE001 - background best-effort
            debug("download", f"politrees background refresh failed err={exc}")
        except BaseException:
            # Test network guard is a BaseException; never kill the daemon thread.
            debug("download", "politrees background refresh aborted")
        finally:
            with _refresh_lock:
                _refresh_in_flight = False

    threading.Thread(target=run, name="uvr-politrees-refresh", daemon=True).start()


def _write_disk_cache(data: Dict) -> None:
    try:
        cache_path = _politrees_cache_path()
        os.makedirs(os.path.dirname(cache_path) or ".", exist_ok=True)
        with open(cache_path, "w", encoding="utf-8") as handle:
            json.dump({"fetched_at": time.time(), "data": data}, handle)
    except OSError as exc:
        debug("download", f"politrees cache write failed err={exc}")


def _apply_politrees_content(content: Any) -> Optional[Dict]:
    global _cached_links, _cached_weight_index, _cached_loaded_at
    data = dict(content.payload)
    previous = _cached_links
    _cached_links = data
    _cached_weight_index = None
    _cached_loaded_at = float(content.fetched_at)
    if data != previous:
        from .model_display import clear_display_cache

        clear_display_cache()
    return data


def load_politrees_links(
    *, force: bool = False, allow_network: bool = True
) -> Optional[Dict]:
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

    from .access_policy import AccessPolicy, current_access_policy
    from .catalogue_types import RefreshMode

    source = _politrees_source()
    policy = current_access_policy()
    if not force:
        if _cached_links is None:
            source.reset()
        offline = AccessPolicy(allow_network=False, allow_metadata_writes=False)
        state = source.load(mode=RefreshMode.OFFLINE, policy=offline)
        content = state.content
        if content is not None:
            _apply_politrees_content(content)
            if allow_network and source._stale(content.fetched_at, source._now()):
                _start_background_refresh()
            return _cached_links
        if not allow_network:
            return None

    if not allow_network:
        return None

    net_policy = AccessPolicy(
        allow_network=True,
        allow_metadata_writes=policy.allow_metadata_writes,
        allow_cache_writes=policy.allow_cache_writes,
    )
    state = source.load(mode=RefreshMode.FORCE, policy=net_policy)
    if state.content is not None:
        return _apply_politrees_content(state.content)
    return _cached_links


def merge_supplemental_list(
    base: Mapping[str, Any], extra: Mapping[str, Any]
) -> Dict[str, Any]:
    """Add catalogue entries present in ``extra`` but not in ``base``."""
    merged = dict(base)
    for key, value in extra.items():
        if key not in merged:
            merged[key] = value
    return merged


def merge_politrees_catalogues(
    vr: Mapping[str, Any],
    mdx: Mapping[str, Any],
    demucs: Mapping[str, Any],
    politrees: Optional[Dict],
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    if not politrees:
        return dict(vr), dict(mdx), dict(demucs)

    vr = merge_supplemental_list(vr, politrees.get("vr_download_list", {}))
    demucs = merge_supplemental_list(demucs, politrees.get("demucs_download_list", {}))

    for key in _POLITREES_MDX_SOURCE_KEYS:
        mdx = merge_supplemental_list(mdx, politrees.get(key, {}))

    return dict(vr), dict(mdx), dict(demucs)


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
    filename = str(model)
    return [(f"{model_repo}{filename}", os.path.join(paths.VR_MODELS_DIR, filename))]


def resolve_mdx_jobs(
    model: object, model_repo: str, *, fetch_config: bool = True
) -> List[Tuple[str, str]]:
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
                if fetch_config:
                    from .mdx_config_fetch import ensure_mdx_c_config

                    ensure_mdx_c_config(ref)
        return jobs
    filename = str(model)
    return [(f"{model_repo}{filename}", os.path.join(paths.MDX_MODELS_DIR, filename))]


def apollo_checkpoint_filename(model: object) -> str:
    """Return the checkpoint filename for an Apollo catalogue entry."""
    if isinstance(model, dict):
        for name in model:
            if not name.endswith(".yaml"):
                return name
        return next(iter(model), "")
    return str(model)


def resolve_apollo_jobs(model: object) -> List[Tuple[str, str]]:
    """Return download jobs for an Apollo entry.

    Checkpoints land in ``APOLLO_MODELS_DIR`` and their yaml in
    ``APOLLO_CONFIG_PATH``, matching where :mod:`core.apollo` looks them up.
    Unlike the MDX path there is no upstream repo fallback: Apollo entries are
    fork-curated and always carry absolute URLs.
    """
    if not isinstance(model, dict):
        return []

    jobs: List[Tuple[str, str]] = []
    for name, ref in model.items():
        if not is_remote_ref(ref):
            continue
        base = os.path.basename(name)
        if base != name or ".." in base:
            continue
        if base.endswith(".yaml"):
            jobs.append((ref, os.path.join(paths.APOLLO_CONFIG_PATH, base)))
        else:
            jobs.append((ref, os.path.join(paths.APOLLO_MODELS_DIR, base)))
    return jobs


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
        for url, _ in resolve_demucs_jobs(model, ""):
            links.append(("Open Link to Model", url))
    return links
