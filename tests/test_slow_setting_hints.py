"""Cost-factor workload hint tests (no GTK imports)."""
import unittest

from bundled.constants import DEMUCS_ARCH_TYPE, ENSEMBLE_MODE, MDX_ARCH_TYPE, VR_ARCH_TYPE
from core.run_estimate import (
    RunCostTier,
    WorkloadEstimate,
    compose_stem_group_tooltip,
    cost_factor_hints,
    format_workload_tooltip_section,
)
from core.settings import Settings


def _settings(values: dict[str, object]) -> Settings:
    return Settings.from_flat(values)


class CostFactorHintTests(unittest.TestCase):
    def test_mdx_overlap_and_match_freq_with_pitch(self) -> None:
        settings = _settings(
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
        settings = _settings(
            {
                "is_match_frequency_pitch": True,
                "semitone_shift": "0",
            }
        )
        self.assertNotIn("Match frequency", cost_factor_hints(settings, MDX_ARCH_TYPE))

    def test_demucs_shifts(self) -> None:
        settings = _settings({"shifts": 2})
        self.assertIn("Shifts 2", cost_factor_hints(settings, DEMUCS_ARCH_TYPE))

    def test_vr_tta(self) -> None:
        settings = _settings({"is_tta": True})
        self.assertIn("TTA", cost_factor_hints(settings, VR_ARCH_TYPE))

    def test_skips_pass_duplicated_secondary(self) -> None:
        settings = _settings(
            {
                "mdx_is_secondary_model_activate": True,
                "overlap_mdx23": "0",
            }
        )
        self.assertEqual(cost_factor_hints(settings, MDX_ARCH_TYPE), ())

    def test_skips_pre_process_already_in_passes(self) -> None:
        settings = _settings(
            {"is_demucs_pre_proc_model_activate": True, "shifts": 1}
        )
        self.assertNotIn("Pre-process", cost_factor_hints(settings, DEMUCS_ARCH_TYPE))

    def test_ensemble_includes_global_cost_factors(self) -> None:
        settings = _settings(
            {
                "is_tta": True,
                "shifts": 2,
                "overlap_mdx23": "16",
                "denoise_option": "Standard",
            }
        )
        hints = cost_factor_hints(settings, ENSEMBLE_MODE)
        self.assertIn("TTA", hints)
        self.assertIn("Shifts 2", hints)
        self.assertIn("Overlap 16", hints)
        self.assertIn("Denoise", hints)

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
