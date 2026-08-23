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
    CHOOSE_MODEL,
    DEMUCS_4_SOURCE_LIST,
    DEMUCS_ARCH_TYPE,
    ENSEMBLE_MODE,
    INST_WITH_BACKING_VOCALS_STEM,
    INST_WITH_LEAD_VOCALS_STEM,
    MDX_ARCH_TYPE,
    NO_MODEL,
    VR_ARCH_PM,
)

from .device import DeviceRequest
from .export_naming import (
    OutputNamingContext,
    build_output_naming_context,
    format_stem_basename,
)
from .model_config import assemble_model
from .model_config.determine import secondary_slot_for_primary_stem
from .model_identity import (
    DemucsSpec,
    MdxSpec,
    ModelArtifacts,
    ModelIdentityService,
    ModelRecord,
)
from .access_policy import access_policy
from .settings import Settings
from .stems import (
    EnsemblePair,
    FOCUS_PRIMARY,
    FOCUS_SECONDARY,
    StemBucket,
    StemLiteral,
    StemRoute,
    StemRouteKind,
    StemSelectionStatus,
    coerce_ensemble_pair,
    derived_stem_route,
    focus_bucket,
    model_stem_routes,
    model_stem_count,
    positional_stem_focus,
    select_ensemble_stem_routes,
    select_stem_routes,
    ui_label,
)


MODEL_SENTINELS = frozenset({CHOOSE_MODEL, NO_MODEL, ""})
_MODEL_FAMILIES = frozenset({"vr", "mdx", "demucs"})
_SECONDARY_SLOTS = ("voc_inst", "other", "bass", "drums")


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
    payload = {
        path: _identity_digest_entry(dependencies[path])
        for path in sorted(dependencies)
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return f"sha256:{hashlib.sha256(canonical.encode('utf-8')).hexdigest()}"


EMPTY_MODEL_IDENTITY_DIGEST = compute_model_identity_digest({})


def _model_reference(settings: Settings, path: str) -> str:
    if path.startswith("ensemble.selected_models["):
        index = int(path.removeprefix("ensemble.selected_models[").removesuffix("]"))
        return str(settings.ensemble.selected_models[index] or "")
    section_name, field_name = path.split(".", 1)
    return str(getattr(getattr(settings, section_name), field_name) or "")


def _selected_family_paths(settings: Settings, command: str) -> list[tuple[str, str]]:
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
    reference = str(getattr(getattr(settings, family), "model") or "")
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
    primary_paths = _selected_family_paths(settings, command)
    paths = [path for path, _reference in primary_paths]
    if primary is None:
        primaries: tuple[ModelRecord, ...] = ()
    elif isinstance(primary, ModelRecord):
        primaries = (primary,)
    else:
        primaries = tuple(primary)
    selected_families = {
        record.family for record in primaries
    } or {
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

    ensemble_multi = (
        command == "ensemble"
        and coerce_ensemble_pair(settings.ensemble.main_stem).is_multi_or_four()
    )
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
            (primary_stems or {}).get(primary_path)
            or (primary_stems or {}).get(record.id)
            or ""
        )
        if native_stem:
            native_stems_by_family.setdefault(record.family, set()).add(native_stem)

    for family in ("vr", "mdx", "demucs"):
        if family not in selected_families:
            continue
        section = getattr(settings, family)
        if not section.is_secondary_model_activate:
            continue
        all_slots = (
            family == "demucs"
            and (
                ensemble_multi
                or (
                    command != "ensemble"
                    and bool(demucs_layouts.intersection({"4_stem", "6_stem"}))
                )
            )
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
                            coerce_ensemble_pair(
                                settings.ensemble.main_stem
                            ).stem_halves()[0]
                            if command == "ensemble" else getattr(section, "stems", "")
                        )
                        or ""
                    )
                }
            if family == "demucs" and command == "ensemble":
                selected_stems = {
                    coerce_ensemble_pair(
                        settings.ensemble.main_stem
                    ).stem_halves()[0]
                }
            selected_slots = {
                secondary_slot_for_primary_stem(stem) or "voc_inst"
                for stem in selected_stems
            }
            slots = tuple(
                slot for slot in _SECONDARY_SLOTS if slot in selected_slots
            )
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
    backend_name: str = ""
    artifacts: ModelArtifacts = field(default_factory=lambda: ModelArtifacts(""))
    demucs: DemucsSpec | None = None
    mdx: MdxSpec | None = None
    checkpoint: str | None = None
    checkpoint_hash: str | None = None
    primary_stem: str | None = None
    secondary_stem: str | None = None
    metadata_source: str | None = None
    stem_count: int = 0
    is_karaoke: bool = False
    is_bv: bool = False
    routes: tuple[StemRoute, ...] = ()


