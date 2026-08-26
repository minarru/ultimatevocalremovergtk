"""Strict local declarations for exact model-output stem semantics.

The direct loader is deliberately fail-closed: a malformed declaration is a
typed error.  The application-facing bundled loader converts that error into
one startup diagnostic and an empty registry, allowing model execution to
continue through raw, isolated stem outputs.
"""

from __future__ import annotations

import json
import unicodedata
from dataclasses import dataclass, replace
from functools import lru_cache
from pathlib import Path
from types import MappingProxyType
from typing import Mapping, Sequence

from .debug_log import log_event
from .model_identity import parse_stored_model_id
from .model_stem_semantics import MODEL_STEM_INTENTS
from .paths import BUNDLED_DATA_DIR
from .stem_roles import (
    ModelStemSemantics,
    SemanticStemOutput,
    StemId,
    StemLiteral,
    StemProcessingContext,
    StemProduction,
    StemReviewStatus,
    StemRoleDefinition,
    StemRoleFamily,
    StemRoleId,
)

BUNDLED_MANIFEST_PATH = Path(BUNDLED_DATA_DIR) / "model_stem_manifest.json"


class StemManifestError(ValueError):
    """A manifest validation failure annotated with its document path."""

    def __init__(self, path: tuple[str | int, ...], message: str) -> None:
        self.path = path
        self.message = message
        rendered = "".join(
            f"[{part}]" if isinstance(part, int) else ("." if index else "") + part
            for index, part in enumerate(path)
        )
        super().__init__(f"{rendered}: {message}")


@dataclass(frozen=True, slots=True)
class StemPairDefinition:
    """One reviewed two-role semantic ensemble pair."""

    id: str
    display: str
    roles: tuple[StemRoleId, StemRoleId]


@dataclass(frozen=True, slots=True)
class _ModelStemContext:
    logical_primary: StemRoleId
    outputs: tuple[SemanticStemOutput, ...]
    logical_secondary: StemRoleId | None = None


@dataclass(frozen=True, slots=True)
class _ModelStemDeclaration:
    native_signature: tuple[str, ...]
    intent: str
    contexts: Mapping[StemProcessingContext, _ModelStemContext]
    evidence: str


@dataclass(frozen=True, slots=True)
class StemSemanticsRegistry:
    """Immutable collection of direct, locally-reviewed declarations."""

    roles: Mapping[StemRoleId, StemRoleDefinition]
    pairs: Mapping[str, StemPairDefinition]
    models: Mapping[str, _ModelStemDeclaration]
    waivers: Mapping[str, str]

    @classmethod
    def empty(cls) -> StemSemanticsRegistry:
        empty: Mapping[object, object] = MappingProxyType({})
        return cls(empty, empty, empty, empty)  # type: ignore[arg-type]


def _error(path: tuple[str | int, ...], message: str) -> StemManifestError:
    return StemManifestError(path, message)


def _mapping(value: object, path: tuple[str | int, ...]) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise _error(path, "must be an object")
    if any(not isinstance(key, str) for key in value):
        raise _error(path, "keys must be strings")
    return value


def _closed_mapping(
    value: object,
    path: tuple[str | int, ...],
    *,
    required: frozenset[str],
    optional: frozenset[str],
) -> Mapping[str, object]:
    """Return one schema object after enforcing required and allowed fields."""
    document = _mapping(value, path)
    missing = sorted(required.difference(document))
    if missing:
        raise _error(path + (missing[0],), "missing required field")
    unknown = sorted(set(document).difference(required | optional))
    if unknown:
        raise _error(path + (unknown[0],), "unknown field")
    return document


def _strict_bool(value: object, path: tuple[str | int, ...]) -> bool:
    if type(value) is not bool:
        raise _error(path, "must be a boolean")
    return value


def _duplicate_aware_mapping(pairs: list[tuple[str, object]]) -> dict[str, object]:
    """Build one JSON object while rejecting keys the decoder would overwrite."""
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            # ``object_pairs_hook`` visits nested objects before their parents,
            # so the complete path is unavailable. Preserve the exact key.
            raise _error(("manifest",), f"duplicate key {key!r}")
        result[key] = value
    return result


