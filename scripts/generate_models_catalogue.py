#!/usr/bin/env python3
"""Generate docs/models-catalogue.md from TRvlvr + Politrees download catalogues.

Audits stem metadata (primary_stem / target_instrument) against catalogue naming
intent so mislabeled vocal vs instrumental models can be spotted.
"""

from __future__ import annotations

import json
import os
import re
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from bundled.constants import INST_STEM, VOCAL_STEM  # noqa: E402
from core import paths  # noqa: E402
from core.mdx_c_registry import compute_checkpoint_hash, infer_mdx_c_architecture, sanitize_catalogue_label  # noqa: E402
from core.model_data import load_mdx_c_config, load_model_hash_data, _mdx_c_training  # noqa: E402
from core.model_stem_semantics import (  # noqa: E402
    INTENT_INSTRUMENTAL,
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
    is_specialty_instrument_pair,
    is_vocal_target,
    normalize_stem_label,
    resolve_is_karaoke,
    special_fx_ui_note,
    specialty_ui_note,
)
from core.politrees_catalog import merge_politrees_catalogues  # noqa: E402

OUTPUT_PATH = os.path.join(ROOT, "docs", "models-catalogue.md")
REFERENCE_TSV_PATH = os.path.join(ROOT, "docs", "model_intent_reference.tsv")
YAML_CACHE_DIR = os.path.join(ROOT, "docs", ".yaml_cache")
POLITREES_CACHE_DIR = os.path.join(ROOT, "docs", ".politrees_cache")
COMMUNITY_CACHE_DIR = os.path.join(ROOT, "docs", ".community_cache")

_POLITREES_VR_DATA_URL = (
    "https://raw.githubusercontent.com/Politrees/UVR_resources/main/UVR_resources/model_data/vr_model_data.json"
)
_POLITREES_MDX_DATA_URL = (
    "https://raw.githubusercontent.com/Politrees/UVR_resources/main/UVR_resources/model_data/mdx_model_data.json"
)
_COMMUNITY_MODELS_URL = (
    "https://raw.githubusercontent.com/upseem/uvr5-cli-no-ui/main/models.txt"
)

_POLITREES_KEYS = (
    "mdx_download_list",
    "mdx23c_download_list",
    "roformer_download_list",
    "scnet_download_list",
    "bandit_download_list",
)


@dataclass
class CommunityRef:
    filename: str
    arch: str
    primary_stem: str
    stems_text: str
    friendly_name: str
    intent: str = ""


@dataclass
class CatalogueContext:
    community_by_file: Dict[str, CommunityRef] = field(default_factory=dict)
    vr_by_hash: Dict[str, dict] = field(default_factory=dict)
    mdx_by_hash: Dict[str, dict] = field(default_factory=dict)
    weight_to_hash: Dict[str, str] = field(default_factory=dict)


@dataclass
class ModelEntry:
    source: str
    family: str
    catalogue_label: str
    weight_file: str
    config_yaml: str = ""
    config_url: str = ""
    arch: str = ""
    primary_stem: str = ""
    secondary_stem: str = ""
    instruments: List[str] = field(default_factory=list)
    target_instrument: str = ""
    stem_count: int = 0
    is_karaoke: bool = False
    name_intent: str = ""
    best_result: str = ""
    backend_focus: str = ""
    ui_export_note: str = ""
    metadata_source: str = ""
    flags: List[str] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)


def _load_trvlvr_catalogue() -> dict:
    with open(paths.DOWNLOAD_MODEL_CACHE_PATH, encoding="utf-8") as handle:
        return json.load(handle)


def _load_politrees_catalogue() -> Optional[dict]:
    path = os.path.join(ROOT, "politrees_model_links.json")
    if not os.path.isfile(path):
        return None
    with open(path, encoding="utf-8") as handle:
        payload = json.load(handle)
    return payload.get("data") if isinstance(payload, dict) else payload


def _merged_catalogues() -> Tuple[dict, dict, dict]:
    trvlvr = _load_trvlvr_catalogue()
    politrees = _load_politrees_catalogue()
    vr = dict(trvlvr.get("vr_download_list", {}))
    mdx = dict(trvlvr.get("mdx_download_list", {}))
    mdx.update(trvlvr.get("mdx23_download_list", {}))
    mdx.update(trvlvr.get("mdx23c_download_list", {}))
    demucs = dict(trvlvr.get("demucs_download_list", {}))
    vr, mdx, demucs = merge_politrees_catalogues(vr, mdx, demucs, politrees)
    for key in _POLITREES_KEYS:
        if politrees and key in politrees:
            for label, entry in politrees[key].items():
                if label not in mdx:
                    mdx[label] = entry
    return vr, mdx, demucs


