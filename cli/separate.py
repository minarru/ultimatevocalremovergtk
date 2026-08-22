"""Single-model separation command."""

from __future__ import annotations

import argparse
import sys
from typing import Optional

from .execution import run_batch, write_manifest
from .job import (
    add_job_input_args,
    add_job_output_args,
    add_profile_args,
    format_effective_plan,
    resolve_separate_job,
)
from .process_flags import add_process_args
from .reporting import (
    add_reporting_args,
    emit_document,
    emit_event,
    fail,
    report_mode,
    warn_validation,
)

STEMS_HELP = (
    "Which stems to save. Concept names (vocals, instrumental, bass, drums, "
    "other) select that stem even when it is not the checkpoint primary. "
    "Positional names (primary, secondary, both) follow the model layout and "
    "write primary / secondary (or empty for both) into process.stem_focus."
)

_REQUIRED_RUNTIME_MODULES = ("kthread", "soundfile")


def check_runtime_deps() -> Optional[str]:
    missing = []
    for name in _REQUIRED_RUNTIME_MODULES:
        try:
            __import__(name)
        except ImportError:
            missing.append(name)
    if not missing:
        return None
    return f"missing Python packages: {', '.join(missing)}; run install_packages.sh"


def add_separate_args(parser: argparse.ArgumentParser) -> None:
    add_job_input_args(parser)
    model = parser.add_argument_group("Model")
    model.add_argument(
        "--model",
        default=None,
        help="Canonical model ID or a unique installed model name",
    )
    output = parser.add_argument_group("Stem selection")
    output.add_argument(
        "--stems",
        default=None,
        help=STEMS_HELP,
    )
    performance = parser.add_argument_group("Long files")
    performance.add_argument("--long-chunk-seconds", type=float, default=None)
    performance.add_argument("--long-chunk-overlap", type=float, default=None)
    add_job_output_args(parser)
    add_profile_args(parser)
    add_process_args(parser)
    add_reporting_args(parser)
    parser.add_argument(
        "--offline",
        action="store_true",
        help="Do not fetch missing MDX-C YAML configs during planning",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Resolve and verify the model without loading weights or processing",
    )


def confirm_inherited(args: argparse.Namespace, plan: dict) -> int:
    print(format_effective_plan(plan), file=sys.stderr)
    if report_mode(args) != "human":
        return fail(
            args,
            "profile-supplied identity requires --accept-inherited in machine mode",
            exit_code=2,
            extra={"plan": plan},
        )
    if not getattr(sys.stdin, "isatty", lambda: False)():
        return fail(
            args,
            "cannot confirm profile-supplied identity non-interactively; pass --accept-inherited",
            exit_code=2,
        )
    sys.stderr.write("Use these settings? [y/N] ")
    sys.stderr.flush()
    if sys.stdin.readline().strip().lower() not in {"y", "yes"}:
        return fail(args, "aborted; no files processed", exit_code=2)
    return 0


def cmd_separate(args: argparse.Namespace) -> int:
    try:
        job = resolve_separate_job(args)
    except (OSError, ValueError) as exc:
        return fail(args, str(exc), exit_code=2, exc=exc)

    warn_validation(args, job.validation_warnings)
    emit_event(args, "planned", command="separate", plan=job.plan)
    if args.dry_run:
        if report_mode(args) == "human":
            print(format_effective_plan(job.plan))
        else:
            emit_document(
                args,
                {"ok": True, "status": "validated", "dry_run": True, "plan": job.plan, "inputs": []},
            )
        return 0
    if job.identity_inherited and not args.accept_inherited:
        result = confirm_inherited(args, job.plan)
        if result:
            return result
    elif args.verbose or (job.identity_inherited and not args.quiet):
        print(format_effective_plan(job.plan), file=sys.stderr)

    dep_err = check_runtime_deps()
    if dep_err:
        return fail(args, dep_err, exit_code=2, kind="runtime")
    emit_event(args, "started", command="separate", plan=job.plan)
    outcome = run_batch(args, job)
    try:
        manifest = write_manifest(
            args, job, outcome,
            original_argv=getattr(args, "original_argv", sys.argv[1:]),
        )
    except OSError as exc:
        return fail(args, f"manifest write failed: {exc}", exit_code=1, exc=exc, kind="runtime")
    payload = {
        "ok": outcome.exit_code == 0,
        "status": outcome.status,
        "command": "separate",
        "elapsed_s": outcome.elapsed_s,
        "export_path": job.output,
        "plan": job.plan,
        "inputs": outcome.inputs,
        "stopped": outcome.interrupted,
    }
    if manifest:
        payload["manifest"] = manifest
    emit_document(args, payload)
    return outcome.exit_code
