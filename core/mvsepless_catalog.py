"""Live-merge the noblebarkrr/mvsepless_resources catalogue into Download Center.

Fetches ``models.json`` from Hugging Face (Politrees-style disk cache), converts
entries into UVR download-list shape, and classifies which models this fork can
actually run. Unsupported entries are exposed separately so the UI can show them
grayed out without offering a download.
"""

from __future__ import annotations

import json
import os
import threading
import time
from typing import Any, Dict, List, Mapping, Optional, Tuple
from urllib.parse import unquote, urlparse

from bundled.constants import (
    DEMUCS_ARCH_TYPE,
    MDX_ARCH_TYPE,
    MVSEPLESS_MODELS_JSON_URL,
    VR_ARCH_TYPE,
)

from . import paths
from .catalog_dedupe import normalize_catalogue_label
from .debug_log import debug
from .mdx_config_fetch import _urlopen
from .politrees_catalog import merge_supplemental_list

_MVSEPLESS_CACHE_TTL_SECONDS = 24 * 60 * 60

#: MDX-family list keys that flatten into the Download Center MDX tab.
_MVSEPLESS_MDX_SOURCE_KEYS = (
    "mdx_download_list",
    "mdx23c_download_list",
    "roformer_download_list",
    "scnet_download_list",
    "bandit_download_list",
)

#: model_type values we can download + run via existing MDX-C / Bandit paths.
_SUPPORTED_MODEL_TYPES = frozenset(
    {
        "mel_band_roformer",
        "bs_roformer",
        "mdx23c",
        "scnet",
        "scnet_masked",
        "scnet_tran",
        "bandit",
        "bandit_v2",
    }
)

#: model_type → short UI reason (always unsupported in first pass).
_UNSUPPORTED_MODEL_TYPES: Dict[str, str] = {
    "medley_vox": "Medley-Vox engine not ported",
    "htdemucs": "MSST Demucs single-ckpt format not supported",
    "vr": "needs VR .ckpt+yaml hash bridge",
    "mdxnet": "needs MDX-Net ONNX yaml→hash bridge",
}

#: Known entry ids whose yaml needs features we do not implement.
_UNSUPPORTED_ENTRY_IDS: Dict[str, str] = {
    "mbr_wsa": "Windowed Sink Attention Mel-Band not ported",
    "bs_cr_4stem_zf_turbo": "BS Conformer not ported",
}


def _quarantine_reason(entry_id: str, entry: Mapping[str, Any]) -> str:
    """Return why a known malformed remote record must be omitted."""
    checkpoint_url = str(entry.get("checkpoint_url") or "")
    if (
        entry_id == "scnet_mid_side_gilliaaan"
        and "/mdx23c/mdx23c_mid_side_gilliaaan.ckpt" in checkpoint_url
    ):
        return "SCNet record points at the MDX23C Mid-Side checkpoint"
    return ""

_MODEL_TYPE_TO_LIST_KEY: Dict[str, str] = {
    "mel_band_roformer": "roformer_download_list",
    "bs_roformer": "roformer_download_list",
    "mdx23c": "mdx23c_download_list",
    "scnet": "scnet_download_list",
    "bandit": "bandit_download_list",
    "bandit_v2": "bandit_download_list",
    "mdxnet": "mdx_download_list",
    "vr": "vr_download_list",
    "htdemucs": "demucs_download_list",
    "medley_vox": "mdx_download_list",
    "scnet_masked": "scnet_download_list",
    "scnet_tran": "scnet_download_list",
}

