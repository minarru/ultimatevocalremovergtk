"""Unit tests for ensemble UI helper logic (presets, titles, filters)."""

from __future__ import annotations

import unittest

from bundled.constants import (
    CHUNK_MIN,
    HYBRID_SPEC,
    MAX_SPEC,
    MEDIAN_SPEC,
    MIN_SPEC,
    SOFT_SPEC,
)
from core.ensemble_algorithms import (
    CUSTOM_PRESET,
    HYBRID_CLEAN_PRESET,
    RECOMMENDED_PRESET,
    SOFT_BLEND_PRESET,
    algorithm_blurb,
    algorithm_row_titles,
    ensemble_options_summary,
    model_row_matches_query,
    models_selection_status,
    pair_for_preset,
    preset_for_pair,
    wav_ensemble_subtitle,
)


class PresetMappingTests(unittest.TestCase):
    def test_recommended_round_trip(self) -> None:
        pair = pair_for_preset(RECOMMENDED_PRESET)
        self.assertEqual(pair, (MAX_SPEC, MIN_SPEC))
        assert pair is not None
        self.assertEqual(preset_for_pair(*pair), RECOMMENDED_PRESET)

    def test_named_presets(self) -> None:
        self.assertEqual(pair_for_preset(SOFT_BLEND_PRESET), (SOFT_SPEC, SOFT_SPEC))
        self.assertEqual(pair_for_preset(HYBRID_CLEAN_PRESET), (HYBRID_SPEC, MIN_SPEC))
        self.assertEqual(preset_for_pair(MEDIAN_SPEC, MEDIAN_SPEC), "Median robust")

    def test_custom_when_unmatched(self) -> None:
        self.assertIsNone(pair_for_preset(CUSTOM_PRESET))
        self.assertEqual(preset_for_pair(MAX_SPEC, SOFT_SPEC), CUSTOM_PRESET)


class StemTitleTests(unittest.TestCase):
    def test_dual_stem_titles(self) -> None:
        primary, secondary = algorithm_row_titles("Vocals", "Instrumental", multi_stem=False)
        self.assertEqual(primary, "Vocals algorithm")
        self.assertEqual(secondary, "Instrumental algorithm")

    def test_fallback_titles(self) -> None:
        primary, secondary = algorithm_row_titles(None, None, multi_stem=False)
        self.assertEqual(primary, "Primary algorithm")
        self.assertEqual(secondary, "Secondary algorithm")

    def test_multi_stem_title(self) -> None:
        primary, secondary = algorithm_row_titles("Vocals", "Instrumental", multi_stem=True)
        self.assertEqual(primary, "Ensemble algorithm")


class FilterAndStatusTests(unittest.TestCase):
    def test_model_row_matches_query(self) -> None:
        self.assertTrue(model_row_matches_query("Kim Vocal 2", "MDX-Net", ""))
        self.assertTrue(model_row_matches_query("Kim Vocal 2", "MDX-Net", "vocal"))
        self.assertTrue(model_row_matches_query("Kim Vocal 2", "MDX-Net", "mdx"))
        self.assertFalse(model_row_matches_query("Kim Vocal 2", "MDX-Net", "demucs"))

    def test_models_selection_status(self) -> None:
        self.assertEqual(models_selection_status(0, visible_matches=0), "No matches")
        self.assertEqual(models_selection_status(0), "Select at least 2 models")
        self.assertEqual(models_selection_status(1), "Select at least 2 models (1 selected)")
        self.assertEqual(models_selection_status(3), "3 models selected")


class SummaryAndBlurbTests(unittest.TestCase):
    def test_incomplete_summary(self) -> None:
        text = ensemble_options_summary(
            stem_chosen=False,
            main_stem="Choose Stem Pair",
            primary_stem=None,
            secondary_stem=None,
            primary_algo=MAX_SPEC,
            secondary_algo=MIN_SPEC,
            model_count=0,
            multi_stem=False,
        )
        self.assertIn("stem pair", text.casefold())

    def test_dual_ready_summary(self) -> None:
        text = ensemble_options_summary(
            stem_chosen=True,
            main_stem="Vocals/Instrumental",
            primary_stem="Vocals",
            secondary_stem="Instrumental",
            primary_algo=MAX_SPEC,
            secondary_algo=MIN_SPEC,
            model_count=3,
            multi_stem=False,
        )
        self.assertEqual(
            text,
            "Vocals ← Max Spec · Instrumental ← Min Spec · 3 models",
        )

    def test_algorithm_blurb_and_wav_subtitle(self) -> None:
        self.assertIn("agreement", algorithm_blurb(SOFT_SPEC).casefold())
        self.assertIn("chunk", wav_ensemble_subtitle(uses_chunk_min=True).casefold())
        self.assertIn("time domain", wav_ensemble_subtitle(uses_chunk_min=False).casefold())
        self.assertTrue(algorithm_blurb(CHUNK_MIN))


class MainStemChangedOrderTests(unittest.TestCase):
    def test_model_list_rebuilds_before_stem_toggles(self) -> None:
        """Regression: stem-only toggles resolve export-semantics hints from
        _selected_model_tags(), which reads the model checklist built by
        _rebuild_model_list(). Rebuilding toggles first meant that checklist
        still reflected the *previous* stem pair for one render pass.
        """
        from unittest import mock

        import ui.ensemble.window as ensemble_window

        page = object.__new__(ensemble_window.EnsemblePage)
        page._loading = False
        page.settings = mock.Mock()
        page.main_stem_row = mock.Mock()
        page.saved_row = mock.Mock()

        order: list[str] = []
        page._refresh_ensemble_type_values = mock.Mock(
            side_effect=lambda: order.append("refresh_type")
        )
        page._rebuild_model_list = mock.Mock(
            side_effect=lambda tags: order.append("rebuild_model_list")
        )
        page._rebuild_stem_only_toggles = mock.Mock(
            side_effect=lambda: order.append("rebuild_stem_toggles")
        )
        page._update_ensemble_options_summary = mock.Mock(
            side_effect=lambda: order.append("update_summary")
        )
        page._selected_model_tags = mock.Mock(return_value=["tag-a"])

        with mock.patch.object(
            ensemble_window, "get_combo_value", return_value="Vocals/Instrumental"
        ), mock.patch.object(ensemble_window, "set_combo_value"):
            page._on_main_stem_changed()

        self.assertEqual(
            order,
            ["refresh_type", "rebuild_model_list", "rebuild_stem_toggles", "update_summary"],
        )


if __name__ == "__main__":
    unittest.main()
