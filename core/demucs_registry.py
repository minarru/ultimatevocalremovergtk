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
from .model_identity import DemucsSpec, parse_stored_model_id

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


__all__ = [
    "validate_demucs_inference_layouts",
    "demucs_source_layout_name",
    "load_bundled_demucs_specs",
    "mapper_stems",
    "validate_demucs_output_layout",
]
