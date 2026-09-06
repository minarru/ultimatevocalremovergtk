"""Evidence for the one-snapshot catalogue publication pipeline."""

from __future__ import annotations

from types import SimpleNamespace
from typing import (
    AbstractSet,
    Any,
    List,
    Mapping,
)

from catalogue.types import ModelEntry, ReconciledStemEvidence, ReviewedResultProjection
from core.catalogue_identity import catalogue_model_id
from core.mdx_runtime_contract import (
    MdxRuntimeContractRegistry,
    ReconciledMdxRuntimeSignature,
    is_catalogue_mdx_target_runtime,
    reconcile_catalogue_mdx_runtime_signature,
)
from core.model_catalogue import project_catalogue_display
from core.model_manifest.stems import (
    catalogue_stem_evidence_uses_config,
    reviewed_catalogue_stem_signature,
)
from core.model_naming import canonical_display_name
from core.model_stem_manifest import StemSemanticsRegistry
from core.model_stem_semantics import (
    INTENT_DUAL_VOC_INST,
    INTENT_MULTI_STEM,
    INTENT_SPECIALTY_STEM,
    resolve_catalogue_stem_semantics,
)
from core.stem_roles import (
    ModelStemSemantics,
    SemanticStemOutput,
    StemProcessingContext,
    StemProduction,
    StemReviewStatus,
    StemRoleId,
)


def reviewed_stem_signature(
    model_id: str,
    instruments: Any,
    *,
    registry: StemSemanticsRegistry | None = None,
    evidence_uses_config: bool | None = None,
    reviewed_non_config_ids: AbstractSet[str] | None = None,
) -> tuple[str, ...]:
    """Prefer exact non-config declarations over inferred inventory hints."""
    actual = tuple(str(native) for native in instruments)
    if registry is None or reviewed_non_config_ids is None:
        reviewed = reviewed_catalogue_stem_signature(model_id)
        uses_config = catalogue_stem_evidence_uses_config(model_id)
    else:
        declaration = registry.models.get(model_id)
        reviewed = () if declaration is None else declaration.native_signature
        uses_config = bool(evidence_uses_config) and model_id not in reviewed_non_config_ids
    if reviewed and not uses_config:
        return reviewed
    return actual or reviewed


is_runtime_target_instrument = is_catalogue_mdx_target_runtime


def runtime_stem_signature(
    model_id: str,
    instruments: Any,
    *,
    target_instrument: str = "",
    config_yaml: str = "",
    config_sha256: str = "",
    metadata_source: str = "",
    registry: StemSemanticsRegistry | None = None,
    contracts: MdxRuntimeContractRegistry | None = None,
    reviewed_non_config_ids: AbstractSet[str] | None = None,
) -> tuple[str, ...]:
    """Project collected training evidence to actual engine-native source keys."""
    return runtime_stem_reconciliation(
        model_id,
        instruments,
        target_instrument=target_instrument,
        config_yaml=config_yaml,
        config_sha256=config_sha256,
        metadata_source=metadata_source,
        registry=registry,
        contracts=contracts,
        reviewed_non_config_ids=reviewed_non_config_ids,
    ).native_signature


def runtime_stem_reconciliation(
    model_id: str,
    instruments: Any,
    *,
    target_instrument: str = "",
    config_yaml: str = "",
    config_sha256: str = "",
    metadata_source: str = "",
    registry: StemSemanticsRegistry | None = None,
    contracts: MdxRuntimeContractRegistry | None = None,
    reviewed_non_config_ids: AbstractSet[str] | None = None,
) -> ReconciledMdxRuntimeSignature:
    """Return the one shared exact runtime-signature reconciliation result."""
    uses_config = bool(config_yaml) or metadata_source.startswith(("bundled_yaml:", "remote_yaml:"))
    selected_instruments = reviewed_stem_signature(
        model_id,
        instruments,
        registry=registry,
        evidence_uses_config=uses_config,
        reviewed_non_config_ids=reviewed_non_config_ids,
    )
    reconciled = reconcile_catalogue_mdx_runtime_signature(
        model_id,
        selected_instruments,
        target_instrument=target_instrument,
        config_yaml=config_yaml,
        config_sha256=config_sha256,
        metadata_source=metadata_source,
        contracts=contracts,
    )
    if reconciled.native_signature:
        return reconciled
    fallback = reviewed_stem_signature(
        model_id,
        selected_instruments,
        registry=registry,
        evidence_uses_config=uses_config,
        reviewed_non_config_ids=reviewed_non_config_ids,
    )
    if not fallback:
        return reconciled
    return ReconciledMdxRuntimeSignature(
        native_signature=fallback,
        contract=reconciled.contract,
        reviewed=reconciled.reviewed,
        warning=reconciled.warning,
    )


