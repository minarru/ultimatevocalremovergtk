"""Layered job validation commands."""

from __future__ import annotations

import argparse
from .job import (
    resolve_ensemble_job,
    resolve_separate_job,
)
from .reporting import emit_document, fail, report_mode

from core.job_plan import (
    ValidationLevel,
    format_effective_plan as format_resolved_plan,
)

LEVELS = tuple(level.value for level in ValidationLevel)


def add_validation_level(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--level", choices=LEVELS, default="model",
        help="Validation boundary (default: model)",
    )


def cmd_validate(args: argparse.Namespace) -> int:
    try:
        resolver = resolve_separate_job if args.validation_command == "separate" else resolve_ensemble_job
        level = ValidationLevel(args.level)
        job = resolver(args, validation_level=level)
        effective = job.resolved
        errors = [
            item.message for item in effective.diagnostics
            if item.severity == "error"
        ]
        if errors:
            raise ValueError(errors[0])
    except (ImportError, OSError, ValueError) as exc:
        return fail(args, str(exc), exit_code=2, exc=exc, kind="validation")
    if report_mode(args) == "human":
        print(
            format_resolved_plan(effective)
        )
        print(f"validation={args.level} ok")
    else:
        emit_document(args, {
            "ok": True, "status": "validated", "level": args.level,
            "command": args.validation_command,
            "plan": effective.to_dict(),
        })
    return 0
