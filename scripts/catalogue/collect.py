"""Collect Download Center catalogue entries into a machine-readable IR.

Membership comes from ``CatalogueCoordinator`` (TRvlvr → Politrees → extras →
mvsepless, plus Apollo). The CLI renders this into Markdown; this module is
the one collection path."""
from __future__ import annotations

import os
from dataclasses import asdict
from datetime import datetime, timezone
from typing import AbstractSet, Any, Dict, List, Mapping, Optional, Tuple

from catalogue import cache, config_evidence, locations

# Legacy public imports retain object identity; consumers use the owners.
from catalogue.cache import DEFAULT_FETCH_POLICY as DEFAULT_FETCH_POLICY
from catalogue.cache import OFFLINE_FETCH_POLICY as OFFLINE_FETCH_POLICY
from catalogue.cache import FetchPolicy as FetchPolicy
from catalogue.config_evidence import _architecture_from_yaml_name
from catalogue.entry_rules import (
    _apply_community_ref,
    _apply_entry_meta,
    _finalize_entry,
    _infer_name_intent,
    _infer_onnx_meta,
    _infer_vr_meta,
    _parse_community_models_bytes,
)
from catalogue.evidence import catalogue_identity_inputs as catalogue_identity_inputs
from catalogue.evidence import catalogue_projection as catalogue_projection
from catalogue.evidence import is_runtime_target_instrument as is_runtime_target_instrument
from catalogue.evidence import reconcile_stem_semantics as reconcile_stem_semantics
from catalogue.evidence import reviewed_stem_signature as reviewed_stem_signature
from catalogue.evidence import runtime_stem_reconciliation as runtime_stem_reconciliation
from catalogue.evidence import runtime_stem_signature as runtime_stem_signature
from catalogue.locations import CACHE_MAX_AGE_SECONDS as CACHE_MAX_AGE_SECONDS
from catalogue.locations import COMMUNITY_CACHE_DIR as COMMUNITY_CACHE_DIR
from catalogue.locations import DISPLAY_REFERENCE_TSV_PATH as DISPLAY_REFERENCE_TSV_PATH
from catalogue.locations import OUTPUT_PATH as OUTPUT_PATH
from catalogue.locations import REFERENCE_TSV_PATH as REFERENCE_TSV_PATH
from catalogue.locations import ROOT as ROOT
from catalogue.locations import (
    STEM_SEMANTICS_REFERENCE_TSV_PATH as STEM_SEMANTICS_REFERENCE_TSV_PATH,
)
from catalogue.locations import YAML_CACHE_DIR as YAML_CACHE_DIR
from catalogue.types import CatalogueContext as CatalogueContext
from catalogue.types import CommunityRef as CommunityRef
from catalogue.types import ModelEntry as ModelEntry
from catalogue.types import ReconciledStemEvidence as ReconciledStemEvidence
from catalogue.types import ReviewedResultProjection as ReviewedResultProjection
from core.access_policy import AccessPolicy, access_policy
from core.catalogue_coordinator import (
    CatalogueCoordinator,
    flatten_upstream_lists,
    yaml_basename_from_ref,
)
from core.catalogue_types import (
    UPSTREAM_DEMUCS_KEYS,
    UPSTREAM_MDX_KEYS,
    UPSTREAM_VR_KEYS,
    RefreshMode,
    SourceId,
)
from core.extra_catalog import APOLLO_LIST_KEY
from core.mdx_runtime_contract import (
    BUNDLED_MDX_RUNTIME_CONTRACT_PATH,
    MdxRuntimeContractError,
    MdxRuntimeContractRegistry,
    load_mdx_runtime_contracts,
)
from core.model_manifest.schema import UnifiedModelRecord
from core.model_manifest.stems import (
    stem_semantics_registry,
)
from core.model_stem_manifest import StemSemanticsRegistry
from core.model_stem_semantics import (
    is_dual_stem_weight,
)

_COMMUNITY_MODELS_URL = "https://raw.githubusercontent.com/upseem/uvr5-cli-no-ui/main/models.txt"


