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
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping, Tuple

from .model_identity import parse_stored_model_id

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
    "MDX23 Model VIP: ",
    "MDX-Net Model VIP: ",
    "Roformer Model VIP: ",
    "MDX23C Model: ",
    "MDX23 Model: ",
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
    (re.compile(r"^mdx23c(?=$|[\s_|-])", re.IGNORECASE), "MDX23C"),
    (re.compile(r"^scnet\b", re.IGNORECASE), "SCNet"),
    (re.compile(r"^bandit\b", re.IGNORECASE), "Bandit"),
    (re.compile(r"^apollo\b", re.IGNORECASE), "Apollo"),
)

#: ``by <author>`` at the end of a label, in any of the four dialects — or the
#: canonical ``· <author>`` this function itself emits, which is what makes
#: ``canonical_display_name`` idempotent.
_AUTHOR_RE = re.compile(r"(?:\s+by[\s_-]+|\s*\u00b7\s*)(?P<author>[^|\u00b7]+?)\s*$", re.IGNORECASE)

_DEMUCS_RE = re.compile(r"^Demucs (v\d+)(?::| —) (.+)$", re.IGNORECASE)

#: mvsepless HyperACE rows append this parenthetical; crop it for display.
_HYPERACE_FINETUNE_PAREN_RE = re.compile(
    r"\s*\(\s*finetuned\s+anvuew\s+vocal\s+model\s*\)\s*",
    re.IGNORECASE,
)

_MANIFEST_PATH = Path(__file__).resolve().parent.parent / "bundled" / "model_manifest.json"
_EMPTY_DISPLAY_MANIFEST: Mapping[str, Any] = MappingProxyType(
    {
        "author_aliases": MappingProxyType({}),
        "model_aliases": MappingProxyType({}),
        "waivers": MappingProxyType({}),
    }
)
_STEM_COUNT_RE = re.compile(r"(?<!\()\b(?P<count>\d+)[\s-]+stems?\b", re.IGNORECASE)
_TOKEN_REPLACEMENTS = (
    (re.compile(r"\binst(?:rumental)?[-\s]?voc(?:als)?\b", re.IGNORECASE), "Instrumental/Vocals"),
    (re.compile(r"\binst\b", re.IGNORECASE), "Instrumental"),
    (re.compile(r"\bvoc\b", re.IGNORECASE), "Vocals"),
    (re.compile(r"\bvox\b", re.IGNORECASE), "Vocals"),
    (re.compile(r"\bvocal\b", re.IGNORECASE), "Vocals"),
    (re.compile(r"\bft\b", re.IGNORECASE), "Fine-Tuned"),
    (re.compile(r"\bhigh[\s_-]+quality\b", re.IGNORECASE), "HQ"),
    (re.compile(r"\bhq\b", re.IGNORECASE), "HQ"),
    (re.compile(r"\bsdr\b", re.IGNORECASE), "SDR"),
    (re.compile(r"\bfft\b", re.IGNORECASE), "FFT"),
    (re.compile(r"\b8k\b", re.IGNORECASE), "8K"),
    (re.compile(r"\b16k\b", re.IGNORECASE), "16 kHz"),
    (re.compile(r"\bde[\s_-]?verb\b|\bdereverb\b", re.IGNORECASE), "DeReverb"),
    (re.compile(r"\bdenoise\b", re.IGNORECASE), "DeNoise"),
    (re.compile(r"\bdebleed\b", re.IGNORECASE), "DeBleed"),
    (re.compile(r"\bspeechsep\b", re.IGNORECASE), "SpeechSep"),
    (re.compile(r"\bchoirsep\b", re.IGNORECASE), "ChoirSep"),
    (re.compile(r"\bdrumsep\b", re.IGNORECASE), "DrumSep"),
    (re.compile(r"\bmale[\s_-]+female\b", re.IGNORECASE), "Male/Female"),
    (
        re.compile(r"\b(beta|preview|full|final)\b", re.IGNORECASE),
        lambda match: match.group(1).title(),
    ),
    (re.compile(r"\bV(?=\d+(?:\.\d+)?\b)", re.IGNORECASE), "v"),
)
_DEMUCS_BACKEND_ALIASES = {
    "demucs": "Time-Domain",
    "demucs_extra": "Time-Domain Extra",
    "light": "Light",
    "light_extra": "Light Extra",
    "tasnet": "Conv-TasNet",
    "tasnet_extra": "Conv-TasNet Extra",
    "demucs48_hq": "Time-Domain 48 kHz HQ",
    "demucs_unittest": "Unit Test",
    "mdx": "MDX",
    "mdx_extra": "MDX Extra",
    "mdx_extra_q": "MDX Extra Quantized",
    "mdx_q": "MDX Quantized",
    "repro_mdx_a": "Repro MDX A",
    "repro_mdx_a_hybrid_only": "Repro MDX A Hybrid Only",
    "repro_mdx_a_time_only": "Repro MDX A Time-Domain Only",
    "uvr model": "UVR Model (2 Stems)",
    "hdemucs_mmi": "Hybrid Demucs MMI",
    "htdemucs": "Hybrid Transformer",
    "htdemucs_6s": "Hybrid Transformer (6 Stems)",
    "htdemucs_ft": "Hybrid Transformer Fine-Tuned",
}


