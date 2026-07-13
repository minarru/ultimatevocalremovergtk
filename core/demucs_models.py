"""Demucs v3/v4 model discovery helpers."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Iterable, Set

import yaml

from core import paths


def demucs_yaml_bag_member_sigs(directory: str) -> Set[str]:
    """Return XP sig prefixes referenced by yaml bag files in ``directory``."""
    sigs: Set[str] = set()
    if not os.path.isdir(directory):
        return sigs
    for entry in os.listdir(directory):
        if not entry.lower().endswith(".yaml"):
            continue
        bag_path = os.path.join(directory, entry)
        try:
            with open(bag_path, encoding="utf-8") as handle:
                bag = yaml.safe_load(handle)
        except (OSError, yaml.YAMLError):
            continue
        if not isinstance(bag, dict):
            continue
        for sig in bag.get("models") or []:
            if sig:
                sigs.add(str(sig))
    return sigs


def is_demucs_bag_member_weight(stem: str, bag_sigs: Iterable[str]) -> bool:
    """True when ``stem`` names a ``sig-checksum.th`` file owned by a yaml bag."""
    if "-" not in stem:
        return False
    sig = stem.split("-", 1)[0]
    return sig in set(bag_sigs)


def demucs_pretrained_load_name(model_path: str | os.PathLike) -> str:
    """Resolve the ``name`` argument for ``vendor.demucs.pretrained.get_model``."""
    path = Path(model_path)
    stem = path.stem
    if path.suffix.lower() == ".yaml":
        return stem
    if "-" in stem:
        sig = stem.split("-", 1)[0]
        from vendor.demucs.repo import LocalRepo

        repo = LocalRepo(path.parent)
        if repo.has_model(sig):
            return sig
    return stem


def resolve_demucs_model_file(model_name: str, demucs_version: str) -> str:
    """Return an on-disk Demucs model file path for ``model_name``."""
    from bundled.constants import DEMUCS_V3, DEMUCS_V4

    demucs_newer = demucs_version in {DEMUCS_V3, DEMUCS_V4}
    primary_dir = paths.DEMUCS_NEWER_REPO_DIR if demucs_newer else paths.DEMUCS_MODELS_DIR
    search_dirs = [primary_dir]
    if primary_dir != paths.DEMUCS_MODELS_DIR:
        search_dirs.append(paths.DEMUCS_MODELS_DIR)

    for directory in search_dirs:
        for ext in (".yaml", ".th", ".ckpt", ".gz"):
            candidate = os.path.join(directory, f"{model_name}{ext}")
            if os.path.isfile(candidate):
                return candidate
    return os.path.join(paths.DEMUCS_NEWER_REPO_DIR, f"{model_name}.yaml")
