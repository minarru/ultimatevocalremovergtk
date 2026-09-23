"""Auto-register Apollo checkpoints downloaded alongside their config yaml.

:class:`core.apollo.ApolloModelData` recognises a checkpoint by looking up
``APOLLO_HASH_DIR/<md5>.json`` for a ``{"config_yaml": "<name>.yaml"}`` mapping.
Without that file a freshly downloaded model falls through to the
``on_unrecognized`` prompt, which would make every Download Center install ask
the user to pick a config it already knows.

This is the Apollo counterpart of
:func:`core.mdx_c_registry.register_mdx_c_from_download_jobs`.
"""

from __future__ import annotations

import json
import os
from typing import List, Tuple

from . import paths
from .apollo import checkpoint_md5
from .debug_log import debug

APOLLO_CHECKPOINT_EXTENSIONS = (".ckpt", ".bin")


def _is_apollo_checkpoint(path: str) -> bool:
    return path.lower().endswith(APOLLO_CHECKPOINT_EXTENSIONS)


def pair_apollo_jobs(jobs: List[Tuple[str, str]]) -> List[Tuple[str, str]]:
    """Return ``[(checkpoint_path, yaml_basename), ...]`` from a download batch."""
    yaml_names = [
        os.path.basename(save_path)
        for _url, save_path in jobs
        if save_path.startswith(paths.APOLLO_CONFIG_PATH) and save_path.endswith(".yaml")
    ]
    if not yaml_names:
        return []

    yaml_name = yaml_names[0]
    pairs: List[Tuple[str, str]] = []
    for _url, save_path in jobs:
        if not save_path.startswith(paths.APOLLO_MODELS_DIR):
            continue
        # Config yamls live under APOLLO_CONFIG_PATH, itself inside
        # APOLLO_MODELS_DIR — skip them so only checkpoints are paired.
        if save_path.startswith(paths.APOLLO_CONFIG_PATH):
            continue
        if not _is_apollo_checkpoint(save_path):
            continue
        if os.path.isfile(save_path):
            pairs.append((save_path, yaml_name))
    return pairs


def register_apollo_checkpoint(checkpoint_path: str, yaml_name: str) -> bool:
    """Persist ``<md5>.json`` for one checkpoint. Returns ``True`` when written."""
    if not os.path.isfile(checkpoint_path) or not yaml_name:
        return False

    try:
        model_hash = checkpoint_md5(checkpoint_path)
    except OSError as exc:
        debug("download", f"apollo hash failed err={type(exc).__name__}: {exc}")
        return False

    dump_path = os.path.join(paths.APOLLO_HASH_DIR, f"{model_hash}.json")
    if os.path.isfile(dump_path):
        return False

    try:
        os.makedirs(paths.APOLLO_HASH_DIR, exist_ok=True)
        with open(dump_path, "w", encoding="utf-8") as handle:
            json.dump({"config_yaml": yaml_name}, handle, indent=4)
    except OSError as exc:
        debug("download", f"apollo register failed err={type(exc).__name__}: {exc}")
        return False

    debug(
        "download",
        f"apollo registered {os.path.basename(checkpoint_path)} -> {yaml_name}",
    )
    return True


def register_apollo_from_download_jobs(jobs: List[Tuple[str, str]]) -> bool:
    """Register every Apollo checkpoint downloaded with a config yaml."""
    registered = False
    for checkpoint_path, yaml_name in pair_apollo_jobs(jobs):
        if register_apollo_checkpoint(checkpoint_path, yaml_name):
            registered = True
    return registered
