"""Ensemble rows command operations."""

from __future__ import annotations

from typing import Any


def ensemble_rows() -> list[dict[str, Any]]:
    from core.ensemble_presets import (
        curated_combo_label,
        list_curated_ensembles,
        load_curated_ensemble,
    )
    from core.ensemble_service import list_saved_ensembles, load_ensemble

    rows = []
    for preset in list_curated_ensembles():
        rows.append(
            {
                "id": preset,
                "display": curated_combo_label(preset),
                "kind": "curated",
                "data": load_curated_ensemble(preset),
            }
        )
    for name in list_saved_ensembles():
        rows.append({"id": name, "display": name, "kind": "saved", "data": load_ensemble(name)})
    return rows
