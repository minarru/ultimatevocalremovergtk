"""argparse root for the headless CLI (``python -m cli``)."""

from __future__ import annotations

import argparse
from typing import Optional, Sequence

from .bench import cmd_bench_ab
from .ensemble import add_ensemble_args, cmd_ensemble
from .list_models import add_list_models_args, cmd_list_models
from .separate import add_separate_args, cmd_separate


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m cli",
        description="Headless Ultimate Vocal Remover GTK runner",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    separate = sub.add_parser("separate", help="Run a single-method separation job")
    add_separate_args(separate)
    separate.set_defaults(func=cmd_separate)

    ensemble = sub.add_parser(
        "ensemble", help="Run several models and combine their stems"
    )
    add_ensemble_args(ensemble)
    ensemble.set_defaults(func=cmd_ensemble)

    bench = sub.add_parser(
        "bench-ab",
        help="A/B two env configurations via subprocess separate runs + stem null metrics",
    )
    add_separate_args(bench)
    bench.add_argument(
        "--env",
        action="append",
        required=True,
        metavar="KEY=VALUE",
        help="Env assignment for leg A then B (exactly two required)",
    )
    bench.add_argument(
        "--json-out",
        default=None,
        metavar="PATH",
        help="Optional path to write the JSON summary (was --json before v5.7)",
    )
    bench.set_defaults(func=cmd_bench_ab)

    listing = sub.add_parser("list-models", help="List installed models and saved/curated ensembles")
    add_list_models_args(listing)
    listing.set_defaults(func=cmd_list_models)

    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    try:
        return int(args.func(args))
    except KeyboardInterrupt:
        from .reporting import fail

        return fail(
            args,
            "interrupted",
            exit_code=130,
            extra={"stopped": True},
        )
    except (ValueError, OSError) as exc:
        from .reporting import fail

        # User/config errors that escape a command (e.g. --set process.method
        # to Ensemble Mode on `separate`) must still own --json stdout.
        return fail(args, str(exc), exit_code=2, exc=exc)
