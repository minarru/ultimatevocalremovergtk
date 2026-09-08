"""Installed model presentation and filtering; no GTK or repository mutations."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from functools import cmp_to_key
from typing import Any

from core.model_identity import ModelRecord
from core.model_scores import purpose_pages_for_label, purpose_roles_from_meta, sdr_for_files

from .download_presentation import (
    ARCHITECTURE_LABELS,
    architecture_for,
    compare_models,
    output_summary,
    purpose_score,
)


@dataclass(frozen=True)
class PickerFilters:
    query: str = ''
    purpose: str = 'all'
    architecture: str = 'all'
    supported_only: bool = True
    by_score: bool = False
    descending: bool = False


@dataclass(frozen=True)
class PickerModel:
    record: ModelRecord
    architecture: str
    outputs: str
    purposes: frozenset[str]
    scores: Mapping[str, float]
    stem_count: int
    reason: str | None

    @property
    def id(self) -> str:
        return self.record.id

    def score(self, purpose: str) -> float | None:
        return purpose_score(self.scores, purpose, self.stem_count)

    def subtitle(self, purpose: str) -> str:
        text = self.outputs
        if purpose in ('vocals', 'instrumental'):
            score = self.score(purpose)
            text += ' · ' + (f'{score:.2f} dB SDR' if score is not None else 'SDR unavailable')
        return text + (' · Unsupported' if self.reason else '')


def project_installed(
    records: Iterable[ModelRecord],
    snapshot: Any,
    scores: Mapping[str, Mapping[str, float]],
) -> tuple[PickerModel, ...]:
    result = []
    scoped = getattr(snapshot, 'meta_by_family', {})
    unsupported = getattr(snapshot, 'unsupported', {})
    for record in records:
        if not record.installed or record.family not in {'vr', 'mdx', 'demucs'}:
            continue
        ref = record.catalogue_entry
        meta = scoped.get(ref.family, {}).get(ref.selection) if ref else None
        files = (record.artifacts.primary_filename, *record.artifacts.supporting_filenames)
        architecture, _ = architecture_for(record.family, files, record.basename, record.display)
        # Runtime identity knows the local architecture even without catalogue labels.
        if record.mdx and architecture == 'unknown':
            kind = record.mdx.kind
            architecture = {
                'scnet_masked': 'scnet',
                'scnet_tran': 'scnet',
                'bandit_v2': 'bandit',
            }.get(kind, kind)
        reason = (
            None
            if record.identity_complete
            else (record.identity_error or 'Incomplete model identity')
        )
        if ref:
            reason = reason or dict(unsupported.get(record.arch, ())).get(ref.selection)
        primary, outputs = purpose_roles_from_meta(meta)
        projection = getattr(meta, 'stem_semantics', None)
        intent = getattr(projection, 'intent', None) or getattr(meta, 'intent', None)
        purposes = purpose_pages_for_label(
            record.display,
            intent=intent,
            arch=record.arch,
            primary_role=primary,
            output_roles=outputs,
        )
        result.append(
            PickerModel(
                record,
                architecture,
                output_summary(meta),
                purposes,
                sdr_for_files(files, scores),
                len(getattr(meta, 'stems', ()) or ()) or 2,
                reason,
            )
        )
    return tuple(result)


def visible_models(models: Iterable[PickerModel], filters: PickerFilters) -> list[PickerModel]:
    query = filters.query.strip().casefold()
    result = [
        model
        for model in models
        if (not filters.supported_only or not model.reason)
        and (filters.purpose == 'all' or filters.purpose in model.purposes)
        and (filters.architecture == 'all' or filters.architecture == model.architecture)
        and query
        in ' '.join(
            (
                model.record.display,
                model.record.basename,
                model.outputs,
                ARCHITECTURE_LABELS.get(model.architecture, model.architecture),
            )
        ).casefold()
    ]

    def compare(left: PickerModel, right: PickerModel) -> int:
        return compare_models(
            left.record.display,
            left.score(filters.purpose),
            bool(left.reason),
            right.record.display,
            right.score(filters.purpose),
            bool(right.reason),
            filters.by_score and filters.purpose in ('vocals', 'instrumental'),
            filters.descending,
        )

    return sorted(result, key=cmp_to_key(compare))
