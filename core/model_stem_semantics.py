"""Shared stem export semantics for runtime UI and the model catalogue generator.

Derives display-label overrides and export intent from resolved model metadata
(yaml instruments, hash primary_stem, karaoke flags) without reading generated docs.
"""

from __future__ import annotations

import typing
from dataclasses import replace
from typing import Dict, List, Mapping, Optional, Sequence, Tuple

from bundled.constants import (
    ALL_STEMS,
    BV_VOCAL_STEM,
    BV_VOCAL_STEM_LABEL,
    INST_STEM,
    NO_OTHER_STEM,
    NO_STEM,
    OTHER_STEM,
    VOCAL_STEM,
)

from .catalogue_types import StemSemanticProjection, StemSemanticRoute
from .stem_roles import (
    ModelStemSemantics,
    StemProcessingContext,
    StemReviewStatus,
    StemRoleId,
)

# Catalogue / runtime intent labels (stable strings).
INTENT_KARAOKE = "karaoke"
INTENT_DRUM_BASS_SEP = "drum_bass_sep"
INTENT_DUAL_VOC_INST = "dual_voc_inst"
INTENT_MULTI_STEM = "multi_stem"
INTENT_SPECIAL_FX = "special_fx"
INTENT_SPECIALTY_STEM = "specialty_stem"
INTENT_INSTRUMENTAL = "instrumental"
INTENT_VOCALS = "vocals"
INTENT_UNKNOWN = "unknown"
MODEL_STEM_INTENTS = frozenset(
    {
        INTENT_KARAOKE,
        INTENT_DRUM_BASS_SEP,
        INTENT_DUAL_VOC_INST,
        INTENT_MULTI_STEM,
        INTENT_SPECIAL_FX,
        INTENT_SPECIALTY_STEM,
        INTENT_INSTRUMENTAL,
        INTENT_VOCALS,
        INTENT_UNKNOWN,
    }
)


def resolve_catalogue_stem_semantics(
    model_id: str,
    *,
    native_stems: Sequence[str],
    backend_primary: str = "",
    backend_target: str = "",
    context: StemProcessingContext = StemProcessingContext.FULL_MIX,
    runtime_warning: str = "",
    registry: typing.Any = None,
) -> ModelStemSemantics:
    """Resolve a catalogue row through exact declarations or an exact waiver.

    Catalogue name/category guesses deliberately do not take part in this
    lookup.  A waiver is audit evidence for an exact canonical identity, not a
    declaration of output membership, so it carries no routes.
    """
    from .model_stem_manifest import (
        StemSemanticsRegistry,
        load_bundled_stem_semantics,
        resolve_model_stem_semantics,
    )

    selected_registry = registry if registry is not None else load_bundled_stem_semantics()
    semantics = resolve_model_stem_semantics(
        model_id,
        native_stems=native_stems,
        backend_primary=backend_primary,
        backend_target=backend_target,
        context=context,
        registry=StemSemanticsRegistry.empty() if runtime_warning else selected_registry,
    )
    if runtime_warning:
        return replace(semantics, warning=runtime_warning)
    waiver = selected_registry.waivers.get(model_id)
    if waiver is not None and semantics.status is StemReviewStatus.RAW:
        return ModelStemSemantics(
            model_id=model_id,
            context=context,
            intent="",
            outputs=(),
            status=StemReviewStatus.WAIVED,
            evidence=waiver,
        )
    return semantics


def stem_semantics_projection(
    semantics: ModelStemSemantics | None,
    *,
    backend_primary: str | None = None,
    backend_target: str | None = None,
) -> StemSemanticProjection:
    """Render exact semantics for catalogue, plan, CLI, and diagnostics.

    The result intentionally keeps raw backend primary/target fields adjacent
    to reviewed display data.  It has no display-to-identity path and never
    derives a role from a native spelling.
    """
    primary = None if backend_primary is None else str(backend_primary)
    target = None if backend_target is None else str(backend_target)
    if semantics is None:
        return StemSemanticProjection(
            backend_primary_stem=primary,
            backend_target_stem=target,
            logical_primary_role=None,
            logical_secondary_role=None,
            status=StemReviewStatus.RAW.value,
            context=StemProcessingContext.FULL_MIX.value,
            routes=(),
        )

    from .model_stem_manifest import load_bundled_stem_semantics

    registry = load_bundled_stem_semantics()
    routes: list[StemSemanticRoute] = []
    roles: list[str] = []
    logical_primary_role: str | None = None
    logical_secondary_role = (
        semantics.logical_secondary_role.value
        if isinstance(semantics.logical_secondary_role, StemRoleId)
        else (
            f"raw:{semantics.logical_secondary_role.tag.strip().casefold()}"
            if semantics.logical_secondary_role is not None
            else None
        )
    )
    # ``outputs`` preserves the exact reviewed manifest/native declaration
    # order. Logical route markers are metadata, never an ordering rule.
    for output in semantics.outputs:
        native = output.native.raw if output.native is not None else None
        if isinstance(output.role, StemRoleId):
            definition = registry.roles.get(output.role)
            role = output.role.value
            display = definition.display if definition is not None else (native or role)
            filename_tag = definition.filename_tag if definition is not None else display
            roles.append(role)
            if output.logical_primary:
                logical_primary_role = role
        else:
            role = None
            display = native or output.role.tag
            filename_tag = display
        routes.append(
            StemSemanticRoute(
                native=native,
                role=role,
                display=display,
                filename_tag=filename_tag,
                production=output.production.value,
                logical_primary=output.logical_primary,
                logical_secondary=output.logical_secondary,
                derived_from=tuple(item.value for item in output.derived_from),
                complement_of=(
                    output.complement_of.value if output.complement_of is not None else None
                ),
                selected_by_default=output.selected_by_default,
            )
        )
    return StemSemanticProjection(
        backend_primary_stem=primary,
        backend_target_stem=target,
        logical_primary_role=logical_primary_role,
        logical_secondary_role=logical_secondary_role,
        status=semantics.status.value,
        context=semantics.context.value,
        routes=tuple(routes),
        canonical_roles=tuple(roles),
        evidence=semantics.evidence,
        warning=semantics.warning,
    )


