import typing
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
    VR_ARCH_TYPE,
)
from core.stems import EnsemblePair
from core.settings import Settings
from core.run_estimate import (
    ProgressEtaTracker,
    RunCostTier,
    WorkloadEstimate,
    combine_progress_local_step,
    classify_export_tier,
    classify_run_tier,
    compute_run_cost_units,
    count_expected_outputs,
    count_inference_passes,
    count_inference_passes_from_models,
    ensemble_export_summary,
    estimate_workload,
    format_workload_line,
    save_progress_local_step,
)
from core.stem_selection import (
    _QUICK_ALL,
    _QUICK_VOCALS,
)
from ui.widgets.stem_only import (
    SaveStemsSection,
)


class _Settings(Settings):
    def __init__(self, data: typing.Any=None):
        super().__init__()
        self.update(data or {})

    def __getitem__(self, key: typing.Any):
        return self.get(key)

    def __setitem__(self, key: typing.Any, value: typing.Any):
        self.set(key, value)


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

    def test_count_from_models_pre_proc_and_voc_split(self):
        model = SimpleNamespace(
            process_method=DEMUCS_ARCH_TYPE,
            is_secondary_model_activated=False,
            demucs_4_stem_added_count=0,
            pre_proc_model_activated=True,
            is_vocal_split_model_activated=True,
        )
        self.assertEqual(count_inference_passes_from_models([model]), 4)

    def test_job_runner_delegates_to_shared_helper(self):
        from core.job_runner import JobRunner

        model = SimpleNamespace(
            process_method=MDX_ARCH_TYPE,
            is_secondary_model_activated=True,
            demucs_4_stem_added_count=0,
            pre_proc_model_activated=False,
            is_vocal_split_model_activated=False,
        )
        runner = JobRunner(_Settings({}))
        self.assertEqual(
            runner._count_true_models([model]),
            count_inference_passes_from_models([model]),
        )

    def test_count_light_mdx_secondary(self):
        settings = _Settings({"mdx_is_secondary_model_activate": True})
        self.assertEqual(count_inference_passes(settings, method_key=MDX_ARCH_TYPE), 2)

    def test_count_ensemble_members_fallback_without_repo(self):
        settings = _Settings({"selected_models": ["a", "b", "c"]})
        self.assertEqual(count_inference_passes(settings, method_key=ENSEMBLE_MODE), 3)

    def test_count_ensemble_uses_assembled_models(self):
        settings = _Settings({"selected_models": ["a", "b"]})

        class _Repo:
            pass

        assembled = [
            SimpleNamespace(
                process_method=MDX_ARCH_TYPE,
                is_secondary_model_activated=True,
                demucs_4_stem_added_count=0,
                pre_proc_model_activated=False,
                is_vocal_split_model_activated=False,
                model_status=True,
            ),
            SimpleNamespace(
                process_method=MDX_ARCH_TYPE,
                is_secondary_model_activated=False,
                demucs_4_stem_added_count=0,
                pre_proc_model_activated=False,
                is_vocal_split_model_activated=False,
                model_status=True,
            ),
        ]
        import core.model_config as model_config

        original = model_config.assemble_model
        model_config.assemble_model = lambda *a, **k: assembled
        try:
            self.assertEqual(
                count_inference_passes(settings, method_key=ENSEMBLE_MODE, repo=_Repo()),
                3,
            )
        finally:
            model_config.assemble_model = original


