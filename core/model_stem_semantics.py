"""Shared stem export semantics for runtime UI and the model catalogue generator.

Derives display-label overrides and export intent from resolved model metadata
(yaml instruments, hash primary_stem, karaoke flags) without reading generated docs.
"""

from __future__ import annotations

from typing import Dict, List, Mapping, Optional, Sequence, Set

from bundled.constants import ALL_STEMS, INST_STEM, NO_OTHER_STEM, NO_STEM, OTHER_STEM, VOCAL_STEM

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


def model_weight_basename(model) -> str:
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


def training_instruments(model) -> List[str]:
    if model is None:
        return []
    configs = getattr(model, "mdx_c_configs", None)
    training = getattr(configs, "training", None) if configs is not None else None
    if training is None:
        stems = getattr(model, "mdx_model_stems", None) or []
        return list(stems)
    instruments = getattr(training, "instruments", None) or []
    return [str(name) for name in instruments]


def target_instrument(model) -> str:
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


def is_instrumental_target(stem: str) -> bool:
    if not stem:
        return False
    low = str(stem).lower()
    return low in ("instrumental", "inst", "other")


def infer_is_karaoke_from_hints(
    *,
    model_name: str = "",
    config_yaml: str = "",
    weight_basename: str = "",
) -> bool:
    """Infer karaoke intent from catalogue label, config name, or weight basename."""
    text = " ".join(
        part for part in (model_name, config_yaml, weight_basename) if part
    ).lower()
    return "karaoke" in text


def resolve_is_karaoke(
    *,
    model_data: Optional[Mapping] = None,
    model_name: str = "",
    config_yaml: str = "",
    weight_basename: str = "",
) -> bool:
    """Resolve karaoke flag from hash metadata or catalogue/config hints."""
    if model_data:
        if model_data.get("is_karaoke") or model_data.get("is_karaokee"):
            return True
    return infer_is_karaoke_from_hints(
        model_name=model_name,
        config_yaml=config_yaml,
        weight_basename=weight_basename,
    )


def is_vocals_other_pair(instruments: Sequence[str]) -> bool:
    lowered = {str(name).lower() for name in instruments}
    return {"vocals", "other"} <= lowered


def is_drum_bass_pair(instruments: Sequence[str]) -> bool:
    lowered = {str(name).lower() for name in instruments}
    return bool({"no drum-bass", "drum-bass"} & lowered)


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
    """Human-readable best-result line for FX / subtraction primaries."""
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
    if low in ("vocals", "vocal"):
        return INTENT_VOCALS
    if low in ("instrumental", "inst"):
        return INTENT_INSTRUMENTAL
    if "drum" in low and "bass" in low:
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
    """Infer export intent from model metadata fields."""
    instruments = list(instruments or [])
    if is_dual_stem_weight(weight_basename):
        return INTENT_DUAL_VOC_INST

    if is_karaoke:
        return INTENT_KARAOKE
    if is_specialty_instrument_pair(instruments):
        return INTENT_SPECIALTY_STEM
    if target:
        t = target.lower()
        if t in ("vocals", "vocal"):
            return INTENT_VOCALS
        if t in ("instrumental", "inst", "other"):
            return INTENT_INSTRUMENTAL
        if "drum" in t and "bass" in t:
            return INTENT_DRUM_BASS_SEP
        if t in ("drums", "bass", "piano"):
            return INTENT_MULTI_STEM
        if t == "guitar":
            return INTENT_SPECIALTY_STEM
        if is_specialty_stem(target):
            return INTENT_SPECIALTY_STEM
        if is_special_fx_stem(target):
            return INTENT_SPECIAL_FX
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


def export_intent_from_model(model) -> str:
    """Infer export intent from a resolved :class:`ModelData` instance."""
    if model is None:
        return INTENT_UNKNOWN
    model_data = getattr(model, "model_data", None)
    config_yaml = ""
    if model_data:
        config_yaml = str(model_data.get("config_yaml") or "")
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


def stem_display_overrides(model) -> Optional[Dict[str, str]]:
    """Return per-stem display-label overrides for Save stems UI."""
    if model is None:
        return None
    instruments = training_instruments(model)
    if len(instruments) == 2 and is_vocals_other_pair(instruments):
        return dict(VOCALS_OTHER_DISPLAY_OVERRIDES)
    return None


def vocal_stem_key(model, stems: Optional[Sequence[str]] = None) -> str:
    """Yaml/hash stem name used for vocal quick-export selection, or ``Vocals``."""
    for stem in stems or training_instruments(model):
        if is_vocal_target(stem) or stem == VOCAL_STEM:
            return str(stem)
    primary = str(getattr(model, "primary_stem", "") or "") if model else ""
    if is_vocal_target(primary):
        return primary
    return VOCAL_STEM


def shows_voc_inst_quick_export(model, stems: Sequence[str]) -> bool:
    """Whether the All / Vocals / Instrumental quick-export row applies."""
    if not model or not stems:
        return False
    intent = export_intent_from_model(model)
    if intent in (
        INTENT_SPECIALTY_STEM,
        INTENT_SPECIAL_FX,
        INTENT_MULTI_STEM,
        INTENT_DRUM_BASS_SEP,
    ):
        return False
    return any(is_vocal_target(stem) or stem == VOCAL_STEM for stem in stems)