# Weight basenames where both 2-stem exports are first-class (backend primary is arbitrary).
DUAL_STEM_WEIGHTS = frozenset(
    {
        "uvr_mdxnet_main.onnx",
        "uvr_mdxnet_main",
    }
)


def is_dual_stem_weight(weight_basename: str) -> bool:
    """True when both 2-stem exports are first-class for this weight basename."""
    low = (weight_basename or "").lower()
    if not low:
        return False
    if low in DUAL_STEM_WEIGHTS:
        return True
    stem = low[:-5] if low.endswith(".onnx") else low
    return stem in DUAL_STEM_WEIGHTS or f"{stem}.onnx" in DUAL_STEM_WEIGHTS


_DUAL_VOC_INST_LABELS = (
    "mdx-net main",
    "uvr-mdx-net main",
)

_DRUM_BASS_HINTS = ("drum-bass", "no drum", "drum bass", "sdr 1053")

_SPECIAL_FX_LABEL_HINTS = (
    "dereverb",
    "de-reverb",
    "deverb",
    "denoise",
    "de-noise",
    "de-echo",
    "deecho",
    "de echo",
    "reverb hq",
    "uvr-deecho",
    "uvr-de-echo",
    "uvr-denoise",
    "uvr-dereverb",
    "uvr-de-reverb",
    "uvr-de-echo",
    "mdx23c dereverb",
)

_EARLY_SPECIAL_FX_LABEL_HINTS = (
    "crowd hq",
    "wind_inst",
    "wind inst",
)

_SPECIALTY_LABEL_HINTS = (
    "male-female",
    "male female",
    "chorus male",
    "aspiration",
    "phantom centre",
    "phantom center",
    " bve",
    "| bve",
    " guitar by",
    "| guitar by",
    " crowd by",
    "| crowd by",
)

_SPECIALTY_STEMS = frozenset(
    {
        "male",
        "female",
        "aspiration",
        "similarity",
        "lead",
        "crowd",
        "guitar",
    }
)

_SPECIALTY_STEM_PAIRS = (
    frozenset({"male", "female"}),
    frozenset({"aspiration", "other"}),
)

_SPECIAL_FX_STEM_COMPACT = frozenset(
    {
        "noise",
        "reverb",
        "dry",
        "noreverb",
        "nodry",
        "noecho",
    }
)

# Two-stem yaml pairs use `vocals` + `other` where `other` is the instrumental side
# (not Demucs 4-stem "Other"). Relabel only for display; backend stem keys are unchanged.
VOCALS_OTHER_DISPLAY_OVERRIDES: Dict[str, str] = {
    "vocals": VOCAL_STEM,
    "Vocals": VOCAL_STEM,
    VOCAL_STEM: VOCAL_STEM,
    "other": INST_STEM,
    "Other": INST_STEM,
    OTHER_STEM: INST_STEM,
    "No vocals": INST_STEM,
    "No Vocals": INST_STEM,
    f"{NO_STEM}{VOCAL_STEM}": INST_STEM,
    f"{NO_STEM}{VOCAL_STEM.lower()}": INST_STEM,
    "No other": VOCAL_STEM,
    "No Other": VOCAL_STEM,
    NO_OTHER_STEM: VOCAL_STEM,
    f"{NO_STEM}{OTHER_STEM.lower()}": VOCAL_STEM,
    f"{NO_STEM}{OTHER_STEM}": VOCAL_STEM,
}


def model_weight_basename(model: typing.Any) -> str:
    if model is None:
        return ""
    for attr in ("model_basename", "model_name"):
        value = getattr(model, attr, None)
        if value:
            return str(value).lower()
    path = getattr(model, "model_path", None) or ""
    if path:
        import os

        return os.path.basename(path).lower()
    return ""


def training_instruments(model: typing.Any) -> List[str]:
    if model is None:
        return []
    configs = getattr(model, "mdx_c_configs", None)
    training = getattr(configs, "training", None) if configs is not None else None
    if training is None:
        stems = getattr(model, "mdx_model_stems", None) or []
        return list(stems)
    instruments = getattr(training, "instruments", None) or []
    return [str(name) for name in instruments]


