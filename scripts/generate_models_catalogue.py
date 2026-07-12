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
from typing import Dict, List, Optional, Tuple

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from bundled.constants import INST_STEM, VOCAL_STEM  # noqa: E402
from core import paths  # noqa: E402
from core.mdx_c_registry import infer_mdx_c_architecture, sanitize_catalogue_label  # noqa: E402
from core.model_data import load_mdx_c_config, load_model_hash_data, _mdx_c_training  # noqa: E402
from core.politrees_catalog import merge_politrees_catalogues  # noqa: E402

OUTPUT_PATH = os.path.join(ROOT, "docs", "models-catalogue.md")
YAML_CACHE_DIR = os.path.join(ROOT, "docs", ".yaml_cache")

_POLITREES_KEYS = (
    "mdx_download_list",
    "mdx23c_download_list",
    "roformer_download_list",
    "scnet_download_list",
    "bandit_download_list",
)

_VOCAL_HINTS = (
    "vocal",
    "voc ",
    " voc",
    "lead",
    "chorus",
    "aspiration",
    "bve",
    "syhft",
    "bleedless",
    "fullness",
    "revive",
    "resurrection vocals",
    "male-female",
    "male female",
    "phantom",
    "centre",
    "center",
)
_INST_HINTS = (
    "inst",
    "instrumental",
    "instr",
    "hp-uvr",
    "hp2-uvr",
    "hp uvr",
    "wind_inst",
    "crowd",
    "fno",
    "guitar",
    "metal",
    "drumsep",
    "drum sep",
    "duality",
    "instvoc",
    "main",
    "mgm_main",
)
_SPECIAL_HINTS = (
    "dereverb",
    "de-reverb",
    "deverb",
    "denoise",
    "de-echo",
    "deecho",
    "reverb",
    "echo",
    "noise",
    "bleed",
    "suppressor",
)
_MULTI_HINTS = (
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


def _infer_name_intent(label: str) -> str:
    text = label.lower()
    if "karaoke" in text and "fusion" not in text:
        return "karaoke"
    if any(h in text for h in _MULTI_HINTS):
        if "instvoc" in text or "duality" in text:
            return "dual_voc_inst"
        return "multi_stem"
    if any(h in text for h in _SPECIAL_HINTS):
        return "special_fx"
    inst = any(h in text for h in _INST_HINTS)
    vocal = any(h in text for h in _VOCAL_HINTS)
    if inst and vocal:
        return "dual_voc_inst"
    if inst:
        return "instrumental"
    if vocal:
        return "vocals"
    return "unknown"


def _normalize_stem(stem: str) -> str:
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


def _backend_focus(primary: str, target: str, instruments: List[str], *, is_karaoke: bool) -> str:
    if is_karaoke:
        if _normalize_stem(primary) == VOCAL_STEM or _normalize_stem(target) == VOCAL_STEM:
            return "karaoke_vocal_primary"
        return "karaoke_instrumental_primary"
    if target:
        norm = _normalize_stem(target)
        if norm == VOCAL_STEM:
            return "vocal_target"
        if norm == INST_STEM:
            return "instrumental_target"
        if target.lower() == "other":
            return "instrumental_target_other_yaml"
        return f"single_target:{target}"
    if len(instruments) >= 3:
        return "multi_stem"
    if len(instruments) == 2:
        return "two_stem"
    if primary:
        norm = _normalize_stem(primary)
        if norm == VOCAL_STEM:
            return "vocal_primary"
        if norm == INST_STEM:
            return "instrumental_primary"
    return "unknown"


def _best_result(entry: ModelEntry) -> str:
    if entry.name_intent == "karaoke":
        if entry.backend_focus == "karaoke_vocal_primary":
            return "Karaoke vocals (Vocals primary; complement = instrumental backing)"
        return "Karaoke backing (Instrumental primary; complement = lead vocals)"
    if entry.name_intent == "dual_voc_inst":
        return "User picks Vocals or Instrumental (dual 2-stem)"
    if entry.target_instrument:
        t = entry.target_instrument.lower()
        if t in ("vocals", "vocal"):
            return "Vocals (complement = Instrumental)"
        if t in ("instrumental", "inst"):
            return "Instrumental (complement = Vocals)"
        if t == "other":
            return "Instrumental (yaml `other`; complement = vocals)"
        return f"{entry.target_instrument} (single native output)"
    if entry.primary_stem:
        p = _normalize_stem(entry.primary_stem)
        if p == VOCAL_STEM:
            return "Vocals (+ Instrumental complement)"
        if p == INST_STEM:
            return "Instrumental (+ Vocals complement)"
        if entry.stem_count == 1:
            return entry.primary_stem
    if entry.instruments:
        return ", ".join(entry.instruments)
    return entry.name_intent


def _ui_note(entry: ModelEntry) -> str:
    if entry.instruments and {"vocals", "other"} <= {s.lower() for s in entry.instruments}:
        return "UI: Lead Vocals / Mix minus Lead Vocals (roformer vocals+other yaml)"
    if entry.target_instrument and entry.target_instrument.lower() in ("vocals", "vocal"):
        return "UI: Vocals / Instrumental"
    if entry.target_instrument and entry.target_instrument.lower() in ("instrumental", "inst", "other"):
        return "UI: Instrumental / Vocals (or Lead Vocals relabel for `other`)"
    if entry.primary_stem in (VOCAL_STEM, INST_STEM):
        return f"UI: {entry.primary_stem} / complement"
    if entry.stem_count >= 3:
        return "UI: per-stem subset or focus row"
    return ""


def _intent_compatible(intent: str, focus: str) -> bool:
    if intent in ("multi_stem", "special_fx", "dual_voc_inst", "unknown"):
        return True
    if intent == "karaoke":
        return focus.startswith("karaoke_")
    if intent == "instrumental":
        return focus.startswith("instrumental") or focus.startswith("single_target")
    if intent == "vocals":
        return focus.startswith("vocal")
    return True


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
    os.makedirs(YAML_CACHE_DIR, exist_ok=True)
    cache_path = os.path.join(YAML_CACHE_DIR, yaml_name)
    if os.path.isfile(cache_path):
        return cache_path
    try:
        with urllib.request.urlopen(url, timeout=20) as response:
            data = response.read()
        with open(cache_path, "wb") as handle:
            handle.write(data)
        return cache_path
    except (urllib.error.URLError, OSError, TimeoutError):
        return None


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
        from ml_collections import ConfigDict

        config = ConfigDict(load_mdx_c_config(config_path))
        training = _mdx_c_training(config)
        if training is None:
            return [], "", "", source
        instruments = list(getattr(training, "instruments", None) or [])
        target = getattr(training, "target_instrument", None) or ""
        arch, _ = infer_mdx_c_architecture(yaml_name)
        return instruments, str(target) if target else "", arch, source
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
    if any(k in low for k in ("voc", "karaoke", "aspiration", "bve", "revive", "chorus", "male_female")):
        return ["other", "vocals"], "vocals", arch
    if any(k in low for k in ("dereverb", "deverb", "denoise", "echo", "bleed")):
        return ["no_reverb"], "no_reverb", arch
    return [], "", arch


def _hash_lookup(weight_path: str, hash_json_path: str) -> Optional[dict]:
    if not os.path.isfile(weight_path) or not os.path.isfile(hash_json_path):
        return None
    from core.mdx_c_registry import compute_checkpoint_hash

    digest = compute_checkpoint_hash(weight_path)
    if not digest:
        return None
    data = load_model_hash_data(hash_json_path)
    return data.get(digest)


def _infer_onnx_meta(filename: str, label: str) -> Tuple[str, bool, str]:
    low = f"{filename} {label}".lower()
    if "kara" in low:
        return VOCAL_STEM, True, "onnx_name_heuristic"
    if any(k in low for k in ("kim_vocal", "voc_ft", "vocals", "_voc")):
        return VOCAL_STEM, False, "onnx_name_heuristic"
    if any(k in low for k in ("kim_inst", "inst_", "_inst", "main", "crowd")):
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
    if any(k in low for k in ("hp-uvr", "hp2-uvr", "hp_uvr", "hp2_uvr", "wind_inst", "mgm_main", "main")):
        return INST_STEM, False, "vr_name_heuristic"
    if any(k in low for k in ("deecho", "de-echo", "dereverb", "denoise", "deverb")):
        return "No Reverb", False, "vr_name_heuristic"
    return "", False, ""


def _parse_catalogue_entry(
    *,
    source: str,
    family: str,
    label: str,
    payload,
    hash_json: str = "",
    weight_dir: str = "",
) -> List[ModelEntry]:
    entries: List[ModelEntry] = []
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
    elif hash_json and weight_dir and weight:
        full = os.path.join(weight_dir, weight)
        row = _hash_lookup(full, hash_json)
        if row:
            meta.primary_stem = row.get("primary_stem", "")
            meta.is_karaoke = bool(row.get("is_karaoke"))
            meta.metadata_source = "hash_json"
            meta.stem_count = 2

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

    if not meta.metadata_source:
        meta.metadata_source = "unavailable"

    meta.backend_focus = _backend_focus(
        meta.primary_stem, meta.target_instrument, meta.instruments, is_karaoke=meta.is_karaoke
    )
    meta.best_result = _best_result(meta)
    meta.ui_export_note = _ui_note(meta)
    meta.flags = _flag_mismatches(meta)

    if meta.target_instrument.lower() == "other" and meta.name_intent == "instrumental":
        meta.notes.append("Expected: inst models use yaml stem `other` (not Demucs Other)")

    entries.append(meta)
    return entries


def _collect_entries() -> List[ModelEntry]:
    vr_cat, mdx_cat, demucs_cat = _merged_catalogues()
    politrees = _load_politrees_catalogue()
    trvlvr = _load_trvlvr_catalogue()
    all_entries: List[ModelEntry] = []

    def _source_for(label: str) -> str:
        in_pt = False
        if politrees:
            for key in ("vr_download_list", *_POLITREES_KEYS, "demucs_download_list"):
                if label in (politrees.get(key) or {}):
                    in_pt = True
                    break
        in_tr = (
            label in trvlvr.get("vr_download_list", {})
            or label in trvlvr.get("mdx_download_list", {})
            or label in trvlvr.get("mdx23_download_list", {})
            or label in trvlvr.get("demucs_download_list", {})
        )
        if in_pt and not in_tr:
            return "Politrees"
        if in_pt and in_tr:
            return "TRvlvr+Politrees"
        return "TRvlvr"

    for label, payload in sorted(vr_cat.items()):
        all_entries.extend(
            _parse_catalogue_entry(
                source=_source_for(label),
                family="VR Architecture",
                label=label,
                payload=payload,
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
                source=_source_for(label),
                family=family,
                label=label,
                payload=payload,
                hash_json=paths.MDX_HASH_JSON if family == "MDX-Net ONNX" else "",
                weight_dir=paths.MDX_MODELS_DIR,
            )
        )

    for label, payload in sorted(demucs_cat.items()):
        all_entries.extend(
            _parse_catalogue_entry(
                source=_source_for(label),
                family="Demucs",
                label=label,
                payload=payload,
            )
        )
        entry = all_entries[-1]
        if "UVR Model" in label or "uvr" in label.lower():
            entry.instruments = ["instrumental", "vocals"]
            entry.stem_count = 2
            entry.best_result = "2-stem: instrumental + vocals (user picks focus)"
        elif "6s" in label:
            entry.instruments = ["drums", "bass", "other", "vocals", "guitar", "piano"]
            entry.stem_count = 6
            entry.best_result = "6-stem Demucs"
        else:
            entry.instruments = ["drums", "bass", "other", "vocals"]
            entry.stem_count = 4
            entry.best_result = "4-stem Demucs"
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
        "This catalogue compares **catalogue naming intent** with **backend stem metadata**",
        "(`primary_stem`, `training.instruments`, `training.target_instrument`). Use it to",
        "verify Save stems labels and which output users should treat as the “best” result.",
        "",
        "## How to read this",
        "",
        "- **Name intent** — inferred from the Download Center label.",
        "- **Backend focus** — what `ModelData` uses as `primary_stem` at runtime.",
        "- **Best result** — the stem users typically want from that model name.",
        "- **Flags** — vocal/instrumental labelling mismatches (only when metadata resolved).",
        "",
        "### Roformer `other` yaml quirk (not a bug)",
        "",
        "Instrumental Mel-Band / BS models often use `target_instrument: other` with",
        "`instruments: [other, vocals]`. That is a **2-stem vocal/instrumental** split.",
        "The GUI should show **Lead Vocals** / **Mix minus Lead Vocals**, not Demucs Other.",
        "",
        "## Summary",
        "",
        f"- Total catalogue entries: **{len(entries)}**",
        f"- Entries with resolved metadata: **{len(with_meta)}**",
        f"- Flagged mismatches: **{len(flagged)}**",
        "",
    ]

    # Compact master table
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
                "**Lead Vocals** / **Mix minus Lead Vocals** for the complement stem.",
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
    entries = _collect_entries()
    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as handle:
        handle.write(_render(entries))
    flagged = sum(1 for e in entries if e.flags)
    with_meta = sum(1 for e in entries if e.metadata_source not in ("unavailable", ""))
    print(f"Wrote {OUTPUT_PATH} ({len(entries)} models, {with_meta} with metadata, {flagged} flagged)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
