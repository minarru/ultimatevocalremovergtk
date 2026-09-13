"""Validated, frontend-independent ensemble blend settings."""

from __future__ import annotations

import math
from typing import Any, Sequence

BLEND_FIELDS = (
    "member_weights",
    "smoothing",
    "soft_strength",
    "hybrid_balance",
    "alignment_correction",
)
_RANGES = {"smoothing": (0.0, 4.0), "soft_strength": (0.0, 10.0), "hybrid_balance": (0.0, 1.0)}


def validate_blend_value(field: str, value: Any) -> Any:
    if field in _RANGES:
        number = float(value)
        low, high = _RANGES[field]
        if not math.isfinite(number) or not low <= number <= high:
            raise ValueError(f"ensemble.{field} must be between {low} and {high}")
        return number
    if field == "member_weights":
        if not isinstance(value, dict):
            raise ValueError("ensemble.member_weights must map stem role IDs to model weights")
        result: dict[str, dict[str, float]] = {}
        for role, members in value.items():
            if not isinstance(role, str) or not role or not isinstance(members, dict):
                raise ValueError(
                    "ensemble.member_weights requires role IDs and model-weight objects"
                )
            if role != "*":
                from core.model_stem_manifest import load_bundled_stem_semantics
                from core.stem_roles import StemRoleId

                try:
                    role_id = StemRoleId(role)
                except ValueError as exc:
                    raise ValueError(
                        f"ensemble.member_weights has invalid role ID {role!r}"
                    ) from exc
                if role_id not in load_bundled_stem_semantics().roles:
                    raise ValueError(f"ensemble.member_weights has unknown role ID {role!r}")
            result[role] = {}
            for model_id, weight in members.items():
                if not isinstance(model_id, str) or not model_id:
                    raise ValueError("ensemble.member_weights requires model IDs")
                from core.model_identity import parse_stored_model_id

                try:
                    parse_stored_model_id(model_id)
                except ValueError as exc:
                    raise ValueError(
                        f"ensemble.member_weights requires canonical model IDs: {model_id!r}"
                    ) from exc
                number = float(weight)
                if not math.isfinite(number) or not 0 <= number <= 100:
                    raise ValueError("ensemble member weights must be between 0 and 100")
                result[role][model_id] = number
        return result
    if field == "alignment_correction":
        if isinstance(value, bool):
            return value
        if value in (0, 1):
            return bool(value)
        if isinstance(value, str):
            lowered = value.strip().casefold()
            if lowered in {"1", "true", "yes", "on"}:
                return True
            if lowered in {"0", "false", "no", "off", ""}:
                return False
        raise ValueError("ensemble.alignment_correction must be a boolean")
    return value


def blend_kwargs(settings: Any, member_ids: Sequence[str], role: str = "*") -> dict[str, Any]:
    """Resolve weights by exact contributor identity, never list position or label."""
    ensemble = settings.ensemble
    weights = validate_blend_value("member_weights", getattr(ensemble, "member_weights", {}))
    common = weights.get("*", {})
    specific = weights.get(role, {})
    return {
        "weights": [specific.get(model, common.get(model, 1.0)) for model in member_ids],
        "smoothing": validate_blend_value("smoothing", getattr(ensemble, "smoothing", 0.0)),
        "soft_strength": validate_blend_value(
            "soft_strength", getattr(ensemble, "soft_strength", 1.0)
        ),
        "hybrid_balance": validate_blend_value(
            "hybrid_balance", getattr(ensemble, "hybrid_balance", 0.5)
        ),
        "align": validate_blend_value(
            "alignment_correction", getattr(ensemble, "alignment_correction", False)
        ),
        "on_alignment": report_alignment,
    }


def saved_blend_options(settings: Any) -> dict[str, Any]:
    return {name: getattr(settings.ensemble, name) for name in BLEND_FIELDS}


def restore_blend_options(
    payload: Any,
    warnings: list[str] | None = None,
    *,
    strict: bool = False,
) -> dict[str, Any]:
    """Validate options, falling back one field at a time for persisted data."""
    from core.settings.model import EnsembleSettings

    defaults = EnsembleSettings()
    if isinstance(payload, dict):
        values = payload
    elif payload is None or not strict:
        values = {}
        if payload is not None and warnings is not None:
            warnings.append("ensemble.blend_options: expected an object; using defaults")
    else:
        raise ValueError("ensemble blend options must be an object")
    if strict:
        unknown = sorted(set(values).difference(BLEND_FIELDS))
        if unknown:
            raise ValueError(f"unknown ensemble blend option: {unknown[0]}")

    restored: dict[str, Any] = {}
    for name in BLEND_FIELDS:
        default = getattr(defaults, name)
        try:
            restored[name] = validate_blend_value(name, values.get(name, default))
        except (TypeError, ValueError) as exc:
            if strict:
                raise
            restored[name] = default
            if warnings is not None:
                warnings.append(f"ensemble.{name}: {exc}; using default {default!r}")
    return restored


def report_alignment(diagnostics: Sequence[Any]) -> None:
    from dataclasses import asdict

    from core.debug_log import log_event

    for item in diagnostics:
        log_event("ensemble", "alignment", level="debug", **asdict(item))
