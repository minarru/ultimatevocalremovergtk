"""Unified runtime display names for VR, MDX-Net, and Demucs models."""

from __future__ import annotations

import json
import os
import re
from typing import Any, TYPE_CHECKING, Dict, Iterable, List, Mapping, Optional, Tuple

from bundled.constants import (
    DEMUCS_ARCH_TYPE,
    ENSEMBLE_PARTITION,
    MDX_ARCH_TYPE,
    VR_ARCH_TYPE,
)

from . import paths

if TYPE_CHECKING:
    from .model_data import ModelRepository

_CHECKPOINT_EXTENSIONS = (".ckpt", ".pth", ".onnx")
_MAPPER_EXTENSIONS = ("", ".ckpt", ".pth", ".onnx", ".yaml", ".th", ".gz")

_MDX_CATALOG_SOURCE_KEYS = (
    "mdx_download_list",
    "mdx23c_download_list",
    "roformer_download_list",
    "scnet_download_list",
    "bandit_download_list",
    "mdx_download_vip_list",
    "mdx23c_download_vip_list",
    "roformer_download_vip_list",
)

_VR_CATALOG_SOURCE_KEYS = ("vr_download_list",)

_DEMUCS_CATALOG_SOURCE_KEYS = ("demucs_download_list",)

_CATALOGUE_LABEL_PREFIXES = (
    "Roformer Model: ",
    "SCnet: ",
    "Bandit Plus: ",
    "Bandit v2: ",
    "Bandit: ",
    "MDX23C Model VIP: ",
    "MDX23C Model: ",
    "MDX23C: ",
    "MDX-Net Model VIP: ",
    "MDX-Net Model: ",
    "MDX-Net: ",
)

_VR_CATALOGUE_PREFIXES = (
    "VR Arch Single Model ",
    "VR Arch ",
)

_DEMUCS_CATALOGUE_RE = re.compile(r"^Demucs (v\d+): (.+)$", re.IGNORECASE)


def _is_checkpoint_name(filename: str) -> bool:
    return filename.lower().endswith(_CHECKPOINT_EXTENSIONS)


def sanitize_catalogue_label(label: str) -> str:
    """Strip Download Center category prefixes from a catalogue entry label."""
    text = str(label).strip()
    for prefix in _CATALOGUE_LABEL_PREFIXES:
        if text.startswith(prefix):
            text = text[len(prefix) :].strip()
    if text.endswith(".ckpt"):
        text = text[: -len(".ckpt")].strip()
    return text


def sanitize_vr_catalogue_label(label: str) -> str:
    """Convert an upstream VR catalogue key to a runtime display label."""
    text = str(label).strip()
    for prefix in _VR_CATALOGUE_PREFIXES:
        if text.startswith(prefix):
            text = text[len(prefix) :].strip()
            break
    return text


def sanitize_demucs_catalogue_label(label: str) -> str:
    """Convert ``Demucs v4: htdemucs`` to ``v4 | htdemucs``."""
    text = str(label).strip()
    match = _DEMUCS_CATALOGUE_RE.match(text)
    if match:
        return f"{match.group(1)} | {match.group(2)}"
    return text


def lookup_mapper_display(basename: str, name_mapper: Optional[Dict[str, str]]) -> Optional[str]:
    """Map an on-disk basename to a display label using a name mapper."""
    if not basename or not name_mapper:
        return None
    for ext in _MAPPER_EXTENSIONS:
        key = f"{basename}{ext}" if ext else basename
        if key in name_mapper:
            return name_mapper[key]
    for file_key, display in name_mapper.items():
        if os.path.splitext(file_key)[0] == basename:
            return display
    for file_key, display in name_mapper.items():
        if basename in file_key:
            return display
    return None


