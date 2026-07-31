"""Typed stem identity for ensemble eligibility, export, and settings.

Layers:

- :class:`StemId` — model/yaml dict key (preserve author casing for lookup).
- :class:`StemBucket` — filename-safe ensemble/eligibility identity.
- :class:`StemLiteral` — specialty stem kept as its own combine key.
- :class:`EnsemblePair` — persisted user request (stable machine ids only).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping, Optional, Sequence, Tuple, Union

from bundled.constants import (
    BACKING_VOCALS_TAG,
    BASS_STEM,
    DRUM_STEM,
    FOUR_STEM_ENSEMBLE,
    GUITAR_STEM,
    INST_STEM,
    INST_WITH_BACKING_VOCALS_STEM,
    INST_WITH_BACKING_VOCALS_TAG,
    INST_WITH_LEAD_VOCALS_STEM,
    INST_WITH_LEAD_VOCALS_TAG,
    LEAD_VOCAL_STEM_LABEL,
    LEAD_VOCALS_TAG,
    MULTI_STEM_ENSEMBLE,
    NO_BASS_STEM,
    NO_DRUM_STEM,
    NO_OTHER_STEM,
    OTHER_STEM,
    PIANO_STEM,
    VOCAL_STEM,
)


class StemBucket(str, Enum):
    """Filename-safe combine / eligibility identity."""

    VOCALS = VOCAL_STEM
    INSTRUMENTAL = INST_STEM
    OTHER = OTHER_STEM
    DRUMS = DRUM_STEM
    BASS = BASS_STEM
    GUITAR = GUITAR_STEM
    PIANO = PIANO_STEM
    LEAD_VOCALS = LEAD_VOCALS_TAG
    BACKING_VOCALS = BACKING_VOCALS_TAG
    INST_WITH_BV = INST_WITH_BACKING_VOCALS_TAG
    INST_WITH_LEAD = INST_WITH_LEAD_VOCALS_TAG
    UNKNOWN = "Unknown"


@dataclass(frozen=True)
class StemLiteral:
    """Non-bucket specialty stem kept as its own combine/export key."""

    tag: str


StemKey = Union[StemBucket, StemLiteral]


@dataclass(frozen=True)
class StemId:
    """Opaque model-output key. ``raw`` keeps yaml casing for dict lookup."""

    raw: str

    def casefold(self) -> str:
        return str(self.raw or "").strip().casefold()

    def matches(self, other: str | StemId) -> bool:
        if isinstance(other, StemId):
            return self.casefold() == other.casefold()
        return self.casefold() == str(other or "").strip().casefold()

    def __str__(self) -> str:
        return self.raw


class EnsemblePair(str, Enum):
    """Persisted ensemble main-stem request (stable ids, not UI labels)."""

    CHOOSE = "choose"
    VOCALS_INSTRUMENTAL = "vocals_instrumental"
    KARAOKE = "karaoke"
    OTHER = "other"
    DRUMS = "drums"
    BASS = "bass"
    FOUR_STEM = "four_stem"
    MULTI_STEM = "multi_stem"

    def buckets(self) -> Tuple[StemBucket, StemBucket]:
        """Return ``(primary, secondary)`` buckets for this pair request.

        Complement pairs use :attr:`StemBucket.UNKNOWN` as secondary (discard).
        Non-pair modes return ``(UNKNOWN, UNKNOWN)``.
        """
        table = {
            EnsemblePair.VOCALS_INSTRUMENTAL: (
                StemBucket.VOCALS,
                StemBucket.INSTRUMENTAL,
            ),
            EnsemblePair.KARAOKE: (
                StemBucket.LEAD_VOCALS,
                StemBucket.INST_WITH_BV,
            ),
            EnsemblePair.OTHER: (StemBucket.OTHER, StemBucket.UNKNOWN),
            EnsemblePair.DRUMS: (StemBucket.DRUMS, StemBucket.UNKNOWN),
            EnsemblePair.BASS: (StemBucket.BASS, StemBucket.UNKNOWN),
        }
        return table.get(self, (StemBucket.UNKNOWN, StemBucket.UNKNOWN))

    def is_multi_or_four(self) -> bool:
        return self in (EnsemblePair.FOUR_STEM, EnsemblePair.MULTI_STEM)

    def stem_halves(self) -> Tuple[str, str]:
        """UI / stem-only label halves (not filename combine tags).

        Complement pairs keep the historic ``No Other`` / ``No Drums`` /
        ``No Bass`` secondary labels. Non-pair modes return ``("", "")``.
        """
        table = {
            EnsemblePair.VOCALS_INSTRUMENTAL: (VOCAL_STEM, INST_STEM),
            EnsemblePair.KARAOKE: (
                LEAD_VOCAL_STEM_LABEL,
                INST_WITH_BACKING_VOCALS_STEM,
            ),
            EnsemblePair.OTHER: (OTHER_STEM, NO_OTHER_STEM),
            EnsemblePair.DRUMS: (DRUM_STEM, NO_DRUM_STEM),
            EnsemblePair.BASS: (BASS_STEM, NO_BASS_STEM),
        }
        return table.get(self, ("", ""))


_PAIR_UI_LABELS = {
    EnsemblePair.CHOOSE: "Choose Stem Pair",
    EnsemblePair.VOCALS_INSTRUMENTAL: f"{VOCAL_STEM}/{INST_STEM}",
    EnsemblePair.KARAOKE: f"{LEAD_VOCAL_STEM_LABEL}/{INST_WITH_BACKING_VOCALS_STEM}",
    EnsemblePair.OTHER: f"{OTHER_STEM}/No Other",
    EnsemblePair.DRUMS: f"{DRUM_STEM}/No Drums",
    EnsemblePair.BASS: f"{BASS_STEM}/No Bass",
    EnsemblePair.FOUR_STEM: FOUR_STEM_ENSEMBLE,
    EnsemblePair.MULTI_STEM: MULTI_STEM_ENSEMBLE,
}

_BUCKET_UI_LABELS = {
    StemBucket.LEAD_VOCALS: LEAD_VOCAL_STEM_LABEL,
    StemBucket.BACKING_VOCALS: "Backing Vocals",
    StemBucket.INST_WITH_BV: INST_WITH_BACKING_VOCALS_STEM,
    StemBucket.INST_WITH_LEAD: INST_WITH_LEAD_VOCALS_STEM,
}

_IDENTITY_BUCKETS = {
    "lead_only": StemBucket.LEAD_VOCALS,
    "lead vocals": StemBucket.LEAD_VOCALS,
    "backing_only": StemBucket.BACKING_VOCALS,
    "backing vocals": StemBucket.BACKING_VOCALS,
}

_VOCAL_TOKENS = frozenset({"vocals", "vocal", "voc"})
_INSTRUMENTAL_TOKENS = frozenset({"instrumental", "inst", "instrument"})
_SIMPLE_STEM_TOKENS = {
    "drums": StemBucket.DRUMS,
    "bass": StemBucket.BASS,
    "guitar": StemBucket.GUITAR,
    "piano": StemBucket.PIANO,
}


def coerce_ensemble_pair(value: Any) -> EnsemblePair:
    """Accept only :class:`EnsemblePair` ids; unknown → ``CHOOSE``.

    Legacy display strings (``Vocals/Instrumental``, …) are **not** migrated.
    """
    if isinstance(value, EnsemblePair):
        return value
    if isinstance(value, str):
        try:
            return EnsemblePair(value.strip())
        except ValueError:
            pass
    if value not in (None, ""):
        try:
            from core.debug_log import debug

            debug(
                "settings",
                f"ensemble.main_stem unknown value={value!r}; using choose",
            )
        except Exception:
            pass
    return EnsemblePair.CHOOSE


def ui_label(value: EnsemblePair | StemBucket | StemLiteral | str) -> str:
    """Human-readable label for UI; never use for filenames or settings ids."""
    if isinstance(value, EnsemblePair):
        return _PAIR_UI_LABELS[value]
    if isinstance(value, StemBucket):
        return _BUCKET_UI_LABELS.get(value, value.value)
    if isinstance(value, StemLiteral):
        return value.tag
    return str(value)


def filename_tag(key: StemKey) -> str:
    """Filename/RAM combine tag. ``UNKNOWN`` is not exportable."""
    if isinstance(key, StemBucket):
        if key is StemBucket.UNKNOWN:
            raise ValueError("StemBucket.UNKNOWN is not exportable")
        return key.value
    return key.tag


def bucket_for_model_stem(
    stem: str | StemId,
    *,
    stem_count: int = 2,
    is_karaoke: bool = False,
    is_bv: bool = False,
) -> StemBucket:
    """Map a model stem id to an ensemble bucket (may be ``UNKNOWN``)."""
    raw = stem.raw if isinstance(stem, StemId) else stem
    token = str(raw or "").strip().casefold()
    if not token:
        return StemBucket.UNKNOWN

    identity = _IDENTITY_BUCKETS.get(token)
    if identity is not None:
        return identity

    is_vocal = token in _VOCAL_TOKENS
    is_instrumental = token in _INSTRUMENTAL_TOKENS or (
        token == "other" and 1 <= stem_count <= 2
    )

    if is_karaoke:
        if is_vocal:
            return StemBucket.LEAD_VOCALS
        if is_instrumental:
            return StemBucket.INST_WITH_BV
    if is_bv:
        if is_vocal:
            return StemBucket.BACKING_VOCALS
        if is_instrumental:
            return StemBucket.INST_WITH_LEAD

    if is_vocal:
        return StemBucket.VOCALS
    if is_instrumental:
        return StemBucket.INSTRUMENTAL
    if token == "other":
        return StemBucket.OTHER
    simple = _SIMPLE_STEM_TOKENS.get(token)
    if simple is not None:
        return simple
    return StemBucket.UNKNOWN


def model_stem_count(model: Any) -> int:
    """How many stems a model produces across MDX/Demucs fields.

    Returns ``0`` when nothing is known (do not guess 2).
    """
    counts = (
        int(getattr(model, "mdx_stem_count", 0) or 0),
        int(getattr(model, "demucs_stem_count", 0) or 0),
        len(getattr(model, "mdx_model_stems", ()) or ()),
        len(getattr(model, "demucs_source_list", ()) or ()),
    )
    return max(counts)


def export_stem_key(
    model: Any,
    stem: str | StemId,
    *,
    for_ensemble: bool = False,
) -> StemKey | str:
    """Return the export/combine key for ``stem``.

    Ensemble mode returns :class:`StemKey`. Outside ensemble, returns a string
    label (karaoke/BV human names or the raw stem).
    """
    from bundled.constants import (
        BV_VOCAL_STEM,
        BV_VOCAL_STEM_LABEL,
        LEAD_VOCAL_STEM,
        LEAD_VOCAL_STEM_LABEL,
    )
    from core.model_stem_semantics import (
        canonical_ensemble_stem_tag,
        karaoke_bv_export_labels,
    )

    raw = stem.raw if isinstance(stem, StemId) else stem
    if not raw:
        return raw
    if for_ensemble:
        bucket = bucket_for_model_stem(
            raw,
            stem_count=model_stem_count(model),
            is_karaoke=bool(getattr(model, "is_karaoke", False)),
            is_bv=bool(getattr(model, "is_bv_model", False)),
        )
        if bucket is not StemBucket.UNKNOWN:
            return bucket
        return StemLiteral(canonical_ensemble_stem_tag(str(raw)))
    if raw == LEAD_VOCAL_STEM:
        return LEAD_VOCAL_STEM_LABEL
    if raw == BV_VOCAL_STEM:
        return BV_VOCAL_STEM_LABEL
    labels = karaoke_bv_export_labels(model)
    if not labels:
        return raw
    return labels.get(raw, raw)


def export_stem_label(model: Any, stem: str, *, for_ensemble: bool = False) -> str:
    """String form of :func:`export_stem_key` for filenames and tests."""
    key = export_stem_key(model, stem, for_ensemble=for_ensemble)
    if isinstance(key, (StemBucket, StemLiteral)):
        return filename_tag(key)
    return str(key)


def resolve_in_sources(
    sources: Optional[Mapping[str, Any]], stem: str | StemId
) -> Optional[str]:
    """Return the key in ``sources`` matching ``stem`` (case/alias insensitive)."""
    from core.model_stem_semantics import canonical_ensemble_stem_tag

    if not isinstance(sources, Mapping):
        return None
    raw = stem.raw if isinstance(stem, StemId) else stem
    if raw is None or raw == "":
        return None
    if raw in sources:
        return str(raw)
    want = str(raw).casefold()
    for key in sources:
        if str(key).casefold() == want:
            return str(key)
    want_canon = canonical_ensemble_stem_tag(str(raw))
    for key in sources:
        if canonical_ensemble_stem_tag(str(key)) == want_canon:
            return str(key)
    return None


def ensemble_pair_choices() -> Sequence[tuple[str, str]]:
    """``(stored_id, display_label)`` pairs for the ensemble main-stem combo."""
    return tuple((pair.value, ui_label(pair)) for pair in EnsemblePair)
