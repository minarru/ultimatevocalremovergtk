"""Unit tests for ensemble UI helper logic (presets, titles, filters)."""

from __future__ import annotations

import unittest
from collections.abc import Iterable
from typing import Any

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
    PAIR_CONSISTENT_PRESET,
    RECOMMENDED_PRESET,
    SOFT_BLEND_PRESET,
    algorithm_blurb,
    algorithm_row_titles,
    models_selection_status,
    pair_for_preset,
    preset_for_pair,
    wav_ensemble_subtitle,
)
from core.stem_roles import StemRoleId
from core.stems import StemId, StemRoute, StemRouteKind
from tests.private_gtk import require_private_gtk


def setUpModule() -> None:
    require_private_gtk()


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

    def test_pair_consistent_titles_generic_when_unresolved(self) -> None:
        primary, secondary = algorithm_row_titles(
            None,
            None,
            multi_stem=False,
            derive_complement_from_mix=True,
        )
        self.assertEqual(primary, "Primary algorithm")
        self.assertEqual(secondary, "Complement (from mix)")

    def test_pair_consistent_titles_use_leftover_from_mix(self) -> None:
        primary, secondary = algorithm_row_titles(
            "Vocals",
            "Instrumental",
            multi_stem=False,
            derive_complement_from_mix=True,
            leftover_label="Instrumental",
        )
        self.assertEqual(primary, "Vocals algorithm")
        self.assertEqual(secondary, "Instrumental (from mix)")


class FilterAndStatusTests(unittest.TestCase):
    def test_models_selection_status(self) -> None:
        self.assertEqual(models_selection_status(0, visible_matches=0), "No matches")
        self.assertEqual(models_selection_status(0), "Select at least 2 models")
        self.assertEqual(models_selection_status(1), "Select at least 2 models (1 selected)")
        self.assertEqual(models_selection_status(3), "3 models selected")


class BlurbTests(unittest.TestCase):
    def test_algorithm_blurb_and_wav_subtitle(self) -> None:
        self.assertIn("agreement", algorithm_blurb(SOFT_SPEC).casefold())
        self.assertIn("chunk", wav_ensemble_subtitle(uses_chunk_min=True).casefold())
        self.assertIn("time domain", wav_ensemble_subtitle(uses_chunk_min=False).casefold())
        self.assertTrue(algorithm_blurb(CHUNK_MIN))


_VOCALS = StemRoleId("vocal.vocals")
_INST = StemRoleId("mix.instrumental")


def _native_route(role: StemRoleId, key: str) -> StemRoute:
    return StemRoute(StemId(key), role, key, key, StemRouteKind.NATIVE)


def _complement_route(role: StemRoleId, of_role: StemRoleId) -> StemRoute:
    return StemRoute(
        None,
        role,
        str(role),
        str(role),
        StemRouteKind.DERIVED,
        complement_of=of_role,
    )


