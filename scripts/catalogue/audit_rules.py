"""Audit rules for the one-snapshot catalogue publication pipeline."""

from __future__ import annotations

import unicodedata
from collections import defaultdict
from typing import (
    Any,
    Iterable,
    Mapping,
    Sequence,
)

from catalogue.audit_types import (
    _COMPLEMENT_ONLY_NAMES,
    CatalogueEvidenceCounts,
    ContextAssessment,
    ModelContextAssessment,
    StemAuditDiagnostic,
    _ContextRoleProjection,
)
from catalogue.evidence import catalogue_identity_inputs
from catalogue.types import ModelEntry
from core.catalogue_identity import catalogue_model_id
from core.model_stem_manifest import StemSemanticsRegistry, _ModelStemContext, _ModelStemDeclaration
from core.stem_roles import (
    ModelStemSemantics,
    StemProcessingContext,
    StemProduction,
    StemReviewStatus,
    StemRoleId,
)


def _audit_key(value: object) -> str:
    return unicodedata.normalize("NFKC", str(value or "")).strip().casefold()


def _signature_matches(expected: Sequence[str], actual: Sequence[str]) -> bool:
    expected_keys = tuple(_audit_key(value) for value in expected)
    actual_keys = tuple(_audit_key(value) for value in actual)
    return len(expected_keys) == len(actual_keys) and set(expected_keys) == set(actual_keys)


def _sorted_model_ids(model_ids: Iterable[str]) -> tuple[str, ...]:
    return tuple(sorted(set(model_ids), key=lambda value: (value.casefold(), value)))


def _catalogue_model_id(entry: ModelEntry) -> str:
    family, selection, files, meta = catalogue_identity_inputs(entry)
    model_id = catalogue_model_id(family, selection, files, meta)
    if model_id is None:
        raise ValueError(
            f"catalogue row has no unambiguous presentation primary: {entry.catalogue_label!r}"
        )
    return model_id


def _community_stem_tokens(stems_text: str) -> tuple[str, ...]:
    tokens = []
    for raw in stems_text.split(","):
        token = raw.replace("*", "").strip()
        token = token.split("(", 1)[0].strip()
        if token and token.casefold() != "unknown":
            tokens.append(token)
    return tuple(tokens)


def catalogue_evidence_counts(
    entries: Sequence[ModelEntry], community_by_file: Mapping[str, Any]
) -> CatalogueEvidenceCounts:
    """Measure the approved evidence universe without inventing semantics."""
    current_files = {str(entry.weight_file).casefold() for entry in entries}
    literals = set(_COMPLEMENT_ONLY_NAMES)
    primary = set()
    community_tokens = set()
    for entry in entries:
        literals.update(str(stem) for stem in entry.instruments if str(stem))
        if entry.primary_stem:
            value = str(entry.primary_stem)
            literals.add(value)
            primary.add(value.casefold())
        if entry.target_instrument:
            literals.add(str(entry.target_instrument))
    for filename, reference in community_by_file.items():
        if filename.casefold() not in current_files:
            continue
        for token in _community_stem_tokens(str(reference.stems_text)):
            literals.add(token)
            community_tokens.add(token)
    return CatalogueEvidenceCounts(
        literal_names=len(literals),
        normalized_names=len({value.casefold() for value in literals}),
        primary_names=len(primary),
        community_tokens=tuple(sorted(community_tokens, key=str.casefold)),
    )


def _context_value(raw_context: object) -> StemProcessingContext | None:
    try:
        if isinstance(raw_context, StemProcessingContext):
            return raw_context
        return StemProcessingContext(str(raw_context))
    except ValueError:
        return None


def _output_role(output: Any) -> str:
    return str(output.role)


def _native_outputs(context: Any) -> tuple[Any, ...]:
    return tuple(output for output in context.outputs if output.native is not None)


def _derived_outputs(context: Any) -> tuple[Any, ...]:
    return tuple(output for output in context.outputs if output.native is None)


def _diagnostic_sort_key(
    diagnostic: StemAuditDiagnostic,
) -> tuple[str, tuple[str, ...], str, str]:
    context = diagnostic.context.value if diagnostic.context is not None else ""
    return diagnostic.code, diagnostic.model_ids, context, diagnostic.message


def _role_users(registry: StemSemanticsRegistry) -> Mapping[str, set[str]]:
    users: dict[str, set[str]] = defaultdict(set)
    for model_id, declaration in registry.models.items():
        for context in declaration.contexts.values():
            for output in context.outputs:
                users[_output_role(output)].add(model_id)
    return users