def _string(value: object, path: tuple[str | int, ...]) -> str:
    if not isinstance(value, str) or not value.strip():
        raise _error(path, "must be a non-empty string")
    return value


def _role_id(value: object, path: tuple[str | int, ...]) -> StemRoleId:
    try:
        return StemRoleId(_string(value, path))
    except ValueError as error:
        raise _error(path, str(error)) from error


def _normalized(value: str) -> str:
    return unicodedata.normalize("NFKC", value).strip().casefold()


def _native_key(value: str) -> str:
    return value.strip().casefold()


def _canonical_model_id(value: str, path: tuple[str | int, ...]) -> str:
    try:
        return parse_stored_model_id(value).value
    except ValueError as error:
        raise _error(path, f"invalid canonical model ID: {error}") from error


def _parse_roles(value: object) -> Mapping[StemRoleId, StemRoleDefinition]:
    document = _mapping(value, ("roles",))
    result: dict[StemRoleId, StemRoleDefinition] = {}
    pending_removed: dict[StemRoleId, tuple[StemRoleDefinition, object, tuple[str | int, ...]]] = {}
    displays: dict[str, StemRoleId] = {}
    filename_tags: dict[str, StemRoleId] = {}
    for raw_id, raw_definition in document.items():
        path = ("roles", raw_id)
        role_id = _role_id(raw_id, path)
        definition = _closed_mapping(
            raw_definition,
            path,
            required=frozenset({"display", "filename_tag", "family"}),
            optional=frozenset({"removed_of"}),
        )
        display = _string(definition["display"], path + ("display",))
        filename_tag = _string(definition["filename_tag"], path + ("filename_tag",))
        try:
            family = StemRoleFamily(_string(definition["family"], path + ("family",)))
        except ValueError as error:
            raise _error(path + ("family",), "invalid stem role family") from error
        if role_id.value.partition(".")[0] != family.value:
            raise _error(path + ("family",), "role namespace must match declared family")
        normalized_display = _normalized(display)
        if normalized_display in displays:
            raise _error(path + ("display",), "duplicate role display")
        normalized_tag = _normalized(filename_tag)
        if normalized_tag in filename_tags:
            raise _error(path + ("filename_tag",), "duplicate filename tag")
        displays[normalized_display] = role_id
        filename_tags[normalized_tag] = role_id
        parsed = StemRoleDefinition(role_id, display, filename_tag, family)
        result[role_id] = parsed
        if "removed_of" in definition:
            pending_removed[role_id] = (
                parsed,
                definition["removed_of"],
                path + ("removed_of",),
            )
    for role_id, (definition, raw_removed_of, path) in pending_removed.items():
        removed_of = _role_id(raw_removed_of, path)
        if removed_of not in result:
            raise _error(path, "missing role reference")
        result[role_id] = replace(definition, removed_of=removed_of)
    _validate_removed_graph(result)
    return MappingProxyType(result)


def _validate_removed_graph(roles: Mapping[StemRoleId, StemRoleDefinition]) -> None:
    """Validate exact, same-family, acyclic ``removed_of`` relationships."""
    for role_id, definition in roles.items():
        removed_of = definition.removed_of
        if removed_of is None:
            continue
        path = ("roles", role_id.value, "removed_of")
        if removed_of == role_id:
            raise _error(path, "removed_of cannot reference itself")
        target = roles.get(removed_of)
        if target is None:
            raise _error(path, "missing role reference")
        if target.family is not definition.family:
            raise _error(path, "removed_of roles must belong to the same family")

    visiting: set[StemRoleId] = set()
    visited: set[StemRoleId] = set()

    def visit(role_id: StemRoleId) -> None:
        if role_id in visited:
            return
        if role_id in visiting:
            raise _error(("roles", role_id.value, "removed_of"), "removed_of cycle")
        visiting.add(role_id)
        removed_of = roles[role_id].removed_of
        if removed_of is not None:
            visit(removed_of)
        visiting.remove(role_id)
        visited.add(role_id)

    for role_id in roles:
        visit(role_id)

    for role_id, definition in roles.items():
        removed_of = definition.removed_of
        if removed_of is not None and role_id.value != f"{removed_of.value}.removed":
            raise _error(
                ("roles", role_id.value, "removed_of"),
                "removed role id must use reciprocal .removed naming",
            )


