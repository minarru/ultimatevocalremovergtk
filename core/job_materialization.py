"""Policy-scoped materialization and explicit filesystem/runtime observations."""

from __future__ import annotations

import dataclasses
import importlib.util
import os
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Mapping, Protocol, Sequence

from bundled.constants import (
    ENSEMBLE_MODE,
    INST_WITH_BACKING_VOCALS_STEM,
    INST_WITH_LEAD_VOCALS_STEM,
)

from .access_policy import access_policy
from .device import DeviceRequest
from .job_plan_types import Diagnostic, ModelDescriptor
from .job_projection import (
    DescriptorEvidence,
    NativeSettingsProjection,
    project_descriptor,
    project_native_settings,
    project_record_descriptors,
)
from .model_config import assemble_model
from .model_identity import ModelRecord
from .settings import Settings
from .stems import (
    StemBucket,
    StemRouteKind,
    derived_stem_route,
    model_stem_count,
    model_stem_routes,
)

if TYPE_CHECKING:
    from .model_config import ModelConfig


class PlanningMaterializer(Protocol):
    def assemble(
        self,
        settings: Settings,
        command: str,
        records: Sequence[ModelRecord],
        *,
        allow_network: bool,
        model_dependencies: Mapping[str, ModelRecord] | None,
    ) -> list[ModelConfig]: ...
    def load_checkpoints(self, models: Sequence[ModelConfig]) -> None: ...


class PlanningProbes(Protocol):
    def is_file(self, path: str) -> bool: ...
    def checkpoint_hash(self, path: str) -> str: ...
    def missing_runtime_packages(self) -> tuple[str, ...]: ...
    def device_diagnostics(self, settings: Settings) -> Sequence[Diagnostic]: ...


class DefaultPlanningProbes:
    def is_file(self, path: str) -> bool:
        return os.path.isfile(path)

    def checkpoint_hash(self, path: str) -> str:
        from .mdx_c_registry import compute_checkpoint_hash

        return str(compute_checkpoint_hash(path) or "")

    def missing_runtime_packages(self) -> tuple[str, ...]:
        return tuple(
            name for name in ("kthread", "soundfile") if importlib.util.find_spec(name) is None
        )

    def device_diagnostics(self, settings: Settings) -> Sequence[Diagnostic]:
        return device_runtime_diagnostics(settings)


class DefaultPlanningMaterializer:
    def __init__(self, repo: Any):
        self.repo = repo

    def assemble(
        self,
        settings: Settings,
        command: str,
        records: Sequence[ModelRecord],
        *,
        allow_network: bool = True,
        model_dependencies: Mapping[str, ModelRecord] | None = None,
    ) -> list[ModelConfig]:
        from .mdx_config_fetch import mdx_c_network

        with (
            access_policy(allow_network=allow_network, allow_metadata_writes=allow_network),
            mdx_c_network(allow_network),
        ):
            method_value = str(getattr(settings.process.method, "value", settings.process.method))
            if command == "ensemble" or method_value == ENSEMBLE_MODE:
                settings.ensemble.selected_models = [record.id for record in records]
                return assemble_model(
                    settings,
                    self.repo,
                    arch_type=ENSEMBLE_MODE,
                    model_dependencies=model_dependencies,
                )
            record = records[0]
            getattr(settings, record.family).model = record.id
            return assemble_model(
                settings,
                self.repo,
                record.id,
                record.method,
                model_dependencies=model_dependencies,
            )

    def load_checkpoints(self, models: Sequence[ModelConfig]) -> None:
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
            return [
                Diagnostic(
                    "runtime.device_unavailable",
                    f"Requested device {requested} resolved to {backend.backend_name}",
                )
            ]
    except (ImportError, RuntimeError, ValueError) as exc:
        return [Diagnostic("runtime.device", str(exc))]
    return []


@dataclass(frozen=True)
class TopologyMaterialization:
    models: tuple[ModelConfig, ...]
    primary_stems: Mapping[str, str]
    available: bool
    diagnostics: tuple[Diagnostic, ...] = ()


@dataclass(frozen=True)
class ModelMaterialization:
    models: list[ModelConfig]
    diagnostics: tuple[Diagnostic, ...] = ()


