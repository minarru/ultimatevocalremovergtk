"""The ``separate`` command: one method, one or more input files."""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Optional

from core.headless_run import (
    build_settings,
    resolve_vocal_splitter,
    run_separation_sync,
    settings_summary,
)
from core.settings import Settings
from core.settings.access import apply_settings_overrides

from .process_flags import add_process_args, collect_overrides

_REQUIRED_RUNTIME_MODULES = ("kthread", "soundfile")


def check_runtime_deps() -> Optional[str]:
    """Return a short error message if core runtime packages are missing."""
    missing = []
    for name in _REQUIRED_RUNTIME_MODULES:
        try:
            __import__(name)
        except ImportError:
            missing.append(name)
    if not missing:
        return None
    return (
        f"missing Python packages: {', '.join(missing)}. "
        f"Use the project venv, e.g. "
        f"`./.venv/bin/python -m cli ...` "
        f"(current interpreter: {sys.executable})"
    )


def add_separate_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("inputs", nargs="+", help="Input audio file path(s)")
    parser.add_argument(
        "-o", "--output", required=True, help="Export directory for stem outputs"
    )
    parser.add_argument(
        "--method",
        choices=("mdx", "demucs", "vr"),
        default=None,
        help="Process method (default: value from settings / last GUI session)",
    )
    parser.add_argument(
        "--model",
        default=None,
        help=(
            "Model display name, on-disk basename, or weight filename/path "
            "(e.g. 'v4 | hdemucs_mmi' or hdemucs_mmi.yaml); default: settings"
        ),
    )
    parser.add_argument(
        "--settings",
        default=None,
        help="Path to settings.json (default: UVR data dir settings file)",
    )
    parser.add_argument(
        "--stems",
        default=None,
        help=(
            "Which stems to save for this run only: both|primary|secondary|"
            "vocals|instrumental|bass|drums|other "
            "(or vocals,instrumental). Default: settings / last GUI session"
        ),
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
    add_process_args(parser)


def cmd_separate(args: argparse.Namespace) -> int:
    dep_err = check_runtime_deps()
    if dep_err:
        print(f"error: {dep_err}", file=sys.stderr)
        return 2

    os.makedirs(args.output, exist_ok=True)
    try:
        settings: Settings = build_settings(
            settings_path=args.settings,
            export_path=os.path.abspath(args.output),
            method=args.method,
            model=args.model,
            stems=args.stems,
            stable_names=True,
            long_chunk_seconds=args.long_chunk_seconds,
            long_chunk_overlap=args.long_chunk_overlap,
        )
        resolved_splitter = None
        if args.vocal_split:
            from core.model_data import ModelRepository

            from .offline import catalogue_offline

            with catalogue_offline(True):
                resolved_splitter = resolve_vocal_splitter(
                    args.vocal_split, settings, ModelRepository()
                )
        apply_settings_overrides(
            settings,
            collect_overrides(
                args, resolved_vocal_splitter=resolved_splitter
            ),
        )
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if args.print_settings:
        print(json.dumps(settings_summary(settings), indent=2))

    missing = [p for p in args.inputs if not os.path.isfile(p)]
    if missing:
        print(f"error: input not found: {missing[0]}", file=sys.stderr)
        return 2

    result = run_separation_sync(settings, [os.path.abspath(p) for p in args.inputs])
    if result.error is not None:
        print(f"error: {type(result.error).__name__}: {result.error}", file=sys.stderr)
        return 1
    if result.stopped:
        print("error: separation stopped", file=sys.stderr)
        return 1
    print(f"elapsed_s={result.elapsed_s:.3f}")
    print(f"export_path={result.export_path}")
    return 0
