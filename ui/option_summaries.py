"""Pure state summaries for collapsible option sections.

Each function turns a settings mapping into the one-line subtitle shown on a
collapsed ``Adw.ExpanderRow``, so a user can see whether a section is on, and
what it will do, without opening it.

No GTK import: these are plain functions over typed settings and are unit tested
headlessly. They live at the ``ui/`` root rather than under
``ui/model_options/`` because both :mod:`ui.views.base` and
:mod:`ui.widgets.vocal_split_row` consume them, and a widget importing from
``model_options`` would invert the dependency.
"""

from __future__ import annotations

from typing import List, Tuple

from bundled.constants import (
    ALL_STEMS,
    BASS_PAIR,
    CHOOSE_STEM_PAIR,
    DEMUCS_ARCH_TYPE,
    DRUM_PAIR,
    ENSEMBLE_MODE,
    ENSEMBLE_PARTITION,
    FOUR_STEM_ENSEMBLE,
    MULTI_STEM_ENSEMBLE,
    NO_MODEL,
    OTHER_PAIR,
    VOCAL_PAIR,
)
from .settings_bind import get_flat

#: Subtitle for a section whose every activate switch is off.
OFF = "Off"
#: Subtitle for a section that is on but has no model chosen yet.
ON_NO_MODEL = "On — no model selected"

#: Joins the parts of a multi-part summary.
_SEP = " · "

#: ``(slot, label)`` for the secondary-model stem pairs, matching the order of
#: ``ui.views.base._SECONDARY_SLOTS``. Only the first entry applies unless the
#: run uses four sources -- see :func:`four_stem_secondaries_apply`.
_SECONDARY_PAIRS: Tuple[Tuple[str, str], ...] = (
    ("voc_inst", VOCAL_PAIR),
    ("other", OTHER_PAIR),
    ("bass", BASS_PAIR),
    ("drums", DRUM_PAIR),
)


def _model_label(tag) -> str:
    """Strip the ``"<arch>: "`` prefix from a stored model tag.

    Stored values come from ``ModelConfig.model_and_process_tag`` (e.g.
    ``"MDX-Net: UVR-MDX-NET Inst HQ 3"``). Subtitles are tight on space and the
    architecture is already implied by the tab, so only the model name is kept.
    Returns ``""`` for an unset model, which callers treat as "not configured".
    """
    if not tag or tag == NO_MODEL:
        return ""
    text = str(tag)
    _, separator, name = text.partition(ENSEMBLE_PARTITION)
    return name if separator else text


def four_stem_secondaries_apply(settings, process_method: str) -> bool:
    """Whether the ``other`` / ``bass`` / ``drums`` secondary slots can affect a run.

    Mirrors the engine's own branch in ``core/model_data.py`` (the
    ``is_valid_ensemble or is_4_stem_ensemble or is_multi_stem_ensemble_demucs``
    condition): the four-slot path runs for a Demucs model exporting all stems
    (only outside ensemble mode), for any member of a 4-stem ensemble, and for
    a Demucs member of a multi-stem ensemble. In every other case those three
    slots are dead weight.
    """
    is_demucs = process_method == DEMUCS_ARCH_TYPE
    if settings.process.method == ENSEMBLE_MODE:
        main_stem = settings.ensemble.main_stem or CHOOSE_STEM_PAIR
        return main_stem == FOUR_STEM_ENSEMBLE or (
            main_stem == MULTI_STEM_ENSEMBLE and is_demucs
        )
    return is_demucs and settings.demucs.stems == ALL_STEMS


def secondary_models_summary(settings, prefix: str, *, four_stem: bool) -> str:
    """One-line state of the per-architecture secondary-model section.

    ``four_stem`` must match what the section actually shows (see
    :func:`four_stem_secondaries_apply`) so the subtitle never describes a slot
    the user cannot see.
    """
    if not get_flat(settings, f"{prefix}_is_secondary_model_activate"):
        return OFF

    pairs = _SECONDARY_PAIRS if four_stem else _SECONDARY_PAIRS[:1]
    parts: List[str] = []
    for slot, label in pairs:
        name = _model_label(
            get_flat(settings, f"{prefix}_{slot}_secondary_model", NO_MODEL)
        )
        if not name:
            continue
        scale = get_flat(settings, f"{prefix}_{slot}_secondary_model_scale", 0.9)
        try:
            scale_text = f"{float(scale):.2f}"
        except (TypeError, ValueError):
            scale_text = str(scale)
        parts.append(f"{label}: {name} ({scale_text})")

    return _SEP.join(parts) if parts else ON_NO_MODEL


def preproc_summary(settings) -> str:
    """One-line state of the Demucs pre-process-model section."""
    if not settings.demucs.is_pre_proc_model_activate:
        return OFF
    name = _model_label(settings.demucs.pre_proc_model or NO_MODEL)
    if not name:
        return ON_NO_MODEL
    if settings.demucs.is_pre_proc_model_inst_mix:
        return f"{name}{_SEP}saves instrumental mixture"
    return name


def vocal_split_summary(settings) -> str:
    """One-line state of the vocal-splitter and deverb section.

    This section holds two independent switches, so it is ``OFF`` only when both
    are off; otherwise the enabled halves are joined.
    """
    split_on = bool(settings.process.vocal_splitter_enabled)
    deverb_on = bool(settings.process.deverb_vocals)
    if not split_on and not deverb_on:
        return OFF

    parts: List[str] = []
    if split_on:
        name = _model_label(settings.process.vocal_splitter or NO_MODEL)
        parts.append(name if name else ON_NO_MODEL)
    if deverb_on:
        parts.append(f"deverb: {settings.process.deverb_vocal_opt}")
    return _SEP.join(parts)