_MODEL_TYPE_TO_ARCH: Dict[str, str] = {
    "mel_band_roformer": MDX_ARCH_TYPE,
    "bs_roformer": MDX_ARCH_TYPE,
    "mdx23c": MDX_ARCH_TYPE,
    "scnet": MDX_ARCH_TYPE,
    "bandit": MDX_ARCH_TYPE,
    "bandit_v2": MDX_ARCH_TYPE,
    "mdxnet": MDX_ARCH_TYPE,
    "medley_vox": MDX_ARCH_TYPE,
    "scnet_masked": MDX_ARCH_TYPE,
    "scnet_tran": MDX_ARCH_TYPE,
    "vr": VR_ARCH_TYPE,
    "htdemucs": DEMUCS_ARCH_TYPE,
}

from .model_stem_semantics import (
    INTENT_DRUM_BASS_SEP,
    INTENT_DUAL_VOC_INST,
    INTENT_INSTRUMENTAL,
    INTENT_KARAOKE,
    INTENT_MULTI_STEM,
    INTENT_SPECIAL_FX,
    INTENT_SPECIALTY_STEM,
    INTENT_UNKNOWN,
    INTENT_VOCALS,
)

#: mvsepless ``category`` values are Russian. Map each to an English label and
#: the stem-semantics intent, so the purpose filter uses real metadata instead
#: of regex-guessing from the label.
_CATEGORY_TABLE: Dict[str, Tuple[str, str]] = {
    "Вокал": ("Vocals", INTENT_VOCALS),
    "Инструментал": ("Instrumental", INTENT_INSTRUMENTAL),
    "Инструментал и вокал": ("Instrumental & vocals", INTENT_DUAL_VOC_INST),
    "Караоке": ("Karaoke", INTENT_KARAOKE),
    "4 стема": ("4 stems", INTENT_MULTI_STEM),
    "6 стемов": ("6 stems", INTENT_MULTI_STEM),
    "Все стемы": ("All stems", INTENT_MULTI_STEM),
    "Ударные": ("Drums", INTENT_DRUM_BASS_SEP),
    "Бас": ("Bass", INTENT_DRUM_BASS_SEP),
    "Басс": ("Bass", INTENT_DRUM_BASS_SEP),
    "DrumSep": ("DrumSep", INTENT_DRUM_BASS_SEP),
    "Реверб": ("Reverb", INTENT_SPECIAL_FX),
    "Эхо": ("Echo", INTENT_SPECIAL_FX),
    "Реверб и эхо": ("Reverb & echo", INTENT_SPECIAL_FX),
    "Шум": ("Noise", INTENT_SPECIAL_FX),
    "Звуковые эффекты": ("Sound effects", INTENT_SPECIAL_FX),
    "Дыхание": ("Breath", INTENT_SPECIAL_FX),
    "Разделение голосов": ("Voice separation", INTENT_VOCALS),
    "Мужской/Женский вокал": ("Male/female vocals", INTENT_VOCALS),
    "Дуэт": ("Duet", INTENT_VOCALS),
    "Хор": ("Choir", INTENT_SPECIALTY_STEM),
    "Гитара": ("Guitar", INTENT_SPECIALTY_STEM),
    "Клавишные": ("Keys", INTENT_SPECIALTY_STEM),
    "Перкуссия": ("Percussion", INTENT_SPECIALTY_STEM),
    "Оркестр": ("Orchestra", INTENT_SPECIALTY_STEM),
    "Синтезатор": ("Synth", INTENT_SPECIALTY_STEM),
    "Саксофон": ("Saxophone", INTENT_SPECIALTY_STEM),
    "Струнные": ("Strings", INTENT_SPECIALTY_STEM),
    "Щипковые струнные": ("Plucked strings", INTENT_SPECIALTY_STEM),
    "Смычковые струнные": ("Bowed strings", INTENT_SPECIALTY_STEM),
    "Духовые": ("Winds", INTENT_SPECIALTY_STEM),
    "Деревянные духовые": ("Woodwinds", INTENT_SPECIALTY_STEM),
    "Медные духовые": ("Brass", INTENT_SPECIALTY_STEM),
    "Гармоники": ("Harmonics", INTENT_SPECIALTY_STEM),
    "Звуки толпы": ("Crowd", INTENT_SPECIALTY_STEM),
    "Скретч": ("Scratch", INTENT_SPECIALTY_STEM),
    "Кинематограф": ("Cinematic", INTENT_SPECIALTY_STEM),
    "Объёмный звук": ("Surround", INTENT_SPECIALTY_STEM),
    "Фантомный центр": ("Phantom centre", INTENT_SPECIALTY_STEM),
    "Прочее": ("Other", INTENT_UNKNOWN),
}


