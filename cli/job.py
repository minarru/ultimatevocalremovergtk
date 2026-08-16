"""Shared job specification and effective-plan resolution."""

from __future__ import annotations

import argparse
import os
from dataclasses import dataclass, field
from typing import Any, Optional

from core.model_data import ModelRepository
from core.settings import Settings
from core.settings.job_resolution import (
    SettingsLayer,
    SettingsResolver,
    apply_stem_selection,
    resolve_splitter_identity,
)

from core.input_discovery import discover_inputs
from core.model_identity import ModelIdentityService, ModelRecord, canonical_member_tag, resolve_model_id
from core.offline import catalogue_offline
from .process_flags import collect_overrides
from .profiles import (
    IDENTITY_SETTING_PATHS,
    LoadedProfile,
    MODEL_REFERENCE_SETTING_PATHS,
    apply_profile_values,
    load_profile,
)


def _resolved_settings(
    base: Settings,
    *,
    output: str,
    method: str,
    model: ModelRecord | None = None,
    stems: str | None = None,
    long_chunk_seconds: float | None = None,
    long_chunk_overlap: float | None = None,
    base_provenance: dict[str, str] | None = None,
    model_source: str | None = None,
) -> tuple[Settings, dict[str, str]]:
    settings, sources = SettingsResolver().resolve(
        base, export_path=output, method=method,
        base_provenance=base_provenance,
    )
    if model is not None:
        getattr(settings, model.family).model = model.id
        sources[f"{model.family}.model"] = model_source or "derived"
    if stems is not None:
        apply_stem_selection(settings, stems)
        for path in (
            "process.primary_stem_only", "process.secondary_stem_only",
            "mdx.stems", "mdx.stems_selected", "demucs.stems",
        ):
            sources[path] = "cli"
    if long_chunk_seconds is not None:
        settings.process.long_file_chunk_seconds = float(long_chunk_seconds)
        sources["process.long_file_chunk_seconds"] = "cli"
    if long_chunk_overlap is not None:
        settings.process.long_file_chunk_overlap_seconds = float(long_chunk_overlap)
        sources["process.long_file_chunk_overlap_seconds"] = "cli"
    return settings, sources


@dataclass
class ResolvedJob:
    command: str
    settings: Settings
    profile: LoadedProfile
    inputs: list[str]
    output: str
    model: Optional[ModelRecord] = None
    members: list[ModelRecord] = field(default_factory=list)
    models: list[Any] = field(default_factory=list)
    plan: dict[str, Any] = field(default_factory=dict)
    identity_inherited: bool = False
    resolved: Any = None


def add_job_input_args(parser: argparse.ArgumentParser) -> None:
    group = parser.add_argument_group("Input")
    group.add_argument("inputs", nargs="+", help="Audio file(s) or directories")
    group.add_argument("--recursive", action="store_true", help="Recurse into input directories")
    group.add_argument(
        "--include",
        action="append",
        default=[],
        metavar="GLOB",
        help="Filename filter for directory inputs; repeatable",
    )
    group.add_argument(
        "--accept-any-input",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Permit decoder probing for files with unknown extensions",
    )


def add_job_output_args(parser: argparse.ArgumentParser) -> None:
    group = parser.add_argument_group("Output")
    group.add_argument("-o", "--output", required=True, help="Stem output directory")
    group.add_argument(
        "--on-exists",
        choices=("fail", "overwrite", "rename", "skip"),
        default="fail",
        help="Existing-output policy (default: fail)",
    )
    batch = group.add_mutually_exclusive_group()
    batch.add_argument("--continue-on-error", action="store_true", default=True)
    batch.add_argument("--fail-fast", action="store_true")
    manifest = group.add_mutually_exclusive_group()
    manifest.add_argument("--manifest", action="store_true", help="Write a manifest under output")
    manifest.add_argument("--manifest-out", metavar="PATH", help="Write a manifest to PATH")


def add_profile_args(parser: argparse.ArgumentParser) -> None:
    group = parser.add_argument_group("Profiles")
    group.add_argument(
        "--profile",
        default=None,
        help="defaults, gui, a named sparse profile, or a JSON path",
    )
    group.add_argument(
        "--accept-inherited",
        action="store_true",
        help="Allow a profile-supplied identity without prompting",
    )


def _device_override(value: Optional[str]) -> list[tuple[str, Any]]:
    from core.device import resolve_device_request

    return resolve_device_request(value)


def _profile_provenance(
    settings: Settings, profile: LoadedProfile
) -> dict[str, str]:
    if profile.source == "gui":
        return {
            f"{section}.{name}": "gui"
            for section, values in settings.to_json_dict().items()
            if isinstance(values, dict)
            for name in values
        }
    return {path: profile.source for path in profile.settings}