def materialize_topology(
    materializer: PlanningMaterializer,
    settings: Settings,
    command: str,
    records: Sequence[ModelRecord],
    primary: Mapping[str, ModelRecord],
    *,
    allow_network: bool,
) -> TopologyMaterialization:
    try:
        models = materializer.assemble(
            settings, command, records, allow_network=allow_network, model_dependencies={}
        )
        if len(models) != len(records) or any(
            not getattr(model, "model_status", False) for model in models
        ):
            raise ValueError("one or more primary model configurations are unavailable")
        stems = {
            path: str(getattr(model, "primary_stem", "") or "")
            for (path, _record), model in zip(primary.items(), models, strict=False)
        }
    except (OSError, ValueError) as exc:
        return TopologyMaterialization(
            (), {}, False, (Diagnostic("model.configuration", str(exc)),)
        )
    return TopologyMaterialization(tuple(models), stems, True)


def materialize_models(
    materializer: PlanningMaterializer,
    settings: Settings,
    command: str,
    records: Sequence[ModelRecord],
    dependencies: Mapping[str, ModelRecord],
    *,
    allow_network: bool,
) -> ModelMaterialization:
    models: list[ModelConfig] = []
    try:
        models = materializer.assemble(
            settings, command, records, allow_network=allow_network, model_dependencies=dependencies
        )
        if len(models) != len(records) or any(
            not getattr(model, "model_status", False) for model in models
        ):
            raise ValueError("one or more model configurations are unavailable")
    except (OSError, ValueError) as exc:
        # A returned invalid list still supplies descriptor/native/focus evidence.
        return ModelMaterialization(models, (Diagnostic("model.configuration", str(exc)),))
    return ModelMaterialization(models)


def metadata_source(model: Any, probes: PlanningProbes) -> str:
    return (
        "model-local"
        if probes.is_file(str(getattr(model, "model_hash_dir", "") or ""))
        else "model-catalog"
    )


def collect_descriptor_evidence(
    model: Any, probes: PlanningProbes, *, verify: bool
) -> DescriptorEvidence:
    path = str(getattr(model, "model_path", "") or "")
    digest = probes.checkpoint_hash(path) if verify and path and probes.is_file(path) else None
    routes = list(model_stem_routes(model))
    splitter = getattr(model, "vocal_split_model", None)
    if (
        splitter is not None
        and getattr(model, "is_vocal_split_model_activated", False)
        and not getattr(model, "is_ensemble_mode", False)
    ):
        routes.extend(
            dataclasses.replace(
                route,
                kind=StemRouteKind.SPLITTER,
                conditional=True,
                selected_by_default=True,
            )
            for route in model_stem_routes(splitter)
        )
        if getattr(model, "is_save_inst_vocal_splitter", False):
            routes.extend(
                (
                    derived_stem_route(
                        StemBucket.INST_WITH_BV,
                        label=INST_WITH_BACKING_VOCALS_STEM,
                        conditional=True,
                        selected_by_default=True,
                        kind=StemRouteKind.SPLITTER,
                    ),
                    derived_stem_route(
                        StemBucket.INST_WITH_LEAD,
                        label=INST_WITH_LEAD_VOCALS_STEM,
                        conditional=True,
                        selected_by_default=True,
                        kind=StemRouteKind.SPLITTER,
                    ),
                )
            )
    return DescriptorEvidence(
        checkpoint=path or None,
        checkpoint_hash=digest,
        primary_stem=getattr(model, "primary_stem", None),
        secondary_stem=getattr(model, "secondary_stem", None),
        backend_target_stem=getattr(model, "target_instrument", None),
        metadata_source=metadata_source(model, probes),
        stem_count=model_stem_count(model),
        is_karaoke=bool(getattr(model, "is_karaoke", False)),
        is_bv=bool(getattr(model, "is_bv_model", False)),
        stem_semantics=getattr(model, "stem_semantics", None),
        routes=tuple(routes),
        backend_primary_stem=(
            getattr(model, "primary_stem_native", None) or getattr(model, "primary_stem", None)
        ),
    )


def describe_models(
    records: Sequence[ModelRecord], models: Sequence[Any], probes: PlanningProbes, *, verify: bool
) -> tuple[ModelDescriptor, ...]:
    if not models:
        return project_record_descriptors(records)
    return tuple(
        project_descriptor(record, collect_descriptor_evidence(model, probes, verify=verify))
        for record, model in zip(records, models, strict=False)
    )


def enrich_native_settings(
    settings: Settings,
    provenance: Mapping[str, str],
    records: Sequence[ModelRecord],
    models: Sequence[Any],
    probes: PlanningProbes,
) -> NativeSettingsProjection:
    """Observe each metadata source immediately before applying its native values."""
    result = NativeSettingsProjection(settings, dict(provenance))
    for record, model in zip(records, models, strict=False):
        source = metadata_source(model, probes)
        result = project_native_settings(
            result.settings, result.provenance, (record,), (model,), (source,)
        )
    return result
