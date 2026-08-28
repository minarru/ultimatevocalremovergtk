"""Strict, atomic loader for all bundled per-model reviewed metadata."""

from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from types import MappingProxyType
from typing import Mapping

from core.debug_log import log_event
from core.model_identity import parse_stored_model_id
from core.paths import BASE_PATH, BUNDLED_DATA_DIR

from .presentation import build_presentation_view
from .runtime import build_runtime_view
from .schema import (
    CatalogueEvidence,
    ConfigEvidence,
    ModelManifestError,
    ModelManifestRegistry,
    UnifiedModelRecord,
)
from .stems import build_stem_view

_ROOT_FIELDS = frozenset({"schema_version", "author_aliases", "roles", "pairs", "models"})
_MODEL_FIELDS = frozenset(
    {
        "lifecycle",
        "display_alias",
        "display_waivers",
        "stem_semantics",
        "stem_waiver",
        "catalogue_evidence",
        "config_evidence",
        "runtime_contract",
    }
)
_CATALOGUE_FIELDS = frozenset(
    {"source", "catalogue_label", "primary_artifact", "metadata_source", "config_yaml"}
)
_CONFIG_EVIDENCE_FIELDS = frozenset(
    {"training_instruments", "target_instrument", "content_sha256", "sources"}
)
_STEM_SEMANTICS_FIELDS = frozenset({"native_signature", "intent", "contexts", "review_note"})
_RUNTIME_CONTRACT_FIELDS = frozenset(
    {"backend", "primary_native", "config_yamls", "artifact_evidence", "evidence"}
)
_SOURCE_PREFIXES = ("http://", "https://", "bundled/", "models/", "cache:", "checked-in:")
_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")

BUNDLED_MODEL_MANIFEST_PATH = Path(BUNDLED_DATA_DIR) / "model_manifest.json"
_registry_cache: dict[Path, ModelManifestRegistry] = {}
_bundled_failure_logged = False


def _error(path: tuple[str | int, ...], message: str) -> ModelManifestError:
    return ModelManifestError(path, message)


def _mapping(value: object, path: tuple[str | int, ...]) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        raise _error(path, "must be an object with string keys")
    return value


def _closed(
    value: object,
    path: tuple[str | int, ...],
    *,
    required: frozenset[str],
    allowed: frozenset[str],
) -> Mapping[str, object]:
    result = _mapping(value, path)
    missing = sorted(required.difference(result))
    if missing:
        raise _error(path + (missing[0],), "missing required field")
    unknown = sorted(set(result).difference(allowed))
    if unknown:
        raise _error(path + (unknown[0],), "unknown field")
    return result


def _string(value: object, path: tuple[str | int, ...]) -> str:
    if not isinstance(value, str) or not value.strip():
        raise _error(path, "must be a non-empty string")
    return value.strip()


