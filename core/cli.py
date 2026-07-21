"""Headless CLI for Ultimate Vocal Remover GTK.

Examples::

    python -m core.cli separate song.wav -o /tmp/out --method mdx --stems both
    python -m core.cli bench-ab song.wav -o /tmp/ab \\
        --env UVR_AUTOCAST=0 --env UVR_AUTOCAST=1 --method mdx --stems both
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from typing import Optional, Sequence

from .bench_metrics import (
    compare_stem_dirs,
    parse_env_assignment,
    sanitize_env_label,
)
from .headless_run import (
    build_settings,
    run_separation_sync,
    settings_summary,
)

_REQUIRED_RUNTIME_MODULES = ("kthread", "soundfile")


def _clear_dir_files(path: str) -> None:
    """Remove files directly under ``path`` (not recursive) so A/B legs stay clean."""
    if not os.path.isdir(path):
        return
    for name in os.listdir(path):
        file_path = os.path.join(path, name)
        if os.path.isfile(file_path) or os.path.islink(file_path):
            try:
                os.remove(file_path)
            except OSError:
                pass


def _check_runtime_deps() -> Optional[str]:
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
        f"`./.venv/bin/python -m core.cli ...` "
        f"(current interpreter: {sys.executable})"
    )


def _add_common_separate_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "inputs",
        nargs="+",
        help="Input audio file path(s)",
    )
    parser.add_argument(
        "-o",
        "--output",
        required=True,
        help="Export directory for stem outputs",
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
        help="Path to data.pkl (default: UVR data dir settings file)",
    )
    parser.add_argument(
        "--cpu",
        action="store_true",
        help="Force CPU (sets is_gpu_conversion=False)",
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


def _cmd_separate(args: argparse.Namespace) -> int:
    dep_err = _check_runtime_deps()
    if dep_err:
        print(f"error: {dep_err}", file=sys.stderr)
        return 2

    os.makedirs(args.output, exist_ok=True)
    try:
        settings = build_settings(
            settings_path=args.settings,
            export_path=os.path.abspath(args.output),
            method=args.method,
            model=args.model,
            stems=args.stems,
            use_gpu=False if args.cpu else None,
            stable_names=True,
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


def _build_separate_argv(
    *,
    inputs: Sequence[str],
    output: str,
    method: Optional[str],
    model: Optional[str],
    settings: Optional[str],
    cpu: bool,
    stems: Optional[str] = None,
) -> list[str]:
    argv = [
        sys.executable,
        "-m",
        "core.cli",
        "separate",
        *inputs,
        "-o",
        output,
    ]
    if method:
        argv.extend(["--method", method])
    if model:
        argv.extend(["--model", model])
    if settings:
        argv.extend(["--settings", settings])
    if stems:
        argv.extend(["--stems", stems])
    if cpu:
        argv.append("--cpu")
    return argv


def _cmd_bench_ab(args: argparse.Namespace) -> int:
    dep_err = _check_runtime_deps()
    if dep_err:
        print(f"error: {dep_err}", file=sys.stderr)
        return 2

    if len(args.env) != 2:
        print("error: bench-ab requires exactly two --env KEY=value flags", file=sys.stderr)
        return 2

    try:
        key_a, val_a = parse_env_assignment(args.env[0])
        key_b, val_b = parse_env_assignment(args.env[1])
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    os.makedirs(args.output, exist_ok=True)
    label_a = sanitize_env_label([f"{key_a}={val_a}"])
    label_b = sanitize_env_label([f"{key_b}={val_b}"])
    dir_a = os.path.join(os.path.abspath(args.output), f"ab_a_{label_a}")
    dir_b = os.path.join(os.path.abspath(args.output), f"ab_b_{label_b}")
    os.makedirs(dir_a, exist_ok=True)
    os.makedirs(dir_b, exist_ok=True)
    # Drop leftovers from earlier model families so null pairing stays honest.
    _clear_dir_files(dir_a)
    _clear_dir_files(dir_b)

    missing = [p for p in args.inputs if not os.path.isfile(p)]
    if missing:
        print(f"error: input not found: {missing[0]}", file=sys.stderr)
        return 2

    inputs = [os.path.abspath(p) for p in args.inputs]
    base_env = os.environ.copy()

    def run_leg(label: str, out_dir: str, key: str, value: str) -> tuple[bool, float, str]:
        env = base_env.copy()
        env[key] = value
        argv = _build_separate_argv(
            inputs=inputs,
            output=out_dir,
            method=args.method,
            model=args.model,
            settings=args.settings,
            cpu=args.cpu,
            stems=args.stems,
        )
        print(f"\n=== bench-ab {label}: {key}={value} ===", flush=True)
        started = time.perf_counter()
        proc = subprocess.run(argv, env=env, check=False)
        elapsed = time.perf_counter() - started
        ok = proc.returncode == 0
        if not ok:
            print(
                f"error: {label} failed with exit code {proc.returncode}",
                file=sys.stderr,
            )
        return ok, elapsed, out_dir

    ok_a, wall_a, _ = run_leg("A", dir_a, key_a, val_a)
    if not ok_a:
        return 1
    ok_b, wall_b, _ = run_leg("B", dir_b, key_b, val_b)
    if not ok_b:
        return 1

    report = compare_stem_dirs(dir_a, dir_b)
    speedup = (wall_a / wall_b) if wall_b > 0 else float("inf")

    print("\n=== bench-ab summary ===")
    print(f"A {key_a}={val_a}  wall_s={wall_a:.3f}  dir={dir_a}")
    print(f"B {key_b}={val_b}  wall_s={wall_b:.3f}  dir={dir_b}")
    print(f"speedup_A_over_B={speedup:.3f}x  ( >1 means A slower than B )")
    print(f"paired_stems={len(report.pairs)}")
    print(f"max_rms_diff={report.max_rms_diff:.6g}")
    print(f"max_peak_abs_diff={report.max_peak_abs_diff:.6g}")
    if report.only_a:
        print(f"only_in_A={report.only_a}")
    if report.only_b:
        print(f"only_in_B={report.only_b}")
    for pair in report.pairs:
        print(
            f"  {pair.name}: rms_diff={pair.rms_diff:.6g} "
            f"peak_abs_diff={pair.peak_abs_diff:.6g}"
        )

    payload = {
        "a": {"env": {key_a: val_a}, "wall_s": wall_a, "dir": dir_a},
        "b": {"env": {key_b: val_b}, "wall_s": wall_b, "dir": dir_b},
        "speedup_a_over_b": speedup,
        "compare": report.to_dict(),
    }
    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2)
            fh.write("\n")
        print(f"json={args.json}")

    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m core.cli",
        description="Headless Ultimate Vocal Remover GTK runner",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    separate = sub.add_parser("separate", help="Run a single-method separation job")
    _add_common_separate_args(separate)
    separate.set_defaults(func=_cmd_separate)

    bench = sub.add_parser(
        "bench-ab",
        help="A/B two env configurations via subprocess separate runs + stem null metrics",
    )
    _add_common_separate_args(bench)
    bench.add_argument(
        "--env",
        action="append",
        required=True,
        metavar="KEY=VALUE",
        help="Env assignment for leg A then B (exactly two required)",
    )
    bench.add_argument(
        "--json",
        default=None,
        help="Optional path to write a JSON summary",
    )
    bench.set_defaults(func=_cmd_bench_ab)

    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
