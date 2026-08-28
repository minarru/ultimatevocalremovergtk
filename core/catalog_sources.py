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
from dataclasses import dataclass, field, replace
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
from .catalogue_identity import catalogue_model_id
from .catalogue_types import CatalogueEvidenceState, StemSemanticProjection
from .debug_log import debug
from .extra_catalog import apollo_download_list, merge_extra_catalogues
from .mdx_runtime_contract import reconcile_catalogue_mdx_runtime_signature
from .model_identity import FAMILY_BY_ARCH
from .model_naming import canonical_display_name
from .model_stem_semantics import (
    INTENT_UNKNOWN,
    resolve_catalogue_intent,
    resolve_exact_catalogue_stem_semantics,
    resolve_is_karaoke,
    stem_semantics_projection,
)
from .mvsepless_catalog import merge_mvsepless_catalogues, mvsepless_metadata
from .politrees_catalog import (
    load_politrees_links,
    merge_politrees_catalogues,
    merge_supplemental_list,
)

#: Bumped by :func:`invalidate_catalogue_merge` when any catalogue source changes.
_merge_generation: int = 0
_supp_cache: Dict[
    bool, Tuple[int, Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any]]]
] = {}
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
    config_sha256: str = ""
    intent: str = INTENT_UNKNOWN
    #: Name/category inference retained strictly as inspectable audit evidence.
    guessed_intent: str = INTENT_UNKNOWN
    stem_semantics: StemSemanticProjection = field(
        default_factory=lambda: StemSemanticProjection(
            backend_primary_stem=None,
            backend_target_stem=None,
            logical_primary_role=None,
            logical_secondary_role=None,
            status="raw",
            context="full_mix",
            routes=(),
        )
    )
    catalogue_evidence_status: CatalogueEvidenceState = CatalogueEvidenceState.UNAVAILABLE
    catalogue_evidence_warning: str = ""


def _entry_config_yaml(meta: EntryMeta) -> str:
    return next(
        (
            os.path.basename(str(name))
            for name in meta.files
            if str(name).casefold().endswith((".yaml", ".yml"))
        ),
        "",
    )


def _append_warning(current: str, warning: str) -> str:
    if not warning:
        return current
    return f"{current}; {warning}" if current else warning


