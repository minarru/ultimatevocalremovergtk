#!/usr/bin/env python3
"""Generate docs/models-catalogue.md from the Download Center catalogue snapshot.

Membership comes from ``CatalogueCoordinator`` (TRvlvr → Politrees → extras →
mvsepless, plus Apollo). This script audits stem metadata against catalogue
naming intent so mislabeled vocal vs instrumental models can be spotted.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
import urllib.error
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from bundled.constants import INST_STEM, VOCAL_STEM  # noqa: E402
from core import paths  # noqa: E402
from core.catalogue_coordinator import CatalogueCoordinator, flatten_upstream_lists  # noqa: E402
from core.catalogue_types import (  # noqa: E402
    SourceId,
    UPSTREAM_DEMUCS_KEYS,
    UPSTREAM_MDX_KEYS,
    UPSTREAM_VR_KEYS,
)
from core.extra_catalog import APOLLO_LIST_KEY  # noqa: E402
from core.mdx_c_registry import compute_checkpoint_hash, infer_mdx_c_architecture  # noqa: E402
from core.model_data import load_mdx_c_config, load_model_hash_data, _mdx_c_training  # noqa: E402
from core.model_naming import canonical_display_name  # noqa: E402
from core.model_stem_semantics import (  # noqa: E402
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
OUTPUT_PATH = os.path.join(ROOT, "docs", "models-catalogue.md")
REFERENCE_TSV_PATH = os.path.join(ROOT, "docs", "model_intent_reference.tsv")

#: Ephemeral supplements live under CACHE_DIR, not in the documentation tree:
#: docs/ holds deliberate, reviewable output only.
_CACHE_ROOT = os.path.join(paths.CACHE_DIR, "models_catalogue")
YAML_CACHE_DIR = os.path.join(_CACHE_ROOT, "yaml")
POLITREES_CACHE_DIR = os.path.join(_CACHE_ROOT, "politrees")
COMMUNITY_CACHE_DIR = os.path.join(_CACHE_ROOT, "community")

#: How long a supplemental download stays good. Without a TTL, "regenerate
#: after catalogue updates" silently reused whatever was fetched first.
CACHE_MAX_AGE_SECONDS = 24 * 60 * 60

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
    *UPSTREAM_VR_KEYS,
    *UPSTREAM_MDX_KEYS,
    *UPSTREAM_DEMUCS_KEYS,
)
_SUPPLEMENT_LIST_KEYS = (*_POLITREES_KEYS, APOLLO_LIST_KEY)


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
    # Family-specific prose that should win over the generic derivation in
    # _best_result. Set by a family overlay *before* _finalize_entry runs.
    best_result_override: str = ""


def _source_payload(coordinator: CatalogueCoordinator, source_id: SourceId) -> dict:
    content = coordinator.source(source_id).state.content
    if content is None:
        return {}
    return dict(content.payload)


def _source_payloads(coordinator: CatalogueCoordinator) -> Tuple[dict, dict, dict, dict]:
    return (
        _source_payload(coordinator, SourceId.UPSTREAM),
        _source_payload(coordinator, SourceId.POLITREES),
        _source_payload(coordinator, SourceId.EXTRAS),
        _source_payload(coordinator, SourceId.MVSEPLESS),
    )


def _unsupported_count(unsupported: Any) -> int:
    if not isinstance(unsupported, dict):
        return 0
    total = 0
    for rows in unsupported.values():
        if isinstance(rows, list):
            total += len(rows)
    return total


def _snapshot_and_payloads(
    *,
    allow_network: bool,
    coordinator: Optional[CatalogueCoordinator] = None,
) -> Tuple[Any, Tuple[dict, dict, dict, dict]]:
    owned = coordinator is None
    if owned:
        coordinator = CatalogueCoordinator()
    try:
        snapshot = coordinator.ensure(vip=False, allow_network=allow_network)
        payloads = _source_payloads(coordinator)
        return snapshot, payloads
    finally:
        if owned:
            coordinator.close()


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


def _display_label(entry: ModelEntry) -> str:
    return canonical_display_name(entry.catalogue_label) or entry.catalogue_label


@dataclass(frozen=True)
class FetchPolicy:
    """How this run is allowed to reach the network and reuse caches.

    One object rather than a pair of booleans threaded through every layer:
    the generator has several fetch points and they must all agree, which is
    exactly what went wrong when only the snapshot honoured ``--offline``.
    """

    allow_network: bool = True
    refresh: bool = False
    max_age: float = CACHE_MAX_AGE_SECONDS
    #: Whether this run may write into runtime model config storage. --check
    #: promises to write nothing, and fetch_mdx_config_url writes a yaml into
    #: paths.MDX_C_CONFIG_PATH -- inside the repo in the portable dev layout.
    allow_metadata_writes: bool = True


#: Used by callers that do not care -- online, cache-respecting, TTL'd.
DEFAULT_FETCH_POLICY = FetchPolicy()

#: Cache-only: never fetch, serve whatever is on disk however old.
OFFLINE_FETCH_POLICY = FetchPolicy(allow_network=False)


def _cache_path(cache_dir: str, url: str, filename: str) -> str:
    """Cache identity keyed by URL, not by basename alone.

    Two different models can both ship a ``config.yaml``; keying on the
    basename made the second one silently read the first one's bytes. The
    readable stem is kept so the directory stays browsable.
    """
    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:12]
    stem, ext = os.path.splitext(filename)
    return os.path.join(cache_dir, f"{stem}-{digest}{ext}")


def _fetch_cached(
    url: str,
    cache_dir: str,
    filename: str,
    *,
    policy: FetchPolicy = DEFAULT_FETCH_POLICY,
    allow_network: Optional[bool] = None,
    refresh: bool = False,
) -> Optional[str]:
    """Return a cached copy of ``url``, refetching when stale or asked to.

    Offline is strictly cache-only: a miss stays a miss and a stale entry is
    still served, because the alternative is a silent download. Online, an
    entry older than ``policy.max_age`` is refreshed.
    """
    if allow_network is not None or refresh:
        policy = FetchPolicy(
            allow_network=policy.allow_network if allow_network is None else allow_network,
            refresh=refresh or policy.refresh,
            max_age=policy.max_age,
            allow_metadata_writes=policy.allow_metadata_writes,
        )

    cache_path = _cache_path(cache_dir, url, filename)
    cached = os.path.isfile(cache_path)

    if not policy.allow_network:
        # However old: offline must never turn a cache hit into a fetch.
        return cache_path if cached else None
    if cached and not policy.refresh:
        try:
            if time.time() - os.path.getmtime(cache_path) < policy.max_age:
                return cache_path
        except OSError:
            pass

    os.makedirs(cache_dir, exist_ok=True)
    try:
        from core.mdx_config_fetch import _urlopen

        with _urlopen(url) as response:
            data = response.read()
        # Staged, so a failed write cannot truncate a good entry into a
        # corrupt one that is then served for the rest of the TTL.
        tmp_path = f"{cache_path}.part"
        try:
            with open(tmp_path, "wb") as handle:
                handle.write(data)
            os.replace(tmp_path, cache_path)
        finally:
            try:
                os.unlink(tmp_path)
            except FileNotFoundError:
                pass
        return cache_path
    except (urllib.error.URLError, OSError, TimeoutError):
        return cache_path if cached else None


def _load_json_cache(
    url: str, cache_dir: str, filename: str, *, policy: FetchPolicy = DEFAULT_FETCH_POLICY
) -> dict:
    path = _fetch_cached(url, cache_dir, filename, policy=policy)
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


def _reference_tsv_text(refs: Dict[str, CommunityRef]) -> str:
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
    return "\n".join(lines) + "\n"


def _build_catalogue_context(
    *,
    policy: FetchPolicy = DEFAULT_FETCH_POLICY,
    allow_network: Optional[bool] = None,
) -> CatalogueContext:
    if allow_network is not None:
        policy = FetchPolicy(
            allow_network=allow_network,
            refresh=policy.refresh,
            max_age=policy.max_age,
            allow_metadata_writes=policy.allow_metadata_writes,
        )
    remote_vr = _load_json_cache(
        _POLITREES_VR_DATA_URL, POLITREES_CACHE_DIR, "vr_model_data.json", policy=policy
    )
    remote_mdx = _load_json_cache(
        _POLITREES_MDX_DATA_URL, POLITREES_CACHE_DIR, "mdx_model_data.json", policy=policy
    )
    community_path = _fetch_cached(
        _COMMUNITY_MODELS_URL, COMMUNITY_CACHE_DIR, "models.txt", policy=policy
    )
    community = _parse_community_models_txt(community_path or "")
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


def _yaml_paths(yaml_name: str, yaml_url: str = "") -> List[str]:
    """Where a config yaml may already be on disk, most authoritative first.

    The cache entry is URL-keyed, so it can only be probed when the URL is
    known -- looking for the bare basename there never matches and left the
    cache write-only.
    """
    candidates = [
        os.path.join(paths.MDX_C_CONFIG_PATH, yaml_name),
        os.path.join(ROOT, "models", "MDX_Net_Models", "model_data", "mdx_c_configs", yaml_name),
    ]
    if yaml_url:
        candidates.append(_cache_path(YAML_CACHE_DIR, yaml_url, yaml_name))
    return candidates


def _yaml_source_label(yaml_name: str, config_path: str) -> str:
    """Provenance label for a resolved config, keyed on where it now lives.

    Must be a pure function of the final location: anything that depends on
    whether *this* run downloaded it changes between runs and shows up as
    catalogue drift.

    "bundled_yaml" means "resolved from the local config store", which holds
    both shipped configs and ones core downloaded earlier; the two are not
    distinguishable after the fact. "remote_yaml" means this script fetched it
    into its own cache.
    """
    where = "remote_yaml" if YAML_CACHE_DIR in config_path else "bundled_yaml"
    return f"{where}:{yaml_name}"


def _fetch_yaml(
    url: str, yaml_name: str, *, policy: FetchPolicy = DEFAULT_FETCH_POLICY
) -> Optional[str]:
    if not url or not yaml_name.endswith(".yaml"):
        return None
    return _fetch_cached(url, YAML_CACHE_DIR, yaml_name, policy=policy)


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


def _load_yaml_meta(
    yaml_name: str,
    yaml_url: str = "",
    *,
    policy: FetchPolicy = DEFAULT_FETCH_POLICY,
    allow_network: Optional[bool] = None,
) -> Tuple[List[str], str, str, str]:
    if allow_network is not None:
        policy = FetchPolicy(
            allow_network=allow_network,
            refresh=policy.refresh,
            max_age=policy.max_age,
            allow_metadata_writes=policy.allow_metadata_writes,
        )
    if not yaml_name:
        return [], "", "", ""
    config_path = ""
    for candidate in _yaml_paths(yaml_name, yaml_url):
        if os.path.isfile(candidate):
            config_path = candidate
            break

    source = ""
    if config_path:
        source = _yaml_source_label(yaml_name, config_path)
    elif yaml_url:
        if policy.allow_network and policy.allow_metadata_writes:
            # fetch_mdx_config_url writes into runtime model config storage, so
            # it must never run for a read-only offline or --check report.
            from core.mdx_config_fetch import fetch_mdx_config_url

            if fetch_mdx_config_url(yaml_name, yaml_url):
                dest = os.path.join(paths.MDX_C_CONFIG_PATH, yaml_name)
                if os.path.isfile(dest):
                    config_path = dest
                    # Same rule as the on-disk lookup above. Labelling this
                    # "remote_yaml" made the value flip to "bundled_yaml" on the
                    # next run, once the file was found in place -- which reads
                    # as drift to --check.
                    source = _yaml_source_label(yaml_name, config_path)
        if not config_path:
            # Not gated on allow_network: _fetch_cached honours the policy
            # itself, and offline it is the only thing that reads the cache.
            fetched = _fetch_yaml(yaml_url, yaml_name, policy=policy)
            if fetched:
                config_path = fetched
                source = f"remote_yaml:{yaml_name}"
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
        if not arch:
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
    meta.best_result = meta.best_result_override or _best_result(meta)
    meta.ui_export_note = _ui_note(meta)
    meta.flags = _flag_mismatches(meta)
    if meta.target_instrument.lower() == "other" and meta.name_intent == "instrumental":
        meta.notes.append("Expected: inst models use yaml stem `other` (UI: Vocals / Instrumental)")


def _demucs_overlay(meta: ModelEntry) -> None:
    """Demucs family facts, inferred from the label.

    Demucs entries carry no yaml and no hash metadata, so their stem set comes
    from the label alone. This must run *before* _finalize_entry: the derived
    fields (backend_focus, ui_export_note, flags) are computed from
    instruments/stem_count/name_intent, and deriving them from an empty entry
    left every Demucs model with a blank export note.
    """
    label = meta.catalogue_label
    if "UVR Model" in label or "uvr" in label.lower():
        meta.instruments = ["instrumental", "vocals"]
        meta.stem_count = 2
        meta.name_intent = "dual_voc_inst"
        meta.best_result_override = "2-stem: instrumental + vocals (user picks focus)"
    elif "6s" in label:
        meta.instruments = ["drums", "bass", "other", "vocals", "guitar", "piano"]
        meta.stem_count = 6
        meta.name_intent = "multi_stem"
        meta.best_result_override = "6-stem Demucs"
    else:
        meta.instruments = ["drums", "bass", "other", "vocals"]
        meta.stem_count = 4
        meta.name_intent = "multi_stem"
        meta.best_result_override = "4-stem Demucs"
    meta.metadata_source = "demucs_heuristic"


def _parse_catalogue_entry(
    *,
    source: str,
    family: str,
    label: str,
    payload: Any,
    ctx: CatalogueContext,
    hash_json: str = "",
    weight_dir: str = "",
    entry_meta: Any = None,
    policy: FetchPolicy = DEFAULT_FETCH_POLICY,
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
        instruments, target, arch, yaml_source = _load_yaml_meta(
            yaml_name, yaml_url, policy=policy
        )
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

    _apply_entry_meta(meta, entry_meta)
    if family == "Demucs":
        _demucs_overlay(meta)
    _finalize_entry(meta)
    return [meta]


def _label_in_lists(label: str, payload: Optional[dict], keys: Tuple[str, ...]) -> bool:
    if not payload:
        return False
    return any(label in (payload.get(key) or {}) for key in keys)


def _mvsepless_lists(payload: Optional[dict]) -> Optional[dict]:
    if not payload:
        return None
    if "unsupported" in payload or "mdx_download_list" in payload:
        return payload
    from core.mvsepless_catalog import convert_mvsepless_catalog

    return convert_mvsepless_catalog(payload)


def _source_for(
    label: str,
    politrees: Optional[dict] = None,
    trvlvr: Optional[dict] = None,
    extras: Optional[dict] = None,
    mvsepless: Optional[dict] = None,
    *,
    upstream_lists: Optional[Tuple[Any, Any, Any]] = None,
    mvsepless_lists: Optional[dict] = None,
) -> str:
    """Attribute ``label`` to catalogue sources by membership, in merge order.

    ``upstream_lists`` and ``mvsepless_lists`` let a caller hoist the two
    derived payloads out of a per-label loop; both are constant for a run and
    rebuilding them per entry meant one full mvsepless conversion per model.
    """
    if upstream_lists is None and trvlvr:
        upstream_lists = flatten_upstream_lists(trvlvr, vip=False)
    in_tr = False
    if upstream_lists is not None:
        vr, mdx, demucs = upstream_lists
        in_tr = label in vr or label in mdx or label in demucs
    if mvsepless_lists is None:
        mvsepless_lists = _mvsepless_lists(mvsepless)
    in_pt = _label_in_lists(label, politrees, _POLITREES_KEYS)
    in_ex = _label_in_lists(label, extras, _SUPPLEMENT_LIST_KEYS)
    in_mv = _label_in_lists(label, mvsepless_lists, _POLITREES_KEYS)
    parts: List[str] = []
    if in_tr:
        parts.append("TRvlvr")
    if in_pt:
        parts.append("Politrees")
    if in_ex:
        parts.append("extras")
    if in_mv:
        parts.append("mvsepless")
    # No membership in any payload means the label was not attributable, which
    # is not the same as "it came from TRvlvr" -- a source that failed to load
    # is an empty payload, so a failed membership check proves nothing.
    return "+".join(parts) if parts else "unknown"


def _mdx_family(label: str) -> str:
    family_map = [
        ("Apollo Model", "Apollo"),
        ("MDX-Net Model", "MDX-Net ONNX"),
        ("MDX23 Model", "MDX23C"),
        ("MDX23C Model", "MDX23C"),
        ("Roformer Model", "Roformer"),
        ("SCnet:", "SCNet"),
        ("Bandit", "Bandit"),
    ]
    for prefix, fam in family_map:
        if label.startswith(prefix):
            return fam
    return "MDX-Net"


def _entries_from_snapshot(
    snapshot: Any,
    payloads: Tuple[dict, dict, dict, dict],
    ctx: CatalogueContext,
    *,
    policy: FetchPolicy = DEFAULT_FETCH_POLICY,
) -> List[ModelEntry]:
    trvlvr, politrees, extras, mvsepless = payloads
    meta_index = getattr(snapshot, "meta", {}) or {}
    all_entries: List[ModelEntry] = []

    # Both of these are constant across the run; computing them per label meant
    # a full mvsepless catalogue conversion for every one of ~474 entries.
    upstream_lists = flatten_upstream_lists(trvlvr, vip=False) if trvlvr else None
    mvsepless_lists = _mvsepless_lists(mvsepless)

    def source_for(label: str) -> str:
        return _source_for(
            label,
            politrees,
            trvlvr,
            extras=extras,
            mvsepless=mvsepless,
            upstream_lists=upstream_lists,
            mvsepless_lists=mvsepless_lists,
        )

    for label, payload in sorted(dict(snapshot.vr).items()):
        all_entries.extend(
            _parse_catalogue_entry(
                source=source_for(label),
                family="VR Architecture",
                label=label,
                payload=payload,
                ctx=ctx,
                hash_json=paths.VR_HASH_JSON,
                weight_dir=paths.VR_MODELS_DIR,
                entry_meta=meta_index.get(label),
                policy=policy,
            )
        )

    for label, payload in sorted(dict(snapshot.mdx).items()):
        family = _mdx_family(label)
        all_entries.extend(
            _parse_catalogue_entry(
                source=source_for(label),
                family=family,
                label=label,
                payload=payload,
                ctx=ctx,
                hash_json=paths.MDX_HASH_JSON if family == "MDX-Net ONNX" else "",
                weight_dir=paths.MDX_MODELS_DIR,
                entry_meta=meta_index.get(label),
                policy=policy,
            )
        )

    for label, payload in sorted(dict(snapshot.demucs).items()):
        all_entries.extend(
            _parse_catalogue_entry(
                source=source_for(label),
                family="Demucs",
                label=label,
                payload=payload,
                ctx=ctx,
                entry_meta=meta_index.get(label),
                policy=policy,
            )
        )

    for label, payload in sorted(dict(snapshot.apollo).items()):
        all_entries.extend(
            _parse_catalogue_entry(
                source=source_for(label),
                family="Apollo",
                label=label,
                payload=payload,
                ctx=ctx,
                entry_meta=meta_index.get(label),
                policy=policy,
            )
        )

    return all_entries


def _collect_entries(
    ctx: CatalogueContext,
    *,
    allow_network: bool = True,
    coordinator: Optional[CatalogueCoordinator] = None,
) -> List[ModelEntry]:
    snapshot, payloads = _snapshot_and_payloads(
        allow_network=allow_network, coordinator=coordinator
    )
    return _entries_from_snapshot(
        snapshot, payloads, ctx, policy=FetchPolicy(allow_network=allow_network)
    )


def _md_table(headers: List[str], rows: List[List[str]]) -> str:
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join(["---"] * len(headers)) + " |",
    ]
    for row in rows:
        safe = [str(cell).replace("|", "\\|").replace("\n", " ") for cell in row]
        lines.append("| " + " | ".join(safe) + " |")
    return "\n".join(lines)


def _render(
    entries: List[ModelEntry], *, unsupported_count: int = 0, report: Any = None
) -> str:
    flagged = [e for e in entries if e.flags]
    unknown = [e for e in entries if e.name_intent == "unknown"]
    with_meta = [e for e in entries if e.metadata_source not in ("unavailable", "")]
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    lines = [
        "# UVR Model Catalogue (TRvlvr + Politrees + extras + mvsepless)",
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
        "- **Backend focus** — catalogue helper summarizing primary/target; export is concept/route based.",
        "- **Best result** — the stem users typically want from that model name.",
        "- **Flags** — vocal/instrumental labelling mismatches (only when metadata resolved).",
        "",
        "### Roformer `other` yaml quirk (not a bug)",
        "",
        "Instrumental Mel-Band / BS models often use `target_instrument: other` with",
        "`instruments: [other, vocals]`. That is a **2-stem vocal/instrumental** split.",
        "The GUI should show **Vocals** / **Instrumental** for 2-stem yaml pairs, not Demucs Other.",
        "",
        *_provenance_lines(report),
        "## Summary",
        "",
        f"- Total catalogue entries: **{len(entries)}**",
        f"- Entries with resolved metadata: **{len(with_meta)}**",
        f"- Unknown intent remaining: **{len(unknown)}**",
        f"- Flagged mismatches: **{len(flagged)}**",
        f"- Unsupported mvsepless entries (omitted): **{unsupported_count}**",
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
                            _display_label(e),
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
                        _display_label(e)[:60],
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
                            _display_label(e),
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
                            _display_label(e),
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
                            _display_label(e),
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
        short = _display_label(entry)
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


def _parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate docs/models-catalogue.md from the Download Center snapshot."
    )
    parser.add_argument(
        "--offline",
        action="store_true",
        help="Read catalogue caches only (no remote refresh).",
    )
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="Refetch supplemental catalogue downloads even if cached and fresh.",
    )
    parser.add_argument(
        "--allow-degraded",
        action="store_true",
        help="Publish even when sources failed and the catalogue shrank sharply.",
    )
    parser.add_argument(
        "--write-tsv",
        action="store_true",
        help=f"Also write {os.path.basename(REFERENCE_TSV_PATH)} (off by default).",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--write",
        action="store_true",
        help="Write the generated artifacts (the default).",
    )
    mode.add_argument(
        "--check",
        action="store_true",
        help="Report whether the artifacts are up to date; write nothing. "
        "Exits 1 on drift, for CI.",
    )
    return parser.parse_args(argv)


#: Line prefixes that change on every run regardless of the catalogue. Drift
#: means the catalogue changed, not that time passed or a cache aged, so these
#: are excluded from the --check comparison.
_VOLATILE_PREFIXES = ("Generated: ", "- Snapshot ", "- Source ", "- Cache ")


def _canonical_for_diff(text: str) -> str:
    """``text`` with the volatile header lines removed, for drift comparison."""
    return "\n".join(
        line
        for line in text.splitlines()
        if not line.startswith(_VOLATILE_PREFIXES)
    )


def _text_matches(path: str, text: str) -> bool:
    """Whether ``path`` already holds ``text``, ignoring volatile header lines."""
    try:
        with open(path, encoding="utf-8") as handle:
            existing = handle.read()
    except OSError:
        return False
    return _canonical_for_diff(existing) == _canonical_for_diff(text)


def _provenance_lines(report: Any) -> List[str]:
    """Where this document's data came from, and how healthy it was.

    Answers "was this generated from good data?" at review time -- a document
    regenerated from a half-stale snapshot otherwise looks identical to one
    built from a clean fetch.
    """
    if report is None:
        return []

    def names(items: Any) -> str:
        collected: List[str] = [
            str(getattr(item, "value", item)) for item in (tuple(items or ()))
        ]
        return ", ".join(collected) if collected else "none"

    lines = [
        "## Source provenance",
        "",
        f"- Snapshot mode: `{getattr(getattr(report, 'mode', None), 'value', 'unknown')}`",
        f"- Source refreshed: {names(getattr(report, 'succeeded', ()))}",
        f"- Source stale: {names(getattr(report, 'stale', ()))}",
    ]
    failed: Tuple[Any, ...] = tuple(getattr(report, "failed", ()) or ())
    if failed:
        detail = "; ".join(
            f"{getattr(item[0], 'value', item[0])} ({item[1]})" for item in failed
        )
        lines.append(f"- Source failed: {detail}")
    else:
        lines.append("- Source failed: none")
    lines.append(f"- Source upstream live: {bool(getattr(report, 'upstream_live', False))}")

    for label, cache_dir in (
        ("politrees", POLITREES_CACHE_DIR),
        ("community", COMMUNITY_CACHE_DIR),
        ("yaml", YAML_CACHE_DIR),
    ):
        lines.append(f"- Cache {label}: {_cache_age_text(cache_dir)}")
    lines.append("")
    return lines


def _cache_age_text(cache_dir: str) -> str:
    """Newest entry age in a supplemental cache directory, in human terms."""
    try:
        stamps = [
            os.path.getmtime(os.path.join(cache_dir, name))
            for name in os.listdir(cache_dir)
        ]
    except OSError:
        return "absent"
    if not stamps:
        return "empty"
    age = time.time() - max(stamps)
    if age < 3600:
        return f"{age / 60:.0f}m old"
    if age < 86400:
        return f"{age / 3600:.0f}h old"
    return f"{age / 86400:.0f}d old"


#: A drop larger than this fraction of the previously published catalogue is
#: treated as evidence the run is broken rather than as real shrinkage.
_DEGRADED_DROP_RATIO = 0.10


@dataclass(frozen=True)
class PublicationVerdict:
    """Whether this run's entries may replace the published document."""

    ok: bool
    reason: str = ""


