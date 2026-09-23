"""Formatting command operations."""

from __future__ import annotations

import argparse
import json
from enum import Enum
from typing import Any, Mapping

from ..reporting import emit_document, report_mode


def _print_rows(args: argparse.Namespace, rows: list[dict[str, Any]]) -> int:
    if report_mode(args) == "human":
        for row in rows:
            print("\t".join(_human_cell(value, key=key, row=row) for key, value in row.items()))
    else:
        emit_document(args, {"ok": True, "status": "success", "items": rows})
    return 0


def _print_detail(args: argparse.Namespace, row: dict[str, Any]) -> int:
    """Render one inspection object with stable field labels in human mode."""
    if report_mode(args) != "human":
        return _print_rows(args, [row])
    for label, value in row.items():
        print(f"{label}\t{_human_cell(value, key=label, row=row)}")
    return 0


def _projected_stem_label(row: Mapping[str, Any] | None, key: str) -> str | None:
    """Read a human stem label from the exact semantic route projection."""
    if row is None:
        return None
    routes = row.get("stem_routes")
    if not isinstance(routes, (list, tuple)):
        return None
    if key in {"primary_stem", "secondary_stem"}:
        role_field = "logical_primary_role" if key == "primary_stem" else "logical_secondary_role"
        marker_field = "logical_primary" if key == "primary_stem" else "logical_secondary"
        role = row.get(role_field)
        for route in routes:
            if not isinstance(route, Mapping):
                continue
            if (role is not None and route.get("role") == role) or (
                role is None and route.get(marker_field)
            ):
                display = route.get("display")
                if isinstance(display, str) and display:
                    return display
        if role is not None:
            return None
    native = row.get(key)
    for route in routes:
        if not isinstance(route, Mapping) or route.get("native") != native:
            continue
        display = route.get("display")
        if isinstance(display, str) and display:
            return display
    return None


def _human_cell(value: Any, *, key: str | None = None, row: Mapping[str, Any] | None = None) -> str:
    if key == "catalogue_evidence_warning":
        return ""
    if key == "catalogue_evidence_status":
        warning = "" if row is None else str(row.get("catalogue_evidence_warning") or "")
        if "mismatch" in warning:
            return "evidence: mismatch"
        labels = {
            "pending": "evidence: pending",
            "unavailable": "evidence: unavailable",
            "stale": "evidence: stale",
        }
        return labels.get(str(value), "")
    if key in {"primary_stem", "secondary_stem"}:
        projected = _projected_stem_label(row, key)
        if projected is not None:
            return projected
    value = _jsonable(value)
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(value, sort_keys=True, separators=(",", ":"))
    if value is None:
        return ""
    return str(value)


def _jsonable(value: Any) -> Any:
    return value.value if isinstance(value, Enum) else value