def target_instrument(model: typing.Any) -> str:
    if model is None:
        return ""
    configs = getattr(model, "mdx_c_configs", None)
    training = getattr(configs, "training", None) if configs is not None else None
    if training is None:
        return ""
    target = getattr(training, "target_instrument", None) or ""
    return str(target) if target else ""


def is_vocal_target(stem: str) -> bool:
    """True when a yaml/hash stem names the vocal target (any common casing)."""
    if not stem:
        return False
    return str(stem).lower() in ("vocals", "vocal", "voc")


def is_vocal_family_stem(stem: str) -> bool:
    """Catalogue/intent vocal-side spellings. Broader than :func:`is_vocal_target`.

    Engines invert through ``is_vocal_target`` only. Intent and focus may treat
    ``voices`` / ``vox`` / ``lead-vocal`` as vocal-family without opening that
    invert path. Bare ``lead`` and ``singer_1`` stay specialty.
    """
    if not stem:
        return False
    if is_vocal_target(stem):
        return True
    token = str(stem).lower().strip().replace(" ", "-").replace("_", "-")
    return token in ("voices", "vox", "lead-vocal")


def is_instrumental_target(stem: str) -> bool:
    if not stem:
        return False
    low = str(stem).lower()
    return low in ("instrumental", "inst", "instrument", "other")


# Yaml/community spellings for a dedicated backing-vocal stem. Kept out of
# ``_STEM_NAME_ALIASES`` so they never merge with MUSDB ``Vocals``.
_BACKING_VOCAL_TOKENS = frozenset(
    {
        "backing_vocal",
        "backing_vocals",
        "backing vocals",
        "backing_only",
        BV_VOCAL_STEM.casefold(),
        BV_VOCAL_STEM_LABEL.casefold(),
    }
)


def is_backing_vocal_stem(stem: str) -> bool:
    """True for a dedicated backing-vocal yaml/logic name (not MUSDB Vocals)."""
    if not stem:
        return False
    return str(stem).strip().casefold() in _BACKING_VOCAL_TOKENS


def pick_vocal_key(sources: Optional[Mapping[str, typing.Any]]) -> Optional[str]:
    """First sources-dict key that names vocals, any common casing."""
    if not isinstance(sources, Mapping):
        return None
    for key in sources:
        if is_vocal_target(str(key)):
            return str(key)
    return None


def pick_backing_key(sources: Optional[Mapping[str, typing.Any]]) -> Optional[str]:
    """Backing-vocal key, else 2-stem instrumental/other. Not 4-stem ``other``."""
    if not isinstance(sources, Mapping):
        return None
    instrumental: Optional[str] = None
    other: Optional[str] = None
    for key in sources:
        name = str(key)
        if is_backing_vocal_stem(name):
            return name
        low = name.casefold()
        if low in ("instrumental", "inst", "instrument"):
            if instrumental is None:
                instrumental = name
        elif low == "other":
            other = name
    if instrumental is not None:
        return instrumental
    if other is not None and len(sources) <= 2:
        return other
    return None


def pick_instrumental_key(sources: Optional[Mapping[str, typing.Any]]) -> Optional[str]:
    """True instrumental for inst-mixes: not backing vocals, not 4-stem ``other``."""
    if not isinstance(sources, Mapping):
        return None
    instrumental: Optional[str] = None
    other: Optional[str] = None
    for key in sources:
        name = str(key)
        if is_backing_vocal_stem(name):
            continue
        low = name.casefold()
        if low in ("instrumental", "inst", "instrument"):
            if instrumental is None:
                instrumental = name
        elif low == "other":
            other = name
    if instrumental is not None:
        return instrumental
    if other is not None and len(sources) <= 2:
        return other
    return None


def vocal_inst_from_sources(
    sources: Optional[Mapping[str, typing.Any]],
) -> Tuple[typing.Any, typing.Any]:
    """``(vocal_array, instrumental_array)`` from a demix/export map, or Nones."""
    if not isinstance(sources, Mapping):
        return None, None
    vocal_key = pick_vocal_key(sources)
    inst_key = pick_instrumental_key(sources)
    vocal = sources[vocal_key] if vocal_key is not None else None
    inst = sources[inst_key] if inst_key is not None else None
    return vocal, inst


def vocal_split_source_roles(
    sources: Optional[Mapping[str, typing.Any]],
    *,
    is_bv_model: bool = False,
) -> Tuple[Optional[str], Optional[str]]:
    """Yaml keys for ``(lead, backing)`` audio in a vocal-splitter demix dict."""
    vocal_key = pick_vocal_key(sources)
    backing_key = pick_backing_key(sources)
    if is_bv_model:
        return backing_key, vocal_key
    return vocal_key, backing_key


def infer_is_karaoke_from_hints(
    *,
    model_name: str = "",
    config_yaml: str = "",
    weight_basename: str = "",
) -> bool:
    """Infer karaoke intent from catalogue label, config name, or weight basename."""
    text = " ".join(part for part in (model_name, config_yaml, weight_basename) if part).lower()
    return "karaoke" in text


