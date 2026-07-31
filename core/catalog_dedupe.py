"""Deduplicate Download Center catalogue entries after community merges.

Upstream catalogues (TRvlvr → Politrees → extras → mvsepless) can list the
same weight under different selectable labels, or the same logical model under
slightly different titles. A single pass keeps the **first** occurrence
(insertion order = merge priority) and drops later collisions.
"""

from __future__ import annotations

import os
import re
from typing import Any, Dict, Mapping, Optional, Tuple

from .debug_log import debug

_LABEL_PREFIXES = (
    "roformer model:",
    "mdx23c model:",
    "mdx-net model:",
    "scnet:",
    "bandit:",
    "bandit plus:",
    "bandit v2:",
    "vr arch single model v5:",
    "vr arch single model v4:",
    "demucs v3:",
    "demucs v4:",
    "apollo model:",
)

_STOP_WORDS = frozenset(
    {
        "model",
        "by",
        "the",
        "a",
        "an",
        "and",
        "v5",
        "hq",
    }
)


def primary_checkpoint_name(model: object) -> Optional[str]:
    """Return the primary weight filename for a catalogue value, if any."""
    if isinstance(model, dict):
        for name in model:
            text = str(name)
            if text.endswith(".yaml"):
                continue
            return os.path.basename(text)
        return None
    text = str(model).strip()
    return os.path.basename(text) if text else None


def normalize_catalogue_label(label: str) -> str:
    """Collapse cosmetic label differences for duplicate detection."""
    text = str(label or "").casefold().strip()
    for prefix in _LABEL_PREFIXES:
        if text.startswith(prefix):
            text = text[len(prefix) :].strip()
            break

    text = text.replace("mel-band", "melband").replace("mel band", "melband")
    text = text.replace("band-split", "bandsplit").replace("bs-roformer", "bandsplit roformer")
    text = text.replace("bs roformer", "bandsplit roformer")
    text = text.replace("mdx23c-", "mdx23c ")
    text = text.replace("instvoc", "inst voc").replace("inst-voc", "inst voc")
    text = text.replace("de-echo", "deecho").replace("de-reverb", "dereverb")
    text = text.replace("|", " ")
    text = re.sub(r"\(([^)]*)\)", r" \1 ", text)
    text = re.sub(r"[^a-z0-9]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    parts = [part for part in text.split() if part not in _STOP_WORDS]
    return " ".join(parts)


def _demucs_signature(model: object) -> Optional[Tuple[Tuple[str, str], ...]]:
    """Stable identity for a Demucs multi-file bag."""
    if not isinstance(model, dict) or not model:
        return None
    items = []
    for name, ref in model.items():
        items.append((str(name), str(ref).split("?", 1)[0]))
    return tuple(sorted(items))


def dedupe_download_catalogue(
    catalogue: Mapping[str, Any],
    *,
    demucs_bags: bool = False,
) -> Dict[str, Any]:
    """Return ``catalogue`` with later duplicate entries removed.

    Collision keys (any match drops the later label):

    * primary checkpoint basename (VR / MDX-family; not used for Demucs bags)
    * normalized selectable label
    * for Demucs bags only: identical full file→URL map
    """
    kept: Dict[str, Any] = {}
    seen_ckpts: set[str] = set()
    seen_labels: set[str] = set()
    seen_bags: set[Tuple[Tuple[str, str], ...]] = set()
    dropped = 0

    for label, model in catalogue.items():
        norm = normalize_catalogue_label(label)
        if norm and norm in seen_labels:
            dropped += 1
            continue

        if demucs_bags:
            signature = _demucs_signature(model)
            if signature is not None and signature in seen_bags:
                dropped += 1
                continue
        else:
            ckpt = primary_checkpoint_name(model)
            if ckpt:
                key = ckpt.casefold()
                if key in seen_ckpts:
                    dropped += 1
                    continue
                seen_ckpts.add(key)

        kept[label] = model
        if norm:
            seen_labels.add(norm)
        if demucs_bags:
            signature = _demucs_signature(model)
            if signature is not None:
                seen_bags.add(signature)

    if dropped:
        debug("download", f"catalogue dedupe dropped {dropped} duplicate entries")
    return kept
