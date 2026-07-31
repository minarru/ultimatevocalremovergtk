"""Canonical display names for catalogue models.

Four sources contribute labels in four house styles (upstream TRvlvr,
Politrees, ``bundled/extra_models.json``, mvsepless). This module is the only
place that decides what a model is *called*, so the Download Center and the
runtime method pickers cannot disagree.

Normalization is deliberately conservative: category prefixes are stripped,
architecture-family spellings are unified, and the author separator is
normalized. The descriptive middle of a label passes through verbatim, so no
model is ever renamed into something misleading.
"""

from __future__ import annotations

import re
from typing import Tuple

#: Rendered between the family and the descriptive title.
TITLE_SEPARATOR = " — "
#: Rendered between the title and the author.
AUTHOR_SEPARATOR = " · "

#: Download Center category prefixes. Longest-first so ``MDX23C Model VIP: ``
#: is matched before ``MDX23C Model: ``.
_CATEGORY_PREFIXES = (
    "VR Arch Single Model v5: ",
    "VR Arch Single Model v4: ",
    "VR Arch Single Model ",
    "VR Arch ",
    "MDX23C Model VIP: ",
    "MDX-Net Model VIP: ",
    "Roformer Model VIP: ",
    "MDX23C Model: ",
    "MDX-Net Model: ",
    "Roformer Model: ",
    "Apollo Model: ",
    "Bandit Plus: ",
    "Bandit v2: ",
    "MDX23C: ",
    "MDX-Net: ",
    "Bandit: ",
    "SCnet: ",
)

#: ``(regex, canonical family)`` — first match wins, so longer/more specific
#: families must come first.
_FAMILY_PATTERNS = (
    (re.compile(r"^mel[\s_-]?band[\s_-]?roformer\b", re.IGNORECASE), "MelBand Roformer"),
    (re.compile(r"^(?:bs|band[\s_-]?split)[\s_-]?roformer\b", re.IGNORECASE), "BandSplit Roformer"),
    (re.compile(r"^mdx23c\b", re.IGNORECASE), "MDX23C"),
    (re.compile(r"^scnet\b", re.IGNORECASE), "SCNet"),
    (re.compile(r"^bandit\b", re.IGNORECASE), "Bandit"),
    (re.compile(r"^apollo\b", re.IGNORECASE), "Apollo"),
)

#: ``by <author>`` at the end of a label, in any of the four dialects — or the
#: canonical ``· <author>`` this function itself emits, which is what makes
#: ``canonical_display_name`` idempotent.
_AUTHOR_RE = re.compile(
    r"(?:\s+by[\s_-]+|\s*\u00b7\s*)(?P<author>[^|\u00b7]+?)\s*$", re.IGNORECASE
)

_DEMUCS_RE = re.compile(r"^Demucs (v\d+): (.+)$", re.IGNORECASE)


#: Category prefixes that themselves declare a family. ``Roformer Model: `` is
#: absent on purpose: it does not say *which* Roformer, and the remainder does.
_PREFIX_FAMILIES = {
    "SCnet: ": "SCNet",
    "MDX23C Model VIP: ": "MDX23C",
    "MDX23C Model: ": "MDX23C",
    "MDX23C: ": "MDX23C",
    "MDX-Net Model VIP: ": "MDX-Net",
    "MDX-Net Model: ": "MDX-Net",
    "MDX-Net: ": "MDX-Net",
    "Bandit Plus: ": "Bandit",
    "Bandit v2: ": "Bandit",
    "Bandit: ": "Bandit",
    "Apollo Model: ": "Apollo",
}


def split_catalogue_prefix(label: str) -> Tuple[str, str]:
    """Return ``(family_from_prefix, remainder)`` for a catalogue label.

    The category prefix is often the only place the family is named — the
    remainder of ``SCnet: 4-stems Huge SCNet Bleedless by Aname`` starts with
    ``4-stems``, so dropping the prefix would lose the family entirely.
    """
    text = str(label or "").strip()
    family = ""
    for prefix in _CATEGORY_PREFIXES:
        if text.lower().startswith(prefix.lower()):
            family = _PREFIX_FAMILIES.get(prefix, "")
            text = text[len(prefix):].strip()
            break
    if text.lower().endswith(".ckpt"):
        text = text[: -len(".ckpt")].strip()
    return family, text


def strip_catalogue_prefix(label: str) -> str:
    """Remove a Download Center category prefix and a trailing ``.ckpt``."""
    return split_catalogue_prefix(label)[1]


def canonical_family(text: str) -> str:
    """Return the canonical family name a label starts with, or ``""``."""
    stripped = str(text or "").lstrip()
    for pattern, family in _FAMILY_PATTERNS:
        if pattern.match(stripped):
            return family
    return ""


def canonical_display_name(label: str) -> str:
    """Return the canonical display name for a catalogue label.

    Idempotent: running it over its own output is a no-op, so a label that has
    already been canonicalized upstream is safe to pass through again.
    """
    prefix_family, text = split_catalogue_prefix(label)
    if not text:
        return ""

    match = _DEMUCS_RE.match(text)
    if match:
        return f"{match.group(1)}{TITLE_SEPARATOR}{match.group(2)}"

    author = ""
    author_match = _AUTHOR_RE.search(text)
    if author_match:
        author = author_match.group("author").strip()
        text = text[: author_match.start()].strip()

    # Already canonical (contains the title separator): keep the head verbatim
    # as the family. This is what makes the function idempotent for families
    # that canonical_family cannot re-detect, such as MDX-Net and Demucs vN.
    if TITLE_SEPARATOR in text:
        head, _, tail = text.partition(TITLE_SEPARATOR)
        return _join(head.strip(), tail, author)

    # A family named by the remainder wins; the prefix is the fallback.
    family = canonical_family(text)
    if not family and prefix_family and not text.lower().startswith(prefix_family.lower()):
        return _join(prefix_family, text, author)
    if family:
        pattern = next(p for p, f in _FAMILY_PATTERNS if f == family)
        remainder = pattern.sub("", text.lstrip(), count=1)
    else:
        remainder = text
    # Both dialect separators collapse to whitespace before re-rendering.
    remainder = remainder.replace("|", " ")
    remainder = remainder.replace(TITLE_SEPARATOR.strip(), " ")
    remainder = remainder.replace(AUTHOR_SEPARATOR.strip(), " ")
    remainder = re.sub(r"\s+", " ", remainder).strip(" -—")

    if family and remainder:
        title = f"{family}{TITLE_SEPARATOR}{remainder}"
    elif family:
        title = family
    else:
        title = remainder

    if author:
        title = f"{title}{AUTHOR_SEPARATOR}{author}"
    return title


def _join(family: str, remainder: str, author: str) -> str:
    text = re.sub(r"\s+", " ", remainder.replace("|", " ")).strip(" -\u2014")
    title = f"{family}{TITLE_SEPARATOR}{text}" if text else family
    return f"{title}{AUTHOR_SEPARATOR}{author}" if author else title
