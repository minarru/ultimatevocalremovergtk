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
        primary, _secondary = algorithm_row_titles("Vocals", "Instrumental", multi_stem=True)
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
        page._model_members_for_rebuild = mock.Mock(return_value=["tag-a"])

        with (
            mock.patch.object(
                ensemble_window,
                "get_combo_value",
                return_value="pair.vocals_instrumental",
            ),
            mock.patch.object(ensemble_window, "set_combo_value"),
        ):
            page._on_main_stem_changed()

        self.assertEqual(
            order,
            ["refresh_type", "rebuild_model_list", "rebuild_stem_toggles", "update_summary"],
        )


class CenterSideReadinessTests(unittest.TestCase):
    def test_current_center_side_id_is_ready_with_two_selected_models(self) -> None:
        """The current spatial pair reaches the normal ensemble readiness path."""
        from core.settings import Settings
        from ui.ensemble.window import EnsemblePage

        settings = Settings.defaults()
        settings.ensemble.main_stem = "pair.center_side"
        settings.ensemble.selected_models = [
            "mdx:bs_mid_side1_gilliaaan",
            "mdx:bs_mid_side2_gilliaaan",
        ]
        page = object.__new__(EnsemblePage)
        page.settings = settings
        page._effective_selected_models = lambda: settings.ensemble.selected_models

        self.assertEqual(page._ensemble_pair(), "pair.center_side")
        self.assertIsNone(page._config_blocked_reason())


class InstalledPairChoiceTests(unittest.TestCase):
    def test_only_choices_with_two_distinct_installed_contributors_are_listed(self) -> None:
        from ui.ensemble.window import installed_ensemble_pair_choices

        class _Repo:
            def ensemble_model_list(self, _settings: object, pair_id: str) -> list[str]:
                return {
                    "pair.vocals_instrumental": ["mdx:a", "vr:b"],
                    "pair.karaoke": ["mdx:k"],
                    "pair.backing_vocals": ["vr:bve", "mdx:bve"],
                    "pair.center_side": ["mdx:center", "mdx:side", "mdx:center"],
                    "mode.four_stem": ["demucs:a"],
                    "mode.multi_stem": ["demucs:a", "mdx:a"],
                }.get(pair_id, [])

        choices = installed_ensemble_pair_choices(_Repo(), object())

        self.assertEqual(
            choices,
            [
                ("", "Choose Stem Pair"),
                ("pair.vocals_instrumental", "Vocals/Instrumental"),
                (
                    "pair.backing_vocals",
                    "Backing Vocals/Instrumental with Lead Vocals",
                ),
                ("pair.center_side", "Center/Side"),
                ("mode.multi_stem", "Multi-stem Ensemble"),
            ],
        )


class RebuildStemOnlyTogglesConfidenceTests(unittest.TestCase):
    """Regression: _rebuild_stem_only_toggles is a second configure_exclusive
    call site the stem-focus anchoring plan's spec missed (it claimed only
    one call site existed) -- it must forward the same karaoke/bv
    confidence signals as MethodView._configure_save_stems, or the
    ensemble page silently drives stem-focus anchoring with
    is_karaoke=False/is_karaoke_curated=False/is_bv=False regardless of
    the resolved model's real metadata."""

    def _page(self):
        from unittest import mock

        import ui.ensemble.window as ensemble_window

        save_stems = mock.Mock()
        page = object.__new__(ensemble_window.EnsemblePage)
        page.settings = mock.Mock()
        page.save_stems = save_stems
        page.stems_group = mock.Mock()
        page._ensemble_stem_pair = mock.Mock(return_value=("Vocals", "Instrumental"))
        page._ensemble_is_multi_or_four = mock.Mock(return_value=False)
        page._ensemble_pair_routes = mock.Mock(return_value=())
        page._update_stems_group_metadata = mock.Mock()
        return page, save_stems

    def test_passes_karaoke_and_bv_confidence_from_the_resolved_model(self) -> None:
        from types import SimpleNamespace
        from unittest import mock

        page, save_stems = self._page()
        model = SimpleNamespace(is_karaoke=True, is_karaoke_curated=True, is_bv_model=False)
        page._resolve_ensemble_semantics_model = mock.Mock(return_value=model)

        page._rebuild_stem_only_toggles()

        _, kwargs = save_stems.configure_exclusive.call_args
        self.assertTrue(kwargs["is_karaoke"])
        self.assertTrue(kwargs["is_karaoke_curated"])
        self.assertFalse(kwargs["is_bv"])
        self.assertEqual(kwargs["stem_count"], 2)

    def test_defaults_safely_when_the_model_cannot_be_resolved(self) -> None:
        from unittest import mock

        page, save_stems = self._page()
        page._resolve_ensemble_semantics_model = mock.Mock(return_value=None)

        page._rebuild_stem_only_toggles()

        _, kwargs = save_stems.configure_exclusive.call_args
        self.assertFalse(kwargs["is_karaoke"])
        self.assertFalse(kwargs["is_karaoke_curated"])
        self.assertFalse(kwargs["is_bv"])


if __name__ == "__main__":
    unittest.main()
