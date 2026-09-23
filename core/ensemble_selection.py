"""Exact reviewed-role selection for final ensemble outputs only."""

from typing import Protocol, Sequence, TypeVar

from .stem_roles import StemLiteral, StemRoleId


class RoleOutput(Protocol):
    @property
    def role(self) -> StemRoleId | StemLiteral: ...


OutputT = TypeVar("OutputT", bound=RoleOutput)


def select_ensemble_subset(
    outputs: Sequence[OutputT], selected: Sequence[str]
) -> tuple[tuple[OutputT, ...], tuple[str, ...]]:
    """Empty selection means All; never resolve identity from display labels."""
    if not selected:
        return tuple(outputs), ()
    available = {str(output.role) for output in outputs if isinstance(output.role, StemRoleId)}
    missing = tuple(token for token in selected if token not in available)
    return tuple(output for output in outputs if str(output.role) in selected), missing
