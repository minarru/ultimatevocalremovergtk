"""Safe staged batch execution, promotion, and manifests."""

from __future__ import annotations

import copy
import dataclasses
import json
import os
import signal
import shutil
import sys
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Sequence

from bundled.constants import ENSEMBLE_MODE
from core.blocking_runner import RunResult, run_blocking
from core.export_naming import rebase_output_naming
from core.job_runner import JobCallbacks, JobRunner
from core.settings import Settings

from .job import ResolvedJob
from .reporting import emit_event, ensure_job_id, finish_progress, make_progress_printer

MANIFEST_SCHEMA_VERSION = 1


class PromotionSkipped(Exception):
    """A promotion-time collision caused the whole input to be skipped."""


@dataclass
class BatchOutcome:
    status: str
    elapsed_s: float
    inputs: list[dict[str, Any]] = field(default_factory=list)
    interrupted: bool = False

    @property
    def exit_code(self) -> int:
        if self.interrupted:
            return 130
        successes = sum(item["status"] == "success" for item in self.inputs)
        failures = sum(item["status"] == "failed" for item in self.inputs)
        if failures and successes:
            return 3
        if failures:
            return 1
        return 0


def run_runner_cli(
    runner: Any,
    start: Callable[[JobCallbacks], None],
    *,
    print_console: bool = True,
    join_timeout: float | None = None,
    on_progress: Callable[..., None] | None = None,
) -> RunResult:
    """Run a callback runner while the CLI owns signals and presentation."""
    interrupted = {"count": 0}

    def request_stop(_signum: int, _frame: Any) -> None:
        interrupted["count"] += 1
        force = interrupted["count"] > 1
        print(
            "\nforcing stop" if force else "\nstopping… (Ctrl-C again to force)",
            file=sys.stderr,
        )
        runner.stop(force=force)

    previous: dict[int, Any] = {}
    for signum in (signal.SIGINT, getattr(signal, "SIGTERM", None)):
        if signum is None:
            continue
        try:
            previous[signum] = signal.getsignal(signum)
            signal.signal(signum, request_stop)
        except (AttributeError, OSError, ValueError):
            pass
    try:
        result = run_blocking(
            runner,
            start,
            timeout=join_timeout,
            on_progress=on_progress,
            on_console=(
                lambda value: print(
                    value, file=sys.stderr, end="" if value.endswith("\n") else "\n"
                )
                if print_console else None
            ),
        )
    finally:
        for signum, handler in previous.items():
            try:
                signal.signal(signum, handler)
            except (AttributeError, OSError, TypeError, ValueError):
                pass
    return result.with_interrupted(bool(interrupted["count"]))


def _run_job_cli(
    settings: Settings,
    input_paths: Sequence[str],
    *,
    ensemble: bool,
    print_console: bool = True,
    join_timeout: float | None = None,
    on_progress: Callable[..., None] | None = None,
    runner: JobRunner | None = None,
    models: Sequence[Any] | None = None,
    planned: Sequence[Any] | None = None,
    planned_output_root: str | None = None,
) -> RunResult:
    if not input_paths:
        raise ValueError("at least one input path is required")
    if not settings.process.export_path:
        raise ValueError("export_path is empty")
    job_runner = runner or JobRunner(settings)
    # A batch deliberately reuses one runner/repository and the engine weight
    # cache, but each input has a distinct staging export directory.
    job_runner.settings = settings
    if ensemble:
        start = lambda callbacks: job_runner.start_ensemble(
            list(input_paths),
            callbacks,
            models=models,
            planned=planned,
            planned_output_root=planned_output_root,
        )
    else:
        start = lambda callbacks: job_runner.start(
            list(input_paths),
            callbacks,
            models=models,
            planned=planned,
            planned_output_root=planned_output_root,
        )
    return run_runner_cli(
        job_runner, start, print_console=print_console,
        join_timeout=join_timeout, on_progress=on_progress,
    )


def run_separation_cli(settings: Settings, input_paths: Sequence[str], **kwargs: Any) -> RunResult:
    if settings.process.method == ENSEMBLE_MODE:
        raise ValueError("ensemble mode requires run_ensemble_cli")
    return _run_job_cli(settings, input_paths, ensemble=False, **kwargs)


def run_ensemble_cli(settings: Settings, input_paths: Sequence[str], **kwargs: Any) -> RunResult:
    return _run_job_cli(settings, input_paths, ensemble=True, **kwargs)


