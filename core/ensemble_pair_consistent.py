from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from core.stem_roles import StemRoleId
from core.stems import StemRoute, StemRouteKind


@dataclass(frozen=True, slots=True)
class PairConsistentPlan:
    stacked_role: StemRoleId
    leftover_role: StemRoleId


def is_native_pair_output(route: StemRoute) -> bool:
    return (
        isinstance(route.role, StemRoleId)
        and route.kind is StemRouteKind.NATIVE
        and route.complement_of is None
    )


def resolve_pair_consistent_plan(
    pair_roles: tuple[StemRoleId, StemRoleId],
    member_routes: Sequence[Sequence[StemRoute]],
) -> PairConsistentPlan | None:
    role_a, role_b = pair_roles
    native_a = 0
    native_b = 0
    for routes in member_routes:
        saw_a = False
        saw_b = False
        for route in routes:
            if not is_native_pair_output(route):
                continue
            if route.role == role_a:
                saw_a = True
            elif route.role == role_b:
                saw_b = True
        native_a += int(saw_a)
        native_b += int(saw_b)
    if native_a >= 2 and native_b == 0:
        return PairConsistentPlan(role_a, role_b)
    if native_b >= 2 and native_a == 0:
        return PairConsistentPlan(role_b, role_a)
    return None
