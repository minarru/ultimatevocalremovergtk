"""The single merge of every catalogue source.

Before this module there were two independent merge paths — ``DownloadManager``
merged upstream + politrees + extras + mvsepless, while the runtime display
index read only upstream + politrees. They drifted, and models installed from
the two newest sources rendered as raw basenames in the method pickers.

Both consumers now read this module, so a fifth source cannot reintroduce that
class of bug. Only disk caches are read here: no network, so populating a model
dropdown stays fast and works offline.

Merge priority (earlier wins on label and every dedupe key):

1. upstream / TRvlvr
2. Politrees
3. fork extras
4. mvsepless
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Tuple

from bundled.constants import (
    APOLLO_ARCH_TYPE,
    DEMUCS_ARCH_TYPE,
    MDX_ARCH_TYPE,
    VR_ARCH_TYPE,
)

from .catalog_dedupe import (
    dedupe_download_catalogue,
    normalize_catalogue_label,
    primary_checkpoint_url,
)
from .debug_log import debug
from .extra_catalog import apollo_download_list, merge_extra_catalogues
from .model_naming import canonical_display_name
from .model_stem_semantics import INTENT_UNKNOWN
from .mvsepless_catalog import merge_mvsepless_catalogues, mvsepless_metadata
from .politrees_catalog import (
    load_politrees_links,
    merge_politrees_catalogues,
    merge_supplemental_list,
)

#: Bumped by :func:`invalidate_catalogue_merge` when any catalogue source changes.
_merge_generation: int = 0
_supp_cache: Optional[
    Tuple[int, Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any]]]
] = None
_merge_cache: Dict[Tuple[Any, ...], "MergedCatalogues"] = {}


@dataclass(frozen=True)
class EntryMeta:
    """Everything known about one catalogue entry, keyed by its label."""

    label: str
    display: str
    arch: str
    files: Dict[str, str] = field(default_factory=dict)
    checkpoint: Optional[str] = None
    stems: List[str] = field(default_factory=list)
    target_instrument: Optional[str] = None
    intent: str = INTENT_UNKNOWN


@dataclass(frozen=True)
class MergedCatalogues:
    vr: Dict[str, Any]
    mdx: Dict[str, Any]
    demucs: Dict[str, Any]
    apollo: Dict[str, Any]
    meta: Dict[str, EntryMeta]



def invalidate_catalogue_merge() -> None:
    """Drop cached supplement/full merges (call when any source changes)."""
    global _merge_generation, _supp_cache
    _merge_generation += 1
    _supp_cache = None
    _merge_cache.clear()


def _upstream_fingerprint(
    vr: Mapping[str, Any],
    mdx: Mapping[str, Any],
    demucs: Mapping[str, Any],
) -> Tuple[frozenset[str], frozenset[str], frozenset[str]]:
    return (frozenset(vr), frozenset(mdx), frozenset(demucs))


def _collect_supplemental_sources() -> Tuple[
    Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any]
]:
    """Collect politrees + extras + mvsepless entries, **without** any base.

    Each merge helper is called with empty bases, so what comes back is the
    supplements alone, already ordered politrees > extras > mvsepless among
    themselves. :func:`merged_catalogues` then merges this under the caller's
    upstream catalogues, which keeps upstream-wins in exactly one place.
    """
    vr: Dict[str, Any] = {}
    mdx: Dict[str, Any] = {}
    demucs: Dict[str, Any] = {}

    politrees = load_politrees_links()
    if politrees:
        vr, mdx, demucs = merge_politrees_catalogues(vr, mdx, demucs, politrees)
    vr, mdx, demucs = merge_extra_catalogues(vr, mdx, demucs)
    vr, mdx, demucs = merge_mvsepless_catalogues(vr, mdx, demucs)
    return dict(vr), dict(mdx), dict(demucs), mvsepless_metadata()


def _supplemental_sources() -> Tuple[
    Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any]
]:
    """Cached wrapper around :func:`_collect_supplemental_sources`."""
    global _supp_cache
    if _supp_cache is not None and _supp_cache[0] == _merge_generation:
        return _supp_cache[1]
    result = _collect_supplemental_sources()
    _supp_cache = (_merge_generation, result)
    return result


def _primary_checkpoint(files: Mapping[str, str]) -> Optional[str]:
    for name in files:
        if not str(name).endswith(".yaml"):
            return os.path.basename(str(name))
    for name in files:
        return os.path.basename(str(name))
    return None


def _yaml_config_url(files: Mapping[str, str]) -> Optional[str]:
    for name, ref in files.items():
        if str(name).endswith((".yaml", ".yml")) and str(ref).startswith(
            ("http://", "https://")
        ):
            return str(ref).split("?", 1)[0]
    return None


def _build_meta(
    catalogue: Mapping[str, Any],
    arch: str,
    extra_meta: Mapping[str, Mapping[str, Any]],
    alias_meta: Mapping[str, Mapping[str, Any]],
) -> Dict[str, EntryMeta]:
    from .catalogue_stem_cache import lookup_stems

    out: Dict[str, EntryMeta] = {}
    for label, model in catalogue.items():
        files: Dict[str, str] = (
            {str(k): str(v) for k, v in model.items()}
            if isinstance(model, dict)
            else {str(model): ""}
        )
        source_meta = (
            extra_meta.get(label)
            or alias_meta.get(normalize_catalogue_label(label))
            or {}
        )
        stems_raw = source_meta.get("stems")
        stems = list(stems_raw) if isinstance(stems_raw, list) else []
        target = source_meta.get("target_instrument") or None
        if not stems:
            yaml_url = _yaml_config_url(files)
            if yaml_url:
                hit = lookup_stems(yaml_url)
                if hit is not None and hit.ok and hit.stems:
                    stems = list(hit.stems)
                    if not target:
                        target = hit.target_instrument
        out[label] = EntryMeta(
            label=label,
            display=canonical_display_name(label),
            arch=arch,
            files=files,
            checkpoint=_primary_checkpoint(files),
            stems=stems,
            target_instrument=target,
            intent=str(source_meta.get("intent") or INTENT_UNKNOWN),
        )
    return out


def _metadata_alias_index(
    metadata: Mapping[str, Mapping[str, Any]],
) -> Dict[str, Mapping[str, Any]]:
    """Index the richest metadata record under each logical label identity."""
    aliases: Dict[str, Mapping[str, Any]] = {}

    def richness(value: Mapping[str, Any]) -> Tuple[int, int, int]:
        stems = value.get("stems")
        intent = str(value.get("intent") or INTENT_UNKNOWN)
        return (
            len(stems) if isinstance(stems, list) else 0,
            1 if value.get("target_instrument") else 0,
            1 if intent != INTENT_UNKNOWN else 0,
        )

    for label, value in metadata.items():
        identity = normalize_catalogue_label(label)
        if not identity:
            continue
        current = aliases.get(identity)
        if current is None or richness(value) > richness(current):
            aliases[identity] = value
    return aliases


def _checkpoint_urls(*catalogues: Mapping[str, Any]) -> List[str]:
    urls: List[str] = []
    for catalogue in catalogues:
        for model in catalogue.values():
            url = primary_checkpoint_url(model)
            if url:
                urls.append(url)
    return urls


def merged_catalogues(
    *,
    vr: Mapping[str, Any],
    mdx: Mapping[str, Any],
    demucs: Mapping[str, Any],
    force: bool = False,
) -> MergedCatalogues:
    """Merge every source over the supplied upstream catalogues, then dedupe."""
    gen_at_start = _merge_generation
    supp_vr, supp_mdx, supp_demucs, extra_meta = _supplemental_sources()
    cache_key = (
        gen_at_start,
        _upstream_fingerprint(vr, mdx, demucs),
        _upstream_fingerprint(supp_vr, supp_mdx, supp_demucs),
        frozenset(extra_meta),
    )
    if not force:
        cached = _merge_cache.get(cache_key)
        if cached is not None:
            return cached

    # Upstream-wins, in one place: a label already in the base is never
    # replaced by a supplement.
    vr_all = merge_supplemental_list(vr, supp_vr)
    mdx_all = merge_supplemental_list(mdx, supp_mdx)
    demucs_all = merge_supplemental_list(demucs, supp_demucs)
    apollo_all = apollo_download_list()
    alias_meta = _metadata_alias_index(extra_meta)

    # Metadata is built **before** dedupe, on purpose. Dedupe is right for the
    # Download Center's list — do not offer one weight twice — but wrong for a
    # lookup index: a duplicate label dropped from the list still names a
    # checkpoint that has to resolve in the runtime pickers. Deduping first
    # silently un-named five legacy upstream models.
    meta: Dict[str, EntryMeta] = {}
    for catalogue, arch in (
        (vr_all, VR_ARCH_TYPE),
        (mdx_all, MDX_ARCH_TYPE),
        (demucs_all, DEMUCS_ARCH_TYPE),
        (apollo_all, APOLLO_ARCH_TYPE),
    ):
        meta.update(_build_meta(catalogue, arch, extra_meta, alias_meta))

    from .download_sizes import content_ids_from_cache

    content_ids = content_ids_from_cache(
        _checkpoint_urls(vr_all, mdx_all, apollo_all)
    )

    before = len(vr_all) + len(mdx_all) + len(demucs_all) + len(apollo_all)
    vr_out = dedupe_download_catalogue(vr_all, content_ids=content_ids)
    mdx_out = dedupe_download_catalogue(mdx_all, content_ids=content_ids)
    demucs_out = dedupe_download_catalogue(demucs_all, demucs_bags=True)
    apollo_out = dedupe_download_catalogue(apollo_all, content_ids=content_ids)
    after = len(vr_out) + len(mdx_out) + len(demucs_out) + len(apollo_out)
    dropped = before - after

    with_stems = sum(1 for entry in meta.values() if entry.stems)
    debug(
        "download",
        f"catalog_sources merged entries={len(meta)} "
        f"dedupe_dropped={dropped} with_stems={with_stems}",
    )
    result = MergedCatalogues(
        vr=vr_out,
        mdx=mdx_out,
        demucs=demucs_out,
        apollo=apollo_out,
        meta=meta,
    )
    # A clear_display_cache / invalidate mid-flight bumps the generation; do
    # not publish that stale result under the new live key.
    if not force and _merge_generation == gen_at_start:
        _merge_cache[cache_key] = result
    return result