#: Category prefixes that themselves declare a family. ``Roformer Model: `` is
#: absent on purpose: it does not say *which* Roformer, and the remainder does.
_PREFIX_FAMILIES = {
    "VR Arch Single Model v5: ": "VR v5",
    "VR Arch Single Model v4: ": "VR v4",
    "VR Arch Single Model ": "VR",
    "VR Arch ": "VR",
    "SCnet: ": "SCNet",
    "MDX23C Model VIP: ": "MDX23C",
    "MDX23 Model VIP: ": "MDX23C",
    "MDX23C Model: ": "MDX23C",
    "MDX23 Model: ": "MDX23C",
    "MDX23C: ": "MDX23C",
    "MDX-Net Model VIP: ": "MDX-Net",
    "MDX-Net Model: ": "MDX-Net",
    "MDX-Net: ": "MDX-Net",
    "Bandit Plus: ": "Bandit",
    "Bandit v2: ": "Bandit",
    "Bandit: ": "Bandit",
    "Apollo Model: ": "Apollo",
}


def load_model_display_manifest(path: str | Path = _MANIFEST_PATH) -> Mapping[str, Any]:
    """Return the presentation view from one unified manifest.

    The manifest is deliberately data-only: it may improve a title, but it
    never supplies an identity lookup or accepts a display string as an ID.
    """
    from .model_manifest import ModelManifestError, load_model_manifest

    manifest_path = Path(path)
    try:
        return load_model_manifest(manifest_path).presentation
    except ModelManifestError:
        # ``load_model_manifest`` owns the bounded critical diagnostic for the
        # bundled path. Presentation is an application boundary: a damaged
        # atomic authority must publish no partial view, but it must not make
        # imports fail before callers can fall back to raw canonical names.
        if manifest_path.resolve() == _MANIFEST_PATH.resolve():
            return _EMPTY_DISPLAY_MANIFEST
        raise


_DISPLAY_MANIFEST = load_model_display_manifest()


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
            text = text[len(prefix) :].strip()
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


def _strip_hyperace_finetune_paren(text: str) -> str:
    """Drop the mvsepless HyperACE ``(finetuned anvuew vocal model)`` note."""
    cleaned = _HYPERACE_FINETUNE_PAREN_RE.sub(" ", text)
    return re.sub(r"^[\s—-]+|[\s—-]+$", "", re.sub(r"\s+", " ", cleaned))


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
        return f"Demucs {match.group(1)}{TITLE_SEPARATOR}{match.group(2)}"

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
    remainder = re.sub(r"\s+", " ", remainder).strip(" _-—")
    remainder = _strip_hyperace_finetune_paren(remainder)

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
    text = _strip_hyperace_finetune_paren(
        re.sub(r"\s+", " ", remainder.replace("|", " ")).strip(" -\u2014")
    )
    title = f"{family}{TITLE_SEPARATOR}{text}" if text else family
    return f"{title}{AUTHOR_SEPARATOR}{author}" if author else title


