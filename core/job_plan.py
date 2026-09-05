"""Shared effective-job facade and ordered planning phase composition."""

from __future__ import annotations

import copy
import os
from typing import TYPE_CHECKING, Any, Sequence

from .device import DeviceRequest
from .export_naming import build_output_naming_context
from .job_acquisition import (
    DefaultMdxConfigurationFiles,
    MdxConfigurationFiles,
    acquire_configurations,
)
from .job_dependencies import (
    MODEL_SENTINELS as MODEL_SENTINELS,
)
from .job_dependencies import (
    DependencyPlanner,
    PlanningIdentities,
    RepositoryPlanningIdentities,
    selected_family_paths,
)
from .job_dependencies import active_model_paths as active_model_paths
from .job_diagnostics import (
    assess_inputs,
    assess_stem_focus,
    ensemble_pair_diagnostics,
    runtime_diagnostics,
    stem_semantics_diagnostics,
)
from .job_materialization import (
    DefaultPlanningMaterializer,
    DefaultPlanningProbes,
    PlanningMaterializer,
    PlanningProbes,
    describe_models,
    enrich_native_settings,
    materialize_models,
    materialize_topology,
)
from .job_materialization import device_runtime_diagnostics as device_runtime_diagnostics
from .job_naming import PlanningNaming, plan_inputs
from .job_plan_types import EMPTY_MODEL_IDENTITY_DIGEST as EMPTY_MODEL_IDENTITY_DIGEST
from .job_plan_types import Diagnostic as Diagnostic
from .job_plan_types import JobSpec as JobSpec
from .job_plan_types import ModelDescriptor as ModelDescriptor
from .job_plan_types import PlannedInput as PlannedInput
from .job_plan_types import PlannedOutput as PlannedOutput
from .job_plan_types import Provenance as Provenance
from .job_plan_types import ResolvedJob as ResolvedJob
from .job_plan_types import ValidationLevel as ValidationLevel
from .job_plan_types import compute_model_identity_digest as compute_model_identity_digest
from .job_plan_types import settings_fingerprint as settings_fingerprint
from .job_projection import select_output_routes
from .model_identity import ModelRecord
from .settings import Settings
from .stems import StemRoute

if TYPE_CHECKING:
    from .model_config import ModelConfig


def _debug_planned_output_routes(
    *,
    focus: str,
    positional: str,
    reason: str,
    routes: Sequence[StemRoute],
) -> None:
    """Opt-in trace when resolving planned export routes (``uvr-settings``)."""
    try:
        from core.debug_log import log_event

        log_event(
            "settings",
            "planned_outputs",
            focus=focus,
            positional=positional,
            reason=reason,
            routes=tuple(
                {
                    "label": route.label,
                    "role": str(route.role),
                    "native": route.native.raw if route.native is not None else None,
                }
                for route in routes
            ),
            route_count=len(routes),
        )
    except Exception:
        pass


def planned_output_routes(
    settings: Settings, descriptors: Sequence[ModelDescriptor], *, command: str
) -> tuple[StemRoute, ...]:
    """Select routes and emit the existing best-effort output trace."""
    result = select_output_routes(settings, descriptors, command=command)
    _debug_planned_output_routes(
        focus=result.focus, positional=result.positional, reason=result.reason, routes=result.routes
    )
    return result.routes


def planned_output_stems(
    settings: Settings,
    descriptors: Sequence[ModelDescriptor],
    *,
    command: str,
) -> tuple[tuple[str, bool], ...]:
    routes = planned_output_routes(settings, descriptors, command=command)
    return tuple(
        (
            route.label,
            route.conditional,
        )
        for route in routes
    )