class PairConsistentPlanAvailabilityTests(unittest.TestCase):
    def test_real_preset_signals_settle_and_preserve_complement_state(self) -> None:
        from unittest import mock

        import gi

        gi.require_version("Gtk", "4.0")
        gi.require_version("Adw", "1")
        from gi.repository import Adw, Gtk

        from ui.ensemble.window import EnsemblePage
        from ui.template import load_builder
        from ui.widgets.rows import get_combo_value, set_combo_value

        if not Gtk.init_check():
            self.skipTest("GTK display unavailable")
        Adw.init()
        page = self._page()
        page._loading = False
        page._custom_algorithms = False
        page._stem_pair_chosen = lambda: True
        page._update_wav_ensemble_subtitle = mock.Mock()
        page._update_algorithm_visibility = EnsemblePage._update_algorithm_visibility.__get__(page)
        builder = load_builder("ensemble-page")
        for name in (
            "preset_row",
            "derive_complement_row",
            "primary_algo_row",
            "secondary_algo_row",
        ):
            setattr(page, name, builder.get_object(name))
        vocal = (_native_route(_VOCALS, "vocals"), _complement_route(_INST, _VOCALS))
        page._dry_resolved_member_routes.return_value = (vocal, vocal)
        page._refresh_ensemble_type_values()
        notifications = 0

        def changed(*args: object) -> None:
            nonlocal notifications
            notifications += 1
            # Bound a regression without hanging the suite or raising inside GI.
            if notifications <= 20:
                page._on_preset_changed(*args)

        page.preset_row.connect("notify::selected", changed)
        page.derive_complement_row.connect("notify::active", page._on_derive_complement_changed)
        for row in (page.primary_algo_row, page.secondary_algo_row):
            row.connect("notify::selected", page._on_ensemble_type_changed)

        set_combo_value(page.preset_row, PAIR_CONSISTENT_PRESET)
        self.assertLess(notifications, 20, "Preset selection entered a notification loop")
        self.assertEqual(get_combo_value(page.preset_row), PAIR_CONSISTENT_PRESET)
        self.assertTrue(page.settings.ensemble.derive_complement_from_mix)
        self.assertTrue(page.derive_complement_row.get_active())
        self.assertFalse(page.secondary_algo_row.get_sensitive())

        set_combo_value(page.preset_row, CUSTOM_PRESET)
        self.assertTrue(page.primary_algo_row.get_visible())
        self.assertFalse(page.secondary_algo_row.get_sensitive())
        page.derive_complement_row.set_active(False)
        self.assertFalse(page.settings.ensemble.derive_complement_from_mix)
        self.assertTrue(page.secondary_algo_row.get_sensitive())
        page.derive_complement_row.set_active(True)

        page._dry_resolved_member_routes.return_value = None
        page._apply_algorithm_row_presentation()
        page._update_algo_sensitivity()
        self.assertFalse(page.derive_complement_row.get_visible())
        self.assertTrue(page.settings.ensemble.derive_complement_from_mix)
        self.assertTrue(page.secondary_algo_row.get_sensitive())
        page._dry_resolved_member_routes.return_value = (vocal, vocal)
        page._apply_algorithm_row_presentation()
        page._update_algo_sensitivity()
        self.assertTrue(page.derive_complement_row.get_visible())
        self.assertTrue(page.derive_complement_row.get_active())
        self.assertFalse(page.secondary_algo_row.get_sensitive())

        set_combo_value(page.preset_row, RECOMMENDED_PRESET)
        self.assertFalse(page.settings.ensemble.derive_complement_from_mix)
        self.assertFalse(page.derive_complement_row.get_active())
        self.assertLess(notifications, 20)

    def _page(self) -> Any:
        from unittest import mock

        from core.settings import Settings
        from ui.ensemble.window import EnsemblePage

        page: Any = object.__new__(EnsemblePage)
        page.settings = Settings.defaults()
        page._syncing_preset = False
        page._lock_leftover_algo = False
        page._ensemble_is_multi_or_four = mock.Mock(return_value=False)
        page._ensemble_pair = mock.Mock(return_value="pair.vocals_instrumental")
        page._ensemble_stem_pair = mock.Mock(return_value=("Vocals", "Instrumental"))
        page._dry_resolved_member_routes = mock.Mock(return_value=None)
        page.derive_complement_row = mock.Mock()
        page.preset_row = mock.Mock()
        page._update_algorithm_visibility = mock.Mock()
        page.primary_algo_row = mock.Mock()
        page.secondary_algo_row = mock.Mock()
        return page

    def test_voc_primary_members_yield_a_plan(self) -> None:
        page = self._page()
        voc_member = (_native_route(_VOCALS, "vocals"), _complement_route(_INST, _VOCALS))
        page._dry_resolved_member_routes.return_value = (voc_member, voc_member)

        plan = page._pair_consistent_plan()

        self.assertIsNotNone(plan)
        assert plan is not None
        self.assertEqual(plan.stacked_role, _VOCALS)
        self.assertEqual(plan.leftover_role, _INST)

    def test_dual_native_or_unresolved_or_multi_has_no_plan(self) -> None:
        page = self._page()
        dual = (_native_route(_VOCALS, "vocals"), _native_route(_INST, "instrumental"))
        page._dry_resolved_member_routes.return_value = (dual, dual)
        self.assertIsNone(page._pair_consistent_plan())

        page._dry_resolved_member_routes.return_value = None
        self.assertIsNone(page._pair_consistent_plan())

        page._ensemble_is_multi_or_four.return_value = True
        page._dry_resolved_member_routes.return_value = (
            (_native_route(_VOCALS, "vocals"), _complement_route(_INST, _VOCALS)),
            (_native_route(_VOCALS, "vocals"), _complement_route(_INST, _VOCALS)),
        )
        self.assertIsNone(page._pair_consistent_plan())

    def test_switch_visible_only_when_a_plan_exists(self) -> None:
        from unittest import mock

        import ui.ensemble.window as ensemble_window

        page = self._page()
        voc_member = (_native_route(_VOCALS, "vocals"), _complement_route(_INST, _VOCALS))
        page._dry_resolved_member_routes.return_value = (voc_member, voc_member)

        with (
            mock.patch.object(ensemble_window, "set_combo_values"),
            mock.patch.object(ensemble_window, "set_combo_value"),
            mock.patch.object(ensemble_window, "set_row_title"),
        ):
            page._apply_algorithm_row_presentation()

        page.derive_complement_row.set_visible.assert_called_with(True)

        page._dry_resolved_member_routes.return_value = None
        with (
            mock.patch.object(ensemble_window, "set_combo_values"),
            mock.patch.object(ensemble_window, "set_combo_value"),
            mock.patch.object(ensemble_window, "set_row_title"),
        ):
            page._apply_algorithm_row_presentation()

        page.derive_complement_row.set_visible.assert_called_with(False)

    def test_leftover_stays_unlocked_until_the_toggle_is_on(self) -> None:
        from unittest import mock

        import ui.ensemble.window as ensemble_window

        page = self._page()
        voc_member = (_native_route(_VOCALS, "vocals"), _complement_route(_INST, _VOCALS))
        page._dry_resolved_member_routes.return_value = (voc_member, voc_member)
        page.settings.ensemble.derive_complement_from_mix = False

        with (
            mock.patch.object(ensemble_window, "set_combo_values"),
            mock.patch.object(ensemble_window, "set_combo_value"),
            mock.patch.object(ensemble_window, "set_row_title"),
        ):
            page._apply_algorithm_row_presentation()

        self.assertFalse(page._lock_leftover_algo)

        page.settings.ensemble.derive_complement_from_mix = True
        with (
            mock.patch.object(ensemble_window, "set_combo_values"),
            mock.patch.object(ensemble_window, "set_combo_value"),
            mock.patch.object(ensemble_window, "set_row_title"),
        ):
            page._apply_algorithm_row_presentation()

        self.assertTrue(page._lock_leftover_algo)

    def test_preset_combo_drops_pair_consistent_when_plan_is_missing(self) -> None:
        from unittest import mock

        import ui.ensemble.window as ensemble_window

        page = self._page()
        page._dry_resolved_member_routes.return_value = None
        captured: list[tuple[str, ...]] = []

        def _capture(_row: object, values: Iterable[str]) -> None:
            captured.append(tuple(values))

        with (
            mock.patch.object(ensemble_window, "set_combo_values", side_effect=_capture),
            mock.patch.object(ensemble_window, "set_combo_value"),
            mock.patch.object(ensemble_window, "set_row_title"),
        ):
            page._apply_algorithm_row_presentation()

        self.assertTrue(captured)
        self.assertNotIn(PAIR_CONSISTENT_PRESET, captured[-1])