def preflight_collisions(job: ResolvedJob, policy: str) -> set[str]:
    planned_inputs = job.resolved.inputs if job.resolved is not None else ()
    collided: set[str] = set()
    for item in planned_inputs:
        guaranteed = [output.path for output in item.outputs if not output.conditional]
        if any(os.path.exists(path) for path in guaranteed):
            collided.add(item.path)
    if collided and policy == "fail":
        first = sorted(collided)[0]
        raise ValueError(
            f"output already exists for {first}; choose --on-exists overwrite, rename, or skip"
        )
    return collided


def _unique_target(path: str) -> str:
    if not os.path.exists(path):
        return path
    root, ext = os.path.splitext(path)
    index = 2
    while os.path.exists(f"{root}_{index}{ext}"):
        index += 1
    return f"{root}_{index}{ext}"


def _track_base_from_destination(path: str) -> str | None:
    stem, _ext = os.path.splitext(os.path.basename(path))
    idx = stem.rfind(" (")
    if idx > 0:
        return stem[:idx]
    return stem or None


def _matches_unit_name(name: str, track_base: str) -> bool:
    return name.startswith(f"{track_base} (") or name.startswith(f"{track_base}.")


def _with_unit_suffix(path: str, track_base: str, index: int) -> str:
    name = os.path.basename(path)
    if not _matches_unit_name(name, track_base):
        return path
    return os.path.join(
        os.path.dirname(path),
        f"{track_base}_{index}{name[len(track_base):]}",
    )


def _promote(
    stage: str,
    output: str,
    policy: str,
    *,
    destinations: Sequence[str] | None = None,
) -> list[str]:
    entries: list[tuple[str, str]] = []
    for root, dirs, files in os.walk(stage):
        dirs.sort()
        rel_root = os.path.relpath(root, stage)
        target_root = output if rel_root == "." else os.path.join(output, rel_root)
        for name in sorted(files):
            entries.append((os.path.join(root, name), os.path.join(target_root, name)))
    # Recheck all predictable targets before moving any file. This keeps a
    # promotion-time race under ``fail`` from exposing half an input's stems.
    collision_paths = (
        list(destinations) if destinations is not None
        else [target for _source, target in entries]
    )
    if policy == "fail":
        collision = next((path for path in collision_paths if os.path.exists(path)), None)
        if collision:
            raise FileExistsError(collision)
    if policy == "skip":
        collision = next((path for path in collision_paths if os.path.exists(path)), None)
        if collision:
            raise PromotionSkipped(collision)
    if policy == "rename" and destinations is not None and any(
        os.path.exists(path) for path in destinations
    ):
        track_base = next(
            (
                base
                for path in destinations
                if (base := _track_base_from_destination(path)) is not None
            ),
            None,
        )
        if track_base is not None:
            index = 2
            while True:
                rewritten = [
                    _with_unit_suffix(path, track_base, index) for path in destinations
                ]
                if not any(os.path.exists(path) for path in rewritten):
                    entries = [
                        (source, _with_unit_suffix(target, track_base, index))
                        for source, target in entries
                    ]
                    break
                index += 1
    promoted: list[str] = []
    for source, initial_target in entries:
        target = initial_target
        target_root = os.path.dirname(target)
        os.makedirs(target_root, exist_ok=True)
        if os.path.exists(target):
            if policy == "fail":
                raise FileExistsError(target)
            if policy == "skip":
                continue
            if policy == "rename":
                target = _unique_target(target)
        os.replace(source, target)
        promoted.append(target)
    return promoted