@dataclass(frozen=True)
class PlannedOutput:
    path: str
    stem: str
    conditional: bool = False
    concept: str = ""


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
            "models": [dataclasses.asdict(model) for model in self.models],
            "model_dependencies": {
                path: record.id
                for path, record in sorted(self.model_dependencies.items())
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


def settings_fingerprint(settings: Settings) -> str:
    payload = json.dumps(settings.to_json_dict(), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _checkpoint_hash(path: str) -> str:
    from .mdx_c_registry import compute_checkpoint_hash

    return str(compute_checkpoint_hash(path) or "")


def _descriptor(record: ModelRecord, model: Any, verify: bool) -> ModelDescriptor:
    path = str(getattr(model, "model_path", "") or "")
    digest = _checkpoint_hash(path) if verify and path and os.path.isfile(path) else None
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
            routes.extend((
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
            ))
    return ModelDescriptor(
        id=record.id,
        family=record.family,
        basename=record.basename,
        display=record.display,
        backend_name=record.backend_name,
        artifacts=record.artifacts,
        demucs=record.demucs,
        mdx=record.mdx,
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
        routes=tuple(routes),
    )


def _stem_focus_diagnostics(
    settings: Settings,
    models: Sequence[Any],
    descriptors: Sequence[ModelDescriptor],
    provenance: Mapping[str, str] | None = None,
    *,
    command: str = "separate",
) -> list[Diagnostic]:
    """Report a ``process.stem_focus`` that names none of a model's stems.

    Such a focus cannot be honored, and the run silently falls back to
    exporting every stem — worth saying out loud before a long job rather
    than leaving the user to notice the extra files afterwards.
    """
    focus = str(settings.process.stem_focus or "")
    if not focus or positional_stem_focus(focus):
        return []
    source = (provenance or {}).get("process.stem_focus", "")
    severity = "error" if source == Provenance.CLI.value else "warning"
    if command == "ensemble":
        routes, union = _ensemble_output_routes(settings, descriptors)
        selection = select_ensemble_stem_routes(routes, union, focus)
        if selection.status is StemSelectionStatus.MATCHED:
            return []
        insufficient = selection.status is StemSelectionStatus.INSUFFICIENT_MEMBERS
        available = ", ".join(route.label for route in routes) or "none"
        return [Diagnostic(
            (
                "stems.focus_insufficient_members"
                if insufficient else "stems.focus_unmatched"
            ),
            (
                f"stem focus {focus!r} has fewer than two ensemble contributors"
                if insufficient
                else f"stem focus {focus!r} matches no ensemble output"
            ) + f" (available: {available}); exporting all stems",
            severity,
        )]

    result: list[Diagnostic] = []
    for index, model in enumerate(models):
        if getattr(model, "is_vocal_split_model", False):
            continue
        routes = (
            descriptors[index].routes
            if index < len(descriptors) and descriptors[index].routes
            else model_stem_routes(model)
        )
        selection = select_stem_routes(routes, focus)
        if selection.status is StemSelectionStatus.MATCHED:
            continue
        label = (
            descriptors[index].display
            if index < len(descriptors)
            else getattr(model, "model_basename", "") or "model"
        )
        stems = ", ".join(route.label for route in routes)
        result.append(
            Diagnostic(
                "stems.focus_unmatched",
                f"stem focus {focus!r} matches no stem of {label}"
                + (f" (has {stems}); exporting all stems" if stems else "; exporting all stems"),
                severity,
            )
        )
    return result


def _fallback_descriptor_routes(descriptor: ModelDescriptor) -> tuple[StemRoute, ...]:
    """Route inventory for older callers constructing descriptors directly."""
    if descriptor.routes:
        return descriptor.routes

    class _DescriptorModel:
        primary_stem = descriptor.primary_stem
        secondary_stem = descriptor.secondary_stem
        mdx_model_stems = tuple(
            stem for stem in (descriptor.primary_stem, descriptor.secondary_stem) if stem
        )
        demucs_source_list: tuple[str, ...] = ()
        mdx_stem_count = descriptor.stem_count
        demucs_stem_count = 0
        is_karaoke = descriptor.is_karaoke
        is_bv_model = descriptor.is_bv
        is_vocal_split_model = False

    routes = model_stem_routes(_DescriptorModel())
    if routes:
        return routes
    return (
        derived_stem_route(
            StemLiteral("Primary"), label="Primary", selected_by_default=True
        ),
        derived_stem_route(
            StemLiteral("Secondary"), label="Secondary", selected_by_default=True
        ),
    )


def _ensemble_output_routes(
    settings: Settings, descriptors: Sequence[ModelDescriptor]
) -> tuple[tuple[StemRoute, ...], tuple[StemRoute, ...]]:
    """Return viable final routes and the union before contributor filtering."""
    pair = coerce_ensemble_pair(settings.ensemble.main_stem)
    if not pair.is_multi_or_four():
        routes_list: list[StemRoute] = []
        for bucket, label in zip(pair.buckets(), pair.stem_halves()):
            if not label:
                continue
            route_concept: StemBucket | StemLiteral = (
                bucket if bucket is not StemBucket.UNKNOWN else StemLiteral(label)
            )
            routes_list.append(
                derived_stem_route(
                    route_concept,
                    label=label,
                    selected_by_default=True,
                )
            )
        routes = tuple(routes_list)
        return routes, routes

    if pair is EnsemblePair.FOUR_STEM:
        standard = tuple(
            derived_stem_route(
                focus_bucket(stem), label=stem, tag=stem, selected_by_default=True
            )
            for stem in DEMUCS_4_SOURCE_LIST
        )
        if not any(descriptor.routes for descriptor in descriptors):
            return standard, standard
        counts = {route.concept.casefold(): 0 for route in standard}
        for descriptor in descriptors:
            member_concepts = {
                route.concept.casefold()
                for route in _fallback_descriptor_routes(descriptor)
                if route.selected_by_default
            }
            for concept in counts:
                counts[concept] += int(concept in member_concepts)
        union = tuple(
            route for route in standard if counts[route.concept.casefold()] >= 1
        )
        viable = tuple(
            route for route in standard if counts[route.concept.casefold()] >= 2
        )
        return viable, union

    contributors: dict[str, list[StemRoute]] = {}
    order: list[str] = []
    for descriptor in descriptors:
        seen_member: set[str] = set()
        for route in _fallback_descriptor_routes(descriptor):
            key = route.concept.casefold()
            if key in seen_member or not route.selected_by_default:
                continue
            seen_member.add(key)
            if key not in contributors:
                contributors[key] = []
                order.append(key)
            contributors[key].append(route)
    union = tuple(contributors[key][0] for key in order)
    viable = tuple(
        dataclasses.replace(contributors[key][0], selected_by_default=True)
        for key in order
        if len(contributors[key]) >= 2
    )
    return viable, union


def _debug_planned_output_routes(
    *,
    focus: str,
    positional: str,
    reason: str,
    routes: Sequence[StemRoute],
) -> None:
    """Opt-in trace when resolving planned export routes (``uvr-settings``)."""
    try:
        from core.debug_log import debug

        labels = ",".join(route.label for route in routes) or "(none)"
        debug(
            "settings",
            f"planned outputs focus={focus!r} positional={positional!r} "
            f"reason={reason} routes=[{labels}] count={len(routes)}",
        )
    except Exception:
        pass


def planned_output_routes(
    settings: Settings,
    descriptors: Sequence[ModelDescriptor],
    *,
    command: str,
) -> tuple[StemRoute, ...]:
    """Canonical routes that this resolved job intends to write."""
    focus = str(settings.process.stem_focus or "")
    positional = positional_stem_focus(focus)
    reason = "unknown"
    selected: tuple[StemRoute, ...] = ()

    if command == "ensemble":
        routes, _union = _ensemble_output_routes(settings, descriptors)
        if positional:
            selected = tuple(routes)
            if not coerce_ensemble_pair(settings.ensemble.main_stem).is_multi_or_four():
                if positional == FOCUS_PRIMARY:
                    selected = selected[:1]
                    reason = "ensemble-positional-primary"
                elif positional == FOCUS_SECONDARY:
                    selected = selected[1:2]
                    reason = "ensemble-positional-secondary"
                else:
                    reason = "ensemble-positional"
            else:
                reason = "ensemble-positional-multi"
        else:
            selection = select_ensemble_stem_routes(routes, _union, focus)
            selected = tuple(
                selection.routes if selection.routes else routes
            )
            reason = (
                "ensemble-focus-matched"
                if selection.routes
                else "ensemble-focus-fallback-all"
            )
        _debug_planned_output_routes(
            focus=focus,
            positional=positional,
            reason=reason,
            routes=selected,
        )
        return selected

    routes = _fallback_descriptor_routes(descriptors[0]) if descriptors else ()
    if positional:
        if positional == FOCUS_PRIMARY:
            primary = descriptors[0].primary_stem if descriptors else None
            matched = tuple(
                route for route in routes
                if route.native is not None and route.native.matches(primary or "")
            )
            if matched:
                selected = matched
                reason = "positional-primary-native-match"
            else:
                selected = tuple(
                    route for route in routes if route.selected_by_default
                ) or tuple(routes)
                reason = (
                    f"positional-primary-fallback-defaults "
                    f"primary_stem={primary!r}"
                )
        else:
            secondary = descriptors[0].secondary_stem if descriptors else None
            matched = tuple(
                route for route in routes
                if (
                    route.native is not None and route.native.matches(secondary or "")
                ) or (route.native is None and route.label == secondary)
            )
            if matched:
                selected = matched
                reason = "positional-secondary-match"
            else:
                selected = tuple(
                    route for route in routes if route.selected_by_default
                ) or tuple(routes)
                reason = (
                    f"positional-secondary-fallback-defaults "
                    f"secondary_stem={secondary!r}"
                )
    else:
        selection = select_stem_routes(routes, focus)
        if selection.status is StemSelectionStatus.MATCHED and selection.routes:
            selected = tuple(selection.routes)
            reason = "focus-matched"
        elif focus:
            selected = tuple(
                route for route in routes if route.selected_by_default
            ) or tuple(routes)
            reason = "focus-unmatched-fallback-defaults"
        else:
            selected = tuple(
                selection.routes
                if selection.routes
                else tuple(route for route in routes if route.selected_by_default)
                or tuple(routes)
            )
            reason = "empty-focus-defaults"
        if (
            focus
            and not positional
            and settings.mdx.is_mdx_include_stem_complement
            and any(route.native is not None for route in selected)
        ):
            selected = tuple(dict.fromkeys((
                *selected,
                *(route for route in routes if route.native is None and route.conditional),
            )))
            reason = f"{reason}+complement"

    _debug_planned_output_routes(
        focus=focus,
        positional=positional,
        reason=reason,
        routes=selected,
    )
    return selected


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


def _apply_model_native_values(
    settings: Settings, records: Sequence[ModelRecord], models: Sequence[Any],
    provenance: dict[str, str],
) -> None:
    """Materialize model-native values only for settings whose value is auto.

    Only ``mdx.compensate`` qualifies. There is deliberately no demucs.segment
    branch: ``ModelConfig.segment`` is the *setting* rendered into the legacy
    ``Default``/numeric label ``vendor.demucs.apply.demucs_segments`` branches
    on, not model metadata -- ``get_demucs_model_data`` sets no segment and no
    Demucs model_data carries one. Reading it back crashed every Demucs run at
    plan time, because whenever the setting was unset the value was the
    unparseable string ``Default``.
    """
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


def _mdx_yaml_config_names(record: ModelRecord) -> tuple[str, ...]:
    if record.family != "mdx":
        return ()
    if record.mdx is not None and record.mdx.kind == "classic_onnx":
        return ()
    names = tuple(
        name for name in record.artifacts.supporting_filenames
        if name.casefold().endswith((".yaml", ".yml"))
    )
    if names:
        return names
    if record.mdx is not None and record.mdx.kind != "classic_onnx":
        from .mdx_c_registry import yaml_for_checkpoint

        yaml_name = yaml_for_checkpoint(record.backend_name)
        if yaml_name:
            return (yaml_name,)
    return ()


def _is_repairable_mdx_config_dependency(record: ModelRecord) -> bool:
    """Whether planning may fetch one exact missing MDX-C YAML for this record."""
    names = _mdx_yaml_config_names(record)
    return (
        record.family == "mdx"
        and record.installed
        and not record.identity_complete
        and record.mdx is None
        and record.artifacts.primary_filename.casefold().endswith(".ckpt")
        and len(names) == 1
        and str(record.identity_error or "").startswith(
            "unknown MDX YAML architecture"
        )
    )


class JobResolver:
    def __init__(self, repo: Any):
        self.repo = repo
        self.identities = ModelIdentityService(repo)

    def _ensure_mdx_yaml_configs(
        self,
        dependencies: Mapping[str, ModelRecord],
        *,
        allow_network: bool,
    ) -> dict[str, ModelRecord]:
        from . import paths
        from .mdx_config_fetch import ensure_mdx_c_config

        refresh_needed = False
        for record in dependencies.values():
            for yaml_name in _mdx_yaml_config_names(record):
                dest = os.path.join(paths.MDX_C_CONFIG_PATH, yaml_name)
                if os.path.isfile(dest):
                    if _is_repairable_mdx_config_dependency(record):
                        refresh_needed = True
                    continue
                if not allow_network:
                    raise ValueError(
                        f"MDX configuration {yaml_name!r} is not available offline"
                    )
                if ensure_mdx_c_config(yaml_name, allow_network=True):
                    refresh_needed = True
                else:
                    raise ValueError(
                        f"MDX configuration {yaml_name!r} could not be downloaded"
                    )

        resolved = dict(dependencies)
        if refresh_needed:
            invalidate = getattr(self.repo, "invalidate_models", None)
            if callable(invalidate):
                invalidate()

            self.identities.invalidate()
            resolved = {
                path: self.identities.lookup(record.id)
                for path, record in dependencies.items()
            }

        for path, record in resolved.items():
            if not record.identity_complete:
                detail = record.identity_error or "identity metadata is incomplete"
                raise ValueError(
                    f"{path} references model {record.id!r}: {detail}"
                )
        return resolved

    def resolve(
        self,
        spec: JobSpec,
        level: ValidationLevel = ValidationLevel.MODEL,
        *,
        allow_network: bool = True,
    ) -> ResolvedJob:
        settings = copy.deepcopy(spec.settings)
        settings.process.export_path = os.path.abspath(spec.output)
        diagnostics: list[Diagnostic] = []
        configs_unavailable = False
        dependencies: dict[str, ModelRecord] = {}
        records: list[ModelRecord] = []
        models: list[Any] = []
        topology_models: list[Any] = []
        if not spec.inputs:
            diagnostics.append(Diagnostic("inputs.empty", "Select at least one input file"))
        for path in spec.inputs:
            if not os.path.isfile(path):
                diagnostics.append(Diagnostic("input.missing", f"Input not found: {path}", path=path))
        if not spec.output:
            diagnostics.append(Diagnostic("output.empty", "Choose an output folder"))
        try:
            needs_primary_probe = self._settings_need_secondary_topology(
                settings, spec.command
            )
            if needs_primary_probe:
                primary_dependencies = self._primary_dependency_map(
                    settings,
                    spec.command,
                    allow_repairable_mdx_config=True,
                )
                dependencies = dict(primary_dependencies)
            else:
                dependencies = self._dependency_map(
                    settings,
                    spec.command,
                    allow_repairable_mdx_config=True,
                )
                primary_dependencies = {
                    path: dependencies[path]
                    for path, _reference in _selected_family_paths(
                        settings, spec.command
                    )
                }
        except ValueError as exc:
            diagnostics.append(Diagnostic("model.identity", str(exc)))
        else:
            if dependencies:
                # An offline miss or a failed download is an actionable
                # configuration diagnostic, not an exception: every other
                # planning failure lands in ``diagnostics`` so
                # ``--dry-run --report json`` still returns a plan payload.
                # ``dependencies`` keeps its pre-fetch contents either way --
                # it is what ``model_dependencies`` and the identity digest are
                # built from, and emptying it would misreport the plan.
                try:
                    dependencies = self._ensure_mdx_yaml_configs(
                        dependencies, allow_network=allow_network
                    )
                except ValueError as exc:
                    diagnostics.append(Diagnostic("model.configuration", str(exc)))
                    configs_unavailable = True
                else:
                    primary_dependencies = {
                        path: dependencies[path]
                        for path, _reference in _selected_family_paths(
                            settings, spec.command
                        )
                    }
                    try:
                        self._validate_karaoke_dependencies(
                            settings, dependencies
                        )
                    except ValueError as exc:
                        diagnostics.append(
                            Diagnostic("model.identity", str(exc))
                        )
                        configs_unavailable = True
            records = self._primary_records(dependencies, spec.command)
            if records and not configs_unavailable and needs_primary_probe:
                try:
                    with access_policy(
                        allow_network=allow_network,
                        allow_metadata_writes=allow_network,
                    ):
                        primary_models = self._assemble(
                            settings,
                            spec.command,
                            records,
                            allow_network=allow_network,
                            model_dependencies={},
                        )
                    if len(primary_models) != len(records):
                        raise ValueError(
                            "one or more primary model configurations are unavailable"
                        )
                    if any(
                        not getattr(model, "model_status", False)
                        for model in primary_models
                    ):
                        raise ValueError(
                            "one or more primary model configurations are unavailable"
                        )
                    topology_models = list(primary_models)
                    primary_stems = {
                        path: str(
                            getattr(model, "primary_stem", "") or ""
                        )
                        for (path, _record), model in zip(
                            primary_dependencies.items(), primary_models
                        )
                    }
                except (OSError, ValueError) as exc:
                    diagnostics.append(Diagnostic("model.configuration", str(exc)))
                    configs_unavailable = True
                else:
                    try:
                        dependencies = self._dependency_map(
                            settings,
                            spec.command,
                            primary_dependencies=primary_dependencies,
                            primary_stems=primary_stems,
                            allow_repairable_mdx_config=True,
                        )
                    except ValueError as exc:
                        diagnostics.append(Diagnostic("model.identity", str(exc)))
                        configs_unavailable = True
                    else:
                        try:
                            dependencies = self._ensure_mdx_yaml_configs(
                                dependencies, allow_network=allow_network
                            )
                        except ValueError as exc:
                            diagnostics.append(
                                Diagnostic("model.configuration", str(exc))
                            )
                            configs_unavailable = True
                        else:
                            try:
                                self._validate_karaoke_dependencies(
                                    settings, dependencies
                                )
                            except ValueError as exc:
                                diagnostics.append(
                                    Diagnostic("model.identity", str(exc))
                                )
                                configs_unavailable = True
                            else:
                                records = self._primary_records(
                                    dependencies, spec.command
                                )
        # Assembling a model whose yaml is already known to be missing only
        # restates the diagnostic just recorded.
        verify_model = level is not ValidationLevel.CONFIG
        if records and verify_model and not configs_unavailable:
            try:
                with access_policy(
                    allow_network=allow_network,
                    allow_metadata_writes=allow_network,
                ):
                    models = self._assemble(
                        settings, spec.command, records, allow_network=allow_network,
                        model_dependencies=dependencies,
                    )
                if len(models) != len(records):
                    raise ValueError("one or more model configurations are unavailable")
                if any(not getattr(model, "model_status", False) for model in models):
                    raise ValueError("one or more model configurations are unavailable")
            except (OSError, ValueError) as exc:
                diagnostics.append(Diagnostic("model.configuration", str(exc)))
        descriptor_models = models or topology_models
        descriptors = tuple(
            _descriptor(record, model, verify_model)
            for record, model in zip(records, descriptor_models)
        ) if descriptor_models else tuple(
            ModelDescriptor(
                record.id,
                record.family,
                record.basename,
                record.display,
                record.backend_name,
                record.artifacts,
                record.demucs,
                record.mdx,
            )
            for record in records
        )
        provenance = dict(spec.provenance)
        if models:
            _apply_model_native_values(settings, records, models, provenance)
        diagnostics.extend(_stem_focus_diagnostics(
            settings,
            models,
            descriptors,
            provenance,
            command=spec.command,
        ))
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
            model_dependencies=dependencies,
            model_identity_digest=compute_model_identity_digest(dependencies),
        )

    def is_current(self, plan: ResolvedJob) -> bool:
        if plan.inventory_generation != int(getattr(self.repo, "inventory_generation", 0)):
            return False
        try:
            primary_dependencies = self._primary_dependency_map(
                plan.settings,
                plan.command,
            )
            dependencies = self._dependency_map(
                plan.settings,
                plan.command,
                primary_dependencies=primary_dependencies,
                primary_stems={
                    path: descriptor.primary_stem
                    for (path, _record), descriptor in zip(
                        primary_dependencies.items(), plan.models
                    )
                    if descriptor.primary_stem
                },
            )
            self._validate_karaoke_dependencies(plan.settings, dependencies)
        except ValueError:
            return False
        if compute_model_identity_digest(dependencies) != plan.model_identity_digest:
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
        primary_dependencies = self._primary_dependency_map(settings, spec.command)
        dependencies = self._dependency_map(
            settings,
            spec.command,
            primary_dependencies=primary_dependencies,
            primary_stems={
                path: str(getattr(model, "primary_stem", "") or "")
                for (path, _record), model in zip(
                    primary_dependencies.items(), models
                )
            },
        )
        self._validate_karaoke_dependencies(settings, dependencies)
        descriptors = tuple(
            _descriptor(record, model, level is not ValidationLevel.CONFIG)
            for record, model in zip(records, models)
        )
        provenance = dict(spec.provenance)
        _apply_model_native_values(settings, records, models, provenance)
        diagnostics = tuple(_stem_focus_diagnostics(
            settings,
            models,
            descriptors,
            provenance,
            command=spec.command,
        ))
        return ResolvedJob(
            spec.command,
            settings,
            self._plan_inputs(settings, spec, descriptors),
            descriptors,
            provenance,
            diagnostics,
            level,
            int(getattr(self.repo, "inventory_generation", 0)),
            settings_fingerprint(settings),
            DeviceRequest.from_settings(settings.process).id,
            settings.process.export_path,
            dict(spec.metadata),
            dependencies,
            compute_model_identity_digest(dependencies),
        )

    def _primary_dependency_map(
        self,
        settings: Settings,
        command: str,
        *,
        allow_repairable_mdx_config: bool = False,
    ) -> dict[str, ModelRecord]:
        primary_dependencies: dict[str, ModelRecord] = {}
        for path, reference in _selected_family_paths(settings, command):
            record = self.identities.lookup(reference)
            if path.startswith("ensemble.selected_models["):
                allowed = _MODEL_FAMILIES
            else:
                allowed = frozenset({path.partition(".")[0]})
            self._validate_dependency_family(
                path,
                record,
                allowed,
                allow_repairable_mdx_config=allow_repairable_mdx_config,
            )
            primary_dependencies[path] = record

        method_value = str(
            getattr(settings.process.method, "value", settings.process.method)
        )
        is_ensemble = command == "ensemble" or method_value == ENSEMBLE_MODE
        if is_ensemble and len(primary_dependencies) < 2:
            raise ValueError("an ensemble requires at least two models")

        return primary_dependencies

    def _dependency_map(
        self,
        settings: Settings,
        command: str,
        *,
        primary_dependencies: Mapping[str, ModelRecord] | None = None,
        primary_stems: Mapping[str, str] | None = None,
        allow_repairable_mdx_config: bool = False,
    ) -> dict[str, ModelRecord]:
        if primary_dependencies is None:
            primary_dependencies = self._primary_dependency_map(
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
            self._validate_dependency_family(
                path,
                record,
                allowed,
                allow_repairable_mdx_config=allow_repairable_mdx_config,
            )
            dependencies[path] = record
        return dependencies

    def _validate_karaoke_dependencies(
        self,
        settings: Settings,
        dependencies: Mapping[str, ModelRecord],
    ) -> None:
        record = dependencies.get("process.vocal_splitter")
        if record is None:
            return
        # The active MDX YAML recovery step has already run. Pool construction
        # may inspect unrelated installed models, but it must not fetch or
        # write metadata while deciding exact karaoke/BV membership.
        with access_policy(allow_network=False, allow_metadata_writes=False):
            karaoke_ids = {
                str(value) for value in self.repo.karaoke_model_list(settings)
            }
        if record.id not in karaoke_ids:
            raise ValueError(
                f"process.vocal_splitter references model {record.id!r}, which "
                "is not karaoke/BV eligible"
            )

    @staticmethod
    def _settings_need_secondary_topology(
        settings: Settings, command: str
    ) -> bool:
        selected_families = {
            reference.partition(":")[0]
            for _path, reference in _selected_family_paths(settings, command)
        }
        return any(
            family in selected_families
            and bool(getattr(getattr(settings, family), "is_secondary_model_activate"))
            for family in _MODEL_FAMILIES
        )

    @staticmethod
    def _validate_dependency_family(
        path: str,
        record: ModelRecord,
        allowed: frozenset[str],
        *,
        allow_repairable_mdx_config: bool = False,
    ) -> None:
        if record.family not in allowed:
            expected = ", ".join(sorted(allowed))
            raise ValueError(
                f"{path} references {record.id!r}, but requires family {expected}"
            )
        if not record.installed:
            raise ValueError(f"{path} references model {record.id!r}, which is not installed")
        if not record.identity_complete:
            if (
                allow_repairable_mdx_config
                and _is_repairable_mdx_config_dependency(record)
            ):
                return
            detail = record.identity_error or "identity metadata is incomplete"
            raise ValueError(f"{path} references model {record.id!r}: {detail}")

    @staticmethod
    def _primary_records(
        dependencies: Mapping[str, ModelRecord], command: str
    ) -> list[ModelRecord]:
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

    def _assemble(
        self,
        settings: Settings,
        command: str,
        records: Sequence[ModelRecord],
        *,
        allow_network: bool = True,
        model_dependencies: Mapping[str, ModelRecord] | None = None,
    ) -> list[Any]:
        from .mdx_config_fetch import mdx_c_network

        with mdx_c_network(allow_network):
            method_value = str(
                getattr(settings.process.method, "value", settings.process.method)
            )
            if command == "ensemble" or method_value == ENSEMBLE_MODE:
                settings.ensemble.selected_models = [record.id for record in records]
                return assemble_model(
                    settings, self.repo, arch_type=ENSEMBLE_MODE,
                    model_dependencies=model_dependencies,
                )
            record = records[0]
            setattr(getattr(settings, record.family), "model", record.id)
            return assemble_model(
                settings, self.repo, record.id, record.method,
                model_dependencies=model_dependencies,
            )

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
        stem_routes = planned_output_routes(settings, descriptors, command=spec.command)
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
                    route.conditional,
                    route.concept,
                )
                for route in stem_routes
                for stem in (
                    route.filename_tag if spec.command == "ensemble" else route.label,
                )
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
    "Diagnostic", "JobResolver", "JobSpec", "MODEL_SENTINELS", "ModelDescriptor", "PlannedInput",
    "PlannedOutput", "Provenance", "ResolvedJob", "ValidationLevel",
    "active_model_paths", "compute_model_identity_digest", "device_runtime_diagnostics",
    "format_effective_plan", "planned_output_stems", "planned_output_routes",
    "settings_fingerprint",
]
