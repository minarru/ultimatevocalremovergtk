"""Unified runtime display names for VR, MDX-Net, and Demucs models."""

from __future__ import annotations

import functools
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
    from .catalog_sources import MergedCatalogues
    from .model_repository import ModelRepository

_CHECKPOINT_EXTENSIONS = (".ckpt", ".pth", ".onnx")
_MAPPER_EXTENSIONS = ("", ".ckpt", ".pth", ".onnx", ".yaml", ".th", ".gz")

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

_VR_CATALOG_SOURCE_KEYS = ("vr_download_list",)

_DEMUCS_CATALOG_SOURCE_KEYS = ("demucs_download_list",)

_CATALOGUE_LABEL_PREFIXES = (
    "Roformer Model: ",
    "SCnet: ",
    "Bandit Plus: ",
    "Bandit v2: ",
    "Bandit: ",
    "MDX23C Model VIP: ",
    "MDX23 Model VIP: ",
    "MDX23C Model: ",
    "MDX23 Model: ",
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


def _flatten_source(source: Dict, keys: Tuple[str, ...]) -> Dict[str, Any]:
    """Flatten several catalogue keys of one source into a single dict."""
    flat: Dict[str, Any] = {}
    for catalogue in _catalogues_from_source(source, keys):
        flat.update(catalogue)
    return flat


def _display_base(keys: Tuple[str, ...], *, allow_network: bool) -> Dict[str, Any]:
    """Flatten one architecture's catalogues from the cache **and** Politrees.

    Politrees is read here as well as inside the merge because the merge omits
    the ``*_vip_list`` keys — the Download Center must not offer code-gated
    models. Naming a checkpoint that is already on disk is not gated, though,
    so the display index keeps reading them, as it always has.
    """
    from .politrees_catalog import load_politrees_links

    flat = _flatten_source(_load_manual_download_cache(), keys)
    politrees = load_politrees_links(allow_network=allow_network)
    if isinstance(politrees, dict):
        for label, model in _flatten_source(politrees, keys).items():
            flat.setdefault(label, model)
    return flat


#: Bumped by :func:`clear_display_cache` so an in-flight ``lru_cache`` miss
#: that finishes *after* a clear cannot re-pin a stale merge under the live key.
_display_generation: int = 0
_format_tag_title_cache: dict[tuple[Any, ...], str] = {}


@functools.lru_cache(maxsize=8)
def _merged_for_display_at(generation: int, allow_network: bool):
    """Cached merge keyed by :data:`_display_generation`.

    Callers should use :func:`_merged_for_display` so they always read the
    current generation. Keying on the generation means a mid-flight clear
    (bump) leaves the finishing miss stored under the old key, which the next
    lookup will not see.
    """
    from .catalog_sources import merged_catalogues

    return merged_catalogues(
        vr=_display_base(_VR_CATALOG_SOURCE_KEYS, allow_network=allow_network),
        mdx=_display_base(_MDX_CATALOG_SOURCE_KEYS, allow_network=allow_network),
        demucs=_display_base(_DEMUCS_CATALOG_SOURCE_KEYS, allow_network=allow_network),
        allow_network=allow_network,
    )


def _merged_for_display(*, allow_network: bool = True):
    """Merged catalogues built from the upstream cache plus every supplement.

    Reads the same merge the Download Center does, which is the whole point:
    two separate merge paths are what left mvsepless and extras models showing
    as raw basenames here while the Download Center named them correctly.

    Memoized: this walks every catalogue source and re-reads
    ``model_manual_download.json``, and ``format_tag_title`` calls it once per
    dropdown entry. Invalidate through :func:`clear_display_cache` whenever a
    source changes (politrees refresh, hash-mapper reload).
    """
    return _merged_for_display_at(_display_generation, allow_network)


def clear_display_cache() -> None:
    """Drop the memoized catalogue merge (call when any source changes).

    Bumps :data:`_display_generation` so a concurrent miss that started under
    the previous generation cannot re-publish its result as the live entry.
    """
    global _display_generation
    _display_generation += 1
    _merged_for_display_at.cache_clear()
    _format_tag_title_cache.clear()
    from .catalog_sources import invalidate_catalogue_merge

    invalidate_catalogue_merge()


def _index_from_meta(merged: "MergedCatalogues", arch: str) -> Dict[str, str]:
    """Map every file basename of one architecture to its display name.

    Iterates ``merged.meta``, which is built before dedupe, rather than the
    deduped catalogue: a duplicate label dropped from the Download Center list
    still names a checkpoint that has to resolve here.

    Every file is indexed, not just the primary checkpoint, so Demucs resolves
    on its ``.yaml`` stem the way ``build_demucs_display_index`` did.
    ``setdefault`` preserves upstream-wins.
    """
    index: Dict[str, str] = {}
    for meta in merged.meta.values():
        if meta.arch != arch:
            continue
        for filename in meta.files:
            stem = os.path.splitext(os.path.basename(filename))[0]
            index.setdefault(stem, meta.display)
    return index


def load_mdx_catalog_display_index(*, allow_network: bool = True) -> Dict[str, str]:
    """Build MDX checkpoint-basename→display-name index from every source."""
    return _index_from_meta(_merged_for_display(allow_network=allow_network), MDX_ARCH_TYPE)


def load_vr_catalog_display_index(*, allow_network: bool = True) -> Dict[str, str]:
    """Build VR basename→runtime-display index from every source."""
    return _index_from_meta(_merged_for_display(allow_network=allow_network), VR_ARCH_TYPE)


def load_demucs_catalog_display_index(*, allow_network: bool = True) -> Dict[str, str]:
    """Build Demucs stem→runtime-display index from every source."""
    return _index_from_meta(_merged_for_display(allow_network=allow_network), DEMUCS_ARCH_TYPE)


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
        catalogue_name = lookup[basename]
        # VIP / raw catalogue rows sometimes echo the filename; prefer mapper.
        if catalogue_name != basename:
            return catalogue_name
    mapped = lookup_mapper_display(basename, name_mapper)
    if mapped:
        return mapped
    if basename in lookup:
        return lookup[basename]
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
    """Split a checklist tag into ``(arch, name)``.

    Accepts leftover ``Arch: Display`` strings (``ENSEMBLE_PARTITION``) and
    canonical ``family:basename`` ids.
    """
    if not tag:
        return "", tag
    from .model_identity import ARCH_BY_FAMILY, FAMILIES

    prefix, separator, rest = str(tag).partition(":")
    if separator and prefix.casefold() in FAMILIES:
        return ARCH_BY_FAMILY[prefix.casefold()], rest
    if ENSEMBLE_PARTITION in tag:
        arch, _, model_name = tag.partition(ENSEMBLE_PARTITION)
        return arch, model_name
    return "", tag


def format_tag_subtitle(tag: str) -> str:
    """Return the architecture portion of a model tag."""
    arch, _ = parse_model_tag(tag)
    return arch


def format_tag_title(tag: str, repo: "ModelRepository") -> str:
    """Return the friendly model label for a full arch tag.

    Memoized on ``(tag, catalogue revision, naming revision, display generation)``.
    Catalogue/identity refinements must not require remeshing sources; mapper
    overlay reloads bump the naming revision only.
    """
    naming = int(getattr(repo, "naming_revision", 0) or 0)
    catalogue_rev = getattr(repo, "catalogue_revision", "") or ""
    key = (tag, str(catalogue_rev), naming, _display_generation)
    cached = _format_tag_title_cache.get(key)
    if cached is not None:
        return cached
    arch, model_name = parse_model_tag(tag)
    if not arch:
        result = model_name
    else:
        result = display_name_for_model(arch, model_name, repo)
    _format_tag_title_cache[key] = result
    return result


def map_basenames_to_display(
    basenames: Iterable[str],
    arch: str,
    repo: "ModelRepository",
    *,
    allow_network: bool = False,
) -> List[str]:
    """Map on-disk basenames to runtime display labels for a method dropdown."""
    def catalogue_index(name: str) -> Dict[str, str]:
        provider = getattr(repo, name)
        try:
            return provider(allow_network=allow_network)
        except TypeError:
            # Small repository fakes and third-party adapters predating the
            # policy parameter are intrinsically local-only.
            return provider()

    names = list(basenames)
    if arch in (VR_ARCH_TYPE,):
        lookup = catalogue_index("vr_catalogue_display_index")
        return [lookup.get(name, name) for name in names]
    if arch in (MDX_ARCH_TYPE,):
        catalogue = catalogue_index("mdx_catalogue_display_index")
        return [
            display_name_for_basename(name, repo.mdx_name_select_MAPPER, catalogue_index=catalogue)
            for name in names
        ]
    if arch in (DEMUCS_ARCH_TYPE,):
        catalogue = catalogue_index("demucs_catalogue_display_index")
        return [
            catalogue.get(name)
            or lookup_mapper_display(name, repo.demucs_name_select_MAPPER)
            or name
            for name in names
        ]
    return names
