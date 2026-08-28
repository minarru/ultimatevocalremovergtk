"""Stem-semantics view construction for the unified model manifest."""

from __future__ import annotations

from typing import Mapping

from core.model_stem_manifest import StemSemanticsRegistry, load_stem_manifest_document


def stem_semantics_registry() -> StemSemanticsRegistry:
    """Return the semantic view from the one validated bundled registry."""
    from .loader import load_model_manifest

    return load_model_manifest().stems


def reviewed_catalogue_stem_signature(model_id: str) -> tuple[str, ...]:
    """Project one exact reviewed native signature from the unified record."""
    declaration = stem_semantics_registry().models.get(model_id)
    return () if declaration is None else declaration.native_signature


def catalogue_stem_evidence_uses_config(model_id: str) -> bool:
    """Whether one exact record's stem evidence comes from a parsed config."""
    from .loader import load_model_manifest

    record = load_model_manifest().models.get(model_id)
    return bool(
        record is not None and (record.catalogue_evidence.config_yaml or record.config_evidence)
    )


def catalogue_stem_evidence_not_applicable(model_id: str) -> bool:
    """Whether the unified record deliberately waives stem-output semantics."""
    return model_id in stem_semantics_registry().waivers


def build_stem_view(
    *,
    roles: object,
    pairs: object,
    models: Mapping[str, object],
    waivers: Mapping[str, str],
) -> StemSemanticsRegistry:
    document = {
        "schema_version": 2,
        "roles": roles,
        "pairs": pairs,
        "models": dict(models),
        "waivers": dict(waivers),
    }
    return load_stem_manifest_document(document)