def _affected_role_users(
    roles: Iterable[object],
    users: Mapping[str, set[str]],
    catalogue_model_ids: tuple[str, ...],
) -> tuple[str, ...]:
    affected = {model_id for role in roles for model_id in users.get(str(role), set())}
    return _sorted_model_ids(affected) or catalogue_model_ids


def _role_collision_diagnostics(
    registry: StemSemanticsRegistry,
    catalogue_model_ids: tuple[str, ...],
) -> list[StemAuditDiagnostic]:
    users = _role_users(registry)
    diagnostics = []
    for field_name, code in (
        ("display", "role-display-collision"),
        ("filename_tag", "role-tag-collision"),
    ):
        grouped: dict[str, list[object]] = defaultdict(list)
        for role_id, definition in registry.roles.items():
            grouped[_audit_key(getattr(definition, field_name))].append(role_id)
        for normalized_value, roles in grouped.items():
            if len(roles) < 2:
                continue
            role_ids = tuple(sorted((str(role) for role in roles), key=str.casefold))
            diagnostics.append(
                StemAuditDiagnostic(
                    code=code,
                    model_ids=_affected_role_users(roles, users, catalogue_model_ids),
                    message=(
                        f"roles {', '.join(role_ids)} share normalized {field_name} "
                        f"{normalized_value!r}"
                    ),
                    actual=role_ids,
                )
            )
    return diagnostics


def _unused_role_diagnostics(
    registry: StemSemanticsRegistry,
    catalogue_model_ids: tuple[str, ...],
) -> list[StemAuditDiagnostic]:
    used = {
        output.role
        for declaration in registry.models.values()
        for context in declaration.contexts.values()
        for output in context.outputs
        if isinstance(output.role, StemRoleId)
    }
    used.update(role for pair in registry.pairs.values() for role in pair.roles)
    unused = tuple(sorted((str(role) for role in set(registry.roles) - used), key=str.casefold))
    if not unused:
        return []
    return [
        StemAuditDiagnostic(
            code="role-unused",
            model_ids=catalogue_model_ids,
            message="role definitions must be used by a context output or pair",
            actual=unused,
        )
    ]


def _route_collision_diagnostics(
    model_id: str,
    context: StemProcessingContext,
    outputs: Sequence[Any],
    registry: StemSemanticsRegistry,
) -> list[StemAuditDiagnostic]:
    diagnostics = []
    for field_name, code in (
        ("display", "route-display-collision"),
        ("filename_tag", "route-tag-collision"),
    ):
        grouped: dict[str, list[str]] = defaultdict(list)
        for output in outputs:
            if not isinstance(output.role, StemRoleId):
                continue
            definition = registry.roles.get(output.role)
            if definition is None:
                continue
            grouped[_audit_key(getattr(definition, field_name))].append(str(output.role))
        for normalized, roles in grouped.items():
            role_ids = tuple(sorted(set(roles), key=str.casefold))
            if len(role_ids) < 2:
                continue
            diagnostics.append(
                StemAuditDiagnostic(
                    code=code,
                    model_ids=(model_id,),
                    context=context,
                    message=(
                        f"routes {', '.join(role_ids)} share normalized {field_name} "
                        f"{normalized!r} in one rendered context"
                    ),
                    actual=role_ids,
                )
            )
    return diagnostics