def reconcile_catalogue_evidence(
    meta: EntryMeta,
    *,
    live_stems: Optional[List[str]] = None,
    live_target_instrument: Optional[str] = None,
    live_config_sha256: str = "",
    live_usable: bool = False,
    live_stale: bool = False,
    live_failed: bool = False,
    live_warning: str = "",
    backend_primary: Optional[str] = None,
) -> EntryMeta:
    """Apply exact live, bundled, family, then audit evidence in one place."""
    from .model_manifest.loader import load_model_manifest
    from .model_manifest.runtime import bundled_catalogue_config_evidence
    from .model_manifest.stems import (
        catalogue_stem_evidence_not_applicable,
        reviewed_catalogue_stem_signature,
    )

    config_yaml = _entry_config_yaml(meta)
    family = FAMILY_BY_ARCH.get(meta.arch, "")
    model_id = catalogue_model_id(family, meta.label, meta.files, meta) or ""
    manifest = load_model_manifest()
    record = manifest.models.get(model_id)
    declared_signature = reviewed_catalogue_stem_signature(model_id)
    associated_config = record.catalogue_evidence.config_yaml if record is not None else ""
    evidence_config_yaml = associated_config or (config_yaml if family == "mdx" else "")
    has_config_contract = bool(evidence_config_yaml)
    bundled = (
        bundled_catalogue_config_evidence(model_id, evidence_config_yaml)
        if evidence_config_yaml
        else None
    )
    usable_live = bool(has_config_contract and live_usable and live_stems and live_config_sha256)
    selected_stems: tuple[str, ...] | None = None
    selected_target: Optional[str] = None
    selected_digest = ""
    source = ""
    warning = ""

    if usable_live:
        selected_stems = tuple(str(item) for item in live_stems or ())
        selected_target = live_target_instrument or None
        selected_digest = live_config_sha256
        source = "live"
    elif bundled is not None:
        selected_stems = bundled.training_instruments
        selected_target = bundled.target_instrument
        selected_digest = bundled.content_sha256
        source = "bundled"
    elif not has_config_contract and declared_signature:
        selected_stems = declared_signature
        selected_target = meta.target_instrument
        source = "family"

    if catalogue_stem_evidence_not_applicable(model_id):
        evidence_status = CatalogueEvidenceState.NOT_APPLICABLE
    elif source == "live":
        evidence_status = (
            CatalogueEvidenceState.STALE if live_stale else CatalogueEvidenceState.READY
        )
        warning = live_warning if live_stale else ""
    elif source:
        evidence_status = CatalogueEvidenceState.READY
    elif has_config_contract:
        evidence_status = (
            CatalogueEvidenceState.UNAVAILABLE
            if live_failed or not _yaml_config_url(meta.files)
            else CatalogueEvidenceState.PENDING
        )
        warning = live_warning if live_failed else ""
    else:
        evidence_status = CatalogueEvidenceState.UNAVAILABLE
        warning = live_warning if live_failed else ""

    semantic_mismatch = ""
    exact_native: tuple[str, ...] | None = None
    if selected_stems is not None:
        live_fields_match = bool(
            source == "live"
            and bundled is not None
            and selected_stems == bundled.training_instruments
            and selected_target == bundled.target_instrument
        )
        if source == "live" and bundled is not None and not live_fields_match:
            semantic_mismatch = (
                "catalogue-evidence-mismatch "
                f"model_id={model_id} training.instruments={selected_stems!r} "
                f"expected={bundled.training_instruments!r} "
                f"training.target_instrument={selected_target!r} "
                f"expected={bundled.target_instrument!r}"
            )
        reconciled = reconcile_catalogue_mdx_runtime_signature(
            model_id,
            selected_stems,
            target_instrument=str(selected_target or ""),
            config_yaml=(config_yaml if source == "live" else evidence_config_yaml),
            config_sha256=selected_digest,
        )
        exact_native = reconciled.native_signature
        if reconciled.warning:
            semantic_mismatch = reconciled.warning
        if (
            source == "live"
            and bundled is not None
            and selected_digest != bundled.content_sha256
            and live_fields_match
            and reconciled.contract is None
        ):
            warning = _append_warning(
                warning,
                f"catalogue-evidence-digest-drift model_id={model_id} config={config_yaml}",
            )

    resolved_primary = str(
        backend_primary
        if backend_primary is not None
        else (meta.stem_semantics.backend_primary_stem or "")
    )
    resolved_target = selected_target if selected_stems is not None else meta.target_instrument
    semantics = resolve_exact_catalogue_stem_semantics(
        model_id,
        exact_native_stems=exact_native,
        audit_native_stems=meta.stems,
        backend_primary=resolved_primary,
        backend_target=str(resolved_target or ""),
        evidence_warning=warning,
        semantic_mismatch_warning=semantic_mismatch,
    )
    warning = (
        semantics.warning
        if warning or semantics.warning.startswith(("catalogue-evidence-", "runtime-contract-"))
        else ""
    )
    projection = stem_semantics_projection(
        semantics,
        backend_primary=resolved_primary,
        backend_target=str(resolved_target or ""),
    )
    return replace(
        meta,
        stems=(list(selected_stems) if selected_stems is not None else meta.stems),
        target_instrument=resolved_target,
        config_sha256=(selected_digest if selected_stems is not None else meta.config_sha256),
        intent=(semantics.intent if semantics.status.value == "reviewed" else meta.guessed_intent),
        stem_semantics=projection,
        catalogue_evidence_status=evidence_status,
        catalogue_evidence_warning=warning,
    )


