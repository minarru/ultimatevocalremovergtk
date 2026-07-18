"""Slow-setting workload hint tests (no GTK imports)."""

import unittest

from bundled.constants import DEMUCS_ARCH_TYPE, MDX_ARCH_TYPE, VR_ARCH_TYPE
from core.run_estimate import RunCostTier, WorkloadEstimate, slow_setting_hints


class _Settings(dict):
    def get(self, key, default=None):
        return super().get(key, default)


class SlowSettingHintTests(unittest.TestCase):
    def test_mdx_overlap_and_match_freq(self) -> None:
        settings = _Settings(
            {
                "overlap_mdx23": "8",
                "is_match_frequency_pitch": True,
            }
        )
        hints = slow_setting_hints(settings, MDX_ARCH_TYPE)
        self.assertIn("overlap×8", hints)
        self.assertIn("match-freq", hints)

    def test_demucs_shifts(self) -> None:
        settings = _Settings({"shifts": 2})
        self.assertIn("shifts×2", slow_setting_hints(settings, DEMUCS_ARCH_TYPE))

    def test_vr_tta(self) -> None:
        settings = _Settings({"is_tta": True})
        self.assertIn("TTA", slow_setting_hints(settings, VR_ARCH_TYPE))

    def test_format_summary_includes_hints(self) -> None:
        estimate = WorkloadEstimate(
            inference_passes=1,
            output_count=1,
            uses_gpu=True,
            sample_mode=False,
            sample_seconds=30,
            export_tier=RunCostTier.FASTEST,
            hints=("TTA", "shifts×2"),
        )
        text = estimate.format_summary()
        self.assertIn("TTA", text)
        self.assertIn("shifts×2", text)


if __name__ == "__main__":
    unittest.main()
