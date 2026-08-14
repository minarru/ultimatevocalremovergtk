"""The ``list-models`` command: what is installed on this machine."""

from __future__ import annotations

import argparse
import json
from typing import Any

from bundled.constants import DEMUCS_ARCH_TYPE, MDX_ARCH_TYPE, VR_ARCH_TYPE
from core.ensemble_presets import curated_combo_label, list_curated_ensembles
from core.model_data import ModelRepository, list_saved_ensembles
from core.model_display import map_basenames_to_display

from .offline import catalogue_offline

# CLI method token -> (repository lister attribute, architecture key)
_FAMILIES: dict[str, tuple[str, str]] = {
    "vr": ("list_vr_models", VR_ARCH_TYPE),
    "mdx": ("list_mdx_models", MDX_ARCH_TYPE),
    "demucs": ("list_demucs_models", DEMUCS_ARCH_TYPE),
}


def add_list_models_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--method",
        choices=(*_FAMILIES, "ensemble"),
        default=None,
        help="Limit to one family (default: all three). 'ensemble' lists saved and curated presets.",
    )
    parser.add_argument(
        "--json", action="store_true", help="Emit a JSON array instead of a table"
    )
    parser.add_argument(
        "--online",
        action="store_true",
        help=(
            "Do not force catalogue fetches off. Does not clear "
            "UVR_DISABLE_POLITREES / UVR_DISABLE_MVSEPLESS if already set. "
            "Off by default: each source has a 30s timeout."
        ),
    )


def collect_rows(args: argparse.Namespace, repo: Any) -> list[dict[str, str]]:
    """Build ``{method, basename, display}`` rows for the requested families."""
    wanted = [args.method] if args.method in _FAMILIES else list(_FAMILIES)
    rows: list[dict[str, str]] = []
    for method in wanted:
        lister, arch = _FAMILIES[method]
        basenames = list(getattr(repo, lister)())
        displays = list(map_basenames_to_display(basenames, arch, repo))
        for basename, display in zip(basenames, displays):
            rows.append({"method": method, "basename": basename, "display": display})
    return rows


def collect_ensemble_rows() -> list[dict[str, str]]:
    """Build ``{method, basename, display, kind}`` rows for saved and curated presets."""
    rows: list[dict[str, str]] = []
    for preset_id in list_curated_ensembles():
        label = curated_combo_label(preset_id)
        rows.append({
            "method": "ensemble",
            "basename": preset_id,
            "display": label,
            "kind": "curated",
        })
    for name in list_saved_ensembles():
        rows.append({
            "method": "ensemble",
            "basename": name,
            "display": name,
            "kind": "saved",
        })
    return rows


def cmd_list_models(args: argparse.Namespace) -> int:
    if args.method == "ensemble":
        rows = collect_ensemble_rows()
        if args.json:
            print(json.dumps(rows, indent=2))
            return 0
        for row in rows:
            print(f"ensemble\t{row['kind']}\t{row['display']}")
        if not rows:
            print("(no saved or curated ensembles)")
        return 0

    repo = ModelRepository()
    with catalogue_offline(not args.online):
        rows = collect_rows(args, repo)

    if args.json:
        print(json.dumps(rows, indent=2))
        return 0

    for row in rows:
        if row["display"] and row["display"] != row["basename"]:
            print(f"{row['method']}\t{row['basename']}\t{row['display']}")
        else:
            print(f"{row['method']}\t{row['basename']}")
    if not rows:
        print("(no models installed)")
    return 0