def resolve_mapper_basename(label: str, name_mapper: Optional[Dict[str, str]]) -> Optional[str]:
    """Resolve a display label to an on-disk basename using a name mapper."""
    if not label or not name_mapper:
        return None
    for file_key, display_name in name_mapper.items():
        if label == display_name:
            return os.path.splitext(file_key)[0]
    for file_key, display_name in name_mapper.items():
        if os.path.splitext(file_key)[0] == label:
            return label
    for file_key, display_name in name_mapper.items():
        if label in display_name:
            return os.path.splitext(file_key)[0]
    return None


def build_checkpoint_display_index(
    catalogues: Iterable[Mapping[str, Any]],
) -> Dict[str, str]:
    """Map checkpoint basename (no extension) to a friendly display label."""
    index: Dict[str, str] = {}
    for catalogue in catalogues:
        if not isinstance(catalogue, dict):
            continue
        for selectable, model in catalogue.items():
            if not isinstance(model, dict):
                continue
            display_name = sanitize_catalogue_label(selectable)
            for filename in model:
                if _is_checkpoint_name(filename):
                    index[os.path.splitext(filename)[0]] = display_name
    return index


def build_vr_display_index(catalogues: Iterable[Mapping[str, Any]]) -> Dict[str, str]:
    """Map VR ``.pth`` basename to a sanitized runtime label."""
    index: Dict[str, str] = {}
    for catalogue in catalogues:
        if not isinstance(catalogue, dict):
            continue
        for selectable, model in catalogue.items():
            display_name = sanitize_vr_catalogue_label(selectable)
            if isinstance(model, str) and _is_checkpoint_name(model):
                index[os.path.splitext(model)[0]] = display_name
            elif isinstance(model, dict):
                for filename in model:
                    if _is_checkpoint_name(filename):
                        index[os.path.splitext(filename)[0]] = display_name
    return index


def build_demucs_display_index(
    catalogues: Iterable[Mapping[str, Any]],
) -> Dict[str, str]:
    """Map Demucs yaml/checkpoint stem to a runtime display label."""
    index: Dict[str, str] = {}
    for catalogue in catalogues:
        if not isinstance(catalogue, dict):
            continue
        for selectable, model in catalogue.items():
            if not isinstance(model, dict):
                continue
            display_name = sanitize_demucs_catalogue_label(selectable)
            yaml_keys = [name for name in model if name.endswith(".yaml")]
            for yaml_name in yaml_keys:
                index[os.path.splitext(yaml_name)[0]] = display_name
            if not yaml_keys:
                for filename in model:
                    if filename.endswith((".th", ".ckpt", ".gz")):
                        index[os.path.splitext(filename)[0]] = display_name
    return index