def with_catalogue_config_evidence(
    meta: EntryMeta,
    *,
    stems: List[str],
    target_instrument: Optional[str],
    config_sha256: str,
) -> EntryMeta:
    """Reconcile newly parsed live YAML evidence through the shared boundary."""
    return reconcile_catalogue_evidence(
        meta,
        live_stems=stems,
        live_target_instrument=target_instrument,
        live_config_sha256=config_sha256,
        live_usable=bool(stems and config_sha256),
    )


@dataclass(frozen=True)
class MergedCatalogues:
    vr: Dict[str, Any]
    mdx: Dict[str, Any]
    demucs: Dict[str, Any]
    apollo: Dict[str, Any]
    meta: Dict[str, EntryMeta]
    meta_by_family: Dict[str, Dict[str, EntryMeta]]


def invalidate_catalogue_merge() -> None:
    """Drop cached supplement/full merges (call when any source changes)."""
    global _merge_generation
    _merge_generation += 1
    _supp_cache.clear()
    _merge_cache.clear()


def _upstream_fingerprint(
    vr: Mapping[str, Any],
    mdx: Mapping[str, Any],
    demucs: Mapping[str, Any],
) -> Tuple[Any, ...]:
    from .catalogue_types import freeze_files

    def one(catalogue: Mapping[str, Any]) -> Tuple[Tuple[str, Tuple[Tuple[str, str], ...]], ...]:
        return tuple((str(label), freeze_files(model)) for label, model in catalogue.items())

    return (one(vr), one(mdx), one(demucs))


def _collect_supplemental_sources(
    *, allow_network: bool
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Collect politrees + extras + mvsepless entries, **without** any base.

    Each merge helper is called with empty bases, so what comes back is the
    supplements alone, already ordered politrees > extras > mvsepless among
    themselves. :func:`merged_catalogues` then merges this under the caller's
    upstream catalogues, which keeps upstream-wins in exactly one place.
    """
    vr: Dict[str, Any] = {}
    mdx: Dict[str, Any] = {}
    demucs: Dict[str, Any] = {}

    politrees = load_politrees_links(allow_network=allow_network)
    if politrees:
        vr, mdx, demucs = merge_politrees_catalogues(vr, mdx, demucs, politrees)
    vr, mdx, demucs = merge_extra_catalogues(vr, mdx, demucs)
    vr, mdx, demucs = merge_mvsepless_catalogues(vr, mdx, demucs, allow_network=allow_network)
    return (
        dict(vr),
        dict(mdx),
        dict(demucs),
        mvsepless_metadata(allow_network=allow_network),
    )


def _supplemental_sources(
    *, allow_network: bool
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Cached wrapper around :func:`_collect_supplemental_sources`."""
    gen = _merge_generation
    cached = _supp_cache.get(allow_network)
    if cached is not None and cached[0] == gen:
        return cached[1]
    result = _collect_supplemental_sources(allow_network=allow_network)
    if _merge_generation == gen:
        _supp_cache[allow_network] = (gen, result)
    return result


def _primary_checkpoint(files: Mapping[str, str], *, demucs_bag: bool = False) -> Optional[str]:
    weights = [
        os.path.basename(str(name))
        for name in files
        if not str(name).casefold().endswith((".yaml", ".yml"))
    ]
    if weights:
        # A Demucs YAML may declare several interchangeable ensemble members.
        # Their source mapping order is not identity evidence, so use the same
        # stable reviewed member selection as catalogue collection/publication.
        if demucs_bag:
            return max(weights, key=lambda item: (item.casefold(), item))
        return weights[0]
    for name in files:
        return os.path.basename(str(name))
    return None


def _yaml_config_url(files: Mapping[str, str]) -> Optional[str]:
    for name, ref in files.items():
        if str(name).endswith((".yaml", ".yml")) and str(ref).startswith(("http://", "https://")):
            return str(ref).split("?", 1)[0]
    return None


def _needs_catalogue_config_evidence(meta: EntryMeta) -> bool:
    """Whether one YAML-backed row can still change evidence availability."""
    return bool(_yaml_config_url(meta.files)) and meta.catalogue_evidence_status in (
        CatalogueEvidenceState.PENDING,
        CatalogueEvidenceState.UNAVAILABLE,
        CatalogueEvidenceState.STALE,
    )


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
            extra_meta.get(label) or alias_meta.get(normalize_catalogue_label(label)) or {}
        )
        checkpoint = _primary_checkpoint(files, demucs_bag=arch == DEMUCS_ARCH_TYPE)
        stems_raw = source_meta.get("stems")
        stems = list(stems_raw) if isinstance(stems_raw, list) else []
        target = source_meta.get("target_instrument") or None
        yaml_url = _yaml_config_url(files)
        hit = lookup_stems(yaml_url) if yaml_url else None
        backend_primary = str(source_meta.get("primary_stem") or "")
        backend_target = str(target or "")
        guessed_intent = resolve_catalogue_intent(
            target=backend_target,
            instruments=stems,
            is_karaoke=resolve_is_karaoke(model_name=label),
            weight_basename=str(checkpoint or ""),
            catalogue_label=label,
            category_intent=str(source_meta.get("intent") or INTENT_UNKNOWN),
        )
        base = EntryMeta(
            label=label,
            display=canonical_display_name(label),
            arch=arch,
            files=files,
            checkpoint=checkpoint,
            stems=stems,
            target_instrument=target,
            intent=guessed_intent,
            guessed_intent=guessed_intent,
        )
        out[label] = reconcile_catalogue_evidence(
            base,
            live_stems=(list(hit.stems) if hit is not None else None),
            live_target_instrument=(hit.target_instrument if hit is not None else None),
            live_config_sha256=(hit.content_sha256 if hit is not None else ""),
            live_usable=bool(hit is not None and hit.usable),
            live_stale=bool(hit is not None and hit.stale),
            live_failed=bool(hit is not None and hit.last_error is not None and not hit.usable),
            live_warning=(hit.warning if hit is not None else ""),
            backend_primary=backend_primary,
        )
    return out


