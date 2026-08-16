"""MDX-C catalogue lookup and hash registration helpers."""

from __future__ import annotations

import hashlib
import json
import os
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple

from bundled.constants import CKPT

from . import paths
from .mdx_config_fetch import _ALLOW_NETWORK, ensure_mdx_c_config
from .model_display import (
    _is_checkpoint_name,
    build_checkpoint_display_index,
    display_name_for_basename,
    load_mdx_catalog_display_index,
    resolve_mdx_model_basename,
    sanitize_catalogue_label,
)

_MDX_CATALOG_SOURCE_KEYS = (
    "mdx_download_list",
    "mdx23_download_list",
    "mdx23c_download_list",
    "roformer_download_list",
    "scnet_download_list",
    "bandit_download_list",
    "mdx_download_vip_list",
    "mdx23_download_vip_list",
    "mdx23c_download_vip_list",
    "roformer_download_vip_list",
)


def compute_checkpoint_hash(model_path: str) -> Optional[str]:
    """Return the UVR-style MD5 fingerprint for a checkpoint file."""
    if not os.path.isfile(model_path):
        return None
    try:
        with open(model_path, "rb") as handle:
            handle.seek(-10000 * 1024, 2)
            return hashlib.md5(handle.read()).hexdigest()
    except Exception:
        with open(model_path, "rb") as handle:
            return hashlib.md5(handle.read()).hexdigest()


def infer_mdx_c_architecture(yaml_name: str) -> Tuple[str, bool]:
    """Return ``(architecture label, is_roformer)`` for a bundled MDX-C yaml."""
    if not yaml_name:
        return "", False
    config_path = os.path.join(paths.MDX_C_CONFIG_PATH, yaml_name)
    if not os.path.isfile(config_path):
        return "", False
    try:
        from ml_collections import ConfigDict

        from .model_data import load_mdx_c_config

        config = ConfigDict(load_mdx_c_config(config_path))
    except Exception:
        return "", False

    if getattr(config, "cls", None) == "Bandit":
        return "Bandit", True

    model = getattr(config, "model", None)
    if model is None:
        return "MDX23C", False
    if "band_specs" in model:
        return "Bandit", True
    if "band_SR" in model or "sources" in model:
        if any(str(key).startswith("tran_") for key in model):
            return "SCNet Tran", True
        if "masked" in yaml_name.lower():
            return "SCNet Masked", True
        return "SCNet", True
    if "num_bands" in model:
        return "Mel-Band Roformer", True
    if "freqs_per_bands" in model:
        return "BS Roformer", True
    return "MDX23C", False


def params_from_config_yaml(yaml_name: str) -> Optional[Dict[str, object]]:
    """Build model-data params for a config yaml basename."""
    if not yaml_name or not yaml_name.endswith(".yaml"):
        return None
    arch, is_roformer = infer_mdx_c_architecture(yaml_name)
    if not arch:
        return None
    params: Dict[str, object] = {
        "config_yaml": yaml_name,
        "is_roformer": is_roformer,
    }
    if arch:
        params["model_type"] = arch
    return params


_CHECKPOINT_EXTENSIONS = (".ckpt", ".pth", ".onnx")


def _mapper_key_for_checkpoint(checkpoint_path: str) -> str:
    basename = os.path.basename(checkpoint_path)
    if basename.lower().endswith(_CHECKPOINT_EXTENSIONS):
        return basename
    for ext in _CHECKPOINT_EXTENSIONS:
        candidate = f"{basename}{ext}"
        if os.path.isfile(os.path.join(paths.MDX_MODELS_DIR, candidate)):
            return candidate
    return basename


def register_mdx_display_name(
    checkpoint_path: str,
    display_name: str,
    *,
    write: bool = True,
) -> bool:
    """Persist a friendly display label for a locally-registered checkpoint.

    Reads the merged mapper (upstream mirror + local overlay) to decide whether
    the name is already known, but writes only to the overlay — the mirror has
    to stay a verbatim copy of upstream so deletions there propagate.
    """
    if not display_name:
        return False
    from .name_mapper import add_local_name, load_name_mapper

    mapper_key = _mapper_key_for_checkpoint(checkpoint_path)
    mapper_path = paths.MDX_MODEL_NAME_SELECT
    existing: Dict[str, str] = load_name_mapper(mapper_path)

    if mapper_key in existing or display_name in existing.values():
        return False

    if not write:
        return True

    add_local_name(mapper_path, mapper_key, display_name)
    return True


def _register_display_name_for_checkpoint(
    checkpoint_path: str,
    *,
    display_index: Optional[Dict[str, str]] = None,
) -> bool:
    basename = os.path.splitext(os.path.basename(checkpoint_path))[0]
    lookup = display_index if display_index is not None else load_mdx_catalog_display_index()
    display_name = lookup.get(basename)
    if not display_name:
        return False
    return register_mdx_display_name(checkpoint_path, display_name)


def _yaml_name_from_ref(ref: object) -> Optional[str]:
    if isinstance(ref, str) and ref.endswith(".yaml") and "/" not in ref and "\\" not in ref:
        return ref
    return None