_POLITREES_KEYS = (
    *UPSTREAM_VR_KEYS,
    *UPSTREAM_MDX_KEYS,
    *UPSTREAM_DEMUCS_KEYS,
)


_SUPPLEMENT_LIST_KEYS = (*_POLITREES_KEYS, APOLLO_LIST_KEY)


def _source_payload(coordinator: CatalogueCoordinator, source_id: SourceId) -> dict:
    content = coordinator.source(source_id).state.content
    if content is None:
        return {}
    return dict(content.payload)


def _source_payloads(coordinator: CatalogueCoordinator) -> Tuple[dict, dict, dict, dict]:
    return (
        _source_payload(coordinator, SourceId.UPSTREAM),
        _source_payload(coordinator, SourceId.POLITREES),
        _source_payload(coordinator, SourceId.EXTRAS),
        _source_payload(coordinator, SourceId.MVSEPLESS),
    )


def _unsupported_count(unsupported: Any) -> int:
    if not isinstance(unsupported, dict):
        return 0
    total = 0
    for rows in unsupported.values():
        if isinstance(rows, list):
            total += len(rows)
    return total


def _snapshot_and_payloads(
    *,
    allow_network: bool,
    refresh: bool = False,
    coordinator: Optional[CatalogueCoordinator] = None,
    policy: Optional[FetchPolicy] = None,
) -> Tuple[Any, Tuple[dict, dict, dict, dict]]:
    source_policy = AccessPolicy(
        allow_network=allow_network,
        allow_metadata_writes=True if policy is None else policy.allow_metadata_writes,
        allow_cache_writes=True if policy is None else policy.allow_cache_writes,
    )
    owned = coordinator is None
    if owned:
        coordinator = CatalogueCoordinator()
    try:
        # One blocking snapshot, not refresh() then ensure(). ensure() is
        # stale-while-revalidate and used to republish the FORCE snapshot from
        # cache, including a placeholder RefreshReport(usable=False).
        with access_policy(
            allow_network=source_policy.allow_network,
            allow_metadata_writes=source_policy.allow_metadata_writes,
            allow_cache_writes=source_policy.allow_cache_writes,
        ):
            if refresh and allow_network:
                snapshot = coordinator.snapshot(mode=RefreshMode.FORCE, policy=source_policy)
            else:
                snapshot = coordinator.ensure(allow_network=allow_network, policy=source_policy)
        payloads = _source_payloads(coordinator)
        return snapshot, payloads
    finally:
        if owned:
            coordinator.close()


def _build_catalogue_context(
    *,
    policy: FetchPolicy = DEFAULT_FETCH_POLICY,
    allow_network: Optional[bool] = None,
) -> CatalogueContext:
    if allow_network is not None:
        policy = FetchPolicy(
            allow_network=allow_network,
            refresh=policy.refresh,
            max_age=policy.max_age,
            allow_metadata_writes=policy.allow_metadata_writes,
            allow_cache_writes=policy.allow_cache_writes,
        )
    community_data, _community_path = cache.fetch_cached_bytes(
        _COMMUNITY_MODELS_URL, locations.COMMUNITY_CACHE_DIR, "models.txt", policy=policy
    )
    if community_data is None:
        community, community_available = {}, False
    else:
        community, community_available = _parse_community_models_bytes(community_data)
    unavailable = []
    if not community_available:
        unavailable.append("community models.txt reference")
    try:
        load_mdx_runtime_contracts(BUNDLED_MDX_RUNTIME_CONTRACT_PATH)
    except MdxRuntimeContractError as error:
        unavailable.append(f"MDX runtime contract ({error})")
    return CatalogueContext(
        community_by_file=community,
        unavailable_supplemental_evidence=tuple(unavailable),
    )


