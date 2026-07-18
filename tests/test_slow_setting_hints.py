"""Cost-factor workload hint tests (no GTK imports)."""

import unittest

from bundled.constants import DEMUCS_ARCH_TYPE, MDX_ARCH_TYPE, VR_ARCH_TYPE
from core.run_estimate import (
    RunCostTier,
    WorkloadEstimate,
    compose_stem_group_tooltip,
    cost_factor_hints,
    format_workload_tooltip_section,
)


class _Settings(dict):
    def get(self, key, default=None):
        return super().get(key, default)


class CostFactorHintTests(unittest.TestCase):
    def test_mdx_overlap_and_match_freq_with_pitch(self) -> None:
        settings = _Settings(
            {
                "overlap_mdx23": "8",
                "is_match_frequency_pitch": True,
                "semitone_shift": "2",
            }
        )
        hints = cost_factor_hints(settings, MDX_ARCH_TYPE)
        self.assertIn("Overlap 8", hints)
        self.assertIn("Match frequency", hints)

    def test_match_freq_requires_pitch_change(self) -> None:
        settings = _Settings(
            {
                "is_match_frequency_pitch": True,
                "semitone_shift": "0",
            }
        )
        self.assertNotIn("Match frequency", cost_factor_hints(settings, MDX_ARCH_TYPE))

    def test_demucs_shifts(self) -> None:
        settings = _Settings({"shifts": 2})
        self.assertIn("Shifts 2", cost_factor_hints(settings, DEMUCS_ARCH_TYPE))

    def test_vr_tta(self) -> None:
        settings = _Settings({"is_tta": True})
        self.assertIn("TTA", cost_factor_hints(settings, VR_ARCH_TYPE))

    def test_skips_pass_duplicated_secondary(self) -> None:
        settings = _Settings({"mdx_is_secondary_model_activate": True})
        self.assertEqual(cost_factor_hints(settings, MDX_ARCH_TYPE), ())

    def test_format_summary_excludes_hints(self) -> None:
        estimate = WorkloadEstimate(
            inference_passes=1,
            output_count=1,
            uses_gpu=True,
            sample_mode=False,
            sample_seconds=30,
            export_tier=RunCostTier.FASTEST,
            hints=("TTA", "Shifts 2"),
        )
        text = estimate.format_summary()
        self.assertNotIn("TTA", text)
        self.assertNotIn("Shifts 2", text)
        self.assertEqual(estimate.format_cost_factors(), "TTA · Shifts 2")

    def test_tooltip_section_appends_cost_factors(self) -> None:
        estimate = WorkloadEstimate(
            inference_passes=1,
            output_count=1,
            uses_gpu=True,
            sample_mode=False,
            sample_seconds=30,
            export_tier=RunCostTier.FASTEST,
            hints=("Overlap 29",),
        )
        section = format_workload_tooltip_section(estimate, base_hint="Base workload")
        self.assertIn("Base workload", section)
        self.assertIn("Cost factors: Overlap 29", section)
        composed = compose_stem_group_tooltip(
            "Export help",
            estimate,
            workload_hint="Base workload",
        )
        self.assertIn("Export help", composed)
        self.assertIn("Cost factors: Overlap 29", composed)


if __name__ == "__main__":
    unittest.main()