def _pair_diagnostics(
    registry: StemSemanticsRegistry,
    catalogue_model_ids: tuple[str, ...],
    context_projections: Sequence[_ContextRoleProjection],
) -> list[StemAuditDiagnostic]:
    users = _role_users(registry)
    diagnostics = []
    pair_ids_by_role: dict[str, list[str]] = defaultdict(list)
    for pair_id, pair in registry.pairs.items():
        roles = tuple(pair.roles)
        for role in roles:
            pair_ids_by_role[str(role)].append(pair_id)
        present = tuple(role for role in roles if role in registry.roles)
        definition_is_complete = len(roles) == 2 and roles[0] != roles[1] and len(present) == 2
        if not definition_is_complete:
            diagnostics.append(
                StemAuditDiagnostic(
                    code="pair-incomplete",
                    model_ids=_affected_role_users(roles, users, catalogue_model_ids),
                    message=f"{pair_id} must define two distinct existing roles",
                    expected=tuple(str(role) for role in roles),
                    actual=tuple(str(role) for role in present),
                )
            )
            continue
        expected_roles = tuple(str(role) for role in roles)
        expected_role_set = frozenset(expected_roles)
        for projection in context_projections:
            if not expected_role_set.issubset(projection.declared_roles):
                continue
            if expected_role_set.issubset(projection.resolved_roles):
                continue
            diagnostics.append(
                StemAuditDiagnostic(
                    code="pair-context-incomplete",
                    model_ids=(projection.model_id,),
                    context=projection.context,
                    message=f"{pair_id} resolved without every declared pair role",
                    expected=expected_roles,
                    actual=tuple(
                        role for role in expected_roles if role in projection.resolved_roles
                    ),
                )
            )
    for role, pair_ids in pair_ids_by_role.items():
        if len(pair_ids) < 2:
            continue
        diagnostics.append(
            StemAuditDiagnostic(
                code="pair-role-collision",
                model_ids=_affected_role_users((role,), users, catalogue_model_ids),
                message=f"role {role} belongs to multiple pairs",
                expected=("one pair",),
                actual=tuple(sorted(pair_ids, key=str.casefold)),
            )
        )
    return diagnostics


def _target_projection_diagnostics(
    model_id: str,
    declaration: Any,
    runtime_signature: tuple[str, ...],
) -> list[StemAuditDiagnostic]:
    diagnostics = []
    for raw_context, declared_context in declaration.contexts.items():
        context = _context_value(raw_context)
        if not _signature_matches(declaration.native_signature, runtime_signature):
            diagnostics.append(
                StemAuditDiagnostic(
                    code="target-runtime-signature",
                    model_ids=(model_id,),
                    context=context,
                    message="target-instrument declaration does not match runtime inventory",
                    expected=tuple(declaration.native_signature),
                    actual=runtime_signature,
                )
            )
        native = _native_outputs(declared_context)
        native_names = tuple(output.native.raw for output in native)
        native_is_valid = (
            len(native) == 1
            and native[0].production is StemProduction.NATIVE
            and _signature_matches(native_names, runtime_signature)
        )
        if not native_is_valid:
            diagnostics.append(
                StemAuditDiagnostic(
                    code="target-native-output",
                    model_ids=(model_id,),
                    context=context,
                    message="target context must expose exactly one native runtime source",
                    expected=runtime_signature,
                    actual=native_names,
                )
            )
        derived = _derived_outputs(declared_context)
        native_role = _output_role(native[0]) if len(native) == 1 else ""
        dependency_is_valid = (
            len(derived) == 1
            and str(derived[0].complement_of or "") == native_role
            and not derived[0].derived_from
        )
        if (
            len(derived) != 1
            or derived[0].production is not StemProduction.DERIVED
            or not dependency_is_valid
        ):
            actual_dependencies = tuple(
                str(role)
                for output in derived
                for role in (
                    (output.complement_of,)
                    if output.complement_of is not None
                    else output.derived_from
                )
            )
            diagnostics.append(
                StemAuditDiagnostic(
                    code="target-derived-complement",
                    model_ids=(model_id,),
                    context=context,
                    message=(
                        "target context must expose one derived complement with an explicit "
                        "dependency on its native role"
                    ),
                    expected=(native_role,) if native_role else (),
                    actual=actual_dependencies,
                )
            )
    return diagnostics