class OutputCountExtraTests(unittest.TestCase):
    def test_four_stem_ensemble_outputs(self):
        settings = _Settings(
            {
                "ensemble_main_stem": EnsemblePair.FOUR_STEM.value,
                "selected_models": ["a", "b"],
                "is_save_all_outputs_ensemble": False,
            }
        )
        self.assertEqual(
            count_expected_outputs(settings=settings, method_key=ENSEMBLE_MODE),
            4,
        )
        self.assertEqual(ensemble_export_summary(settings), "4 stem outputs")

    def test_save_all_adds_member_files(self):
        settings = _Settings(
            {
                "ensemble_main_stem": EnsemblePair.FOUR_STEM.value,
                "selected_models": ["a", "b", "c"],
                "is_save_all_outputs_ensemble": True,
            }
        )
        self.assertEqual(
            count_expected_outputs(settings=settings, method_key=ENSEMBLE_MODE),
            7,
        )

    def test_voc_split_instrumentals_add_two(self):
        settings = _Settings(
            {
                "is_set_vocal_splitter": True,
                "set_vocal_splitter": "Some Split Model",
                "is_save_inst_set_vocal_splitter": True,
            }
        )
        section = SaveStemsSection(settings=settings)
        section.configure_exclusive(
            primary_stem=VOCAL_STEM,
            secondary_stem="Instrumental",
            primary_key="is_primary_stem_only",
            secondary_key="is_secondary_stem_only",
            has_model=True,
        )
        self.assertEqual(
            count_expected_outputs(section, settings=settings, method_key=MDX_ARCH_TYPE),
            4,
        )

    def test_estimate_hidden_ensemble_four_stem(self):
        settings = _Settings(
            {
                "ensemble_main_stem": EnsemblePair.FOUR_STEM.value,
                "selected_models": ["a", "b"],
                "is_save_all_outputs_ensemble": False,
                "is_gpu_conversion": True,
                "model_sample_mode": False,
                "model_sample_mode_duration": 30,
            }
        )
        section = SaveStemsSection(settings=settings)
        section.configure_hidden(has_model=False)
        estimate = estimate_workload(
            settings,
            method_key=ENSEMBLE_MODE,
            save_stems=section,
            has_model=True,
        )
        self.assertIsNotNone(estimate)
        assert estimate is not None
        self.assertEqual(estimate.output_count, 4)
        self.assertEqual(estimate.inference_passes, 2)
        self.assertIn("2 passes", estimate.format_summary())


class RunCostUnitTests(unittest.TestCase):
    def test_tta_doubles_units(self):
        settings = _Settings({"is_tta": True})
        self.assertEqual(compute_run_cost_units(settings, VR_ARCH_TYPE, 1), 2)
        self.assertEqual(classify_run_tier(2), RunCostTier.TYPICAL)

    def test_shifts_bump_tier(self):
        settings = _Settings({"shifts": 3})
        self.assertEqual(compute_run_cost_units(settings, DEMUCS_ARCH_TYPE, 1), 3)
        self.assertEqual(classify_run_tier(3), RunCostTier.SLOWER)

    def test_estimate_run_tier_uses_units(self):
        settings = _Settings(
            {
                "is_tta": True,
                "is_gpu_conversion": False,
                "model_sample_mode": False,
                "model_sample_mode_duration": 30,
            }
        )
        section = SaveStemsSection(settings=settings)
        section.configure_exclusive(
            primary_stem=VOCAL_STEM,
            secondary_stem="Instrumental",
            primary_key="is_primary_stem_only",
            secondary_key="is_secondary_stem_only",
            has_model=True,
        )
        settings.process.stem_focus = VOCAL_STEM
        section.sync_from_settings()
        estimate = estimate_workload(
            settings,
            method_key=VR_ARCH_TYPE,
            save_stems=section,
            has_model=True,
        )
        self.assertIsNotNone(estimate)
        assert estimate is not None
        self.assertEqual(estimate.inference_passes, 1)
        self.assertEqual(estimate.run_tier, RunCostTier.TYPICAL)


