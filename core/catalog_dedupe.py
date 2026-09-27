"""Deduplicate Download Center catalogue entries after community merges.

Upstream catalogues (TRvlvr → Politrees → extras → mvsepless) can list the
same weight under different selectable labels, or the same logical model under
slightly different titles. A single pass keeps the **first** occurrence
(insertion order = merge priority) and drops later collisions.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Any, Dict, Mapping, Optional, Tuple
from urllib.parse import parse_qsl, unquote, urlencode, urlsplit, urlunsplit

_LABEL_PREFIXES = (
    "roformer model vip:",
    "roformer model:",
    "mdx23c model vip:",
    "mdx23c model:",
    "mdx23 model vip:",
    "mdx23 model:",
    "mdx-net model vip:",
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
    family = ""
    for prefix in _LABEL_PREFIXES:
        if text.startswith(prefix):
            if prefix == "scnet:":
                family = "scnet"
            text = text[len(prefix) :].strip()
            break

    # ``+`` is part of several real model version names (v1+, Fv7+). Treat it
    # like the written word "Plus" instead of letting punctuation stripping
    # collapse those weights onto their non-plus predecessors.
    text = text.replace("+", " plus ")
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
    # Some sources express SCNet as a catalogue prefix while others put it in
    # the title, and the older curated labels do both (``SCnet: ... SCNet``).
    # Keep the family once, in a stable position, so those source aliases
    # collide without weakening identity matching for the descriptive title.
    if family == "scnet" or "scnet" in parts:
        parts = ["scnet", *(part for part in parts if part != "scnet")]
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


def _checkpoint_name_matches_url(model: object) -> bool:
    """Whether a model's local checkpoint name matches its remote basename.

    A shared URL normally means aliases for the same bytes. When one alias
    renames the file to a conflicting model title while another keeps the
    remote basename, the matching entry is the trustworthy one. This catches
    malformed source rows such as a ``Bleedless`` local name pointing at the
    ``Fullness`` checkpoint without penalising ordinary single-entry rehosts.
    """
    name = primary_checkpoint_name(model)
    url = primary_checkpoint_url(model)
    if not name or not url:
        return False
    remote_name = os.path.basename(unquote(urlsplit(url).path))
    return name.casefold() == remote_name.casefold()


@dataclass(frozen=True)
class CatalogueDuplicate:
    """A dropped row and the kept row it provably duplicates.

    ``evidence`` names the exact key both rows share, strongest first:
    ``sha256`` (same content), ``rehost`` (reviewed copy of the kept
    checkpoint), ``url`` (same download) or ``checkpoint`` (same checkpoint
    filename, ignoring case). A shared normalized label alone never counts.
    """

    kept: str
    evidence: str


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
    * content identity (SHA-256) when ``content_ids`` maps the primary URL
    * normalized selectable label
    * for Demucs bags only: identical full file→URL map

    Insertion order is merge priority: earlier catalogues win.
    :mod:`core.checkpoint_identities` adds reviewed rows: withdrawn rows are
    dropped before they claim any key, and a rehost collides on the upstream
    checkpoint name it copies.
    """
    return _dedupe(catalogue, demucs_bags=demucs_bags, content_ids=content_ids)[0]


def find_catalogue_duplicates(
    catalogue: Mapping[str, Any],
    *,
    content_ids: Optional[Mapping[str, str]] = None,
) -> Tuple[Dict[str, Any], Dict[str, CatalogueDuplicate]]:
    """Deduplicate a VR / MDX-family catalogue and explain the dropped rows.

    Returns the rows :func:`dedupe_download_catalogue` keeps, plus each dropped
    row whose exact keys (content, rehost, URL, checkpoint name) all belong to
    one kept row. Rows dropped for a shared label alone, withdrawn rows and
    rows whose keys point at different kept rows are left out.
    """
    return _dedupe(catalogue, demucs_bags=False, content_ids=content_ids)


def _dedupe(
    catalogue: Mapping[str, Any],
    *,
    demucs_bags: bool,
    content_ids: Optional[Mapping[str, str]],
) -> Tuple[Dict[str, Any], Dict[str, CatalogueDuplicate]]:
    from .checkpoint_identities import load_checkpoint_identities

    identities = load_checkpoint_identities()
    kept: Dict[str, Any] = {}
    # Each key maps to the kept label that claimed it.
    seen_ckpts: Dict[str, str] = {}
    seen_urls: Dict[str, str] = {}
    seen_content: Dict[str, str] = {}
    seen_labels: set[str] = set()
    seen_bags: set[Tuple[Tuple[str, str], ...]] = set()
    ids = content_ids or {}

    # Prefer a filename-consistent row within a same-URL collision even when
    # it appears later. With no unique consistent row, insertion priority still
    # decides as before.
    url_rows: Dict[str, list[Tuple[str, Any]]] = {}
    for label, model in catalogue.items():
        url = primary_checkpoint_url(model)
        if url:
            url_rows.setdefault(url, []).append((label, model))
    preferred_url_labels: Dict[str, str] = {}
    for url, rows in url_rows.items():
        matching = [label for label, model in rows if _checkpoint_name_matches_url(model)]
        if len(rows) > 1 and len(matching) == 1:
            preferred_url_labels[url] = matching[0]

    for label, model in catalogue.items():
        if primary_checkpoint_url(model) in identities.withdrawn:
            continue
        url = primary_checkpoint_url(model) if not demucs_bags else None
        preferred = preferred_url_labels.get(url or "")
        if preferred is not None and label != preferred:
            continue

        norm = normalize_catalogue_label(label)
        if norm and norm in seen_labels:
            continue

        if demucs_bags:
            signature = _demucs_signature(model)
            if signature is not None and signature in seen_bags:
                continue
        else:
            url = primary_checkpoint_url(model)
            ckpt = identities.rehosts.get(url or "") or primary_checkpoint_name(model)
            if ckpt:
                key = ckpt.casefold()
                if key in seen_ckpts:
                    continue
            if url and url in seen_urls:
                continue
            content_id = _lookup_content_id(url, ids)
            if content_id and content_id in seen_content:
                continue
            if ckpt:
                seen_ckpts[ckpt.casefold()] = label
            if url:
                seen_urls[url] = label
            if content_id:
                seen_content[content_id] = label

        kept[label] = model
        if norm:
            seen_labels.add(norm)
        if demucs_bags:
            signature = _demucs_signature(model)
            if signature is not None:
                seen_bags.add(signature)

    duplicates: Dict[str, CatalogueDuplicate] = {}
    if demucs_bags:
        return kept, duplicates
    for label, model in catalogue.items():
        url = primary_checkpoint_url(model)
        if label in kept or url in identities.withdrawn:
            continue
        rehost = identities.rehosts.get(url or "")
        name = primary_checkpoint_name(model)
        content_id = _lookup_content_id(url, ids)
        # The same checks as the pass above, in order of evidence strength.
        candidates = [
            ("sha256", seen_content.get(content_id) if content_id else None),
            ("rehost", seen_ckpts.get(rehost.casefold()) if rehost else None),
            ("url", seen_urls.get(url) if url else None),
            ("checkpoint", seen_ckpts.get(name.casefold()) if name and not rehost else None),
        ]
        found = [(evidence, owner) for evidence, owner in candidates if owner is not None]
        if found and len({owner for _evidence, owner in found}) == 1:
            evidence, owner = found[0]
            duplicates[label] = CatalogueDuplicate(owner, evidence)
    return kept, duplicates
