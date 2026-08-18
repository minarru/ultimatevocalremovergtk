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
    "backing_vocal": StemBucket.BACKING_VOCALS,
    "backing_vocals": StemBucket.BACKING_VOCALS,
}

_VOCAL_FAMILY = {
    StemBucket.VOCALS,
    StemBucket.LEAD_VOCALS,
    StemBucket.BACKING_VOCALS,
}
_INST_FAMILY = {
    StemBucket.INSTRUMENTAL,
    StemBucket.INST_WITH_BV,
    StemBucket.INST_WITH_LEAD,
}

# Canonical label -> bucket enum for the plain single-instrument stems.
# Alias spellings (vocals/voc/drums/...) live in the shared
# core.model_stem_semantics table bucket_for_model_stem now queries via
# canonical_stem_alias; this dict only maps already-canonical labels to
# their bucket, it is not alias data.
_SIMPLE_STEM_BUCKETS = {
    DRUM_STEM: StemBucket.DRUMS,
    BASS_STEM: StemBucket.BASS,
    GUITAR_STEM: StemBucket.GUITAR,
    PIANO_STEM: StemBucket.PIANO,
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
    stem_count: int,
    is_karaoke: bool = False,
    is_bv: bool = False,
    is_vocal_split: bool = False,
) -> StemBucket:
    """Map a model stem id to an ensemble bucket (may be ``UNKNOWN``).

    ``stem_count`` is **required**: native ``other`` means the instrumental
    side on a 2-stem model and the MUSDB residual on a 4-stem one, so a
    defaulted count silently mis-resolves it. With a model in hand, prefer
    :func:`stem_concept`, which derives the whole context from the model.

    ``is_vocal_split`` is the karaoke/BV *splitter role*, not karaoke-as-primary.
    A splitter's instrumental complement is Backing Vocals (or Lead Vocals when
    the splitter is a BV model), never Inst-with-BGV.
    """
    from core.model_stem_semantics import canonical_stem_alias

    raw = stem.raw if isinstance(stem, StemId) else stem
    token = str(raw or "").strip().casefold()
    if not token:
        return StemBucket.UNKNOWN

    identity = _IDENTITY_BUCKETS.get(token)
    if identity is not None:
        return identity

    canonical = canonical_stem_alias(token)
    is_vocal = canonical == VOCAL_STEM
    is_instrumental = canonical == INST_STEM or (
        token == "other" and 1 <= stem_count <= 2
    )

    if is_vocal_split:
        if is_vocal:
            return StemBucket.BACKING_VOCALS if is_bv else StemBucket.LEAD_VOCALS
        if is_instrumental:
            return StemBucket.LEAD_VOCALS if is_bv else StemBucket.BACKING_VOCALS

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
    simple = _SIMPLE_STEM_BUCKETS.get(canonical) if canonical else None
    if simple is not None:
        return simple
    return StemBucket.UNKNOWN


def concept_is(
    stem: str | StemId,
    bucket: StemBucket,
    *,
    stem_count: int,
    is_karaoke: bool = False,
    is_bv: bool = False,
    is_vocal_split: bool = False,
) -> bool:
    """True when ``stem`` resolves to ``bucket`` under the given run context."""
    return (
        bucket_for_model_stem(
            stem,
            stem_count=stem_count,
            is_karaoke=is_karaoke,
            is_bv=is_bv,
            is_vocal_split=is_vocal_split,
        )
        is bucket
    )


def focus_matches_stem(
    focus: str,
    stem: str | StemId | None,
    *,
    stem_count: int,
    is_karaoke: bool = False,
    is_bv: bool = False,
    is_vocal_split: bool = False,
) -> bool:
    """True when a persisted ``process.stem_focus`` names this native stem.

    Accepts bucket tags (``Vocals``, ``Lead_Vocals``), UI labels, yaml
    aliases (``vocals``), and ``raw:`` specialty anchors.
    """
    if not focus or stem is None:
        return False
    raw = stem.raw if isinstance(stem, StemId) else str(stem)
    token = raw.strip()
    if not token:
        return False
    want = str(focus).strip()
    if not want:
        return False
    if want.startswith("raw:"):
        return want == f"raw:{token.casefold()}"

    ctx = {
        "stem_count": stem_count,
        "is_karaoke": is_karaoke,
        "is_bv": is_bv,
        "is_vocal_split": is_vocal_split,
    }
    stem_bucket = bucket_for_model_stem(token, **ctx)
    if stem_bucket is StemBucket.UNKNOWN:
        return False
    if stem_bucket.value == want or ui_label(stem_bucket) == want:
        return True
    # CLI ``--stems vocals`` stores the plain Vocals bucket; karaoke remaps
    # the same native key to Lead Vocals. Match the un-remapped family too,
    # including already-remapped labels (``Lead Vocals``), not only native keys.
    focus_as_stem = bucket_for_model_stem(want, stem_count=stem_count)
    if focus_as_stem is StemBucket.UNKNOWN:
        return False
    return _plain_family(stem_bucket) is _plain_family(focus_as_stem)