def _parse_pairs(
    value: object, roles: Mapping[StemRoleId, StemRoleDefinition]
) -> Mapping[str, StemPairDefinition]:
    document = _mapping(value, ("pairs",))
    result: dict[str, StemPairDefinition] = {}
    for pair_id, raw_pair in document.items():
        path = ("pairs", pair_id)
        if not pair_id.startswith("pair."):
            raise _error(path, "pair id must be namespaced with pair.")
        pair = _closed_mapping(
            raw_pair,
            path,
            required=frozenset({"display", "roles"}),
            optional=frozenset(),
        )
        display = _string(pair["display"], path + ("display",))
        raw_roles = pair["roles"]
        if not isinstance(raw_roles, list) or len(raw_roles) != 2:
            raise _error(path + ("roles",), "must contain exactly two roles")
        parsed_roles = tuple(
            _role_id(raw_role, path + ("roles", index)) for index, raw_role in enumerate(raw_roles)
        )
        if parsed_roles[0] == parsed_roles[1]:
            raise _error(path + ("roles",), "roles must be distinct")
        for index, role in enumerate(parsed_roles):
            if role not in roles:
                raise _error(path + ("roles", index), "missing pair role reference")
        result[pair_id] = StemPairDefinition(pair_id, display, parsed_roles)  # type: ignore[arg-type]
    return MappingProxyType(result)


def _parse_output(
    value: object,
    path: tuple[str | int, ...],
    roles: Mapping[StemRoleId, StemRoleDefinition],
) -> SemanticStemOutput:
    raw_output = _mapping(value, path)
    if "native" not in raw_output:
        raise _error(path + ("native",), "missing native key")
    output = _closed_mapping(
        raw_output,
        path,
        required=frozenset({"native", "role"}),
        optional=frozenset({"production", "selected_by_default", "derived_from", "complement_of"}),
    )
    role = _role_id(output["role"], path + ("role",))
    if role not in roles:
        raise _error(path + ("role",), "missing role reference")
    native_value = output["native"]
    native = StemId(_string(native_value, path + ("native",))) if native_value is not None else None
    if native is None and "production" not in output:
        raise _error(path + ("production",), "missing required field")
    default_production = (
        StemProduction.NATIVE.value if native is not None else StemProduction.DERIVED.value
    )
    try:
        production = StemProduction(output.get("production", default_production))
    except ValueError as error:
        raise _error(path + ("production",), "invalid production") from error
    selected_by_default = (
        _strict_bool(output["selected_by_default"], path + ("selected_by_default",))
        if "selected_by_default" in output
        else True
    )
    has_derived_from = "derived_from" in output
    has_complement_of = "complement_of" in output
    if native is not None:
        if production is not StemProduction.NATIVE:
            raise _error(path + ("production",), "native output must use native production")
        if has_derived_from:
            raise _error(path + ("derived_from",), "native output has dependency")
        if has_complement_of:
            raise _error(path + ("complement_of",), "native output has dependency")
        return SemanticStemOutput(
            native=native,
            role=role,
            production=production,
            backend_primary=False,
            logical_primary=False,
            selected_by_default=selected_by_default,
        )
    if production is not StemProduction.DERIVED:
        raise _error(path + ("production",), "derived output must use derived production")
    if has_derived_from == has_complement_of:
        raise _error(path, "derived output requires exactly one dependency form")
    if has_derived_from:
        raw_dependencies = output["derived_from"]
        if not isinstance(raw_dependencies, list):
            raise _error(path + ("derived_from",), "must be a role list")
        dependencies = tuple(
            _role_id(dependency, path + ("derived_from", index))
            for index, dependency in enumerate(raw_dependencies)
        )
        if any(dependency not in roles for dependency in dependencies):
            raise _error(path + ("derived_from",), "missing role reference")
        return SemanticStemOutput(
            native=None,
            role=role,
            production=production,
            backend_primary=False,
            logical_primary=False,
            derived_from=dependencies,
            selected_by_default=selected_by_default,
        )
    complement = _role_id(output["complement_of"], path + ("complement_of",))
    if complement not in roles:
        raise _error(path + ("complement_of",), "missing role reference")
    return SemanticStemOutput(
        native=None,
        role=role,
        production=production,
        backend_primary=False,
        logical_primary=False,
        complement_of=complement,
        selected_by_default=selected_by_default,
    )


