"""Typed stem identity for ensemble eligibility, export, and settings.

Layers:

- :class:`StemId` — model/yaml dict key (preserve author casing for lookup).
- :class:`StemBucket` — filename-safe ensemble/eligibility identity.
- :class:`StemLiteral` — specialty stem kept as its own combine key.
Reviewed ensemble pairs and modes are exact IDs owned by :mod:`core.stem_pairs`.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from hashlib import sha256
from typing import Any, Mapping, Optional, Sequence, Tuple, Union

from bundled.constants import (
    BACKING_VOCALS_TAG,
    BASS_STEM,
    BV_VOCAL_STEM,
    BV_VOCAL_STEM_LABEL,
    DRUM_STEM,
    GUITAR_STEM,
    INST_STEM,
    INST_WITH_BACKING_VOCALS_STEM,
    INST_WITH_BACKING_VOCALS_TAG,
    INST_WITH_LEAD_VOCALS_STEM,
    INST_WITH_LEAD_VOCALS_TAG,
    LEAD_VOCAL_STEM,
    LEAD_VOCAL_STEM_LABEL,
    LEAD_VOCALS_TAG,
    NO_BASS_STEM,
    NO_DRUM_STEM,
    NO_GUITAR_STEM,
    NO_OTHER_STEM,
    NO_PIANO_STEM,
    OTHER_STEM,
    PIANO_STEM,
    VOCAL_STEM,
)

from .model_stem_manifest import (
    StemPairDefinition,
    load_bundled_stem_semantics,
    resolve_model_stem_semantics,
)
from .stem_roles import (
    ModelStemSemantics,
    StemId,
    StemLiteral,
    StemProcessingContext,
    StemProduction,
    StemRoleId,
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


StemKey = Union[StemBucket, StemLiteral]


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


def stem_role_key(role: StemRoleId | StemLiteral) -> str:
    """Stable focus/persistence identity for one semantic route role."""
    if isinstance(role, StemRoleId):
        return role.value
    if role.tag.startswith("legacy:"):
        return role.tag.removeprefix("legacy:")
    return f"raw:{role.tag.strip().casefold()}"


@dataclass(frozen=True, slots=True, init=False)
class StemRoute:
    """One canonical, exportable model or ensemble output.

    ``native`` preserves the model/yaml key used to address source arrays.
    ``role`` is a reviewed semantic ID or an isolated raw literal. ``concept``
    remains a read-only compatibility projection for callers still awaiting
    the role cutover.
    """

    native: Optional[StemId]
    role: StemRoleId | StemLiteral
    label: str
    filename_tag: str
    kind: StemRouteKind
    conditional: bool
    selected_by_default: bool
    logical_primary: bool
    selection_scope: str
    derived_from: tuple[StemRoleId, ...]
    complement_of: StemRoleId | None

    def __init__(
        self,
        native: Optional[StemId],
        role: StemRoleId | StemLiteral | None = None,
        label: str = "",
        filename_tag: str = "",
        kind: StemRouteKind = StemRouteKind.NATIVE,
        conditional: bool = False,
        selected_by_default: bool = True,
        logical_primary: bool = False,
        selection_scope: str = "",
        derived_from: tuple[StemRoleId, ...] = (),
        complement_of: StemRoleId | None = None,
        *,
        concept: str | None = None,
    ) -> None:
        """Create a route; ``concept=`` remains constructor compatibility only."""
        if role is None:
            if concept is None:
                raise TypeError("StemRoute requires role")
            role = StemLiteral(f"legacy:{concept}")
        object.__setattr__(self, "native", native)
        object.__setattr__(self, "role", role)
        object.__setattr__(self, "label", label)
        object.__setattr__(self, "filename_tag", filename_tag)
        object.__setattr__(self, "kind", kind)
        object.__setattr__(self, "conditional", conditional)
        object.__setattr__(self, "selected_by_default", selected_by_default)
        object.__setattr__(self, "logical_primary", logical_primary)
        object.__setattr__(self, "selection_scope", selection_scope)
        object.__setattr__(self, "derived_from", tuple(derived_from))
        object.__setattr__(self, "complement_of", complement_of)

    @property
    def concept(self) -> str:
        """Compatibility projection; new code should consume ``role``."""
        return stem_role_key(self.role)


_RAW_SCOPE_MARKER = "#scope="


def persisted_stem_focus(route: StemRoute) -> str:
    """Return the Settings-safe focus identity for exactly one route.

    Reviewed roles are portable namespaced identifiers.  Raw literals are
    deliberately not: their native spelling is meaningful only for the exact
    reviewed-resolution input (model, signature, and processing context) that
    produced it, so persist that opaque scope with the raw tag.
    """
    concept = route.concept
    if isinstance(route.role, StemLiteral) and not route.role.tag.startswith("legacy:"):
        if not route.selection_scope:
            return ""
        return f"{concept}{_RAW_SCOPE_MARKER}{route.selection_scope}"
    return concept


@dataclass(frozen=True)
class StemSelection:
    """Canonical result of matching ``process.stem_focus`` to routes."""

    requested: str
    routes: Tuple[StemRoute, ...]
    status: StemSelectionStatus
    available: Tuple[str, ...]


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


def ui_label(value: StemBucket | StemLiteral | str) -> str:
    """Human-readable label for UI; never use for filenames or settings ids."""
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
    is_instrumental = canonical == INST_STEM or (token == "other" and 1 <= stem_count <= 2)

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
    reviewed_bucket = focus_bucket(want) if "." in want else StemBucket.UNKNOWN
    if reviewed_bucket is not StemBucket.UNKNOWN:
        return _plain_family(stem_bucket) is _plain_family(reviewed_bucket)
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
    reviewed = {
        "vocal.vocals": StemBucket.VOCALS,
        "mix.instrumental": StemBucket.INSTRUMENTAL,
        "instrument.bass": StemBucket.BASS,
        "instrument.drums": StemBucket.DRUMS,
        "residual.other": StemBucket.OTHER,
    }.get(folded)
    if reviewed is not None:
        return reviewed
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
        raw_token, marker, scope = token.partition(_RAW_SCOPE_MARKER)
        rest = raw_token[4:].strip()
        if rest:
            if marker:
                if scope and _RAW_SCOPE_MARKER not in scope:
                    return f"raw:{rest.casefold()}{_RAW_SCOPE_MARKER}{scope}"
                if strict:
                    raise ValueError("raw stem focus has an invalid scope")
                return ""
            return f"raw:{rest.casefold()}"
        if strict:
            raise ValueError("stem focus 'raw:' needs a stem name after the prefix")
        return ""
    try:
        return StemRoleId(token).value
    except ValueError:
        pass
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


def _legacy_route_role(key: StemKey | str) -> StemRoleId | StemLiteral:
    """Adapter for callers outside the semantic-route cutover.

    Reviewed model routes never call this helper.  It only keeps existing
    UI/engine construction sites functional while they still request one of
    the former :class:`StemBucket` concepts.
    """
    if isinstance(key, StemLiteral):
        return StemLiteral(f"legacy:{_concept_id(key)}")
    if isinstance(key, StemBucket):
        return StemLiteral(f"legacy:{key.value}")
    return StemLiteral(f"legacy:{key}")


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
        role=_legacy_route_role(key),
        label=export_stem_label(model, native.raw),
        filename_tag=filename_tag(key),
        kind=(
            StemRouteKind.SPLITTER
            if bool(getattr(model, "is_vocal_split_model", False))
            else (StemRouteKind.SPECIALTY if isinstance(key, StemLiteral) else StemRouteKind.NATIVE)
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
        role=_legacy_route_role(key),
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
            role=chosen.role,
            label=chosen.label,
            filename_tag=chosen.filename_tag,
            kind=chosen.kind,
            conditional=existing.conditional and route.conditional,
            selected_by_default=(existing.selected_by_default or route.selected_by_default),
            logical_primary=(existing.logical_primary or route.logical_primary),
            selection_scope=chosen.selection_scope,
            derived_from=chosen.derived_from,
            complement_of=chosen.complement_of,
        )
    return tuple(result)


def _model_native_stems(model: Any) -> tuple[str, ...]:
    """Read backend-native source keys without normalizing their spelling."""

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
    return native_stems


def _model_semantics(model: Any, native_stems: Sequence[str]) -> ModelStemSemantics | None:
    """Resolve and cache one immutable projection on an assembled model only."""
    model_id = str(getattr(model, "canonical_id", "") or "")
    if not model_id:
        return None
    context = (
        StemProcessingContext.VOCAL_SPLIT
        if bool(getattr(model, "is_vocal_split_model", False))
        else StemProcessingContext.FULL_MIX
    )
    cache_key = (
        model_id,
        tuple((StemId(stem).casefold(), str(stem)) for stem in native_stems),
        context,
    )
    cached = getattr(model, "stem_semantics", None)
    if isinstance(cached, ModelStemSemantics) and (
        getattr(model, "_stem_semantics_cache_key", None) == cache_key
    ):
        return cached
    semantics = resolve_model_stem_semantics(
        model_id,
        native_stems=native_stems,
        backend_primary=str(
            getattr(model, "primary_stem_native", None) or getattr(model, "primary_stem", "") or ""
        ),
        backend_target=str(getattr(model, "target_instrument", "") or ""),
        context=context,
    )
    # Model configuration state is per assembled model; never write the shared
    # Settings object while retaining this exact resolution for later routes.
    try:
        model.stem_semantics = semantics
        model._stem_semantics_cache_key = cache_key
    except (AttributeError, TypeError):
        pass
    return semantics


def _raw_selection_scope(semantics: ModelStemSemantics) -> str:
    """Opaque identity binding a raw focus to one resolved model signature."""
    signature = "\x1f".join(
        output.native.casefold() if output.native is not None else "<derived>"
        for output in semantics.outputs
    )
    identity = "\x1f".join((semantics.model_id, semantics.context.value, signature))
    return sha256(identity.encode("utf-8")).hexdigest()


def _semantic_routes(semantics: ModelStemSemantics) -> tuple[StemRoute, ...]:
    registry = load_bundled_stem_semantics()
    routes: list[StemRoute] = []
    raw_scope = _raw_selection_scope(semantics)
    for output in sorted(semantics.outputs, key=lambda output: not output.logical_primary):
        if isinstance(output.role, StemRoleId):
            definition = registry.roles.get(output.role)
            if definition is None:
                # A corrupt/unavailable registry is already fail-closed at the
                # resolver boundary, but preserve the output if a caller passes
                # a hand-built projection.
                label = output.native.raw if output.native is not None else output.role.value
                tag = label
            else:
                label = definition.display
                tag = definition.filename_tag
        else:
            label = output.native.raw if output.native is not None else output.role.tag
            tag = label
        routes.append(
            StemRoute(
                native=output.native,
                role=output.role,
                label=label,
                filename_tag=tag,
                kind=(
                    StemRouteKind.DERIVED
                    if output.production is StemProduction.DERIVED
                    else StemRouteKind.NATIVE
                ),
                selected_by_default=output.selected_by_default,
                logical_primary=output.logical_primary,
                selection_scope=(
                    raw_scope
                    if isinstance(output.role, StemLiteral)
                    and not output.role.tag.startswith("legacy:")
                    else ""
                ),
                derived_from=output.derived_from,
                complement_of=output.complement_of,
            )
        )
    return tuple(routes)


def model_stem_routes(model: Any) -> Tuple[StemRoute, ...]:
    """Complete exact semantic route inventory for one assembled model.

    A reviewed declaration is resolved once from the canonical ID, whole
    native signature, backend metadata, and explicit processing context.  A
    missing/mismatched declaration returns raw literals rather than guessed
    buckets.  The legacy branch only serves non-assembled compatibility stubs
    that lack a canonical model identity.
    """
    native_stems = _model_native_stems(model)
    semantics = _model_semantics(model, native_stems)
    if semantics is not None:
        return _dedupe_routes(_semantic_routes(semantics))

    mdx_stems = tuple(str(item) for item in getattr(model, "mdx_model_stems", ()) or () if item)

    routes: list[StemRoute] = [native_stem_route(model, stem) for stem in native_stems]
    secondary = str(getattr(model, "secondary_stem", "") or "")
    selected_mdx = tuple(
        str(item) for item in getattr(model, "mdxnet_stems_selected", ()) or () if item
    )
    include_selected_complement = bool(
        len(mdx_stems) > 2
        and len(selected_mdx) == 1
        and getattr(model, "is_mdx_include_stem_complement", False)
    )

    # A one-target model's other side and a Demucs focus complement are
    # computed from the mix rather than addressed in the native source map.
    if secondary and not any(
        route.native is not None and route.native.matches(secondary) for route in routes
    ):
        secondary_key = bucket_for_model_stem(secondary, **stem_context(model))
        secondary_concept: StemBucket | StemLiteral = (
            secondary_key if secondary_key is not StemBucket.UNKNOWN else StemLiteral(secondary)
        )
        routes.append(
            derived_stem_route(
                secondary_concept,
                label=(
                    ui_label(secondary_key)
                    if secondary_key is not StemBucket.UNKNOWN
                    else secondary
                ),
                conditional=include_selected_complement,
                selected_by_default=(len(native_stems) <= 1 or include_selected_complement),
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
    if isinstance(route.role, StemRoleId):
        return route.role.value == requested
    if route.role.tag.startswith("legacy:"):
        if route.concept.casefold() == requested.casefold():
            return True
        if route.label.casefold() == requested.strip().casefold():
            return True
        if route.native is not None and route.native.matches(requested):
            return True
        wanted = focus_bucket(requested)
        actual = focus_bucket(route.concept)
        return (
            wanted is not StemBucket.UNKNOWN
            and actual is not StemBucket.UNKNOWN
            and (actual is wanted or _plain_family(actual) is _plain_family(wanted))
        )
    return persisted_stem_focus(route) == requested


def select_stem_routes(routes: Sequence[StemRoute], focus: str) -> StemSelection:
    """Resolve one focus against a complete route inventory."""
    available = tuple(dict.fromkeys(route.concept for route in routes))
    requested = normalize_stem_focus(focus)
    if not requested:
        defaults = tuple(route for route in routes if route.selected_by_default)
        return StemSelection("", defaults or tuple(routes), StemSelectionStatus.EMPTY, available)
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
    ctx = (
        stem_context(model)
        if model is not None
        else {
            "stem_count": 2,
            "is_karaoke": False,
            "is_bv": False,
            "is_vocal_split": False,
        }
    )
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


def routes_for_ensemble_pair(
    routes: Sequence[StemRoute], pair: StemPairDefinition | str | None
) -> Tuple[StemRoute, ...]:
    """Return a complete reviewed pair in the model's native route order.

    An ensemble pair is meaningful only when a reviewed model projection
    provides *both* exact role IDs from the manifest definition.  Raw
    literals, legacy concepts, labels, and native-key spellings cannot satisfy
    this boundary.
    """
    definition: StemPairDefinition | None
    if isinstance(pair, str):
        from .stem_pairs import stem_pair_definition

        definition = stem_pair_definition(pair)
    else:
        definition = pair
    if definition is None:
        return ()
    wanted = set(definition.roles)
    matched: list[StemRoute] = []
    found: set[StemRoleId] = set()
    for route in routes:
        if isinstance(route.role, StemRoleId) and route.role in wanted:
            matched.append(route)
            found.add(route.role)
    return tuple(matched) if found == wanted else ()


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
    if getattr(model, "is_secondary_model", False) or getattr(model, "is_pre_proc_model", False):
        return available or selected
    if getattr(model, "is_inst_only_voc_splitter", False) or getattr(
        model, "is_sec_bv_rebalance", False
    ):
        return available or selected
    if getattr(model, "is_ensemble_mode", False):
        settings = getattr(model, "settings", None)
        ensemble = getattr(settings, "ensemble", None) if settings is not None else None
        from .stem_pairs import is_stem_mode, normalize_stem_pair_id

        pair_id = normalize_stem_pair_id(getattr(ensemble, "main_stem", None))
        if is_stem_mode(pair_id):
            return available
        if pair_id:
            # A dual pair has already been filtered to its complete reviewed
            # role coverage by ``ModelConfig._apply_stem_focus``.  An empty
            # selection is intentional: falling back to ``available`` would
            # let an incomplete four-stem member leak a shared role.
            return selected
    return selected or available


def exports_named_stem(model: Any, stem: str | StemId | None) -> bool:
    """True when ``run_export_routes`` includes a route for ``stem``."""
    return any(route_matches_stem(route, stem, model) for route in run_export_routes(model))


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


def resolve_in_sources(sources: Optional[Mapping[str, Any]], stem: str | StemId) -> Optional[str]:
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
