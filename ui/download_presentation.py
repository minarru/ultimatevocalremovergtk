"""Download Center presentation, without GTK or changes to download identity."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any

from core.model_inventory import mdx_kind_from_names
from core.model_scores import (
    PURPOSE_FX,
    PURPOSE_INSTRUMENTAL,
    PURPOSE_KARAOKE,
    PURPOSE_REMOVAL,
    PURPOSE_RESTORE,
    PURPOSE_STEMS,
    PURPOSE_VOCALS,
)
from core.stems import StemBucket, bucket_for_model_stem

ARCHITECTURES = (
    ('all', 'All architectures'),
    ('vr', 'VR'),
    ('classic_onnx', 'Classic MDX'),
    ('mdx23c', 'MDX23C'),
    ('mel_band_roformer', 'Mel-Band Roformer'),
    ('bs_roformer', 'BS-Roformer'),
    ('bs_polarformer', 'BS-PolarFormer'),
    ('scnet', 'SCNet'),
    ('bandit', 'Bandit'),
    ('demucs', 'Demucs'),
    ('apollo', 'Apollo'),
    ('unknown', 'Other architectures'),
)
ARCHITECTURE_LABELS = dict(ARCHITECTURES)
PURPOSE_DESCRIPTIONS = {
    PURPOSE_VOCALS: 'Isolate vocals from the instrumental accompaniment.',
    PURPOSE_INSTRUMENTAL: 'Isolate instrumental accompaniment from vocals.',
    PURPOSE_KARAOKE: 'Separate lead and backing vocals for karaoke mixes.',
    PURPOSE_STEMS: 'Separate instruments such as drums, bass, and guitar.',
    PURPOSE_FX: 'Separate dialogue, sound effects, and other cinematic sounds.',
    PURPOSE_REMOVAL: 'Remove noise, echo, reverb, and other unwanted sounds.',
    PURPOSE_RESTORE: 'Improve audio quality and reduce compression artifacts.',
}
SEARCH_LABELS = (
    'Search vocal models',
    'Search instrumental models',
    'Search karaoke models',
    'Search stem models',
    'Search FX models',
    'Search removal models',
    'Search restoration models',
)


def architecture_for(
    family: str | None, files: Sequence[str], name: str, display: str
) -> tuple[str, str]:
    if family in {'vr', 'demucs', 'apollo'}:
        return family, 'Catalogue family'
    if family != 'mdx':
        return 'unknown', ''
    if display.casefold().startswith('bandsplit polarformer'):
        return 'bs_polarformer', 'Catalogue name'
    kind = mdx_kind_from_names(files)
    source = 'Local configuration or model filenames'
    if kind is None:
        kind = mdx_kind_from_names(files, labels=(name, display))
        source = 'Catalogue name'
    kind = {'scnet_masked': 'scnet', 'scnet_tran': 'scnet', 'bandit_v2': 'bandit'}.get(
        kind or '', kind
    )
    return (kind, source) if kind in ARCHITECTURE_LABELS else ('unknown', '')


def purpose_score(scores: Mapping[str, float], purpose: str, stem_count: int) -> float | None:
    if purpose not in (PURPOSE_VOCALS, PURPOSE_INSTRUMENTAL):
        return None
    target = StemBucket.VOCALS if purpose == PURPOSE_VOCALS else StemBucket.INSTRUMENTAL
    values = []
    for name, value in scores.items():
        if bucket_for_model_stem(name, stem_count=stem_count) == target:
            if not math.isfinite(value):
                return None
            values.append(float(value))
    return values[0] if values and len(set(values)) == 1 else None


def output_summary(meta: Any) -> str:
    projection = getattr(meta, 'stem_semantics', None)
    evidence = getattr(meta, 'catalogue_evidence_status', 'unavailable')
    evidence = str(getattr(evidence, 'value', evidence))
    if getattr(projection, 'status', '') == 'reviewed' and evidence in {'ready', 'stale'}:
        outputs = list(dict.fromkeys(route.display for route in getattr(projection, "routes", ())))
        if outputs:
            return ', '.join(outputs)
    if evidence == 'pending':
        return 'Loading output details…'
    if evidence == 'not_applicable':
        return 'Restoration'
    stems = list(dict.fromkeys(getattr(meta, 'stems', ()) or ()))
    return 'Raw outputs: ' + ', '.join(stems) if stems else 'Output details unavailable'


def compare_models(
    left: str,
    x: float | None,
    unsupported_left: bool,
    right: str,
    y: float | None,
    unsupported_right: bool,
    by_score: bool,
    descending: bool,
) -> int:
    if unsupported_left != unsupported_right:
        return 1 if unsupported_left else -1
    if by_score and not unsupported_left:
        if (x is None) != (y is None):
            return 1 if x is None else -1
        if x is not None and y is not None and x != y:
            return ((x > y) - (x < y)) * (-1 if descending else 1)
    a, b = left.casefold(), right.casefold()
    result = (a > b) - (a < b)
    return -result if descending and not by_score else result