def assess_context(
    model_id: str,
    declaration: _ModelStemDeclaration,
    context: StemProcessingContext,
    declared_context: _ModelStemContext,
    resolved: ModelStemSemantics | None,
) -> ContextAssessment:
    """Assess one valid context in declaration and route order."""
    diagnostics: list[StemAuditDiagnostic] = []
    full_mix_reviewed = False
    roles = tuple(_output_role(output) for output in declared_context.outputs)
    if len(set(roles)) != len(roles):
        diagnostics.append(
            StemAuditDiagnostic(
                code="context-duplicate-role",
                model_ids=(model_id,),
                context=context,
                message="processing context maps more than one output to the same role",
                actual=roles,
            )
        )
    logical_primary = str(declared_context.logical_primary)
    primary_count = sum(role == logical_primary for role in roles)
    if primary_count != 1:
        diagnostics.append(
            StemAuditDiagnostic(
                code="context-logical-primary",
                model_ids=(model_id,),
                context=context,
                message="processing context must contain its logical primary exactly once",
                expected=(logical_primary,),
                actual=tuple(role for role in roles if role == logical_primary),
            )
        )
    logical_secondary_value = getattr(declared_context, "logical_secondary", None)
    if logical_secondary_value is not None:
        logical_secondary = str(logical_secondary_value)
        secondary_matches = tuple(role for role in roles if role == logical_secondary)
        if logical_secondary == logical_primary or len(secondary_matches) != 1:
            diagnostics.append(
                StemAuditDiagnostic(
                    code="context-logical-secondary",
                    model_ids=(model_id,),
                    context=context,
                    message=(
                        "processing context logical secondary must be distinct from "
                        "primary and occur exactly once"
                    ),
                    expected=(logical_secondary,),
                    actual=secondary_matches,
                )
            )
    if declaration.intent == "karaoke" and str(logical_secondary_value or "") != "vocal.lead":
        diagnostics.append(
            StemAuditDiagnostic(
                code="context-logical-secondary-required",
                model_ids=(model_id,),
                context=context,
                message="karaoke contexts must declare vocal.lead as logical secondary",
                expected=("vocal.lead",),
                actual=(str(logical_secondary_value),) if logical_secondary_value else (),
            )
        )
    native_names = tuple(output.native.raw for output in _native_outputs(declared_context))
    if not _signature_matches(declaration.native_signature, native_names):
        diagnostics.append(
            StemAuditDiagnostic(
                code="context-native-signature",
                model_ids=(model_id,),
                context=context,
                message="context native outputs do not match the declaration signature",
                expected=tuple(declaration.native_signature),
                actual=native_names,
            )
        )
    if resolved is None:
        projection = _ContextRoleProjection(
            model_id,
            context,
            frozenset(roles),
            frozenset(),
            None,
        )
        diagnostics.append(
            StemAuditDiagnostic(
                code="context-resolution-error",
                model_ids=(model_id,),
                context=context,
                message="reconciled snapshot has no projection for the declared context",
            )
        )
        return ContextAssessment(tuple(diagnostics), projection, False)
    projection = _ContextRoleProjection(
        model_id,
        context,
        frozenset(roles),
        frozenset(
            str(output.role) for output in resolved.outputs if isinstance(output.role, StemRoleId)
        ),
        resolved,
    )
    declared_by_role = {_output_role(output): output for output in declared_context.outputs}
    resolved_by_role = {_output_role(output): output for output in resolved.outputs}
    if tuple(declared_by_role) != tuple(resolved_by_role):
        diagnostics.append(
            StemAuditDiagnostic(
                code="reference-route-set",
                model_ids=(model_id,),
                context=context,
                message="resolved reference routes differ from declared routes or order",
                expected=tuple(declared_by_role),
                actual=tuple(resolved_by_role),
            )
        )
    expected_secondary_role = str(logical_secondary_value or "")
    actual_secondary_role = str(resolved.logical_secondary_role or "")
    if expected_secondary_role != actual_secondary_role:
        diagnostics.append(
            StemAuditDiagnostic(
                code="reference-logical-secondary",
                model_ids=(model_id,),
                context=context,
                message="resolved context has stale logical-secondary role evidence",
                expected=(expected_secondary_role,) if expected_secondary_role else (),
                actual=(actual_secondary_role,) if actual_secondary_role else (),
            )
        )
    for output in resolved.outputs:
        role_id = _output_role(output)
        declared_output = declared_by_role.get(role_id)
        if declared_output is None:
            continue
        expected_native = declared_output.native.raw if declared_output.native else ""
        actual_native = output.native.raw if output.native else ""
        expected_route = (
            expected_native,
            declared_output.production.value,
            str(declared_output.complement_of or ""),
            *(str(role) for role in declared_output.derived_from),
        )
        actual_route = (
            actual_native,
            output.production.value,
            str(output.complement_of or ""),
            *(str(role) for role in output.derived_from),
        )
        if expected_route != actual_route:
            diagnostics.append(
                StemAuditDiagnostic(
                    code="reference-route-data",
                    model_ids=(model_id,),
                    context=context,
                    message="resolved reference route differs from its declaration",
                    expected=expected_route,
                    actual=actual_route,
                )
            )
        expected_primary = role_id == logical_primary
        if type(output.logical_primary) is not bool or (
            output.logical_primary is not expected_primary
        ):
            diagnostics.append(
                StemAuditDiagnostic(
                    code="reference-logical-primary",
                    model_ids=(model_id,),
                    context=context,
                    message="resolved route has stale logical-primary evidence",
                    expected=(str(expected_primary).lower(),),
                    actual=(str(output.logical_primary).lower(),),
                )
            )
        expected_secondary = logical_secondary_value is not None and role_id == str(
            logical_secondary_value
        )
        if type(output.logical_secondary) is not bool or (
            output.logical_secondary is not expected_secondary
        ):
            diagnostics.append(
                StemAuditDiagnostic(
                    code="reference-logical-secondary",
                    model_ids=(model_id,),
                    context=context,
                    message="resolved route has stale logical-secondary evidence",
                    expected=(str(expected_secondary).lower(),),
                    actual=(str(output.logical_secondary).lower(),),
                )
            )
        expected_default = declared_output.selected_by_default
        if (
            type(expected_default) is not bool
            or type(output.selected_by_default) is not bool
            or (output.selected_by_default is not expected_default)
        ):
            diagnostics.append(
                StemAuditDiagnostic(
                    code="reference-selected-by-default",
                    model_ids=(model_id,),
                    context=context,
                    message="resolved route has stale default-selection evidence",
                    expected=(str(expected_default).lower(),),
                    actual=(str(output.selected_by_default).lower(),),
                )
            )
    native_role_ids = {
        _output_role(output) for output in declared_context.outputs if output.native is not None
    }
    for output in declared_context.outputs:
        complement = str(output.complement_of or "")
        dependencies = tuple(str(role) for role in output.derived_from)
        native_recipe_valid = (
            output.production is StemProduction.NATIVE and not complement and not dependencies
        )
        complement_recipe_valid = (
            output.production is StemProduction.DERIVED
            and bool(complement)
            and not dependencies
            and complement in native_role_ids
        )
        derived_recipe_valid = (
            output.production is StemProduction.DERIVED
            and not complement
            and len(dependencies) >= 2
            and len(set(dependencies)) == len(dependencies)
            and set(dependencies).issubset(native_role_ids)
        )
        recipe_valid = (
            native_recipe_valid
            if output.native is not None
            else complement_recipe_valid or derived_recipe_valid
        )
        if recipe_valid:
            continue
        diagnostics.append(
            StemAuditDiagnostic(
                code="context-recipe-invalid",
                model_ids=(model_id,),
                context=context,
                message="route does not satisfy the schema-2 production recipe",
                expected=(
                    (
                        "native route without recipe"
                        if output.native is not None
                        else "two-or-more native role dependencies"
                        if dependencies
                        else "complement_of one native role"
                    ),
                ),
                actual=tuple(filter(None, (complement, *dependencies))),
            )
        )
    if resolved.status is not StemReviewStatus.REVIEWED:
        diagnostics.append(
            StemAuditDiagnostic(
                code="context-unreviewed",
                model_ids=(model_id,),
                context=context,
                message=resolved.warning or "processing context resolved without review",
            )
        )
    elif context is StemProcessingContext.FULL_MIX:
        full_mix_reviewed = True
    return ContextAssessment(tuple(diagnostics), projection, full_mix_reviewed)