def run_batch(
    args: Any,
    job: ResolvedJob,
    runner: Callable[..., RunResult],
) -> BatchOutcome:
    started = time.perf_counter()
    collided = preflight_collisions(job, args.on_exists)
    os.makedirs(job.output, exist_ok=True)
    job_id = ensure_job_id(args)
    temp_root = os.path.join(job.output, ".uvr-tmp", job_id)
    os.makedirs(temp_root, exist_ok=True)
    outcomes: list[dict[str, Any]] = []
    interrupted = False
    from core.job_runner import JobRunner

    shared_runner = JobRunner(job.settings)
    shared_models = shared_runner.resolve_models()
    try:
        for index, input_path in enumerate(job.inputs, start=1):
            if input_path in collided and args.on_exists == "skip":
                item = {
                    "input": input_path, "status": "skipped", "outputs": [],
                    "elapsed_s": 0.0,
                }
                outcomes.append(item)
                emit_event(args, "input_finished", **item)
                continue
            stage = os.path.join(temp_root, str(index))
            os.makedirs(stage, exist_ok=True)
            input_started = time.perf_counter()
            settings = copy.deepcopy(job.settings)
            settings.process.export_path = stage
            emit_event(
                args, "progress", fraction=0.0, phase="input_started",
                input=input_path, index=index, total=len(job.inputs),
            )
            progress = make_progress_printer(args)
            planned_item = job.resolved.inputs[index - 1]
            staged = dataclasses.replace(
                planned_item,
                naming=rebase_output_naming(
                    planned_item.naming, stage, job.output,
                ),
            )
            result = runner(
                settings,
                [input_path],
                print_console=not args.quiet,
                on_progress=progress,
                runner=shared_runner,
                models=shared_models,
                planned=(staged,),
                planned_output_root=job.output,
            )
            if progress is not None:
                finish_progress(args)
            if result.stopped:
                interrupted = True
                item = {
                    "input": input_path, "status": "failed", "error": "interrupted",
                    "outputs": [], "elapsed_s": time.perf_counter() - input_started,
                }
                outcomes.append(item)
                emit_event(args, "input_finished", **item)
                break
            if result.error is not None:
                item = {
                    "input": input_path,
                    "status": "failed",
                    "error": f"{type(result.error).__name__}: {result.error}",
                    "outputs": [],
                    "elapsed_s": time.perf_counter() - input_started,
                }
                outcomes.append(item)
                emit_event(args, "input_finished", **item)
                if args.fail_fast:
                    break
                continue
            try:
                outputs = _promote(
                    stage, job.output, args.on_exists,
                    destinations=[
                        output.path
                        for output in planned_item.outputs
                        if not output.conditional
                    ],
                )
                if not outputs:
                    raise OSError("separation completed without generating output files")
            except PromotionSkipped:
                item = {
                    "input": input_path, "status": "skipped", "outputs": [],
                    "elapsed_s": time.perf_counter() - input_started,
                }
                outcomes.append(item)
                emit_event(args, "input_finished", **item)
                continue
            except OSError as exc:
                item = {
                    "input": input_path,
                    "status": "failed",
                    "error": f"{type(exc).__name__}: {exc}",
                    "outputs": [],
                    "elapsed_s": time.perf_counter() - input_started,
                }
                outcomes.append(item)
                emit_event(args, "input_finished", **item)
                if args.fail_fast:
                    break
                continue
            item = {
                "input": input_path, "status": "success", "outputs": outputs,
                "elapsed_s": time.perf_counter() - input_started,
            }
            outcomes.append(item)
            emit_event(args, "input_finished", **item)
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)
        parent = os.path.dirname(temp_root)
        try:
            os.rmdir(parent)
        except OSError:
            pass
    failures = sum(item["status"] == "failed" for item in outcomes)
    successes = sum(item["status"] == "success" for item in outcomes)
    status = "partial" if failures and successes else "failed" if failures else "success"
    return BatchOutcome(
        status=status,
        elapsed_s=time.perf_counter() - started,
        inputs=outcomes,
        interrupted=interrupted,
    )


def manifest_path(args: Any, output: str) -> str | None:
    if getattr(args, "manifest_out", None):
        return os.path.abspath(args.manifest_out)
    if getattr(args, "manifest", False):
        return os.path.join(output, f"uvr-manifest-{ensure_job_id(args)}.json")
    return None


def write_manifest(
    args: Any,
    job: ResolvedJob,
    outcome: BatchOutcome,
    *,
    original_argv: list[str] | None = None,
) -> str | None:
    path = manifest_path(args, job.output)
    if path is None:
        return None
    settings_payload = job.settings.to_json_dict()
    for setting_path, identity in (
        job.plan.get("model_chains")
        or (job.plan.get("metadata") or {}).get("model_chains")
        or {}
    ).items():
        section, field_name = setting_path.split(".", 1)
        if section in settings_payload:
            settings_payload[section][field_name] = identity["id"]
    payload = {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "job_id": ensure_job_id(args),
        "command": job.command,
        "argv": original_argv or [],
        "plan": job.plan,
        "settings": settings_payload,
        "job_spec": {
            "inputs": list(job.inputs),
            "output": job.output,
            "model": job.model.id if job.model else None,
            "ensemble": (job.plan.get("metadata") or {}).get("preset"),
            "members": [record.id for record in job.members],
            "collision_policy": getattr(args, "on_exists", "fail"),
        },
        "status": outcome.status,
        "interrupted": outcome.interrupted,
        "stopped": outcome.interrupted,
        "elapsed_s": outcome.elapsed_s,
        "inputs": outcome.inputs,
    }
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")
    os.replace(tmp, path)
    return path
