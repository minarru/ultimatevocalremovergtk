"""Audio inspection and Audio Tools command hierarchy."""

from __future__ import annotations

import argparse
import copy
import os
import shutil
import sys
import time
from typing import Any

from bundled.constants import (
    ALIGN_INPUTS, APOLLO_RESTORE, CHANGE_PITCH, COMBINE_INPUTS, MANUAL_ENSEMBLE,
    MATCH_INPUTS, TIME_STRETCH,
)
from core.audio_plan import AudioJobResolver, AudioJobSpec
from core.audio_probe import probe_audio
from core.audio_tools import AudioToolRunner
from core.input_discovery import InputDiscoveryPolicy, InputDiscoveryService
from core.job_plan import ValidationLevel
from core.model_repository import ModelRepository
from core.model_identity import ModelIdentityService
from core.settings.job_resolution import SettingsLayer, SettingsResolver

from .execution import BatchOutcome, PromotionSkipped, _promote, run_runner_cli
from .process_flags import add_process_args, collect_overrides
from .profiles import load_profile
from .reporting import (
    add_reporting_args, emit_document, emit_event, ensure_job_id, fail,
    finish_progress, make_progress_printer, report_mode,
)

TOOL_BY_COMMAND = {
    "ensemble": MANUAL_ENSEMBLE,
    "stretch": TIME_STRETCH,
    "pitch": CHANGE_PITCH,
    "align": ALIGN_INPUTS,
    "match": MATCH_INPUTS,
    "restore": APOLLO_RESTORE,
}