def _project_source_label(
    source_label: str,
    *,
    presentation: Mapping[str, Any] | None = None,
) -> str:
    """Apply only deterministic presentation cleanup to one exact source label."""
    selected_presentation = _DISPLAY_MANIFEST if presentation is None else presentation
    display = canonical_display_name(source_label)
    if not display:
        return ""

    title, separator, author = display.partition(AUTHOR_SEPARATOR)
    title = re.sub(r"^BS\s+PolarFormer\b", "BandSplit PolarFormer", title, flags=re.IGNORECASE)
    if title.startswith("BandSplit PolarFormer ") and TITLE_SEPARATOR not in title:
        title = title.replace(
            "BandSplit PolarFormer ", f"BandSplit PolarFormer{TITLE_SEPARATOR}", 1
        )
    title = re.sub(r"^(MDX-Net — )UVR-MDX-NET[_-]?", r"\1UVR ", title)
    if title.startswith("MDX-Net — UVR"):
        title = title.replace("_", " ")
    for pattern, replacement in _TOKEN_REPLACEMENTS:
        title = pattern.sub(replacement, title)
    title = _STEM_COUNT_RE.sub(r"(\g<count> Stems)", title)
    family, family_separator, remainder = title.partition(TITLE_SEPARATOR)
    if family_separator:
        repeated_family = re.compile(
            rf"^(?P<prefix>(?:\(\d+ Stems\)\s+)?(?:Huge\s+)?)"
            rf"{re.escape(family)}\b[\s_-]*",
            re.IGNORECASE,
        )
        remainder = repeated_family.sub(r"\g<prefix>", remainder)
        count_match = re.search(r"\((?P<count>\d+) Stems\)", remainder)
        if count_match:
            stem_count = count_match.group(0)
            remainder = re.sub(r"\(\d+ Stems\)", " ", remainder, count=1)
            remainder = re.sub(
                r"\b(?P<version>v\d+(?:\.\d+)?)\s+(?P<size>Small|Large|XL)\b",
                r"\g<size> \g<version>",
                remainder,
                flags=re.IGNORECASE,
            )
            remainder = re.sub(r"\s+", " ", remainder).strip(" -—")
            title = (
                f"{family}{TITLE_SEPARATOR}{remainder} {stem_count}"
                if remainder
                else f"{family} {stem_count}"
            )
        else:
            title = f"{family}{TITLE_SEPARATOR}{remainder}"
    version, demucs_separator, backend = title.partition(TITLE_SEPARATOR)
    if demucs_separator and re.fullmatch(r"Demucs v\d+", version, re.IGNORECASE):
        title = (
            f"{version}{TITLE_SEPARATOR}{_DEMUCS_BACKEND_ALIASES.get(backend.casefold(), backend)}"
        )
    title = re.sub(r"\s+", " ", title).strip()

    if not separator:
        return title
    author = re.sub(r"(\()\s*sdr\b", r"\1SDR", author, flags=re.IGNORECASE)
    author = re.sub(r"\s*\(\s*only weights\s*\)\s*$", "", author, flags=re.IGNORECASE)
    canonical_components: list[str] = []
    for component in re.split(r"\s*&\s*", author.strip()):
        token = component.strip()
        canonical_components.append(
            selected_presentation["author_aliases"].get(token.casefold(), token)
        )
    canonical_author = " & ".join(component for component in canonical_components if component)
    return f"{title}{AUTHOR_SEPARATOR}{canonical_author}" if canonical_author else title


def project_model_display(
    model_id: str,
    *,
    source_label: str = "",
    explicit_display: str = "",
    presentation: Mapping[str, Any] | None = None,
) -> str:
    """Return the human display label for one exact canonical model ID.

    ``model_id`` is validated but never inferred from either presentation
    argument.  Precedence is trusted override, exact manifest alias, exact
    source label, then a family-labelled raw basename for VR/Demucs or the raw
    basename for another family.
    """
    exact_id = parse_stored_model_id(model_id)
    override = str(explicit_display or "").strip()
    if override:
        return override
    selected_presentation = _DISPLAY_MANIFEST if presentation is None else presentation
    alias = selected_presentation["model_aliases"].get(exact_id.value)
    if alias:
        return alias
    source = _project_source_label(
        str(source_label or ""),
        presentation=selected_presentation,
    )
    if source:
        return source
    if exact_id.family == "vr":
        return f"VR{TITLE_SEPARATOR}{exact_id.basename}"
    if exact_id.family == "demucs":
        return f"Demucs{TITLE_SEPARATOR}{exact_id.basename}"
    return exact_id.basename
