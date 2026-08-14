"""The ``bench-ab`` command: two env legs, subprocess separates, null metrics."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from typing import Any, Optional, Sequence

from core.bench_metrics import (
    compare_stem_dirs,
    parse_env_assignment,
    sanitize_env_label,
)

from .process_flags import collect_overrides, overrides_to_argv
from .separate import check_runtime_deps

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


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


def _child_env(base: dict[str, str]) -> dict[str, str]:
    """Ensure the child can import ``cli`` regardless of the inherited cwd."""
    env = base.copy()
    existing = env.get("PYTHONPATH", "")
    parts = [_REPO_ROOT] + [p for p in existing.split(os.pathsep) if p]
    env["PYTHONPATH"] = os.pathsep.join(parts)
    return env


def build_separate_argv(
    *,
    inputs: Sequence[str],
    output: str,
    method: Optional[str],
    model: Optional[str],
    settings: Optional[str],
    stems: Optional[str] = None,
    print_settings: bool = False,
    long_chunk_seconds: Optional[float] = None,
    long_chunk_overlap: Optional[float] = None,
    overrides: Sequence[tuple[str, Any]] = (),
    vocal_split: Optional[str] = None,
) -> list[str]:
    argv = [sys.executable, "-m", "cli", "separate", *inputs, "-o", output]
    if method:
        argv.extend(["--method", method])
    if model:
        argv.extend(["--model", model])
    if settings:
        argv.extend(["--settings", settings])
    if stems:
        argv.extend(["--stems", stems])
    if print_settings:
        argv.append("--print-settings")
    if long_chunk_seconds is not None:
        argv.extend(["--long-chunk-seconds", str(long_chunk_seconds)])
    if long_chunk_overlap is not None:
        argv.extend(["--long-chunk-overlap", str(long_chunk_overlap)])
    argv.extend(overrides_to_argv(overrides))
    if vocal_split:
        argv.extend(["--vocal-split", vocal_split])
    return argv


def cmd_bench_ab(args: argparse.Namespace) -> int:
    dep_err = check_runtime_deps()
    if dep_err:
        print(f"error: {dep_err}", file=sys.stderr)
        return 2

    if len(args.env) != 2:
        print("error: bench-ab requires exactly two --env KEY=value flags", file=sys.stderr)
        return 2

    try:
        key_a, val_a = parse_env_assignment(args.env[0])
        key_b, val_b = parse_env_assignment(args.env[1])
        process_overrides = collect_overrides(args)
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
        env = _child_env(base_env)
        env[key] = value
        argv = build_separate_argv(
            inputs=inputs,
            output=out_dir,
            method=args.method,
            model=args.model,
            settings=args.settings,
            stems=args.stems,
            print_settings=args.print_settings,
            long_chunk_seconds=args.long_chunk_seconds,
            long_chunk_overlap=args.long_chunk_overlap,
            overrides=process_overrides,
            vocal_split=args.vocal_split,
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
