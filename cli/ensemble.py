"""The ``ensemble`` command: run several models and combine their stems."""

from __future__ import annotations

import argparse
import json
import os
import sys

from bundled.constants import CHOOSE_ENSEMBLE_OPTION, ENSEMBLE_ALGORITHMS
from core.ensemble_algorithms import format_ensemble_type, parse_ensemble_type
from core.headless_run import (
    apply_saved_ensemble,
    build_settings,
    resolve_ensemble_members,
    resolve_vocal_splitter,
    run_ensemble_sync,
    settings_summary,
)
from core.model_data import ModelRepository
from core.settings.access import apply_settings_overrides
from core.stems import EnsemblePair

from .offline import catalogue_offline
from .process_flags import add_process_args, collect_overrides
from .reporting import add_reporting_args, emit_json, fail, finish_progress, make_progress_printer
from .separate import check_runtime_deps

_MAIN_STEM_CHOICES = tuple(
    pair.value for pair in EnsemblePair if pair is not EnsemblePair.CHOOSE
)


def add_ensemble_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("inputs", nargs="+", help="Input audio file path(s)")
    parser.add_argument(
        "-o", "--output", required=True, help="Export directory for stem outputs"
    )
    parser.add_argument(
        "--ensemble",
        default=None,
        metavar="NAME",
        help="Load a saved ensemble preset by name",
    )
    parser.add_argument(
        "--model",
        action="append",
        default=None,
        dest="models",
        metavar="TAG",
        help=(
            "Ad-hoc member, repeatable. A full '{arch}: {display}' tag or a "
            "unique substring of one. Overrides a preset's member list."
        ),
    )
    parser.add_argument(
        "--models",
        default=None,
        dest="models_csv",
        metavar="TAG,TAG",
        help="Comma-separated members (convenience form of repeated --model)",
    )
    parser.add_argument(
        "--main-stem",
        choices=_MAIN_STEM_CHOICES,
        default=None,
        help="Ensemble main-stem pair id",
    )
    parser.add_argument(
        "--algorithm",
        default=None,
        metavar="PRIMARY/SECONDARY",
        help=(
            "Ensemble algorithm pair, e.g. 'Max Spec/Min Spec'. A single token "
            "is used for 4-stem and multi-stem runs. Atoms: "
            + ", ".join(ENSEMBLE_ALGORITHMS)
        ),
    )
    parser.add_argument(
        "--wav-ensemble",
        action="store_true",
        help="Combine in the time domain instead of spectrograms",
    )
    save_group = parser.add_mutually_exclusive_group()
    save_group.add_argument(
        "--save-all-outputs",
        action="store_true",
        help="Keep every member's stems alongside the combined result",
    )
    save_group.add_argument(
        "--no-save-all-outputs",
        action="store_true",
        help="Delete member stems after combining",
    )
    parser.add_argument(
        "--settings",
        default=None,
        help="Path to settings.json (default: UVR data dir settings file)",
    )
    parser.add_argument(
        "--stems",
        default=None,
        help="Which stems to save for this run only (see `separate --stems`)",
    )
    parser.add_argument(
        "--print-settings",
        action="store_true",
        help="Print resolved method/model/export knobs before running",
    )
    parser.add_argument(
        "--long-chunk-seconds",
        type=float,
        default=None,
        help="Whole-file chunk length in seconds (0/omit = off)",
    )
    parser.add_argument(
        "--long-chunk-overlap",
        type=float,
        default=None,
        help="Crossfade overlap between long-file chunks in seconds",
    )
    parser.add_argument(
        "--online",
        action="store_true",
        help=(
            "Do not force catalogue fetches off while resolving names. "
            "Does not clear UVR_DISABLE_POLITREES / UVR_DISABLE_MVSEPLESS if "
            "already set."
        ),
    )
    add_process_args(parser)
    add_reporting_args(parser)


def _member_tokens(args: argparse.Namespace) -> list[str]:
    tokens = list(args.models or [])
    if args.models_csv:
        tokens.extend(
            part.strip() for part in str(args.models_csv).split(",") if part.strip()
        )
    return tokens