def translate_category(category: str) -> Tuple[str, str]:
    """Return ``(english_label, intent)`` for an mvsepless category value."""
    text = str(category or "").strip()
    if text in _CATEGORY_TABLE:
        return _CATEGORY_TABLE[text]
    return (text, INTENT_UNKNOWN)


_cached_models: Optional[Dict[str, Any]] = None
_cached_loaded_at: float = 0.0
_cached_converted: Optional[Dict[str, Any]] = None
_refresh_lock = threading.Lock()
_refresh_in_flight = False


def mvsepless_enabled() -> bool:
    return os.environ.get("UVR_DISABLE_MVSEPLESS", "").strip().lower() not in (
        "1",
        "true",
        "yes",
    )


def clear_mvsepless_cache() -> None:
    global _cached_models, _cached_loaded_at, _cached_converted
    _cached_models = None
    _cached_loaded_at = 0.0
    _cached_converted = None
    from .model_display import clear_display_cache

    clear_display_cache()


def _cache_path() -> str:
    return paths.migrate_cache_file("mvsepless_models.json", paths.MVSEPLESS_CACHE_FILE)


def _read_disk_cache() -> Optional[Dict[str, Any]]:
    try:
        with open(_cache_path(), "r", encoding="utf-8") as handle:
            payload = json.load(handle)
        if isinstance(payload, dict) and isinstance(payload.get("data"), dict):
            return payload["data"]
    except (OSError, ValueError, TypeError):
        pass
    return None


def _read_disk_cache_entry() -> Optional[Tuple[Dict[str, Any], float]]:
    """Return ``(data, fetched_at)`` from the on-disk cache, or ``None``."""
    try:
        with open(_cache_path(), "r", encoding="utf-8") as handle:
            payload = json.load(handle)
        if not isinstance(payload, dict) or not isinstance(payload.get("data"), dict):
            return None
        fetched_at = payload.get("fetched_at")
        if not isinstance(fetched_at, (int, float)):
            return None
        return payload["data"], float(fetched_at)
    except (OSError, ValueError, TypeError):
        return None


def _start_background_refresh() -> None:
    """Refresh the catalogue off the main loop; at most one in flight."""
    global _refresh_in_flight
    with _refresh_lock:
        if _refresh_in_flight:
            return
        _refresh_in_flight = True

    def run() -> None:
        global _refresh_in_flight
        try:
            load_mvsepless_models(force=True)
        except Exception as exc:  # noqa: BLE001 - background best-effort
            debug("download", f"mvsepless background refresh failed err={exc}")
        finally:
            with _refresh_lock:
                _refresh_in_flight = False

    threading.Thread(target=run, name="uvr-mvsepless-refresh", daemon=True).start()


def _write_disk_cache(data: Dict[str, Any]) -> None:
    try:
        cache_path = _cache_path()
        os.makedirs(os.path.dirname(cache_path) or ".", exist_ok=True)
        with open(cache_path, "w", encoding="utf-8") as handle:
            json.dump({"fetched_at": time.time(), "data": data}, handle)
    except OSError as exc:
        debug("download", f"mvsepless cache write failed err={exc}")


