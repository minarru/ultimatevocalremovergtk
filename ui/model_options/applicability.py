"""Applicability rules for the model-options sheet."""

from __future__ import annotations

from typing import Any, Iterable, Mapping, Optional, Sequence

from bundled.constants import (
    DEMUCS_ARCH_TYPE,
    ENSEMBLE_PARTITION,
    MDX_ARCH_TYPE,
    VR_ARCH_PM,
    VR_ARCH_TYPE,
)
from core.model_applicability import (
    applicable_stack_names,
    member_arch_counts,
    stack_name_for_method_key,
    stack_name_for_model_reference,
)

OPEN_CONTEXT_SEPARATION = "separation"
OPEN_CONTEXT_ENSEMBLE = "ensemble"
OPEN_CONTEXT_AUDIO_TOOLS = "audio_tools"

_STACK_TITLES = {
    "vr": "VR Architecture",
    "mdx": "MDX-Net",
    "demucs": "Demucs",
}


def stack_name_for_member_tag(tag: str) -> Optional[str]:
    return stack_name_for_model_reference(tag)


def should_hide_unused_stacks(context: str, applicable: Iterable[str]) -> bool:
    """Whether non-applicable architecture tabs should be removed from the switcher.

    Separation keeps every tab visible (the inapplicable ones carry an
    ``Adw.Banner`` explaining they are unused instead). Ensemble hides arches
    unused by members.
    """
    return context == OPEN_CONTEXT_ENSEMBLE and bool(applicable)


def default_stack_name(
    context: str,
    *,
    active_method_key: str,
    selected_models: Sequence[str],
    views_by_stack: Mapping[str, Any],
) -> str:
    applicable = applicable_stack_names(
        context,
        active_method_key=active_method_key,
        selected_models=selected_models,
    )
    if context == OPEN_CONTEXT_SEPARATION:
        stack = stack_name_for_method_key(active_method_key)
        if stack and stack in views_by_stack:
            return stack
    if applicable:
        for stack in ("vr", "mdx", "demucs"):
            if stack in applicable and stack in views_by_stack:
                return stack
    return next(iter(views_by_stack))


def applicability_banner(
    context: str,
    stack_name: str,
    *,
    active_method_key: str,
    selected_models: Sequence[str],
) -> Optional[tuple[str, Optional[str]]]:
    """The banner for one architecture tab, or ``None`` when it needs none.

    Returns ``(text, button_label)``. ``button_label`` is ``None`` for a banner
    with no action. An applicable tab returns ``None`` outright -- absence of a
    banner is what "this tab applies" looks like, so the common case is silent.
    """
    applicable = applicable_stack_names(
        context,
        active_method_key=active_method_key,
        selected_models=selected_models,
    )
    title = _STACK_TITLES.get(stack_name, stack_name)

    if context == OPEN_CONTEXT_AUDIO_TOOLS:
        return ("These options only apply to Separation and Ensemble runs.", None)

    if context == OPEN_CONTEXT_SEPARATION:
        if stack_name in applicable:
            return None
        active_title = _STACK_TITLES.get(
            stack_name_for_method_key(active_method_key) or "", "another architecture"
        )
        return (
            f"Not used by this run — the active method is {active_title}.",
            f"Switch to {title}",
        )

    if context == OPEN_CONTEXT_ENSEMBLE:
        if not applicable:
            return (
                "Select ensemble member models before editing "
                "architecture-specific options.",
                None,
            )
        if stack_name in applicable:
            return None
        return ("Not used — no ensemble members use this architecture.", None)

    return None


def ensemble_context_banner(context: str) -> Optional[str]:
    if context != OPEN_CONTEXT_ENSEMBLE:
        return None
    return (
        "These settings apply to each member model by architecture. "
        "They do not change which models are selected or how results are combined."
    )