def exclusive_flags_for_focus(
    focus: str,
    *,
    primary_stem: str | None,
    secondary_stem: str | None,
    stem_count: int,
    is_karaoke: bool = False,
    is_bv: bool = False,
) -> tuple[bool, bool] | None:
    """Return ``(primary_only, secondary_only)``, or ``None`` if focus is empty.

    A focus that names neither stem — or both — yields ``(False, False)``:
    export everything rather than guess. Callers that can warn should ask
    :func:`focus_is_resolvable` first.
    """
    if not str(focus or "").strip():
        return None
    ctx = {
        "stem_count": stem_count,
        "is_karaoke": is_karaoke,
        "is_bv": is_bv,
    }
    primary_hit = focus_matches_stem(focus, primary_stem, **ctx)
    secondary_hit = focus_matches_stem(focus, secondary_stem, **ctx)
    if primary_hit and not secondary_hit:
        return True, False
    if secondary_hit and not primary_hit:
        return False, True
    return False, False


def _plain_family(bucket: StemBucket) -> StemBucket:
    """Collapse karaoke/BV remaps onto the Vocals / Instrumental family."""
    if bucket in _VOCAL_FAMILY:
        return StemBucket.VOCALS
    if bucket in _INST_FAMILY:
        return StemBucket.INSTRUMENTAL
    return bucket


def exclusive_flags_for_pair(
    focus: str, pair: EnsemblePair
) -> tuple[bool, bool] | None:
    """Like :func:`exclusive_flags_for_focus`, keyed on pair buckets.

    Ensemble combine and dry-run never have a model: they have an
    :class:`EnsemblePair`. Matching the pair's *labels* (``Lead Vocals``,
    ``Other``) through :func:`exclusive_flags_for_focus` is wrong — those
    strings are already concepts, and ``stem_count=2`` would turn Other
    into Instrumental and leave ``--stems vocals`` unmatched on karaoke.
    """
    if not str(focus or "").strip():
        return None
    wanted = focus_bucket(focus)
    primary_b, secondary_b = pair.buckets()

    def hit(bucket: StemBucket) -> bool:
        if bucket is StemBucket.UNKNOWN or wanted is StemBucket.UNKNOWN:
            return False
        if bucket is wanted:
            return True
        return _plain_family(bucket) is _plain_family(wanted)

    primary_hit = hit(primary_b)
    secondary_hit = hit(secondary_b)
    if primary_hit and not secondary_hit:
        return True, False
    if secondary_hit and not primary_hit:
        return False, True
    return False, False


def exclusive_flags_for_model(model: Any, focus: str) -> tuple[bool, bool] | None:
    """:func:`exclusive_flags_for_focus` with the context read off ``model``."""
    return exclusive_flags_for_focus(
        focus,
        primary_stem=getattr(model, "primary_stem", None),
        secondary_stem=getattr(model, "secondary_stem", None),
        stem_count=model_stem_count(model),
        is_karaoke=bool(getattr(model, "is_karaoke", False)),
        is_bv=bool(getattr(model, "is_bv_model", False)),
    )


def focus_is_resolvable(model: Any, focus: str) -> bool:
    """True when ``focus`` is empty or names exactly one of the model's stems.

    False means the exclusive pick cannot be honored and the run will fall
    back to exporting every stem — the condition worth reporting at plan time.
    """
    flags = exclusive_flags_for_model(model, focus)
    return flags is None or flags != (False, False)