def load_mvsepless_models(*, force: bool = False) -> Optional[Dict[str, Any]]:
    """Return raw ``models.json`` dict, or ``None`` when disabled/unavailable."""
    global _cached_models, _cached_loaded_at, _cached_converted

    if not mvsepless_enabled():
        return None

    now = time.time()
    if (
        not force
        and _cached_models is not None
        and (now - _cached_loaded_at) < _MVSEPLESS_CACHE_TTL_SECONDS
    ):
        return _cached_models

    if not force:
        entry = _read_disk_cache_entry()
        if entry is not None:
            # Any readable disk entry is served immediately (stale-while-
            # revalidate). TTL only decides whether to refresh in the
            # background — it never blocks the caller on HTTP.
            data, fetched_at = entry
            previous = _cached_models
            _cached_models = data
            _cached_loaded_at = now
            _cached_converted = None
            if data != previous:
                from .model_display import clear_display_cache

                clear_display_cache()
            if (now - fetched_at) >= _MVSEPLESS_CACHE_TTL_SECONDS:
                _start_background_refresh()
            return _cached_models

    data: Optional[Dict[str, Any]] = None
    from_disk = False
    try:
        with _urlopen(MVSEPLESS_MODELS_JSON_URL) as response:
            data = json.load(response)
    except Exception as exc:
        debug("download", f"mvsepless fetch failed err={type(exc).__name__}: {exc}")
        data = _read_disk_cache()
        from_disk = True

    if not isinstance(data, dict):
        return None

    previous = _cached_models
    _cached_models = data
    _cached_loaded_at = now
    _cached_converted = None
    if not from_disk:
        # Rewriting here would stamp fetched_at=now onto the copy we just read
        # back from disk, so an offline session makes month-old data look
        # freshly fetched and the TTL never expires.
        _write_disk_cache(data)
    # Invalidate only when the payload actually changed — identical refetches
    # (typical background refresh) must not discard a still-valid merge.
    if data != previous:
        from .model_display import clear_display_cache

        clear_display_cache()
    return data


def url_basename(url: str) -> str:
    """Return the safe basename of a remote URL (strip query / fragment)."""
    path = urlparse(str(url)).path
    name = os.path.basename(unquote(path))
    return name


def classify_entry(entry_id: str, entry: Mapping[str, Any]) -> Tuple[bool, str]:
    """Return ``(supported, reason)``. Reason is empty when supported."""
    model_type = str(entry.get("model_type") or "")
    if entry_id in _UNSUPPORTED_ENTRY_IDS:
        return False, _UNSUPPORTED_ENTRY_IDS[entry_id]
    if model_type in _UNSUPPORTED_MODEL_TYPES:
        return False, _UNSUPPORTED_MODEL_TYPES[model_type]
    if model_type not in _SUPPORTED_MODEL_TYPES:
        return False, f"unknown model_type {model_type!r}"
    return True, ""


def _safe_remote_basename(url: str) -> Optional[str]:
    parsed = urlparse(str(url))
    if ".." in parsed.path.split("/"):
        return None
    name = os.path.basename(unquote(parsed.path))
    if not name or os.path.basename(name) != name or ".." in name:
        return None
    return name


def entry_files(entry: Mapping[str, Any]) -> Optional[Dict[str, str]]:
    """Build ``{local_filename: url}`` for one catalogue entry."""
    ckpt_url = entry.get("checkpoint_url")
    cfg_url = entry.get("config_url")
    if not isinstance(ckpt_url, str) or not isinstance(cfg_url, str):
        return None
    if not ckpt_url.startswith(("http://", "https://")):
        return None
    if not cfg_url.startswith(("http://", "https://")):
        return None
    ckpt_name = _safe_remote_basename(ckpt_url)
    cfg_name = _safe_remote_basename(cfg_url)
    if not ckpt_name or not cfg_name:
        return None
    return {ckpt_name: ckpt_url, cfg_name: cfg_url}


def entry_label(entry_id: str, entry: Mapping[str, Any]) -> str:
    name = str(entry.get("full_name") or "").strip()
    return name or entry_id