def resolve_karaoke_confidence(
    *,
    model_data: Optional[Mapping] = None,
    model_name: str = "",
    config_yaml: str = "",
    weight_basename: str = "",
) -> Tuple[bool, bool]:
    """Resolve ``(is_karaoke, is_curated)``.

    ``is_curated`` is ``True`` only when curated hash metadata settled it.
    ``False`` means ``is_karaoke`` came from
    :func:`infer_is_karaoke_from_hints`'s name/config/weight-basename
    substring guess, which is unreliable for any model without a curated
    hash-table entry -- i.e. every new community model until someone
    curates it.
    """
    if isinstance(model_data, Mapping):
        # Presence is authoritative: an explicit false is curated metadata,
        # not permission to fall through to an unreliable name-based guess.
        for key in ("is_karaoke", "is_karaokee"):
            if key in model_data:
                return bool(model_data[key]), True
    guess = infer_is_karaoke_from_hints(
        model_name=model_name,
        config_yaml=config_yaml,
        weight_basename=weight_basename,
    )
    return guess, False


def resolve_is_karaoke(
    *,
    model_data: Optional[Mapping] = None,
    model_name: str = "",
    config_yaml: str = "",
    weight_basename: str = "",
) -> bool:
    """Resolve karaoke flag from hash metadata or catalogue/config hints."""
    is_karaoke, _is_curated = resolve_karaoke_confidence(
        model_data=model_data,
        model_name=model_name,
        config_yaml=config_yaml,
        weight_basename=weight_basename,
    )
    return is_karaoke


def is_vocals_other_pair(instruments: Sequence[str]) -> bool:
    if len(instruments) != 2:
        return False
    lowered = {str(name).lower() for name in instruments}
    vocal_side = lowered & {"vocals", "vocal", "voc"}
    return bool(vocal_side) and "other" in lowered


def is_drum_bass_pair(instruments: Sequence[str]) -> bool:
    if len(instruments) != 2:
        return False
    lowered = {str(name).lower() for name in instruments}
    return lowered == {"no drum-bass", "drum-bass"}


def is_special_fx_stem(stem: str) -> bool:
    """True when a yaml/hash stem names a post-processing output (dry, no echo, etc.)."""
    if not stem:
        return False
    low = str(stem).lower().strip()
    if low.startswith("no "):
        return True
    compact = low.replace(" ", "").replace("-", "")
    return compact in _SPECIAL_FX_STEM_COMPACT


def is_specialty_stem(stem: str) -> bool:
    if not stem:
        return False
    return str(stem).lower().strip() in _SPECIALTY_STEMS


def is_specialty_instrument_pair(instruments: Sequence[str]) -> bool:
    if len(instruments) != 2:
        return False
    lowered = frozenset(str(name).lower() for name in instruments)
    return lowered in _SPECIALTY_STEM_PAIRS


def describe_special_fx_stem(stem: str) -> str:
    """Catalogue audit formatter; never a runtime role declaration."""
    if not stem:
        return "Post-processing stem export"
    low = str(stem).lower().strip()
    if low.startswith("no "):
        removed = stem[3:].strip()
        return f"{stem} (mix minus {removed})"
    compact = low.replace(" ", "").replace("-", "")
    labels = {
        "noise": "Noise (isolated noise stem)",
        "reverb": "Reverb (isolated reverb stem)",
        "dry": "Dry (dereverbbed signal)",
        "noreverb": "No reverb (dereverbbed signal)",
        "nodry": "Dry (mix minus wet signal)",
        "noecho": "No echo (mix minus echo)",
    }
    if compact in labels:
        return labels[compact]
    return f"{stem} (post-processing stem)"


def describe_kuielab_component(stem: str) -> str:
    if not stem:
        return "Kuielab Demucs component stem"
    return f"Kuielab Demucs {stem} stem (single 4-stem component)"


def specialty_ui_note(instruments: Sequence[str]) -> str:
    if instruments:
        return f"UI: {' / '.join(str(name) for name in instruments)} subset"
    return "UI: specialty stem subset"


def special_fx_ui_note(primary: str = "", target: str = "") -> str:
    stem = target or primary
    if not stem:
        return "UI: post-processing stem export"
    return f"UI: {stem} / complement stem"


def intent_from_primary_stem(primary: str, *, is_karaoke: bool = False) -> str:
    if not primary:
        return ""
    if is_karaoke:
        return INTENT_KARAOKE
    low = primary.lower()
    if is_vocal_family_stem(primary):
        return INTENT_VOCALS
    if low in ("instrumental", "inst"):
        return INTENT_INSTRUMENTAL
    if low in ("drum-bass", "no drum-bass"):
        return INTENT_DRUM_BASS_SEP
    if low in ("drums", "bass", "piano", "other"):
        return INTENT_MULTI_STEM
    if is_specialty_stem(primary):
        return INTENT_SPECIALTY_STEM
    if is_special_fx_stem(primary):
        return INTENT_SPECIAL_FX
    return ""


