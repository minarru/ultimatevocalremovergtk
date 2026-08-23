"""Resolved planning and validation for the shared Audio Tools backend."""

from __future__ import annotations

import copy
import dataclasses
import importlib.util
import os
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Mapping

from bundled.constants import (
    ALIGN_INPUTS,
    APOLLO_RESTORE,
    CHANGE_PITCH,
    MANUAL_ENSEMBLE,
    MATCH_INPUTS,
    TIME_STRETCH,
)

from .apollo import ApolloModelData
from .device import DeviceRequest
from .export_naming import sanitize_filename_component
from .job_plan import (
    EMPTY_MODEL_IDENTITY_DIGEST,
    Diagnostic,
    ModelDescriptor,
    ValidationLevel,
    compute_model_identity_digest,
    settings_fingerprint,
)
from .model_identity import ModelIdentityService, ModelRecord
from .paths import APOLLO_MODELS_DIR
from .settings import Settings

AUDIO_TOOL_IDS = (
    MANUAL_ENSEMBLE, TIME_STRETCH, CHANGE_PITCH,
    ALIGN_INPUTS, MATCH_INPUTS, APOLLO_RESTORE,
)
_APOLLO_DEPENDENCY_PATH = "audio_tools.apollo_model"


def _empty_model_dependencies() -> Mapping[str, ModelRecord]:
    return MappingProxyType({})


@dataclass(frozen=True)
class AudioJobSpec:
    tool: str
    settings: Settings
    output: str
    inputs: tuple[str, ...] = ()
    pairs: tuple[tuple[str, str], ...] = ()
    name: str | None = None
    provenance: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class PlannedAudioUnit:
    inputs: tuple[str, ...]
    outputs: tuple[str, ...]
    name: str


@dataclass(frozen=True)
class ResolvedAudioJob:
    tool: str
    settings: Settings = field(compare=False, repr=False)
    output: str
    units: tuple[PlannedAudioUnit, ...]
    provenance: Mapping[str, str]
    diagnostics: tuple[Diagnostic, ...]
    validation_level: ValidationLevel
    inventory_generation: int
    settings_fingerprint: str
    device: str
    model: ModelDescriptor | None = None
    model_dependencies: Mapping[str, ModelRecord] = field(
        default_factory=_empty_model_dependencies, compare=False, repr=False
    )
    model_identity_digest: str = EMPTY_MODEL_IDENTITY_DIGEST

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "model_dependencies",
            MappingProxyType(dict(self.model_dependencies)),
        )

    @property
    def ok(self) -> bool:
        return not any(item.severity == "error" for item in self.diagnostics)

    def to_dict(self) -> dict[str, Any]:
        return {
            "command": "audio",
            "tool": self.tool,
            "output": self.output,
            "validation_level": self.validation_level.value,
            "inventory_generation": self.inventory_generation,
            "settings_fingerprint": self.settings_fingerprint,
            "device": self.device,
            "model": dataclasses.asdict(self.model) if self.model else None,
            "model_dependencies": {
                path: record.id
                for path, record in sorted(self.model_dependencies.items())
            },
            "model_identity_digest": self.model_identity_digest,
            "units": [dataclasses.asdict(unit) for unit in self.units],
            "provenance": dict(self.provenance),
            "diagnostics": [dataclasses.asdict(item) for item in self.diagnostics],
            "settings": self.settings.to_json_dict(),
        }