def _demucs_overlay(
    meta: ModelEntry,
    registry: StemSemanticsRegistry | None = None,
    presentation: Mapping[str, Any] | None = None,
) -> None:
    """Project Demucs outputs from the unified reviewed declaration."""
    model_id = catalogue_projection(meta, presentation=presentation)[0]
    selected_registry = registry or stem_semantics_registry()
    declaration = selected_registry.models.get(model_id)
    if declaration is None:
        return
    meta.instruments = list(declaration.native_signature)
    meta.stem_count = len(meta.instruments)
    meta.name_intent = declaration.intent
    if meta.stem_count == 2:
        meta.best_result_override = "2-stem: instrumental + vocals (user picks focus)"
    else:
        meta.best_result_override = f"{meta.stem_count}-stem Demucs"
    meta.metadata_source = "catalogue_demucs_declaration"


def _parse_catalogue_entry(
    *,
    source: str,
    family: str,
    label: str,
    payload: Any,
    ctx: CatalogueContext,
    entry_meta: Any = None,
    policy: FetchPolicy = DEFAULT_FETCH_POLICY,
    config_url_index: Mapping[tuple[str, str], str] | None = None,
    registry: StemSemanticsRegistry | None = None,
    reviewed_non_config_ids: AbstractSet[str] | None = None,
    presentation: Mapping[str, Any] | None = None,
    manifest_records: Mapping[str, UnifiedModelRecord] | None = None,
) -> List[ModelEntry]:
    yaml_name = ""
    yaml_url = ""
    weight = ""
    weight_candidates: List[str] = []
    compact_yaml_by_checkpoint: Dict[str, str] = {}
    if isinstance(payload, str):
        weight = payload
    elif isinstance(payload, dict):
        for raw_key, ref in payload.items():
            key = str(raw_key)
            if key.casefold().endswith((".yaml", ".yml")):
                yaml_name = key
                if isinstance(ref, str) and ref.startswith("http"):
                    yaml_url = ref
            elif key.endswith((".pth", ".onnx", ".ckpt", ".th")):
                weight = key
                weight_candidates.append(key)
                compact_yaml = yaml_basename_from_ref(ref)
                if compact_yaml is not None:
                    compact_yaml_by_checkpoint[os.path.basename(key)] = compact_yaml
        if family == "Demucs" and weight_candidates:
            # Remote JSON preserves server insertion order while the atomic
            # cache sorts object keys. A bag contains every member checkpoint,
            # so choose one deterministic representative for audit/display
            # instead of letting fresh-online and warm-offline reports differ.
            weight = max(weight_candidates, key=lambda item: (item.casefold(), item))
        compact_yaml = compact_yaml_by_checkpoint.get(os.path.basename(weight))
        if not yaml_name and compact_yaml is not None:
            yaml_name = compact_yaml
            if config_url_index is not None:
                yaml_url = config_url_index.get(
                    (os.path.basename(weight), compact_yaml),
                    "",
                )

    meta = ModelEntry(
        source=source,
        family=family,
        catalogue_label=label,
        weight_file=weight,
        config_yaml=yaml_name,
        config_url=yaml_url,
    )
    meta.name_intent = _infer_name_intent(label)
    reviewed_non_config = False
    reviewed_config_contract = False
    if yaml_name and family not in ("Apollo", "Demucs") and reviewed_non_config_ids is not None:
        model_id = catalogue_projection(meta, presentation=presentation)[0]
        reviewed_non_config = model_id in reviewed_non_config_ids
        record = manifest_records.get(model_id) if manifest_records is not None else None
        reviewed_config_contract = bool(
            record is not None and record.catalogue_evidence.config_yaml == yaml_name
        )

    if yaml_name and family not in ("Apollo", "Demucs"):
        # Apollo and Demucs sidecars describe execution/configuration details,
        # not the MDX-C training inventory used by this strict stem projection.
        # Their family overlays supply the publication semantics, so those
        # sidecars are not required supplemental evidence here.
        instruments, target, arch, yaml_source, config_sha256 = config_evidence._load_yaml_meta(
            yaml_name,
            yaml_url,
            policy=policy,
        )
        exact_config_evidence = yaml_source.startswith(("bundled_yaml:", "remote_yaml:"))
        if not exact_config_evidence and manifest_records is not None:
            model_id = catalogue_projection(meta, presentation=presentation)[0]
            record = manifest_records.get(model_id)
            evidence = None if record is None else record.config_evidence.get(yaml_name)
            if record is not None and evidence is not None:
                instruments = list(evidence.training_instruments)
                target = evidence.target_instrument or ""
                arch = arch or _architecture_from_yaml_name(yaml_name)
                yaml_source = record.catalogue_evidence.metadata_source
                config_sha256 = evidence.content_sha256
                exact_config_evidence = True
                meta.notes.append(
                    "Exact unified config evidence reused because live/cache bytes were unavailable"
                )
        meta.arch = arch
        if exact_config_evidence:
            meta.instruments = instruments
            meta.target_instrument = target
            meta.config_sha256 = config_sha256
            meta.stem_count = len(instruments) or (1 if target else 0)
            if target:
                meta.primary_stem = target
            elif instruments:
                meta.primary_stem = instruments[0]
        elif not reviewed_non_config and not reviewed_config_contract:
            # Filename guesses can still label architecture informally, but
            # cannot become a native signature used by strict publication.
            ctx.unavailable_yaml_evidence.add(yaml_name)
        if yaml_source:
            meta.metadata_source = yaml_source
    elif (
        yaml_name
        and family == "Apollo"
        and os.path.isfile(os.path.join(locations._BUNDLED_MDX_YAML_DIR, yaml_name))
    ):
        meta.metadata_source = f"bundled_yaml:{yaml_name}"

    if weight:
        ref = ctx.community_by_file.get(weight.lower())
        if ref:
            _apply_community_ref(meta, ref)

    if not meta.metadata_source and weight:
        if weight.endswith(".onnx"):
            stem, karaoke, src = _infer_onnx_meta(weight, label)
            if stem:
                meta.primary_stem = stem
                meta.is_karaoke = karaoke
                meta.metadata_source = src
                meta.stem_count = 2
        elif weight.endswith(".pth"):
            stem, karaoke, src = _infer_vr_meta(weight, label)
            if stem:
                meta.primary_stem = stem
                meta.is_karaoke = karaoke
                meta.metadata_source = src
                meta.stem_count = 2

    if is_dual_stem_weight(weight):
        meta.name_intent = "dual_voc_inst"
        if "Both Vocals and Instrumental are first-class exports" not in meta.notes:
            meta.notes.append("Both Vocals and Instrumental are first-class exports")

    if not meta.metadata_source:
        meta.metadata_source = "unavailable"

    _apply_entry_meta(meta, entry_meta)
    if family == "Demucs":
        _demucs_overlay(meta, registry, presentation)
    _finalize_entry(meta)
    return [meta]