def focus_bucket(token: str) -> StemBucket:
    """Resolve a *focus* token to its bucket, independent of any model.

    Unlike :func:`bucket_for_model_stem` this never reinterprets ``other`` as
    the instrumental side: as a user-typed pick, ``other`` means the Other
    stem. Cross-spelling matching against a 2-stem model's native ``other``
    still happens later, in :func:`focus_matches_stem`.
    """
    from core.model_stem_semantics import canonical_stem_alias

    folded = token.casefold()
    identity = _IDENTITY_BUCKETS.get(folded)
    if identity is not None:
        return identity
    for member in StemBucket:
        if member is StemBucket.UNKNOWN:
            continue
        if folded in (member.value.casefold(), ui_label(member).casefold()):
            return member
    canonical = canonical_stem_alias(folded)
    if canonical == VOCAL_STEM:
        return StemBucket.VOCALS
    if canonical == INST_STEM:
        return StemBucket.INSTRUMENTAL
    if folded == "other" or canonical == OTHER_STEM:
        return StemBucket.OTHER
    simple = _SIMPLE_STEM_BUCKETS.get(canonical) if canonical else None
    return simple if simple is not None else StemBucket.UNKNOWN


def normalize_stem_focus(value: Any, *, strict: bool = False) -> str:
    """Canonical ``process.stem_focus``: bucket tag, ``raw:…``, or empty.

    Accepts aliases (``vocals`` ≡ ``Vocals``) so CLI ``--set`` and GTK persist
    the same exclusive-pick vocabulary. A specialty stem must be named
    explicitly as ``raw:<stem>``; a bare unrecognized token is a typo, not a
    silent specialty pick. ``strict`` raises on one, matching ``--set``
    validation; the permissive default drops it so a hand-edited
    ``settings.json`` degrades to "export everything" instead of failing load.
    """
    token = "" if value is None else str(value).strip()
    if not token:
        return ""
    if token.startswith("raw:"):
        rest = token[4:].strip()
        if rest:
            return f"raw:{rest.casefold()}"
        if strict:
            raise ValueError("stem focus 'raw:' needs a stem name after the prefix")
        return ""
    bucket = focus_bucket(token)
    if bucket is not StemBucket.UNKNOWN:
        return bucket.value
    if strict:
        known = ", ".join(
            sorted(member.value for member in StemBucket if member is not StemBucket.UNKNOWN)
        )
        raise ValueError(
            f"unknown stem focus {token!r}; expected one of {known}, "
            f"or 'raw:{token.casefold()}' for a specialty stem"
        )
    try:
        from core.debug_log import debug

        debug("settings", f"process.stem_focus unknown value={token!r}; using all stems")
    except Exception:
        pass
    return ""


def stem_context(model: Any) -> dict[str, Any]:
    """Resolver context read off a model, for ``**``-splatting into the helpers.

    The single derivation point for ``stem_count``/``is_karaoke``/``is_bv``/
    ``is_vocal_split``. Build context this way rather than by hand, so a call
    site cannot quietly omit one and get a different concept.
    """
    return {
        "stem_count": model_stem_count(model),
        "is_karaoke": bool(getattr(model, "is_karaoke", False)),
        "is_bv": bool(getattr(model, "is_bv_model", False)),
        "is_vocal_split": bool(getattr(model, "is_vocal_split_model", False)),
    }


def stem_concept(
    model: Any,
    stem: str | StemId | None = None,
) -> StemBucket:
    """Concept for ``stem``, or the model's native primary when omitted."""
    raw = stem if stem is not None else getattr(model, "primary_stem", None)
    return bucket_for_model_stem(raw or "", **stem_context(model))


def model_stem_count(model: Any) -> int:
    """How many stems a model produces across MDX/Demucs fields.

    Returns ``0`` when nothing is known (do not guess 2).
    """
    def _count(value: Any) -> int:
        try:
            return int(value or 0)
        except (TypeError, ValueError):
            return 0

    def _len(value: Any) -> int:
        try:
            return len(value or ())
        except TypeError:
            return 0

    counts = (
        _count(getattr(model, "mdx_stem_count", 0)),
        _count(getattr(model, "demucs_stem_count", 0)),
        _len(getattr(model, "mdx_model_stems", ())),
        _len(getattr(model, "demucs_source_list", ())),
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
    from core.model_stem_semantics import (
        canonical_ensemble_stem_tag,
        karaoke_bv_export_labels,
    )

    raw = stem.raw if isinstance(stem, StemId) else stem
    if not raw:
        return raw
    bucket = bucket_for_model_stem(raw, **stem_context(model))
    if for_ensemble:
        if bucket is not StemBucket.UNKNOWN:
            return bucket
        return StemLiteral(canonical_ensemble_stem_tag(str(raw)))
    if bucket is not StemBucket.UNKNOWN:
        return ui_label(bucket)
    labels = karaoke_bv_export_labels(model)
    if not labels:
        return raw
    matched = resolve_in_sources(labels, raw)
    if matched is not None:
        return labels[matched]
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
    if not raw:
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
