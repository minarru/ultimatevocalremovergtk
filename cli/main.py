"""Argument-parser root for the public ``uvr`` command hierarchy."""

from __future__ import annotations

import argparse
import sys
import time
from types import SimpleNamespace
from typing import NoReturn, Optional, Sequence

from __version__ import VERSION

from .audio import add_audio_parser, add_audio_validation_parser
from .bench import add_bench_args, cmd_bench
from .discovery import (
    add_completion_parser,
    add_devices_parser,
    add_ensembles_parser,
    add_models_parser,
    add_settings_parser,
)
from .ensemble import add_ensemble_args, cmd_ensemble
from .replay import add_run_args, cmd_run
from .reporting import REPORT_CHOICES, ensure_job_id, fail
from .separate import add_separate_args, cmd_separate
from .update import add_update_parser
from .validate import add_validation_level, cmd_validate


class UsageError(ValueError):
    pass


class UvrArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        raise UsageError(message)


def cmd_gui(_args: argparse.Namespace) -> int:
    from core.debug_log import normalize_g_messages_debug_env

    normalize_g_messages_debug_env()
    from ui.application import main as gui_main

    return int(gui_main(argv=sys.argv[:1], configure_diagnostics=False))


def build_parser() -> argparse.ArgumentParser:
    parser = UvrArgumentParser(
        prog="uvr",
        description="Ultimate Vocal Remover command-line interface",
    )
    parser.add_argument("--version", action="version", version=VERSION)
    parser.add_argument("--report", choices=REPORT_CHOICES, dest="global_report")
    parser.add_argument("--quiet", action="store_true", dest="global_quiet")
    parser.add_argument("--verbose", action="store_true", dest="global_verbose")
    diagnostics = parser.add_mutually_exclusive_group()
    diagnostics.add_argument(
        "--debug",
        action="store_true",
        dest="global_debug",
        help="Record structured debug diagnostics",
    )
    diagnostics.add_argument(
        "--trace",
        action="store_true",
        dest="global_trace",
        help="Record high-frequency structured trace diagnostics",
    )
    parser.add_argument(
        "--debug-sensitive",
        action="store_true",
        dest="global_debug_sensitive",
        help="Include local and URL paths; credentials and queries stay redacted",
    )
    parser.add_argument(
        "--log-file",
        dest="global_log_file",
        metavar="PATH",
        help="Write diagnostics to PATH instead of the rotating cache log",
    )
    sub = parser.add_subparsers(dest="command", required=True, parser_class=UvrArgumentParser)

    gui = sub.add_parser("gui", help="Launch the GTK application")
    gui.set_defaults(func=cmd_gui, report="human", quiet=False, verbose=False)

    separate = sub.add_parser("separate", help="Separate audio with one model")
    add_separate_args(separate)
    separate.set_defaults(func=cmd_separate)

    ensemble = sub.add_parser("ensemble", help="Combine stems from multiple models")
    add_ensemble_args(ensemble)
    ensemble.set_defaults(func=cmd_ensemble)

    add_audio_parser(sub)

    run = sub.add_parser("run", help="Replay a job manifest")
    add_run_args(run)
    run.set_defaults(func=cmd_run)

    validate = sub.add_parser("validate", help="Validate a job without inference")
    validate_sub = validate.add_subparsers(dest="validation_command", required=True, parser_class=UvrArgumentParser)
    validate_separate = validate_sub.add_parser("separate")
    add_separate_args(validate_separate)
    add_validation_level(validate_separate)
    validate_separate.set_defaults(func=cmd_validate)
    validate_ensemble = validate_sub.add_parser("ensemble")
    add_ensemble_args(validate_ensemble)
    add_validation_level(validate_ensemble)
    validate_ensemble.set_defaults(func=cmd_validate)
    add_audio_validation_parser(validate_sub)

    bench = sub.add_parser("bench", help="Compare two separation configurations")
    add_bench_args(bench)
    bench.set_defaults(func=cmd_bench)

    add_models_parser(sub)
    add_ensembles_parser(sub)
    add_devices_parser(sub)
    add_settings_parser(sub)
    add_completion_parser(sub)
    add_update_parser(sub)
    return parser


def _report_hint(argv: Sequence[str]) -> str:
    for index, token in enumerate(argv):
        if token == "--report" and index + 1 < len(argv):
            value = argv[index + 1]
            return value if value in REPORT_CHOICES else "human"
        if token.startswith("--report="):
            value = token.partition("=")[2]
            return value if value in REPORT_CHOICES else "human"
    return "human"


def _configure_diagnostics(args: argparse.Namespace) -> None:
    from core.debug_log import configure_from_settings
    from core.settings import Settings

    if getattr(args, "trace", False):
        level = "trace"
    elif getattr(args, "debug", False):
        level = "debug"
    elif getattr(args, "global_trace", False):
        level = "trace"
    elif getattr(args, "global_debug", False):
        level = "debug"
    else:
        level = None
    include_sensitive = (
        True
        if getattr(args, "debug_sensitive", False)
        or getattr(args, "global_debug_sensitive", False)
        else None
    )
    log_file = getattr(args, "log_file", None) or getattr(
        args, "global_log_file", None
    )
    configure_from_settings(
        Settings.load(),
        level=level,
        include_sensitive_details=include_sensitive,
        log_file=log_file,
    )


def main(argv: Optional[Sequence[str]] = None) -> int:
    from core.debug_log import configure_bootstrap, install_runtime_hooks

    configure_bootstrap()
    install_runtime_hooks()
    values = list(argv) if argv is not None else sys.argv[1:]
    parser = build_parser()
    try:
        args = parser.parse_args(values)
    except UsageError as exc:
        hint = SimpleNamespace(report=_report_hint(values), quiet=False, verbose=False)
        return fail(hint, str(exc), exit_code=2, exc=exc, kind="usage")
    if args.global_report is not None:
        args.report = args.global_report
    if args.global_quiet:
        args.quiet = True
    if args.global_verbose:
        args.verbose = True
    _configure_diagnostics(args)
    args.original_argv = list(values)
    from core.debug_log import log_event, set_operation_id

    operation_id = ensure_job_id(args)
    started = time.perf_counter()
    set_operation_id(operation_id)
    try:
        log_event(
            "cli",
            "command_started",
            operation_id=operation_id,
            command=getattr(args, "command", ""),
            report=getattr(args, "report", "human"),
            quiet=bool(getattr(args, "quiet", False)),
        )
        try:
            status = int(args.func(args))
        except KeyboardInterrupt:
            return fail(
                args,
                "interrupted",
                exit_code=130,
                extra={"stopped": True},
                kind="runtime",
            )
        except (OSError, ValueError) as exc:
            return fail(args, str(exc), exit_code=2, exc=exc)
        log_event(
            "cli",
            "command_completed",
            operation_id=operation_id,
            command=getattr(args, "command", ""),
            status=status,
            elapsed_s=round(time.perf_counter() - started, 6),
        )
        return status
    finally:
        set_operation_id(None)