def export_intent_from_fields(
    *,
    primary_stem: str = "",
    target: str = "",
    instruments: Optional[Sequence[str]] = None,
    is_karaoke: bool = False,
    weight_basename: str = "",
    catalogue_label: str = "",
) -> str:
    """Infer catalogue-only audit intent from non-manifest metadata fields.

    This preserves source evidence for catalogue review. It must not assign
    runtime roles or presentation labels; those come from exact semantics.
    """
    instruments = list(instruments or [])
    if is_dual_stem_weight(weight_basename):
        return INTENT_DUAL_VOC_INST

    if is_karaoke:
        return INTENT_KARAOKE
    if is_specialty_instrument_pair(instruments):
        return INTENT_SPECIALTY_STEM
    if target:
        t = target.lower()
        if is_vocal_family_stem(target):
            return INTENT_VOCALS
        if t in ("instrumental", "inst"):
            return INTENT_INSTRUMENTAL
        if t == "other":
            if len(instruments) >= 3:
                return INTENT_MULTI_STEM
            if is_vocals_other_pair(instruments):
                return INTENT_INSTRUMENTAL
            if any(is_special_fx_stem(name) for name in instruments):
                return INTENT_SPECIAL_FX
            return INTENT_SPECIALTY_STEM
        if t in ("drum-bass", "no drum-bass"):
            return INTENT_DRUM_BASS_SEP
        if t in ("drums", "bass", "piano"):
            return INTENT_MULTI_STEM
        if is_special_fx_stem(target):
            return INTENT_SPECIAL_FX
        return INTENT_SPECIALTY_STEM
    if is_drum_bass_pair(instruments):
        return INTENT_DRUM_BASS_SEP
    if len(instruments) >= 3:
        return INTENT_MULTI_STEM
    if len(instruments) == 2 and is_vocals_other_pair(instruments):
        if target:
            t = target.lower()
            if t in ("vocals", "vocal"):
                return INTENT_VOCALS
            if t in ("instrumental", "inst", "other"):
                return INTENT_INSTRUMENTAL
        return INTENT_DUAL_VOC_INST
    if primary_stem:
        intent = intent_from_primary_stem(primary_stem, is_karaoke=is_karaoke)
        if intent:
            return intent
    if catalogue_label:
        label_intent = infer_name_intent_from_label(catalogue_label)
        if label_intent != INTENT_UNKNOWN:
            return label_intent
    return INTENT_UNKNOWN


def resolve_catalogue_intent(
    *,
    primary_stem: str = "",
    target: str = "",
    instruments: Optional[Sequence[str]] = None,
    is_karaoke: bool = False,
    weight_basename: str = "",
    catalogue_label: str = "",
    category_intent: str = INTENT_UNKNOWN,
) -> str:
    """Return catalogue audit intent; never a runtime role declaration."""
    from_fields = export_intent_from_fields(
        primary_stem=primary_stem,
        target=target,
        instruments=instruments,
        is_karaoke=is_karaoke,
        weight_basename=weight_basename,
        catalogue_label=catalogue_label,
    )
    if from_fields != INTENT_UNKNOWN:
        return from_fields
    if category_intent and category_intent != INTENT_UNKNOWN:
        return category_intent
    return INTENT_UNKNOWN


def export_intent_from_model(model: typing.Any) -> str:
    """Return an exact reviewed intent for a resolved runtime model.

    Unknown, waived, and signature-mismatched models remain ``unknown``. A
    model name or an ``other`` backend key is not enough to promote an output
    to a canonical runtime role.
    """
    semantics = _model_semantics_projection_source(model)
    if semantics is not None:
        return semantics.intent if semantics.status is StemReviewStatus.REVIEWED else INTENT_UNKNOWN
    if _legacy_identity_unavailable(model):
        return _legacy_export_intent_from_model(model)
    return INTENT_UNKNOWN


def _model_semantics_projection_source(
    model: typing.Any,
) -> ModelStemSemantics | None:
    """Obtain the cached exact runtime projection without display fallbacks."""
    if model is None:
        return None
    from .stems import model_stem_routes

    # The shared route adapter performs exact canonical-ID/signature matching
    # and caches the immutable result on the assembled model.
    model_stem_routes(model)
    semantics = getattr(model, "stem_semantics", None)
    return semantics if isinstance(semantics, ModelStemSemantics) else None


def _legacy_identity_unavailable(model: typing.Any) -> bool:
    """Compatibility boundary for callers that cannot provide a runtime ID.

    Assembled runtime models always carry ``canonical_id`` and consequently
    use the exact projection above. This narrow fallback retains the legacy
    non-runtime inspection API without allowing a raw resolved model to infer
    a reviewed role from a spelling.
    """
    return model is not None and not str(getattr(model, "canonical_id", "") or "")


def _legacy_export_intent_from_model(model: typing.Any) -> str:
    """Compatibility-only audit-style intent for identity-free callers."""
    model_data = getattr(model, "model_data", None)
    config_yaml = str(model_data.get("config_yaml") or "") if model_data else ""
    is_karaoke = bool(getattr(model, "is_karaoke", False)) or resolve_is_karaoke(
        model_data=model_data,
        model_name=str(getattr(model, "model_name", None) or ""),
        config_yaml=config_yaml,
        weight_basename=model_weight_basename(model),
    )
    return export_intent_from_fields(
        primary_stem=str(getattr(model, "primary_stem", None) or ""),
        target=target_instrument(model),
        instruments=training_instruments(model),
        is_karaoke=is_karaoke,
        weight_basename=model_weight_basename(model),
        catalogue_label=str(getattr(model, "model_name", None) or ""),
    )


