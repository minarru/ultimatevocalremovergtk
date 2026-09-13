"""On-demand blend editor; applies a reviewed snapshot without intermediate writes."""

from __future__ import annotations

import copy
from collections.abc import Callable, Sequence
from typing import Any

from gi.repository import Adw, Gtk

from core.ensemble_blend import restore_blend_options, saved_blend_options
from core.settings import Settings
from core.stem_roles import StemRoleId
from ui.template import load_builder, object_from_builder


def show_blend_dialog(
    parent: Gtk.Widget,
    settings: Settings,
    members: Sequence[tuple[str, str, Sequence[Any]]],
    on_apply: Callable[[dict[str, Any]], None],
) -> Adw.Dialog:
    builder = load_builder("ensemble-blend")
    dialog = object_from_builder(builder, "dialog", Adw.Dialog)
    snapshot = copy.deepcopy(saved_blend_options(settings))
    rows = {
        "smoothing": object_from_builder(builder, "smoothing_row", Adw.SpinRow),
        "soft_strength": object_from_builder(builder, "soft_row", Adw.SpinRow),
        "hybrid_balance": object_from_builder(builder, "hybrid_row", Adw.SpinRow),
    }
    for field, row in rows.items():
        row.set_value(snapshot[field])
    alignment = object_from_builder(builder, "alignment_row", Adw.SwitchRow)
    alignment.set_active(snapshot["alignment_correction"])
    group = object_from_builder(builder, "weights_group", Adw.PreferencesGroup)
    weight_rows: list[tuple[str, str, Adw.SpinRow]] = []
    expanders: dict[str, Adw.ExpanderRow] = {}
    for model_id, label, routes in members:
        seen: set[str] = set()
        for route in routes:
            if not isinstance(route.role, StemRoleId):
                continue
            role = str(route.role)
            if role in seen:
                continue
            seen.add(role)
            if role not in expanders:
                expander = Adw.ExpanderRow(title=route.label)
                expanders[role] = expander
                group.add(expander)
            value = (
                snapshot["member_weights"]
                .get(role, {})
                .get(model_id, snapshot["member_weights"].get("*", {}).get(model_id, 1.0))
            )
            row = Adw.SpinRow(
                title=label,
                adjustment=Gtk.Adjustment(lower=0, upper=100, step_increment=0.05, value=value),
                digits=2,
            )
            expanders[role].add_row(row)
            weight_rows.append((role, model_id, row))
    if not weight_rows:
        group.set_description("Choose member models to edit their output weights.")

    def apply(_button: Gtk.Button) -> None:
        for field, row in rows.items():
            snapshot[field] = row.get_value()
        snapshot["alignment_correction"] = alignment.get_active()
        for role, model_id, row in weight_rows:
            snapshot["member_weights"].setdefault(role, {})[model_id] = row.get_value()
        on_apply(restore_blend_options(snapshot))
        dialog.close()

    object_from_builder(builder, "apply_button", Gtk.Button).connect("clicked", apply)
    dialog.present(parent)
    return dialog
