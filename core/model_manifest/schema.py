"""Immutable value objects for the unified bundled model manifest."""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Literal, Mapping

from core.mdx_runtime_contract import MdxConfigEvidence, MdxRuntimeContractRegistry
from core.model_stem_manifest import StemSemanticsRegistry

ModelLifecycle = Literal["current", "retired"]


class ModelManifestError(ValueError):
    """A unified-manifest validation failure annotated with its path."""

    def __init__(self, path: tuple[str | int, ...], message: str) -> None:
        self.path = path
        self.message = message
        rendered = "".join(
            f"[{part}]" if isinstance(part, int) else ("." if index else "") + part
            for index, part in enumerate(path)
        )
        super().__init__(f"{rendered}: {message}")


@dataclass(frozen=True, slots=True)
class CatalogueEvidence:
    source: str
    catalogue_label: str
    primary_artifact: str
    metadata_source: str
    config_yaml: str = ""


# Runtime contracts and model records intentionally share this exact value
# object. A unified registry must not retain a second config-evidence copy
# solely for its runtime projection.
ConfigEvidence = MdxConfigEvidence


@dataclass(frozen=True, slots=True)
class UnifiedModelRecord:
    model_id: str
    lifecycle: ModelLifecycle
    catalogue_evidence: CatalogueEvidence
    config_evidence: Mapping[str, ConfigEvidence] = MappingProxyType({})
    display_alias: str = ""
    display_waivers: Mapping[str, str] = MappingProxyType({})


@dataclass(frozen=True, slots=True)
class ModelManifestRegistry:
    schema_version: int
    models: Mapping[str, UnifiedModelRecord]
    presentation: Mapping[str, Any]
    stems: StemSemanticsRegistry
    runtime: MdxRuntimeContractRegistry

    @classmethod
    def empty(cls) -> ModelManifestRegistry:
        empty: Mapping[str, Any] = MappingProxyType({})
        return cls(
            1,
            empty,
            MappingProxyType(
                {
                    "schema_version": 1,
                    "model_aliases": empty,
                    "author_aliases": empty,
                    "waivers": empty,
                }
            ),
            StemSemanticsRegistry.empty(),
            MdxRuntimeContractRegistry.empty(),
        )
