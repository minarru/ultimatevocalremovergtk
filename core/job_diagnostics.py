"""Pure planning assessments and narrow ordered event delivery."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from .job_materialization import PlanningProbes
from .job_plan_types import Diagnostic, ModelDescriptor, Provenance
from .job_route_observations import collect_ensemble_routes
from .model_stem_manifest import StemPairDefinition
from .model_stem_semantics import StemSemanticProjection, stem_semantics_projection
from .settings import Settings
from .stem_pairs import normalize_stem_pair_id, stem_pair_definition
from .stem_roles import StemRoleId
from .stems import (
    StemSelection,
    StemSelectionStatus,
    model_stem_routes,
    positional_stem_focus,
    select_ensemble_stem_routes,
    select_stem_routes,
)


@dataclass(frozen=True)
class DiagnosticEvent:
    category: str
    name: str
    level: str
    fields: Mapping[str, Any]


@dataclass(frozen=True)
class DiagnosticAssessment:
    diagnostics: tuple[Diagnostic, ...]
    events: tuple[DiagnosticEvent, ...]


def assess_stem_semantics(
    descriptor: ModelDescriptor, projection: StemSemanticProjection | None
) -> DiagnosticAssessment:
    diagnostics: list[Diagnostic] = []
    events: list[DiagnosticEvent] = []
    semantics = descriptor.stem_semantics
    if semantics is None:
        return DiagnosticAssessment((), ())
    assert projection is not None
    primary_route = next(
        (route for route in projection.routes if route.logical_primary),
        None,
    )
    fields = {
        "model_id": descriptor.id,
        "label": primary_route.display if primary_route is not None else None,
        "role": projection.logical_primary_role,
        "native": primary_route.native if primary_route is not None else None,
        "context": projection.context,
        "status": projection.status,
    }
    if projection.status == "raw":
        warning = semantics.warning or "raw-fallback"
        event = "stem_semantics_fallback"
        if warning.startswith("signature-mismatch"):
            event = "stem_semantics_signature_mismatch"
        elif warning.startswith("missing-context"):
            event = "stem_semantics_missing_context"
        events.append(DiagnosticEvent("model", event, "warning", {"reason": warning, **fields}))
        diagnostics.append(
            Diagnostic(
                f"stems.semantics_{event.removeprefix('stem_semantics_')}",
                f"Exact stem semantics unavailable for {descriptor.id}; using raw outputs",
                "warning",
                details=projection.as_dict(),
            )
        )
    else:
        events.append(DiagnosticEvent("model", "stem_semantics_routing", "debug", fields))
    return DiagnosticAssessment(tuple(diagnostics), tuple(events))


@dataclass(frozen=True)
class PairEvidence:
    pair_id: str
    definition: StemPairDefinition | None


def assess_ensemble_pair(
    settings: Settings,
    descriptors: Sequence[ModelDescriptor],
    *,
    command: str,
    evidence: PairEvidence | None,
) -> DiagnosticAssessment:
    """Require an explicit, viable reviewed pair before an ensemble can run."""
    events: list[DiagnosticEvent] = []
    if command != 'ensemble':
        return DiagnosticAssessment((), tuple(events))
    assert evidence is not None
    pair_id = evidence.pair_id
    pair = evidence.definition
    if not pair_id:
        events.append(
            DiagnosticEvent(
                'ensemble',
                'invalid_stem_pair',
                'warning',
                {'pair_id': str(settings.ensemble.main_stem or '') or None},
            )
        )
        return DiagnosticAssessment(
            (
                Diagnostic(
                    'ensemble.pair_repick',
                    'Choose a reviewed ensemble stem pair or mode before running the ensemble',
                    path='ensemble.main_stem',
                ),
            ),
            tuple(events),
        )
    if pair is None or not descriptors:
        return DiagnosticAssessment((), tuple(events))
    required = frozenset(pair.roles)
    eligible_members: set[str] = set()
    incomplete_members: list[str] = []
    for index, descriptor in enumerate(descriptors, start=1):
        member_roles = {
            route.role for route in descriptor.routes if isinstance(route.role, StemRoleId)
        }
        member_name = descriptor.id or descriptor.display or f'member {index}'
        if descriptor.id and required.issubset(member_roles):
            eligible_members.add(descriptor.id)
        else:
            incomplete_members.append(member_name)
    if incomplete_members:
        events.append(
            DiagnosticEvent(
                'ensemble',
                'invalid_stem_pair',
                'warning',
                {'pair_id': pair.id, 'incomplete_count': len(incomplete_members)},
            )
        )
        return DiagnosticAssessment(
            (
                Diagnostic(
                    'ensemble.pair_repick',
                    f"Every selected member needs complete reviewed role coverage for {pair.id!r}; incomplete: {', '.join(incomplete_members)}. Choose a stem pair again",
                    path='ensemble.main_stem',
                ),
            ),
            tuple(events),
        )
    if len(eligible_members) >= 2:
        return DiagnosticAssessment((), tuple(events))
    events.append(
        DiagnosticEvent(
            'ensemble',
            'invalid_stem_pair',
            'warning',
            {'pair_id': pair.id, 'eligible_count': len(eligible_members)},
        )
    )
    return DiagnosticAssessment(
        (
            Diagnostic(
                'ensemble.pair_repick',
                f'The selected pair {pair.id!r} needs two distinct installed models with complete reviewed role coverage; choose a stem pair again',
                path='ensemble.main_stem',
            ),
        ),
        tuple(events),
    )


@dataclass(frozen=True)
class FocusEvidence:
    focus: str
    selection: StemSelection
    label: str = ""
    severity: str = "warning"
    ensemble: bool = False
    available_labels: tuple[str, ...] = ()


def assess_stem_focus(evidence: FocusEvidence) -> list[Diagnostic]:
    """Assess immutable route-selection evidence without accessing model state."""
    focus, selection = evidence.focus, evidence.selection
    if selection.status is StemSelectionStatus.MATCHED:
        return []
    if evidence.ensemble:
        insufficient = selection.status is StemSelectionStatus.INSUFFICIENT_MEMBERS
        # Ensemble diagnostics display route labels, supplied by the observer.
        available = evidence.label or "none"
        return [
            Diagnostic(
                "stems.focus_insufficient_members" if insufficient else "stems.focus_unmatched",
                (
                    f"stem focus {focus!r} has fewer than two ensemble contributors"
                    if insufficient
                    else f"stem focus {focus!r} matches no ensemble output"
                )
                + f" (available: {available}); exporting all stems",
                evidence.severity,
            )
        ]
    stems = ", ".join(evidence.available_labels)
    return [
        Diagnostic(
            "stems.focus_unmatched",
            f"stem focus {focus!r} matches no stem of {evidence.label}"
            + (f" (has {stems}); exporting all stems" if stems else "; exporting all stems"),
            evidence.severity,
        )
    ]


def stem_focus_diagnostics(
    settings: Settings,
    models: Sequence[Any],
    descriptors: Sequence[ModelDescriptor],
    provenance: Mapping[str, str] | None = None,
    *,
    command: str = "separate",
) -> list[Diagnostic]:
    """Observe fallback routes and assess each member before observing the next."""
    focus = str(settings.process.stem_focus or "")
    if not focus or positional_stem_focus(focus):
        return []
    severity = (
        "error"
        if (provenance or {}).get("process.stem_focus", "") == Provenance.CLI.value
        else "warning"
    )
    if command == "ensemble":
        routes, union = collect_ensemble_routes(settings, descriptors)
        selection = select_ensemble_stem_routes(routes, union, focus)
        if selection.status is StemSelectionStatus.MATCHED:
            return []
        return assess_stem_focus(
            FocusEvidence(
                focus, selection, ", ".join(route.label for route in routes), severity, True
            )
        )
    diagnostics = []
    for index, model in enumerate(models):
        if getattr(model, "is_vocal_split_model", False):
            continue
        routes = (
            descriptors[index].routes
            if index < len(descriptors) and descriptors[index].routes
            else model_stem_routes(model)
        )
        selection = select_stem_routes(routes, focus)
        if selection.status is StemSelectionStatus.MATCHED:
            continue
        label = (
            descriptors[index].display
            if index < len(descriptors)
            else getattr(model, "model_basename", "") or "model"
        )
        # Keep display labels separate from concept availability used by selection.
        evidence = FocusEvidence(
            focus,
            selection,
            label,
            severity,
            available_labels=tuple(route.label for route in routes),
        )
        diagnostics.extend(assess_stem_focus(evidence))
    return diagnostics


def emit_assessment(assessment: DiagnosticAssessment) -> tuple[Diagnostic, ...]:
    from .debug_log import log_event

    for event in assessment.events:
        log_event(event.category, event.name, level=event.level, **event.fields)
    return assessment.diagnostics


def stem_semantics_diagnostics(descriptors: Sequence[ModelDescriptor]) -> list[Diagnostic]:
    diagnostics = []
    for descriptor in descriptors:
        # Deliver each event before assessing the next descriptor, including on failure.
        projection = (
            stem_semantics_projection(
                descriptor.stem_semantics,
                backend_primary=(descriptor.backend_primary_stem or descriptor.primary_stem),
                backend_target=descriptor.backend_target_stem,
            )
            if descriptor.stem_semantics is not None
            else None
        )
        diagnostics.extend(emit_assessment(assess_stem_semantics(descriptor, projection)))
    return diagnostics


def ensemble_pair_diagnostics(
    settings: Settings, descriptors: Sequence[ModelDescriptor], *, command: str
) -> tuple[Diagnostic, ...]:
    evidence = None
    if command == "ensemble":
        pair_id = normalize_stem_pair_id(settings.ensemble.main_stem)
        evidence = PairEvidence(pair_id, stem_pair_definition(pair_id))
    return emit_assessment(
        assess_ensemble_pair(settings, descriptors, command=command, evidence=evidence)
    )


def assess_inputs(
    inputs: Sequence[str], output: str, present: Sequence[bool]
) -> tuple[Diagnostic, ...]:
    diagnostics = []
    if not inputs:
        diagnostics.append(Diagnostic("inputs.empty", "Select at least one input file"))
    for path, exists in zip(inputs, present, strict=False):
        if not exists:
            diagnostics.append(Diagnostic("input.missing", f"Input not found: {path}", path=path))
    if not output:
        diagnostics.append(Diagnostic("output.empty", "Choose an output folder"))
    return tuple(diagnostics)


def runtime_diagnostics(settings: Settings, probes: PlanningProbes) -> tuple[Diagnostic, ...]:
    missing = probes.missing_runtime_packages()
    if missing:
        return (
            Diagnostic("runtime.dependencies", f"Missing Python packages: {', '.join(missing)}"),
        )
    return tuple(probes.device_diagnostics(settings))
