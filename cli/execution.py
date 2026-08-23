"""Safe staged batch execution, promotion, and manifests."""

from __future__ import annotations

import dataclasses
import json
import os
import signal
import shutil
import sys
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Sequence, cast

from core.blocking_runner import RunResult, run_blocking
from core.export_naming import format_track_base
from core.job_plan import EMPTY_MODEL_IDENTITY_DIGEST, ResolvedJob as CoreResolvedJob
from core.job_callbacks import JobCallbacks

from .job import ResolvedJob
from .reporting import emit_event, ensure_job_id, finish_progress, make_progress_printer

MANIFEST_SCHEMA_VERSION = 3

_LOCKS_GUARD = threading.Lock()
_OUTPUT_LOCKS: dict[str, threading.Lock] = {}


def _output_dir_lock(output: str) -> threading.Lock:
    key = os.path.abspath(output)
    with _LOCKS_GUARD:
        return _OUTPUT_LOCKS.setdefault(key, threading.Lock())


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


def _matches_ensemble_member_name(name: str, track_prefix: str) -> bool:
    """Recognize retained ensemble-member exports for one input track."""
    stem, extension = os.path.splitext(name)
    return (
        bool(extension)
        and stem.startswith(f"{track_prefix} ")
        and stem.endswith(")")
        and stem.rfind(" (") > len(track_prefix)
    )


def _with_unit_suffix(
    path: str,
    track_base: str,
    index: int,
    *,
    ensemble_member_prefix: str | None = None,
) -> str:
    name = os.path.basename(path)
    if _matches_unit_name(name, track_base):
        prefix = track_base
    elif (
        ensemble_member_prefix is not None
        and _matches_ensemble_member_name(name, ensemble_member_prefix)
    ):
        prefix = ensemble_member_prefix
    else:
        return path
    return os.path.join(
        os.path.dirname(path),
        f"{prefix}_{index}{name[len(prefix):]}",
    )


def _overwrite_backup_path(target: str) -> str:
    directory, name = os.path.split(target)
    return os.path.join(directory, f".{name}.uvr-overwrite.bak")


def _apply_unit_rename(
    entries: list[tuple[str, str]],
    destinations: Sequence[str],
    track_base: str,
    *,
    start_index: int = 2,
    ensemble_member_prefix: str | None = None,
) -> tuple[int, list[tuple[str, str]]]:
    """Pick one free unit suffix for the whole unit.

    Returns the chosen index alongside the remapped entries so a mid-move race
    can restart the unit at a strictly higher index.
    """
    dest_by_name = {os.path.basename(path): path for path in destinations}

    def _remap(index: int) -> list[tuple[str, str]]:
        remapped: list[tuple[str, str]] = []
        for source, target in entries:
            original = dest_by_name.get(os.path.basename(source))
            base_path = original if original is not None else target
            remapped.append((
                source,
                _with_unit_suffix(
                    base_path,
                    track_base,
                    index,
                    ensemble_member_prefix=ensemble_member_prefix,
                ),
            ))
        return remapped

    index = start_index
    while True:
        rewritten = [(
            path,
            _with_unit_suffix(
                path,
                track_base,
                index,
                ensemble_member_prefix=ensemble_member_prefix,
            ),
        ) for path in destinations]
        if any(
            rewritten_path != original and os.path.exists(rewritten_path)
            for original, rewritten_path in rewritten
        ):
            index += 1
            continue
        remapped = _remap(index)
        # Extra stage files may collide too. Only bump when unit-suffix can still
        # move a colliding target; no-op names (sidecar.txt) stay put forever and
        # must not keep this loop alive — those fall back to ``_unique_target``.
        next_by_source = {source: target for source, target in _remap(index + 1)}
        progressable = False
        for source, target in remapped:
            if not os.path.exists(target):
                continue
            if next_by_source.get(source) != target:
                progressable = True
                break
        if progressable:
            index += 1
            continue
        return index, remapped


def _promote(
    stage: str,
    output: str,
    policy: str,
    *,
    destinations: Sequence[str] | None = None,
    expected_track_base: str | None = None,
    ensemble_member_prefix: str | None = None,
) -> list[str]:
    with _output_dir_lock(output):
        return _promote_locked(
            stage,
            output,
            policy,
            destinations=destinations,
            expected_track_base=expected_track_base,
            ensemble_member_prefix=ensemble_member_prefix,
        )