class JobResolver:
    def __init__(
        self,
        repo: Any,
        *,
        identities: PlanningIdentities | None = None,
        configs: MdxConfigurationFiles | None = None,
        materializer: PlanningMaterializer | None = None,
        probes: PlanningProbes | None = None,
        naming: PlanningNaming | None = None,
    ):
        self.repo = repo
        self.identities = (
            identities if identities is not None else RepositoryPlanningIdentities(repo)
        )
        self.configs = configs if configs is not None else DefaultMdxConfigurationFiles()
        self.materializer = (
            materializer if materializer is not None else DefaultPlanningMaterializer(repo)
        )
        self.probes = probes if probes is not None else DefaultPlanningProbes()
        self.naming = naming if naming is not None else build_output_naming_context
        self.dependencies = DependencyPlanner(self.identities, self.configs)

    def resolve(
        self,
        spec: JobSpec,
        level: ValidationLevel = ValidationLevel.MODEL,
        *,
        allow_network: bool = True,
    ) -> ResolvedJob:
        settings = copy.deepcopy(spec.settings)
        settings.process.export_path = os.path.abspath(spec.output)
        diagnostics = list(
            assess_inputs(
                spec.inputs, spec.output, tuple(self.probes.is_file(path) for path in spec.inputs)
            )
        )
        selection = self.dependencies.select(settings, spec.command)
        diagnostics.extend(selection.diagnostics)
        dependencies = selection.dependencies
        primary = selection.primary
        available = not selection.diagnostics
        records = []
        topology_models: tuple[ModelConfig, ...] = ()
        models: list[ModelConfig] = []
        if available:
            if dependencies:
                acquired = acquire_configurations(
                    dependencies, self.identities, self.configs, allow_network=allow_network
                )
                dependencies = acquired.dependencies
                diagnostics.extend(acquired.diagnostics)
                available = acquired.available
                if available:
                    primary = {
                        path: dependencies[path]
                        for path, _ in selected_family_paths(settings, spec.command)
                    }
                    karaoke = self.dependencies.karaoke_diagnostics(settings, dependencies)
                    diagnostics.extend(karaoke)
                    available = not karaoke
            records = self.dependencies.primary_records(dependencies, spec.command)

        if records and available and selection.needs_topology:
            topology = materialize_topology(
                self.materializer,
                settings,
                spec.command,
                records,
                primary,
                allow_network=allow_network,
            )
            diagnostics.extend(topology.diagnostics)
            topology_models = topology.models
            available = topology.available
            if available:
                second = self.dependencies.select(
                    settings, spec.command, primary=primary, primary_stems=topology.primary_stems
                )
                diagnostics.extend(second.diagnostics)
                available = not second.diagnostics
                if available:
                    acquired = acquire_configurations(
                        second.dependencies,
                        self.identities,
                        self.configs,
                        allow_network=allow_network,
                    )
                    dependencies = acquired.dependencies
                    diagnostics.extend(acquired.diagnostics)
                    available = acquired.available
                    if available:
                        karaoke = self.dependencies.karaoke_diagnostics(settings, dependencies)
                        diagnostics.extend(karaoke)
                        available = not karaoke
                        if available:
                            # Failed second karaoke retains first-pass descriptors but refreshed dependencies.
                            records = self.dependencies.primary_records(dependencies, spec.command)

        verify = level is not ValidationLevel.CONFIG
        if records and verify and available:
            materialized = materialize_models(
                self.materializer,
                settings,
                spec.command,
                records,
                dependencies,
                allow_network=allow_network,
            )
            models = materialized.models
            diagnostics.extend(materialized.diagnostics)
        descriptor_models = models or topology_models
        descriptors = describe_models(records, descriptor_models, self.probes, verify=verify)
        provenance = dict(spec.provenance)
        if models:
            native = enrich_native_settings(
                settings,
                provenance,
                records,
                models,
                self.probes,
            )
            settings, provenance = native.settings, dict(native.provenance)
        diagnostics.extend(stem_semantics_diagnostics(descriptors))
        diagnostics.extend(ensemble_pair_diagnostics(settings, descriptors, command=spec.command))
        diagnostics.extend(
            assess_stem_focus(settings, models, descriptors, provenance, command=spec.command)
        )
        if level in {ValidationLevel.RUNTIME, ValidationLevel.LOAD}:
            diagnostics.extend(runtime_diagnostics(settings, self.probes))
        if level is ValidationLevel.LOAD and models and not diagnostics:
            try:
                self.materializer.load_checkpoints(models)
            except (ImportError, OSError, ValueError) as exc:
                diagnostics.append(Diagnostic("model.load", str(exc)))
        planned = self.plan_inputs(settings, spec, descriptors)
        plan = ResolvedJob(
            command=spec.command,
            settings=settings,
            inputs=planned,
            models=descriptors,
            provenance=provenance,
            diagnostics=tuple(diagnostics),
            validation_level=level,
            inventory_generation=self.identities.inventory_generation,
            settings_fingerprint=settings_fingerprint(settings),
            device=DeviceRequest.from_settings(settings.process).id,
            output=settings.process.export_path,
            metadata=dict(spec.metadata),
            model_dependencies=dependencies,
            model_identity_digest=compute_model_identity_digest(dependencies),
        )
        from .debug_log import log_event

        log_event(
            "settings",
            "plan_resolved",
            command=plan.command,
            validation_level=plan.validation_level.value,
            input_count=len(plan.inputs),
            model_count=len(plan.models),
            dependency_count=len(plan.model_dependencies),
            diagnostic_count=len(plan.diagnostics),
            error_count=sum(item.severity == "error" for item in plan.diagnostics),
            inventory_generation=plan.inventory_generation,
            device=plan.device,
        )
        return plan

    def is_current(self, plan: ResolvedJob) -> bool:
        if plan.inventory_generation != self.identities.inventory_generation:
            return False
        try:
            primary_dependencies = self.dependencies.primary_dependencies(
                plan.settings,
                plan.command,
            )
            dependencies = self.dependencies.dependencies(
                plan.settings,
                plan.command,
                primary_dependencies=primary_dependencies,
                primary_stems={
                    path: descriptor.primary_stem
                    for (path, _record), descriptor in zip(
                        primary_dependencies.items(), plan.models, strict=False
                    )
                    if descriptor.primary_stem
                },
            )
            self.dependencies.validate_karaoke(plan.settings, dependencies)
        except ValueError:
            return False
        if compute_model_identity_digest(dependencies) != plan.model_identity_digest:
            return False
        for descriptor in plan.models:
            if not descriptor.checkpoint or not descriptor.checkpoint_hash:
                continue
            if not self.probes.is_file(descriptor.checkpoint):
                return False
            if self.probes.checkpoint_hash(descriptor.checkpoint) != descriptor.checkpoint_hash:
                return False
        return True

    def adopt(
        self,
        spec: JobSpec,
        records: Sequence[ModelRecord],
        models: Sequence[Any],
        *,
        level: ValidationLevel = ValidationLevel.MODEL,
    ) -> ResolvedJob:
        """Build the shared immutable plan from models already dry-assembled by an adapter."""
        settings = copy.deepcopy(spec.settings)
        primary_dependencies = self.dependencies.primary_dependencies(settings, spec.command)
        dependencies = self.dependencies.dependencies(
            settings,
            spec.command,
            primary_dependencies=primary_dependencies,
            primary_stems={
                path: str(getattr(model, "primary_stem", "") or "")
                for (path, _record), model in zip(
                    primary_dependencies.items(), models, strict=False
                )
            },
        )
        self.dependencies.validate_karaoke(settings, dependencies)
        descriptors = (
            describe_models(
                records, models, self.probes, verify=level is not ValidationLevel.CONFIG
            )
            if models
            else ()
        )
        native = enrich_native_settings(
            settings,
            spec.provenance,
            records,
            models,
            self.probes,
        )
        settings, provenance = native.settings, dict(native.provenance)
        diagnostics = tuple(
            (
                *ensemble_pair_diagnostics(settings, descriptors, command=spec.command),
                *assess_stem_focus(
                    settings,
                    models,
                    descriptors,
                    provenance,
                    command=spec.command,
                ),
            )
        )
        plan = ResolvedJob(
            spec.command,
            settings,
            self.plan_inputs(settings, spec, descriptors),
            descriptors,
            provenance,
            diagnostics,
            level,
            self.identities.inventory_generation,
            settings_fingerprint(settings),
            DeviceRequest.from_settings(settings.process).id,
            settings.process.export_path,
            dict(spec.metadata),
            dependencies,
            compute_model_identity_digest(dependencies),
        )
        from .debug_log import log_event

        log_event(
            "settings",
            "plan_adopted",
            command=plan.command,
            validation_level=plan.validation_level.value,
            input_count=len(plan.inputs),
            model_count=len(plan.models),
            dependency_count=len(plan.model_dependencies),
            diagnostic_count=len(plan.diagnostics),
        )
        return plan

    def plan_inputs(
        self, settings: Settings, spec: JobSpec, descriptors: Sequence[ModelDescriptor]
    ) -> tuple[PlannedInput, ...]:
        routes = planned_output_routes(settings, descriptors, command=spec.command)
        return plan_inputs(settings, spec, descriptors, routes, self.naming)


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
