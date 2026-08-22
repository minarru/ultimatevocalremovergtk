"""Validated bundled and user-supplied Demucs identity metadata."""

from __future__ import annotations

import json
import os
from typing import Any, Mapping

from bundled.constants import (
    DEMUCS_2_SOURCE_MAPPER,
    DEMUCS_4_SOURCE_MAPPER,
    DEMUCS_6_SOURCE_MAPPER,
)

from . import paths
from .json_store import locked_json_path, read_json_object, write_json_atomic
from .model_identity import DemucsSpec, parse_stored_model_id


_DEMUCS_REGISTRY_SCHEMA_VERSION = 1
_DEMUCS_VERSIONS = frozenset({"v1", "v2", "v3", "v4"})
_DEMUCS_LAYOUTS = frozenset({"2_stem", "4_stem", "6_stem"})

_SOURCE_LAYOUTS: dict[int, tuple[str, dict[str, int]]] = {
    2: ("2_stem", DEMUCS_2_SOURCE_MAPPER),
    4: ("4_stem", DEMUCS_4_SOURCE_MAPPER),
    6: ("6_stem", DEMUCS_6_SOURCE_MAPPER),
}


def _read_json(path: str) -> Mapping[str, Any]:
    with open(path, encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, Mapping):
        raise ValueError(f"{path} must contain a JSON object")
    return payload


def _bundled_path(filename: str) -> str:
    return os.path.join(
        paths.BUNDLED_MODELS_DIR, "Demucs_Models", "model_data", filename
    )


def _registered_models_path(models_dir: str) -> str:
    return os.path.join(models_dir, "model_data", "registered_models.json")


def _empty_registry_document() -> dict[str, Any]:
    return {
        "schema_version": _DEMUCS_REGISTRY_SCHEMA_VERSION,
        "models": {},
        "by_primary_hash": {},
    }


def _normalize_demucs_registry_relative_path(models_dir: str, value: object) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError("Demucs registry paths must be non-empty")
    rooted = os.path.realpath(models_dir)
    lexical_candidate = os.path.join(models_dir, text.replace("\\", os.sep))
    candidate = os.path.realpath(lexical_candidate)
    if os.path.commonpath((rooted, candidate)) != rooted:
        raise ValueError("path escapes Demucs model root")
    relative = os.path.relpath(candidate, rooted)
    if relative in {"", "."}:
        raise ValueError("Demucs registry paths must reference a file")
    return relative.replace(os.sep, "/")


def _normalize_demucs_registry_model(
    models_dir: str, model_id: str, raw: Mapping[str, Any]
) -> dict[str, Any]:
    parsed = parse_stored_model_id(model_id)
    if parsed.family != "demucs":
        raise ValueError(f"invalid Demucs registry ID {model_id!r}")

    display_name = str(raw.get("display_name") or "").strip()
    backend_name = str(raw.get("backend_name") or "").strip()
    primary_hash = str(raw.get("primary_hash") or "").strip()
    demucs_version = str(raw.get("demucs_version") or "").strip()
    source_layout = str(raw.get("source_layout") or "").strip()
    if not display_name:
        raise ValueError(f"{parsed.value} is missing display_name")
    if not backend_name:
        raise ValueError(f"{parsed.value} is missing backend_name")
    if not primary_hash:
        raise ValueError(f"{parsed.value} is missing primary_hash")
    if demucs_version not in _DEMUCS_VERSIONS:
        raise ValueError(f"invalid Demucs version for {parsed.value}")
    if source_layout not in _DEMUCS_LAYOUTS:
        raise ValueError(f"invalid Demucs source layout for {parsed.value}")

    supporting_raw = raw.get("supporting_artifacts", ())
    if not isinstance(supporting_raw, list):
        raise ValueError(f"{parsed.value} supporting_artifacts must be a list")

    return {
        "display_name": display_name,
        "backend_name": backend_name,
        "entrypoint": _normalize_demucs_registry_relative_path(
            models_dir, raw.get("entrypoint")
        ),
        "supporting_artifacts": [
            _normalize_demucs_registry_relative_path(models_dir, path)
            for path in supporting_raw
        ],
        "primary_hash": primary_hash,
        "demucs_version": demucs_version,
        "source_layout": source_layout,
    }


def _normalize_demucs_registry_document(
    payload: Mapping[str, Any] | None, *, models_dir: str
) -> dict[str, Any]:
    if payload is None:
        return _empty_registry_document()
    if int(payload.get("schema_version") or 0) != _DEMUCS_REGISTRY_SCHEMA_VERSION:
        raise ValueError("unsupported Demucs registry schema")
    raw_models = payload.get("models")
    if not isinstance(raw_models, Mapping):
        raise ValueError("Demucs registry is missing models")

    models: dict[str, dict[str, Any]] = {}
    by_primary_hash: dict[str, str] = {}
    for model_id, raw in raw_models.items():
        if not isinstance(raw, Mapping):
            raise ValueError(f"invalid Demucs registry entry {model_id!r}")
        normalized = _normalize_demucs_registry_model(models_dir, str(model_id), raw)
        canonical_id = parse_stored_model_id(str(model_id)).value
        primary_hash = str(normalized["primary_hash"])
        existing = by_primary_hash.get(primary_hash)
        if existing is not None and existing != canonical_id:
            raise ValueError(
                f"duplicate Demucs primary_hash {primary_hash!r} for {existing!r} and {canonical_id!r}"
            )
        models[canonical_id] = normalized
        by_primary_hash[primary_hash] = canonical_id

    return {
        "schema_version": _DEMUCS_REGISTRY_SCHEMA_VERSION,
        "models": models,
        "by_primary_hash": by_primary_hash,
    }