def _load_manual_download_cache() -> Dict:
    try:
        with open(paths.DOWNLOAD_MODEL_CACHE_PATH, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
        return payload if isinstance(payload, dict) else {}
    except (OSError, ValueError, TypeError):
        return {}


def _catalogues_from_source(source: Dict, keys: Tuple[str, ...]) -> List[Dict[str, object]]:
    catalogues: List[Dict[str, object]] = []
    for key in keys:
        catalogue = source.get(key)
        if isinstance(catalogue, dict):
            catalogues.append(catalogue)
    return catalogues


def load_mdx_catalog_display_index() -> Dict[str, str]:
    """Build MDX checkpoint-basename→display-name index from download catalogues."""
    mdx_catalogues: List[Dict[str, object]] = []
    mdx_catalogues.extend(_catalogues_from_source(_load_manual_download_cache(), _MDX_CATALOG_SOURCE_KEYS))
    from .politrees_catalog import load_politrees_links

    politrees = load_politrees_links()
    if isinstance(politrees, dict):
        mdx_catalogues.extend(_catalogues_from_source(politrees, _MDX_CATALOG_SOURCE_KEYS))
    return build_checkpoint_display_index(mdx_catalogues)


def load_vr_catalog_display_index() -> Dict[str, str]:
    """Build VR basename→runtime-display index from download catalogues."""
    vr_catalogues: List[Dict[str, object]] = []
    vr_catalogues.extend(_catalogues_from_source(_load_manual_download_cache(), _VR_CATALOG_SOURCE_KEYS))
    from .politrees_catalog import load_politrees_links

    politrees = load_politrees_links()
    if isinstance(politrees, dict):
        vr_catalogues.extend(_catalogues_from_source(politrees, _VR_CATALOG_SOURCE_KEYS))
    return build_vr_display_index(vr_catalogues)


def load_demucs_catalog_display_index() -> Dict[str, str]:
    """Build Demucs stem→runtime-display index from download catalogues."""
    demucs_catalogues: List[Dict[str, object]] = []
    demucs_catalogues.extend(
        _catalogues_from_source(_load_manual_download_cache(), _DEMUCS_CATALOG_SOURCE_KEYS)
    )
    from .politrees_catalog import load_politrees_links

    politrees = load_politrees_links()
    if isinstance(politrees, dict):
        demucs_catalogues.extend(
            _catalogues_from_source(politrees, _DEMUCS_CATALOG_SOURCE_KEYS)
        )
    return build_demucs_display_index(demucs_catalogues)


def display_name_for_basename(
    basename: str,
    name_mapper: Optional[Dict[str, str]] = None,
    *,
    catalogue_index: Optional[Dict[str, str]] = None,
) -> str:
    """Return the friendly MDX model label for an on-disk basename.

    Catalogue labels win when present so community/Politrees names stay as
    readable in method pickers as they are in Download Center. The name mapper
    covers custom installs and reverse-resolve of older saved aliases.
    """
    if not basename:
        return basename
    lookup = catalogue_index if catalogue_index is not None else load_mdx_catalog_display_index()
    if basename in lookup:
        return lookup[basename]
    mapped = lookup_mapper_display(basename, name_mapper)
    if mapped:
        return mapped
    return basename


def resolve_mdx_model_basename(
    model_name: str,
    name_mapper: Optional[Dict[str, str]] = None,
    *,
    catalogue_index: Optional[Dict[str, str]] = None,
) -> str:
    """Resolve a dropdown label (or basename) to the on-disk checkpoint basename."""
    if not model_name:
        return model_name
    mapped = resolve_mapper_basename(model_name, name_mapper)
    if mapped:
        return mapped
    lookup = catalogue_index if catalogue_index is not None else load_mdx_catalog_display_index()
    for basename, display_name in lookup.items():
        if model_name == display_name:
            return basename
    return model_name


def resolve_vr_model_basename(
    model_name: str,
    *,
    catalogue_index: Optional[Dict[str, str]] = None,
) -> str:
    """Resolve a VR display label or catalogue key to a ``.pth`` basename."""
    if not model_name:
        return model_name
    lookup = catalogue_index if catalogue_index is not None else load_vr_catalog_display_index()
    if os.path.isfile(os.path.join(paths.VR_MODELS_DIR, f"{model_name}.pth")):
        return model_name
    sanitized_input = sanitize_vr_catalogue_label(model_name)
    for basename, display in lookup.items():
        if model_name == display or sanitized_input == display:
            return basename
    if ": " in model_name:
        candidate = model_name.rsplit(": ", 1)[-1]
        if os.path.isfile(os.path.join(paths.VR_MODELS_DIR, f"{candidate}.pth")):
            return candidate
    return model_name


def resolve_demucs_model_basename(
    model_name: str,
    name_mapper: Optional[Dict[str, str]] = None,
    *,
    catalogue_index: Optional[Dict[str, str]] = None,
) -> str:
    """Resolve a Demucs display label to an on-disk model stem."""
    if not model_name:
        return model_name
    mapped = resolve_mapper_basename(model_name, name_mapper)
    if mapped:
        return mapped
    lookup = catalogue_index if catalogue_index is not None else load_demucs_catalog_display_index()
    for stem, display in lookup.items():
        if model_name == display:
            return stem
    return model_name


def display_name_for_model(
    arch: str,
    name: str,
    repo: "ModelRepository",
) -> str:
    """Return a friendly runtime label for any architecture."""
    if not name:
        return name
    if arch in (VR_ARCH_TYPE,):
        lookup = repo.vr_catalogue_display_index()
        if name in lookup:
            return lookup[name]
        basename = resolve_vr_model_basename(name, catalogue_index=lookup)
        if basename in lookup:
            return lookup[basename]
        sanitized = sanitize_vr_catalogue_label(name)
        return sanitized if sanitized != name else name
    if arch in (MDX_ARCH_TYPE,):
        basename = resolve_mdx_model_basename(
            name,
            repo.mdx_name_select_MAPPER,
            catalogue_index=repo.mdx_catalogue_display_index(),
        )
        return display_name_for_basename(
            basename,
            repo.mdx_name_select_MAPPER,
            catalogue_index=repo.mdx_catalogue_display_index(),
        )
    if arch in (DEMUCS_ARCH_TYPE,):
        lookup = repo.demucs_catalogue_display_index()
        if name in lookup:
            return lookup[name]
        mapped = lookup_mapper_display(name, repo.demucs_name_select_MAPPER)
        if mapped:
            return mapped
        basename = resolve_demucs_model_basename(
            name,
            repo.demucs_name_select_MAPPER,
            catalogue_index=lookup,
        )
        return lookup.get(basename) or lookup_mapper_display(
            basename, repo.demucs_name_select_MAPPER
        ) or name
    return name


def resolve_model_basename(
    arch: str,
    name: str,
    repo: "ModelRepository",
) -> str:
    """Resolve a friendly label to an on-disk basename/stem."""
    if not name:
        return name
    if arch in (VR_ARCH_TYPE,):
        return resolve_vr_model_basename(name, catalogue_index=repo.vr_catalogue_display_index())
    if arch in (MDX_ARCH_TYPE,):
        return resolve_mdx_model_basename(
            name,
            repo.mdx_name_select_MAPPER,
            catalogue_index=repo.mdx_catalogue_display_index(),
        )
    if arch in (DEMUCS_ARCH_TYPE,):
        return resolve_demucs_model_basename(
            name,
            repo.demucs_name_select_MAPPER,
            catalogue_index=repo.demucs_catalogue_display_index(),
        )
    return name


def parse_model_tag(tag: str) -> Tuple[str, str]:
    """Split ``'<arch>: <model>'`` on the first ``': '`` only."""
    if not tag or ENSEMBLE_PARTITION not in tag:
        return "", tag
    arch, _, model_name = tag.partition(ENSEMBLE_PARTITION)
    return arch, model_name


def format_tag_subtitle(tag: str) -> str:
    """Return the architecture portion of a model tag."""
    arch, _ = parse_model_tag(tag)
    return arch


def format_tag_title(tag: str, repo: "ModelRepository") -> str:
    """Return the friendly model label for a full arch tag."""
    arch, model_name = parse_model_tag(tag)
    if not arch:
        return model_name
    return display_name_for_model(arch, model_name, repo)


def map_basenames_to_display(
    basenames: Iterable[str],
    arch: str,
    repo: "ModelRepository",
) -> List[str]:
    """Map on-disk basenames to runtime display labels for a method dropdown."""
    names = list(basenames)
    if arch in (VR_ARCH_TYPE,):
        lookup = repo.vr_catalogue_display_index()
        return [lookup.get(name, name) for name in names]
    if arch in (MDX_ARCH_TYPE,):
        catalogue = repo.mdx_catalogue_display_index()
        return [
            display_name_for_basename(name, repo.mdx_name_select_MAPPER, catalogue_index=catalogue)
            for name in names
        ]
    if arch in (DEMUCS_ARCH_TYPE,):
        catalogue = repo.demucs_catalogue_display_index()
        return [
            catalogue.get(name)
            or lookup_mapper_display(name, repo.demucs_name_select_MAPPER)
            or name
            for name in names
        ]
    return names
