"""Applicability rules for the model-options sheet."""

from __future__ import annotations

from typing import Iterable, Optional, Sequence

from bundled.constants import (
    DEMUCS_ARCH_TYPE,
    ENSEMBLE_PARTITION,
    MDX_ARCH_TYPE,
    VR_ARCH_PM,
    VR_ARCH_TYPE,
)

OPEN_CONTEXT_SEPARATION = "separation"
OPEN_CONTEXT_ENSEMBLE = "ensemble"
OPEN_CONTEXT_AUDIO_TOOLS = "audio_tools"

_ARCH_TO_STACK = {
    VR_ARCH_PM: "vr",
    VR_ARCH_TYPE: "vr",
    MDX_ARCH_TYPE: "mdx",
    DEMUCS_ARCH_TYPE: "demucs",
}

_STACK_TITLES = {
    "vr": "VR Architecture",
    "mdx": "MDX-Net",
    "demucs": "Demucs",
}


def stack_name_for_method_key(method_key: str) -> Optional[str]:
    return _ARCH_TO_STACK.get(method_key)


def stack_name_for_member_tag(tag: str) -> Optional[str]:
    if not tag or ENSEMBLE_PARTITION not in tag:
        return None
    arch, _, _ = tag.partition(ENSEMBLE_PARTITION)
    return _ARCH_TO_STACK.get(arch)


def member_arch_counts(selected_models: Sequence[str]) -> dict[str, int]:
    counts = {"vr": 0, "mdx": 0, "demucs": 0}
    for tag in selected_models or []:
        stack = stack_name_for_member_tag(tag)
        if stack:
            counts[stack] += 1
    return counts


def applicable_stack_names(
    context: str,
    *,
    active_method_key: str,
    selected_models: Sequence[str],
) -> set[str]:
    if context == OPEN_CONTEXT_AUDIO_TOOLS:
        return set()
    if context == OPEN_CONTEXT_SEPARATION:
        stack = stack_name_for_method_key(active_method_key)
        return {stack} if stack else set()
    if context == OPEN_CONTEXT_ENSEMBLE:
        counts = member_arch_counts(selected_models)
        return {stack for stack, count in counts.items() if count > 0}
    return set()


def default_stack_name(
    context: str,
    *,
    active_method_key: str,
    selected_models: Sequence[str],
    views_by_stack: dict,
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


def applicability_subtitle(
    context: str,
    stack_name: str,
    *,
    active_method_key: str,
    selected_models: Sequence[str],
) -> str:
    applicable = applicable_stack_names(
        context,
        active_method_key=active_method_key,
        selected_models=selected_models,
    )
    title = _STACK_TITLES.get(stack_name, stack_name)

    if context == OPEN_CONTEXT_AUDIO_TOOLS:
        return "Only applies to Separation and Ensemble runs"

    if context == OPEN_CONTEXT_SEPARATION:
        if stack_name in applicable:
            return f"Applies to the active {title} separation run"
        return f"Not used — active method is not {title}"

    if context == OPEN_CONTEXT_ENSEMBLE:
        counts = member_arch_counts(selected_models)
        count = counts.get(stack_name, 0)
        total = sum(counts.values())
        if count == 0:
            return "Not used — no ensemble members use this architecture"
        if count == 1 and total == 1:
            return "Applies to the ensemble member model"
        return f"Applies to {count} of {total} ensemble member models"

    return ""


def non_applicable_toast(
    context: str,
    stack_name: str,
    *,
    active_method_key: str,
    selected_models: Sequence[str],
) -> Optional[str]:
    applicable = applicable_stack_names(
        context,
        active_method_key=active_method_key,
        selected_models=selected_models,
    )
    if stack_name in applicable:
        return None
    title = _STACK_TITLES.get(stack_name, stack_name)
    if context == OPEN_CONTEXT_SEPARATION:
        return f"{title} options are not used by the active separation method."
    if context == OPEN_CONTEXT_ENSEMBLE:
        return f"{title} options are not used by any selected ensemble member."
    return f"{title} options do not apply in this context."


def ensemble_context_banner(context: str) -> Optional[str]:
    if context != OPEN_CONTEXT_ENSEMBLE:
        return None
    return (
        "These settings apply to each member model by architecture. "
        "They do not change which models are selected or how results are combined."
    )
