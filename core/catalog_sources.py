"""The single merge of every catalogue source.

Before this module there were two independent merge paths — ``DownloadManager``
merged upstream + politrees + extras + mvsepless, while the runtime display
index read only upstream + politrees. They drifted, and models installed from
the two newest sources rendered as raw basenames in the method pickers.

Both consumers now read this module, so a fifth source cannot reintroduce that
class of bug. Only disk caches are read here: no network, so populating a model
dropdown stays fast and works offline.
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

from .catalog_dedupe import dedupe_download_catalogue
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


def _supplemental_sources() -> Tuple[
    Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any]
]:
    """Collect politrees + extras + mvsepless entries, **without** any base.

    Each merge helper is called with empty bases, so what comes back is the
    supplements alone, already ordered politrees > extras > mvsepless among
    themselves. :func:`merged_catalogues` then merges this under the caller's
    upstream catalogues, which keeps upstream-wins in exactly one place.

    Taking no arguments is deliberate: a version that received the base and
    returned it merged could not be substituted in a test without also
    substituting the merge under test.
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


def _primary_checkpoint(files: Mapping[str, str]) -> Optional[str]:
    for name in files:
        if not str(name).endswith(".yaml"):
            return os.path.basename(str(name))
    for name in files:
        return os.path.basename(str(name))
    return None


def _build_meta(
    catalogue: Mapping[str, Any],
    arch: str,
    extra_meta: Mapping[str, Mapping[str, Any]],
) -> Dict[str, EntryMeta]:
    out: Dict[str, EntryMeta] = {}
    for label, model in catalogue.items():
        files: Dict[str, str] = (
            {str(k): str(v) for k, v in model.items()}
            if isinstance(model, dict)
            else {str(model): ""}
        )
        source_meta = extra_meta.get(label) or {}
        stems = source_meta.get("stems")
        out[label] = EntryMeta(
            label=label,
            display=canonical_display_name(label),
            arch=arch,
            files=files,
            checkpoint=_primary_checkpoint(files),
            stems=list(stems) if isinstance(stems, list) else [],
            target_instrument=source_meta.get("target_instrument") or None,
            intent=str(source_meta.get("intent") or INTENT_UNKNOWN),
        )
    return out


def merged_catalogues(
    *,
    vr: Mapping[str, Any],
    mdx: Mapping[str, Any],
    demucs: Mapping[str, Any],
    force: bool = False,
) -> MergedCatalogues:
    """Merge every source over the supplied upstream catalogues, then dedupe."""
    supp_vr, supp_mdx, supp_demucs, extra_meta = _supplemental_sources()

    # Upstream-wins, in one place: a label already in the base is never
    # replaced by a supplement.
    vr_out = merge_supplemental_list(vr, supp_vr)
    mdx_out = merge_supplemental_list(mdx, supp_mdx)
    demucs_out = merge_supplemental_list(demucs, supp_demucs)

    vr_out = dedupe_download_catalogue(vr_out)
    mdx_out = dedupe_download_catalogue(mdx_out)
    demucs_out = dedupe_download_catalogue(demucs_out, demucs_bags=True)
    apollo_out = dedupe_download_catalogue(apollo_download_list())

    meta: Dict[str, EntryMeta] = {}
    for catalogue, arch in (
        (vr_out, VR_ARCH_TYPE),
        (mdx_out, MDX_ARCH_TYPE),
        (demucs_out, DEMUCS_ARCH_TYPE),
        (apollo_out, APOLLO_ARCH_TYPE),
    ):
        meta.update(_build_meta(catalogue, arch, extra_meta))

    debug("download", f"catalog_sources merged entries={len(meta)}")
    return MergedCatalogues(
        vr=vr_out, mdx=mdx_out, demucs=demucs_out, apollo=apollo_out, meta=meta
    )