def mapper_stems() -> set[str]:
    """Return canonical IDs represented by the bundled official name mapper."""
    from .model_inventory import artifact_stem

    mapper = _read_json(_bundled_path("model_name_mapper.json"))
    return {f"demucs:{artifact_stem(str(filename))}" for filename in mapper}


def load_bundled_demucs_specs() -> dict[str, DemucsSpec]:
    """Load and validate official Demucs version/source-layout declarations."""
    payload = _read_json(_bundled_path("model_specs.json"))
    if payload.get("schema_version") != 1:
        raise ValueError("unsupported bundled Demucs spec schema")
    raw_models = payload.get("models")
    if not isinstance(raw_models, Mapping):
        raise ValueError("bundled Demucs specs are missing models")

    result: dict[str, DemucsSpec] = {}
    for model_id, raw in raw_models.items():
        parsed = parse_stored_model_id(str(model_id))
        if parsed.family != "demucs" or not isinstance(raw, Mapping):
            raise ValueError(f"invalid bundled Demucs spec {model_id!r}")
        version = raw.get("version")
        layout = raw.get("source_layout")
        if version not in {"v1", "v2", "v3", "v4"}:
            raise ValueError(f"invalid Demucs version for {model_id}")
        if layout not in {"2_stem", "4_stem", "6_stem"}:
            raise ValueError(f"invalid Demucs source layout for {model_id}")
        result[parsed.value] = DemucsSpec(version, layout)  # type: ignore[arg-type]

    expected = mapper_stems()
    if set(result) != expected:
        missing = sorted(expected - set(result))
        extra = sorted(set(result) - expected)
        raise ValueError(f"bundled Demucs spec drift: missing={missing}, extra={extra}")
    return result


def demucs_source_layout_name(source_count: int) -> str | None:
    """Return the canonical layout label for a Demucs source count."""
    spec = _SOURCE_LAYOUTS.get(int(source_count))
    return None if spec is None else spec[0]


def validate_demucs_output_layout(
    *, expected_count: int, actual_count: int, model_label: str
) -> dict[str, int]:
    """Return the native source map for ``actual_count`` or raise on layout drift."""
    expected_layout = demucs_source_layout_name(expected_count)
    actual = _SOURCE_LAYOUTS.get(int(actual_count))
    if expected_layout is None:
        raise ValueError(f"unsupported declared Demucs source layout: {expected_count}")
    if actual is None:
        raise ValueError(
            f"{model_label} produced {actual_count} sources; expected {expected_layout} source layout"
        )
    actual_layout, source_map = actual
    if actual_layout != expected_layout:
        raise ValueError(
            f"{model_label} produced {actual_layout}; expected {expected_layout} source layout"
        )
    return source_map


def validate_demucs_inference_layouts(
    *,
    expected_count: int,
    model_label: str,
    source: Any,
    inst_source: Any | None = None,
) -> dict[str, int]:
    """Validate main and optional pre-processing Demucs outputs before grafting."""
    source_map = validate_demucs_output_layout(
        expected_count=expected_count,
        actual_count=len(source),
        model_label=model_label,
    )
    if inst_source is not None:
        validate_demucs_output_layout(
            expected_count=expected_count,
            actual_count=len(inst_source),
            model_label=f"{model_label} pre-processing result",
        )
    return source_map


class DemucsRegistry:
    def __init__(self, *, models_dir: str | None = None):
        self.models_dir = os.path.abspath(models_dir or paths.DEMUCS_MODELS_DIR)
        self.path = _registered_models_path(self.models_dir)
        self.lock_path = f"{self.path}.lock"

    def load(self) -> dict[str, Any]:
        with locked_json_path(self.lock_path):
            try:
                payload = read_json_object(self.path)
            except FileNotFoundError:
                return _empty_registry_document()
            normalized = _normalize_demucs_registry_document(
                payload, models_dir=self.models_dir
            )
            if normalized != payload:
                write_json_atomic(self.path, normalized)
            return normalized

    def save(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        normalized = _normalize_demucs_registry_document(
            payload, models_dir=self.models_dir
        )
        with locked_json_path(self.lock_path):
            write_json_atomic(self.path, normalized)
        return normalized


__all__ = [
    "DemucsRegistry",
    "validate_demucs_inference_layouts",
    "demucs_source_layout_name",
    "load_bundled_demucs_specs",
    "mapper_stems",
    "validate_demucs_output_layout",
]