def _label_in_lists(label: str, payload: Optional[dict], keys: Tuple[str, ...]) -> bool:
    if not payload:
        return False
    return any(label in (payload.get(key) or {}) for key in keys)


def _mvsepless_lists(payload: Optional[dict]) -> Optional[dict]:
    if not payload:
        return None
    if "unsupported" in payload or "mdx_download_list" in payload:
        return payload
    from core.mvsepless_catalog import convert_mvsepless_catalog

    return convert_mvsepless_catalog(payload)


def _source_for(
    label: str,
    politrees: Optional[dict] = None,
    trvlvr: Optional[dict] = None,
    extras: Optional[dict] = None,
    mvsepless: Optional[dict] = None,
    *,
    upstream_lists: Optional[Tuple[Any, Any, Any]] = None,
    mvsepless_lists: Optional[dict] = None,
) -> str:
    """Attribute ``label`` to catalogue sources by membership, in merge order.

    ``upstream_lists`` and ``mvsepless_lists`` let a caller hoist the two
    derived payloads out of a per-label loop; both are constant for a run and
    rebuilding them per entry meant one full mvsepless conversion per model.
    """
    if upstream_lists is None and trvlvr:
        upstream_lists = flatten_upstream_lists(trvlvr)
    in_tr = False
    if upstream_lists is not None:
        vr, mdx, demucs = upstream_lists
        in_tr = label in vr or label in mdx or label in demucs
    if mvsepless_lists is None:
        mvsepless_lists = _mvsepless_lists(mvsepless)
    in_pt = _label_in_lists(label, politrees, _POLITREES_KEYS)
    in_ex = _label_in_lists(label, extras, _SUPPLEMENT_LIST_KEYS)
    in_mv = _label_in_lists(label, mvsepless_lists, _POLITREES_KEYS)
    parts: List[str] = []
    if in_tr:
        parts.append("TRvlvr")
    if in_pt:
        parts.append("Politrees")
    if in_ex:
        parts.append("extras")
    if in_mv:
        parts.append("mvsepless")
    # No membership in any payload means the label was not attributable, which
    # is not the same as "it came from TRvlvr" -- a source that failed to load
    # is an empty payload, so a failed membership check proves nothing.
    return "+".join(parts) if parts else "unknown"


