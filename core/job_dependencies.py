"""Exact active identity selection and secondary topology decisions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Protocol, Sequence

from bundled.constants import (
    CHOOSE_MODEL,
    DEMUCS_ARCH_TYPE,
    ENSEMBLE_MODE,
    MDX_ARCH_TYPE,
    NO_MODEL,
    VR_ARCH_PM,
)

from .access_policy import access_policy
from .job_acquisition import MdxConfigurationFiles, is_repairable_mdx_config_dependency
from .job_plan_types import Diagnostic
from .model_config.determine import secondary_slot_for_primary_stem
from .model_identity import ModelIdentityService, ModelRecord
from .model_stem_manifest import load_bundled_stem_semantics
from .settings import Settings
from .stem_pairs import is_stem_mode, normalize_stem_pair_id, stem_pair_definition

MODEL_SENTINELS = frozenset({CHOOSE_MODEL, NO_MODEL, ""})
_MODEL_FAMILIES = frozenset({"vr", "mdx", "demucs"})
_SECONDARY_SLOTS = ("voc_inst", "other", "bass", "drums")


class PlanningIdentities(Protocol):
    @property
    def inventory_generation(self) -> int: ...
    def lookup(self, canonical_id: str) -> ModelRecord: ...
    def invalidate(self) -> None: ...
    def karaoke_ids(self, settings: Settings) -> Sequence[str]: ...


class RepositoryPlanningIdentities:
    def __init__(self, repo: Any):
        self.repo = repo
        self.service = ModelIdentityService(repo)

    @property
    def inventory_generation(self) -> int:
        return int(getattr(self.repo, "inventory_generation", 0))

    def lookup(self, canonical_id: str) -> ModelRecord:
        return self.service.lookup(canonical_id)

    def invalidate(self) -> None:
        invalidate = getattr(self.repo, "invalidate_models", None)
        if callable(invalidate):
            invalidate()
        self.service.invalidate()

    def karaoke_ids(self, settings: Settings) -> Sequence[str]:
        with access_policy(allow_network=False, allow_metadata_writes=False):
            return self.repo.karaoke_model_list(settings)


@dataclass(frozen=True)
class DependencySelection:
    dependencies: Mapping[str, ModelRecord]
    primary: Mapping[str, ModelRecord]
    needs_topology: bool
    diagnostics: tuple[Diagnostic, ...] = ()


def _ensemble_primary_label(pair_id: str) -> str:
    """Reviewed display label for the pair's first exact role, if any."""
    definition = stem_pair_definition(pair_id)
    if definition is None:
        return ""
    role = load_bundled_stem_semantics().roles.get(definition.roles[0])
    return role.display if role is not None else ""


def _model_reference(settings: Settings, path: str) -> str:
    if path.startswith("ensemble.selected_models["):
        index = int(path.removeprefix("ensemble.selected_models[").removesuffix("]"))
        return str(settings.ensemble.selected_models[index] or "")
    section_name, field_name = path.split(".", 1)
    return str(getattr(getattr(settings, section_name), field_name) or "")


def selected_family_paths(settings: Settings, command: str) -> list[tuple[str, str]]:
    method_value = str(getattr(settings.process.method, "value", settings.process.method))
    if command == "ensemble" or method_value == ENSEMBLE_MODE:
        return [
            (f"ensemble.selected_models[{index}]", str(reference or ""))
            for index, reference in enumerate(settings.ensemble.selected_models)
            if str(reference or "") not in MODEL_SENTINELS
        ]
    family = {
        VR_ARCH_PM: "vr",
        MDX_ARCH_TYPE: "mdx",
        DEMUCS_ARCH_TYPE: "demucs",
    }.get(method_value)
    if family is None:
        return []
    reference = str(getattr(settings, family).model or "")
    return [] if reference in MODEL_SENTINELS else [(f"{family}.model", reference)]


