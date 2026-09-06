"""Live staged-file publication, collision retry, and rollback transaction."""

from __future__ import annotations

import errno
import os
import sys
import threading
from typing import Sequence

from .promotion_plan import (
    PromotionPlan,
    _matches_ensemble_member_name,
    _matches_unit_name,
    suffix_candidate,
)

_LOCKS_GUARD = threading.Lock()
_OUTPUT_LOCKS: dict[str, threading.Lock] = {}


def _output_dir_lock(output: str) -> threading.Lock:
    key = os.path.abspath(output)
    with _LOCKS_GUARD:
        return _OUTPUT_LOCKS.setdefault(key, threading.Lock())


class PromotionSkipped(Exception):
    """A promotion-time collision caused the whole input to be skipped."""


def _unique_target(path: str) -> str:
    if not os.path.lexists(path):
        return path
    root, ext = os.path.splitext(path)
    index = 2
    while os.path.lexists(f"{root}_{index}{ext}"):
        index += 1
    return f"{root}_{index}{ext}"


def _overwrite_backup_path(target: str) -> str:
    directory, name = os.path.split(target)
    return os.path.join(directory, f".{name}.uvr-overwrite.bak")


def _move_no_replace(source: str, target: str) -> None:
    """Publish a staged file atomically without replacing another writer's file."""
    if sys.platform == "win32":
        # Unlike POSIX rename, Windows rename rejects an existing destination.
        os.rename(source, target)
        return
    if sys.platform.startswith("linux"):
        import ctypes

        renameat2 = getattr(ctypes.CDLL(None, use_errno=True), "renameat2", None)
        if renameat2 is not None:
            renameat2.argtypes = (
                ctypes.c_int,
                ctypes.c_char_p,
                ctypes.c_int,
                ctypes.c_char_p,
                ctypes.c_uint,
            )
            renameat2.restype = ctypes.c_int
            # AT_FDCWD = -100, RENAME_NOREPLACE = 1. Unlike link/unlink, this
            # also supports removable filesystems without hard links.
            if renameat2(-100, os.fsencode(source), -100, os.fsencode(target), 1) == 0:
                return
            error = ctypes.get_errno()
            if error not in (errno.ENOSYS, errno.EINVAL, errno.EOPNOTSUPP):
                raise OSError(error, os.strerror(error), target)
    # Portable same-filesystem fallback. Never fall back to a replacing rename
    # if the filesystem cannot support an atomic claim.
    os.link(source, target)
    try:
        os.unlink(source)
    except BaseException:
        os.unlink(target)
        raise


def _apply_unit_rename(
    plan: PromotionPlan,
    *,
    start_index: int = 2,
) -> tuple[int, list[tuple[str, str]]]:
    """Probe current occupancy for successive immutable whole-unit candidates."""
    index = start_index
    while True:
        candidate = suffix_candidate(plan, index)
        if any(os.path.lexists(target) for target in candidate.rewritten_targets):
            index += 1
            continue
        # No-op sidecars never force an endless unit-suffix loop: the live
        # transaction will choose their per-file unique destination instead.
        progressable = False
        for source, target in candidate.entries:
            if not os.path.lexists(target):
                continue
            if source in candidate.progressable_sources:
                progressable = True
                break
        if progressable:
            index += 1
            continue
        return index, list(candidate.entries)


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
    plan = PromotionPlan.associate(
        entries,
        destinations=destinations,
        expected_track_base=expected_track_base,
        ensemble_member_prefix=ensemble_member_prefix,
    )
    track_base = plan.track_base
    if policy == "fail":
        collision = next((path for path in collision_paths if os.path.lexists(path)), None)
        if collision:
            raise FileExistsError(collision)
    if policy == "skip":
        collision = next((path for path in collision_paths if os.path.lexists(path)), None)
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
    if unit_destinations is not None and any(os.path.lexists(path) for path in unit_destinations):
        unit_index, attempt = _apply_unit_rename(
            plan,
        )
    backups: list[tuple[str, str]] = []
    promoted: list[str] = []
    moved: list[tuple[str, str]] = []
    try:
        if policy == "overwrite":
            # Move, don't copy: the backup only has to survive until the whole
            # unit lands, and a rename is atomic within the output directory.
            for _source, target in entries:
                if os.path.lexists(target):
                    bak = _overwrite_backup_path(target)
                    os.replace(target, bak)
                    backups.append((target, bak))
        while True:
            restart = False
            for source, initial_target in attempt:
                target = initial_target
                os.makedirs(os.path.dirname(target) or ".", exist_ok=True)
                while True:
                    try:
                        if os.path.lexists(target) and policy != "overwrite":
                            raise FileExistsError(target)
                        if policy == "overwrite":
                            os.replace(source, target)
                        else:
                            _move_no_replace(source, target)
                    except FileExistsError as exc:
                        if policy == "fail":
                            raise
                        if policy == "skip":
                            raise PromotionSkipped(target) from exc
                        if policy != "rename":
                            raise
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
                        continue
                    break
                if restart:
                    break
                moved.append((source, target))
                promoted.append(target)
            if not restart or unit_destinations is None:
                break
            for source, target in reversed(moved):
                if os.path.lexists(target):
                    os.makedirs(os.path.dirname(source) or ".", exist_ok=True)
                    os.replace(target, source)
            moved.clear()
            promoted.clear()
            unit_index, attempt = _apply_unit_rename(
                plan,
                start_index=2 if unit_index is None else unit_index + 1,
            )
    except BaseException:
        for source, target in reversed(moved):
            if os.path.lexists(target):
                os.makedirs(os.path.dirname(source) or ".", exist_ok=True)
                os.replace(target, source)
        for target, bak in backups:
            if os.path.lexists(bak):
                os.replace(bak, target)
        raise
    for _target, bak in backups:
        if os.path.lexists(bak):
            os.unlink(bak)
    return promoted