def preferred_quick_export_mode(model) -> Optional[str]:
    """Default quick-export mode for subset UI, or ``None`` to keep user settings."""
    if export_intent_from_model(model) != INTENT_KARAOKE:
        return None
    primary = str(getattr(model, "primary_stem", "") or "")
    target = target_instrument(model)
    if is_vocal_target(primary) or is_vocal_target(target):
        return "instrumental"
    return None


def apply_karaoke_quick_export_default(
    settings,
    model,
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
    if settings.get(primary_key) or settings.get(secondary_key):
        return False
    vocal = vocal_stem_key(model, stems)
    settings.set(selected_key, [vocal])
    settings.set(stems_key, vocal)
    settings.set(primary_key, False)
    settings.set(secondary_key, True)
    return True


def recommended_export_note(model) -> str:
    """Short UX hint for Save stems when intent differs from a single primary stem."""
    intent = export_intent_from_model(model)
    if intent == INTENT_DUAL_VOC_INST:
        if is_dual_stem_weight(model_weight_basename(model)):
            return "Both Vocals and Instrumental are first-class exports for this model."
        return "Vocals and Instrumental are both valid primary exports."
    if intent == INTENT_KARAOKE:
        primary = str(getattr(model, "primary_stem", "") or "")
        target = target_instrument(model)
        if is_vocal_target(primary) or is_vocal_target(target):
            return (
                "Karaoke model: Instrumental (backing) is usually the desired export; "
                "Vocals is the isolated vocal stem."
            )
        if is_instrumental_target(primary) or is_instrumental_target(target):
            return "Karaoke model: Instrumental primary; Vocals is the complement stem."
        return "Karaoke model: instrumental backing is typically the desired export."
    if intent == INTENT_DRUM_BASS_SEP:
        return "Drum/bass separation model — pick No Drum-Bass or Drum-Bass."
    if intent == INTENT_INSTRUMENTAL and target_instrument(model).lower() == "other":
        return "Instrumental model: Vocals + Instrumental (Instrumental is the backing track)."
    if intent == INTENT_SPECIAL_FX:
        stem = target_instrument(model) or str(getattr(model, "primary_stem", "") or "")
        if stem:
            return describe_special_fx_stem(stem)
        return "Post-processing stem export."
    if intent == INTENT_SPECIALTY_STEM:
        instruments = training_instruments(model)
        if instruments:
            names = " / ".join(format_specialty_instrument_name(name) for name in instruments)
            return (
                f"Specialty stems: export {names} "
                "individually (not Vocals/Instrumental quick export)."
            )
        return "Specialty stem model — use per-stem subset export."
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
        "4-stem", "4 stem", "4stems", "scnet", "kuielab", "demucs", "bandit",
        "drums", "bass", "speech", "music", "effects", "sfx", "ensemble",
    )
    if any(h in text for h in multi_hints):
        return INTENT_MULTI_STEM
    if any(h in text for h in _EARLY_SPECIAL_FX_LABEL_HINTS):
        return INTENT_SPECIAL_FX
    if any(h in text for h in _SPECIALTY_LABEL_HINTS):
        return INTENT_SPECIALTY_STEM
    inst_hints = (
        "inst", "instrumental", "instr", "hp-uvr", "hp2-uvr", "hp uvr",
        "fno", "metal", "drumsep", "drum sep",
        "instvoc", "mgm", "sp-uvr", "sp_uvr", "bleed suppressor",
    )
    vocal_hints = (
        "vocal", "voc ", " voc", "syhft",
        "bleedless", "fullness", "revive", "resurrection vocals",
        "big beta", "big syhft",
        " kim | ft", "| ft ", "sdr 1143", "sdr 1296", "sdr 1297",
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
    low = stem.lower()
    if low in ("vocals", "vocal", "voc"):
        return VOCAL_STEM
    if low in ("instrumental", "inst"):
        return INST_STEM
    if low == "other":
        return "Other"
    return stem


def backend_focus_label(
    primary: str,
    target: str,
    instruments: Sequence[str],
    *,
    is_karaoke: bool = False,
) -> str:
    """Catalogue helper: summarize backend primary/target focus."""
    if is_karaoke:
        if normalize_stem_label(primary) == VOCAL_STEM or normalize_stem_label(target) == VOCAL_STEM:
            return "karaoke_vocal_primary"
        if normalize_stem_label(primary) == INST_STEM or normalize_stem_label(target) == INST_STEM:
            return "karaoke_instrumental_primary"
        return "karaoke_instrumental_primary"
    if target:
        norm = normalize_stem_label(target)
        if norm == VOCAL_STEM:
            return "vocal_target"
        if norm == INST_STEM:
            return "instrumental_target"
        if target.lower() == "other":
            return "instrumental_target_other_yaml"
        if "drum" in target.lower() and "bass" in target.lower():
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