def stem_display_overrides(model: typing.Any) -> Optional[Dict[str, str]]:
    """Return reviewed native-key -> display overrides for the Save stems UI."""
    semantics = _model_semantics_projection_source(model)
    if semantics is None or semantics.status is not StemReviewStatus.REVIEWED:
        if not _legacy_identity_unavailable(model):
            return None
        overrides: Dict[str, str] = {}
        instruments = training_instruments(model)
        if len(instruments) == 2 and is_vocals_other_pair(instruments):
            overrides.update(VOCALS_OTHER_DISPLAY_OVERRIDES)
        from .stems import karaoke_bv_export_labels

        karaoke_bv = karaoke_bv_export_labels(model)
        if karaoke_bv:
            overrides.update(
                {
                    VOCAL_STEM: karaoke_bv[VOCAL_STEM],
                    INST_STEM: karaoke_bv[INST_STEM],
                    "vocals": karaoke_bv[VOCAL_STEM],
                    "instrumental": karaoke_bv[INST_STEM],
                }
            )
        return overrides or None
    projection = stem_semantics_projection(
        semantics,
        backend_primary=getattr(model, "primary_stem", None),
        backend_target=getattr(model, "target_instrument", None),
    )
    overrides = {
        route.native: route.display
        for route in projection.routes
        if route.native is not None and route.role is not None
    }
    return overrides or None


def vocal_stem_key(model: typing.Any, stems: Optional[Sequence[str]] = None) -> str:
    """Yaml/hash stem name used for vocal quick-export selection, or ``Vocals``."""
    for stem in stems or training_instruments(model):
        if is_vocal_target(stem) or stem == VOCAL_STEM:
            return str(stem)
    primary = str(getattr(model, "primary_stem", "") or "") if model else ""
    if is_vocal_target(primary):
        return primary
    return VOCAL_STEM


def shows_voc_inst_quick_export(model: typing.Any, stems: Sequence[str]) -> bool:
    """Whether the All / Vocals / Instrumental quick-export row applies."""
    if not model or not stems:
        return False
    semantics = _model_semantics_projection_source(model)
    if semantics is None or semantics.status is not StemReviewStatus.REVIEWED:
        if not _legacy_identity_unavailable(model):
            return False
        return _legacy_shows_voc_inst_quick_export(model, stems)
    roles = {
        output.role.value for output in semantics.outputs if isinstance(output.role, StemRoleId)
    }
    return bool(
        any(role.startswith("vocal.") for role in roles)
        and any(role.startswith("mix.instrumental") for role in roles)
    )


def preferred_quick_export_mode(model: typing.Any) -> Optional[str]:
    """Default quick-export mode for subset UI, or ``None`` to keep user settings."""
    semantics = _model_semantics_projection_source(model)
    if semantics is None or semantics.status is not StemReviewStatus.REVIEWED:
        if not _legacy_identity_unavailable(model):
            return None
        return _legacy_preferred_quick_export_mode(model)
    if semantics.intent != INTENT_KARAOKE:
        return None
    if any(
        output.logical_primary
        and isinstance(output.role, StemRoleId)
        and output.role.value.startswith("mix.instrumental")
        for output in semantics.outputs
    ):
        return "instrumental"
    return None


def apply_karaoke_quick_export_default(
    settings: typing.Any,
    model: typing.Any,
    *,
    primary_key: str,
    secondary_key: str,
    stems_key: str = "mdx_stems",
    selected_key: str = "mdx_stems_selected",
) -> bool:
    """Apply instrumental quick-export defaults for vocal-target karaoke models."""
    if preferred_quick_export_mode(model) != "instrumental":
        return False
    stems = list(getattr(model, "mdx_model_stems", []) or [])
    if len(stems) < 3:
        return False
    if settings.get(selected_key):
        return False
    if settings.get(stems_key) not in (ALL_STEMS, None):
        return False
    process = getattr(settings, "process", None)
    if process is not None and str(getattr(process, "stem_focus", "") or ""):
        return False
    if settings.get(primary_key) or settings.get(secondary_key):
        return False
    vocal = vocal_stem_key(model, stems)
    settings.set(selected_key, [vocal])
    settings.set(stems_key, vocal)
    if process is not None:
        process.stem_focus = "mix.instrumental_with_backing_vocals"
    return True


def recommended_export_note(model: typing.Any) -> str:
    """Short reviewed-route hint for Save stems; raw models receive no guess."""
    semantics = _model_semantics_projection_source(model)
    if semantics is None or semantics.status is not StemReviewStatus.REVIEWED:
        return _legacy_recommended_export_note(model) if _legacy_identity_unavailable(model) else ""
    projection = stem_semantics_projection(
        semantics,
        backend_primary=getattr(model, "primary_stem", None),
        backend_target=getattr(model, "target_instrument", None),
    )
    primary = next((route for route in projection.routes if route.logical_primary), None)
    if primary is None or primary.role is None:
        return ""
    labels = " / ".join(route.display for route in projection.routes)
    return f"Reviewed stem routing: {labels}. Logical primary: {primary.display} [{primary.role}]."