_RUNTIME_FAMILY_BY_CATALOGUE_FAMILY = {
    "VR Architecture": "vr",
    "Demucs": "demucs",
    "Apollo": "apollo",
    "MDX-Net": "mdx",
    "MDX-Net ONNX": "mdx",
    "MDX23C": "mdx",
    "Roformer": "mdx",
    "SCNet": "mdx",
    "Bandit": "mdx",
}


def catalogue_identity_inputs(entry: ModelEntry) -> tuple[str, str, dict[str, str], object]:
    """Build one complete, family-scoped identity row for shared consumers."""
    try:
        family = _RUNTIME_FAMILY_BY_CATALOGUE_FAMILY[entry.family]
    except KeyError as exc:
        accepted = ", ".join(_RUNTIME_FAMILY_BY_CATALOGUE_FAMILY)
        raise ValueError(
            f"unsupported catalogue family {entry.family!r} for "
            f"{entry.catalogue_label!r}; accepted families: {accepted}"
        ) from exc
    if not entry.weight_file:
        raise ValueError(f"catalogue row has no primary artifact: {entry.catalogue_label!r}")
    files = {entry.weight_file: ""}
    if entry.config_yaml:
        files[entry.config_yaml] = ""
    meta = SimpleNamespace(
        label=entry.catalogue_label,
        display=entry.catalogue_label,
        files=files,
        checkpoint=entry.weight_file,
        stems=(),
    )
    return family, entry.catalogue_label, files, meta


def catalogue_projection(
    entry: ModelEntry,
    *,
    presentation: Mapping[str, Any] | None = None,
) -> tuple[str, str]:
    """Return the exact canonical ID and display for a collected row."""
    family, selection, files, meta = catalogue_identity_inputs(entry)
    model_id = catalogue_model_id(family, selection, files, meta)
    if model_id is None:
        raise ValueError(
            f"catalogue row has no unambiguous presentation primary: {entry.catalogue_label!r}"
        )
    return model_id, project_catalogue_display(
        family,
        selection,
        files,
        meta,
        presentation=presentation,
    )


def _reviewed_result_projection(
    contexts: tuple[ModelStemSemantics, ...],
    registry: StemSemanticsRegistry,
) -> ReviewedResultProjection:
    """Project result prose from semantic priority without reordering routes."""
    semantics = next(
        (context for context in contexts if context.context is StemProcessingContext.FULL_MIX),
        contexts[0],
    )
    routes: list[tuple[int, SemanticStemOutput, str]] = []
    for index, output in enumerate(semantics.outputs):
        if isinstance(output.role, StemRoleId):
            definition = registry.roles.get(output.role)
            display = definition.display if definition is not None else output.role.value
        elif output.native is not None:
            display = output.native.raw
        else:
            display = output.role.tag
        routes.append((index, output, display))

    if not routes:
        return ReviewedResultProjection(semantics.intent, semantics.intent, "")

    primary_route = next(
        ((index, output, display) for index, output, display in routes if output.logical_primary),
        None,
    )
    if primary_route is None:
        raise ValueError("reviewed result projection has no logical primary route")
    primary_index, primary_output, primary_display = primary_route

    secondary_index = next(
        (index for index, output, _display in routes if output.logical_secondary),
        None,
    )
    if secondary_index is None and semantics.logical_secondary_role is not None:
        secondary_index = next(
            (
                index
                for index, output, _display in routes
                if output.role == semantics.logical_secondary_role
            ),
            None,
        )
    role_indices = {
        output.role: index
        for index, output, _display in routes
        if isinstance(output.role, StemRoleId)
    }
    matching_pair = (
        next(
            (
                pair
                for pair in registry.pairs.values()
                if primary_output.role in pair.roles and set(pair.roles).issubset(role_indices)
            ),
            None,
        )
        if isinstance(primary_output.role, StemRoleId)
        else None
    )
    if secondary_index is None and matching_pair is not None:
        secondary_role = next(role for role in matching_pair.roles if role != primary_output.role)
        secondary_index = role_indices[secondary_role]

    priority_indices = [primary_index]
    if secondary_index is not None and secondary_index != primary_index:
        priority_indices.append(secondary_index)
    used_indices = set(priority_indices)
    priority_indices.extend(
        index
        for index, output, _display in routes
        if index not in used_indices and output.selected_by_default
    )
    used_indices.update(priority_indices)
    priority_indices.extend(
        index for index, _output, _display in routes if index not in used_indices
    )
    routes_by_index = {index: (output, display) for index, output, display in routes}
    ordered_routes = tuple(routes_by_index[index] for index in priority_indices)

    def availability_label(output: SemanticStemOutput, display: str) -> str:
        if output.selected_by_default:
            return display
        kind = "derived output" if output.production is StemProduction.DERIVED else "output"
        return f"{display} (available {kind}; not selected by default)"

    ordered_labels = tuple(
        availability_label(output, display) for output, display in ordered_routes
    )
    primary_complement_source = next(
        (
            display
            for _index, output, display in routes
            if primary_output.complement_of is not None
            and output.role == primary_output.complement_of
        ),
        "",
    )
    complement_of_primary = next(
        (
            availability_label(output, display)
            for _index, output, display in routes
            if output.complement_of is not None and output.complement_of == primary_output.role
        ),
        "",
    )
    if (
        matching_pair is not None
        and len(ordered_routes) == 2
        and (primary_complement_source or complement_of_primary)
    ):
        best_result = " / ".join(ordered_labels)
    elif primary_complement_source and len(ordered_routes) == 2:
        best_result = f"{primary_display} (complement of {primary_complement_source})"
    elif complement_of_primary and len(ordered_routes) == 2:
        best_result = f"{ordered_labels[0]} (+ {complement_of_primary} complement)"
    elif semantics.intent == INTENT_MULTI_STEM:
        best_result = f"Multi-stem: {', '.join(ordered_labels)}"
    elif semantics.intent == INTENT_DUAL_VOC_INST and len(ordered_labels) == 2:
        best_result = (
            f"{ordered_labels[0]} or {ordered_labels[1]} — both are first-class 2-stem exports"
        )
    else:
        best_result = ", ".join(ordered_labels)

    if len(ordered_labels) < 2:
        ui_export_note = ""
    elif semantics.intent in (INTENT_MULTI_STEM, INTENT_SPECIALTY_STEM):
        ui_export_note = f"UI: {' / '.join(ordered_labels)} subset"
    elif semantics.intent == INTENT_DUAL_VOC_INST:
        ui_export_note = f"UI: {' / '.join(ordered_labels)} (either stem is a valid primary export)"
    else:
        ui_export_note = f"UI: {' / '.join(ordered_labels)}"
    return ReviewedResultProjection(semantics.intent, best_result, ui_export_note)


