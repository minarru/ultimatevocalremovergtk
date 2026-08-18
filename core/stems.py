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
    BV_VOCAL_STEM,
    BV_VOCAL_STEM_LABEL,
    DRUM_STEM,
    FOUR_STEM_ENSEMBLE,
    GUITAR_STEM,
    INST_STEM,
    INST_WITH_BACKING_VOCALS_STEM,
    INST_WITH_BACKING_VOCALS_TAG,
    INST_WITH_LEAD_VOCALS_STEM,
    INST_WITH_LEAD_VOCALS_TAG,
    LEAD_VOCAL_STEM,
    LEAD_VOCAL_STEM_LABEL,
    LEAD_VOCALS_TAG,
    MULTI_STEM_ENSEMBLE,
    NO_BASS_STEM,
    NO_DRUM_STEM,
    NO_GUITAR_STEM,
    NO_OTHER_STEM,
    NO_PIANO_STEM,
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


class StemRouteKind(str, Enum):
    """How an export route is produced."""

    NATIVE = "native"
    DERIVED = "derived"
    SPLITTER = "splitter"
    SPECIALTY = "specialty"


class StemSelectionStatus(str, Enum):
    """Result of resolving one stem-focus request."""

    EMPTY = "empty"
    MATCHED = "matched"
    UNMATCHED = "unmatched"
    INSUFFICIENT_MEMBERS = "insufficient_members"


@dataclass(frozen=True)
class StemRoute:
    """One canonical, exportable model or ensemble output.

    ``native`` preserves the model/yaml key used to address source arrays.
    ``concept`` is the stable selection identity (a bucket value or
    ``raw:<casefolded-name>``). ``label`` is the standalone filename label and
    ``filename_tag`` is the canonical ensemble/capture tag.
    """

    native: Optional[StemId]
    concept: str
    label: str
    filename_tag: str
    kind: StemRouteKind = StemRouteKind.NATIVE
    conditional: bool = False
    selected_by_default: bool = True


@dataclass(frozen=True)
class StemSelection:
    """Canonical result of matching ``process.stem_focus`` to routes."""

    requested: str
    routes: Tuple[StemRoute, ...]
    status: StemSelectionStatus
    available: Tuple[str, ...]


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
# Alias spellings live in _STEM_NAME_ALIASES / canonical_stem_alias; this
# dict only maps already-canonical labels to their bucket.
_SIMPLE_STEM_BUCKETS = {
    DRUM_STEM: StemBucket.DRUMS,
    BASS_STEM: StemBucket.BASS,
    GUITAR_STEM: StemBucket.GUITAR,
    PIANO_STEM: StemBucket.PIANO,
}

# Raw-name -> canonical-stem lookup shared by UI display, ensemble
# bucketing, and stem-focus persistence anchoring. Only entries every
# consumer already agrees on (or a strict, verified addition) belong here.
# UI-only specialty names (speech/music/sfx/effects) and each consumer's
# own complement ("No X") handling stay separate -- see
# docs/superpowers/specs/2026-08-09-stem-export-semantics-design.md.
_STEM_NAME_ALIASES: dict[str, str] = {
    "vocals": VOCAL_STEM,
    "vocal": VOCAL_STEM,
    "voc": VOCAL_STEM,
    "instrumental": INST_STEM,
    "inst": INST_STEM,
    "instrument": INST_STEM,
    "other": OTHER_STEM,
    "bass": BASS_STEM,
    "drums": DRUM_STEM,
    "guitar": GUITAR_STEM,
    "piano": PIANO_STEM,
}


def canonical_stem_alias(name: Optional[str]) -> Optional[str]:
    """Shared raw-name -> canonical-stem lookup, casefolded.

    Single source of truth for UI display, ensemble bucketing, and
    stem-focus anchoring. Returns ``None`` for anything not in the shared
    core vocabulary -- callers layer their own purpose-specific handling
    (specialty names, complement stems, karaoke/BV identity codes) on top.
    """
    if not name:
        return None
    return _STEM_NAME_ALIASES.get(str(name).strip().casefold())


