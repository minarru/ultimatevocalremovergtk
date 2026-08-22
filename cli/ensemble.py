"""Multi-model ensemble command."""

from __future__ import annotations

import argparse
import sys

from core.stems import EnsemblePair

from .execution import run_batch, write_manifest
from .job import (
    add_job_input_args,
    add_job_output_args,
    add_profile_args,
    format_effective_plan,
    resolve_ensemble_job,
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
from .separate import STEMS_HELP, check_runtime_deps, confirm_inherited

_MAIN_STEMS = tuple(pair.value for pair in EnsemblePair if pair is not EnsemblePair.CHOOSE)


def add_ensemble_args(parser: argparse.ArgumentParser) -> None:
    add_job_input_args(parser)
    model = parser.add_argument_group("Model")
    identity = model.add_mutually_exclusive_group()
    identity.add_argument("--ensemble", metavar="NAME", help="Saved or curated ensemble")
    identity.add_argument(
        "--model", action="append", default=None, dest="models", metavar="ID",
        help="Canonical or unique member model; repeat at least twice",
    )
    model.add_argument("--main-stem", choices=_MAIN_STEMS, default=None)
    model.add_argument("--algorithm", metavar="PRIMARY/SECONDARY", default=None)
    model.add_argument(
        "--wav-ensemble", action=argparse.BooleanOptionalAction, default=None,
        help="Enable or disable time-domain combination",
    )
    model.add_argument(
        "--save-all-outputs", action=argparse.BooleanOptionalAction, default=None,
        help="Keep or discard member outputs",
    )
    output = parser.add_argument_group("Stem selection")
    output.add_argument("--stems", default=None, help=STEMS_HELP)
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
    parser.add_argument("--dry-run", action="store_true")


def cmd_ensemble(args: argparse.Namespace) -> int:
    try:
        job = resolve_ensemble_job(args)
    except (OSError, ValueError) as exc:
        return fail(args, str(exc), exit_code=2, exc=exc)
    warn_validation(args, job.validation_warnings)
    emit_event(args, "planned", command="ensemble", plan=job.plan)
    if args.dry_run:
        if report_mode(args) == "human":
            print(format_effective_plan(job.plan))
        else:
            emit_document(args, {
                "ok": True, "status": "validated", "dry_run": True,
                "plan": job.plan, "inputs": [],
            })
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
    emit_event(args, "started", command="ensemble", plan=job.plan)
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
        "command": "ensemble",
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
