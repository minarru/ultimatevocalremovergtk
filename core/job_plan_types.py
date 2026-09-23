"""Wire records and stable digests shared by planning and replay."""

from __future__ import annotations

import dataclasses
import hashlib
import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping

from .export_naming import OutputNamingContext
from .model_identity import DemucsSpec, MdxSpec, ModelArtifacts, ModelRecord
from .model_stem_semantics import stem_semantics_projection
from .settings import Settings
from .stem_roles import ModelStemSemantics, StemRoleId
from .stems import StemLiteral, StemRoute


def _identity_digest_entry(record: ModelRecord) -> dict[str, Any]:
    return {
        "id": record.id,
        "family": record.family,
        "backend_name": record.backend_name,
        "primary": record.artifacts.primary_filename,
        "supporting": list(record.artifacts.supporting_filenames),
        "demucs": dataclasses.asdict(record.demucs) if record.demucs else None,
        "mdx": dataclasses.asdict(record.mdx) if record.mdx else None,
    }


def compute_model_identity_digest(
    dependencies: Mapping[str, ModelRecord],
) -> str:
    payload = {path: _identity_digest_entry(dependencies[path]) for path in sorted(dependencies)}
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return f"sha256:{hashlib.sha256(canonical.encode('utf-8')).hexdigest()}"


EMPTY_MODEL_IDENTITY_DIGEST = compute_model_identity_digest({})


class ValidationLevel(str, Enum):
    CONFIG = "config"
    MODEL = "model"
    RUNTIME = "runtime"
    LOAD = "load"


class Provenance(str, Enum):
    BUILT_IN = "built-in"
    MODEL_CATALOG = "model-catalog"
    MODEL_LOCAL = "model-local"
    PRESET = "preset"
    PROFILE = "profile"
    GUI = "gui"
    CLI = "cli"
    ENVIRONMENT = "environment"
    DERIVED = "derived"


@dataclass(frozen=True)
class Diagnostic:
    code: str
    message: str
    severity: str = "error"
    path: str | None = None
    details: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ModelDescriptor:
    id: str
    family: str
    basename: str
    display: str
    backend_name: str = ""
    artifacts: ModelArtifacts = field(default_factory=lambda: ModelArtifacts(""))
    demucs: DemucsSpec | None = None
    mdx: MdxSpec | None = None
    checkpoint: str | None = None
    checkpoint_hash: str | None = None
    primary_stem: str | None = None
    secondary_stem: str | None = None
    backend_target_stem: str | None = None
    metadata_source: str | None = None
    stem_count: int = 0
    is_karaoke: bool = False
    is_bv: bool = False
    stem_semantics: ModelStemSemantics | None = None
    routes: tuple[StemRoute, ...] = ()
    backend_primary_stem: str | None = None


@dataclass(frozen=True)
class PlannedOutput:
    path: str
    stem: str
    conditional: bool = False
    concept: str = ""
    role: StemRoleId | StemLiteral | None = None
    filename_tag: str = ""


@dataclass(frozen=True)
class PlannedInput:
    path: str
    naming: OutputNamingContext
    outputs: tuple[PlannedOutput, ...]


@dataclass(frozen=True)
class JobSpec:
    command: str
    settings: Settings
    inputs: tuple[str, ...]
    output: str
    provenance: Mapping[str, str] = field(default_factory=dict)
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ResolvedJob:
    command: str
    settings: Settings = field(compare=False, repr=False)
    inputs: tuple[PlannedInput, ...]
    models: tuple[ModelDescriptor, ...]
    provenance: Mapping[str, str]
    diagnostics: tuple[Diagnostic, ...]
    validation_level: ValidationLevel
    inventory_generation: int
    settings_fingerprint: str
    device: str
    output: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)
    model_dependencies: Mapping[str, ModelRecord] = field(
        default_factory=dict, compare=False, repr=False
    )
    model_identity_digest: str = EMPTY_MODEL_IDENTITY_DIGEST

    @property
    def ok(self) -> bool:
        return not any(item.severity == "error" for item in self.diagnostics)

    def to_dict(self) -> dict[str, Any]:
        return {
            "command": self.command,
            "validation_level": self.validation_level.value,
            "inventory_generation": self.inventory_generation,
            "settings_fingerprint": self.settings_fingerprint,
            "device": self.device,
            "output": self.output,
            "models": [_model_descriptor_payload(model) for model in self.models],
            "model_dependencies": {
                path: record.id for path, record in sorted(self.model_dependencies.items())
            },
            "model_identity_digest": self.model_identity_digest,
            "inputs": [
                {
                    "path": item.path,
                    "naming": dataclasses.asdict(item.naming),
                    "outputs": [dataclasses.asdict(output) for output in item.outputs],
                }
                for item in self.inputs
            ],
            "provenance": dict(self.provenance),
            "diagnostics": [dataclasses.asdict(item) for item in self.diagnostics],
            "settings": self.settings.to_json_dict(),
            "metadata": dict(self.metadata),
        }


def _model_descriptor_payload(model: ModelDescriptor) -> dict[str, Any]:
    """Serialize a model descriptor without exposing semantic value objects."""
    payload = dataclasses.asdict(model)
    payload.pop("stem_semantics", None)
    # Routes are an in-memory engine/planning boundary.  The public projection
    # below retains their native keys beside semantic identifiers and labels.
    payload.pop("routes", None)
    payload.update(
        stem_semantics_projection(
            model.stem_semantics,
            backend_primary=(model.backend_primary_stem or model.primary_stem),
            backend_target=model.backend_target_stem,
        ).as_dict()
    )
    return payload


def settings_fingerprint(settings: Settings) -> str:
    payload = json.dumps(settings.to_json_dict(), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