class AudioJobResolver:
    def __init__(self, repo: Any):
        self.repo = repo
        self.identities = ModelIdentityService(repo)

    def resolve(
        self,
        spec: AudioJobSpec,
        level: ValidationLevel = ValidationLevel.MODEL,
        *,
        allow_network: bool = True,
    ) -> ResolvedAudioJob:
        settings = copy.deepcopy(spec.settings)
        settings.process.export_path = os.path.abspath(spec.output) if spec.output else ""
        diagnostics: list[Diagnostic] = []
        if spec.tool not in AUDIO_TOOL_IDS:
            diagnostics.append(Diagnostic("audio.tool", f"Unknown audio tool: {spec.tool}"))
        if not spec.output:
            diagnostics.append(Diagnostic("output.empty", "Choose an output folder"))
        diagnostics.extend(self._input_diagnostics(spec))
        diagnostics.extend(self._option_diagnostics(spec.tool, settings))
        model: ModelDescriptor | None = None
        dependencies: Mapping[str, ModelRecord] = _empty_model_dependencies()
        if spec.tool == APOLLO_RESTORE:
            record = self._resolve_apollo_record(settings, diagnostics)
            if record is not None:
                model = self._apollo_descriptor(record, diagnostics, level)
                dependencies = MappingProxyType({_APOLLO_DEPENDENCY_PATH: record})
        if level in {ValidationLevel.RUNTIME, ValidationLevel.LOAD}:
            diagnostics.extend(self._runtime_diagnostics(spec.tool, settings))
        if level is ValidationLevel.LOAD and spec.tool == APOLLO_RESTORE and model:
            try:
                import ml.apollo_inference  # noqa: F401
            except (ImportError, OSError, RuntimeError) as exc:
                diagnostics.append(Diagnostic("audio.load", str(exc)))
        units = self._plan_units(spec, settings)
        plan = ResolvedAudioJob(
            spec.tool, settings, settings.process.export_path, units,
            dict(spec.provenance), tuple(diagnostics), level,
            int(getattr(self.repo, "inventory_generation", 0)),
            settings_fingerprint(settings), DeviceRequest.from_settings(settings.process).id,
            model,
            dependencies,
            compute_model_identity_digest(dependencies),
        )
        from .debug_log import log_event

        log_event(
            "settings",
            "audio_plan_resolved",
            tool=plan.tool,
            validation_level=plan.validation_level.value,
            unit_count=len(plan.units),
            dependency_count=len(plan.model_dependencies),
            diagnostic_count=len(plan.diagnostics),
            error_count=sum(item.severity == "error" for item in plan.diagnostics),
            inventory_generation=plan.inventory_generation,
            device=plan.device,
        )
        return plan

    def is_current(self, plan: ResolvedAudioJob) -> bool:
        if plan.inventory_generation != int(getattr(self.repo, "inventory_generation", 0)):
            return False
        current_dependencies: dict[str, ModelRecord] = {}
        try:
            for path, recorded in plan.model_dependencies.items():
                if path != _APOLLO_DEPENDENCY_PATH:
                    return False
                current = self.identities.lookup(recorded.id)
                self._validate_apollo_record(current)
                current_dependencies[path] = current
        except (AttributeError, TypeError, ValueError):
            return False
        if plan.model is not None and not current_dependencies:
            return False
        if (
            compute_model_identity_digest(current_dependencies)
            != plan.model_identity_digest
        ):
            return False
        if plan.model and plan.model.checkpoint and plan.model.checkpoint_hash:
            from .apollo import checkpoint_md5

            return os.path.isfile(plan.model.checkpoint) and checkpoint_md5(plan.model.checkpoint) == plan.model.checkpoint_hash
        return True

    @staticmethod
    def _input_diagnostics(spec: AudioJobSpec) -> list[Diagnostic]:
        result: list[Diagnostic] = []
        if spec.tool in {ALIGN_INPUTS, MATCH_INPUTS}:
            if not spec.pairs:
                result.append(Diagnostic("audio.pairs.empty", "Provide at least one input pair"))
            for left, right in spec.pairs:
                if left == right:
                    result.append(Diagnostic("audio.pair.same", f"Pair uses the same file twice: {left}"))
                for path in (left, right):
                    if not os.path.isfile(path):
                        result.append(Diagnostic("input.missing", f"Input not found: {path}", path=path))
        else:
            minimum = 2 if spec.tool == MANUAL_ENSEMBLE else 1
            if len(spec.inputs) < minimum:
                result.append(Diagnostic("inputs.empty", f"Select at least {minimum} input file(s)"))
            for path in spec.inputs:
                if not os.path.isfile(path):
                    result.append(Diagnostic("input.missing", f"Input not found: {path}", path=path))
        return result

    @staticmethod
    def _option_diagnostics(tool: str, settings: Settings) -> list[Diagnostic]:
        audio = settings.audio_tools
        if tool == TIME_STRETCH and not 0.1 <= audio.time_stretch_rate <= 10:
            return [Diagnostic("audio.rate", "Stretch rate must be between 0.1 and 10")]
        if tool == CHANGE_PITCH and not -10 <= audio.pitch_rate <= 10:
            return [Diagnostic("audio.pitch", "Pitch must be between -10 and 10 semitones")]
        if tool == APOLLO_RESTORE and (audio.apollo_overlap < 0 or audio.apollo_chunk_size <= 0):
            return [Diagnostic("audio.apollo.options", "Apollo overlap must be non-negative and chunk size positive")]
        return []

    def _resolve_apollo(
        self, settings: Settings, diagnostics: list[Diagnostic], level: ValidationLevel
    ) -> ModelDescriptor | None:
        record = self._resolve_apollo_record(settings, diagnostics)
        return (
            self._apollo_descriptor(record, diagnostics, level)
            if record is not None
            else None
        )

    def _resolve_apollo_record(
        self, settings: Settings, diagnostics: list[Diagnostic]
    ) -> ModelRecord | None:
        reference = str(settings.audio_tools.apollo_model or "")
        try:
            record = self.identities.lookup(reference)
            self._validate_apollo_record(record)
            return record
        except (OSError, TypeError, ValueError) as exc:
            diagnostics.append(Diagnostic("audio.apollo.model", str(exc)))
            return None

    @staticmethod
    def _validate_apollo_record(record: ModelRecord) -> None:
        if record.family != "apollo":
            raise ValueError("Audio restore requires an apollo: model")
        if not record.installed:
            raise ValueError(f"Apollo model {record.id!r} is not installed")
        if not record.identity_complete:
            detail = record.identity_error or "identity metadata is incomplete"
            raise ValueError(f"Apollo model {record.id!r}: {detail}")

    @staticmethod
    def _apollo_descriptor(
        record: ModelRecord,
        diagnostics: list[Diagnostic],
        level: ValidationLevel,
    ) -> ModelDescriptor | None:
        try:
            path = os.path.join(APOLLO_MODELS_DIR, record.backend_name)
            digest = None
            primary = None
            if level is not ValidationLevel.CONFIG:
                if not os.path.isfile(path):
                    raise ValueError(f"Apollo checkpoint is missing: {path}")
                data = ApolloModelData(record.backend_name, is_dry_check=True)
                if not data.is_model_status:
                    raise ValueError(f"Apollo configuration is unavailable for {record.id}")
                digest = data.model_hash
                primary = "Restored"
            return ModelDescriptor(
                record.id,
                record.family,
                record.basename,
                record.display,
                backend_name=record.backend_name,
                artifacts=record.artifacts,
                checkpoint=path,
                checkpoint_hash=digest,
                primary_stem=primary,
                metadata_source="model-local",
            )
        except (OSError, TypeError, ValueError) as exc:
            diagnostics.append(Diagnostic("audio.apollo.model", str(exc)))
            return None

    @staticmethod
    def _runtime_diagnostics(tool: str, settings: Settings) -> list[Diagnostic]:
        required = {"soundfile"}
        if tool == MATCH_INPUTS:
            required.add("matchering")
        missing = sorted(name for name in required if importlib.util.find_spec(name) is None)
        if missing:
            return [Diagnostic("runtime.dependencies", f"Missing Python packages: {', '.join(missing)}")]
        if tool in {TIME_STRETCH, CHANGE_PITCH}:
            from .external_tools import resolve_rubberband

            if not resolve_rubberband():
                return [Diagnostic("runtime.rubberband", "Rubber Band CLI was not found")]
        if tool == APOLLO_RESTORE:
            from .job_plan import device_runtime_diagnostics

            return device_runtime_diagnostics(settings)
        return []

    @staticmethod
    def _plan_units(spec: AudioJobSpec, settings: Settings) -> tuple[PlannedAudioUnit, ...]:
        extension = str(getattr(settings.process.save_format, "value", settings.process.save_format)).casefold()
        output = settings.process.export_path
        testing = "preview " if settings.process.testing_audio else ""

        def clean(path: str) -> str:
            return sanitize_filename_component(os.path.splitext(os.path.basename(path))[0]) or "audio"

        if spec.tool == MANUAL_ENSEMBLE:
            base = sanitize_filename_component(spec.name or clean(spec.inputs[0])) or "audio"
            algorithm = str(getattr(settings.audio_tools.choose_algorithm, "value", settings.audio_tools.choose_algorithm))
            suffix = f" ({sanitize_filename_component(algorithm)})" if algorithm else ""
            return (PlannedAudioUnit(spec.inputs, (os.path.join(output, f"{testing}{base}{suffix}.{extension}"),), base),)
        result: list[PlannedAudioUnit] = []
        if spec.tool in {ALIGN_INPUTS, MATCH_INPUTS}:
            for left, right in spec.pairs:
                if spec.tool == MATCH_INPUTS:
                    names = (f"{testing}{clean(left)} (Matched).{extension}",)
                else:
                    names = [f"{testing}{clean(right)} (Aligned).{extension}"]
                    if settings.mdx.is_save_align:
                        names.append(f"{testing}{clean(left)} (Inverted).{extension}")
                result.append(PlannedAudioUnit((left, right), tuple(os.path.join(output, name) for name in names), clean(left)))
            return tuple(result)
        suffix = {
            TIME_STRETCH: " time stretched",
            CHANGE_PITCH: " pitch shifted",
            APOLLO_RESTORE: " restored",
        }.get(spec.tool, "")
        for path in spec.inputs:
            base = clean(path)
            result.append(PlannedAudioUnit((path,), (os.path.join(output, f"{testing}{base}{suffix}.{extension}"),), base))
        return tuple(result)


__all__ = [
    "AUDIO_TOOL_IDS", "AudioJobResolver", "AudioJobSpec",
    "PlannedAudioUnit", "ResolvedAudioJob",
]