def cmd_ensemble(args: argparse.Namespace) -> int:
    dep_err = check_runtime_deps()
    if dep_err:
        return fail(args, dep_err, exit_code=2)

    tokens = _member_tokens(args)
    if not args.ensemble and not tokens:
        return fail(
            args,
            "ensemble requires --ensemble NAME or --model/--models; "
            "do not inherit members from the last GUI session",
            exit_code=2,
        )

    os.makedirs(args.output, exist_ok=True)
    try:
        settings = build_settings(
            settings_path=args.settings,
            export_path=os.path.abspath(args.output),
            method="ensemble",
            stems=args.stems,
            stable_names=True,
            allow_ensemble=True,
            long_chunk_seconds=args.long_chunk_seconds,
            long_chunk_overlap=args.long_chunk_overlap,
        )
    except ValueError as exc:
        return fail(args, str(exc), exit_code=2, exc=exc)

    try:
        resolved_splitter = None
        repo = None
        with catalogue_offline(not args.online):
            repo = ModelRepository()
            if args.ensemble:
                apply_saved_ensemble(settings, args.ensemble, repo=repo)
            if tokens:
                settings.ensemble.selected_models = resolve_ensemble_members(
                    tokens, repo
                )
                # The members no longer exactly represent the named preset.
                settings.ensemble.chosen_ensemble = CHOOSE_ENSEMBLE_OPTION
            if args.vocal_split:
                resolved_splitter = resolve_vocal_splitter(
                    args.vocal_split, settings, repo
                )

        if args.main_stem is not None:
            settings.ensemble.main_stem = EnsemblePair(args.main_stem)
        if args.algorithm is not None:
            primary, secondary = parse_ensemble_type(args.algorithm)
            settings.ensemble.type = format_ensemble_type(primary, secondary)
    except ValueError as exc:
        return fail(args, str(exc), exit_code=2, exc=exc)

    if args.wav_ensemble:
        settings.ensemble.wav_ensemble = True
    if args.save_all_outputs:
        settings.ensemble.save_all_outputs = True
    elif args.no_save_all_outputs:
        settings.ensemble.save_all_outputs = False

    try:
        # Apply last: --set must beat process flags and ensemble-specific named
        # flags such as --main-stem, --algorithm, and --save-all-outputs.
        apply_settings_overrides(
            settings,
            collect_overrides(
                args, resolved_vocal_splitter=resolved_splitter
            ),
        )
    except ValueError as exc:
        return fail(args, str(exc), exit_code=2, exc=exc)

    if tokens and not args.ensemble and args.main_stem is None:
        return fail(
            args,
            "an ad-hoc ensemble requires --main-stem; "
            "do not inherit this semantic choice from the last GUI session",
            exit_code=2,
        )
    if settings.ensemble.main_stem == EnsemblePair.CHOOSE:
        return fail(args, "choose an ensemble --main-stem", exit_code=2)

    members = list(settings.ensemble.selected_models)
    if len(members) < 2:
        source = f"saved ensemble {args.ensemble!r}" if args.ensemble else "--model/--models"
        return fail(
            args,
            f"an ensemble needs at least 2 members, got {len(members)} from {source}",
            exit_code=2,
        )

    with catalogue_offline(not args.online):
        try:
            raw_eligible = repo.ensemble_model_list(
                settings, settings.ensemble.main_stem
            )
        except Exception:
            raw_eligible = None
    if isinstance(raw_eligible, (list, tuple, set)):
        eligible = set(raw_eligible)
        ineligible = [m for m in members if m not in eligible]
        if ineligible:
            preview = ", ".join(repr(m) for m in ineligible[:6])
            print(
                f"warning: {len(ineligible)} member(s) are outside the "
                f"{settings.ensemble.main_stem.value} pool and may not combine: "
                f"{preview}",
                file=sys.stderr,
            )

    missing = [p for p in args.inputs if not os.path.isfile(p)]
    if missing:
        return fail(args, f"input not found: {missing[0]}", exit_code=2)

    if args.print_settings and not args.json:
        print(json.dumps(settings_summary(settings), indent=2))

    on_progress = None if args.quiet else make_progress_printer()
    result = run_ensemble_sync(
        settings,
        [os.path.abspath(p) for p in args.inputs],
        print_console=not (args.quiet or args.json),
        on_progress=on_progress,
    )
    if on_progress is not None:
        finish_progress()

    if result.error is not None:
        return fail(
            args,
            f"{type(result.error).__name__}: {result.error}",
            exit_code=1,
            exc=result.error,
        )
    if result.stopped:
        return fail(
            args,
            "ensemble stopped",
            exit_code=130,
            extra={"stopped": True},
        )

    if args.json:
        payload = {
            "ok": True,
            "elapsed_s": result.elapsed_s,
            "export_path": result.export_path,
            "members": members,
        }
        if args.print_settings:
            payload["settings"] = settings_summary(settings)
        emit_json(payload)
    else:
        print(f"elapsed_s={result.elapsed_s:.3f}")
        print(f"export_path={result.export_path}")
        print(f"members={len(members)}")
    return 0
