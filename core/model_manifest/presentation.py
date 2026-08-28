"""Presentation view construction for the unified model manifest."""

from __future__ import annotations

from types import MappingProxyType
from typing import Any, Mapping


def presentation_registry() -> Mapping[str, Any]:
    """Return the presentation view from the one validated bundled registry."""
    from .loader import load_model_manifest

    return load_model_manifest().presentation


def build_presentation_view(
    *,
    author_aliases: Mapping[str, str],
    model_aliases: Mapping[str, str],
    waivers: Mapping[str, Mapping[str, str]],
) -> Mapping[str, Any]:
    return MappingProxyType(
        {
            "schema_version": 1,
            "model_aliases": MappingProxyType(dict(model_aliases)),
            "author_aliases": MappingProxyType(dict(author_aliases)),
            "waivers": MappingProxyType(dict(waivers)),
        }
    )