def _promote_locked(
    stage: str,
    output: str,
    policy: str,
    *,
    destinations: Sequence[str] | None = None,
    expected_track_base: str | None = None,
    ensemble_member_prefix: str | None = None,
) -> list[str]:
    entries: list[tuple[str, str]] = []
    for root, dirs, files in os.walk(stage):
        dirs.sort()
        rel_root = os.path.relpath(root, stage)
        target_root = output if rel_root == "." else os.path.join(output, rel_root)
        for name in sorted(files):
            entries.append((os.path.join(root, name), os.path.join(target_root, name)))
    # The staged files are authoritative. Plans intentionally omit conditional
    # outputs, and runtime label canonicalization can expose additional files;
    # collision policy must cover the complete unit that actually exists.
    collision_paths = [target for _source, target in entries]
    track_base: str | None = expected_track_base
    if track_base is None and destinations is not None:
        track_base = next(
            (
                base
                for path in destinations
                if (base := _track_base_from_destination(path)) is not None
            ),
            None,
        )
    if expected_track_base is not None:
        unexpected = next(
            (
                source for source, _target in entries
                if not (
                    _matches_unit_name(os.path.basename(source), expected_track_base)
                    or (
                        ensemble_member_prefix is not None
                        and _matches_ensemble_member_name(
                            os.path.basename(source), ensemble_member_prefix
                        )
                    )
                )
            ),
            None,
        )
        if unexpected is not None:
            raise OSError(
                "unexpected staged separation output "
                f"{os.path.basename(unexpected)!r} for track {expected_track_base!r}"
            )
    if policy == "fail":
        collision = next((path for path in collision_paths if os.path.exists(path)), None)
        if collision:
            raise FileExistsError(collision)
    if policy == "skip":
        collision = next((path for path in collision_paths if os.path.exists(path)), None)
        if collision:
            raise PromotionSkipped(collision)
    # Unit renaming needs both a destination list and a shared track base;
    # without them a collision falls back to a per-file ``_unique_target``.
    unit_destinations: Sequence[str] | None = None
    unit_track_base = ""
    if policy == "rename" and track_base is not None:
        unit_destinations = collision_paths
        unit_track_base = track_base
    unit_index: int | None = None
    attempt = list(entries)
    if unit_destinations is not None and any(
        os.path.exists(path) for path in unit_destinations
    ):
        unit_index, attempt = _apply_unit_rename(
            entries,
            unit_destinations,
            unit_track_base,
            ensemble_member_prefix=ensemble_member_prefix,
        )
    backups: list[tuple[str, str]] = []
    promoted: list[str] = []
    moved: list[tuple[str, str]] = []
    try:
        if policy == "overwrite":
            # Move, don't copy: the backup only has to survive until the whole
            # unit lands, and a rename is atomic within the output directory.
            for _source, target in entries:
                if os.path.exists(target):
                    bak = _overwrite_backup_path(target)
                    os.replace(target, bak)
                    backups.append((target, bak))
        while True:
            restart = False
            for source, initial_target in attempt:
                target = initial_target
                os.makedirs(os.path.dirname(target) or ".", exist_ok=True)
                if os.path.exists(target):
                    if policy == "fail":
                        raise FileExistsError(target)
                    if policy == "skip":
                        raise PromotionSkipped(target)
                    if policy == "rename":
                        source_name = os.path.basename(source)
                        if unit_destinations is not None and (
                            _matches_unit_name(source_name, unit_track_base)
                            or (
                                ensemble_member_prefix is not None
                                and _matches_ensemble_member_name(
                                    source_name, ensemble_member_prefix
                                )
                            )
                        ):
                            # A raced suffix splits the unit; restart it whole.
                            restart = True
                            break
                        target = _unique_target(target)
                os.replace(source, target)
                moved.append((source, target))
                promoted.append(target)
            if not restart or unit_destinations is None:
                break
            for source, target in reversed(moved):
                if os.path.exists(target):
                    os.makedirs(os.path.dirname(source) or ".", exist_ok=True)
                    os.replace(target, source)
            moved.clear()
            promoted.clear()
            unit_index, attempt = _apply_unit_rename(
                entries,
                unit_destinations,
                unit_track_base,
                start_index=2 if unit_index is None else unit_index + 1,
                ensemble_member_prefix=ensemble_member_prefix,
            )
    except BaseException:
        for source, target in reversed(moved):
            if os.path.exists(target):
                os.makedirs(os.path.dirname(source) or ".", exist_ok=True)
                os.replace(target, source)
        for target, bak in backups:
            if os.path.exists(bak):
                os.replace(bak, target)
        raise
    for _target, bak in backups:
        if os.path.exists(bak):
            os.unlink(bak)
    return promoted


