"""Immutable effective-job planning shared by GUI and CLI adapters."""

from __future__ import annotations

import copy
import dataclasses
import hashlib
import importlib.util
import json
import os
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping, Sequence

from bundled.constants import (
    DEMUCS_4_SOURCE_LIST,
    DEMUCS_ARCH_TYPE,
    ENSEMBLE_MODE,
    MDX_ARCH_TYPE,
    VR_ARCH_PM,
)

from .device import DeviceRequest
from .export_naming import (
    OutputNamingContext,
    build_output_naming_context,
    format_stem_basename,
)
from .model_config import assemble_model
from .model_identity import ModelIdentityService, ModelRecord
from .access_policy import access_policy
from .settings import Settings
from .stems import (
    EnsemblePair,
    coerce_ensemble_pair,
    exclusive_flags_for_focus,
    exclusive_flags_for_pair,
    focus_is_resolvable,
    model_stem_count,
)


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


@dataclass(frozen=True)
class ModelDescriptor:
    id: str
    family: str
    basename: str
    display: str
    checkpoint: str | None = None
    checkpoint_hash: str | None = None
    primary_stem: str | None = None
    secondary_stem: str | None = None
    metadata_source: str | None = None
    stem_count: int = 0
    is_karaoke: bool = False
    is_bv: bool = False


@dataclass(frozen=True)
class PlannedOutput:
    path: str
    stem: str
    conditional: bool = False


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
            "models": [dataclasses.asdict(model) for model in self.models],
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