def _validate_context_dependencies(
    outputs: tuple[SemanticStemOutput, ...],
    path: tuple[str | int, ...],
) -> None:
    """Validate derived recipes against exact native roles in one context."""
    roles = {output.role for output in outputs}
    native_roles = {output.role for output in outputs if output.native is not None}
    for index, output in enumerate(outputs):
        if output.native is not None:
            continue
        if output.complement_of is not None:
            dependency = output.complement_of
            dependency_path = path + ("outputs", index, "complement_of")
            if dependency == output.role:
                raise _error(dependency_path, "self-dependency is forbidden")
            if dependency not in roles:
                raise _error(dependency_path, "dependency role is not an output in this context")
            if dependency not in native_roles:
                raise _error(dependency_path, "dependency must identify exactly one native output")
            continue

        dependency_path = path + ("outputs", index, "derived_from")
        if len(output.derived_from) < 2:
            raise _error(dependency_path, "must contain at least two distinct native roles")
        if len(set(output.derived_from)) != len(output.derived_from):
            raise _error(dependency_path, "duplicate dependency")
        for dependency_index, dependency in enumerate(output.derived_from):
            item_path = dependency_path + (dependency_index,)
            if dependency == output.role:
                raise _error(item_path, "self-dependency is forbidden")
            if dependency not in roles:
                raise _error(item_path, "dependency role is not an output in this context")
            if dependency not in native_roles:
                raise _error(item_path, "dependency must identify a native output")


