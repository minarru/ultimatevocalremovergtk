"""Framework-neutral input discovery and readiness policies."""

from __future__ import annotations

import fnmatch
import os
from dataclasses import dataclass
from typing import AbstractSet, Sequence

from .audio_formats import is_audio_filename


@dataclass(frozen=True)
class InputDiscoveryPolicy:
    recursive: bool = False
    includes: tuple[str, ...] = ()
    accept_any: bool = False
    strict: bool = True
    canonicalize: bool = True
    max_files: int | None = None
    large_batch_threshold: int = 100


@dataclass(frozen=True)
class InputDiscoveryResult:
    paths: tuple[str, ...]
    missing: tuple[str, ...] = ()
    unreadable: tuple[str, ...] = ()
    unsupported: tuple[str, ...] = ()
    truncated_count: int = 0
    large_batch_threshold: int = 100

    @property
    def large_batch(self) -> bool:
        return len(self.paths) >= self.large_batch_threshold


class InputDiscoveryService:
    def discover(
        self, values: Sequence[str], policy: InputDiscoveryPolicy
    ) -> InputDiscoveryResult:
        found: list[str] = []
        missing: list[str] = []
        unreadable: list[str] = []
        unsupported: list[str] = []

        def accepted(path: str) -> bool:
            name = os.path.basename(path)
            return (policy.accept_any or is_audio_filename(name)) and (
                not policy.includes
                or any(fnmatch.fnmatch(name, pattern) for pattern in policy.includes)
            )

        for raw in values:
            if raw == "-":
                if policy.strict:
                    raise ValueError("stdin input is not supported; pass an audio file path")
                unsupported.append(raw)
                continue
            path = os.path.abspath(raw)
            if os.path.isfile(path):
                if not os.access(path, os.R_OK):
                    unreadable.append(raw)
                elif accepted(path):
                    found.append(path)
                else:
                    unsupported.append(raw)
                continue
            if not os.path.exists(path):
                missing.append(raw)
                continue
            if not os.path.isdir(path):
                unsupported.append(raw)
                continue
            if not os.access(path, os.R_OK):
                unreadable.append(raw)
                continue
            if policy.recursive:
                for root, dirs, files in os.walk(path):
                    dirs.sort()
                    found.extend(
                        candidate
                        for name in sorted(files)
                        if os.path.isfile(candidate := os.path.join(root, name))
                        and accepted(candidate)
                    )
            else:
                try:
                    names = sorted(os.listdir(path))
                except OSError:
                    unreadable.append(raw)
                    continue
                found.extend(
                    candidate
                    for name in names
                    if os.path.isfile(candidate := os.path.join(path, name))
                    and accepted(candidate)
                )

        if policy.strict:
            if missing:
                raise ValueError(f"input not found: {missing[0]}")
            if unreadable:
                raise ValueError(f"input is not readable: {unreadable[0]}")
            if unsupported:
                raise ValueError(
                    f"unsupported input type: {unsupported[0]}; "
                    "pass --accept-any-input to probe it"
                )
        normalized = [os.path.realpath(path) if policy.canonicalize else path for path in found]
        unique = list(dict.fromkeys(normalized))
        truncated = 0
        if policy.max_files is not None and len(unique) > policy.max_files:
            truncated = len(unique) - policy.max_files
            unique = unique[: policy.max_files]
        if policy.strict and not unique:
            raise ValueError("input discovery found no matching audio files")
        return InputDiscoveryResult(
            tuple(unique), tuple(missing), tuple(unreadable), tuple(unsupported),
            truncated, policy.large_batch_threshold,
        )


def discover_inputs(
    values: Sequence[str], *, recursive: bool = False,
    includes: Sequence[str] = (), accept_any: bool = False,
) -> list[str]:
    result = InputDiscoveryService().discover(
        values,
        InputDiscoveryPolicy(
            recursive=recursive, includes=tuple(includes), accept_any=accept_any
        ),
    )
    return list(result.paths)


def partition_input_paths(paths: Sequence[str]) -> tuple[list[str], list[str]]:
    result = InputDiscoveryService().discover(
        paths,
        InputDiscoveryPolicy(strict=False, accept_any=True, canonicalize=False),
    )
    return list(result.paths), list(result.missing) + list(result.unsupported)


def prune_unreadable_paths(
    unreadable: AbstractSet[str], current_paths: Sequence[str]
) -> set[str]:
    current = {path for path in current_paths if path}
    return {path for path in unreadable if path in current}


def remove_unreadable_from_paths(
    paths: Sequence[str], unreadable: AbstractSet[str]
) -> list[str]:
    return [path for path in paths if path and path not in unreadable]