def _mdx_family(label: str) -> str:
    family_map = [
        ("Apollo Model", "Apollo"),
        ("MDX-Net Model", "MDX-Net ONNX"),
        ("MDX23 Model", "MDX23C"),
        ("MDX23C Model", "MDX23C"),
        ("Roformer Model", "Roformer"),
        ("SCnet:", "SCNet"),
        ("Bandit", "Bandit"),
    ]
    for prefix, fam in family_map:
        if label.startswith(prefix):
            return fam
    return "MDX-Net"


def _entries_from_snapshot(
    snapshot: Any,
    payloads: Tuple[dict, dict, dict, dict],
    ctx: CatalogueContext,
    *,
    policy: FetchPolicy = DEFAULT_FETCH_POLICY,
    registry: StemSemanticsRegistry | None = None,
    reviewed_non_config_ids: AbstractSet[str] | None = None,
    presentation: Mapping[str, Any] | None = None,
    manifest_records: Mapping[str, UnifiedModelRecord] | None = None,
) -> List[ModelEntry]:
    trvlvr, politrees, extras, mvsepless = payloads
    meta_index = getattr(snapshot, "meta", {}) or {}
    config_url_index = getattr(snapshot, "checkpoint_yaml_url_index", {}) or {}
    all_entries: List[ModelEntry] = []

    # Both of these are constant across the run; computing them per label meant
    # a full mvsepless catalogue conversion for every one of ~474 entries.
    upstream_lists = flatten_upstream_lists(trvlvr) if trvlvr else None
    mvsepless_lists = _mvsepless_lists(mvsepless)

    def source_for(label: str) -> str:
        return _source_for(
            label,
            politrees,
            trvlvr,
            extras=extras,
            mvsepless=mvsepless,
            upstream_lists=upstream_lists,
            mvsepless_lists=mvsepless_lists,
        )

    for label, payload in sorted(dict(snapshot.vr).items()):
        all_entries.extend(
            _parse_catalogue_entry(
                source=source_for(label),
                family="VR Architecture",
                label=label,
                payload=payload,
                ctx=ctx,
                entry_meta=meta_index.get(label),
                policy=policy,
                config_url_index=config_url_index,
                registry=registry,
                reviewed_non_config_ids=reviewed_non_config_ids,
                presentation=presentation,
                manifest_records=manifest_records,
            )
        )

    for label, payload in sorted(dict(snapshot.mdx).items()):
        family = _mdx_family(label)
        all_entries.extend(
            _parse_catalogue_entry(
                source=source_for(label),
                family=family,
                label=label,
                payload=payload,
                ctx=ctx,
                entry_meta=meta_index.get(label),
                policy=policy,
                config_url_index=config_url_index,
                registry=registry,
                reviewed_non_config_ids=reviewed_non_config_ids,
                presentation=presentation,
                manifest_records=manifest_records,
            )
        )

    for label, payload in sorted(dict(snapshot.demucs).items()):
        all_entries.extend(
            _parse_catalogue_entry(
                source=source_for(label),
                family="Demucs",
                label=label,
                payload=payload,
                ctx=ctx,
                entry_meta=meta_index.get(label),
                policy=policy,
                config_url_index=config_url_index,
                registry=registry,
                reviewed_non_config_ids=reviewed_non_config_ids,
                presentation=presentation,
                manifest_records=manifest_records,
            )
        )

    for label, payload in sorted(dict(snapshot.apollo).items()):
        all_entries.extend(
            _parse_catalogue_entry(
                source=source_for(label),
                family="Apollo",
                label=label,
                payload=payload,
                ctx=ctx,
                entry_meta=meta_index.get(label),
                policy=policy,
                config_url_index=config_url_index,
                registry=registry,
                reviewed_non_config_ids=reviewed_non_config_ids,
                presentation=presentation,
                manifest_records=manifest_records,
            )
        )

    return all_entries