# Ensemble-only: complement ("No X") tags, matched as a whole lowercase
# string. Kept separate from _STEM_NAME_ALIASES -- unlike the UI's
# NO_STEM-prefix-then-suffix-lookup approach (ui/widgets/stem_only.py), this
# must match a raw, fully-lowercase yaml value directly. Verified: the UI's
# canonical_stem_name only recognizes an already-capitalized "No " prefix.
_ENSEMBLE_STEM_COMPLEMENTS: dict[str, str] = {
    "no other": NO_OTHER_STEM,
    "no bass": NO_BASS_STEM,
    "no drums": NO_DRUM_STEM,
    "no guitar": NO_GUITAR_STEM,
    "no piano": NO_PIANO_STEM,
}

_ENSEMBLE_STEM_PRESERVE = frozenset(
    {
        LEAD_VOCAL_STEM,
        BV_VOCAL_STEM,
        LEAD_VOCAL_STEM_LABEL,
        BV_VOCAL_STEM_LABEL,
        INST_WITH_LEAD_VOCALS_STEM,
        INST_WITH_BACKING_VOCALS_STEM,
        # Bucket tags written into ensemble member filenames. The combine stage
        # re-reads them from the filename, so they must survive unchanged.
        INST_WITH_BACKING_VOCALS_TAG,
        INST_WITH_LEAD_VOCALS_TAG,
        LEAD_VOCALS_TAG,
        BACKING_VOCALS_TAG,
    }
)

_ENSEMBLE_STEM_CANONICAL = frozenset(
    {
        VOCAL_STEM,
        INST_STEM,
        OTHER_STEM,
        BASS_STEM,
        DRUM_STEM,
        GUITAR_STEM,
        PIANO_STEM,
        NO_OTHER_STEM,
        NO_BASS_STEM,
        NO_DRUM_STEM,
        NO_GUITAR_STEM,
        NO_PIANO_STEM,
    }
)


def canonical_ensemble_stem_tag(stem: str) -> str:
    """Normalize a stem tag for multi-stem ensemble bucketing and filenames.

    Only folds well-known aliases (``vocals`` → ``Vocals``, ``drums`` →
    ``Drums``, …). Leaves karaoke/BV identity codes and specialty stems
    (Speech, Lead Vocals, Sfx, …) unchanged so they never merge with MUSDB
    stems by accident.
    """
    if not stem:
        return stem
    stripped = str(stem).strip()
    if not stripped:
        return stripped
    if stripped in _ENSEMBLE_STEM_PRESERVE:
        return stripped
    if stripped in _ENSEMBLE_STEM_CANONICAL:
        return stripped
    complement = _ENSEMBLE_STEM_COMPLEMENTS.get(stripped.casefold())
    if complement is not None:
        return complement
    aliased = canonical_stem_alias(stripped)
    if aliased is not None:
        return aliased
    # Title Case / odd casing of a known label (e.g. ``VOCALS`` → ``Vocals``).
    for label in _ENSEMBLE_STEM_CANONICAL:
        if label.casefold() == stripped.casefold():
            return label
    return stripped