def _add_common(parser: argparse.ArgumentParser, *, paired: bool = False) -> None:
    if paired:
        parser.add_argument("--pair", nargs=2, action="append", required=True, metavar=("A", "B"))
    else:
        parser.add_argument("inputs", nargs="+", help="Audio files or directories")
        parser.add_argument("--recursive", action="store_true")
        parser.add_argument("--include", action="append", default=[])
        parser.add_argument("--accept-any-input", action="store_true")
    parser.add_argument("-o", "--output", required=True)
    parser.add_argument("--profile")
    parser.add_argument("--accept-inherited", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--on-exists", choices=("fail", "overwrite", "rename", "skip"), default="fail")
    parser.add_argument("--fail-fast", action="store_true")
    manifest = parser.add_mutually_exclusive_group()
    manifest.add_argument("--manifest", action="store_true")
    manifest.add_argument("--manifest-out")
    add_process_args(parser)
    add_reporting_args(parser)


def _add_audio_commands(
    children: argparse._SubParsersAction, *, validating: bool = False
) -> None:
    command = cmd_audio_validate if validating else cmd_audio
    ensemble = children.add_parser("ensemble", help="Combine two or more audio files")
    _add_common(ensemble)
    ensemble.add_argument("--algorithm")
    ensemble.add_argument("--name")
    ensemble.add_argument("--waveform", action=argparse.BooleanOptionalAction, default=None)
    ensemble.set_defaults(func=command)

    stretch = children.add_parser("stretch", help="Change playback rate")
    _add_common(stretch)
    stretch.add_argument("--rate", type=float, required=True)
    stretch.set_defaults(func=command)

    pitch = children.add_parser("pitch", help="Shift pitch in semitones")
    _add_common(pitch)
    pitch.add_argument("--semitones", type=float, required=True)
    pitch.add_argument("--time-correction", action=argparse.BooleanOptionalAction, default=None)
    pitch.set_defaults(func=command)

    align = children.add_parser("align", help="Align pairs of audio files")
    _add_common(align, paired=True)
    align.add_argument("--time-window")
    align.add_argument("--intro-analysis")
    align.add_argument("--db-analysis")
    align.add_argument("--phase-option")
    align.add_argument("--phase-shifts")
    align.add_argument("--save-aligned", action=argparse.BooleanOptionalAction, default=None)
    align.add_argument("--match-silence", action=argparse.BooleanOptionalAction, default=None)
    align.add_argument("--spectral-match", action=argparse.BooleanOptionalAction, default=None)
    align.set_defaults(func=command)

    match = children.add_parser("match", help="Master targets against references")
    _add_common(match, paired=True)
    match.set_defaults(func=command)

    restore = children.add_parser("restore", help="Restore audio with Apollo")
    _add_common(restore)
    restore.add_argument("--model")
    restore.add_argument("--overlap", type=int)
    restore.add_argument("--chunk-size", type=int)
    restore.set_defaults(func=command)
    if validating:
        for parser in (ensemble, stretch, pitch, align, match, restore):
            parser.add_argument(
                "--level", choices=tuple(level.value for level in ValidationLevel),
                default="model",
            )


def add_audio_parser(sub: argparse._SubParsersAction) -> None:
    root = sub.add_parser("audio", help="Inspect or transform audio")
    children = root.add_subparsers(dest="audio_command", required=True)
    inspect = children.add_parser("inspect", help="Probe audio metadata")
    inspect.add_argument("inputs", nargs="+")
    inspect.add_argument("--recursive", action="store_true")
    inspect.add_argument("--include", action="append", default=[])
    inspect.add_argument("--accept-any-input", action="store_true")
    add_reporting_args(inspect)
    inspect.set_defaults(func=cmd_audio_inspect)
    _add_audio_commands(children)


def add_audio_validation_parser(sub: argparse._SubParsersAction) -> None:
    root = sub.add_parser("audio", help="Validate an Audio Tools job")
    children = root.add_subparsers(dest="audio_command", required=True)
    _add_audio_commands(children, validating=True)


def cmd_audio_inspect(args: argparse.Namespace) -> int:
    try:
        paths = InputDiscoveryService().discover(
            args.inputs,
            InputDiscoveryPolicy(
                recursive=args.recursive, includes=tuple(args.include),
                accept_any=args.accept_any_input,
            ),
        ).paths
    except ValueError as exc:
        return fail(args, str(exc), exit_code=2, exc=exc)
    rows = [{"path": path, **vars(probe_audio(path))} for path in paths]
    ok = all(row["readable"] for row in rows)
    if report_mode(args) == "human":
        for row in rows:
            print(
                f"{row['path']}\t{row['format'] or '?'}\t{row['sample_rate'] or '?'} Hz\t"
                f"{row['channels'] or '?'} ch\t{row['duration_seconds'] or 0:.3f}s\t"
                f"{'ok' if row['readable'] else row['error']}"
            )
    else:
        emit_document(args, {"ok": ok, "status": "success" if ok else "failed", "items": rows})
    return 0 if ok else 1


def _resolve_audio(args: argparse.Namespace, level: ValidationLevel = ValidationLevel.MODEL):
    base, profile = load_profile(args.profile)
    overrides = collect_overrides(args)
    named: list[tuple[str, Any]] = []
    device_paths = {"process.use_gpu", "process.device", "process.use_directml"}
    if args.device is not None or not device_paths.intersection(profile.settings):
        from core.device import resolve_device_request

        named.extend(resolve_device_request(args.device))
    command = args.audio_command
    if command == "ensemble":
        if args.algorithm:
            named.append(("audio_tools.choose_algorithm", args.algorithm))
        if args.waveform is not None:
            named.append(("ensemble.wav_ensemble", bool(args.waveform)))
    elif command == "stretch":
        named.append(("audio_tools.time_stretch_rate", args.rate))
    elif command == "pitch":
        named.append(("audio_tools.pitch_rate", args.semitones))
        if args.time_correction is not None:
            named.append(("audio_tools.is_time_correction", bool(args.time_correction)))
    elif command == "align":
        for dest, path in (
            ("time_window", "audio_tools.time_window"),
            ("intro_analysis", "audio_tools.intro_analysis"),
            ("db_analysis", "audio_tools.db_analysis"),
            ("phase_option", "mdx.phase_option"),
            ("phase_shifts", "mdx.phase_shifts"),
            ("save_aligned", "mdx.is_save_align"),
            ("match_silence", "mdx.is_match_silence"),
            ("spectral_match", "mdx.is_spec_match"),
        ):
            value = getattr(args, dest, None)
            if value is not None:
                named.append((path, value))
    elif command == "restore":
        if args.overlap is not None:
            named.append(("audio_tools.apollo_overlap", args.overlap))
        if args.chunk_size is not None:
            named.append(("audio_tools.apollo_chunk_size", args.chunk_size))
    settings, sources = SettingsResolver().resolve(
        base,
        export_path=os.path.abspath(args.output),
        layers=(SettingsLayer("cli", tuple([*named, *overrides])),),
        base_provenance=(
            {
                f"{section}.{name}": "gui"
                for section, values in base.to_json_dict().items()
                if isinstance(values, dict)
                for name in values
            }
            if profile.source == "gui"
            else {path: profile.source for path in profile.settings}
        ),
    )
    repo = ModelRepository()
    inherited = False
    if command == "restore":
        profile_model = (
            base.audio_tools.apollo_model if profile.source == "gui" else profile.model
        )
        if str(profile_model or "").casefold() in {"", "choose model", "no model selected"}:
            profile_model = None
        reference = args.model or profile_model
        inherited = not bool(args.model) and bool(profile_model)
        if not reference:
            raise ValueError("audio restore requires --model or a profile model")
        record = ModelIdentityService(repo).resolve(reference, family="apollo")
        if record.family != "apollo":
            raise ValueError("audio restore requires an apollo: model")
        settings.audio_tools.apollo_model = record.id
        sources["audio_tools.apollo_model"] = "cli" if args.model else profile.source
    if command in {"align", "match"}:
        pairs = tuple((os.path.abspath(a), os.path.abspath(b)) for a, b in args.pair)
        inputs: tuple[str, ...] = ()
    else:
        inputs = InputDiscoveryService().discover(
            args.inputs,
            InputDiscoveryPolicy(
                recursive=args.recursive, includes=tuple(args.include),
                accept_any=args.accept_any_input,
            ),
        ).paths
        pairs = ()
    spec = AudioJobSpec(
        TOOL_BY_COMMAND[command], settings, os.path.abspath(args.output),
        inputs, pairs, getattr(args, "name", None), sources,
    )
    return AudioJobResolver(repo).resolve(spec, level), inherited


def _confirm_audio(args: argparse.Namespace, plan: Any) -> int:
    print(_format_audio_plan(plan), file=sys.stderr)
    if report_mode(args) != "human" or not getattr(sys.stdin, "isatty", lambda: False)():
        return fail(args, "profile-supplied Apollo identity requires --accept-inherited", exit_code=2, extra={"plan": plan.to_dict()})
    sys.stderr.write("Use these settings? [y/N] ")
    sys.stderr.flush()
    return 0 if sys.stdin.readline().strip().casefold() in {"y", "yes"} else fail(args, "aborted; no files processed", exit_code=2)


def _format_audio_plan(plan: Any) -> str:
    lines = [f"Effective audio plan\n  tool: {plan.tool}", f"  output: {plan.output}", f"  units: {len(plan.units)}", f"  device: {plan.device}"]
    if plan.model:
        lines.append(f"  model: {plan.model.display} [{plan.model.id}]")
    for unit in plan.units[:5]:
        lines.append(f"  {', '.join(unit.inputs)} -> {', '.join(unit.outputs)}")
    return "\n".join(lines)


def _run_audio(args: argparse.Namespace, plan: Any) -> BatchOutcome:
    started = time.perf_counter()
    collisions = {
        index for index, unit in enumerate(plan.units)
        if any(os.path.exists(path) for path in unit.outputs)
    }
    if collisions and args.on_exists == "fail":
        raise ValueError(f"planned output already exists: {plan.units[min(collisions)].outputs[0]}")
    os.makedirs(plan.output, exist_ok=True)
    temp_root = os.path.join(plan.output, ".uvr-tmp", ensure_job_id(args))
    os.makedirs(temp_root, exist_ok=True)
    outcomes: list[dict[str, Any]] = []
    interrupted = False
    try:
        for index, unit in enumerate(plan.units):
            if index in collisions and args.on_exists == "skip":
                item = {"input": list(unit.inputs), "status": "skipped", "outputs": [], "elapsed_s": 0.0}
                outcomes.append(item)
                emit_event(args, "input_finished", **item)
                continue
            unit_started = time.perf_counter()
            stage = os.path.join(temp_root, str(index + 1))
            os.makedirs(stage, exist_ok=True)
            settings = copy.deepcopy(plan.settings)
            settings.process.export_path = stage
            runner = AudioToolRunner(settings)
            singles = list(unit.inputs) if plan.tool not in {ALIGN_INPUTS, MATCH_INPUTS} else []
            pairs = [tuple(unit.inputs)] if plan.tool in {ALIGN_INPUTS, MATCH_INPUTS} else []
            apollo_params = None
            if plan.tool == APOLLO_RESTORE:
                from core.apollo import ApolloModelData

                data = ApolloModelData(settings.audio_tools.apollo_model, is_dry_check=True)
                apollo_params = {"extracted_params": data.extracted_params, "config": data.config}
            progress = make_progress_printer(args)
            manual_name = None
            if plan.tool == MANUAL_ENSEMBLE:
                manual_name = unit.name
                algorithm = str(getattr(
                    settings.audio_tools.choose_algorithm, "value",
                    settings.audio_tools.choose_algorithm,
                ))
                if algorithm == COMBINE_INPUTS:
                    manual_name = f"{manual_name} ({algorithm})"
            result = run_runner_cli(
                runner,
                lambda callbacks: runner.start(
                    plan.tool, singles, pairs, callbacks,
                    apollo_params=apollo_params,
                    output_name=manual_name,
                ),
                print_console=not args.quiet,
                on_progress=progress,
            )
            if progress:
                finish_progress(args)
            if result.interrupted or result.stopped:
                interrupted = True
                item = {"input": list(unit.inputs), "status": "failed", "error": "interrupted", "outputs": [], "elapsed_s": result.elapsed_s}
                outcomes.append(item)
                emit_event(args, "input_finished", **item)
                break
            if result.error:
                item = {"input": list(unit.inputs), "status": "failed", "error": f"{type(result.error).__name__}: {result.error}", "outputs": [], "elapsed_s": result.elapsed_s}
                outcomes.append(item)
                emit_event(args, "input_finished", **item)
                if args.fail_fast:
                    break
                continue
            try:
                # Audio units can intentionally emit more than one unrelated
                # basename (align emits an aligned and optional inverted file),
                # so collision renaming must operate per exact output.
                outputs = _promote(stage, plan.output, args.on_exists)
                if not outputs:
                    raise OSError("audio tool completed without output files")
            except PromotionSkipped:
                item = {
                    "input": list(unit.inputs), "status": "skipped",
                    "outputs": [], "elapsed_s": time.perf_counter() - unit_started,
                }
                outcomes.append(item)
                emit_event(args, "input_finished", **item)
                continue
            except OSError as exc:
                item = {"input": list(unit.inputs), "status": "failed", "error": str(exc), "outputs": [], "elapsed_s": time.perf_counter() - unit_started}
                outcomes.append(item)
                if args.fail_fast:
                    break
                continue
            item = {"input": list(unit.inputs), "status": "success", "outputs": outputs, "elapsed_s": time.perf_counter() - unit_started}
            outcomes.append(item)
            emit_event(args, "input_finished", **item)
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)
    failures = sum(row["status"] == "failed" for row in outcomes)
    successes = sum(row["status"] == "success" for row in outcomes)
    return BatchOutcome("partial" if failures and successes else "failed" if failures else "success", time.perf_counter() - started, outcomes, interrupted)