def _legacy_shows_voc_inst_quick_export(model: typing.Any, stems: Sequence[str]) -> bool:
    """Compatibility-only quick-export decision for identity-free callers."""
    intent = _legacy_export_intent_from_model(model)
    if intent in (
        INTENT_SPECIALTY_STEM,
        INTENT_SPECIAL_FX,
        INTENT_MULTI_STEM,
        INTENT_DRUM_BASS_SEP,
    ):
        return False
    return any(is_vocal_target(stem) or stem == VOCAL_STEM for stem in stems)


def _legacy_preferred_quick_export_mode(model: typing.Any) -> Optional[str]:
    """Compatibility-only default for identity-free callers."""
    if _legacy_export_intent_from_model(model) != INTENT_KARAOKE:
        return None
    primary = str(getattr(model, "primary_stem", "") or "")
    target = target_instrument(model)
    return "instrumental" if is_vocal_target(primary) or is_vocal_target(target) else None


def _legacy_recommended_export_note(model: typing.Any) -> str:
    """Compatibility-only note for identity-free callers."""
    intent = _legacy_export_intent_from_model(model)
    if intent == INTENT_DUAL_VOC_INST:
        if is_dual_stem_weight(model_weight_basename(model)):
            return "Both Vocals and Instrumental are first-class exports for this model"
        return "Vocals and Instrumental are both valid primary exports"
    if intent == INTENT_KARAOKE:
        primary = str(getattr(model, "primary_stem", "") or "")
        target = target_instrument(model)
        instruments = training_instruments(model)
        side = karaoke_focus_side(primary, target, instruments)
        if side == "vocal":
            return (
                "Karaoke model: Instrumental (backing) is usually the desired export; "
                "Vocals is the isolated vocal stem"
            )
        if side == "inst":
            return "Karaoke model: Instrumental primary; Vocals is the complement stem"
        return "Karaoke model: vocal-side vs backing primary is not classified"
    if intent == INTENT_DRUM_BASS_SEP:
        return "Drum/bass separation model — pick No Drum-Bass or Drum-Bass"
    if intent == INTENT_INSTRUMENTAL and target_instrument(model).lower() == "other":
        return "Instrumental model: Vocals + Instrumental (Instrumental is the backing track)"
    if intent == INTENT_SPECIAL_FX:
        stem = target_instrument(model) or str(getattr(model, "primary_stem", "") or "")
        if str(stem).lower() == "other":
            sibling = next(
                (name for name in training_instruments(model) if is_special_fx_stem(name)),
                "",
            )
            if sibling:
                return describe_special_fx_stem(sibling)
        if stem:
            return describe_special_fx_stem(stem)
        return "Post-processing stem export"
    if intent == INTENT_SPECIALTY_STEM:
        instruments = training_instruments(model)
        if instruments:
            names = " / ".join(format_specialty_instrument_name(name) for name in instruments)
            return (
                f"Specialty stems: export {names} "
                "individually (not Vocals/Instrumental quick export)"
            )
        return "Specialty stem model — use per-stem subset export"
    return ""


def format_specialty_instrument_name(name: str) -> str:
    """Readable specialty stem label without mangling existing capitalization."""
    text = str(name).strip().replace("_", " ")
    if not text:
        return text
    if any(ch.isupper() for ch in text):
        return text
    return " ".join(part.capitalize() for part in text.split())


def infer_name_intent_from_label(label: str) -> str:
    """Infer intent from a Download Center catalogue label (generator helper)."""
    text = label.lower()
    if "karaoke" in text:
        return INTENT_KARAOKE
    if any(h in text for h in _DRUM_BASS_HINTS):
        return INTENT_DRUM_BASS_SEP
    if "instvoc" in text or "duality" in text:
        return INTENT_DUAL_VOC_INST
    if any(pattern in text for pattern in _DUAL_VOC_INST_LABELS) and "inst main" not in text:
        return INTENT_DUAL_VOC_INST
    multi_hints = (
        "4-stem",
        "4 stem",
        "4stems",
        "scnet",
        "kuielab",
        "demucs",
        "bandit",
        "drums",
        "bass",
        "speech",
        "music",
        "effects",
        "sfx",
        "ensemble",
    )
    if any(h in text for h in multi_hints):
        return INTENT_MULTI_STEM
    if any(h in text for h in _EARLY_SPECIAL_FX_LABEL_HINTS):
        return INTENT_SPECIAL_FX
    if any(h in text for h in _SPECIALTY_LABEL_HINTS):
        return INTENT_SPECIALTY_STEM
    inst_hints = (
        "inst",
        "instrumental",
        "instr",
        "hp-uvr",
        "hp2-uvr",
        "hp uvr",
        "fno",
        "metal",
        "drumsep",
        "drum sep",
        "instvoc",
        "mgm",
        "sp-uvr",
        "sp_uvr",
        "bleed suppressor",
    )
    vocal_hints = (
        "vocal",
        "voc ",
        " voc",
        "syhft",
        "bleedless",
        "fullness",
        "revive",
        "resurrection vocals",
        "big beta",
        "big syhft",
        " kim | ft",
        "| ft ",
        "sdr 1143",
        "sdr 1296",
        "sdr 1297",
    )
    if "instrumental" in text:
        vocal_hints = tuple(h for h in vocal_hints if h != "bleedless")
    inst = any(h in text for h in inst_hints)
    vocal = any(h in text for h in vocal_hints)
    if inst and vocal:
        return INTENT_DUAL_VOC_INST
    if inst:
        return INTENT_INSTRUMENTAL
    if vocal:
        return INTENT_VOCALS
    if any(h in text for h in _SPECIAL_FX_LABEL_HINTS) or "uvr-de" in text:
        return INTENT_SPECIAL_FX
    if "crowd" in text:
        return INTENT_SPECIALTY_STEM
    if "mdx-net 1" in text or "mdx-net 2" in text or "mdx-net 3" in text:
        return INTENT_VOCALS
    if "mdxnet_9482" in text or "d1581" in text:
        return INTENT_VOCALS
    return INTENT_UNKNOWN


