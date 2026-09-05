"""Pure installed-member projection; acquisition and reconciliation belong to the page."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Collection, Sequence

from core.model_identity import ModelRecord, parse_stored_model_id


@dataclass(frozen=True)
class MemberProjection:
    records: tuple[ModelRecord, ...]
    selected_ids: tuple[str, ...]
    warnings: tuple[str, ...]
    gated_ids: tuple[str, ...]
    write_gated: bool
    replace_gate: bool
    placeholder: str
    reconcile_after_render: bool


def project_members(
    records: Sequence[ModelRecord],
    preselected: Sequence[Any],
    *,
    pair_id: str,
    eligible_ids: Collection[str] | None,
    prior_gated_ids: Collection[str] = (),
    load_error: bool = False,
    pair_chosen: bool | None = None,
) -> MemberProjection:
    chosen = bool(pair_id) if pair_chosen is None else pair_chosen
    installed_ids = {record.id for record in records if record.installed}
    check_eligibility = chosen and not load_error
    warnings: list[str] = []
    gated: set[str] = set()
    for index, value in enumerate(preselected):
        path = f'ensemble.selected_models[{index}]'
        warning = None
        try:
            model_id = parse_stored_model_id(value).value if isinstance(value, str) else None
        except ValueError:
            model_id = None
        if model_id is None:
            warning = f'{path}: expected a canonical model ID; excluding {value!r}'
        elif model_id not in installed_ids:
            warning = f'{path}: model {value!r} is not installed; excluding it'
        elif check_eligibility and eligible_ids is not None and model_id not in eligible_ids:
            warning = f'{path}: model {value!r} is not eligible for {pair_id!r}; excluding it'
        if warning:
            warnings.append(warning)
            if isinstance(value, str):
                gated.add(value)
    if not chosen or load_error:
        return MemberProjection(
            (),
            (),
            tuple(warnings),
            (),
            bool(warnings),
            False,
            'Could not list models' if chosen else 'Choose a stem pair to list models',
            False,
        )
    newly_available = sorted(set(prior_gated_ids) - gated)
    warnings.extend(
        f'ensemble member {value!r} is now available; pick it to select it'
        for value in newly_available
    )
    gated.update(prior_gated_ids)
    ordered = tuple(
        sorted(
            (
                record
                for record in records
                if record.installed and eligible_ids is not None and record.id in eligible_ids
            ),
            key=lambda record: (record.display.casefold(), record.id),
        )
    )
    selected = {value for value in preselected if isinstance(value, str)}
    return MemberProjection(
        ordered,
        tuple(record.id for record in ordered if record.id in selected and record.id not in gated),
        tuple(warnings),
        tuple(sorted(gated)),
        bool(warnings or gated),
        True,
        '' if ordered else 'No compatible models found',
        bool(ordered),
    )