def _fetch_cached(url: str, cache_dir: str, filename: str) -> Optional[str]:
    os.makedirs(cache_dir, exist_ok=True)
    cache_path = os.path.join(cache_dir, filename)
    if os.path.isfile(cache_path):
        return cache_path
    try:
        with urllib.request.urlopen(url, timeout=30) as response:
            data = response.read()
        with open(cache_path, "wb") as handle:
            handle.write(data)
        return cache_path
    except (urllib.error.URLError, OSError, TimeoutError):
        return cache_path if os.path.isfile(cache_path) else None


def _load_json_cache(url: str, cache_dir: str, filename: str) -> dict:
    path = _fetch_cached(url, cache_dir, filename)
    if not path:
        return {}
    try:
        with open(path, encoding="utf-8") as handle:
            payload = json.load(handle)
        return payload if isinstance(payload, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def _merge_hash_tables(local_path: str, remote: dict) -> dict:
    merged: dict = {}
    if os.path.isfile(local_path):
        try:
            merged.update(load_model_hash_data(local_path))
        except (FileNotFoundError, ValueError, json.JSONDecodeError):
            pass
    merged.update(remote)
    return merged


def _scan_weight_hashes(*weight_dirs: str) -> Dict[str, str]:
    index: Dict[str, str] = {}
    for weight_dir in weight_dirs:
        if not os.path.isdir(weight_dir):
            continue
        for name in os.listdir(weight_dir):
            if not name.endswith((".pth", ".onnx", ".ckpt", ".th")):
                continue
            digest = compute_checkpoint_hash(os.path.join(weight_dir, name))
            if digest:
                index[name.lower()] = digest
    return index


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


def _parse_community_models_txt(path: str) -> Dict[str, CommunityRef]:
    refs: Dict[str, CommunityRef] = {}
    if not os.path.isfile(path):
        return refs
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            line = line.rstrip()
            if not line or line.startswith("#") or line.startswith("-"):
                continue
            if set(line) <= {"-"}:
                continue
            if "Model Filename" in line or "Output Stems" in line:
                continue
            parts = re.split(r"\s{2,}", line.strip())
            if len(parts) < 4:
                continue
            filename, arch, stems_text, friendly = parts[0], parts[1], parts[2], parts[3]
            if not filename.endswith((".pth", ".onnx", ".ckpt", ".th")):
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
    return refs


def _write_reference_tsv(refs: Dict[str, CommunityRef]) -> None:
    rows = sorted(refs.values(), key=lambda item: item.filename.lower())
    lines = ["filename\tarch\tprimary_stem\tintent\tstems\tfriendly_name"]
    for ref in rows:
        lines.append(
            "\t".join(
                [
                    ref.filename,
                    ref.arch,
                    ref.primary_stem,
                    ref.intent or "unknown",
                    ref.stems_text.replace("\t", " "),
                    ref.friendly_name.replace("\t", " "),
                ]
            )
        )
    os.makedirs(os.path.dirname(REFERENCE_TSV_PATH), exist_ok=True)
    with open(REFERENCE_TSV_PATH, "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")


def _build_catalogue_context() -> CatalogueContext:
    remote_vr = _load_json_cache(_POLITREES_VR_DATA_URL, POLITREES_CACHE_DIR, "vr_model_data.json")
    remote_mdx = _load_json_cache(_POLITREES_MDX_DATA_URL, POLITREES_CACHE_DIR, "mdx_model_data.json")
    community_path = _fetch_cached(_COMMUNITY_MODELS_URL, COMMUNITY_CACHE_DIR, "models.txt")
    community = _parse_community_models_txt(community_path or "")
    if community:
        _write_reference_tsv(community)
    return CatalogueContext(
        community_by_file=community,
        vr_by_hash=_merge_hash_tables(paths.VR_HASH_JSON, remote_vr),
        mdx_by_hash=_merge_hash_tables(paths.MDX_HASH_JSON, remote_mdx),
        weight_to_hash=_scan_weight_hashes(paths.VR_MODELS_DIR, paths.MDX_MODELS_DIR),
    )


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
    if entry.target_instrument and entry.target_instrument.lower() in ("instrumental", "inst", "other"):
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
    if intent == "vocals" and focus == "two_stem" and not _is_vocals_instrumental_pair(entry.instruments):
        flags.append("NAME says vocals but backend is specialty 2-stem")
    if intent == "vocals" and focus.startswith("single_target:"):
        stem = focus.split(":", 1)[-1]
        if not is_vocal_target(stem):
            flags.append(f"NAME says vocals but native target is {stem}")
    if intent == "instrumental" and entry.target_instrument.lower() in ("vocals", "vocal"):
        flags.append("target_instrument=Vocals on instrumental-named model")
    if intent == "vocals" and entry.target_instrument.lower() in ("other", "instrumental", "inst"):
        if not (intent == "vocals" and entry.target_instrument.lower() == "other" and "inst" in entry.catalogue_label.lower()):
            flags.append("target_instrument is non-vocal on vocal-named model")
    return flags


def _yaml_paths(yaml_name: str) -> List[str]:
    return [
        os.path.join(paths.MDX_C_CONFIG_PATH, yaml_name),
        os.path.join(ROOT, "models", "MDX_Net_Models", "model_data", "mdx_c_configs", yaml_name),
        os.path.join(YAML_CACHE_DIR, yaml_name),
    ]


def _fetch_yaml(url: str, yaml_name: str) -> Optional[str]:
    if not url or not yaml_name.endswith(".yaml"):
        return None
    return _fetch_cached(url, YAML_CACHE_DIR, yaml_name)


def _training_fields(training: Any) -> Tuple[List[str], str]:
    if training is None:
        return [], ""
    if isinstance(training, dict):
        instruments = list(training.get("instruments") or [])
        target = training.get("target_instrument") or ""
        return instruments, str(target) if target else ""
    instruments = list(getattr(training, "instruments", None) or [])
    target = getattr(training, "target_instrument", None) or ""
    return instruments, str(target) if target else ""


def _load_yaml_meta(yaml_name: str, yaml_url: str = "") -> Tuple[List[str], str, str, str]:
    if not yaml_name:
        return [], "", "", ""
    config_path = ""
    for candidate in _yaml_paths(yaml_name):
        if os.path.isfile(candidate):
            config_path = candidate
            break
    source = ""
    if not config_path and yaml_url:
        fetched = _fetch_yaml(yaml_url, yaml_name)
        if fetched:
            config_path = fetched
            source = f"remote_yaml:{yaml_name}"
    elif config_path:
        if YAML_CACHE_DIR in config_path:
            source = f"remote_yaml:{yaml_name}"
        else:
            source = f"bundled_yaml:{yaml_name}"
    if not config_path:
        inferred = _infer_from_yaml_name(yaml_name)
        if inferred[0] or inferred[1]:
            return inferred[0], inferred[1], inferred[2], f"yaml_name_heuristic:{yaml_name}"
        return [], "", "", ""
    try:
        config = load_mdx_c_config(config_path)
        training = _mdx_c_training(config)
        instruments, target = _training_fields(training)
        arch, _ = infer_mdx_c_architecture(yaml_name)
        if not arch and isinstance(config, dict):
            model = config.get("model") or {}
            if "num_bands" in model:
                arch = "Mel-Band Roformer"
            elif "freqs_per_bands" in model:
                arch = "BS Roformer"
        return instruments, target, arch, source
    except Exception:
        inferred = _infer_from_yaml_name(yaml_name)
        if inferred[0] or inferred[1]:
            return inferred[0], inferred[1], inferred[2], f"yaml_name_heuristic:{yaml_name}"
        return [], "", "", source or "yaml_parse_failed"


def _infer_from_yaml_name(yaml_name: str) -> Tuple[List[str], str, str]:
    low = yaml_name.lower()
    arch, _ = infer_mdx_c_architecture(yaml_name)
    if "4stem" in low or "4_stem" in low or "musdb18" in low or "dnr_bandit" in low:
        return [], "", arch
    if any(k in low for k in ("instvoc", "duality", "2_stem", "2stem")):
        return ["instrumental", "vocals"], "", arch
    if any(k in low for k in ("inst", "instrumental", "fno", "crowd", "guitar", "metal")):
        return ["other", "vocals"], "other", arch
    if any(k in low for k in ("voc", "karaoke", "aspiration", "bve", "revive", "chorus", "male_female", "big_beta", "kim_ft")):
        return ["other", "vocals"], "vocals", arch
    if any(k in low for k in ("dereverb", "deverb", "denoise", "echo", "bleed")):
        return ["no_reverb"], "no_reverb", arch
    return [], "", arch


def _hash_lookup_local(weight_path: str, hash_json_path: str) -> Optional[dict]:
    if not os.path.isfile(weight_path) or not os.path.isfile(hash_json_path):
        return None
    digest = compute_checkpoint_hash(weight_path)
    if not digest:
        return None
    data = load_model_hash_data(hash_json_path)
    return data.get(digest)


def _lookup_hash_row(
    weight_file: str,
    ctx: CatalogueContext,
    *,
    prefer_vr: bool,
) -> Tuple[Optional[dict], str]:
    digest = ctx.weight_to_hash.get(weight_file.lower())
    if not digest:
        return None, ""
    if prefer_vr and digest in ctx.vr_by_hash:
        return ctx.vr_by_hash[digest], "politrees_vr_hash"
    if digest in ctx.mdx_by_hash:
        return ctx.mdx_by_hash[digest], "politrees_mdx_hash"
    if digest in ctx.vr_by_hash:
        return ctx.vr_by_hash[digest], "politrees_vr_hash"
    return None, ""


def _apply_hash_row(meta: ModelEntry, row: dict, source: str) -> None:
    meta.metadata_source = source
    if row.get("primary_stem"):
        meta.primary_stem = row["primary_stem"]
        meta.stem_count = 2
    meta.is_karaoke = bool(row.get("is_karaoke"))
    if row.get("config_yaml") and not meta.config_yaml:
        meta.config_yaml = row["config_yaml"]


def _infer_onnx_meta(filename: str, label: str) -> Tuple[str, bool, str]:
    low = f"{filename} {label}".lower()
    if "kara_2" in low or "karaoke 2" in low:
        return INST_STEM, True, "onnx_name_heuristic"
    if "kara" in low:
        return VOCAL_STEM, True, "onnx_name_heuristic"
    if any(k in low for k in ("kim_vocal", "voc_ft", "vocals", "_voc", "mdxnet_1", "mdxnet_2", "mdxnet_3", "9482")):
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
    if any(k in low for k in ("hp-uvr", "hp2-uvr", "hp_uvr", "hp2_uvr", "wind_inst", "mgm", "sp-uvr", "sp_uvr")):
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
    meta.best_result = _best_result(meta)
    meta.ui_export_note = _ui_note(meta)
    meta.flags = _flag_mismatches(meta)
    if meta.target_instrument.lower() == "other" and meta.name_intent == "instrumental":
        meta.notes.append("Expected: inst models use yaml stem `other` (UI: Vocals / Instrumental)")


def _parse_catalogue_entry(
    *,
    source: str,
    family: str,
    label: str,
    payload: Any,
    ctx: CatalogueContext,
    hash_json: str = "",
    weight_dir: str = "",
) -> List[ModelEntry]:
    yaml_name = ""
    yaml_url = ""
    weight = ""
    if isinstance(payload, str):
        weight = payload
    elif isinstance(payload, dict):
        for key, ref in payload.items():
            if key.endswith(".yaml"):
                yaml_name = key
                if isinstance(ref, str) and ref.startswith("http"):
                    yaml_url = ref
            elif key.endswith((".pth", ".onnx", ".ckpt", ".th")):
                weight = key

    meta = ModelEntry(
        source=source,
        family=family,
        catalogue_label=label,
        weight_file=weight,
        config_yaml=yaml_name,
        config_url=yaml_url,
    )
    meta.name_intent = _infer_name_intent(label)

    if yaml_name:
        instruments, target, arch, yaml_source = _load_yaml_meta(yaml_name, yaml_url)
        meta.instruments = instruments
        meta.target_instrument = target
        meta.arch = arch
        meta.stem_count = len(instruments) or (1 if target else 0)
        if target:
            meta.primary_stem = target
        elif instruments:
            meta.primary_stem = instruments[0]
        if yaml_source:
            meta.metadata_source = yaml_source

    prefer_vr = family == "VR Architecture"
    if weight:
        row, row_source = _lookup_hash_row(weight, ctx, prefer_vr=prefer_vr)
        if row:
            _apply_hash_row(meta, row, row_source)
        elif hash_json and weight_dir:
            full = os.path.join(weight_dir, weight)
            row = _hash_lookup_local(full, hash_json)
            if row:
                _apply_hash_row(meta, row, "hash_json")

    if weight:
        ref = ctx.community_by_file.get(weight.lower())
        if ref:
            _apply_community_ref(meta, ref)

    if not meta.metadata_source and weight:
        if weight.endswith(".onnx"):
            stem, karaoke, src = _infer_onnx_meta(weight, label)
            if stem:
                meta.primary_stem = stem
                meta.is_karaoke = karaoke
                meta.metadata_source = src
                meta.stem_count = 2
        elif weight.endswith(".pth"):
            stem, karaoke, src = _infer_vr_meta(weight, label)
            if stem:
                meta.primary_stem = stem
                meta.is_karaoke = karaoke
                meta.metadata_source = src
                meta.stem_count = 2

    if is_dual_stem_weight(weight):
        meta.name_intent = "dual_voc_inst"
        if "Both Vocals and Instrumental are first-class exports" not in meta.notes:
            meta.notes.append("Both Vocals and Instrumental are first-class exports")

    if not meta.metadata_source:
        meta.metadata_source = "unavailable"

    _finalize_entry(meta)
    return [meta]


_TRVLVR_KEYS = (
    "vr_download_list",
    "mdx_download_list",
    "mdx23_download_list",
    "mdx23c_download_list",
    "demucs_download_list",
)


def _source_for(label: str, politrees: Optional[dict], trvlvr: dict) -> str:
    """Attribute ``label`` to TRvlvr, Politrees, or both, by catalogue membership."""
    in_pt = False
    if politrees:
        for key in ("vr_download_list", *_POLITREES_KEYS, "demucs_download_list"):
            if label in (politrees.get(key) or {}):
                in_pt = True
                break
    in_tr = any(label in trvlvr.get(key, {}) for key in _TRVLVR_KEYS)
    if in_pt and not in_tr:
        return "Politrees"
    if in_pt and in_tr:
        return "TRvlvr+Politrees"
    return "TRvlvr"


def _collect_entries(ctx: CatalogueContext) -> List[ModelEntry]:
    vr_cat, mdx_cat, demucs_cat = _merged_catalogues()
    politrees = _load_politrees_catalogue()
    trvlvr = _load_trvlvr_catalogue()
    all_entries: List[ModelEntry] = []

    for label, payload in sorted(vr_cat.items()):
        all_entries.extend(
            _parse_catalogue_entry(
                source=_source_for(label, politrees, trvlvr),
                family="VR Architecture",
                label=label,
                payload=payload,
                ctx=ctx,
                hash_json=paths.VR_HASH_JSON,
                weight_dir=paths.VR_MODELS_DIR,
            )
        )

    family_map = [
        ("MDX-Net Model", "MDX-Net ONNX"),
        ("MDX23 Model", "MDX23C"),
        ("MDX23C Model", "MDX23C"),
        ("Roformer Model", "Roformer"),
        ("SCnet:", "SCNet"),
        ("Bandit", "Bandit"),
    ]

    for label, payload in sorted(mdx_cat.items()):
        family = "MDX-Net"
        for prefix, fam in family_map:
            if label.startswith(prefix):
                family = fam
                break
        all_entries.extend(
            _parse_catalogue_entry(
                source=_source_for(label, politrees, trvlvr),
                family=family,
                label=label,
                payload=payload,
                ctx=ctx,
                hash_json=paths.MDX_HASH_JSON if family == "MDX-Net ONNX" else "",
                weight_dir=paths.MDX_MODELS_DIR,
            )
        )

    for label, payload in sorted(demucs_cat.items()):
        all_entries.extend(
            _parse_catalogue_entry(
                source=_source_for(label, politrees, trvlvr),
                family="Demucs",
                label=label,
                payload=payload,
                ctx=ctx,
            )
        )
        entry = all_entries[-1]
        if "UVR Model" in label or "uvr" in label.lower():
            entry.instruments = ["instrumental", "vocals"]
            entry.stem_count = 2
            entry.best_result = "2-stem: instrumental + vocals (user picks focus)"
            entry.name_intent = "dual_voc_inst"
        elif "6s" in label:
            entry.instruments = ["drums", "bass", "other", "vocals", "guitar", "piano"]
            entry.stem_count = 6
            entry.best_result = "6-stem Demucs"
            entry.name_intent = "multi_stem"
        else:
            entry.instruments = ["drums", "bass", "other", "vocals"]
            entry.stem_count = 4
            entry.best_result = "4-stem Demucs"
            entry.name_intent = "multi_stem"
        entry.metadata_source = "demucs_heuristic"
        entry.backend_focus = "multi_stem"

    return all_entries


def _md_table(headers: List[str], rows: List[List[str]]) -> str:
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join(["---"] * len(headers)) + " |",
    ]
    for row in rows:
        safe = [str(cell).replace("|", "\\|").replace("\n", " ") for cell in row]
        lines.append("| " + " | ".join(safe) + " |")
    return "\n".join(lines)


