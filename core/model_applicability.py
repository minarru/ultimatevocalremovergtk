"""Architecture applicability rules independent of frontend presentation."""

from __future__ import annotations

from collections.abc import Sequence

from bundled.constants import DEMUCS_ARCH_TYPE, MDX_ARCH_TYPE, VR_ARCH_PM, VR_ARCH_TYPE

from .model_identity import FAMILY_BY_ARCH, ModelId

ARCH_TO_STACK = {
    VR_ARCH_PM: "vr", VR_ARCH_TYPE: "vr", MDX_ARCH_TYPE: "mdx",
    DEMUCS_ARCH_TYPE: "demucs",
}


def stack_name_for_method_key(method_key: str) -> str | None:
    return ARCH_TO_STACK.get(method_key)


def stack_name_for_model_reference(reference: str) -> str | None:
    raw = str(reference or "")
    prefix, separator, _name = raw.partition(":")
    if separator and prefix.casefold() in {"vr", "mdx", "demucs"}:
        return prefix.casefold()
    arch, separator, _name = raw.partition(": ")
    return ARCH_TO_STACK.get(arch) if separator else None


def member_arch_counts(selected_models: Sequence[str]) -> dict[str, int]:
    counts = {"vr": 0, "mdx": 0, "demucs": 0}
    for reference in selected_models or []:
        stack = stack_name_for_model_reference(reference)
        if stack:
            counts[stack] += 1
    return counts


def applicable_stack_names(
    context: str, *, active_method_key: str, selected_models: Sequence[str]
) -> set[str]:
    if context == "audio_tools":
        return set()
    if context == "separation":
        stack = stack_name_for_method_key(active_method_key)
        return {stack} if stack else set()
    if context == "ensemble":
        return {name for name, count in member_arch_counts(selected_models).items() if count}
    return set()