def convert_mvsepless_catalog(
    models: Mapping[str, Any],
) -> Dict[str, Any]:
    """Convert raw ``models.json`` into UVR list keys + unsupported metadata.

    Returns::

        {
          "vr_download_list": {...},
          "mdx_download_list": {...},  # flattened MDX-family supported entries
          "demucs_download_list": {...},
          "unsupported": {arch: [(label, reason), ...]},
          "unsupported_labels": {label: reason},
        }
    """
    lists: Dict[str, Dict[str, Any]] = {
        "vr_download_list": {},
        "mdx_download_list": {},
        "mdx23c_download_list": {},
        "roformer_download_list": {},
        "scnet_download_list": {},
        "bandit_download_list": {},
        "demucs_download_list": {},
    }
    unsupported: Dict[str, List[Tuple[str, str]]] = {
        VR_ARCH_TYPE: [],
        MDX_ARCH_TYPE: [],
        DEMUCS_ARCH_TYPE: [],
    }
    unsupported_labels: Dict[str, str] = {}
    metadata: Dict[str, Dict[str, Any]] = {}
    claimed_supported_labels: set[str] = set()

    for entry_id, entry in models.items():
        if not isinstance(entry, dict):
            continue
        quarantine = _quarantine_reason(str(entry_id), entry)
        if quarantine:
            debug("download", f"mvsepless quarantined id={entry_id} reason={quarantine}")
            continue
        model_type = str(entry.get("model_type") or "")
        label = entry_label(str(entry_id), entry)
        files = entry_files(entry)
        supported, reason = classify_entry(str(entry_id), entry)
        arch = _MODEL_TYPE_TO_ARCH.get(model_type, MDX_ARCH_TYPE)

        # ``full_name`` is not unique in the upstream payload. Preserve every
        # runnable weight by giving later collisions a stable id suffix; the
        # first spelling remains unchanged for compatibility with other
        # catalogue sources and existing searches.
        if supported and files is not None:
            base_label = label
            candidate = label
            suffix = 1
            while candidate.casefold() in claimed_supported_labels:
                discriminator = str(entry_id) if suffix == 1 else f"{entry_id}-{suffix}"
                candidate = f"{base_label} [{discriminator}]"
                suffix += 1
            label = candidate
            claimed_supported_labels.add(label.casefold())

        # Before the supported/unsupported split so grayed-out rows carry
        # metadata too. ``setdefault`` matches the upstream-wins rule the
        # label merge already follows.
        category_en, intent = translate_category(entry.get("category") or "")
        stems = entry.get("stems")
        metadata.setdefault(
            label,
            {
                "entry_id": str(entry_id),
                "model_type": model_type,
                "stems": list(stems) if isinstance(stems, list) else [],
                "target_instrument": entry.get("target_instrument") or None,
                "category": str(entry.get("category") or ""),
                "category_en": category_en,
                "intent": intent,
                "arch": arch,
            },
        )

        if not supported or files is None:
            if not reason:
                reason = "invalid catalogue entry"
            unsupported.setdefault(arch, []).append((label, reason))
            unsupported_labels[label] = reason
            continue

        list_key = _MODEL_TYPE_TO_LIST_KEY.get(model_type)
        if not list_key:
            unsupported.setdefault(arch, []).append(
                (label, f"unmapped model_type {model_type!r}")
            )
            unsupported_labels[label] = f"unmapped model_type {model_type!r}"
            continue
        lists[list_key][label] = files

    # Unsupported records cannot be selected, so duplicate names carry no
    # useful distinction and only create repeated disabled rows in the UI.
    for arch, rows in unsupported.items():
        seen: set[str] = set()
        unique: List[Tuple[str, str]] = []
        for label, reason in rows:
            identity = normalize_catalogue_label(label) or label.casefold()
            if identity in seen:
                continue
            seen.add(identity)
            unique.append((label, reason))
        unsupported[arch] = unique

    # Flatten MDX-family lists the same way Politrees / extras do for the UI.
    mdx_flat: Dict[str, Any] = {}
    for key in _MVSEPLESS_MDX_SOURCE_KEYS:
        mdx_flat = merge_supplemental_list(mdx_flat, lists[key])

    return {
        "vr_download_list": lists["vr_download_list"],
        "mdx_download_list": mdx_flat,
        "demucs_download_list": lists["demucs_download_list"],
        "unsupported": unsupported,
        "unsupported_labels": unsupported_labels,
        "metadata": metadata,
    }