def settings_fingerprint(settings: Settings) -> str:
    payload = json.dumps(settings.to_json_dict(), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _checkpoint_hash(path: str) -> str:
    from .mdx_c_registry import compute_checkpoint_hash

    return str(compute_checkpoint_hash(path) or "")


def _descriptor(record: ModelRecord, model: Any, verify: bool) -> ModelDescriptor:
    path = str(getattr(model, "model_path", "") or "")
    digest = _checkpoint_hash(path) if verify and path and os.path.isfile(path) else None
    return ModelDescriptor(
        id=record.id,
        family=record.family,
        basename=record.basename,
        display=record.display,
        checkpoint=path or None,
        checkpoint_hash=digest,
        primary_stem=getattr(model, "primary_stem", None),
        secondary_stem=getattr(model, "secondary_stem", None),
        metadata_source=(
            "model-local"
            if os.path.isfile(str(getattr(model, "model_hash_dir", "") or ""))
            else "model-catalog"
        ),
        stem_count=model_stem_count(model),
        is_karaoke=bool(getattr(model, "is_karaoke", False)),
        is_bv=bool(getattr(model, "is_bv_model", False)),
    )


def _stem_focus_diagnostics(
    settings: Settings,
    models: Sequence[Any],
    descriptors: Sequence[ModelDescriptor],
) -> list[Diagnostic]:
    """Report a ``process.stem_focus`` that names none of a model's stems.

    Such a focus cannot be honored, and the run silently falls back to
    exporting every stem — worth saying out loud before a long job rather
    than leaving the user to notice the extra files afterwards.
    """
    focus = str(settings.process.stem_focus or "")
    if not focus:
        return []
    result: list[Diagnostic] = []
    for index, model in enumerate(models):
        if getattr(model, "is_vocal_split_model", False):
            continue
        if focus_is_resolvable(model, focus):
            continue
        label = (
            descriptors[index].display
            if index < len(descriptors)
            else getattr(model, "model_basename", "") or "model"
        )
        stems = ", ".join(
            str(stem)
            for stem in (
                getattr(model, "primary_stem", None),
                getattr(model, "secondary_stem", None),
            )
            if stem
        )
        result.append(
            Diagnostic(
                "stems.focus_unmatched",
                f"stem focus {focus!r} matches no stem of {label}"
                + (f" (has {stems}); exporting all stems" if stems else "; exporting all stems"),
            )
        )
    return result


def planned_output_stems(
    settings: Settings,
    descriptors: Sequence[ModelDescriptor],
    *,
    command: str,
) -> tuple[tuple[str, bool], ...]:
    if command == "ensemble":
        pair = coerce_ensemble_pair(settings.ensemble.main_stem)
        if pair is EnsemblePair.FOUR_STEM:
            return tuple((stem, False) for stem in DEMUCS_4_SOURCE_LIST)
        if pair is EnsemblePair.MULTI_STEM:
            seen: dict[str, bool] = {}
            for descriptor in descriptors:
                for stem in (descriptor.primary_stem, descriptor.secondary_stem):
                    if stem:
                        seen.setdefault(stem, False)
            topologies = {
                (item.primary_stem, item.secondary_stem) for item in descriptors
            }
            conditional = len(topologies) > 1
            return tuple((stem, conditional) for stem in seen)
        left, right = pair.stem_halves()
        result: list[tuple[str, bool]] = []
        if left:
            result.append((left, False))
        if right and not right.startswith("No "):
            result.append((right, False))
        flags = exclusive_flags_for_pair(
            str(settings.process.stem_focus or ""), pair
        )
        if flags is None:
            primary_only = settings.process.primary_stem_only
            secondary_only = settings.process.secondary_stem_only
        else:
            primary_only, secondary_only = flags
        if primary_only:
            return tuple(item for item in result if item[0] == left)
        if secondary_only:
            return tuple(item for item in result if item[0] == right)
        return tuple(result)
    descriptor = descriptors[0] if descriptors else ModelDescriptor("", "", "", "")
    primary_only = settings.process.primary_stem_only
    secondary_only = settings.process.secondary_stem_only
    # ``process.stem_focus`` overrides the positional booleans, and resolves
    # against this model's own stems (assemble does the same, per config).
    flags = exclusive_flags_for_focus(
        str(settings.process.stem_focus or ""),
        primary_stem=descriptor.primary_stem,
        secondary_stem=descriptor.secondary_stem,
        stem_count=descriptor.stem_count,
        is_karaoke=descriptor.is_karaoke,
        is_bv=descriptor.is_bv,
    )
    if flags is not None:
        primary_only, secondary_only = flags
    if primary_only:
        return ((descriptor.primary_stem or "Primary", False),)
    if secondary_only:
        return ((descriptor.secondary_stem or "Secondary", False),)
    return (
        (descriptor.primary_stem or "Primary", False),
        (descriptor.secondary_stem or "Secondary", False),
    )


def _apply_model_native_values(
    settings: Settings, records: Sequence[ModelRecord], models: Sequence[Any],
    provenance: dict[str, str],
) -> None:
    """Materialize model-native values only for settings whose value is auto."""
    for record, model in zip(records, models):
        source = (
            Provenance.MODEL_LOCAL.value
            if os.path.isfile(str(getattr(model, "model_hash_dir", "") or ""))
            else Provenance.MODEL_CATALOG.value
        )
        if record.family == "mdx" and settings.mdx.compensate is None:
            value = getattr(model, "compensate", None)
            if value is not None:
                settings.mdx.compensate = float(value)
                provenance["mdx.compensate"] = source
        if record.family == "demucs" and settings.demucs.segment is None:
            value = getattr(model, "segment", None)
            if value is not None:
                settings.demucs.segment = int(value)
                provenance["demucs.segment"] = source


def device_runtime_diagnostics(settings: Settings) -> list[Diagnostic]:
    """Validate the requested inference device without loading model weights."""
    try:
        from .gpu_backend import resolve_inference_backend
        from .platform import system_name

        backend = resolve_inference_backend(
            use_gpu=settings.process.use_gpu,
            device_set=str(settings.process.device or "Default"),
            is_use_directml=settings.process.use_directml,
            is_macos=system_name() == "Darwin",
        )
        requested = DeviceRequest.from_settings(settings.process).id.split(":", 1)[0]
        if requested not in {"auto", "cpu"} and backend.backend_name != requested:
            return [Diagnostic(
                "runtime.device_unavailable",
                f"Requested device {requested} resolved to {backend.backend_name}",
            )]
    except (ImportError, RuntimeError, ValueError) as exc:
        return [Diagnostic("runtime.device", str(exc))]
    return []


class JobResolver:
    def __init__(self, repo: Any):
        self.repo = repo
        self.identities = ModelIdentityService(repo)

    def resolve(
        self, spec: JobSpec, level: ValidationLevel = ValidationLevel.MODEL
    ) -> ResolvedJob:
        settings = copy.deepcopy(spec.settings)
        settings.process.export_path = os.path.abspath(spec.output)
        diagnostics: list[Diagnostic] = []
        records: list[ModelRecord] = []
        models: list[Any] = []
        if not spec.inputs:
            diagnostics.append(Diagnostic("inputs.empty", "Select at least one input file"))
        for path in spec.inputs:
            if not os.path.isfile(path):
                diagnostics.append(Diagnostic("input.missing", f"Input not found: {path}", path=path))
        if not spec.output:
            diagnostics.append(Diagnostic("output.empty", "Choose an output folder"))
        try:
            records = self._identity_records(settings, spec.command)
        except ValueError as exc:
            diagnostics.append(Diagnostic("model.identity", str(exc)))
        verify_model = level is not ValidationLevel.CONFIG
        if records and verify_model:
            try:
                with access_policy(allow_network=False, allow_metadata_writes=False):
                    models = self._assemble(settings, spec.command, records)
                if len(models) != len(records):
                    raise ValueError("one or more model configurations are unavailable")
                if any(not getattr(model, "model_status", False) for model in models):
                    raise ValueError("one or more model configurations are unavailable")
            except (OSError, ValueError) as exc:
                diagnostics.append(Diagnostic("model.configuration", str(exc)))
        descriptors = tuple(
            _descriptor(record, model, verify_model)
            for record, model in zip(records, models)
        ) if models else tuple(
            ModelDescriptor(record.id, record.family, record.basename, record.display)
            for record in records
        )
        provenance = dict(spec.provenance)
        if models:
            _apply_model_native_values(settings, records, models, provenance)
        diagnostics.extend(_stem_focus_diagnostics(settings, models, descriptors))
        if level in {ValidationLevel.RUNTIME, ValidationLevel.LOAD}:
            diagnostics.extend(self._runtime_diagnostics(settings))
        if level is ValidationLevel.LOAD and models and not diagnostics:
            try:
                self._load_checkpoints(models)
            except (ImportError, OSError, ValueError) as exc:
                diagnostics.append(Diagnostic("model.load", str(exc)))
        planned = self._plan_inputs(settings, spec, descriptors)
        request = DeviceRequest.from_settings(settings.process)
        return ResolvedJob(
            command=spec.command,
            settings=settings,
            inputs=planned,
            models=descriptors,
            provenance=provenance,
            diagnostics=tuple(diagnostics),
            validation_level=level,
            inventory_generation=int(getattr(self.repo, "inventory_generation", 0)),
            settings_fingerprint=settings_fingerprint(settings),
            device=request.id,
            output=settings.process.export_path,
            metadata=dict(spec.metadata),
        )

    def is_current(self, plan: ResolvedJob) -> bool:
        if plan.inventory_generation != int(getattr(self.repo, "inventory_generation", 0)):
            return False
        for descriptor in plan.models:
            if not descriptor.checkpoint or not descriptor.checkpoint_hash:
                continue
            if not os.path.isfile(descriptor.checkpoint):
                return False
            if _checkpoint_hash(descriptor.checkpoint) != descriptor.checkpoint_hash:
                return False
        return True

    def adopt(
        self, spec: JobSpec, records: Sequence[ModelRecord], models: Sequence[Any],
        *, level: ValidationLevel = ValidationLevel.MODEL,
    ) -> ResolvedJob:
        """Build the shared immutable plan from models already dry-assembled by an adapter."""
        settings = copy.deepcopy(spec.settings)
        descriptors = tuple(
            _descriptor(record, model, level is not ValidationLevel.CONFIG)
            for record, model in zip(records, models)
        )
        provenance = dict(spec.provenance)
        _apply_model_native_values(settings, records, models, provenance)
        return ResolvedJob(
            spec.command,
            settings,
            self._plan_inputs(settings, spec, descriptors),
            descriptors,
            provenance,
            (),
            level,
            int(getattr(self.repo, "inventory_generation", 0)),
            settings_fingerprint(settings),
            DeviceRequest.from_settings(settings.process).id,
            settings.process.export_path,
            dict(spec.metadata),
        )

    def _identity_records(self, settings: Settings, command: str) -> list[ModelRecord]:
        method_value = str(getattr(settings.process.method, "value", settings.process.method))
        if command == "ensemble" or method_value == ENSEMBLE_MODE:
            records = [
                self.identities.resolve(reference)
                for reference in settings.ensemble.selected_models
            ]
            if len(records) < 2:
                raise ValueError("an ensemble requires at least two models")
            return records
        family, reference = {
            VR_ARCH_PM: ("vr", settings.vr.model),
            MDX_ARCH_TYPE: ("mdx", settings.mdx.model),
            DEMUCS_ARCH_TYPE: ("demucs", settings.demucs.model),
        }[method_value]
        token = str(reference)
        if token.partition(":")[0].casefold() not in {"vr", "mdx", "demucs"}:
            token = f"{family}:{token}"
        return [self.identities.resolve(token)]

    def _assemble(
        self, settings: Settings, command: str, records: Sequence[ModelRecord]
    ) -> list[Any]:
        from .mdx_config_fetch import mdx_c_network

        with mdx_c_network(False):
            method_value = str(
                getattr(settings.process.method, "value", settings.process.method)
            )
            if command == "ensemble" or method_value == ENSEMBLE_MODE:
                settings.ensemble.selected_models = [record.id for record in records]
                return assemble_model(settings, self.repo, arch_type=ENSEMBLE_MODE)
            record = records[0]
            setattr(getattr(settings, record.family), "model", record.id)
            return assemble_model(settings, self.repo, record.id, record.method)

    def _runtime_diagnostics(self, settings: Settings) -> list[Diagnostic]:
        missing = [name for name in ("kthread", "soundfile") if importlib.util.find_spec(name) is None]
        if missing:
            return [Diagnostic("runtime.dependencies", f"Missing Python packages: {', '.join(missing)}")]
        return device_runtime_diagnostics(settings)

    def _plan_inputs(
        self, settings: Settings, spec: JobSpec, descriptors: Sequence[ModelDescriptor]
    ) -> tuple[PlannedInput, ...]:
        result: list[PlannedInput] = []
        total = len(spec.inputs)
        descriptor = descriptors[0] if descriptors else ModelDescriptor("", "", "", "")
        stem_entries = planned_output_stems(settings, descriptors, command=spec.command)
        from .export_naming import ensemble_name_for_export

        ensemble_label = (
            ensemble_name_for_export(settings.ensemble.chosen_ensemble)
            if spec.command == "ensemble" else None
        )
        model_label = descriptor.display if spec.command != "ensemble" else None
        for index, path in enumerate(spec.inputs, start=1):
            naming = build_output_naming_context(
                settings, path, export_path=settings.process.export_path,
                file_index=index, file_total=total, model_label=model_label,
                ensemble_label=ensemble_label,
                force_ensemble_label=(
                    spec.command == "ensemble"
                    and bool(settings.ensemble.append_ensemble_name)
                ),
            )
            outputs = tuple(
                PlannedOutput(
                    os.path.join(
                        naming.export_directory,
                        f"{format_stem_basename(naming.track_base, stem)}.{naming.extension}",
                    ),
                    stem,
                    conditional,
                )
                for stem, conditional in stem_entries
            )
            result.append(PlannedInput(path, naming, outputs))
        return tuple(result)

    def _load_checkpoints(self, models: Sequence[Any]) -> None:
        from pathlib import Path
        from .torch_checkpoint import load_torch_checkpoint

        for model in models:
            path = str(getattr(model, "model_path", "") or "")
            suffix = Path(path).suffix.casefold()
            if suffix == ".onnx":
                import onnxruntime as ort
                session = ort.InferenceSession(path, providers=["CPUExecutionProvider"])
                del session
            elif suffix in {".pth", ".pt", ".ckpt", ".th"}:
                weights = load_torch_checkpoint(path, map_location="cpu")
                del weights
            else:
                raise ValueError(f"load validation does not support {suffix!r}")


def format_effective_plan(plan: ResolvedJob) -> str:
    lines = ["Effective plan"]
    if len(plan.models) == 1:
        model = plan.models[0]
        lines.append(f"  model: {model.display} [{model.id}]")
    elif plan.models:
        lines.append("  models: " + ", ".join(f"{m.display} [{m.id}]" for m in plan.models))
    lines.append(f"  device: {plan.device}")
    lines.append(f"  inputs: {len(plan.inputs)}")
    lines.append(f"  outputs: {sum(len(item.outputs) for item in plan.inputs)} guaranteed")
    for diagnostic in plan.diagnostics:
        lines.append(f"  {diagnostic.severity}: {diagnostic.message}")
    return "\n".join(lines)


__all__ = [
    "Diagnostic", "JobResolver", "JobSpec", "ModelDescriptor", "PlannedInput",
    "PlannedOutput", "Provenance", "ResolvedJob", "ValidationLevel",
    "device_runtime_diagnostics", "format_effective_plan", "planned_output_stems",
    "settings_fingerprint",
]
