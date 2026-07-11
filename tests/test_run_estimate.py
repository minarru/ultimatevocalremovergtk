import unittest
from types import SimpleNamespace

from bundled.constants import (
    ALL_STEMS,
    BASS_STEM,
    DRUM_STEM,
    DEMUCS_ARCH_TYPE,
    ENSEMBLE_MODE,
    MDX_ARCH_TYPE,
    VOCAL_STEM,
)
from core.run_estimate import (
    ProgressEtaTracker,
    RunCostTier,
    WorkloadEstimate,
    classify_export_tier,
    classify_run_tier,
    count_inference_passes,
    count_inference_passes_from_models,
    estimate_workload,
    format_workload_line,
)
from ui.widgets.stem_only import (
    SaveStemsSection,
    _QUICK_ALL,
    _QUICK_INSTRUMENTAL,
    _QUICK_VOCALS,
)


class _Settings(dict):
    def get(self, key, default=None):
        return super().get(key, default)

    def set(self, key, value):
        self[key] = value


class TierClassificationTests(unittest.TestCase):
    def test_export_tiers(self):
        self.assertEqual(classify_export_tier(1), RunCostTier.FASTEST)
        self.assertEqual(classify_export_tier(2), RunCostTier.TYPICAL)
        self.assertEqual(classify_export_tier(4), RunCostTier.SLOWER)

    def test_run_tiers(self):
        self.assertIsNone(classify_run_tier(1))
        self.assertEqual(classify_run_tier(2), RunCostTier.TYPICAL)
        self.assertEqual(classify_run_tier(3), RunCostTier.SLOWER)


class WorkloadEstimateTests(unittest.TestCase):
    def test_format_summary_single_pass(self):
        estimate = WorkloadEstimate(
            inference_passes=1,
            output_count=2,
            uses_gpu=True,
            sample_mode=False,
            sample_seconds=30,
            export_tier=RunCostTier.TYPICAL,
        )
        self.assertEqual(estimate.format_summary(), "1 pass · 2 outputs · GPU · Typical")

    def test_format_summary_mixed_tiers(self):
        estimate = WorkloadEstimate(
            inference_passes=2,
            output_count=1,
            uses_gpu=True,
            sample_mode=True,
            sample_seconds=30,
            export_tier=RunCostTier.FASTEST,
            run_tier=RunCostTier.TYPICAL,
        )
        self.assertEqual(
            estimate.format_summary(),
            "2 passes · 1 output · GPU · Sample 30s · Fastest export · Typical run",
        )


class InferencePassTests(unittest.TestCase):
    def test_count_from_models_secondary(self):
        model = SimpleNamespace(
            process_method=MDX_ARCH_TYPE,
            is_secondary_model_activated=True,
            demucs_4_stem_added_count=0,
            pre_proc_model_activated=False,
            is_vocal_split_model_activated=False,
        )
        self.assertEqual(count_inference_passes_from_models([model]), 2)

    def test_count_light_mdx_secondary(self):
        settings = _Settings({"mdx_is_secondary_model_activate": True})
        self.assertEqual(count_inference_passes(settings, method_key=MDX_ARCH_TYPE), 2)

    def test_count_ensemble_members(self):
        settings = _Settings({"selected_models": ["a", "b", "c"]})
        self.assertEqual(count_inference_passes(settings, method_key=ENSEMBLE_MODE), 3)


class SaveStemsOutputCountTests(unittest.TestCase):
    def setUp(self):
        self.settings = _Settings(
            {
                "is_primary_stem_only": False,
                "is_secondary_stem_only": False,
                "mdx_stems_selected": [],
                "mdx_stems": ALL_STEMS,
                "demucs_stems": ALL_STEMS,
                "is_primary_stem_only_Demucs": False,
                "is_secondary_stem_only_Demucs": False,
            }
        )
        self.section = SaveStemsSection(settings=self.settings)

    def test_exclusive_all_outputs(self):
        self.section.configure_exclusive(
            primary_stem=VOCAL_STEM,
            secondary_stem="Instrumental",
            primary_key="is_primary_stem_only",
            secondary_key="is_secondary_stem_only",
            has_model=True,
        )
        self.assertEqual(self.section.expected_output_count(), 2)

    def test_exclusive_single_output(self):
        self.section.configure_exclusive(
            primary_stem=VOCAL_STEM,
            secondary_stem="Instrumental",
            primary_key="is_primary_stem_only",
            secondary_key="is_secondary_stem_only",
            has_model=True,
        )
        self.settings["is_primary_stem_only"] = True
        self.section.sync_from_settings()
        self.assertEqual(self.section.expected_output_count(), 1)

    def test_subset_quick_vocals(self):
        self.section.configure_subset(
            stems=[VOCAL_STEM, BASS_STEM, DRUM_STEM],
            has_vocals=True,
            primary_key="is_primary_stem_only",
            secondary_key="is_secondary_stem_only",
            has_model=True,
        )
        self.section._subset_mode = _QUICK_VOCALS
        self.assertEqual(self.section.expected_output_count(), 1)

    def test_subset_all_stems(self):
        self.section.configure_subset(
            stems=[VOCAL_STEM, BASS_STEM],
            has_vocals=True,
            primary_key="is_primary_stem_only",
            secondary_key="is_secondary_stem_only",
            has_model=True,
        )
        self.section._subset_mode = _QUICK_ALL
        self.assertEqual(self.section.expected_output_count(), 2)

    def test_demucs_all_stems(self):
        self.section.configure_demucs(
            focus_stems=[ALL_STEMS, BASS_STEM],
            primary_key="is_primary_stem_only_Demucs",
            secondary_key="is_secondary_stem_only_Demucs",
            has_model=True,
            demucs_stem_count=6,
        )
        self.section._demucs_focus.set_active_name(_QUICK_ALL)
        self.assertEqual(self.section.expected_output_count(), 6)