def _device_pairs(args: argparse.Namespace, profile: LoadedProfile) -> tuple[list[tuple[str, Any]], bool]:
    device_paths = {"process.use_gpu", "process.device", "process.use_directml"}
    if args.device is None and device_paths.intersection(profile.settings):
        return [], False
    return _device_override(args.device), args.device is not None


def _base_resolve(args: argparse.Namespace) -> tuple[Settings, LoadedProfile, list[str], str]:
    settings, profile = load_profile(args.profile)
    inputs = discover_inputs(
        args.inputs,
        recursive=args.recursive,
        includes=args.include,
        accept_any=args.accept_any_input,
    )
    output = os.path.abspath(args.output)
    return settings, profile, inputs, output


def _validate_job_overrides(overrides: list[tuple[str, Any]]) -> None:
    prohibited = [path for path, _value in overrides if path in IDENTITY_SETTING_PATHS]
    if prohibited:
        raise ValueError(
            f"{prohibited[0]} is controlled by job identity; use its named CLI argument"
        )


def _canonicalize_model_references(
    settings: Settings, repo: ModelRepository
) -> dict[str, dict[str, str]]:
    from core.settings.access import get_path, set_path
    from core.settings.coerce import enum_value
    from core.types import ProcessMethod

    identities: dict[str, dict[str, str]] = {}
    sentinels = {"", "none", "no model selected", "choose model"}
    family_by_path = {
        "vr.model": "vr", "mdx.model": "mdx", "demucs.model": "demucs",
        "audio_tools.apollo_model": "apollo",
    }
    allowed_by_path = {
        "process.vocal_splitter": ("vr", "mdx"),
        "demucs.pre_proc_model": ("vr", "mdx"),
    }
    method_value = str(enum_value(settings.process.method) or "")
    active_primary_family = {
        ProcessMethod.VR.value: "vr",
        ProcessMethod.VR_ARCH.value: "vr",
        ProcessMethod.MDX.value: "mdx",
        ProcessMethod.DEMUCS.value: "demucs",
        ProcessMethod.APOLLO.value: "apollo",
    }.get(method_value)
    service = ModelIdentityService(repo)
    for path in MODEL_REFERENCE_SETTING_PATHS | frozenset(family_by_path):
        section_name = path.split(".", 1)[0]
        active = True
        if path in family_by_path:
            # Only the job's own family primary is load-bearing; stale GUI
            # primaries in unused families must not abort --profile gui.
            active = family_by_path[path] == active_primary_family
        elif path == "process.vocal_splitter":
            active = settings.process.vocal_splitter_enabled
        elif path == "demucs.pre_proc_model":
            active = settings.demucs.is_pre_proc_model_activate
        elif "secondary_model" in path:
            active = bool(
                getattr(getattr(settings, section_name), "is_secondary_model_activate")
            )
        raw = str(get_path(settings, path, "") or "").strip()
        if raw.casefold() in sentinels:
            continue
        try:
            if path in family_by_path:
                record = service.resolve(raw, family=family_by_path[path], fuzzy=False)
            elif path in allowed_by_path:
                record = service.resolve(
                    raw, allowed_families=allowed_by_path[path], fuzzy=False
                )
            elif "secondary_model" in path:
                record = service.resolve(
                    raw, allowed_families=("vr", "mdx", "demucs"), fuzzy=False
                )
            else:
                record = service.resolve(raw, fuzzy=False)
        except ValueError:
            if active:
                raise
            continue
        set_path(settings, path, canonical_member_tag(record))
        if active:
            identities[path] = record.to_dict()
    return identities