def _duplicate_aware_mapping(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise _error(("manifest",), f"duplicate key {key!r}")
        result[key] = value
    return result


def _presentation_waivers(
    value: object,
    path: tuple[str | int, ...],
) -> Mapping[str, str]:
    raw = _mapping(value, path)
    if not raw:
        raise _error(path, "must contain at least one reviewed reason")
    return MappingProxyType(
        {_string(flag, path): _string(reason, path + (flag,)) for flag, reason in raw.items()}
    )


def _catalogue_evidence(value: object, path: tuple[str | int, ...]) -> CatalogueEvidence:
    raw = _closed(
        value,
        path,
        required=frozenset({"source", "catalogue_label", "primary_artifact", "metadata_source"}),
        allowed=_CATALOGUE_FIELDS,
    )
    config = raw.get("config_yaml", "")
    if not isinstance(config, str):
        raise _error(path + ("config_yaml",), "must be a string")
    return CatalogueEvidence(
        source=_string(raw["source"], path + ("source",)),
        catalogue_label=_string(raw["catalogue_label"], path + ("catalogue_label",)),
        primary_artifact=_string(raw["primary_artifact"], path + ("primary_artifact",)),
        metadata_source=_string(raw["metadata_source"], path + ("metadata_source",)),
        config_yaml=config.strip(),
    )


def _string_list(
    value: object,
    path: tuple[str | int, ...],
    *,
    allow_empty: bool,
    casefold_unique: bool,
) -> tuple[str, ...]:
    if not isinstance(value, list) or (not allow_empty and not value):
        raise _error(path, "must be a non-empty list" if not allow_empty else "must be a list")
    result = tuple(_string(item, path + (index,)) for index, item in enumerate(value))
    if casefold_unique and len({item.casefold() for item in result}) != len(result):
        raise _error(path, "duplicate case-insensitive value")
    return result


def _config_evidence(
    value: object,
    path: tuple[str | int, ...],
) -> Mapping[str, ConfigEvidence]:
    raw = _mapping(value, path)
    result: dict[str, ConfigEvidence] = {}
    for config_name, raw_evidence in raw.items():
        item_path = path + (config_name,)
        if os.path.basename(config_name) != config_name or Path(
            config_name
        ).suffix.casefold() not in {
            ".yaml",
            ".yml",
        }:
            raise _error(item_path, "must be keyed by an exact YAML config basename")
        item = _closed(
            raw_evidence,
            item_path,
            required=_CONFIG_EVIDENCE_FIELDS,
            allowed=_CONFIG_EVIDENCE_FIELDS,
        )
        digest = _string(item["content_sha256"], item_path + ("content_sha256",))
        if _SHA256_PATTERN.fullmatch(digest) is None:
            raise _error(item_path + ("content_sha256",), "must be a lowercase SHA-256 digest")
        target_value = item["target_instrument"]
        target = (
            None
            if target_value is None
            else _string(target_value, item_path + ("target_instrument",))
        )
        sources = _string_list(
            item["sources"], item_path + ("sources",), allow_empty=False, casefold_unique=True
        )
        for index, source in enumerate(sources):
            if not source.startswith(_SOURCE_PREFIXES):
                raise _error(item_path + ("sources", index), "has an unsupported evidence source")
        evidence = ConfigEvidence(
            training_instruments=_string_list(
                item["training_instruments"],
                item_path + ("training_instruments",),
                allow_empty=False,
                casefold_unique=True,
            ),
            target_instrument=target,
            content_sha256=digest,
            sources=sources,
        )
        _validate_local_config_evidence(config_name, evidence, item_path)
        result[config_name] = evidence
    return MappingProxyType(result)


def _validate_local_config_evidence(
    config_name: str,
    evidence: ConfigEvidence,
    path: tuple[str | int, ...],
) -> None:
    """Revalidate checked-in YAML claims instead of trusting their JSON summary."""
    from core.model_data import load_mdx_c_config_data

    for index, source in enumerate(evidence.sources):
        if not source.startswith(("bundled/", "models/")):
            continue
        source_path = Path(BASE_PATH) / source
        try:
            data = source_path.read_bytes()
        except OSError as error:
            raise _error(
                path + ("sources", index), f"could not read local source: {error}"
            ) from error
        if hashlib.sha256(data).hexdigest() != evidence.content_sha256:
            raise _error(path + ("content_sha256",), "does not match local source bytes")
        try:
            parsed = load_mdx_c_config_data(data)
        except Exception as error:
            raise _error(
                path + ("sources", index), f"could not parse local YAML: {error}"
            ) from error
        training = parsed.get("training")
        if not isinstance(training, dict):
            raise _error(path + ("sources", index), f"{config_name} has no training object")
        instruments = training.get("instruments")
        if not isinstance(instruments, list) or any(
            not isinstance(instrument, str) for instrument in instruments
        ):
            raise _error(path + ("training_instruments",), "does not match parsed YAML")
        if tuple(instruments) != evidence.training_instruments:
            raise _error(
                path + ("training_instruments",),
                f"does not match {config_name} training.instruments",
            )
        target = training.get("target_instrument")
        if target not in (None, "") and not isinstance(target, str):
            raise _error(path + ("target_instrument",), "does not match parsed YAML")
        parsed_target = None if target in (None, "") else target
        if parsed_target != evidence.target_instrument:
            raise _error(
                path + ("target_instrument",),
                f"does not match {config_name} training.target_instrument",
            )


def load_model_manifest_document(document: object) -> ModelManifestRegistry:
    """Validate every manifest domain before publishing one immutable registry."""
    root = _closed(document, (), required=_ROOT_FIELDS, allowed=_ROOT_FIELDS)
    if type(root["schema_version"]) is not int or root["schema_version"] != 1:
        raise _error(("schema_version",), "must be the exact integer 1")
    authors_raw = _mapping(root["author_aliases"], ("author_aliases",))
    authors: dict[str, str] = {}
    for raw_token, raw_display in authors_raw.items():
        token = _string(raw_token, ("author_aliases", raw_token)).casefold()
        if token in authors:
            raise _error(("author_aliases", raw_token), "duplicate case-insensitive token")
        authors[token] = _string(raw_display, ("author_aliases", raw_token))

    raw_models = _mapping(root["models"], ("models",))
    records: dict[str, UnifiedModelRecord] = {}
    aliases: dict[str, str] = {}
    display_waivers: dict[str, Mapping[str, str]] = {}
    stem_models: dict[str, object] = {}
    stem_waivers: dict[str, str] = {}
    runtime_contracts: dict[str, object] = {}
    for raw_model_id, raw_value in raw_models.items():
        path = ("models", raw_model_id)
        try:
            model_id = parse_stored_model_id(raw_model_id).value
        except ValueError as error:
            raise _error(path, f"invalid canonical model ID: {error}") from error
        value = _closed(
            raw_value,
            path,
            required=frozenset({"lifecycle", "catalogue_evidence"}),
            allowed=_MODEL_FIELDS,
        )
        lifecycle_value = _string(value["lifecycle"], path + ("lifecycle",))
        if lifecycle_value not in {"current", "retired"}:
            raise _error(path + ("lifecycle",), "must be current or retired")
        has_semantics = "stem_semantics" in value
        has_waiver = "stem_waiver" in value
        if has_semantics == has_waiver:
            raise _error(path, "requires exactly one of stem_semantics or stem_waiver")
        alias = ""
        if "display_alias" in value:
            alias = _string(value["display_alias"], path + ("display_alias",))
            aliases[model_id] = alias
        waivers: Mapping[str, str] = MappingProxyType({})
        if "display_waivers" in value:
            waivers = _presentation_waivers(value["display_waivers"], path + ("display_waivers",))
            display_waivers[model_id] = waivers
        evidence = _catalogue_evidence(value["catalogue_evidence"], path + ("catalogue_evidence",))
        config_evidence = _config_evidence(
            value.get("config_evidence", {}), path + ("config_evidence",)
        )
        if evidence.config_yaml and config_evidence and evidence.config_yaml not in config_evidence:
            raise _error(
                path + ("catalogue_evidence", "config_yaml"),
                "must name config_evidence in the same model record",
            )
        if has_semantics:
            semantics = dict(
                _closed(
                    value["stem_semantics"],
                    path + ("stem_semantics",),
                    required=_STEM_SEMANTICS_FIELDS,
                    allowed=_STEM_SEMANTICS_FIELDS,
                )
            )
            semantics["evidence"] = semantics.pop("review_note")
            stem_models[model_id] = semantics
        else:
            stem_waivers[model_id] = _string(value["stem_waiver"], path + ("stem_waiver",))
        if "runtime_contract" in value:
            if not model_id.startswith("mdx:"):
                raise _error(path + ("runtime_contract",), "is only allowed for mdx records")
            contract = dict(
                _closed(
                    value["runtime_contract"],
                    path + ("runtime_contract",),
                    required=_RUNTIME_CONTRACT_FIELDS,
                    allowed=_RUNTIME_CONTRACT_FIELDS,
                )
            )
            if not has_semantics:
                raise _error(path + ("runtime_contract",), "requires stem_semantics")
            config_names = contract.get("config_yamls")
            if isinstance(config_names, list):
                for index, config_name in enumerate(config_names):
                    if not isinstance(config_name, str) or config_name not in config_evidence:
                        raise _error(
                            path + ("runtime_contract", "config_yamls", index),
                            "must name config_evidence in the same model record",
                        )
            semantics_value = _mapping(value["stem_semantics"], path + ("stem_semantics",))
            contract["native_signature"] = semantics_value.get("native_signature")
            contract["config_evidence"] = value.get("config_evidence", {})
            runtime_contracts[model_id] = contract
        records[model_id] = UnifiedModelRecord(
            model_id=model_id,
            lifecycle=lifecycle_value,  # type: ignore[arg-type]
            catalogue_evidence=evidence,
            config_evidence=config_evidence,
            display_alias=alias,
            display_waivers=waivers,
        )

    try:
        stems = build_stem_view(
            roles=root["roles"],
            pairs=root["pairs"],
            models=stem_models,
            waivers=stem_waivers,
        )
        runtime = build_runtime_view(
            runtime_contracts,
            registry=stems,
            model_config_evidence={
                model_id: record.config_evidence for model_id, record in records.items()
            },
        )
    except ValueError as error:
        error_path = getattr(error, "path", ())
        if error_path and error_path[0] == "contracts":
            error_path = ("models", error_path[1], "runtime_contract", *error_path[2:])
        raise _error(error_path or ("manifest",), getattr(error, "message", str(error))) from error
    presentation = build_presentation_view(
        author_aliases=authors,
        model_aliases=aliases,
        waivers=display_waivers,
    )
    return ModelManifestRegistry(
        schema_version=1,
        models=MappingProxyType(records),
        presentation=presentation,
        stems=stems,
        runtime=runtime,
    )


def reset_model_manifest_cache_for_tests() -> None:
    """Clear successful manifest loads and the bundled-failure log guard."""
    global _bundled_failure_logged
    from .runtime import bundled_catalogue_config_evidence

    _registry_cache.clear()
    bundled_catalogue_config_evidence.cache_clear()
    _bundled_failure_logged = False


def _log_bundled_failure_once(manifest_path: Path, error: ModelManifestError) -> None:
    global _bundled_failure_logged
    if manifest_path == BUNDLED_MODEL_MANIFEST_PATH.resolve() and not _bundled_failure_logged:
        log_event("model", "model_manifest_invalid", level="critical", error=str(error))
        _bundled_failure_logged = True


def load_model_manifest(path: str | Path = BUNDLED_MODEL_MANIFEST_PATH) -> ModelManifestRegistry:
    """Read one manifest once and cache it only after full validation succeeds."""
    global _bundled_failure_logged
    manifest_path = Path(path).resolve()
    cached = _registry_cache.get(manifest_path)
    if cached is not None:
        return cached
    try:
        document = json.loads(
            manifest_path.read_text(encoding="utf-8"),
            object_pairs_hook=_duplicate_aware_mapping,
        )
    except ModelManifestError as error:
        _log_bundled_failure_once(manifest_path, error)
        raise
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        failure = _error(("manifest",), f"could not read manifest: {error}")
        _log_bundled_failure_once(manifest_path, failure)
        raise failure from error
    try:
        registry = load_model_manifest_document(document)
    except ModelManifestError as error:
        _log_bundled_failure_once(manifest_path, error)
        raise
    _registry_cache[manifest_path] = registry
    return registry