def _write_audio_manifest(args: argparse.Namespace, plan: Any, outcome: BatchOutcome) -> str | None:
    path = args.manifest_out
    if not path and args.manifest:
        path = os.path.join(plan.output, f"uvr-manifest-{ensure_job_id(args)}.json")
    if not path:
        return None
    from core.json_store import write_json_atomic

    write_json_atomic(path, {
        "schema_version": 2, "job_id": ensure_job_id(args), "command": "audio",
        "argv": list(getattr(args, "original_argv", [])),
        "plan": plan.to_dict(), "status": outcome.status, "inputs": outcome.inputs,
        "job_spec": {
            "tool": args.audio_command,
            "inputs": [path for unit in plan.units for path in unit.inputs]
            if args.audio_command not in {"ensemble", "align", "match"}
            else list(plan.units[0].inputs) if args.audio_command == "ensemble" else [],
            "pairs": [list(unit.inputs) for unit in plan.units]
            if args.audio_command in {"align", "match"} else [],
            "output": plan.output,
            "model": plan.model.id if plan.model else None,
            "name": getattr(args, "name", None),
            "collision_policy": args.on_exists,
        },
    })
    return path


def cmd_audio(args: argparse.Namespace) -> int:
    try:
        plan, inherited = _resolve_audio(args)
    except (OSError, TypeError, ValueError) as exc:
        return fail(args, str(exc), exit_code=2, exc=exc)
    if not plan.ok:
        return fail(args, plan.diagnostics[0].message, exit_code=2, extra={"plan": plan.to_dict()})
    if args.dry_run:
        if report_mode(args) == "human":
            print(_format_audio_plan(plan))
        else:
            emit_document(args, {"ok": True, "status": "validated", "dry_run": True, "plan": plan.to_dict(), "inputs": []})
        return 0
    if inherited and not args.accept_inherited:
        confirmed = _confirm_audio(args, plan)
        if confirmed:
            return confirmed
    elif args.verbose:
        print(_format_audio_plan(plan), file=sys.stderr)
    emit_event(args, "started", command="audio", plan=plan.to_dict())
    try:
        outcome = _run_audio(args, plan)
        manifest = _write_audio_manifest(args, plan, outcome)
    except (OSError, ValueError) as exc:
        return fail(args, str(exc), exit_code=2 if isinstance(exc, ValueError) else 1, exc=exc)
    payload = {
        "ok": outcome.exit_code == 0, "status": outcome.status,
        "command": "audio", "tool": plan.tool, "elapsed_s": outcome.elapsed_s,
        "export_path": plan.output, "plan": plan.to_dict(), "inputs": outcome.inputs,
        "manifest": manifest, "stopped": outcome.interrupted,
    }
    emit_document(args, payload)
    return outcome.exit_code


def cmd_audio_validate(args: argparse.Namespace) -> int:
    try:
        plan, _inherited = _resolve_audio(args, ValidationLevel(args.level))
    except (ImportError, OSError, TypeError, ValueError) as exc:
        return fail(args, str(exc), exit_code=2, exc=exc, kind="validation")
    if not plan.ok:
        return fail(
            args, plan.diagnostics[0].message, exit_code=2,
            extra={"plan": plan.to_dict()}, kind="validation",
        )
    if report_mode(args) == "human":
        print(_format_audio_plan(plan))
        print(f"validation={args.level} ok")
    else:
        emit_document(args, {
            "ok": True, "status": "validated", "level": args.level,
            "command": "audio", "plan": plan.to_dict(),
        })
    return 0


__all__ = [
    "add_audio_parser", "add_audio_validation_parser", "cmd_audio",
    "cmd_audio_inspect", "cmd_audio_validate",
]
