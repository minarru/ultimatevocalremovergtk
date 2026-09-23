"""Immutable association and destination remapping for one staged output unit."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Sequence


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
    elif ensemble_member_prefix is not None and _matches_ensemble_member_name(
        name, ensemble_member_prefix
    ):
        prefix = ensemble_member_prefix
    else:
        return path
    return os.path.join(
        os.path.dirname(path),
        f"{prefix}_{index}{name[len(prefix) :]}",
    )


@dataclass(frozen=True, slots=True)
class PromotionPlan:
    entries: tuple[tuple[str, str], ...]
    track_base: str | None
    ensemble_member_prefix: str | None

    @classmethod
    def associate(
        cls,
        entries: Sequence[tuple[str, str]],
        *,
        destinations: Sequence[str] | None,
        expected_track_base: str | None,
        ensemble_member_prefix: str | None,
    ) -> PromotionPlan:
        track_base = expected_track_base
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
                    source
                    for source, _target in entries
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
        return cls(tuple(entries), track_base, ensemble_member_prefix)

    @property
    def destinations(self) -> tuple[str, ...]:
        return tuple(target for _source, target in self.entries)

    def remap(self, index: int) -> tuple[tuple[str, str], ...]:
        return remap_entries(
            self.entries,
            self.destinations,
            self.track_base or "",
            index,
            ensemble_member_prefix=self.ensemble_member_prefix,
        )


def remap_entries(
    entries: Sequence[tuple[str, str]],
    destinations: Sequence[str],
    track_base: str,
    index: int,
    *,
    ensemble_member_prefix: str | None = None,
) -> tuple[tuple[str, str], ...]:
    dest_by_name = {os.path.basename(path): path for path in destinations}
    remapped = []
    for source, target in entries:
        original = dest_by_name.get(os.path.basename(source))
        base_path = original if original is not None else target
        remapped.append(
            (
                source,
                _with_unit_suffix(
                    base_path, track_base, index, ensemble_member_prefix=ensemble_member_prefix
                ),
            )
        )
    return tuple(remapped)


@dataclass(frozen=True, slots=True)
class PromotionCandidate:
    """One suffix attempt and the targets capable of advancing as a unit."""

    entries: tuple[tuple[str, str], ...]
    rewritten_targets: tuple[str, ...]
    progressable_sources: frozenset[str]


def suffix_candidate(plan: PromotionPlan, index: int) -> PromotionCandidate:
    entries = plan.remap(index)
    next_by_source = dict(plan.remap(index + 1))
    rewritten = tuple(
        _with_unit_suffix(
            path, plan.track_base or "", index, ensemble_member_prefix=plan.ensemble_member_prefix
        )
        for path in plan.destinations
    )
    return PromotionCandidate(
        entries,
        tuple(
            target
            for original, target in zip(plan.destinations, rewritten, strict=True)
            if original != target
        ),
        frozenset(source for source, target in entries if next_by_source.get(source) != target),
    )