def normalize_stem_label(stem: str) -> str:
    if not stem:
        return ""
    if is_vocal_family_stem(stem):
        return VOCAL_STEM
    low = stem.lower()
    if low in ("instrumental", "inst"):
        return INST_STEM
    if low == "other":
        return "Other"
    return stem


def confident_stem_bucket(
    stem: str,
    *,
    stem_count: int,
    is_karaoke: bool,
    is_karaoke_curated: bool,
    is_bv: bool,
) -> str:
    """``bucket_for_model_stem``, but a guessed (non-curated) ``is_karaoke``
    is never passed through as ``True``.

    ``bucket_for_model_stem(stem, is_karaoke=False, is_bv=False)`` already
    falls through to the plain alias-table lookup by default -- that *is*
    the safe fallback for an uncurated model's stems, so nothing else is
    needed here beyond gating the one boolean that isn't always reliable.
    ``is_bv`` needs no such gate: it is only ever set from curated
    metadata, never guessed.
    """
    from core.stems import bucket_for_model_stem

    return bucket_for_model_stem(
        stem,
        stem_count=stem_count,
        is_karaoke=is_karaoke and is_karaoke_curated,
        is_bv=is_bv,
    ).value


def _karaoke_stem_token(stem: str) -> str:
    return str(stem).lower().strip().replace(" ", "_").replace("-", "_")


_KARAOKE_BACKING_TOKENS = frozenset(
    {
        "back_instrum",
        "backing",
        "backing_instrumental",
        "instrumental_backing",
        "backing_track",
    }
)


def karaoke_focus_side(
    primary: str,
    target: str,
    instruments: Sequence[str] = (),
) -> str:
    """``vocal``, ``inst``, or ``unknown`` for a karaoke model's named primary."""
    stem = target or primary
    token = _karaoke_stem_token(stem)
    if is_vocal_family_stem(stem) or token == "lead":
        return "vocal"
    if token in _KARAOKE_BACKING_TOKENS:
        return "inst"
    if token in ("instrumental", "inst", "instrument"):
        return "inst"
    if token == "other" and is_vocals_other_pair(instruments):
        return "inst"
    return "unknown"


def backend_focus_label(
    primary: str,
    target: str,
    instruments: Sequence[str],
    *,
    is_karaoke: bool = False,
) -> str:
    """Catalogue helper: summarize backend primary/target focus."""
    if is_karaoke:
        side = karaoke_focus_side(primary, target, instruments)
        if side == "vocal":
            return "karaoke_vocal_primary"
        if side == "inst":
            return "karaoke_instrumental_primary"
        return "karaoke_unknown_primary"
    if target:
        norm = normalize_stem_label(target)
        if is_vocal_family_stem(target) or norm == VOCAL_STEM:
            return "vocal_target"
        if norm == INST_STEM:
            return "instrumental_target"
        if target.lower() == "other":
            if is_vocals_other_pair(instruments):
                return "instrumental_target_other_yaml"
            sibling = next(
                (name for name in instruments if is_special_fx_stem(name)),
                "",
            )
            if sibling:
                return f"special_fx_target:{sibling}"
            if len(instruments) >= 3:
                return INTENT_MULTI_STEM
            return f"single_target:{target}"
        if target.lower() in ("drum-bass", "no drum-bass"):
            return "drum_bass_target"
        if is_special_fx_stem(target):
            return f"special_fx_target:{target}"
        if is_specialty_stem(target):
            return f"specialty_target:{target}"
        return f"single_target:{target}"
    if is_drum_bass_pair(instruments):
        return INTENT_DRUM_BASS_SEP
    if is_specialty_instrument_pair(instruments):
        return "specialty_two_stem"
    if len(instruments) >= 3:
        return INTENT_MULTI_STEM
    if len(instruments) == 2:
        return "two_stem"
    if primary:
        norm = normalize_stem_label(primary)
        if norm == VOCAL_STEM:
            return "vocal_primary"
        if norm == INST_STEM:
            return "instrumental_primary"
        if is_special_fx_stem(primary):
            return f"special_fx_primary:{primary}"
        if is_specialty_stem(primary):
            return f"specialty_primary:{primary}"
        low = str(primary).lower()
        if low in ("bass", "drums", "other"):
            return f"demucs_component:{primary}"
    return INTENT_UNKNOWN