def karaoke_bv_export_labels(model: Any) -> Optional[dict[str, str]]:
    """Vocals/Instrumental → human karaoke/BV export labels, or ``None``."""
    if model is None:
        return None
    is_bv = bool(getattr(model, "is_bv_model", False))
    is_karaoke = bool(getattr(model, "is_karaoke", False))
    if not is_bv and not is_karaoke:
        return None
    if is_bv:
        return {
            VOCAL_STEM: BV_VOCAL_STEM_LABEL,
            INST_STEM: INST_WITH_LEAD_VOCALS_STEM,
            LEAD_VOCAL_STEM: LEAD_VOCAL_STEM_LABEL,
            BV_VOCAL_STEM: BV_VOCAL_STEM_LABEL,
        }
    return {
        VOCAL_STEM: LEAD_VOCAL_STEM_LABEL,
        INST_STEM: INST_WITH_BACKING_VOCALS_STEM,
        LEAD_VOCAL_STEM: LEAD_VOCAL_STEM_LABEL,
        BV_VOCAL_STEM: BV_VOCAL_STEM_LABEL,
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
    positional = _positional_exclusive_flags(focus)
    if positional is not None:
        return positional
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
    positional = _positional_exclusive_flags(focus)
    if positional is not None:
        return positional
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


FOCUS_PRIMARY = "primary"
FOCUS_SECONDARY = "secondary"
_POSITIONAL_FOCUS = frozenset({FOCUS_PRIMARY, FOCUS_SECONDARY})


def positional_stem_focus(value: Any) -> str:
    """Return ``primary`` / ``secondary``, or ``""`` if ``value`` is not one."""
    token = str(value or "").strip().casefold()
    return token if token in _POSITIONAL_FOCUS else ""


def _positional_exclusive_flags(focus: str) -> tuple[bool, bool] | None:
    token = positional_stem_focus(focus)
    if token == FOCUS_PRIMARY:
        return True, False
    if token == FOCUS_SECONDARY:
        return False, True
    return None


def normalize_stem_focus(value: Any, *, strict: bool = False) -> str:
    """Canonical ``process.stem_focus``: bucket tag, ``raw:…``, positional, or empty.

    Accepts aliases (``vocals`` ≡ ``Vocals``) so CLI ``--set`` and GTK persist
    the same exclusive-pick vocabulary. CLI ``--stems primary|secondary`` stores
    those positional sentinels here; they are not :class:`StemBucket` values.
    A specialty stem must be named explicitly as ``raw:<stem>``; a bare
    unrecognized token is a typo, not a silent specialty pick. ``strict``
    raises on one, matching ``--set`` validation; the permissive default drops
    it so a hand-edited ``settings.json`` degrades to "export everything"
    instead of failing load.
    """
    token = "" if value is None else str(value).strip()
    if not token:
        return ""
    positional = positional_stem_focus(token)
    if positional:
        return positional
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
            f"{FOCUS_PRIMARY}, {FOCUS_SECONDARY}, "
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


def _concept_id(key: StemKey) -> str:
    if isinstance(key, StemBucket):
        return key.value
    return f"raw:{key.tag.strip().casefold()}"


def native_stem_route(
    model: Any,
    stem: str | StemId,
    *,
    conditional: bool = False,
    selected_by_default: bool = True,
) -> StemRoute:
    """Build the canonical route for one model-native source key."""
    native = stem if isinstance(stem, StemId) else StemId(str(stem))
    key = export_stem_key(model, native, for_ensemble=True)
    if not isinstance(key, (StemBucket, StemLiteral)):
        key = StemLiteral(key)
    return StemRoute(
        native=native,
        concept=_concept_id(key),
        label=export_stem_label(model, native.raw),
        filename_tag=filename_tag(key),
        kind=(
            StemRouteKind.SPLITTER
            if bool(getattr(model, "is_vocal_split_model", False))
            else (
                StemRouteKind.SPECIALTY
                if isinstance(key, StemLiteral)
                else StemRouteKind.NATIVE
            )
        ),
        conditional=conditional,
        selected_by_default=selected_by_default,
    )


def derived_stem_route(
    concept: StemBucket | StemLiteral | str,
    *,
    label: str | None = None,
    tag: str | None = None,
    conditional: bool = False,
    selected_by_default: bool = False,
    kind: StemRouteKind = StemRouteKind.DERIVED,
) -> StemRoute:
    """Build a route with no model-native source key."""
    if isinstance(concept, StemBucket):
        key: StemKey = concept
    elif isinstance(concept, StemLiteral):
        key = concept
    else:
        bucket = focus_bucket(str(concept))
        key = bucket if bucket is not StemBucket.UNKNOWN else StemLiteral(str(concept))
    route_tag = tag or filename_tag(key)
    route_label = label or (ui_label(key) if isinstance(key, StemBucket) else key.tag)
    return StemRoute(
        native=None,
        concept=_concept_id(key),
        label=route_label,
        filename_tag=route_tag,
        kind=kind,
        conditional=conditional,
        selected_by_default=selected_by_default,
    )


def _dedupe_routes(routes: Sequence[StemRoute]) -> Tuple[StemRoute, ...]:
    result: list[StemRoute] = []
    positions: dict[str, int] = {}
    for route in routes:
        identity = route.concept.casefold()
        previous = positions.get(identity)
        if previous is None:
            positions[identity] = len(result)
            result.append(route)
            continue
        existing = result[previous]
        # Prefer a native route, but retain default/guarantee information from
        # either spelling of the same semantic output.
        chosen = route if existing.native is None and route.native is not None else existing
        result[previous] = StemRoute(
            native=chosen.native,
            concept=chosen.concept,
            label=chosen.label,
            filename_tag=chosen.filename_tag,
            kind=chosen.kind,
            conditional=existing.conditional and route.conditional,
            selected_by_default=(
                existing.selected_by_default or route.selected_by_default
            ),
        )
    return tuple(result)


def model_stem_routes(model: Any) -> Tuple[StemRoute, ...]:
    """Complete canonical route inventory for an assembled model config."""
    def _stems(attribute: str) -> tuple[str, ...]:
        value = getattr(model, attribute, ())
        if not isinstance(value, (list, tuple)):
            return ()
        return tuple(str(item) for item in value if item)

    mdx_stems = _stems("mdx_model_stems")
    demucs_stems = _stems("demucs_source_list")
    native_stems = mdx_stems or demucs_stems
    if not native_stems:
        native_stems = tuple(
            str(item)
            for item in (
                getattr(model, "primary_stem", None),
                getattr(model, "secondary_stem", None),
            )
            if item
        )

    routes: list[StemRoute] = [native_stem_route(model, stem) for stem in native_stems]
    secondary = str(getattr(model, "secondary_stem", "") or "")
    selected_mdx = _stems("mdxnet_stems_selected")
    include_selected_complement = bool(
        len(mdx_stems) > 2
        and len(selected_mdx) == 1
        and getattr(model, "is_mdx_include_stem_complement", False)
        and not getattr(model, "is_primary_stem_only", False)
        and not getattr(model, "is_secondary_stem_only", False)
    )

    # A one-target model's other side and a Demucs focus complement are
    # computed from the mix rather than addressed in the native source map.
    if secondary and not any(
        route.native is not None and route.native.matches(secondary) for route in routes
    ):
        secondary_key = bucket_for_model_stem(secondary, **stem_context(model))
        secondary_concept: StemBucket | StemLiteral = (
            secondary_key
            if secondary_key is not StemBucket.UNKNOWN
            else StemLiteral(secondary)
        )
        routes.append(
            derived_stem_route(
                secondary_concept,
                label=(ui_label(secondary_key) if secondary_key is not StemBucket.UNKNOWN else secondary),
                conditional=include_selected_complement,
                selected_by_default=(
                    len(native_stems) <= 1 or include_selected_complement
                ),
            )
        )

    # Multi-source models can derive a vocals complement without changing its
    # identity when the Combine Stems recipe changes.
    concepts = {route.concept for route in routes}
    has_vocals = StemBucket.VOCALS.value in concepts
    has_instrumental = StemBucket.INSTRUMENTAL.value in concepts
    if len(native_stems) > 2 and has_vocals and not has_instrumental:
        routes.append(derived_stem_route(StemBucket.INSTRUMENTAL))

    return _dedupe_routes(routes)


def _route_matches_focus(route: StemRoute, requested: str) -> bool:
    if route.concept.casefold() == requested.casefold():
        return True
    wanted = focus_bucket(requested)
    actual = focus_bucket(route.concept)
    if wanted is StemBucket.UNKNOWN or actual is StemBucket.UNKNOWN:
        return False
    return actual is wanted or _plain_family(actual) is _plain_family(wanted)


def select_stem_routes(
    routes: Sequence[StemRoute], focus: str
) -> StemSelection:
    """Resolve one focus against a complete route inventory."""
    available = tuple(dict.fromkeys(route.concept for route in routes))
    requested = normalize_stem_focus(focus)
    if not requested:
        defaults = tuple(route for route in routes if route.selected_by_default)
        return StemSelection(
            "", defaults or tuple(routes), StemSelectionStatus.EMPTY, available
        )
    matched = tuple(route for route in routes if _route_matches_focus(route, requested))
    return StemSelection(
        requested,
        matched,
        StemSelectionStatus.MATCHED if matched else StemSelectionStatus.UNMATCHED,
        available,
    )


def route_matches_stem(
    route: StemRoute,
    stem: str | StemId | None,
    model: Any | None = None,
) -> bool:
    """True when ``stem`` names this route's native key, concept, or label."""
    if stem is None:
        return False
    token = stem.raw if isinstance(stem, StemId) else str(stem)
    if not token.strip():
        return False
    if route.native is not None and route.native.matches(stem):
        return True
    if route.concept.casefold() == token.strip().casefold():
        return True
    if route.label.casefold() == token.strip().casefold():
        return True
    ctx = stem_context(model) if model is not None else {
        "stem_count": 2,
        "is_karaoke": False,
        "is_bv": False,
        "is_vocal_split": False,
    }
    if focus_matches_stem(route.concept, token, **ctx):
        return True
    return focus_matches_stem(token, route.label, **ctx)


def routes_matching_stems(
    routes: Sequence[StemRoute],
    stems: Sequence[str],
    model: Any | None = None,
) -> Tuple[StemRoute, ...]:
    """Native inventory routes matching ``stems``, in sidecar order.

    Derived routes (no native key) are skipped so a custom MDX-C subset
    does not pull in a vocals complement. Unmatched names are ignored.
    """
    picked: list[StemRoute] = []
    seen: set[str] = set()
    for stem in stems:
        token = str(stem).strip()
        if not token:
            continue
        for route in routes:
            if route.native is None or route.concept in seen:
                continue
            if route_matches_stem(route, token, model):
                picked.append(route)
                seen.add(route.concept)
                break
    return tuple(picked)


def _route_matches_pair(route: StemRoute, pair: EnsemblePair, model: Any) -> bool:
    primary_bucket, secondary_bucket = pair.buckets()
    for bucket in (primary_bucket, secondary_bucket):
        if bucket is StemBucket.UNKNOWN:
            continue
        if route.concept == bucket.value:
            return True
        actual = focus_bucket(route.concept)
        if actual is not StemBucket.UNKNOWN and (
            actual is bucket or _plain_family(actual) is _plain_family(bucket)
        ):
            return True
    for half in pair.stem_halves():
        if half and route_matches_stem(route, half, model):
            return True
    return False


def routes_for_ensemble_pair(
    routes: Sequence[StemRoute], pair: EnsemblePair, model: Any
) -> Tuple[StemRoute, ...]:
    """Inventory routes that belong to a dual-stem ensemble pair."""
    if pair.is_multi_or_four() or pair is EnsemblePair.CHOOSE:
        return ()
    return tuple(route for route in routes if _route_matches_pair(route, pair, model))


def run_export_routes(model: Any) -> Tuple[StemRoute, ...]:
    """Routes this run should write, including splitter and 4-stem member rules.

    Vocal splitters keep both lead/backing writes. Four-stem and multi-stem
    ensemble *members* emit their full inventory so the final combine can
    still apply ``process.stem_focus``. Every other run uses
    ``selected_stem_routes``.
    """
    available = tuple(getattr(model, "available_stem_routes", ()) or ())
    selected = tuple(getattr(model, "selected_stem_routes", ()) or ())
    if getattr(model, "is_vocal_split_model", False):
        return available
    if getattr(model, "is_secondary_model", False) or getattr(
        model, "is_pre_proc_model", False
    ):
        return available or selected
    if getattr(model, "is_inst_only_voc_splitter", False) or getattr(
        model, "is_sec_bv_rebalance", False
    ):
        return available or selected
    if getattr(model, "is_ensemble_mode", False):
        settings = getattr(model, "settings", None)
        ensemble = getattr(settings, "ensemble", None) if settings is not None else None
        pair = coerce_ensemble_pair(getattr(ensemble, "main_stem", None))
        if pair.is_multi_or_four():
            return available
    return selected or available


def exports_named_stem(model: Any, stem: str | StemId | None) -> bool:
    """True when ``run_export_routes`` includes a route for ``stem``."""
    return any(
        route_matches_stem(route, stem, model) for route in run_export_routes(model)
    )


def select_ensemble_stem_routes(
    routes: Sequence[StemRoute],
    contributor_union: Sequence[StemRoute],
    focus: str,
) -> StemSelection:
    """Resolve final ensemble routes, distinguishing low contributor count."""
    selection = select_stem_routes(routes, focus)
    if selection.status is not StemSelectionStatus.UNMATCHED:
        return selection
    union_selection = select_stem_routes(contributor_union, focus)
    if union_selection.status is StemSelectionStatus.MATCHED:
        return StemSelection(
            union_selection.requested,
            (),
            StemSelectionStatus.INSUFFICIENT_MEMBERS,
            selection.available,
        )
    return selection


def resolve_in_sources(
    sources: Optional[Mapping[str, Any]], stem: str | StemId
) -> Optional[str]:
    """Return the key in ``sources`` matching ``stem`` (case/alias insensitive)."""
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