def resolve_separate_job(
    args: argparse.Namespace, *, validation_level: Any = None
) -> ResolvedJob:
    base, profile, inputs, output = _base_resolve(args)
    repo = ModelRepository()
    inherited = not bool(args.model) and bool(profile.model)
    model_query = args.model or profile.model
    if not model_query:
        raise ValueError("separate requires --model or a profile containing a model")
    with catalogue_offline(True):
        record = resolve_model_id(model_query, repo)
        settings, sources = _resolved_settings(
            base, output=output, method=record.family, model=record,
            stems=args.stems, long_chunk_seconds=args.long_chunk_seconds,
            long_chunk_overlap=args.long_chunk_overlap,
            base_provenance=_profile_provenance(base, profile),
            model_source="cli" if args.model else profile.source,
        )
        resolved_splitter = None
        split_record = None
        if getattr(args, "vocal_split", None):
            splitter_id = resolve_splitter_identity(args.vocal_split, settings, repo)
            split_record = resolve_model_id(splitter_id, repo)
            resolved_splitter = canonical_member_tag(split_record)
        overrides = collect_overrides(args, resolved_vocal_splitter=resolved_splitter)
        _validate_job_overrides(overrides)
        device_pairs, device_explicit = _device_pairs(args, profile)
        layers = [SettingsLayer("cli" if device_explicit else "derived", tuple(device_pairs))]
        layers.append(SettingsLayer("cli", tuple(overrides)))
        settings, sources = SettingsResolver().resolve(
            settings,
            layers=layers,
            base_provenance=sources,
        )
        model_chains = _canonicalize_model_references(settings, repo)
    from core.job_plan import JobResolver, JobSpec, ValidationLevel

    level = validation_level or ValidationLevel.MODEL

    if not args.model:
        profile.model = record.id
    sources["runtime.backend"] = "derived"
    effective = JobResolver(repo).resolve(
        JobSpec(
            "separate", settings, tuple(inputs), output,
            sources,
            {
                "profile": profile.to_dict(),
                "collision_policy": args.on_exists,
                "identity_source": "cli" if args.model else profile.source,
                "model_chains": model_chains,
                "vocal_splitter": split_record.to_dict() if split_record else None,
            },
        ),
        level,
    )
    errors = [item.message for item in effective.diagnostics if item.severity == "error"]
    if errors:
        raise ValueError(errors[0])
    return ResolvedJob(
        command="separate",
        settings=settings,
        profile=profile,
        inputs=inputs,
        output=output,
        model=record,
        models=[],
        plan=effective.to_dict(),
        identity_inherited=inherited,
        resolved=effective,
    )


def resolve_ensemble_job(
    args: argparse.Namespace, *, validation_level: Any = None
) -> ResolvedJob:
    from bundled.constants import ENSEMBLE_ALGORITHMS
    from core.ensemble_algorithms import format_ensemble_type
    from core.ensemble_service import EnsembleService
    from core.stems import EnsemblePair

    base, profile, inputs, output = _base_resolve(args)
    repo = ModelRepository()
    explicit_identity = bool(args.ensemble or args.models)
    member_tokens = list(args.models or []) if explicit_identity else list(profile.members)
    preset = args.ensemble if explicit_identity else profile.ensemble
    inherited = not bool(args.ensemble or args.models) and bool(preset or member_tokens)
    if not preset and not member_tokens:
        raise ValueError("ensemble requires --ensemble or at least two --model values")
    if (
        member_tokens
        and not preset
        and not args.main_stem
        and "ensemble.main_stem" not in profile.settings
    ):
        raise ValueError("an ad-hoc ensemble requires --main-stem")
    settings, sources = _resolved_settings(
        base, output=output, method="ensemble", stems=args.stems,
        long_chunk_seconds=args.long_chunk_seconds,
        long_chunk_overlap=args.long_chunk_overlap,
        base_provenance=_profile_provenance(base, profile),
    )
    records: list[ModelRecord] = []
    preset_paths: set[str] = set()
    with catalogue_offline(True):
        if preset:
            EnsembleService(repo).apply(settings, preset)
            preset_paths.update({
                "ensemble.chosen_ensemble", "ensemble.main_stem",
                "ensemble.type", "ensemble.selected_models",
                "ensemble.wav_ensemble", "ensemble.save_all_outputs",
            })
            sources.update({path: "preset" for path in preset_paths})
            # Presets sit below explicit profile settings in the precedence
            # chain, so restore the sparse profile layer after preset loading.
            apply_profile_values(settings, profile.settings)
            sources.update({path: profile.source for path in profile.settings})
        if member_tokens:
            records = [resolve_model_id(token, repo) for token in member_tokens]
            settings.ensemble.selected_models = [canonical_member_tag(item) for item in records]
            sources["ensemble.selected_models"] = (
                "cli" if args.models else profile.source
            )
        if args.main_stem:
            settings.ensemble.main_stem = EnsemblePair(args.main_stem)
            sources["ensemble.main_stem"] = "cli"
        if args.algorithm:
            primary, sep, secondary = args.algorithm.partition("/")
            atoms = (primary.strip(), (secondary if sep else primary).strip())
            invalid = [atom for atom in atoms if atom not in ENSEMBLE_ALGORITHMS]
            if invalid:
                raise ValueError(
                    f"unknown ensemble algorithm {invalid[0]!r}; expected one of: "
                    + ", ".join(ENSEMBLE_ALGORITHMS)
                )
            settings.ensemble.type = format_ensemble_type(
                *atoms
            )
            sources["ensemble.type"] = "cli"
        if args.wav_ensemble is not None:
            settings.ensemble.wav_ensemble = bool(args.wav_ensemble)
            sources["ensemble.wav_ensemble"] = "cli"
        if args.save_all_outputs is not None:
            settings.ensemble.save_all_outputs = bool(args.save_all_outputs)
            sources["ensemble.save_all_outputs"] = "cli"
        overrides = collect_overrides(args)
        _validate_job_overrides(overrides)
        device_pairs, device_explicit = _device_pairs(args, profile)
        layers = [SettingsLayer("cli" if device_explicit else "derived", tuple(device_pairs))]
        layers.append(SettingsLayer("cli", tuple(overrides)))
        settings, sources = SettingsResolver().resolve(
            settings,
            layers=layers,
            base_provenance=sources,
        )
        model_chains = _canonicalize_model_references(settings, repo)
    if not records:
        # Resolve preset tags back to canonical records for reports/manifests.
        with catalogue_offline(True):
            for tag in settings.ensemble.selected_models:
                arch, _sep, display = str(tag).partition(": ")
                family = {
                    "VR Arc": "vr",
                    "MDX-Net": "mdx",
                    "Demucs": "demucs",
                }.get(arch)
                records.append(resolve_model_id(f"{family}:{display}" if family else display, repo))
    if len(records) < 2:
        raise ValueError("an ensemble needs at least two members")
    if not explicit_identity and profile.members:
        profile.members = [record.id for record in records]
    sources["runtime.backend"] = "derived"
    from core.job_plan import JobResolver, JobSpec, ValidationLevel

    level = validation_level or ValidationLevel.MODEL

    effective = JobResolver(repo).resolve(
        JobSpec(
            "ensemble", settings, tuple(inputs), output,
            sources,
            {
                "profile": profile.to_dict(),
                "collision_policy": args.on_exists,
                "identity_source": "cli" if explicit_identity else profile.source,
                "preset": preset,
                "model_chains": model_chains,
            },
        ),
        level,
    )
    errors = [item.message for item in effective.diagnostics if item.severity == "error"]
    if errors:
        raise ValueError(errors[0])
    return ResolvedJob(
        command="ensemble",
        settings=settings,
        profile=profile,
        inputs=inputs,
        output=output,
        members=records,
        models=[],
        plan=effective.to_dict(),
        identity_inherited=inherited,
        resolved=effective,
    )