def run_batch(args: Any, job: ResolvedJob) -> BatchOutcome:
    started = time.perf_counter()
    collided = preflight_collisions(job, args.on_exists)
    os.makedirs(job.output, exist_ok=True)
    job_id = ensure_job_id(args)
    temp_root = os.path.join(job.output, ".uvr-tmp", job_id)
    os.makedirs(temp_root, exist_ok=True)
    outcomes: list[dict[str, Any]] = []
    interrupted = False
    from core.job_runner import JobRunner

    shared_runner = JobRunner(job.settings, job.repo)
    resolved: Any = job.resolved
    shared_models = shared_runner.resolve_models(resolved.model_dependencies)
    planned_all: tuple[Any, ...] = tuple(getattr(resolved, "inputs", None) or ())
    total = len(planned_all)
    progress = make_progress_printer(args)

    def record(item: dict[str, Any]) -> None:
        outcomes.append(item)
        emit_event(args, "input_finished", **item)

    try:
        # One run per input: a completed input is promoted out of staging before
        # the next one starts, so a mid-batch death keeps what already finished.
        for index, planned_item in enumerate(planned_all, start=1):
            input_path = planned_item.path
            if input_path in collided and args.on_exists == "skip":
                record({
                    "input": input_path, "status": "skipped", "outputs": [],
                    "elapsed_s": 0.0,
                })
                continue
            stage = os.path.join(temp_root, str(index))
            os.makedirs(stage, exist_ok=True)
            emit_event(
                args, "progress", fraction=0.0, phase="input_started",
                input=input_path, index=index, total=total,
            )
            item_job = cast(
                CoreResolvedJob,
                dataclasses.replace(resolved, inputs=(planned_item,)),
            )
            shared_runner.last_outcomes = ()
            result = run_runner_cli(
                shared_runner,
                lambda callbacks: shared_runner.start_resolved(
                    item_job,
                    callbacks,
                    models=shared_models,
                    fail_fast=True,
                    export_paths=(stage,),
                    operation_id=job_id,
                ),
                print_console=not args.quiet,
                on_progress=progress,
            )
            if progress is not None:
                finish_progress(args)

            last_outcomes = tuple(getattr(shared_runner, "last_outcomes", ()) or ())
            outcome = last_outcomes[0] if last_outcomes else None
            stop_requested = bool(
                result.interrupted
                or result.stopped
                or (outcome is not None and outcome.stopped)
            )
            elapsed = (
                float(outcome.elapsed_s) if outcome is not None
                else float(result.elapsed_s)
            )
            failure: str | None = None
            if result.error is not None:
                # An unexpected runner failure belongs to the in-flight input.
                failure = f"{type(result.error).__name__}: {result.error}"
            elif outcome is None:
                failure = (
                    "interrupted" if stop_requested
                    else "runner produced no result"
                )
            elif outcome.stopped:
                failure = "interrupted"
            elif outcome.status == "failed":
                failure = outcome.error or "failed"

            if failure is not None:
                record({
                    "input": input_path, "status": "failed", "error": failure,
                    "outputs": [], "elapsed_s": elapsed,
                })
            elif outcome is not None and outcome.status == "skipped":
                record({
                    "input": input_path, "status": "skipped", "outputs": [],
                    "elapsed_s": elapsed,
                })
            else:
                try:
                    promoted = _promote(
                        stage, job.output, args.on_exists,
                        destinations=[
                            output.path
                            for output in planned_item.outputs
                            if not output.conditional
                        ],
                        expected_track_base=planned_item.naming.track_base,
                        ensemble_member_prefix=(
                            format_track_base(
                                track=planned_item.naming.track,
                                file_index=planned_item.naming.file_index,
                                file_total=planned_item.naming.file_total,
                                timestamp=planned_item.naming.timestamp,
                            )
                            if job.command == "ensemble"
                            and job.settings.ensemble.save_all_outputs
                            else None
                        ),
                    )
                    if not promoted:
                        raise OSError(
                            "separation completed without generating output files"
                        )
                except PromotionSkipped:
                    record({
                        "input": input_path, "status": "skipped", "outputs": [],
                        "elapsed_s": elapsed,
                    })
                except OSError as exc:
                    failure = f"{type(exc).__name__}: {exc}"
                    record({
                        "input": input_path, "status": "failed", "error": failure,
                        "outputs": [], "elapsed_s": elapsed,
                    })
                else:
                    record({
                        "input": input_path, "status": "success",
                        "outputs": promoted, "elapsed_s": elapsed,
                    })
            shutil.rmtree(stage, ignore_errors=True)

            if stop_requested:
                interrupted = True
                if failure != "interrupted" and index < total:
                    # Attribute the stop to the next unprocessed input — never
                    # re-label a completed success as interrupted.
                    record({
                        "input": planned_all[index].path, "status": "failed",
                        "error": "interrupted", "outputs": [], "elapsed_s": 0.0,
                    })
                break
            if failure is not None and getattr(args, "fail_fast", False):
                break
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
    dependencies = job.plan.get("model_dependencies", {})
    if not isinstance(dependencies, dict):
        raise ValueError("resolved plan model_dependencies must be an object")
    model_dependencies = {
        str(path): str(model_id)
        for path, model_id in sorted(dependencies.items())
    }
    identity_digest = job.plan.get(
        "model_identity_digest", EMPTY_MODEL_IDENTITY_DIGEST
    )
    if not isinstance(identity_digest, str):
        raise ValueError("resolved plan model_identity_digest must be a string")
    payload = {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "model_dependencies": model_dependencies,
        "model_identity_digest": identity_digest,
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
