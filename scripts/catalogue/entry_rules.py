"""Entry rules for the one-snapshot catalogue publication pipeline."""

from __future__ import annotations

import re
from typing import (
    Any,
    Dict,
    List,
    Tuple,
)

from bundled.constants import INST_STEM, VOCAL_STEM
from catalogue.types import CommunityRef, ModelEntry
from core.model_stem_semantics import (
    INTENT_MULTI_STEM,
    INTENT_SPECIALTY_STEM,
    INTENT_UNKNOWN,
    backend_focus_label,
    describe_kuielab_component,
    describe_special_fx_stem,
    export_intent_from_fields,
    infer_name_intent_from_label,
    intent_from_primary_stem,
    is_dual_stem_weight,
    is_special_fx_stem,
    is_vocal_target,
    normalize_stem_label,
    resolve_is_karaoke,
    special_fx_ui_note,
    specialty_ui_note,
)


def _apply_entry_meta(entry: ModelEntry, meta: Any) -> None:
    """Fill blanks from the snapshot's per-entry metadata.

    Runs after metadata_source has already defaulted to "unavailable", so
    anything supplied here has to claim provenance for itself -- otherwise the
    entry is excluded from _flag_mismatches and under-counts in the summary
    despite having real metadata.
    """
    if meta is None:
        return
    supplied = False
    stems = list(getattr(meta, "stems", None) or [])
    if stems and not entry.instruments:
        entry.instruments = stems
        entry.stem_count = max(entry.stem_count, len(stems))
        supplied = True
    target = getattr(meta, "target_instrument", None) or ""
    if target and not entry.target_instrument:
        entry.target_instrument = str(target)
        if not entry.primary_stem:
            entry.primary_stem = str(target)
        supplied = True
    intent = str(getattr(meta, "intent", "") or "")
    if intent and intent != INTENT_UNKNOWN and entry.name_intent == "unknown":
        entry.name_intent = intent
        # Deliberately not `supplied`: intent alone cannot resolve a backend
        # focus, so claiming provenance for it would let _flag_mismatches
        # compare a real intent against an unknown backend and invent a flag.
    if supplied and entry.metadata_source in ("", "unavailable"):
        entry.metadata_source = "catalogue_meta"


def _intent_from_primary_stem(primary: str, *, is_karaoke: bool = False) -> str:
    return intent_from_primary_stem(primary, is_karaoke=is_karaoke) or ""


def _intent_from_community_stems(stems_text: str) -> Tuple[str, str]:
    """Return (intent, primary_stem) from community stems column."""
    text = stems_text.strip()
    if not text or text.lower() == "unknown":
        return "", ""
    match = re.search(r"([^,]+?)\*", text)
    primary = match.group(1).strip() if match else ""
    if not primary:
        primary = re.split(r",\s*", text)[0].strip()
    primary = re.sub(r"\s*\([^)]*\)\s*$", "", primary).strip()
    intent = _intent_from_primary_stem(primary)
    if intent == "multi_stem" and "*" in text:
        if any(k in text.lower() for k in ("vocals", "instrumental", "other")):
            if "vocals" in primary.lower():
                intent = "vocals"
            elif "instrumental" in primary.lower() or primary.lower() == "other":
                intent = "instrumental"
    return intent, primary


def _parse_community_model_lines(lines: Any) -> Tuple[Dict[str, CommunityRef], bool]:
    """Parse the community table without mistaking malformed rows for an empty table."""
    refs: Dict[str, CommunityRef] = {}
    for line in lines:
        line = line.rstrip()
        if not line or line.startswith("#") or line.startswith("-"):
            continue
        if set(line) <= {"-"}:
            continue
        if "Model Filename" in line or "Output Stems" in line:
            continue
        parts = re.split(r"\s{2,}", line.strip())
        if len(parts) < 4:
            return {}, False
        filename, arch, stems_text, friendly = parts[0], parts[1], parts[2], parts[3]
        if not arch or not stems_text or not friendly:
            return {}, False
        if not filename.endswith((".pth", ".onnx", ".ckpt", ".th")):
            # Demucs configuration YAMLs share this otherwise valid table.
            # They are not model-weight references, so preserve the legacy
            # parser behavior: retain evidence availability but omit them from
            # the weight-keyed community projection.
            continue
        intent, primary = _intent_from_community_stems(stems_text)
        refs[filename.lower()] = CommunityRef(
            filename=filename,
            arch=arch,
            primary_stem=primary,
            stems_text=stems_text,
            friendly_name=friendly,
            intent=intent,
        )
    return refs, True