def _render(entries: List[ModelEntry]) -> str:
    flagged = [e for e in entries if e.flags]
    unknown = [e for e in entries if e.name_intent == "unknown"]
    with_meta = [e for e in entries if e.metadata_source not in ("unavailable", "")]
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    lines = [
        "# UVR Model Catalogue (TRvlvr + Politrees)",
        "",
        f"Generated: {now} by `scripts/generate_models_catalogue.py`.",
        "",
        "Regenerate after catalogue updates:",
        "",
        "```bash",
        "python scripts/generate_models_catalogue.py",
        "```",
        "",
        "Intent sources: catalogue label, yaml/hash metadata, Politrees model_data,",
        "and [upseem/uvr5-cli-no-ui models.txt](https://github.com/upseem/uvr5-cli-no-ui/blob/main/models.txt)",
        f"(cached as `{os.path.relpath(REFERENCE_TSV_PATH, ROOT)}`).",
        "",
        "## How to read this",
        "",
        "- **Name intent** — from label, metadata, or community reference.",
        "- **Backend focus** — what `ModelConfig` uses as `primary_stem` at runtime.",
        "- **Best result** — the stem users typically want from that model name.",
        "- **Flags** — vocal/instrumental labelling mismatches (only when metadata resolved).",
        "",
        "### Roformer `other` yaml quirk (not a bug)",
        "",
        "Instrumental Mel-Band / BS models often use `target_instrument: other` with",
        "`instruments: [other, vocals]`. That is a **2-stem vocal/instrumental** split.",
        "The GUI should show **Vocals** / **Instrumental** for 2-stem yaml pairs, not Demucs Other.",
        "",
        "## Summary",
        "",
        f"- Total catalogue entries: **{len(entries)}**",
        f"- Entries with resolved metadata: **{len(with_meta)}**",
        f"- Unknown intent remaining: **{len(unknown)}**",
        f"- Flagged mismatches: **{len(flagged)}**",
        "",
    ]

    if unknown:
        lines.extend(
            [
                "## Models with unknown intent",
                "",
                _md_table(
                    ["Family", "Model", "Metadata", "Primary/Target"],
                    [
                        [
                            e.family,
                            sanitize_catalogue_label(e.catalogue_label),
                            e.metadata_source,
                            e.target_instrument or e.primary_stem or "—",
                        ]
                        for e in unknown
                    ],
                ),
                "",
            ]
        )

    lines.extend(
        [
            "## Quick reference (all models)",
            "",
            _md_table(
                ["Family", "Model", "Intent", "Best result", "Backend", "Target", "Flags"],
                [
                    [
                        e.family,
                        sanitize_catalogue_label(e.catalogue_label)[:60],
                        e.name_intent,
                        (e.best_result[:50] + "…") if len(e.best_result) > 50 else e.best_result,
                        e.backend_focus,
                        e.target_instrument or e.primary_stem,
                        "; ".join(e.flags) or "—",
                    ]
                    for e in entries
                ],
            ),
            "",
        ]
    )

    karaoke_models = [e for e in entries if e.name_intent == "karaoke" or e.is_karaoke]
    if karaoke_models:
        lines.extend(
            [
                "## Karaoke models",
                "",
                "Karaoke models differ by architecture: VR HP-Karaoke uses **Instrumental** as",
                "`primary_stem`; MDX-Net Karaoke uses **Vocals** with `is_karaoke: true`.",
                "Roformer karaoke yamls typically target **vocals** (lead) with instrumental complement.",
                "",
                _md_table(
                    ["Model", "Primary", "Karaoke flag", "Best result"],
                    [
                        [
                            sanitize_catalogue_label(e.catalogue_label),
                            e.primary_stem or e.target_instrument,
                            "yes" if e.is_karaoke else "—",
                            e.best_result,
                        ]
                        for e in karaoke_models
                    ],
                ),
                "",
            ]
        )

    other_yaml_inst = [
        e
        for e in entries
        if e.name_intent == "instrumental"
        and e.target_instrument.lower() == "other"
    ]
    if other_yaml_inst:
        lines.extend(
            [
                "## Instrumental models with yaml stem `other`",
                "",
                "These models are **instrumental-first** in practice. The training yaml names the",
                "native output `other` (not `Instrumental`). Backend `primary_stem` is therefore",
                "`other`, which previously showed as Demucs-style “Other” in the GUI. Relabel to",
                "**Vocals** / **Instrumental** (yaml `other` is the backing track).",
                "",
                _md_table(
                    ["Model", "Config", "Instruments", "Best result"],
                    [
                        [
                            sanitize_catalogue_label(e.catalogue_label),
                            e.config_yaml,
                            ", ".join(e.instruments),
                            e.best_result,
                        ]
                        for e in other_yaml_inst
                    ],
                ),
                "",
            ]
        )

    if flagged:
        lines.extend(
            [
                "## Flagged mismatches",
                "",
                _md_table(
                    ["Label", "Intent", "Backend", "Target/Primary", "Best result", "Flags"],
                    [
                        [
                            sanitize_catalogue_label(e.catalogue_label),
                            e.name_intent,
                            e.backend_focus,
                            e.target_instrument or e.primary_stem,
                            e.best_result,
                            "; ".join(e.flags),
                        ]
                        for e in flagged
                    ],
                ),
                "",
            ]
        )

    current_family = None
    for entry in entries:
        if entry.family != current_family:
            current_family = entry.family
            lines.extend([f"## {current_family} (detail)", ""])
        short = sanitize_catalogue_label(entry.catalogue_label)
        lines.append(f"### {short}")
        lines.append("")
        lines.append(f"- **Source:** {entry.source}")
        lines.append(f"- **Weight:** `{entry.weight_file}`")
        if entry.config_yaml:
            lines.append(f"- **Config:** `{entry.config_yaml}`")
        if entry.arch:
            lines.append(f"- **Architecture:** {entry.arch}")
        lines.append(f"- **Name intent:** {entry.name_intent}")
        lines.append(f"- **Backend focus:** {entry.backend_focus}")
        if entry.primary_stem:
            lines.append(f"- **Primary stem (backend):** `{entry.primary_stem}`")
        if entry.instruments:
            lines.append(f"- **Instruments:** {', '.join(entry.instruments)}")
        if entry.target_instrument:
            lines.append(f"- **Target instrument:** `{entry.target_instrument}`")
        if entry.is_karaoke:
            lines.append("- **Karaoke model:** yes")
        lines.append(f"- **Best result:** {entry.best_result}")
        if entry.ui_export_note:
            lines.append(f"- **Save stems UI:** {entry.ui_export_note}")
        lines.append(f"- **Metadata:** {entry.metadata_source}")
        for note in entry.notes:
            lines.append(f"- **Note:** {note}")
        if entry.flags:
            lines.append(f"- **⚠ Flags:** {'; '.join(entry.flags)}")
        lines.append("")

    return "\n".join(lines)


def main() -> int:
    ctx = _build_catalogue_context()
    entries = _collect_entries(ctx)
    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as handle:
        handle.write(_render(entries))
    flagged = sum(1 for e in entries if e.flags)
    unknown = sum(1 for e in entries if e.name_intent == "unknown")
    with_meta = sum(1 for e in entries if e.metadata_source not in ("unavailable", ""))
    print(
        f"Wrote {OUTPUT_PATH} ({len(entries)} models, {with_meta} with metadata, "
        f"{unknown} unknown, {flagged} flagged)"
    )
    if os.path.isfile(REFERENCE_TSV_PATH):
        print(f"Wrote {REFERENCE_TSV_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