def _previous_entry_count(path: str) -> Optional[int]:
    """Entry count recorded in an existing catalogue document, if there is one.

    Read back from the summary line the renderer emits. This is a stopgap for
    the machine-readable sidecar; it only has to be good enough to notice that
    a 400-entry catalogue just became a 3-entry one.
    """
    try:
        with open(path, encoding="utf-8") as handle:
            for line in handle:
                match = re.search(r"Total catalogue entries: \*\*(\d+)\*\*", line)
                if match:
                    return int(match.group(1))
    except OSError:
        return None
    return None


def _publication_verdict(
    *,
    entries: List[Any],
    report: Any,
    previous_count: Optional[int],
    allow_degraded: bool = False,
) -> PublicationVerdict:
    """Decide whether these entries may overwrite the published catalogue.

    The entry count is the trigger, not source health. Offline sources are
    simply not refreshed rather than reported as failed, so a cold cache
    yields report.usable True and report.failed empty while producing a
    fraction of the entries -- measured, an empty supplemental cache gave 88
    entries where the published document had 474. Failed and stale sources
    are still reported, as context for diagnosing the refusal.

    Legitimate shrinkage goes through --allow-degraded, which is the only
    thing that can distinguish it from a broken run.
    """
    if allow_degraded:
        return PublicationVerdict(ok=True, reason="--allow-degraded")

    if not getattr(report, "usable", True):
        return PublicationVerdict(
            ok=False,
            reason="catalogue snapshot is unusable (no source produced entries)",
        )

    if previous_count:
        floor = previous_count * (1 - _DEGRADED_DROP_RATIO)
        if len(entries) < floor:
            reason = f"{len(entries)} entries against {previous_count} previously"
            failed: Tuple[Any, ...] = tuple(getattr(report, "failed", ()) or ())
            stale: Tuple[Any, ...] = tuple(getattr(report, "stale", ()) or ())
            if failed:
                names = ", ".join(str(getattr(i[0], "value", i[0])) for i in failed)
                reason += f"; failed sources: {names}"
            if stale:
                names = ", ".join(str(getattr(i, "value", i)) for i in stale)
                reason += f"; stale sources: {names}"
            return PublicationVerdict(ok=False, reason=reason)
    return PublicationVerdict(ok=True)