class MainStemChangedOrderTests(unittest.TestCase):
    def test_stem_change_refreshes_types_before_reconciling_members(self) -> None:
        """Reconciliation now owns refreshing output choices after the model list."""
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
        page._reconcile_member_list = mock.Mock(
            side_effect=lambda tags: order.append("rebuild_model_list")
        )
        page._rebuild_stem_only_toggles = mock.Mock(
            side_effect=lambda: order.append("rebuild_stem_toggles")
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
            ["refresh_type", "rebuild_model_list"],
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

    def test_splitter_refresh_repick_blocks_ensemble_readiness(self) -> None:
        from unittest import mock

        from core.settings import Settings
        from ui.ensemble.window import EnsemblePage

        settings = Settings.defaults()
        settings.ensemble.main_stem = "pair.center_side"
        settings.ensemble.selected_models = ["mdx:center", "mdx:side"]
        page = object.__new__(EnsemblePage)
        page.settings = settings
        page._effective_selected_models = lambda: settings.ensemble.selected_models
        page.vocal_split_row = mock.MagicMock()
        page.vocal_split_row.blocked_reason.return_value = (
            "Choose a vocal splitter model again after the model refresh"
        )

        self.assertEqual(
            page._config_blocked_reason(),
            "Choose a vocal splitter model again after the model refresh",
        )


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
        page.output_stems = mock.Mock()
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


class ConflictingMemberRoutesTests(unittest.TestCase):
    """Regression: ``run_export_routes`` raises on a stem-semantics runtime
    error, and the unfiltered Multi-Stem list can hold such a member. The
    ensemble page's GTK callbacks must treat it as unresolved instead of
    letting the ``ValueError`` escape."""

    def _page(self, models: dict[str, Any]) -> Any:
        from types import SimpleNamespace
        from unittest import mock

        from ui.ensemble.window import EnsemblePage

        page: Any = object.__new__(EnsemblePage)
        page._effective_selected_models = mock.Mock(return_value=list(models))
        page._resolve_ensemble_member_model = mock.Mock(side_effect=models.__getitem__)
        page.context = SimpleNamespace(repo=None)
        return page

    @staticmethod
    def _model(runtime_error: str = "") -> Any:
        from types import SimpleNamespace

        route = _native_route(_VOCALS, "vocals")
        return SimpleNamespace(
            stem_semantics=SimpleNamespace(runtime_error=runtime_error),
            available_stem_routes=(route,),
            selected_stem_routes=(route,),
        )

    def test_conflicting_member_makes_dry_routes_unresolved(self) -> None:
        page = self._page({"mdx:ok": self._model(), "mdx:bad": self._model("config conflicts")})
        self.assertIsNone(page._dry_resolved_member_routes())

    def test_clean_members_still_resolve(self) -> None:
        page = self._page({"mdx:a": self._model(), "mdx:b": self._model()})
        routes = page._dry_resolved_member_routes()
        self.assertIsNotNone(routes)
        self.assertEqual(len(routes), 2)

    def test_blend_options_skip_conflicting_member(self) -> None:
        from unittest import mock

        page = self._page({"mdx:ok": self._model(), "mdx:bad": self._model("config conflicts")})
        page.window = mock.Mock()
        page.settings = mock.Mock()
        with (
            mock.patch("core.model_display.format_tag_title", side_effect=lambda tag, _repo: tag),
            mock.patch("ui.ensemble.blend_dialog.show_blend_dialog") as show,
        ):
            page._open_blend_options()
        members = show.call_args.args[2]
        self.assertEqual([member[0] for member in members], ["mdx:ok"])


if __name__ == "__main__":
    unittest.main()