class EstimateWorkloadIntegrationTests(unittest.TestCase):
    def test_estimate_returns_none_without_model(self):
        section = SaveStemsSection(settings=_Settings({}))
        section.configure_hidden(has_model=False)
        self.assertIsNone(
            estimate_workload(
                _Settings({}),
                method_key=MDX_ARCH_TYPE,
                save_stems=section,
                has_model=False,
            )
        )

    def test_format_workload_line(self):
        estimate = WorkloadEstimate(
            inference_passes=1,
            output_count=1,
            uses_gpu=False,
            sample_mode=False,
            sample_seconds=30,
            export_tier=RunCostTier.FASTEST,
        )
        self.assertEqual(format_workload_line(estimate), "1 pass · 1 output · CPU · Fastest")


class ProgressEtaTrackerTests(unittest.TestCase):
    def test_load_phase_no_remaining(self):
        tracker = ProgressEtaTracker()
        text = tracker.format_text(0.05, 30.0, now=30.0)
        self.assertIn("Loading model", text)
        self.assertNotIn("left", text)

    def test_early_inference_calculating(self):
        tracker = ProgressEtaTracker()
        tracker.update(0.12, 40.0)
        text = tracker.format_text(0.12, 40.0, now=40.0)
        self.assertIn("Calculating estimate", text)

    def test_mdx_climb_does_not_show_one_minute_early(self):
        tracker = ProgressEtaTracker()
        t0 = 1000.0
        # Fast early progress (load + first chunks).
        tracker.update(0.15, t0 + 30.0)
        text_early = tracker.format_text(0.15, 30.0, now=t0 + 30.0)
        if "left" in text_early:
            self.assertNotIn("0:59 left", text_early)
            self.assertNotIn("1:00 left", text_early)
        # Slower mid-run progress should yield a longer estimate.
        tracker.update(0.25, t0 + 90.0)
        tracker.update(0.30, t0 + 150.0)
        tracker.update(0.35, t0 + 210.0)
        text_mid = tracker.format_text(0.35, 210.0, now=t0 + 210.0)
        self.assertIn("left", text_mid)
        remaining_sec = int(text_mid.split("~")[1].split(" left")[0].split(":")[0]) * 60
        remaining_sec += int(text_mid.split("~")[1].split(" left")[0].split(":")[1])
        self.assertGreaterEqual(remaining_sec, 120)

    def test_saving_phase(self):
        tracker = ProgressEtaTracker()
        tracker.update(0.95, 200.0)
        text = tracker.format_text(0.95, 200.0, now=200.0)
        self.assertIn("Saving", text)
        self.assertNotIn("left", text)

    def test_ema_smoothing_does_not_halve_on_one_tick(self):
        tracker = ProgressEtaTracker()
        t0 = 500.0
        for frac, dt in ((0.15, 20), (0.25, 80), (0.35, 140), (0.45, 200)):
            tracker.update(frac, t0 + dt)
        before = tracker.format_text(0.45, 200.0, now=t0 + 200.0)
        tracker.update(0.46, t0 + 260.0)
        after = tracker.format_text(0.46, 260.0, now=t0 + 260.0)
        if "left" in before and "left" in after:
            def _parse_remaining(label: str) -> float:
                part = label.split("~")[1].split(" left")[0]
                mins, secs = part.split(":")
                return int(mins) * 60 + int(secs)

            self.assertGreater(_parse_remaining(after), _parse_remaining(before) * 0.5)


if __name__ == "__main__":
    unittest.main()