def _parse_models(
    value: object, roles: Mapping[StemRoleId, StemRoleDefinition]
) -> Mapping[str, _ModelStemDeclaration]:
    document = _mapping(value, ("models",))
    result: dict[str, _ModelStemDeclaration] = {}
    for model_id, raw_model in document.items():
        path = ("models", model_id)
        canonical_model_id = _canonical_model_id(model_id, path)
        model = _closed_mapping(
            raw_model,
            path,
            required=frozenset({"native_signature", "intent", "contexts", "evidence"}),
            optional=frozenset(),
        )
        raw_signature = model["native_signature"]
        if not isinstance(raw_signature, list):
            raise _error(path + ("native_signature",), "must be a list")
        signature = tuple(
            _string(native, path + ("native_signature", index))
            for index, native in enumerate(raw_signature)
        )
        normalized_signature = tuple(_native_key(native) for native in signature)
        if not signature:
            raise _error(path + ("native_signature",), "must contain at least one native key")
        if len(set(normalized_signature)) != len(normalized_signature):
            raise _error(path + ("native_signature",), "duplicate native key")
        intent = _string(model["intent"], path + ("intent",))
        if intent not in MODEL_STEM_INTENTS:
            raise _error(path + ("intent",), "invalid model stem intent")
        evidence = _string(model["evidence"], path + ("evidence",))
        raw_contexts = _mapping(model["contexts"], path + ("contexts",))
        if not raw_contexts:
            raise _error(path + ("contexts",), "must contain at least one context")
        contexts: dict[StemProcessingContext, _ModelStemContext] = {}
        for raw_context, raw_context_value in raw_contexts.items():
            context_path = path + ("contexts", raw_context)
            try:
                context = StemProcessingContext(raw_context)
            except ValueError as error:
                raise _error(context_path, "invalid processing context") from error
            context_value = _closed_mapping(
                raw_context_value,
                context_path,
                required=frozenset({"logical_primary", "outputs"}),
                optional=frozenset({"logical_secondary"}),
            )
            logical_primary = _role_id(
                context_value["logical_primary"], context_path + ("logical_primary",)
            )
            if logical_primary not in roles:
                raise _error(context_path + ("logical_primary",), "missing logical primary role")
            logical_secondary = (
                _role_id(
                    context_value["logical_secondary"],
                    context_path + ("logical_secondary",),
                )
                if "logical_secondary" in context_value
                else None
            )
            if logical_secondary is not None:
                if logical_secondary not in roles:
                    raise _error(
                        context_path + ("logical_secondary",),
                        "missing logical secondary role",
                    )
                if logical_secondary == logical_primary:
                    raise _error(
                        context_path + ("logical_secondary",),
                        "logical secondary must be distinct from logical primary",
                    )
            raw_outputs = context_value["outputs"]
            if not isinstance(raw_outputs, list) or not raw_outputs:
                raise _error(context_path + ("outputs",), "must be a non-empty list")
            outputs = tuple(
                _parse_output(raw_output, context_path + ("outputs", index), roles)
                for index, raw_output in enumerate(raw_outputs)
            )
            native_outputs = tuple(
                output.native.raw for output in outputs if output.native is not None
            )
            normalized_natives = tuple(_native_key(native) for native in native_outputs)
            if len(set(normalized_natives)) != len(normalized_natives):
                raise _error(context_path + ("outputs",), "duplicate case-folded native key")
            if len(native_outputs) != len(signature) or set(normalized_natives) != set(
                normalized_signature
            ):
                raise _error(
                    context_path + ("outputs",), "native outputs must match native signature"
                )
            primary_indexes = [
                index for index, output in enumerate(outputs) if output.role == logical_primary
            ]
            if not primary_indexes:
                raise _error(context_path + ("logical_primary",), "missing logical primary output")
            if len(primary_indexes) > 1:
                raise _error(
                    context_path + ("outputs", primary_indexes[1], "role"),
                    "multiple logical primaries",
                )
            if logical_secondary is not None:
                secondary_count = sum(output.role == logical_secondary for output in outputs)
                if secondary_count != 1:
                    raise _error(
                        context_path + ("logical_secondary",),
                        "logical secondary role must occur exactly once in outputs",
                    )
            seen_roles: dict[StemRoleId | StemLiteral, int] = {}
            for index, output in enumerate(outputs):
                previous = seen_roles.get(output.role)
                if previous is not None:
                    raise _error(
                        context_path + ("outputs", index, "role"),
                        f"duplicate role id; first declared at outputs[{previous}]",
                    )
                seen_roles[output.role] = index
            _validate_context_dependencies(outputs, context_path)
            contexts[context] = _ModelStemContext(
                logical_primary=logical_primary,
                outputs=outputs,
                logical_secondary=logical_secondary,
            )
        result[canonical_model_id] = _ModelStemDeclaration(
            signature, intent, MappingProxyType(contexts), evidence
        )
    return MappingProxyType(result)


def _parse_waivers(value: object) -> Mapping[str, str]:
    document = _mapping(value, ("waivers",))
    result: dict[str, str] = {}
    for model_id, reason in document.items():
        path = ("waivers", model_id)
        canonical_model_id = _canonical_model_id(model_id, path)
        result[canonical_model_id] = _string(reason, path)
    return MappingProxyType(result)


def load_stem_manifest_document(document: object) -> StemSemanticsRegistry:
    """Validate one complete manifest document without any application fallback."""
    root = _closed_mapping(
        document,
        (),
        required=frozenset({"schema_version", "roles", "pairs", "models", "waivers"}),
        optional=frozenset(),
    )
    schema_version = root["schema_version"]
    if type(schema_version) is not int or schema_version != 2:
        raise _error(("schema_version",), "must be the exact integer 2")
    roles = _parse_roles(root["roles"])
    pairs = _parse_pairs(root["pairs"], roles)
    models = _parse_models(root["models"], roles)
    waivers = _parse_waivers(root["waivers"])
    overlap = sorted(set(models).intersection(waivers))
    if overlap:
        raise _error(
            ("waivers", overlap[0]),
            "canonical model ID cannot appear in both models and waivers",
        )
    return StemSemanticsRegistry(roles, pairs, models, waivers)


