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

import typing
from typing import List

from bundled.constants import (
    ALL_STEMS,
    DEMUCS_ARCH_TYPE,
    ENSEMBLE_MODE,
    NO_MODEL,
)
from core.model_display import parse_model_tag
from core.model_identity import ModelIdentityService
from core.model_stem_manifest import load_bundled_stem_semantics
from core.stem_pairs import normalize_stem_pair_id
from core.stem_roles import StemRoleId

from .settings_bind import enum_value, get_flat

#: Subtitle for a section whose every activate switch is off.
OFF = "Off"
#: Subtitle for a section that is on but has no model chosen yet.
ON_NO_MODEL = "On — no model selected"

#: Joins the parts of a multi-part summary.
_SEP = " · "

_SECONDARY_SLOTS = ("voc_inst", "other", "bass", "drums")
_SECONDARY_PRIMARY_ROLES = {
    "other": StemRoleId("residual.other"),
    "bass": StemRoleId("instrument.bass"),
    "drums": StemRoleId("instrument.drums"),
}


def secondary_stem_pair_label(slot: str) -> str:
    """Project one secondary-pass label from exact manifest presentation."""
    registry = load_bundled_stem_semantics()
    if slot == "voc_inst":
        definition = registry.pairs.get("pair.vocals_instrumental")
        if definition is None:
            raise ValueError("missing pair.vocals_instrumental manifest definition")
        return definition.display
    primary_role = _SECONDARY_PRIMARY_ROLES.get(slot)
    if primary_role is None:
        raise ValueError(f"unknown secondary stem slot {slot!r}")
    primary = registry.roles.get(primary_role)
    if primary is None:
        raise ValueError(f"missing manifest role {primary_role.value!r}")
    removed = registry.roles.get(StemRoleId(f"{primary_role.value}.removed"))
    secondary_display = removed.display if removed is not None else f"Mix minus {primary.display}"
    return f"{primary.display}/{secondary_display}"


def _model_label(tag: typing.Any, repo: typing.Any = None) -> str:
    """Return the display/basename half of a stored model reference.

    Accepts canonical ids (``mdx:basename``) and leftover ``Arch: Display``
    tags. Subtitles are tight on space and the architecture is already implied
    by the tab. Returns ``""`` for an unset model.
    """
    if not tag or tag == NO_MODEL:
        return ""
    if repo is not None:
        try:
            return ModelIdentityService(repo).display_label(str(tag))
        except (TypeError, ValueError):
            pass
    _arch, name = parse_model_tag(str(tag))
    return name or str(tag)


def four_stem_secondaries_apply(settings: typing.Any, process_method: str) -> bool:
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
        pair_id = normalize_stem_pair_id(settings.ensemble.main_stem)
        return pair_id == "mode.four_stem" or (pair_id == "mode.multi_stem" and is_demucs)
    return is_demucs and settings.demucs.stems == ALL_STEMS


def secondary_models_summary(
    settings: typing.Any,
    prefix: str,
    *,
    four_stem: bool,
    repo: typing.Any = None,
) -> str:
    """One-line state of the per-architecture secondary-model section.

    ``four_stem`` must match what the section actually shows (see
    :func:`four_stem_secondaries_apply`) so the subtitle never describes a slot
    the user cannot see.
    """
    if not get_flat(settings, f"{prefix}_is_secondary_model_activate"):
        return OFF

    slots = _SECONDARY_SLOTS if four_stem else _SECONDARY_SLOTS[:1]
    parts: List[str] = []
    for slot in slots:
        label = secondary_stem_pair_label(slot)
        name = _model_label(get_flat(settings, f"{prefix}_{slot}_secondary_model", NO_MODEL), repo)
        if not name:
            continue
        scale = get_flat(settings, f"{prefix}_{slot}_secondary_model_scale", 0.9)
        try:
            scale_text = f"{float(scale):.2f}"
        except (TypeError, ValueError):
            scale_text = str(scale)
        parts.append(f"{label}: {name} ({scale_text})")

    return _SEP.join(parts) if parts else ON_NO_MODEL


def preproc_summary(settings: typing.Any, repo: typing.Any = None) -> str:
    """One-line state of the Demucs pre-process-model section."""
    if not settings.demucs.is_pre_proc_model_activate:
        return OFF
    name = _model_label(settings.demucs.pre_proc_model or NO_MODEL, repo)
    if not name:
        return ON_NO_MODEL
    if settings.demucs.is_pre_proc_model_inst_mix:
        return f"{name}{_SEP}saves instrumental mixture"
    return name


def vocal_split_summary(settings: typing.Any, repo: typing.Any = None) -> str:
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
        name = _model_label(settings.process.vocal_splitter or NO_MODEL, repo)
        parts.append(name if name else ON_NO_MODEL)
    if deverb_on:
        parts.append(f"deverb: {enum_value(settings.process.deverb_vocal_opt)}")
    return _SEP.join(parts)
