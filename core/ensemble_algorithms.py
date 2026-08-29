"""Ensemble algorithm atoms and Primary/Secondary pair helpers."""

from __future__ import annotations

from typing import Dict, Iterable, Optional, Sequence, Tuple

from bundled.constants import (
    AUDIO_AVERAGE,
    CHUNK_MIN,
    ENSEMBLE_ALGORITHMS,
    HYBRID_SPEC,
    MAX_MAG_AVG_PHASE,
    MAX_MIN,
    MAX_SPEC,
    MEDIAN_SPEC,
    MIN_SPEC,
    SOFT_SPEC,
)

_DEFAULT_PRIMARY = MAX_SPEC
_DEFAULT_SECONDARY = MIN_SPEC

ENSEMBLE_ALGORITHM_BLURBS: Dict[str, str] = {
    MAX_SPEC: "Strongest magnitude per bin (fuller; can add artifacts)",
    MIN_SPEC: "Weakest magnitude per bin (cleaner; can sound muddy)",
    AUDIO_AVERAGE: "Mean of all member waveforms",
    MEDIAN_SPEC: "Per-bin median — robust with 3+ models",
    SOFT_SPEC: "Agreement-weighted blend (automatic weights)",
    MAX_MAG_AVG_PHASE: "Max magnitudes with averaged phase",
    HYBRID_SPEC: "Average of Max Spec and Min Spec",
    CHUNK_MIN: "Time-domain: quietest chunk from any member",
}

CUSTOM_PRESET = "Custom"
RECOMMENDED_PRESET = "Recommended (Max / Min)"
PAIR_CONSISTENT_PRESET = "Pair-consistent (native / mix residual)"
FULL_MAX_PRESET = "Full Max"
SOFT_BLEND_PRESET = "Soft blend"
HYBRID_CLEAN_PRESET = "Hybrid clean"
MEDIAN_ROBUST_PRESET = "Median robust"

# Display label → (primary, secondary). Custom is not in this map.
ENSEMBLE_PRESET_PAIRS: Dict[str, Tuple[str, str]] = {
    RECOMMENDED_PRESET: (MAX_SPEC, MIN_SPEC),
    FULL_MAX_PRESET: (MAX_SPEC, MAX_SPEC),
    SOFT_BLEND_PRESET: (SOFT_SPEC, SOFT_SPEC),
    HYBRID_CLEAN_PRESET: (HYBRID_SPEC, MIN_SPEC),
    MEDIAN_ROBUST_PRESET: (MEDIAN_SPEC, MEDIAN_SPEC),
}

ENSEMBLE_PRESET_OPTIONS: Tuple[str, ...] = (
    CUSTOM_PRESET,
    RECOMMENDED_PRESET,
    PAIR_CONSISTENT_PRESET,
    FULL_MAX_PRESET,
    SOFT_BLEND_PRESET,
    HYBRID_CLEAN_PRESET,
    MEDIAN_ROBUST_PRESET,
)

_DEFAULT_WAV_ENSEMBLE_SUBTITLE = "Combine in the time domain instead of spectrograms"
_CHUNK_MIN_WAV_SUBTITLE = (
    "Chunk Min always uses the time/chunk path (this toggle is ignored for that atom)"
)


def format_ensemble_type(primary: str, secondary: str) -> str:
    """Serialize dual-stem algorithms as ``Primary/Secondary``."""
    return f"{primary}/{secondary}"


def parse_ensemble_type(
    value: Optional[str],
    *,
    algorithms: Sequence[str] = ENSEMBLE_ALGORITHMS,
) -> Tuple[str, str]:
    """Parse ``ensemble_type`` into ``(primary, secondary)`` atoms.

    Accepts legacy pair strings and single-token 4-stem values. Unknown atoms
    fall back to Max Spec / Min Spec.
    """
    allowed = set(algorithms)
    text = (value or "").strip() or MAX_MIN
    if "/" in text:
        primary, _sep, secondary = text.partition("/")
        primary = primary.strip()
        secondary = secondary.strip()
    else:
        primary = text
        secondary = text
    if primary not in allowed:
        primary = _DEFAULT_PRIMARY
    if secondary not in allowed:
        secondary = _DEFAULT_SECONDARY
    return primary, secondary


def legacy_pair_values() -> Tuple[str, ...]:
    """Historical dual-stem pair labels still accepted when loading settings."""
    from bundled.constants import (
        AVE_AVE,
        AVE_MAX,
        AVE_MIN,
        MAX_AVE,
        MAX_MAX,
        MAX_MIN,
        MIN_AVE,
        MIN_MAX,
        MIN_MIX,
    )

    return (MAX_MIN, MAX_MAX, MAX_AVE, MIN_MAX, MIN_MIX, MIN_AVE, AVE_MAX, AVE_MIN, AVE_AVE)