def active_model_paths(
    settings: Settings,
    *,
    command: str,
    primary: ModelRecord | Sequence[ModelRecord] | None = None,
    source_layout: str | None = None,
    primary_stems: Mapping[str, str] | None = None,
) -> tuple[str, ...]:
    """Return stable settings paths for every active separation dependency."""
    primary_paths = selected_family_paths(settings, command)
    paths = [path for path, _reference in primary_paths]
    if primary is None:
        primaries: tuple[ModelRecord, ...] = ()
    elif isinstance(primary, ModelRecord):
        primaries = (primary,)
    else:
        primaries = tuple(primary)
    selected_families = {record.family for record in primaries} or {
        reference.partition(":")[0]
        for _path, reference in primary_paths
        if reference.partition(":")[0] in _MODEL_FAMILIES
    }
    method_value = str(getattr(settings.process.method, "value", settings.process.method))
    if not selected_families and command != "ensemble":
        family = {
            VR_ARCH_PM: "vr",
            MDX_ARCH_TYPE: "mdx",
            DEMUCS_ARCH_TYPE: "demucs",
        }.get(method_value)
        if family:
            selected_families.add(family)

    ensemble_pair_id = normalize_stem_pair_id(settings.ensemble.main_stem)
    ensemble_multi = command == "ensemble" and is_stem_mode(ensemble_pair_id)
    demucs_layouts = {
        record.demucs.source_layout
        for record in primaries
        if record.family == "demucs" and record.demucs is not None
    }
    if source_layout:
        demucs_layouts.add(source_layout)
    native_stems_by_family: dict[str, set[str]] = {}
    for index, record in enumerate(primaries):
        primary_path = primary_paths[index][0] if index < len(primary_paths) else ""
        native_stem = str(
            (primary_stems or {}).get(primary_path) or (primary_stems or {}).get(record.id) or ""
        )
        if native_stem:
            native_stems_by_family.setdefault(record.family, set()).add(native_stem)

    for family in ("vr", "mdx", "demucs"):
        if family not in selected_families:
            continue
        section = getattr(settings, family)
        if not section.is_secondary_model_activate:
            continue
        all_slots = family == "demucs" and (
            ensemble_multi
            or (command != "ensemble" and bool(demucs_layouts.intersection({"4_stem", "6_stem"})))
        )
        if all_slots:
            slots = _SECONDARY_SLOTS
        else:
            selected_stems = native_stems_by_family.get(family, set())
            if not selected_stems:
                selected_stems = {
                    str(
                        (primary_stems or {}).get(family)
                        or (
                            _ensemble_primary_label(ensemble_pair_id)
                            if command == "ensemble"
                            else getattr(section, "stems", "")
                        )
                        or ""
                    )
                }
            if family == "demucs" and command == "ensemble":
                selected_stems = {_ensemble_primary_label(ensemble_pair_id)}
            selected_slots = {
                secondary_slot_for_primary_stem(stem) or "voc_inst" for stem in selected_stems
            }
            slots = tuple(slot for slot in _SECONDARY_SLOTS if slot in selected_slots)
        for slot in slots:
            path = f"{family}.{slot}_secondary_model"
            if _model_reference(settings, path) not in MODEL_SENTINELS:
                paths.append(path)

    if (
        settings.process.vocal_splitter_enabled
        and str(settings.process.vocal_splitter or "") not in MODEL_SENTINELS
    ):
        paths.append("process.vocal_splitter")
    if (
        settings.demucs.is_pre_proc_model_activate
        and str(settings.demucs.pre_proc_model or "") not in MODEL_SENTINELS
    ):
        paths.append("demucs.pre_proc_model")
    return tuple(paths)


