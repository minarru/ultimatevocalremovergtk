#!/usr/bin/env python3
"""Collect Download Center catalogue entries into a machine-readable IR.

Membership comes from ``CatalogueCoordinator`` (TRvlvr → Politrees → extras →
mvsepless, plus Apollo). The CLI renders this into Markdown; this module is
the one collection path.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import time
import urllib.error
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

from bundled.constants import INST_STEM, VOCAL_STEM  # noqa: E402
from core import paths  # noqa: E402
from core.access_policy import AccessPolicy, access_policy  # noqa: E402
from core.catalogue_coordinator import CatalogueCoordinator, flatten_upstream_lists  # noqa: E402
from core.catalogue_types import (  # noqa: E402
    UPSTREAM_DEMUCS_KEYS,
    UPSTREAM_MDX_KEYS,
    UPSTREAM_VR_KEYS,
    RefreshMode,
    SourceId,
)
from core.extra_catalog import APOLLO_LIST_KEY  # noqa: E402
from core.model_data import (  # noqa: E402
    _mdx_c_training,
    load_mdx_c_config,
    load_mdx_c_config_data,
    load_model_hash_data,
)
from core.model_naming import canonical_display_name  # noqa: E402
from core.model_stem_semantics import (  # noqa: E402
    INTENT_MULTI_STEM,
    INTENT_SPECIALTY_STEM,
    INTENT_UNKNOWN,
    backend_focus_label,
    classic_mdx_runtime_stem_signature,
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

OUTPUT_PATH = os.path.join(ROOT, "docs", "models-catalogue.md")
REFERENCE_TSV_PATH = os.path.join(ROOT, "docs", "model_intent_reference.tsv")
DISPLAY_REFERENCE_TSV_PATH = os.path.join(ROOT, "docs", "model_display_reference.tsv")
STEM_SEMANTICS_REFERENCE_TSV_PATH = os.path.join(ROOT, "docs", "model_stem_semantics_reference.tsv")

#: Ephemeral supplements live under CACHE_DIR, not in the documentation tree:
#: docs/ holds deliberate, reviewable output only.
_CACHE_ROOT = os.path.join(paths.CACHE_DIR, "models_catalogue")
YAML_CACHE_DIR = os.path.join(_CACHE_ROOT, "yaml")
POLITREES_CACHE_DIR = os.path.join(_CACHE_ROOT, "politrees")
COMMUNITY_CACHE_DIR = os.path.join(_CACHE_ROOT, "community")

# Deliberate repository seeds are part of the generator input.  Runtime model
# storage under UVR_DATA_DIR is user state: installed configs and weights must
# never change a strict publication candidate.
_BUNDLED_MDX_YAML_DIR = os.path.join(
    ROOT, "models", "MDX_Net_Models", "model_data", "mdx_c_configs"
)
_BUNDLED_VR_HASH_JSON = os.path.join(ROOT, "models", "VR_Models", "model_data", "model_data.json")
_BUNDLED_MDX_HASH_JSON = os.path.join(
    ROOT, "models", "MDX_Net_Models", "model_data", "model_data.json"
)

#: How long a supplemental download stays good. Without a TTL, "regenerate
#: after catalogue updates" silently reused whatever was fetched first.
CACHE_MAX_AGE_SECONDS = 24 * 60 * 60

_POLITREES_VR_DATA_URL = "https://raw.githubusercontent.com/Politrees/UVR_resources/main/UVR_resources/model_data/vr_model_data.json"
_POLITREES_MDX_DATA_URL = "https://raw.githubusercontent.com/Politrees/UVR_resources/main/UVR_resources/model_data/mdx_model_data.json"
_COMMUNITY_MODELS_URL = "https://raw.githubusercontent.com/upseem/uvr5-cli-no-ui/main/models.txt"

_POLITREES_KEYS = (
    *UPSTREAM_VR_KEYS,
    *UPSTREAM_MDX_KEYS,
    *UPSTREAM_DEMUCS_KEYS,
)
_SUPPLEMENT_LIST_KEYS = (*_POLITREES_KEYS, APOLLO_LIST_KEY)

# The VR backend always emits its reviewed primary plus the computed
# complement. This exact BVE artifact has authoritative hash metadata for the
# primary and an exact community record for the complement, but catalogue
# sources do not carry a native inventory list. Keep the exception scoped to
# its canonical ID so absent inventory for every other model remains absent.
_REVIEWED_MISSING_NATIVE_SIGNATURES = {
    "vr:UVR-BVE-4B_SN-44100-1": ("Vocals", "Instrumental"),
}


def reviewed_stem_signature(model_id: str, instruments: Any) -> tuple[str, ...]:
    """Return actual inventory, or one exact reviewed missing-inventory supplement."""
    actual = tuple(str(native) for native in instruments)
    if actual:
        return actual
    return _REVIEWED_MISSING_NATIVE_SIGNATURES.get(model_id, ())


def is_runtime_target_instrument(
    model_id: str,
    *,
    target_instrument: str = "",
    metadata_source: str = "",
) -> bool:
    """Whether catalogue evidence selects ModelConfig's single-target branch.

    A target read from an actual MDX-C yaml changes the runtime-native source
    inventory to exactly that target. Community tables can describe a primary
    as a target too, but do not configure the engine and therefore must not
    collapse an otherwise native two-output inventory.
    """
    return bool(
        model_id.startswith("mdx:")
        and str(target_instrument or "").strip()
        and str(metadata_source or "").startswith(("bundled_yaml:", "remote_yaml:"))
    )


def runtime_stem_signature(
    model_id: str,
    instruments: Any,
    *,
    target_instrument: str = "",
    metadata_source: str = "",
) -> tuple[str, ...]:
    """Project collected training evidence to actual engine-native source keys."""
    classic_signature = classic_mdx_runtime_stem_signature(model_id)
    if classic_signature:
        return classic_signature
    if is_runtime_target_instrument(
        model_id,
        target_instrument=target_instrument,
        metadata_source=metadata_source,
    ):
        return (str(target_instrument),)
    return reviewed_stem_signature(model_id, instruments)


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
    #: Required supplements that could not be read at all. An empty but valid
    #: response is evidence too; callers must not confuse zero rows with an
    #: unavailable source and reject a coherent snapshot on that basis.
    unavailable_supplemental_evidence: Tuple[str, ...] = ()
    #: Per-model configs required by the collected membership but unavailable
    #: or unparseable in the checked-in seed plus URL-keyed generator cache.
    #: A set keeps duplicate catalogue aliases from inflating the diagnostic.
    unavailable_yaml_evidence: set[str] = field(default_factory=set)


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
    refresh: bool = False,
    coordinator: Optional[CatalogueCoordinator] = None,
    policy: Optional[FetchPolicy] = None,
) -> Tuple[Any, Tuple[dict, dict, dict, dict]]:
    source_policy = AccessPolicy(
        allow_network=allow_network,
        allow_metadata_writes=True if policy is None else policy.allow_metadata_writes,
        allow_cache_writes=True if policy is None else policy.allow_cache_writes,
    )
    owned = coordinator is None
    if owned:
        coordinator = CatalogueCoordinator()
    try:
        # One blocking snapshot, not refresh() then ensure(). ensure() is
        # stale-while-revalidate and used to republish the FORCE snapshot from
        # cache, including a placeholder RefreshReport(usable=False).
        with access_policy(
            allow_network=source_policy.allow_network,
            allow_metadata_writes=source_policy.allow_metadata_writes,
            allow_cache_writes=source_policy.allow_cache_writes,
        ):
            if refresh and allow_network:
                snapshot = coordinator.snapshot(mode=RefreshMode.FORCE, policy=source_policy)
            else:
                snapshot = coordinator.ensure(allow_network=allow_network, policy=source_policy)
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
    #: Whether coordinator/runtime metadata may be persisted. Generator YAML
    #: evidence never uses runtime config storage; it is governed exclusively
    #: by allow_cache_writes below.
    allow_metadata_writes: bool = True
    #: Whether network responses may be persisted in catalogue supplement or
    #: coordinator source caches. Check/summary may still fetch into memory.
    allow_cache_writes: bool = True


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


def _fetch_cached_bytes(
    url: str,
    cache_dir: str,
    filename: str,
    *,
    policy: FetchPolicy = DEFAULT_FETCH_POLICY,
    allow_network: Optional[bool] = None,
    refresh: bool = False,
) -> Tuple[Optional[bytes], Optional[str]]:
    """Return response bytes and the readable cache path, if one exists.

    Offline is strictly cache-only: a miss stays a miss and a stale entry is
    still served, because the alternative is a silent download. Online, an
    entry older than ``policy.max_age`` is refreshed. A read-only online run
    receives fresh bytes in memory without creating or replacing cache files.
    """
    if allow_network is not None or refresh:
        policy = FetchPolicy(
            allow_network=policy.allow_network if allow_network is None else allow_network,
            refresh=refresh or policy.refresh,
            max_age=policy.max_age,
            allow_metadata_writes=policy.allow_metadata_writes,
            allow_cache_writes=policy.allow_cache_writes,
        )

    cache_path = _cache_path(cache_dir, url, filename)
    cached = os.path.isfile(cache_path)
    cached_data: Optional[bytes] = None
    if cached:
        try:
            with open(cache_path, "rb") as handle:
                cached_data = handle.read()
        except OSError:
            pass

    if not policy.allow_network:
        # However old: offline must never turn a cache hit into a fetch.
        return cached_data, cache_path if cached_data is not None else None
    if cached_data is not None and not policy.refresh:
        try:
            if time.time() - os.path.getmtime(cache_path) < policy.max_age:
                return cached_data, cache_path
        except OSError:
            pass

    try:
        from core.mdx_config_fetch import _urlopen

        with _urlopen(url) as response:
            data = response.read()
    except (urllib.error.URLError, OSError, TimeoutError):
        return cached_data, cache_path if cached_data is not None else None

    persisted_path: Optional[str] = cache_path if cached_data is not None else None
    if policy.allow_cache_writes:
        # Staged, so a failed write cannot truncate a good entry into a
        # corrupt one that is then served for the rest of the TTL.
        tmp_path = f"{cache_path}.part"
        try:
            os.makedirs(cache_dir, exist_ok=True)
            with open(tmp_path, "wb") as handle:
                handle.write(data)
            os.replace(tmp_path, cache_path)
            persisted_path = cache_path
        except OSError:
            pass
        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
    return data, persisted_path


def _fetch_cached(
    url: str,
    cache_dir: str,
    filename: str,
    *,
    policy: FetchPolicy = DEFAULT_FETCH_POLICY,
    allow_network: Optional[bool] = None,
    refresh: bool = False,
) -> Optional[str]:
    """Return a readable cache path for compatibility with path consumers."""
    data, path = _fetch_cached_bytes(
        url,
        cache_dir,
        filename,
        policy=policy,
        allow_network=allow_network,
        refresh=refresh,
    )
    return path if data is not None else None


def _load_json_cache(
    url: str, cache_dir: str, filename: str, *, policy: FetchPolicy = DEFAULT_FETCH_POLICY
) -> dict:
    payload, _available = _load_json_cache_with_availability(
        url, cache_dir, filename, policy=policy
    )
    return payload


def _load_json_cache_with_availability(
    url: str, cache_dir: str, filename: str, *, policy: FetchPolicy = DEFAULT_FETCH_POLICY
) -> Tuple[dict, bool]:
    """Load a JSON supplement and retain whether evidence was available at all."""
    data, _path = _fetch_cached_bytes(url, cache_dir, filename, policy=policy)
    if data is None:
        return {}, False
    try:
        payload = json.loads(data.decode("utf-8"))
        return (payload, True) if isinstance(payload, dict) else ({}, False)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {}, False


def _merge_hash_tables(local_path: str, remote: dict) -> dict:
    merged: dict = {}
    if os.path.isfile(local_path):
        try:
            merged.update(load_model_hash_data(local_path))
        except (FileNotFoundError, ValueError, json.JSONDecodeError):
            pass
    merged.update(remote)
    return merged


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
            allow_cache_writes=policy.allow_cache_writes,
        )
    remote_vr, vr_available = _load_json_cache_with_availability(
        _POLITREES_VR_DATA_URL, POLITREES_CACHE_DIR, "vr_model_data.json", policy=policy
    )
    remote_mdx, mdx_available = _load_json_cache_with_availability(
        _POLITREES_MDX_DATA_URL, POLITREES_CACHE_DIR, "mdx_model_data.json", policy=policy
    )
    community_data, _community_path = _fetch_cached_bytes(
        _COMMUNITY_MODELS_URL, COMMUNITY_CACHE_DIR, "models.txt", policy=policy
    )
    if community_data is None:
        community, community_available = {}, False
    else:
        community, community_available = _parse_community_models_bytes(community_data)
    unavailable = []
    if not vr_available:
        unavailable.append("Politrees VR hash metadata")
    if not mdx_available:
        unavailable.append("Politrees MDX hash metadata")
    if not community_available:
        unavailable.append("community models.txt reference")
    return CatalogueContext(
        community_by_file=community,
        vr_by_hash=_merge_hash_tables(_BUNDLED_VR_HASH_JSON, remote_vr),
        mdx_by_hash=_merge_hash_tables(_BUNDLED_MDX_HASH_JSON, remote_mdx),
        # Hash tables are still retained as evidence inputs, but a filename can
        # only be joined to a digest by hashing an installed weight. Runtime
        # weights are deliberately excluded from strict publication.
        weight_to_hash={},
        unavailable_supplemental_evidence=tuple(unavailable),
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


def _yaml_paths(yaml_name: str, yaml_url: str = "") -> List[str]:
    """Strict generator-owned YAML locations, most authoritative first.

    Checked-in configs are deliberate seeds. The optional second path is the
    URL-keyed generator cache. Arbitrary installed configs under UVR_DATA_DIR
    are intentionally absent.
    """
    candidates = [os.path.join(_BUNDLED_MDX_YAML_DIR, yaml_name)]
    if yaml_url:
        candidates.append(_cache_path(YAML_CACHE_DIR, yaml_url, yaml_name))
    return candidates


def _yaml_source_label(yaml_name: str, config_path: str) -> str:
    """Stable provenance for checked-in versus generator-cache evidence."""
    where = "remote_yaml" if YAML_CACHE_DIR in config_path else "bundled_yaml"
    return f"{where}:{yaml_name}"


def _fetch_yaml_bytes(
    url: str, yaml_name: str, *, policy: FetchPolicy = DEFAULT_FETCH_POLICY
) -> Tuple[Optional[bytes], Optional[str]]:
    if not url or not yaml_name.endswith(".yaml"):
        return None, None
    return _fetch_cached_bytes(url, YAML_CACHE_DIR, yaml_name, policy=policy)


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


def _architecture_from_config(yaml_name: str, config: Any) -> str:
    """Infer architecture from already-loaded bytes without reopening runtime state."""
    if not isinstance(config, dict):
        return ""
    if config.get("cls") == "Bandit":
        return "Bandit"
    model = config.get("model") or {}
    if not isinstance(model, dict):
        return "MDX23C"
    if "band_specs" in model:
        return "Bandit"
    if "band_SR" in model or "sources" in model:
        if any(str(key).startswith("tran_") for key in model):
            return "SCNet Tran"
        if "masked" in yaml_name.lower():
            return "SCNet Masked"
        return "SCNet"
    if "num_bands" in model:
        return "Mel-Band Roformer"
    if "freqs_per_bands" in model:
        return "BS Roformer"
    return "MDX23C"


def _architecture_from_yaml_name(yaml_name: str) -> str:
    """Deterministic informational hint used only when config evidence is absent."""
    low = yaml_name.casefold()
    if "bandit" in low:
        return "Bandit"
    if "scnet" in low:
        if "tran" in low:
            return "SCNet Tran"
        if "masked" in low:
            return "SCNet Masked"
        return "SCNet"
    if "melband" in low or "mel_band" in low:
        return "Mel-Band Roformer"
    if "roformer" in low:
        return "Roformer"
    if "mdx23" in low:
        return "MDX23C"
    return ""


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
            allow_cache_writes=policy.allow_cache_writes,
        )
    if not yaml_name:
        return [], "", "", ""
    bundled_path = _yaml_paths(yaml_name, yaml_url)[0]
    config_path = bundled_path if os.path.isfile(bundled_path) else ""

    source = ""
    config_data: Optional[bytes] = None
    if config_path:
        source = _yaml_source_label(yaml_name, config_path)
    elif yaml_url:
        # This boundary owns both fetch and persistence policy. In particular,
        # refresh must revalidate an existing cache entry, and no path here may
        # write to runtime model config storage.
        config_data, fetched_path = _fetch_yaml_bytes(yaml_url, yaml_name, policy=policy)
        if fetched_path:
            config_path = fetched_path
        if config_data is not None:
            source = f"remote_yaml:{yaml_name}"
    if not config_path and config_data is None:
        inferred = _infer_from_yaml_name(yaml_name)
        if inferred[0] or inferred[1]:
            return inferred[0], inferred[1], inferred[2], f"yaml_name_heuristic:{yaml_name}"
        return [], "", "", ""
    try:
        config = (
            load_mdx_c_config(config_path)
            if config_data is None
            else load_mdx_c_config_data(config_data)
        )
        training = _mdx_c_training(config)
        instruments, target = _training_fields(training)
        arch = _architecture_from_config(yaml_name, config)
        return instruments, target, arch, source
    except Exception:
        inferred = _infer_from_yaml_name(yaml_name)
        return inferred[0], inferred[1], inferred[2], f"yaml_parse_failed:{yaml_name}"


def _infer_from_yaml_name(yaml_name: str) -> Tuple[List[str], str, str]:
    low = yaml_name.lower()
    arch = _architecture_from_yaml_name(yaml_name)
    if "4stem" in low or "4_stem" in low or "musdb18" in low or "dnr_bandit" in low:
        return [], "", arch
    if any(k in low for k in ("instvoc", "duality", "2_stem", "2stem")):
        return ["instrumental", "vocals"], "", arch
    if any(k in low for k in ("inst", "instrumental", "fno", "crowd", "guitar", "metal")):
        return ["other", "vocals"], "other", arch
    if any(
        k in low
        for k in (
            "voc",
            "karaoke",
            "aspiration",
            "bve",
            "revive",
            "chorus",
            "male_female",
            "big_beta",
            "kim_ft",
        )
    ):
        return ["other", "vocals"], "vocals", arch
    if any(k in low for k in ("dereverb", "deverb", "denoise", "echo", "bleed")):
        return ["no_reverb"], "no_reverb", arch
    return [], "", arch


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
    entry_meta: Any = None,
    policy: FetchPolicy = DEFAULT_FETCH_POLICY,
) -> List[ModelEntry]:
    yaml_name = ""
    yaml_url = ""
    weight = ""
    weight_candidates: List[str] = []
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
                weight_candidates.append(key)
        if family == "Demucs" and weight_candidates:
            # Remote JSON preserves server insertion order while the atomic
            # cache sorts object keys. A bag contains every member checkpoint,
            # so choose one deterministic representative for audit/display
            # instead of letting fresh-online and warm-offline reports differ.
            weight = max(weight_candidates, key=lambda item: (item.casefold(), item))

    meta = ModelEntry(
        source=source,
        family=family,
        catalogue_label=label,
        weight_file=weight,
        config_yaml=yaml_name,
        config_url=yaml_url,
    )
    meta.name_intent = _infer_name_intent(label)

    if yaml_name and family not in ("Apollo", "Demucs"):
        # Apollo and Demucs sidecars describe execution/configuration details,
        # not the MDX-C training inventory used by this strict stem projection.
        # Their family overlays supply the publication semantics, so those
        # sidecars are not required supplemental evidence here.
        instruments, target, arch, yaml_source = _load_yaml_meta(yaml_name, yaml_url, policy=policy)
        meta.arch = arch
        if yaml_source.startswith(("bundled_yaml:", "remote_yaml:")):
            meta.instruments = instruments
            meta.target_instrument = target
            meta.stem_count = len(instruments) or (1 if target else 0)
            if target:
                meta.primary_stem = target
            elif instruments:
                meta.primary_stem = instruments[0]
        else:
            # Filename guesses can still label architecture informally, but
            # cannot become a native signature used by strict publication.
            ctx.unavailable_yaml_evidence.add(yaml_name)
        if yaml_source:
            meta.metadata_source = yaml_source

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
        upstream_lists = flatten_upstream_lists(trvlvr)
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
    upstream_lists = flatten_upstream_lists(trvlvr) if trvlvr else None
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


def collect_entries(
    ctx: CatalogueContext,
    *,
    policy: Optional[FetchPolicy] = None,
    allow_network: Optional[bool] = None,
    coordinator: Optional[CatalogueCoordinator] = None,
) -> Tuple[Any, List[ModelEntry]]:
    """Acquire a snapshot and turn it into entries. The one collection path.

    ``main`` goes through this too: a second entry path exercised only by
    tests is how the tested behaviour and the real behaviour drift apart.
    """
    if policy is None:
        policy = FetchPolicy(allow_network=True if allow_network is None else allow_network)
    elif allow_network is not None:
        policy = FetchPolicy(
            allow_network=allow_network,
            refresh=policy.refresh,
            max_age=policy.max_age,
            allow_metadata_writes=policy.allow_metadata_writes,
            allow_cache_writes=policy.allow_cache_writes,
        )
    snapshot, payloads = _snapshot_and_payloads(
        allow_network=policy.allow_network,
        refresh=policy.refresh,
        coordinator=coordinator,
        policy=policy,
    )
    return snapshot, _entries_from_snapshot(snapshot, payloads, ctx, policy=policy)


#: Bumped when the IR's shape changes in a way a consumer would notice.
IR_SCHEMA_VERSION = 1


def _ir_path_for(output_path: str) -> str:
    """Sidecar path for a rendered document."""
    stem, _ext = os.path.splitext(output_path)
    return f"{stem}.ir.json"


def _document_digest(path: str) -> str:
    """SHA-256 of a rendered document, used to tie a sidecar to it."""
    from core.json_store import content_digest

    return content_digest(path)


def build_ir(
    entries: List[ModelEntry],
    *,
    report: Any,
    unsupported_count: int,
    document_sha256: str = "",
) -> Dict[str, Any]:
    """The catalogue as data, from which Markdown and TSV are rendered.

    Rendered output is lossy and awkward to diff; this is the form a consumer
    can read without parsing prose. It is also what lets the publication guard
    know how many entries the last good run produced, rather than recovering
    that by re-parsing a summary line.
    """
    return {
        "schema_version": IR_SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "entry_count": len(entries),
        "unsupported_omitted": unsupported_count,
        "provenance": report.as_dict() if hasattr(report, "as_dict") else {},
        # Ties this sidecar to the document it was written beside. Without it
        # a sidecar left behind by a degraded run silently lowers the
        # publication guard's floor for a document it does not describe.
        "document_sha256": document_sha256,
        "entries": [asdict(entry) for entry in entries],
    }