class SaveStemsOutputCountTests(unittest.TestCase):
    def setUp(self):
        self.settings = _Settings(
            {
                "mdx_stems_selected": [],
                "mdx_stems": ALL_STEMS,
                "demucs_stems": ALL_STEMS,
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
        self.settings.process.stem_focus = VOCAL_STEM
        self.section.sync_from_settings()
        self.assertEqual(self.section.expected_output_count(), 1)

    def test_subset_quick_vocals(self):
        self.section.configure_subset(
            stems=[VOCAL_STEM, BASS_STEM, DRUM_STEM],
            show_quick_export=True,
            primary_key="is_primary_stem_only",
            secondary_key="is_secondary_stem_only",
            has_model=True,
        )
        self.section._subset_mode = _QUICK_VOCALS
        self.assertEqual(self.section.expected_output_count(), 1)

    def test_subset_all_stems(self):
        self.section.configure_subset(
            stems=[VOCAL_STEM, BASS_STEM],
            show_quick_export=True,
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


class ProgressLocalStepTests(unittest.TestCase):
    def test_save_steps_span_local_save_range(self):
        self.assertEqual(save_progress_local_step(1, 4), 0.915)
        self.assertEqual(save_progress_local_step(4, 4), 0.96)

    def test_combine_steps_end_at_one(self):
        self.assertAlmostEqual(combine_progress_local_step(0, 2), 0.985)
        self.assertEqual(combine_progress_local_step(1, 2), 1.0)


class ProgressEtaTrackerTests(unittest.TestCase):
    def test_load_phase_holds_without_percent(self):
        tracker = ProgressEtaTracker()
        tracker.update(0.05, 30.0, local_step=0.05, pass_index=1, pass_total=1)
        text = tracker.format_text(0.05, 30.0, now=30.0)
        self.assertIn("Loading model", text)
        self.assertNotIn("left", text)
        self.assertNotIn("%", text)
        self.assertTrue(tracker.is_indeterminate(0.05))

    def test_known_pass_total_drives_display(self):
        tracker = ProgressEtaTracker()
        tracker.update(0.25, 40.0, local_step=0.50, pass_index=1, pass_total=2, detail="Model 1/2")
        display = tracker.inference_display_fraction(0.25)
        self.assertIsNotNone(display)
        assert display is not None
        self.assertAlmostEqual(display, 0.25, delta=0.05)
        text = tracker.format_text(0.25, 40.0, now=40.0)
        self.assertIn("Model 1/2", text)

    def test_infer_clock_pauses_during_save(self):
        tracker = ProgressEtaTracker()
        tracker.update(0.30, 100.0, local_step=0.40, pass_index=1, pass_total=1)
        tracker.update(0.50, 130.0, local_step=0.60, pass_index=1, pass_total=1)
        # Long save should not count toward inference elapsed used for gating.
        tracker.update(0.90, 400.0, local_step=0.92, pass_index=1, pass_total=1)
        self.assertTrue(tracker.is_indeterminate(0.90))
        self.assertIn("Saving stems", tracker.format_text(0.90, 300.0, now=400.0))
        # Resume inference on next pass
        tracker.update(0.55, 410.0, local_step=0.30, pass_index=2, pass_total=2)
        self.assertFalse(tracker.is_indeterminate(0.55))
        self.assertGreaterEqual(len(tracker._pass_durations), 1)

    def test_pass_boundary_records_duration(self):
        tracker = ProgressEtaTracker()
        tracker.update(0.20, 10.0, local_step=0.30, pass_index=1, pass_total=2)
        tracker.update(0.40, 40.0, local_step=0.70, pass_index=1, pass_total=2)
        tracker.update(0.55, 50.0, local_step=0.20, pass_index=2, pass_total=2)
        self.assertGreaterEqual(len(tracker._pass_durations), 1)

    def test_combine_shows_index_and_eta(self):
        tracker = ProgressEtaTracker()
        tracker.update(0.40, 50.0, local_step=0.50, pass_index=1, pass_total=1)
        tracker.update(0.80, 80.0, local_step=0.80, pass_index=1, pass_total=1)
        tracker.update(
            0.95,
            90.0,
            local_step=0.98,
            pass_index=1,
            pass_total=1,
            combine_index=1,
            combine_total=3,
        )
        text = tracker.format_text(0.95, 90.0, now=90.0)
        self.assertIn("Combining ensemble (1/3)", text)
        self.assertNotIn("left", text)
        tracker.update(
            0.97,
            100.0,
            local_step=0.99,
            pass_index=1,
            pass_total=1,
            combine_index=2,
            combine_total=3,
        )
        text_next = tracker.format_text(0.97, 100.0, now=100.0)
        self.assertIn("Combining ensemble (2/3)", text_next)
        self.assertIn("left", text_next)

    def test_early_inference_calculating(self):
        tracker = ProgressEtaTracker()
        tracker.update(0.12, 40.0, local_step=0.20, pass_index=1, pass_total=1)
        text = tracker.format_text(0.12, 40.0, now=40.0)
        self.assertIn("Calculating estimate", text)
        self.assertIn("%", text)
        tracker.update(0.18, 42.5, local_step=0.28, pass_index=1, pass_total=1)
        later = tracker.format_text(0.18, 2.5, now=42.5)
        self.assertIn("left", later)
        self.assertNotIn("Calculating estimate", later)

    def test_saving_phase_via_global_fraction(self):
        tracker = ProgressEtaTracker()
        tracker.update(0.95, 200.0)
        text = tracker.format_text(0.95, 200.0, now=200.0)
        self.assertIn("Saving stems", text)
        self.assertNotIn("left", text)

    def test_mdx_climb_does_not_show_one_minute_early(self):
        tracker = ProgressEtaTracker()
        t0 = 1000.0
        tracker.update(0.15, t0, local_step=0.22, pass_index=1, pass_total=1)
        tracker.update(0.15, t0 + 30.0, local_step=0.22, pass_index=1, pass_total=1)
        text = tracker.format_text(0.15, 30.0, now=t0 + 30.0)
        self.assertIn("left", text)
        remaining_sec = int(text.split("~")[1].split(" left")[0].split(":")[0]) * 60
        remaining_sec += int(text.split("~")[1].split(" left")[0].split(":")[1])
        self.assertGreaterEqual(remaining_sec, 120)

    def test_ema_smoothing_does_not_halve_on_one_tick(self):
        tracker = ProgressEtaTracker()
        t0 = 500.0
        for frac, dt, local in (
            (0.15, 20, 0.20),
            (0.25, 80, 0.35),
            (0.35, 140, 0.50),
            (0.45, 200, 0.65),
        ):
            tracker.update(frac, t0 + dt, local_step=local, pass_index=1, pass_total=1)
        before = tracker.format_text(0.45, 200.0, now=t0 + 200.0)
        tracker.update(0.46, t0 + 260.0, local_step=0.66, pass_index=1, pass_total=1)
        after = tracker.format_text(0.46, 260.0, now=t0 + 260.0)
        if "left" in before and "left" in after:
            def _parse_remaining(label: str) -> float:
                part = label.split("~")[1].split(" left")[0]
                mins, secs = part.split(":")
                return int(mins) * 60 + int(secs)

            self.assertGreater(_parse_remaining(after), _parse_remaining(before) * 0.5)


class JobProgressCallbackTests(unittest.TestCase):
    def test_progress_forwards_pass_metadata(self):
        from core.job_callbacks import JobCallbacks

        seen = {}

        def on_progress(fraction: typing.Any, **kwargs: typing.Any):
            seen["fraction"] = fraction
            seen.update(kwargs)

        cb = JobCallbacks(on_progress=on_progress)
        cb.progress(
            0.4,
            local_step=0.5,
            pass_index=2,
            pass_total=4,
            detail="Model 2/4 · Demo",
        )
        self.assertEqual(seen["fraction"], 0.4)
        self.assertEqual(seen["pass_index"], 2)
        self.assertEqual(seen["pass_total"], 4)
        self.assertEqual(seen["detail"], "Model 2/4 · Demo")


if __name__ == "__main__":
    unittest.main()