class DependencyPlanner:
    def __init__(self, identities: PlanningIdentities, configs: MdxConfigurationFiles):
        self.identities = identities
        self.configs = configs

    def primary_dependencies(
        self,
        settings: Settings,
        command: str,
        *,
        allow_repairable_mdx_config: bool = False,
    ) -> dict[str, ModelRecord]:
        primary_dependencies: dict[str, ModelRecord] = {}
        for path, reference in selected_family_paths(settings, command):
            record = self.identities.lookup(reference)
            if path.startswith("ensemble.selected_models["):
                allowed = _MODEL_FAMILIES
            else:
                allowed = frozenset({path.partition(".")[0]})
            self.validate_family(
                path,
                record,
                allowed,
                allow_repairable_mdx_config=allow_repairable_mdx_config,
            )
            primary_dependencies[path] = record

        method_value = str(getattr(settings.process.method, "value", settings.process.method))
        is_ensemble = command == "ensemble" or method_value == ENSEMBLE_MODE
        if is_ensemble and len(primary_dependencies) < 2:
            raise ValueError("an ensemble requires at least two models")

        return primary_dependencies

    def dependencies(
        self,
        settings: Settings,
        command: str,
        *,
        primary_dependencies: Mapping[str, ModelRecord] | None = None,
        primary_stems: Mapping[str, str] | None = None,
        allow_repairable_mdx_config: bool = False,
    ) -> dict[str, ModelRecord]:
        if primary_dependencies is None:
            primary_dependencies = self.primary_dependencies(
                settings,
                command,
                allow_repairable_mdx_config=allow_repairable_mdx_config,
            )

        dependencies = dict(primary_dependencies)
        paths = active_model_paths(
            settings,
            command=command,
            primary=tuple(primary_dependencies.values()),
            primary_stems=primary_stems,
        )
        for path in paths:
            if path in dependencies:
                continue
            record = self.identities.lookup(_model_reference(settings, path))
            allowed = (
                frozenset({"vr", "mdx"})
                if path in {"process.vocal_splitter", "demucs.pre_proc_model"}
                else _MODEL_FAMILIES
            )
            self.validate_family(
                path,
                record,
                allowed,
                allow_repairable_mdx_config=allow_repairable_mdx_config,
            )
            dependencies[path] = record
        return dependencies

    def validate_karaoke(
        self,
        settings: Settings,
        dependencies: Mapping[str, ModelRecord],
    ) -> None:
        record = dependencies.get("process.vocal_splitter")
        if record is None:
            return
        karaoke_ids = {str(value) for value in self.identities.karaoke_ids(settings)}
        if record.id not in karaoke_ids:
            raise ValueError(
                f"process.vocal_splitter references model {record.id!r}, which "
                "is not karaoke/BV eligible"
            )

    @staticmethod
    def needs_topology(settings: Settings, command: str) -> bool:
        selected_families = {
            reference.partition(":")[0]
            for _path, reference in selected_family_paths(settings, command)
        }
        return any(
            family in selected_families
            and bool(getattr(settings, family).is_secondary_model_activate)
            for family in _MODEL_FAMILIES
        )

    def validate_family(
        self,
        path: str,
        record: ModelRecord,
        allowed: frozenset[str],
        *,
        allow_repairable_mdx_config: bool = False,
    ) -> None:
        if record.family not in allowed:
            expected = ", ".join(sorted(allowed))
            raise ValueError(f"{path} references {record.id!r}, but requires family {expected}")
        if not record.installed:
            raise ValueError(f"{path} references model {record.id!r}, which is not installed")
        if not record.identity_complete:
            if allow_repairable_mdx_config and is_repairable_mdx_config_dependency(
                record, self.configs
            ):
                return
            detail = record.identity_error or "identity metadata is incomplete"
            raise ValueError(f"{path} references model {record.id!r}: {detail}")

    @staticmethod
    def primary_records(dependencies: Mapping[str, ModelRecord], command: str) -> list[ModelRecord]:
        if command == "ensemble":
            return [
                record
                for path, record in dependencies.items()
                if path.startswith("ensemble.selected_models[")
            ]
        return [
            record
            for path, record in dependencies.items()
            if path in {"vr.model", "mdx.model", "demucs.model"}
        ]

    def select(
        self,
        settings: Settings,
        command: str,
        *,
        primary: Mapping[str, ModelRecord] | None = None,
        primary_stems: Mapping[str, str] | None = None,
    ) -> DependencySelection:
        needs_topology = self.needs_topology(settings, command)
        try:
            if primary is None and needs_topology:
                dependencies = self.primary_dependencies(
                    settings, command, allow_repairable_mdx_config=True
                )
            else:
                dependencies = self.dependencies(
                    settings,
                    command,
                    primary_dependencies=primary,
                    primary_stems=primary_stems,
                    allow_repairable_mdx_config=True,
                )
            selected = {
                path: dependencies[path] for path, _ in selected_family_paths(settings, command)
            }
        except ValueError as exc:
            return DependencySelection(
                {}, {}, needs_topology, (Diagnostic("model.identity", str(exc)),)
            )
        return DependencySelection(dependencies, selected, needs_topology)

    def karaoke_diagnostics(
        self, settings: Settings, dependencies: Mapping[str, ModelRecord]
    ) -> tuple[Diagnostic, ...]:
        try:
            self.validate_karaoke(settings, dependencies)
        except ValueError as exc:
            return (Diagnostic("model.identity", str(exc)),)
        return ()
