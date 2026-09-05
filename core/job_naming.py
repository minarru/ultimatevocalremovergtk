"""Per-input naming adapter; testing-audio clock reads stay inside the input loop."""

from __future__ import annotations

from typing import Protocol, Sequence

from .export_naming import (
    OutputNamingContext,
    build_output_naming_context,
    ensemble_name_for_export,
)
from .job_plan_types import JobSpec, ModelDescriptor, PlannedInput
from .job_projection import project_input
from .settings import Settings
from .stems import StemRoute


class PlanningNaming(Protocol):
    def __call__(
        self,
        settings: Settings,
        input_path: str,
        *,
        export_path: str,
        file_index: int | None = None,
        file_total: int = 1,
        model_label: str | None = None,
        ensemble_label: str | None = None,
        force_ensemble_label: bool = False,
    ) -> OutputNamingContext: ...


def plan_inputs(
    settings: Settings,
    spec: JobSpec,
    descriptors: Sequence[ModelDescriptor],
    routes: Sequence[StemRoute],
    naming_provider: PlanningNaming = build_output_naming_context,
) -> tuple[PlannedInput, ...]:
    descriptor = descriptors[0] if descriptors else ModelDescriptor("", "", "", "")
    ensemble_label = (
        ensemble_name_for_export(settings.ensemble.chosen_ensemble)
        if spec.command == "ensemble"
        else None
    )
    model_label = descriptor.display if spec.command != "ensemble" else None
    result = []
    for index, path in enumerate(spec.inputs, start=1):
        naming = naming_provider(
            settings,
            path,
            export_path=settings.process.export_path,
            file_index=index,
            file_total=len(spec.inputs),
            model_label=model_label,
            ensemble_label=ensemble_label,
            force_ensemble_label=(
                spec.command == "ensemble" and bool(settings.ensemble.append_ensemble_name)
            ),
        )
        result.append(project_input(path, naming, routes, command=spec.command))
    return tuple(result)