def is_single_token_ensemble_type(value: Optional[str]) -> bool:
    """True for 4-stem / multi-stem styles that store one algorithm atom."""
    text = (value or "").strip()
    return bool(text) and "/" not in text


def normalize_ensemble_algorithm(
    algorithm: Optional[str],
    *,
    algorithms: Iterable[str] = ENSEMBLE_ALGORITHMS,
) -> str:
    """Return a known algorithm atom or Max Spec."""
    allowed = set(algorithms)
    text = (algorithm or "").strip()
    if text in allowed:
        return text
    return MAX_SPEC


def algorithm_blurb(algorithm: Optional[str]) -> str:
    """One-line description for an algorithm atom."""
    return ENSEMBLE_ALGORITHM_BLURBS.get((algorithm or "").strip(), "")


def preset_for_pair(primary: str, secondary: str) -> str:
    """Return the preset label for a pair, or Custom if none match."""
    pair = (primary, secondary)
    for label, mapped in ENSEMBLE_PRESET_PAIRS.items():
        if mapped == pair:
            return label
    return CUSTOM_PRESET


def pair_for_preset(preset: Optional[str]) -> Optional[Tuple[str, str]]:
    """Return ``(primary, secondary)`` for a named preset, or None for Custom/unknown."""
    if not preset or preset == CUSTOM_PRESET:
        return None
    if preset == PAIR_CONSISTENT_PRESET:
        return (_DEFAULT_PRIMARY, _DEFAULT_PRIMARY)
    return ENSEMBLE_PRESET_PAIRS.get(preset)


def preset_for_state(
    primary: str,
    secondary: str,
    *,
    derive_complement_from_mix: bool = False,
) -> str:
    """Return the preset label for a pair plus the mix-residual flag."""
    if derive_complement_from_mix:
        if (primary, secondary) == (_DEFAULT_PRIMARY, _DEFAULT_PRIMARY):
            return PAIR_CONSISTENT_PRESET
        return CUSTOM_PRESET
    return preset_for_pair(primary, secondary)


def algorithm_row_titles(
    primary_stem: Optional[str],
    secondary_stem: Optional[str],
    *,
    multi_stem: bool,
    derive_complement_from_mix: bool = False,
    leftover_label: str | None = None,
) -> Tuple[str, str]:
    """Titles for primary/secondary algorithm combo rows."""
    if multi_stem:
        return "Ensemble algorithm", "Secondary algorithm"
    primary = f"{primary_stem} algorithm" if primary_stem else "Primary algorithm"
    if derive_complement_from_mix:
        leftover = leftover_label or "Complement"
        return primary, f"{leftover} (from mix)"
    secondary = f"{secondary_stem} algorithm" if secondary_stem else "Secondary algorithm"
    return primary, secondary


def ensemble_options_summary(
    *,
    stem_chosen: bool,
    main_stem: str,
    primary_stem: Optional[str],
    secondary_stem: Optional[str],
    primary_algo: str,
    secondary_algo: str,
    model_count: int,
    multi_stem: bool,
    derive_complement_from_mix: bool = False,
    leftover_label: str | None = None,
) -> str:
    """Live description for the Ensemble options group."""
    if not stem_chosen:
        return "Choose a stem pair · select 2+ models"

    models_bit = f"{model_count} model" if model_count == 1 else f"{model_count} models"
    if model_count < 2:
        models_bit = f"{models_bit} (need 2+)"

    if multi_stem:
        return f"{main_stem} · {primary_algo} · {models_bit}"

    left = primary_stem or "Primary"
    if derive_complement_from_mix:
        right = leftover_label or "mix residual"
        return f"{left} ← {primary_algo} · {right} · {models_bit}"
    right = secondary_stem or "Secondary"
    return f"{left} ← {primary_algo} · {right} ← {secondary_algo} · {models_bit}"


def wav_ensemble_subtitle(*, uses_chunk_min: bool) -> str:
    """Subtitle for the Ensemble waveforms switch."""
    if uses_chunk_min:
        return _CHUNK_MIN_WAV_SUBTITLE
    return _DEFAULT_WAV_ENSEMBLE_SUBTITLE


def model_row_matches_query(title: str, subtitle: str, query: str) -> bool:
    """True when a member-model row matches a casefold search query."""
    q = (query or "").strip().casefold()
    if not q:
        return True
    haystack = f"{title} {subtitle}".casefold()
    return q in haystack


def models_selection_status(selected: int, *, visible_matches: Optional[int] = None) -> str:
    """Status line for the member-models dialog."""
    if visible_matches == 0:
        return "No matches"
    if selected == 0:
        return "Select at least 2 models"
    if selected == 1:
        return "Select at least 2 models (1 selected)"
    return f"{selected} models selected"