def _metadata_alias_index(
    metadata: Mapping[str, Mapping[str, Any]],
) -> Dict[str, Mapping[str, Any]]:
    """Index metadata aliases only when their normalized identity is unique.

    Exact labels are resolved by :func:`_build_meta` before this fallback.  A
    normalized alias spanning multiple records is ambiguous and must not select
    one record by payload insertion order or metadata richness.
    """
    aliases: Dict[str, Mapping[str, Any]] = {}
    ambiguous: set[str] = set()

    for label, value in metadata.items():
        identity = normalize_catalogue_label(label)
        if not identity or identity in ambiguous:
            continue
        current = aliases.get(identity)
        if current is None:
            aliases[identity] = value
        else:
            aliases.pop(identity)
            ambiguous.add(identity)
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
    allow_network: bool = True,
) -> MergedCatalogues:
    """Merge every source over the supplied upstream catalogues, then dedupe."""
    gen_at_start = _merge_generation
    supp_vr, supp_mdx, supp_demucs, extra_meta = _supplemental_sources(allow_network=allow_network)
    cache_key = (
        gen_at_start,
        allow_network,
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
    meta_by_family: Dict[str, Dict[str, EntryMeta]] = {}
    for family, catalogue, arch in (
        ("vr", vr_all, VR_ARCH_TYPE),
        ("mdx", mdx_all, MDX_ARCH_TYPE),
        ("demucs", demucs_all, DEMUCS_ARCH_TYPE),
        ("apollo", apollo_all, APOLLO_ARCH_TYPE),
    ):
        family_meta = _build_meta(catalogue, arch, extra_meta, alias_meta)
        meta_by_family[family] = family_meta
        meta.update(family_meta)

    from .download_sizes import content_ids_from_cache

    content_ids = content_ids_from_cache(_checkpoint_urls(vr_all, mdx_all, apollo_all))

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
        meta_by_family=meta_by_family,
    )
    # A clear_display_cache / invalidate mid-flight bumps the generation; do
    # not publish that stale result under the new live key.
    if not force and _merge_generation == gen_at_start:
        _merge_cache[cache_key] = result
    return result