def build_checkpoint_yaml_index(
    catalogues: Iterable[Mapping[str, Any]],
) -> Dict[str, str]:
    """Map checkpoint basename to yaml basename from download catalogues."""
    index: Dict[str, str] = {}
    for catalogue in catalogues:
        if not isinstance(catalogue, dict):
            continue
        for model in catalogue.values():
            if not isinstance(model, dict):
                continue
            yaml_keys = [name for name in model if name.endswith(".yaml")]
            checkpoint_names = [name for name in model if _is_checkpoint_name(name)]
            if not checkpoint_names:
                continue
            default_yaml = yaml_keys[0] if yaml_keys else None
            for checkpoint_name in checkpoint_names:
                ref = model.get(checkpoint_name)
                yaml_ref = _yaml_name_from_ref(ref)
                if yaml_ref:
                    index[checkpoint_name] = yaml_ref
                elif default_yaml:
                    index[checkpoint_name] = default_yaml
    return index


def _load_manual_download_cache() -> Dict:
    try:
        with open(paths.DOWNLOAD_MODEL_CACHE_PATH, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
        return payload if isinstance(payload, dict) else {}
    except (OSError, ValueError, TypeError):
        return {}


def _catalogues_from_source(source: Dict) -> List[Dict[str, object]]:
    catalogues: List[Dict[str, object]] = []
    for key in _MDX_CATALOG_SOURCE_KEYS:
        catalogue = source.get(key)
        if isinstance(catalogue, dict):
            catalogues.append(catalogue)
    return catalogues


def load_mdx_catalog_index() -> Dict[str, str]:
    """Build checkpoint→yaml index from bundled and cached download catalogues."""
    catalogues: List[Dict[str, object]] = []
    catalogues.extend(_catalogues_from_source(_load_manual_download_cache()))

    from .politrees_catalog import load_politrees_links

    politrees = load_politrees_links(allow_network=False)
    if isinstance(politrees, dict):
        catalogues.extend(_catalogues_from_source(politrees))

    return build_checkpoint_yaml_index(catalogues)


def yaml_for_checkpoint(filename: str, index: Optional[Dict[str, str]] = None) -> Optional[str]:
    if not filename:
        return None
    lookup = index if index is not None else load_mdx_catalog_index()
    return lookup.get(os.path.basename(filename))


def _hash_json_path(model_hash: str) -> str:
    return os.path.join(paths.MDX_HASH_DIR, f"{model_hash}.json")


def register_mdx_c_checkpoint(
    checkpoint_path: str,
    yaml_name: str,
    *,
    model_hash: Optional[str] = None,
    write: bool = True,
) -> Optional[Dict[str, object]]:
    """Register MDX-C params for a checkpoint; write ``<hash>.json`` if missing."""
    if not _is_checkpoint_name(checkpoint_path):
        return None
    params = params_from_config_yaml(yaml_name)
    if not params:
        return None

    if not ensure_mdx_c_config(yaml_name):
        return None

    resolved_hash = model_hash or compute_checkpoint_hash(checkpoint_path)
    if not resolved_hash:
        return None

    json_path = _hash_json_path(resolved_hash)
    if os.path.isfile(json_path):
        try:
            with open(json_path, "r", encoding="utf-8") as handle:
                existing = json.load(handle)
            if isinstance(existing, dict):
                return existing
        except (OSError, ValueError, TypeError):
            pass

    # Network-forbidden planning is also non-mutating: skip writing the hash
    # registry whenever network access is disallowed (even if write=True).
    if write and _ALLOW_NETWORK.get():
        os.makedirs(paths.MDX_HASH_DIR, exist_ok=True)
        with open(json_path, "w", encoding="utf-8") as handle:
            handle.write(json.dumps(params, indent=4))

    return params


def try_register_from_catalog(
    checkpoint_path: str,
    model_hash: Optional[str] = None,
    *,
    index: Optional[Dict[str, str]] = None,
) -> Optional[Dict[str, object]]:
    """Resolve MDX-C params from the download catalogue and persist if needed."""
    yaml_name = yaml_for_checkpoint(checkpoint_path, index=index)
    if not yaml_name:
        return None
    params = register_mdx_c_checkpoint(
        checkpoint_path,
        yaml_name,
        model_hash=model_hash,
        write=True,
    )
    if params:
        _register_display_name_for_checkpoint(checkpoint_path)
    return params


def pair_checkpoint_yaml_jobs(jobs: List[Tuple[str, str]]) -> List[Tuple[str, str]]:
    """Return ``[(checkpoint_path, yaml_basename), ...]`` from a download job batch."""
    yaml_jobs = [
        os.path.basename(save_path)
        for _, save_path in jobs
        if save_path.startswith(paths.MDX_C_CONFIG_PATH) and save_path.endswith(".yaml")
    ]
    if not yaml_jobs:
        return []

    yaml_name = yaml_jobs[0]
    pairs: List[Tuple[str, str]] = []
    for _, save_path in jobs:
        if not save_path.startswith(paths.MDX_MODELS_DIR):
            continue
        if not _is_checkpoint_name(save_path):
            continue
        if os.path.isfile(save_path):
            pairs.append((save_path, yaml_name))
    return pairs


def register_mdx_c_from_download_jobs(
    jobs: List[Tuple[str, str]],
) -> bool:
    """Auto-register MDX-C checkpoints downloaded alongside a config yaml."""
    registered = False
    display_index = load_mdx_catalog_display_index()
    for checkpoint_path, yaml_name in pair_checkpoint_yaml_jobs(jobs):
        if register_mdx_c_checkpoint(checkpoint_path, yaml_name):
            registered = True
        if _register_display_name_for_checkpoint(checkpoint_path, display_index=display_index):
            registered = True
    return registered
