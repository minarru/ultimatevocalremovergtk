"""General two-leg separation benchmark."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from typing import Any, Sequence

from core.bench_metrics import compare_stem_dirs, parse_env_assignment

from .reporting import add_reporting_args, emit_document, ensure_job_id, fail

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def add_bench_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("inputs", nargs="+", help="Explicit input audio files")
    parser.add_argument("-o", "--output", required=True, help="Benchmark root")
    parser.add_argument("--model", help="Shared canonical model ID")
    parser.add_argument("--profile", help="Shared non-GUI profile")
    parser.add_argument("--a-model")
    parser.add_argument("--b-model")
    parser.add_argument("--a-profile")
    parser.add_argument("--b-profile")
    parser.add_argument("--a-env", action="append", default=[], metavar="KEY=VALUE")
    parser.add_argument("--b-env", action="append", default=[], metavar="KEY=VALUE")
    parser.add_argument("--a-set", action="append", default=[], metavar="PATH=VALUE")
    parser.add_argument("--b-set", action="append", default=[], metavar="PATH=VALUE")
    parser.add_argument("--stems")
    parser.add_argument(
        "--keep-outputs", choices=("always", "failure", "never"), default="always"
    )
    manifest = parser.add_mutually_exclusive_group()
    manifest.add_argument("--manifest", action="store_true")
    manifest.add_argument("--manifest-out")
    add_reporting_args(parser)


def _child_env(assignments: Sequence[str]) -> dict[str, str]:
    env = os.environ.copy()
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = os.pathsep.join(
        [_REPO_ROOT, *[part for part in existing.split(os.pathsep) if part]]
    )
    for assignment in assignments:
        key, value = parse_env_assignment(assignment)
        env[key] = value
    return env


def _leg_argv(
    args: argparse.Namespace,
    label: str,
    output: str,
    *,
    dry_run: bool,
) -> list[str]:
    lower = label.lower()
    model = getattr(args, f"{lower}_model") or args.model
    profile = getattr(args, f"{lower}_profile") or args.profile
    values = [sys.executable, "-m", "cli", "separate", *args.inputs, "-o", output]
    if model:
        values.extend(["--model", model])
    if profile:
        values.extend(["--profile", profile, "--accept-inherited"])
    if args.stems:
        values.extend(["--stems", args.stems])
    for setting in getattr(args, f"{lower}_set"):
        values.extend(["--set", setting])
    values.extend(["--report", "json", "--quiet"])
    if dry_run:
        values.append("--dry-run")
    return values


def _run_child(argv: list[str], env: dict[str, str]) -> tuple[int, dict[str, Any], float]:
    started = time.perf_counter()
    proc = subprocess.run(argv, env=env, capture_output=True, text=True, check=False)
    elapsed = time.perf_counter() - started
    try:
        payload = json.loads(proc.stdout) if proc.stdout.strip() else {}
    except json.JSONDecodeError:
        payload = {"error": {"message": proc.stderr.strip() or "invalid child output"}}
    return proc.returncode, payload, elapsed


def _stem_topology(plan: dict[str, Any]) -> tuple[str, ...]:
    models = plan.get("models") or []
    stems: set[str] = set()
    for model in models:
        for key in ("primary_stem", "secondary_stem"):
            value = model.get(key)
            if value:
                stems.add(str(value))
    return tuple(sorted(stems))


def _cleanup_outputs(args: argparse.Namespace, root: str, *, succeeded: bool) -> None:
    if args.keep_outputs == "never" or (args.keep_outputs == "failure" and succeeded):
        shutil.rmtree(root, ignore_errors=True)


def cmd_bench(args: argparse.Namespace) -> int:
    profile_a = args.a_profile or args.profile
    profile_b = args.b_profile or args.profile
    if not (args.a_model or args.model or (profile_a and profile_a != "gui")):
        return fail(args, "benchmark leg A requires an explicit model or non-GUI profile", exit_code=2)
    if not (args.b_model or args.model or (profile_b and profile_b != "gui")):
        return fail(args, "benchmark leg B requires an explicit model or non-GUI profile", exit_code=2)
    try:
        env_a = _child_env(args.a_env)
        env_b = _child_env(args.b_env)
    except ValueError as exc:
        return fail(args, str(exc), exit_code=2, exc=exc)

    root = os.path.join(os.path.abspath(args.output), f"bench-{ensure_job_id(args)}")
    dir_a, dir_b = os.path.join(root, "a"), os.path.join(root, "b")
    # Both dry validations occur before the benchmark root is created.
    code_a, check_a, _ = _run_child(_leg_argv(args, "a", dir_a, dry_run=True), env_a)
    code_b, check_b, _ = _run_child(_leg_argv(args, "b", dir_b, dry_run=True), env_b)
    if code_a or code_b:
        interrupted = code_a == 130 or code_b == 130
        return fail(
            args,
            "benchmark validation was interrupted" if interrupted else "benchmark validation failed before leg A",
            exit_code=130 if interrupted else 2,
            extra={"a": check_a, "b": check_b},
        )
    topo_a = _stem_topology(check_a.get("plan") or {})
    topo_b = _stem_topology(check_b.get("plan") or {})
    if not topo_a or not topo_b or topo_a != topo_b:
        return fail(args, "benchmark legs have incompatible stem topology", exit_code=2)

    os.makedirs(root, exist_ok=False)
    code_a, result_a, wall_a = _run_child(_leg_argv(args, "a", dir_a, dry_run=False), env_a)
    if code_a:
        _cleanup_outputs(args, root, succeeded=False)
        return fail(args, f"benchmark leg A failed with exit code {code_a}", exit_code=130 if code_a == 130 else 1, extra={"a": result_a})
    code_b, result_b, wall_b = _run_child(_leg_argv(args, "b", dir_b, dry_run=False), env_b)
    if code_b:
        _cleanup_outputs(args, root, succeeded=False)
        return fail(args, f"benchmark leg B failed with exit code {code_b}", exit_code=130 if code_b == 130 else 1, extra={"b": result_b})
    comparison = compare_stem_dirs(dir_a, dir_b)
    payload: dict[str, Any] = {
        "ok": True,
        "status": "success",
        "command": "bench",
        "a": {"wall_s": wall_a, "dir": dir_a, "result": result_a},
        "b": {"wall_s": wall_b, "dir": dir_b, "result": result_b},
        "speedup_a_over_b": wall_a / wall_b if wall_b else float("inf"),
        "compare": comparison.to_dict(),
    }
    manifest_path = args.manifest_out
    if args.manifest and not manifest_path:
        manifest_path = os.path.join(
            os.path.abspath(args.output), f"benchmark-manifest-{ensure_job_id(args)}.json"
        )
    if manifest_path:
        os.makedirs(os.path.dirname(os.path.abspath(manifest_path)) or ".", exist_ok=True)
        tmp = f"{manifest_path}.tmp"
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump({"schema_version": 1, "job_id": ensure_job_id(args), **payload}, handle, indent=2, sort_keys=True)
            handle.write("\n")
        os.replace(tmp, manifest_path)
        payload["manifest"] = os.path.abspath(manifest_path)
    _cleanup_outputs(args, root, succeeded=True)
    emit_document(args, payload)
    return 0