def reconcile_stem_semantics(
    entries: List[ModelEntry],
    *,
    registry: StemSemanticsRegistry,
    contracts: MdxRuntimeContractRegistry | None = None,
    reviewed_non_config_ids: AbstractSet[str] | None = None,
    presentation: Mapping[str, Any] | None = None,
) -> None:
    """Attach exact reviewed semantics to one already-collected snapshot."""
    for entry in entries:
        model_id, model_display = catalogue_projection(
            entry,
            presentation=presentation,
        )
        runtime = runtime_stem_reconciliation(
            model_id,
            entry.instruments,
            target_instrument=entry.target_instrument,
            config_yaml=entry.config_yaml,
            config_sha256=entry.config_sha256,
            metadata_source=entry.metadata_source,
            registry=registry,
            contracts=contracts,
            reviewed_non_config_ids=reviewed_non_config_ids,
        )
        declaration = registry.models.get(model_id)
        contexts = (
            tuple(declaration.contexts)
            if declaration is not None
            else (StemProcessingContext.FULL_MIX,)
        )
        projections = tuple(
            resolve_catalogue_stem_semantics(
                model_id,
                native_stems=runtime.native_signature,
                backend_primary=entry.primary_stem,
                backend_target=entry.target_instrument,
                context=context,
                registry=registry,
                runtime_warning=runtime.warning,
            )
            for context in contexts
        )
        reviewed = bool(projections) and all(
            projection.status is StemReviewStatus.REVIEWED for projection in projections
        )
        guessed_intent = "" if reviewed else entry.name_intent
        guessed_flags = () if reviewed else tuple(entry.flags)
        if reviewed:
            result = _reviewed_result_projection(projections, registry)
            entry.name_intent = result.intent
            entry.best_result = result.best_result
            entry.ui_export_note = result.ui_export_note
            entry.best_result_override = ""
            entry.flags.clear()
        entry.stem_semantics = ReconciledStemEvidence(
            model_id=model_id,
            model_display=model_display,
            native_signature=runtime.native_signature,
            runtime_warning=runtime.warning,
            reviewed=reviewed,
            contexts=projections,
            guessed_intent=guessed_intent,
            guessed_flags=guessed_flags,
        )


def _display_label(entry: ModelEntry) -> str:
    return canonical_display_name(entry.catalogue_label) or entry.catalogue_label
