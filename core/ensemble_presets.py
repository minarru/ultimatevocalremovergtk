"""Bundled curated ensemble recipes (model combos + algorithm pairs)."""

from __future__ import annotations
import typing

import json
import os
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from bundled.constants import (
    DEMUCS_ARCH_TYPE,
    MDX_ARCH_TYPE,
    VR_ARCH_TYPE,
)
from core import paths
from core.debug_log import debug
from core.model_display import (
    parse_model_tag,
    resolve_model_basename,
    sanitize_catalogue_label,
)
from core.politrees_catalog import mdx_checkpoint_filename

CURATED_ENSEMBLE_DIR = os.path.join(paths.BUNDLED_DATA_DIR, "ensemble_presets")

# Prefix shown in the Saved ensemble combo for bundled recipes.
CURATED_COMBO_PREFIX = "Curated: "


def curated_combo_label(preset_id: str) -> str:
    return f"{CURATED_COMBO_PREFIX}{preset_id.replace('_', ' ')}"


def curated_id_from_combo_label(label: str) -> Optional[str]:
    text = (label or "").strip()
    if not text.startswith(CURATED_COMBO_PREFIX):
        return None
    return text[len(CURATED_COMBO_PREFIX) :].strip().replace(" ", "_")


def is_curated_combo_label(label: str) -> bool:
    return curated_id_from_combo_label(label) is not None


def list_curated_ensembles() -> List[str]:
    """Return curated preset ids (filename stems), sorted."""
    if not os.path.isdir(CURATED_ENSEMBLE_DIR):
        return []
    names = [
        os.path.splitext(entry)[0]
        for entry in os.listdir(CURATED_ENSEMBLE_DIR)
        if entry.lower().endswith(".json")
    ]
    return sorted(names)


def _preset_path(preset_id: str) -> str:
    return os.path.join(CURATED_ENSEMBLE_DIR, f"{preset_id.replace(' ', '_')}.json")


def load_curated_ensemble(preset_id: str) -> Optional[dict]:
    """Load a curated preset JSON (same core fields as user ensembles)."""
    path = _preset_path(preset_id)
    if not os.path.isfile(path):
        return None
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError, TypeError) as exc:
        debug("ensemble", f"curated load failed id={preset_id!r} err={exc}")
        return None
    if not isinstance(data, dict):
        return None
    return data


def resolve_member_tag(tag: str, repo: typing.Any) -> str:
    """Rewrite an ensemble member reference to a canonical ``family:basename`` id."""
    from core.model_identity import FAMILY_BY_ARCH, ModelId

    arch, model_name = parse_model_tag(tag)
    if not arch or not model_name:
        return tag
    basename = resolve_model_basename(arch, model_name, repo) or model_name
    stem = os.path.splitext(basename)[0]
    family = FAMILY_BY_ARCH.get(arch)
    if family and stem and ":" not in stem:
        return str(ModelId(family, stem))
    return tag


def resolve_member_tags(tags: Sequence[str], repo: typing.Any) -> List[str]:
    return [resolve_member_tag(tag, repo) for tag in tags]


def _installed_basenames(repo: typing.Any, arch: str) -> set:
    if arch == VR_ARCH_TYPE:
        return set(repo.list_vr_models())
    if arch == MDX_ARCH_TYPE:
        return set(repo.list_mdx_models())
    if arch == DEMUCS_ARCH_TYPE:
        return set(repo.list_demucs_models())
    return set()


def member_is_installed(tag: str, repo: typing.Any) -> bool:
    arch, model_name = parse_model_tag(tag)
    if not arch or not model_name:
        return False
    basename = resolve_model_basename(arch, model_name, repo)
    installed = _installed_basenames(repo, arch)
    if basename in installed:
        return True
    # Some lists store stems without extension.
    stem = os.path.splitext(basename)[0]
    return stem in installed or any(os.path.splitext(item)[0] == stem for item in installed)


def classify_preset_members(
    tags: Sequence[str],
    repo: typing.Any,
) -> Tuple[List[str], List[str]]:
    """Return ``(installed_tags, missing_tags)`` after display-name resolution."""
    installed: List[str] = []
    missing: List[str] = []
    for tag in tags:
        resolved = resolve_member_tag(tag, repo)
        if member_is_installed(resolved, repo) or member_is_installed(tag, repo):
            installed.append(resolved)
        else:
            missing.append(tag)
    return installed, missing


def _catalogue_for_arch(manager: typing.Any, arch: str) -> Dict[str, object]:
    if arch == VR_ARCH_TYPE:
        return getattr(manager, "vr_download_list", {}) or {}
    if arch == MDX_ARCH_TYPE:
        return getattr(manager, "mdx_download_list", {}) or {}
    if arch == DEMUCS_ARCH_TYPE:
        return getattr(manager, "demucs_download_list", {}) or {}
    return {}


def find_download_selection(tag: str, manager: typing.Any) -> Optional[Tuple[str, str]]:
    """Map an ensemble tag to ``(catalogue_selectable, arch)`` for enqueue."""
    arch, model_name = parse_model_tag(tag)
    if not arch or not model_name:
        return None
    if hasattr(manager, "ensure_catalogues"):
        try:
            manager.ensure_catalogues(allow_network=False)
        except TypeError:
            manager.ensure_catalogues()
    catalogue = _catalogue_for_arch(manager, arch)
    if not catalogue:
        return None

    target_display = sanitize_catalogue_label(model_name).casefold()
    target_basenames = {
        model_name.casefold(),
        sanitize_catalogue_label(model_name).casefold(),
        os.path.splitext(model_name)[0].casefold(),
    }

    for selectable, model in catalogue.items():
        selectable_display = sanitize_catalogue_label(selectable).casefold()
        if selectable_display == target_display or selectable.casefold() == model_name.casefold():
            return selectable, arch
        if arch == MDX_ARCH_TYPE:
            checkpoint = mdx_checkpoint_filename(model)
            stem = os.path.splitext(checkpoint)[0].casefold()
            if stem in target_basenames or checkpoint.casefold() in target_basenames:
                return selectable, arch
        elif isinstance(model, str):
            stem = os.path.splitext(model)[0].casefold()
            if stem in target_basenames or model.casefold() in target_basenames:
                return selectable, arch
        elif isinstance(model, dict):
            for filename in model:
                stem = os.path.splitext(filename)[0].casefold()
                if stem in target_basenames or filename.casefold() in target_basenames:
                    return selectable, arch
    return None


def download_entries_for_missing(
    missing_tags: Iterable[str],
    manager: typing.Any,
) -> Tuple[List[Tuple[str, str]], List[str]]:
    """Return ``(enqueue_entries, unresolved_tags)`` for missing preset members."""
    entries: List[Tuple[str, str]] = []
    unresolved: List[str] = []
    seen = set()
    for tag in missing_tags:
        found = find_download_selection(tag, manager)
        if found is None:
            unresolved.append(tag)
            continue
        selectable, arch = found
        key = (selectable, arch)
        if key in seen:
            continue
        seen.add(key)
        entries.append(key)
    return entries, unresolved
