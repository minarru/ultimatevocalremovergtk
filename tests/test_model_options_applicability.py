"""Tests for model-options sheet applicability rules."""

import unittest

from bundled.constants import DEMUCS_ARCH_TYPE, ENSEMBLE_PARTITION, MDX_ARCH_TYPE, VR_ARCH_PM, VR_ARCH_TYPE

from ui.model_options.applicability import (
    OPEN_CONTEXT_AUDIO_TOOLS,
    OPEN_CONTEXT_ENSEMBLE,
    OPEN_CONTEXT_SEPARATION,
    applicable_stack_names,
    applicability_banner,
    default_stack_name,
    member_arch_counts,
    should_hide_unused_stacks,
    stack_name_for_member_tag,
    stack_name_for_method_key,
)


class ModelOptionsApplicabilityTests(unittest.TestCase):
    def test_stack_name_for_method_key_vr_aliases(self) -> None:
        self.assertEqual(stack_name_for_method_key(VR_ARCH_PM), "vr")
        self.assertEqual(stack_name_for_method_key(VR_ARCH_TYPE), "vr")

    def test_stack_name_for_member_tag(self) -> None:
        tag = f"{MDX_ARCH_TYPE}{ENSEMBLE_PARTITION}My Model"
        self.assertEqual(stack_name_for_member_tag(tag), "mdx")

    def test_separation_applicable_only_active_method(self) -> None:
        applicable = applicable_stack_names(
            OPEN_CONTEXT_SEPARATION,
            active_method_key=MDX_ARCH_TYPE,
            selected_models=[],
        )
        self.assertEqual(applicable, {"mdx"})
        # Separation must not remove other architecture tabs from the switcher.
        self.assertFalse(should_hide_unused_stacks(OPEN_CONTEXT_SEPARATION, applicable))

    def test_ensemble_hides_unused_when_members_selected(self) -> None:
        applicable = {"mdx"}
        self.assertTrue(should_hide_unused_stacks(OPEN_CONTEXT_ENSEMBLE, applicable))
        self.assertFalse(should_hide_unused_stacks(OPEN_CONTEXT_ENSEMBLE, set()))

    def test_ensemble_applicable_from_members(self) -> None:
        selected = [
            f"{VR_ARCH_TYPE}{ENSEMBLE_PARTITION}A",
            f"{MDX_ARCH_TYPE}{ENSEMBLE_PARTITION}B",
            f"{MDX_ARCH_TYPE}{ENSEMBLE_PARTITION}C",
        ]
        applicable = applicable_stack_names(
            OPEN_CONTEXT_ENSEMBLE,
            active_method_key=VR_ARCH_PM,
            selected_models=selected,
        )
        self.assertEqual(applicable, {"vr", "mdx"})
        self.assertEqual(member_arch_counts(selected), {"vr": 1, "mdx": 2, "demucs": 0})

    def test_audio_tools_never_applicable(self) -> None:
        applicable = applicable_stack_names(
            OPEN_CONTEXT_AUDIO_TOOLS,
            active_method_key=MDX_ARCH_TYPE,
            selected_models=[f"{MDX_ARCH_TYPE}{ENSEMBLE_PARTITION}X"],
        )
        self.assertEqual(applicable, set())

    def test_default_stack_prefers_active_separation_method(self) -> None:
        views_by_stack = {"vr": object(), "mdx": object(), "demucs": object()}
        stack = default_stack_name(
            OPEN_CONTEXT_SEPARATION,
            active_method_key=DEMUCS_ARCH_TYPE,
            selected_models=[],
            views_by_stack=views_by_stack,
        )
        self.assertEqual(stack, "demucs")


class ApplicabilityBannerTests(unittest.TestCase):
    def test_applicable_separation_tab_gets_no_banner(self):
        self.assertIsNone(
            applicability_banner(
                OPEN_CONTEXT_SEPARATION,
                "mdx",
                active_method_key=MDX_ARCH_TYPE,
                selected_models=[],
            )
        )

    def test_inactive_separation_tab_names_the_active_method(self):
        result = applicability_banner(
            OPEN_CONTEXT_SEPARATION,
            "vr",
            active_method_key=MDX_ARCH_TYPE,
            selected_models=[],
        )
        self.assertIsNotNone(result)
        assert result is not None
        text, button = result
        self.assertIn("MDX-Net", text)
        assert button is not None
        self.assertIn("VR Architecture", button)

    def test_unused_ensemble_tab_says_no_member_uses_it(self):
        result = applicability_banner(
            OPEN_CONTEXT_ENSEMBLE,
            "demucs",
            active_method_key="",
            selected_models=[f"{MDX_ARCH_TYPE}{ENSEMBLE_PARTITION}Some Model"],
        )
        self.assertIsNotNone(result)
        assert result is not None
        text, button = result
        self.assertIn("no ensemble members", text.lower())
        self.assertIsNone(button)

    def test_used_ensemble_tab_gets_no_banner(self):
        self.assertIsNone(
            applicability_banner(
                OPEN_CONTEXT_ENSEMBLE,
                "mdx",
                active_method_key="",
                selected_models=[f"{MDX_ARCH_TYPE}{ENSEMBLE_PARTITION}Some Model"],
            )
        )

    def test_empty_ensemble_prompts_for_members_on_every_tab(self):
        for stack_name in ("vr", "mdx", "demucs"):
            result = applicability_banner(
                OPEN_CONTEXT_ENSEMBLE,
                stack_name,
                active_method_key="",
                selected_models=[],
            )
            self.assertIsNotNone(result, stack_name)
            assert result is not None
            text, button = result
            self.assertIn("Select ensemble member models", text)
            self.assertIsNone(button)

    def test_audio_tools_context_is_never_applicable(self):
        result = applicability_banner(
            OPEN_CONTEXT_AUDIO_TOOLS,
            "mdx",
            active_method_key=MDX_ARCH_TYPE,
            selected_models=[],
        )
        self.assertIsNotNone(result)


if __name__ == "__main__":
    unittest.main()