def format_effective_plan(plan: dict[str, Any]) -> str:
    lines = ["Effective plan"]
    models = plan.get("models") or []
    if len(models) == 1:
        model = models[0]
        lines.append(f"  model: {model.get('display')} [{model.get('id')}]")
        if model.get("checkpoint"):
            lines.append(
                f"  checkpoint: {model['checkpoint']} ({model.get('checkpoint_hash') or 'unverified'})"
            )
    elif models:
        lines.append("  models: " + ", ".join(str(item.get("id")) for item in models))
    metadata = plan.get("metadata") or {}
    if metadata.get("preset"):
        lines.append(f"  ensemble: {metadata['preset']}")
    lines.append(f"  output: {plan.get('output')}")
    settings = plan.get("settings") or {}
    process = settings.get("process") or {}
    lines.append(f"  format: {process.get('save_format')}")
    stem_mode = "primary" if process.get("primary_stem_only") else "secondary" if process.get("secondary_stem_only") else "both"
    lines.append(f"  stems: {stem_mode}")
    lines.append(
        f"  normalize: {process.get('normalization')}  "
        f"mix-match: {process.get('match_mix_level')}"
    )
    lines.append(f"  device: {plan.get('device')}")
    lines.append(f"  autocast: {process.get('autocast')}")
    lines.append(
        f"  sample: {process.get('sample_mode')} ({process.get('sample_mode_duration')}s)  "
        f"long-file: {process.get('long_file_chunk_seconds')}s/"
        f"{process.get('long_file_chunk_overlap_seconds')}s"
    )
    if process.get("vocal_splitter_enabled"):
        lines.append(f"  vocal splitter: {process.get('vocal_splitter')}")
    lines.append(
        f"  naming: model-folders={process.get('create_model_folder')} "
        f"model-name={process.get('add_model_name')}"
    )
    lines.append(f"  collision: {metadata.get('collision_policy')}")
    lines.append(f"  inputs: {len(plan.get('inputs') or [])}")
    profile = metadata.get("profile") or {}
    lines.append(f"  profile: {profile.get('name')} ({profile.get('source')})")
    for diagnostic in plan.get("diagnostics") or []:
        lines.append(f"  {diagnostic.get('severity')}: {diagnostic.get('message')}")
    return "\n".join(lines)