def assess_model_contexts(
    model_id: str,
    declaration: _ModelStemDeclaration,
    semantics_by_context: Mapping[StemProcessingContext, ModelStemSemantics],
) -> ModelContextAssessment:
    diagnostics = []
    full_mix_reviewed = False
    projections = []
    if StemProcessingContext.FULL_MIX not in declaration.contexts:
        diagnostics.append(
            StemAuditDiagnostic(
                code="missing-full-mix",
                model_ids=(model_id,),
                context=StemProcessingContext.FULL_MIX,
                message="reviewed declaration has no full_mix context",
            )
        )
    for raw_context, declared_context in declaration.contexts.items():
        context = _context_value(raw_context)
        if context is None:
            diagnostics.append(
                StemAuditDiagnostic(
                    code="context-invalid",
                    model_ids=(model_id,),
                    message=f"declaration contains invalid context {raw_context!r}",
                    actual=(str(raw_context),),
                )
            )
            continue
        assessment = assess_context(
            model_id, declaration, context, declared_context, semantics_by_context.get(context)
        )
        diagnostics.extend(assessment.diagnostics)
        projections.append(assessment.projection)
        full_mix_reviewed = full_mix_reviewed or assessment.full_mix_reviewed
    fully_reviewed = (
        full_mix_reviewed
        and len(projections) == len(declaration.contexts)
        and all(
            projection.semantics is not None
            and projection.semantics.status is StemReviewStatus.REVIEWED
            for projection in projections
        )
    )
    return ModelContextAssessment(tuple(diagnostics), fully_reviewed, tuple(projections))
