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
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

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


def normalize_checkpoint_url(url: str) -> str:
    """Collapse cosmetic URL differences for duplicate detection.

    Strips the Hugging Face ``download=`` query flag (and empty queries) so
    rehosts that only differ by ``?download=true`` collide.
    """
    text = str(url or "").strip()
    if not text:
        return ""
    parts = urlsplit(text)
    query_items = [
        (key, value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if key != "download"
    ]
    query = urlencode(query_items, doseq=True)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, query, ""))


def primary_checkpoint_url(model: object) -> Optional[str]:
    """Return the normalized primary weight URL for a catalogue value, if any."""
    if not isinstance(model, dict):
        return None
    for name, ref in model.items():
        text = str(name)
        if text.endswith((".yaml", ".yml")):
            continue
        url = str(ref or "").strip()
        if url.startswith(("http://", "https://")):
            return normalize_checkpoint_url(url)
    return None


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


def _lookup_content_id(
    url: Optional[str],
    content_ids: Mapping[str, str],
) -> Optional[str]:
    if not url or not content_ids:
        return None
    direct = content_ids.get(url)
    if direct:
        return direct
    # Callers may key by the raw catalogue URL; try a normalized pass.
    for key, value in content_ids.items():
        if normalize_checkpoint_url(key) == url:
            return value
    return None


def dedupe_download_catalogue(
    catalogue: Mapping[str, Any],
    *,
    demucs_bags: bool = False,
    content_ids: Optional[Mapping[str, str]] = None,
) -> Dict[str, Any]:
    """Return ``catalogue`` with later duplicate entries removed.

    Collision keys (any match drops the later label):

    * primary checkpoint basename (VR / MDX-family; not used for Demucs bags)
    * normalized primary checkpoint URL (VR / MDX-family)
    * content identity (etag) when ``content_ids`` maps the primary URL
    * normalized selectable label
    * for Demucs bags only: identical full file→URL map

    Insertion order is merge priority: earlier catalogues win.
    """
    kept: Dict[str, Any] = {}
    seen_ckpts: set[str] = set()
    seen_urls: set[str] = set()
    seen_content: set[str] = set()
    seen_labels: set[str] = set()
    seen_bags: set[Tuple[Tuple[str, str], ...]] = set()
    ids = content_ids or {}

    for label, model in catalogue.items():
        norm = normalize_catalogue_label(label)
        if norm and norm in seen_labels:
            continue

        if demucs_bags:
            signature = _demucs_signature(model)
            if signature is not None and signature in seen_bags:
                continue
        else:
            ckpt = primary_checkpoint_name(model)
            if ckpt:
                key = ckpt.casefold()
                if key in seen_ckpts:
                    continue
            url = primary_checkpoint_url(model)
            if url and url in seen_urls:
                continue
            content_id = _lookup_content_id(url, ids)
            if content_id and content_id in seen_content:
                continue
            if ckpt:
                seen_ckpts.add(ckpt.casefold())
            if url:
                seen_urls.add(url)
            if content_id:
                seen_content.add(content_id)

        kept[label] = model
        if norm:
            seen_labels.add(norm)
        if demucs_bags:
            signature = _demucs_signature(model)
            if signature is not None:
                seen_bags.add(signature)

    return kept