def _parse_community_models_bytes(data: bytes) -> Tuple[Dict[str, CommunityRef], bool]:
    """Return parsed community evidence and whether the payload was valid."""
    try:
        return _parse_community_model_lines(data.decode("utf-8").splitlines())
    except UnicodeDecodeError:
        return {}, False


def _infer_name_intent(label: str) -> str:
    return infer_name_intent_from_label(label)


def _infer_intent_from_metadata(entry: ModelEntry) -> str:
    intent = export_intent_from_fields(
        primary_stem=entry.primary_stem,
        target=entry.target_instrument,
        instruments=entry.instruments,
        is_karaoke=entry.is_karaoke,
        weight_basename=entry.weight_file,
        catalogue_label=entry.catalogue_label,
    )
    return intent if intent != INTENT_UNKNOWN else ""


def _normalize_stem(stem: str) -> str:
    return normalize_stem_label(stem)


def _backend_focus(primary: str, target: str, instruments: List[str], *, is_karaoke: bool) -> str:
    return backend_focus_label(primary, target, instruments, is_karaoke=is_karaoke)


def _best_result(entry: ModelEntry) -> str:
    if entry.name_intent == "karaoke":
        if entry.backend_focus == "karaoke_vocal_primary":
            return "Karaoke vocals (Vocals primary; complement = instrumental backing)"
        return "Karaoke backing (Instrumental primary; complement = lead vocals)"
    if entry.name_intent == "drum_bass_sep":
        primary = entry.target_instrument or entry.primary_stem or "No Drum-Bass"
        return f"{primary} (drum/bass separation; complement = Drum-Bass)"
    if entry.name_intent == "dual_voc_inst":
        if is_dual_stem_weight(entry.weight_file):
            return "Vocals or Instrumental — both are first-class 2-stem exports"
        return "User picks Vocals or Instrumental (dual 2-stem)"
    if entry.name_intent == "specialty_stem":
        if entry.instruments:
            return ", ".join(entry.instruments)
        stem = entry.target_instrument or entry.primary_stem
        if stem:
            return f"{stem} (specialty stem export)"
        return "Specialty stem export"
    if entry.name_intent == "special_fx":
        stem = entry.target_instrument or entry.primary_stem
        if stem:
            return describe_special_fx_stem(stem)
        if entry.instruments:
            return ", ".join(entry.instruments)
        return "Post-processing stem export"
    if "kuielab" in entry.catalogue_label.lower() and entry.primary_stem:
        if entry.primary_stem.lower() in ("vocals", "vocal"):
            return "Vocals (+ Instrumental complement)"
        return describe_kuielab_component(entry.primary_stem)
    if entry.name_intent == "multi_stem" and entry.instruments:
        return f"Multi-stem: {', '.join(entry.instruments)}"
    if entry.target_instrument:
        t = entry.target_instrument.lower()
        if t in ("vocals", "vocal"):
            return "Vocals (complement = Instrumental)"
        if t in ("instrumental", "inst"):
            return "Instrumental (complement = Vocals)"
        if t == "other":
            return "Instrumental (yaml `other`; complement = vocals)"
        if is_special_fx_stem(entry.target_instrument):
            return describe_special_fx_stem(entry.target_instrument)
        return f"{entry.target_instrument} (single native output)"
    if entry.primary_stem:
        p = _normalize_stem(entry.primary_stem)
        if p == VOCAL_STEM:
            return "Vocals (+ Instrumental complement)"
        if p == INST_STEM:
            return "Instrumental (+ Vocals complement)"
        if is_special_fx_stem(entry.primary_stem):
            return describe_special_fx_stem(entry.primary_stem)
        if entry.stem_count == 1:
            return entry.primary_stem
    if entry.instruments:
        return ", ".join(entry.instruments)
    return entry.name_intent