def collect_entries(
    ctx: CatalogueContext,
    *,
    policy: Optional[FetchPolicy] = None,
    allow_network: Optional[bool] = None,
    coordinator: Optional[CatalogueCoordinator] = None,
    registry: Optional[StemSemanticsRegistry] = None,
    contracts: Optional[MdxRuntimeContractRegistry] = None,
    reviewed_non_config_ids: Optional[AbstractSet[str]] = None,
    presentation: Optional[Mapping[str, Any]] = None,
    manifest_records: Optional[Mapping[str, UnifiedModelRecord]] = None,
) -> Tuple[Any, List[ModelEntry]]:
    """Acquire a snapshot and turn it into entries. The one collection path.

    ``main`` goes through this too: a second entry path exercised only by
    tests is how the tested behaviour and the real behaviour drift apart.
    """
    if policy is None:
        policy = FetchPolicy(allow_network=True if allow_network is None else allow_network)
    elif allow_network is not None:
        policy = FetchPolicy(
            allow_network=allow_network,
            refresh=policy.refresh,
            max_age=policy.max_age,
            allow_metadata_writes=policy.allow_metadata_writes,
            allow_cache_writes=policy.allow_cache_writes,
        )
    snapshot, payloads = _snapshot_and_payloads(
        allow_network=policy.allow_network,
        refresh=policy.refresh,
        coordinator=coordinator,
        policy=policy,
    )
    entries = _entries_from_snapshot(
        snapshot,
        payloads,
        ctx,
        policy=policy,
        registry=registry,
        reviewed_non_config_ids=reviewed_non_config_ids,
        presentation=presentation,
        manifest_records=manifest_records,
    )
    if registry is not None:
        reconcile_stem_semantics(
            entries,
            registry=registry,
            contracts=contracts,
            reviewed_non_config_ids=reviewed_non_config_ids,
            presentation=presentation,
        )
    return snapshot, entries


IR_SCHEMA_VERSION = 1


def _ir_path_for(output_path: str) -> str:
    """Sidecar path for a rendered document."""
    stem, _ext = os.path.splitext(output_path)
    return f"{stem}.ir.json"


def _document_digest(path: str) -> str:
    """SHA-256 of a rendered document, used to tie a sidecar to it."""
    from core.json_store import content_digest

    return content_digest(path)


def build_ir(
    entries: List[ModelEntry],
    *,
    report: Any,
    unsupported_count: int,
    document_sha256: str = "",
) -> Dict[str, Any]:
    """The catalogue as data, from which Markdown and TSV are rendered.

    Rendered output is lossy and awkward to diff; this is the form a consumer
    can read without parsing prose. It is also what lets the publication guard
    know how many entries the last good run produced, rather than recovering
    that by re-parsing a summary line.
    """
    serialized_entries = []
    for entry in entries:
        serialized = asdict(entry)
        # Reconciled evidence is an in-process publication contract.  It is
        # deliberately absent from schema-1 IR and checked-in generated data.
        serialized.pop("stem_semantics", None)
        serialized_entries.append(serialized)
    return {
        "schema_version": IR_SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "entry_count": len(entries),
        "unsupported_omitted": unsupported_count,
        "provenance": report.as_dict() if hasattr(report, "as_dict") else {},
        # Ties this sidecar to the document it was written beside. Without it
        # a sidecar left behind by a degraded run silently lowers the
        # publication guard's floor for a document it does not describe.
        "document_sha256": document_sha256,
        "entries": serialized_entries,
    }
