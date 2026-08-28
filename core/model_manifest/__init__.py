"""Unified bundled model metadata authority."""

from .loader import (
    BUNDLED_MODEL_MANIFEST_PATH,
    load_model_manifest,
    load_model_manifest_document,
    reset_model_manifest_cache_for_tests,
)
from .presentation import presentation_registry
from .runtime import mdx_runtime_registry
from .schema import (
    CatalogueEvidence,
    ConfigEvidence,
    ModelManifestError,
    ModelManifestRegistry,
    UnifiedModelRecord,
)
from .stems import stem_semantics_registry

__all__ = [
    "CatalogueEvidence",
    "ConfigEvidence",
    "BUNDLED_MODEL_MANIFEST_PATH",
    "ModelManifestError",
    "ModelManifestRegistry",
    "UnifiedModelRecord",
    "load_model_manifest",
    "load_model_manifest_document",
    "mdx_runtime_registry",
    "presentation_registry",
    "reset_model_manifest_cache_for_tests",
    "stem_semantics_registry",
]