def load_converted_mvsepless(*, force: bool = False) -> Optional[Dict[str, Any]]:
    """Fetch/convert with in-memory cache of the converted shape."""
    global _cached_converted

    if not mvsepless_enabled():
        return None
    if not force and _cached_converted is not None:
        return _cached_converted

    models = load_mvsepless_models(force=force)
    if not models:
        return None
    _cached_converted = convert_mvsepless_catalog(models)
    return _cached_converted


def merge_mvsepless_catalogues(
    vr: Mapping[str, Any],
    mdx: Mapping[str, Any],
    demucs: Mapping[str, Any],
    converted: Optional[Mapping[str, Any]] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Merge supported mvsepless entries; never overwrite existing labels."""
    data = load_converted_mvsepless() if converted is None else converted
    if not data:
        return dict(vr), dict(mdx), dict(demucs)

    vr_out = merge_supplemental_list(vr, data.get("vr_download_list", {}))
    mdx_out = merge_supplemental_list(mdx, data.get("mdx_download_list", {}))
    demucs_out = merge_supplemental_list(demucs, data.get("demucs_download_list", {}))
    return dict(vr_out), dict(mdx_out), dict(demucs_out)


def unsupported_mvsepless_downloads(
    converted: Optional[Mapping[str, Any]] = None,
    *,
    existing_labels: Optional[Mapping[str, Any]] = None,
) -> Dict[str, List[Tuple[str, str]]]:
    """Return ``{arch: [(label, reason), ...]}`` for unsupported entries.

    Labels already present in ``existing_labels`` (any arch catalogue) are
    omitted so upstream-supported duplicates are not shown as broken. Matching
    is exact or via :func:`normalize_catalogue_label`.
    """
    data = load_converted_mvsepless() if converted is None else converted
    if not data:
        return {}

    taken = set(existing_labels or {})
    taken_norm = {
        normalize_catalogue_label(label)
        for label in taken
        if normalize_catalogue_label(label)
    }
    result: Dict[str, List[Tuple[str, str]]] = {}
    raw = data.get("unsupported") or {}
    if not isinstance(raw, dict):
        return {}
    for arch, rows in raw.items():
        if not isinstance(rows, list):
            continue
        filtered: List[Tuple[str, str]] = []
        for item in rows:
            if not (isinstance(item, (list, tuple)) and len(item) == 2):
                continue
            label, reason = str(item[0]), str(item[1])
            if label in taken:
                continue
            norm = normalize_catalogue_label(label)
            if norm and norm in taken_norm:
                continue
            filtered.append((label, reason))
        if filtered:
            # Stable order by label for the UI.
            filtered.sort(key=lambda pair: pair[0].casefold())
            result[str(arch)] = filtered
    return result


def mvsepless_metadata(
    converted: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Dict[str, Any]]:
    """Return ``{label: metadata}`` for every mvsepless entry."""
    data = load_converted_mvsepless() if converted is None else converted
    if not data:
        return {}
    meta = data.get("metadata") or {}
    return dict(meta) if isinstance(meta, dict) else {}


def unsupported_reason_for_label(
    label: str, converted: Optional[Mapping[str, Any]] = None
) -> Optional[str]:
    data = load_converted_mvsepless() if converted is None else converted
    if not data:
        return None
    reasons = data.get("unsupported_labels") or {}
    if not isinstance(reasons, dict):
        return None
    reason = reasons.get(label)
    return str(reason) if reason else None