def _policy_for(args: argparse.Namespace) -> FetchPolicy:
    """Fetch policy implied by the CLI flags."""
    return FetchPolicy(
        allow_network=not args.offline,
        refresh=args.refresh,
        # --check must leave the tree exactly as it found it.
        allow_metadata_writes=not args.check,
    )


def main(argv: Optional[List[str]] = None) -> int:
    args = _parse_args(argv)
    policy = _policy_for(args)
    ctx = _build_catalogue_context(policy=policy)
    snapshot, payloads = _snapshot_and_payloads(allow_network=policy.allow_network)
    entries = _entries_from_snapshot(snapshot, payloads, ctx, policy=policy)
    unsupported = _unsupported_count(getattr(snapshot, "unsupported", None))

    verdict = _publication_verdict(
        entries=list(entries),
        report=getattr(snapshot, "report", None),
        previous_count=_previous_entry_count(OUTPUT_PATH),
        allow_degraded=args.allow_degraded,
    )
    if not verdict.ok:
        if args.check:
            print(
                f"Cannot judge {OUTPUT_PATH}: {verdict.reason}.\n"
                "This run's data is too degraded to tell drift from a bad fetch.",
                file=sys.stderr,
            )
        else:
            print(
                f"Refusing to write {OUTPUT_PATH}: {verdict.reason}.\n"
                "Pass --allow-degraded if the catalogue really did shrink.",
                file=sys.stderr,
            )
        return 2

    rendered = _render(
        entries, unsupported_count=unsupported, report=getattr(snapshot, "report", None)
    )
    tsv_text = ""
    if args.write_tsv:
        if ctx.community_by_file:
            tsv_text = _reference_tsv_text(ctx.community_by_file)
        else:
            print(
                f"--write-tsv had no community data; leaving {REFERENCE_TSV_PATH} alone "
                "(the models.txt fetch produced nothing).",
                file=sys.stderr,
            )

    if args.check:
        drift = []
        if not _text_matches(OUTPUT_PATH, rendered):
            drift.append(OUTPUT_PATH)
        if tsv_text and not _text_matches(REFERENCE_TSV_PATH, tsv_text):
            drift.append(REFERENCE_TSV_PATH)
        if drift:
            for path in drift:
                print(f"Out of date: {path}", file=sys.stderr)
            regenerate = "python scripts/generate_models_catalogue.py"
            if REFERENCE_TSV_PATH in drift:
                regenerate += " --write-tsv"
            print(f"Regenerate with: {regenerate}", file=sys.stderr)
            return 1
        print(f"Up to date: {OUTPUT_PATH}")
        return 0

    from core.json_store import write_text_atomic

    # A failed write must not truncate the checked-in catalogue document.
    write_text_atomic(OUTPUT_PATH, rendered)
    flagged = sum(1 for e in entries if e.flags)
    unknown = sum(1 for e in entries if e.name_intent == "unknown")
    with_meta = sum(1 for e in entries if e.metadata_source not in ("unavailable", ""))
    print(
        f"Wrote {OUTPUT_PATH} ({len(entries)} models, {with_meta} with metadata, "
        f"{unknown} unknown, {flagged} flagged, {unsupported} unsupported omitted)"
    )
    # Only after the guard: a refused run must not mutate this artifact either.
    if tsv_text:
        write_text_atomic(REFERENCE_TSV_PATH, tsv_text)
        print(f"Wrote {REFERENCE_TSV_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