def _ui_note(entry: ModelEntry) -> str:
    if (
        len(entry.instruments) == 2
        and entry.instruments
        and {"vocals", "other"} <= {s.lower() for s in entry.instruments}
    ):
        return "UI: Vocals / Instrumental (yaml `other` is the backing track)"
    if entry.name_intent == "specialty_stem":
        return specialty_ui_note(entry.instruments)
    if entry.name_intent == "special_fx":
        return special_fx_ui_note(entry.primary_stem, entry.target_instrument)
    if entry.name_intent == "drum_bass_sep":
        return "UI: No Drum-Bass / Drum-Bass subset"
    if entry.name_intent == "dual_voc_inst":
        return "UI: Vocals / Instrumental (either stem is a valid primary export)"
    if entry.target_instrument and entry.target_instrument.lower() in ("vocals", "vocal"):
        return "UI: Vocals / Instrumental"
    if entry.target_instrument and entry.target_instrument.lower() in (
        "instrumental",
        "inst",
        "other",
    ):
        return "UI: Instrumental / Vocals (yaml `other` relabeled as Instrumental)"
    if entry.primary_stem in (VOCAL_STEM, INST_STEM):
        return f"UI: {entry.primary_stem} / complement"
    if is_special_fx_stem(entry.primary_stem) or is_special_fx_stem(entry.target_instrument):
        return special_fx_ui_note(entry.primary_stem, entry.target_instrument)
    if entry.stem_count >= 3:
        return "UI: per-stem subset or focus row"
    return ""


def _intent_compatible(intent: str, focus: str) -> bool:
    if intent in ("dual_voc_inst", "drum_bass_sep", "unknown"):
        return True
    if intent == "multi_stem":
        return focus.startswith((INTENT_MULTI_STEM, "demucs_component:")) or focus == INTENT_UNKNOWN
    if intent == "special_fx":
        return focus.startswith(("special_fx_", "single_target:")) or focus == INTENT_UNKNOWN
    if intent == "specialty_stem":
        return focus.startswith(("specialty_", "single_target:", "two_stem"))
    if intent == "karaoke":
        return focus.startswith("karaoke_")
    if intent == "instrumental":
        return focus.startswith("instrumental") or focus.startswith("single_target")
    if intent == "vocals":
        return focus.startswith("vocal")
    return True


def _is_vocals_instrumental_pair(instruments: List[str]) -> bool:
    if len(instruments) != 2:
        return False
    lowered = {str(name).lower() for name in instruments}
    return (
        lowered <= {"vocals", "instrumental", "vocal", "inst"}
        or lowered <= {"vocals", "other"}
        or lowered <= {"vocal", "other"}
    )


def _flag_mismatches(entry: ModelEntry) -> List[str]:
    if not entry.metadata_source or entry.metadata_source == "unavailable":
        return []
    if not entry.backend_focus or entry.backend_focus == "unknown":
        # No backend to disagree with; every comparison below would be noise.
        return []
    flags: List[str] = []
    intent = entry.name_intent
    focus = entry.backend_focus
    if not _intent_compatible(intent, focus):
        if intent == "instrumental" and focus.startswith("vocal"):
            flags.append("NAME says instrumental but backend is vocal-focused")
        elif intent == "vocals" and focus.startswith("instrumental"):
            flags.append("NAME says vocal but backend is instrumental-focused")
        elif intent == "karaoke" and not focus.startswith("karaoke_"):
            flags.append("NAME says karaoke but backend is not karaoke-focused")
        elif intent == "vocals" and not focus.startswith("vocal"):
            flags.append("NAME says vocals but backend is not vocal-focused")
        elif intent == "specialty_stem" and not focus.startswith(("specialty_", "single_target:")):
            flags.append("NAME says specialty stem but backend focus differs")
    if (
        intent == "vocals"
        and focus == "two_stem"
        and not _is_vocals_instrumental_pair(entry.instruments)
    ):
        flags.append("NAME says vocals but backend is specialty 2-stem")
    if intent == "vocals" and focus.startswith("single_target:"):
        stem = focus.split(":", 1)[-1]
        if not is_vocal_target(stem):
            flags.append(f"NAME says vocals but native target is {stem}")
    if intent == "instrumental" and entry.target_instrument.lower() in ("vocals", "vocal"):
        flags.append("target_instrument=Vocals on instrumental-named model")
    if intent == "vocals" and entry.target_instrument.lower() in ("other", "instrumental", "inst"):
        if not (
            intent == "vocals"
            and entry.target_instrument.lower() == "other"
            and "inst" in entry.catalogue_label.lower()
        ):
            flags.append("target_instrument is non-vocal on vocal-named model")
    return flags