def load_stem_manifest(path: Path) -> StemSemanticsRegistry:
    """Read and strictly validate a JSON manifest from ``path``."""
    try:
        document = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=_duplicate_aware_mapping,
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise _error(("manifest",), f"could not read manifest: {error}") from error
    return load_stem_manifest_document(document)


@lru_cache(maxsize=1)
def load_bundled_stem_semantics() -> StemSemanticsRegistry:
    """Load bundled declarations once, failing closed to raw runtime behavior."""
    try:
        return load_stem_manifest(BUNDLED_MANIFEST_PATH)
    except StemManifestError as error:
        log_event("model", "stem_manifest_invalid", level="error", error=str(error))
        return StemSemanticsRegistry.empty()


def _signature_text(signature: Sequence[str]) -> str:
    return (
        "["
        + ", ".join(repr(value) for value in sorted(_native_key(value) for value in signature))
        + "]"
    )


def _raw_semantics(
    model_id: str,
    native_stems: Sequence[str],
    backend_primary: str,
    context: StemProcessingContext,
    reason: str,
) -> ModelStemSemantics:
    primary = _native_key(backend_primary)
    outputs = tuple(
        SemanticStemOutput(
            native=StemId(native),
            role=StemLiteral(native),
            production=StemProduction.NATIVE,
            backend_primary=bool(primary) and _native_key(native) == primary,
            logical_primary=False,
        )
        for native in native_stems
    )
    return ModelStemSemantics(
        model_id=model_id,
        context=context,
        intent="",
        outputs=outputs,
        status=StemReviewStatus.RAW,
        evidence="",
        warning=reason,
    )


def resolve_model_stem_semantics(
    model_id: str,
    *,
    native_stems: Sequence[str],
    backend_primary: str = "",
    backend_target: str = "",
    context: StemProcessingContext = StemProcessingContext.FULL_MIX,
    registry: StemSemanticsRegistry | None = None,
) -> ModelStemSemantics:
    """Resolve one exact declaration, otherwise preserve raw isolated outputs.

    ``backend_target`` is accepted to keep the resolver's execution-boundary
    contract explicit; reviewed matching intentionally does not infer from it.
    """
    del backend_target
    selected_registry = registry if registry is not None else load_bundled_stem_semantics()
    declaration = selected_registry.models.get(model_id)
    if declaration is None:
        return _raw_semantics(model_id, native_stems, backend_primary, context, "unknown-model")
    actual = tuple(str(native) for native in native_stems)
    actual_keys = tuple(_native_key(native) for native in actual)
    expected_keys = tuple(_native_key(native) for native in declaration.native_signature)
    if len(actual_keys) != len(expected_keys) or set(actual_keys) != set(expected_keys):
        return _raw_semantics(
            model_id,
            actual,
            backend_primary,
            context,
            "signature-mismatch "
            f"expected={_signature_text(declaration.native_signature)} "
            f"actual={_signature_text(actual)}",
        )
    selected_context = declaration.contexts.get(context)
    if selected_context is None:
        return _raw_semantics(
            model_id,
            actual,
            backend_primary,
            context,
            "missing-context "
            f"context={context.value} expected={_signature_text(declaration.native_signature)} "
            f"actual={_signature_text(actual)}",
        )
    actual_by_key = {_native_key(native): native for native in actual}
    primary_key = _native_key(backend_primary)
    outputs = tuple(
        replace(
            output,
            native=(
                StemId(actual_by_key[_native_key(output.native.raw)])
                if output.native is not None
                else None
            ),
            backend_primary=(
                output.native is not None
                and bool(primary_key)
                and _native_key(output.native.raw) == primary_key
            ),
            logical_primary=output.role == selected_context.logical_primary,
            logical_secondary=output.role == selected_context.logical_secondary,
        )
        for output in selected_context.outputs
    )
    return ModelStemSemantics(
        model_id=model_id,
        context=context,
        intent=declaration.intent,
        outputs=outputs,
        status=StemReviewStatus.REVIEWED,
        evidence=declaration.evidence,
        logical_secondary_role=selected_context.logical_secondary,
    )