def _infer_onnx_meta(filename: str, label: str) -> Tuple[str, bool, str]:
    low = f"{filename} {label}".lower()
    if "kara_2" in low or "karaoke 2" in low:
        return INST_STEM, True, "onnx_name_heuristic"
    if "kara" in low:
        return VOCAL_STEM, True, "onnx_name_heuristic"
    if any(
        k in low
        for k in (
            "kim_vocal",
            "voc_ft",
            "vocals",
            "_voc",
            "mdxnet_1",
            "mdxnet_2",
            "mdxnet_3",
            "9482",
        )
    ):
        return VOCAL_STEM, False, "onnx_name_heuristic"
    if any(k in low for k in ("kim_inst", "inst_", "_inst", "inst main", "crowd", "reverb")):
        if "reverb" in low:
            return "Reverb", False, "onnx_name_heuristic"
        return INST_STEM, False, "onnx_name_heuristic"
    if "kuielab" in low:
        for stem in ("vocals", "drums", "bass", "other"):
            if stem in low:
                return stem.title() if stem != "other" else "Other", False, "onnx_name_heuristic"
    return "", False, ""


def _infer_vr_meta(filename: str, label: str) -> Tuple[str, bool, str]:
    low = f"{filename} {label}".lower()
    if "karaoke" in low:
        return INST_STEM, True, "vr_name_heuristic"
    if any(k in low for k in ("hp-vocal", "hp_vocal", "bve", "vocal")):
        return VOCAL_STEM, False, "vr_name_heuristic"
    if any(
        k in low
        for k in ("hp-uvr", "hp2-uvr", "hp_uvr", "hp2_uvr", "wind_inst", "mgm", "sp-uvr", "sp_uvr")
    ):
        return INST_STEM, False, "vr_name_heuristic"
    if any(k in low for k in ("deecho", "de-echo", "dereverb", "denoise", "deverb")):
        return "No Reverb", False, "vr_name_heuristic"
    return "", False, ""


def _apply_community_ref(meta: ModelEntry, ref: CommunityRef) -> None:
    cleaned_primary = ref.primary_stem
    if cleaned_primary:
        if cleaned_primary.lower() in ("instrumental", "inst"):
            meta.primary_stem = INST_STEM
        elif cleaned_primary.lower() in ("vocals", "vocal"):
            meta.primary_stem = VOCAL_STEM
        else:
            meta.primary_stem = cleaned_primary
        meta.stem_count = max(meta.stem_count, 2)
    if not meta.metadata_source or meta.metadata_source == "unavailable":
        meta.metadata_source = "community_models.txt"
    if ref.intent == "karaoke" or "karaoke" in meta.catalogue_label.lower():
        meta.is_karaoke = True
    if is_dual_stem_weight(meta.weight_file):
        meta.name_intent = "dual_voc_inst"
        meta.notes.append("Both Vocals and Instrumental are first-class exports")
    elif ref.intent and meta.name_intent == "unknown":
        meta.name_intent = ref.intent
    if ref.stems_text and ref.stems_text.lower() != "unknown":
        meta.notes.append(f"Community ref: {ref.stems_text}")


def _finalize_entry(meta: ModelEntry) -> None:
    if not meta.is_karaoke and resolve_is_karaoke(
        model_name=meta.catalogue_label,
        weight_basename=meta.weight_file,
    ):
        meta.is_karaoke = True
    metadata_intent = _infer_intent_from_metadata(meta)
    if meta.name_intent == "unknown" and metadata_intent:
        meta.name_intent = metadata_intent
        meta.notes.append(f"Intent inferred from metadata ({metadata_intent})")
    elif metadata_intent and meta.name_intent != metadata_intent:
        if meta.name_intent == "special_fx" and metadata_intent in (
            "vocals",
            "instrumental",
            "dual_voc_inst",
        ):
            meta.name_intent = metadata_intent
            meta.notes.append(f"Name intent corrected from metadata ({metadata_intent})")
        elif meta.name_intent == "instrumental" and metadata_intent == "special_fx":
            meta.name_intent = metadata_intent
            meta.notes.append(f"Name intent corrected from metadata ({metadata_intent})")
        elif meta.name_intent == "vocals" and metadata_intent in (
            INTENT_SPECIALTY_STEM,
            "special_fx",
        ):
            meta.name_intent = metadata_intent
            meta.notes.append(f"Name intent corrected from metadata ({metadata_intent})")
    meta.backend_focus = _backend_focus(
        meta.primary_stem, meta.target_instrument, meta.instruments, is_karaoke=meta.is_karaoke
    )
    meta.best_result = meta.best_result_override or _best_result(meta)
    meta.ui_export_note = _ui_note(meta)
    meta.flags = _flag_mismatches(meta)
    if meta.target_instrument.lower() == "other" and meta.name_intent == "instrumental":
        meta.notes.append("Expected: inst models use yaml stem `other` (UI: Vocals / Instrumental)")
