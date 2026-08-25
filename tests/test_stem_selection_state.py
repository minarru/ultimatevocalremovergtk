"""Boundary tests for the extracted Save Stems state module."""

from __future__ import annotations

import unittest
from pathlib import Path

from core.settings import Settings

_REPO = Path(__file__).resolve().parents[1]
_STATE = _REPO / "core" / "stem_selection.py"
_JOB_RESOLUTION = _REPO / "core" / "settings" / "job_resolution.py"
_STEM_ONLY = _REPO / "ui" / "widgets" / "stem_only.py"
_METHOD_VIEW = _REPO / "ui" / "views" / "base.py"
_OPTION_SUMMARIES = _REPO / "ui" / "option_summaries.py"


class StemSelectionModuleBoundaryTests(unittest.TestCase):
    def test_state_module_has_no_gtk_or_ui(self) -> None:
        source = _STATE.read_text(encoding="utf-8")
        self.assertNotIn("from gi", source)
        self.assertNotIn("import gi", source)
        self.assertNotIn("Gtk", source)
        self.assertNotIn("Adw", source)
        self.assertNotIn("ui.", source)

    def test_job_resolution_does_not_define_apply_stem_selection(self) -> None:
        source = _JOB_RESOLUTION.read_text(encoding="utf-8")
        self.assertNotIn("def apply_stem_selection", source)

    def test_secondary_slot_labels_share_the_manifest_projection_helper(self) -> None:
        from ui.option_summaries import secondary_stem_pair_label

        self.assertEqual(secondary_stem_pair_label("voc_inst"), "Vocals/Instrumental")
        self.assertEqual(secondary_stem_pair_label("other"), "Residual/Mix minus Residual")
        self.assertEqual(secondary_stem_pair_label("bass"), "Bass/Bass Removed")
        self.assertEqual(secondary_stem_pair_label("drums"), "Drums/Drums Removed")

        method_source = _METHOD_VIEW.read_text(encoding="utf-8")
        summary_source = _OPTION_SUMMARIES.read_text(encoding="utf-8")
        self.assertIn("secondary_stem_pair_label(slot)", method_source)
        self.assertIn("secondary_stem_pair_label(slot)", summary_source)
        self.assertNotIn('"Bass/No Bass"', method_source + summary_source)

    def test_stem_only_does_not_define_persist_reducers(self) -> None:
        source = _STEM_ONLY.read_text(encoding="utf-8")
        self.assertNotIn("def _stem_focus_for_choice", source)
        self.assertNotIn("def _persist_subset", source)
        self.assertNotIn("def _persist_demucs", source)
        self.assertNotIn("def apply_stem_selection", source)


class StemSelectionStateRoundTripTests(unittest.TestCase):
    def test_exclusive_focus_survives_side_swap(self) -> None:
        from bundled.constants import INST_STEM, VOCAL_STEM
        from core.settings import Settings
        from core.stem_selection import ExclusiveView, StemSelectionState

        settings = Settings.defaults()
        state = StemSelectionState()
        state.configure_exclusive(
            primary_stem=VOCAL_STEM,
            secondary_stem=INST_STEM,
            primary_key="is_primary_stem_only",
            secondary_key="is_secondary_stem_only",
        )
        state.write(settings, ExclusiveView(choice=INST_STEM))
        self.assertEqual(settings.process.stem_focus, "mix.instrumental")

        state.configure_exclusive(
            primary_stem=INST_STEM,
            secondary_stem=VOCAL_STEM,
            primary_key="is_primary_stem_only",
            secondary_key="is_secondary_stem_only",
        )
        view = state.read(settings)
        assert isinstance(view, ExclusiveView)
        self.assertEqual(view.choice, INST_STEM)

    def test_positional_sentinel_maps_to_primary_route_concept(self) -> None:
        from bundled.constants import INST_STEM, VOCAL_STEM
        from core.settings import Settings
        from core.stem_selection import ExclusiveView, StemSelectionState
        from core.stems import FOCUS_PRIMARY

        settings = Settings.defaults()
        settings.process.stem_focus = FOCUS_PRIMARY
        state = StemSelectionState()
        state.configure_exclusive(
            primary_stem=VOCAL_STEM,
            secondary_stem=INST_STEM,
            primary_key="is_primary_stem_only",
            secondary_key="is_secondary_stem_only",
        )
        view = state.read(settings)
        assert isinstance(view, ExclusiveView)
        self.assertEqual(view.choice, VOCAL_STEM)

    def test_unmatched_focus_parks_and_clears_flags(self) -> None:
        from bundled.constants import INST_STEM
        from core.settings import Settings
        from core.stem_selection import _TOGGLE_ALL, ExclusiveView, StemSelectionState

        settings = Settings.defaults()
        settings.process.stem_focus = INST_STEM
        state = StemSelectionState()
        state.configure_exclusive(
            primary_stem="noreverb",
            secondary_stem="reverb",
            primary_key="is_primary_stem_only",
            secondary_key="is_secondary_stem_only",
        )
        view = state.read(settings)
        assert isinstance(view, ExclusiveView)
        self.assertEqual(view.choice, _TOGGLE_ALL)
        self.assertEqual(settings.process.stem_focus, INST_STEM)

    def test_subset_quick_instrumental_persist(self) -> None:
        from bundled.constants import BASS_STEM, DRUM_STEM, VOCAL_STEM
        from core.settings import Settings
        from core.stem_selection import _QUICK_INSTRUMENTAL, StemSelectionState, SubsetView

        settings = Settings.defaults()
        state = StemSelectionState()
        state.configure_subset(
            stems=[VOCAL_STEM, BASS_STEM, DRUM_STEM],
            primary_key="is_primary_stem_only",
            secondary_key="is_secondary_stem_only",
        )
        state.write(
            settings,
            SubsetView(mode=_QUICK_INSTRUMENTAL, selected=set(), custom_all=False),
        )
        self.assertEqual(settings.mdx.stems_selected, [VOCAL_STEM])
        self.assertEqual(settings.process.stem_focus, "mix.instrumental")

    def test_subset_quick_vocals_persist(self) -> None:
        from bundled.constants import BASS_STEM, VOCAL_STEM
        from core.settings import Settings
        from core.stem_selection import _QUICK_VOCALS, StemSelectionState, SubsetView

        settings = Settings.defaults()
        state = StemSelectionState()
        state.configure_subset(
            stems=[VOCAL_STEM, BASS_STEM],
            primary_key="is_primary_stem_only",
            secondary_key="is_secondary_stem_only",
        )
        state.write(
            settings,
            SubsetView(mode=_QUICK_VOCALS, selected=set(), custom_all=False),
        )
        self.assertEqual(settings.process.stem_focus, "vocal.vocals")

    def test_demucs_all_clears_focus(self) -> None:
        from bundled.constants import ALL_STEMS, BASS_STEM, VOCAL_STEM
        from core.settings import Settings
        from core.stem_selection import (
            _QUICK_ALL,
            _TOGGLE_ALL,
            DemucsView,
            StemSelectionState,
        )

        settings = Settings.defaults()
        settings.process.stem_focus = VOCAL_STEM
        state = StemSelectionState()
        state.configure_demucs(
            focus_stems=[ALL_STEMS, BASS_STEM],
            primary_key="is_primary_stem_only_Demucs",
            secondary_key="is_secondary_stem_only_Demucs",
        )
        state.write(
            settings,
            DemucsView(
                active=_QUICK_ALL,
                export_choice=_TOGGLE_ALL,
                export_filter_visible=False,
            ),
        )
        self.assertEqual(settings.process.stem_focus, "")
        self.assertEqual(settings.demucs.stems, ALL_STEMS)

    def test_demucs_instrumental_quick(self) -> None:
        from bundled.constants import ALL_STEMS, VOCAL_STEM
        from core.settings import Settings
        from core.stem_selection import (
            _FOCUS_INSTRUMENTAL,
            _TOGGLE_ALL,
            DemucsView,
            StemSelectionState,
        )

        settings = Settings.defaults()
        state = StemSelectionState()
        state.configure_demucs(
            focus_stems=[ALL_STEMS, _FOCUS_INSTRUMENTAL],
            primary_key="is_primary_stem_only_Demucs",
            secondary_key="is_secondary_stem_only_Demucs",
        )
        state.write(
            settings,
            DemucsView(
                active=_FOCUS_INSTRUMENTAL,
                export_choice=_TOGGLE_ALL,
                export_filter_visible=False,
            ),
        )
        self.assertEqual(settings.process.stem_focus, "mix.instrumental")
        self.assertEqual(settings.demucs.stems, VOCAL_STEM)


class LegacyStateSemanticPersistenceTests(unittest.TestCase):
    """Identity-less Save Stems state keeps reviewed choices until Task 8."""

    def test_karaoke_bucket_choices_persist_their_distinct_role_ids(self) -> None:
        from core.stem_selection import ExclusiveView, StemSelectionState

        settings = Settings.defaults()
        state = StemSelectionState()
        state.configure_exclusive(
            primary_stem="",
            secondary_stem="",
            primary_key="is_primary_stem_only",
            secondary_key="is_secondary_stem_only",
            stem_pair_id="pair.karaoke",
        )
        for route, expected_role in zip(
            state.routes,
            ("vocal.lead", "mix.instrumental_with_backing_vocals"),
            strict=True,
        ):
            state.write(settings, ExclusiveView(choice=route.concept))
            self.assertEqual(settings.process.stem_focus, expected_role)

    def test_explicit_bv_pair_persists_reviewed_pair_roles(self) -> None:
        from core.stem_selection import ExclusiveView, StemSelectionState

        state = StemSelectionState()
        state.configure_exclusive(
            primary_stem="Backing Vocals",
            secondary_stem="Instrumental With Lead Vocals",
            primary_key="is_primary_stem_only",
            secondary_key="is_secondary_stem_only",
            is_bv=True,
        )
        settings = Settings.defaults()
        for route, expected in zip(
            state.routes,
            ("vocal.backing", "mix.instrumental_with_lead_vocals"),
            strict=True,
        ):
            state.write(settings, ExclusiveView(choice=route.concept))
            self.assertEqual(settings.process.stem_focus, expected)

    def test_exact_instrument_bucket_and_ambiguous_partner_keep_identity(self) -> None:
        from core.stem_selection import ExclusiveView, StemSelectionState
        from core.stems import FOCUS_SECONDARY

        settings = Settings.defaults()
        state = StemSelectionState()
        state.configure_exclusive(
            primary_stem="guitar",
            secondary_stem="noreverb",
            primary_key="is_primary_stem_only",
            secondary_key="is_secondary_stem_only",
        )

        state.write(settings, ExclusiveView(choice=state.routes[0].concept))
        self.assertEqual(settings.process.stem_focus, "instrument.guitar")
        state.write(settings, ExclusiveView(choice=state.routes[1].concept))
        self.assertEqual(settings.process.stem_focus, FOCUS_SECONDARY)

    def test_unknown_identityless_choices_use_positional_focus_not_raw_or_empty(self) -> None:
        from core.stem_selection import ExclusiveView, StemSelectionState
        from core.stems import FOCUS_PRIMARY, FOCUS_SECONDARY

        settings = Settings.defaults()
        state = StemSelectionState()
        state.configure_exclusive(
            primary_stem="Custom A",
            secondary_stem="Custom B",
            primary_key="is_primary_stem_only",
            secondary_key="is_secondary_stem_only",
        )

        state.write(settings, ExclusiveView(choice=state.routes[0].concept))
        self.assertEqual(settings.process.stem_focus, FOCUS_PRIMARY)
        state.write(settings, ExclusiveView(choice=state.routes[1].concept))
        self.assertEqual(settings.process.stem_focus, FOCUS_SECONDARY)

    def test_demucs_no_bass_complement_uses_reviewed_removal_role(self) -> None:
        from bundled.constants import ALL_STEMS, BASS_STEM
        from core.stem_selection import DemucsView, StemSelectionState

        settings = Settings.defaults()
        state = StemSelectionState()
        state.configure_demucs(
            focus_stems=[ALL_STEMS, BASS_STEM],
            primary_key="is_primary_stem_only_Demucs",
            secondary_key="is_secondary_stem_only_Demucs",
            has_model=True,
        )
        state.write(
            settings,
            DemucsView(
                active=BASS_STEM,
                export_choice="raw:no bass",
                export_filter_visible=True,
            ),
        )
        self.assertEqual(settings.process.stem_focus, "instrument.bass.removed")

    def test_reviewed_role_reselects_its_identityless_route(self) -> None:
        from core.stem_selection import ExclusiveView, StemSelectionState

        settings = Settings.defaults()
        state = StemSelectionState()
        state.configure_exclusive(
            primary_stem="noreverb",
            secondary_stem="reverb",
            primary_key="is_primary_stem_only",
            secondary_key="is_secondary_stem_only",
        )
        state.write(settings, ExclusiveView(choice=state.routes[1].concept))
        self.assertEqual(settings.process.stem_focus, "effect.reverb.removed")

        restored = state.read(settings)
        self.assertIsInstance(restored, ExclusiveView)
        assert isinstance(restored, ExclusiveView)
        self.assertEqual(restored.choice, state.routes[1].concept)

    def test_manifest_signature_direction_controls_removal_compatibility(self) -> None:
        from core.model_stem_manifest import resolve_model_stem_semantics
        from core.stem_roles import StemRoleId
        from core.stem_selection import ExclusiveView, StemSelectionState

        cases = (
            (
                "mdx:bs_dereverb_2250_anvuew",
                ["noreverb", "reverb"],
                0,
            ),
            (
                "mdx:MDX23C-De-Reverb-aufr33-jarredou",
                ["dry", "No dry"],
                1,
            ),
        )
        for model_id, stems, index in cases:
            with self.subTest(model_id=model_id, stem=stems[index]):
                expected = resolve_model_stem_semantics(
                    model_id,
                    native_stems=stems,
                )
                expected_role = expected.outputs[index].role
                self.assertIsInstance(expected_role, StemRoleId)
                assert isinstance(expected_role, StemRoleId)
                state = StemSelectionState()
                state.configure_exclusive(
                    primary_stem=stems[0],
                    secondary_stem=stems[1],
                    primary_key="is_primary_stem_only",
                    secondary_key="is_secondary_stem_only",
                )
                settings = Settings.defaults()
                state.write(settings, ExclusiveView(choice=state.routes[index].concept))
                self.assertEqual(settings.process.stem_focus, expected_role.value)

    def test_incomplete_backing_vocal_inventory_uses_positional_focus(self) -> None:
        from core.stem_selection import ExclusiveView, StemSelectionState
        from core.stems import FOCUS_SECONDARY

        state = StemSelectionState()
        state.configure_exclusive(
            primary_stem="vocals",
            secondary_stem="backing_vocal",
            primary_key="is_primary_stem_only",
            secondary_key="is_secondary_stem_only",
        )
        settings = Settings.defaults()
        state.write(settings, ExclusiveView(choice=state.routes[1].concept))
        self.assertEqual(settings.process.stem_focus, FOCUS_SECONDARY)

    def test_complete_backing_vocal_inventory_uses_manifest_role(self) -> None:
        from core.model_stem_manifest import resolve_model_stem_semantics
        from core.stem_roles import StemRoleId
        from core.stem_selection import _SUBSET_CUSTOM, StemSelectionState, SubsetView

        stems = ["vocals", "backing_vocal", "instrumental"]
        state = StemSelectionState()
        state.configure_subset(
            stems=stems,
            primary_key="is_primary_stem_only",
            secondary_key="is_secondary_stem_only",
        )
        route = next(
            route
            for route in state.routes
            if route.native and route.native.matches("backing_vocal")
        )
        settings = Settings.defaults()
        state.write(
            settings,
            SubsetView(mode=_SUBSET_CUSTOM, selected={route.concept}, custom_all=False),
        )
        expected = resolve_model_stem_semantics(
            "mdx:bs_karaoke_3stem_giantailab",
            native_stems=stems,
        )
        expected_output = next(
            output
            for output in expected.outputs
            if output.native and output.native.matches("backing_vocal")
        )
        self.assertIsInstance(expected_output.role, StemRoleId)
        assert isinstance(expected_output.role, StemRoleId)
        self.assertEqual(settings.process.stem_focus, expected_output.role.value)

    def test_signature_compatibility_ignores_derived_routes_but_requires_full_native_inventory(
        self,
    ) -> None:
        from core.model_stem_manifest import load_bundled_stem_semantics
        from core.stem_selection import (
            _SUBSET_CUSTOM,
            StemSelectionState,
            SubsetView,
            _manifest_signature_roles,
        )

        cases = (
            ("mdx:bs_4stem_zfturbo", "other", "residual.other"),
            ("mdx:bs_6stem", "other", "residual.other"),
            ("mdx:bs_mega_53stem_full_mvsep", "accordion", "instrument.accordion"),
        )
        registry = load_bundled_stem_semantics()
        for model_id, target_native, expected_role in cases:
            with self.subTest(model_id=model_id):
                stems = list(registry.models[model_id].native_signature)
                state = StemSelectionState()
                state.configure_subset(
                    stems=stems,
                    primary_key="is_primary_stem_only",
                    secondary_key="is_secondary_stem_only",
                )
                self.assertTrue(
                    any(
                        route.native is None and route.concept == "Instrumental"
                        for route in state.routes
                    )
                )
                route = next(
                    route
                    for route in state.routes
                    if route.native is not None and route.native.matches(target_native)
                )
                settings = Settings.defaults()
                state.write(
                    settings,
                    SubsetView(
                        mode=_SUBSET_CUSTOM,
                        selected={route.concept},
                        custom_all=False,
                    ),
                )
                self.assertEqual(settings.process.stem_focus, expected_role)

                native_routes = tuple(route for route in state.routes if route.native is not None)
                self.assertEqual(_manifest_signature_roles(native_routes[:-1]), {})
                self.assertEqual(
                    _manifest_signature_roles((*native_routes, native_routes[0])),
                    {},
                )

    def test_restore_accepts_only_namespaced_role_or_position(self) -> None:
        from core.stem_selection import _TOGGLE_ALL, ExclusiveView, StemSelectionState

        state = StemSelectionState()
        state.configure_exclusive(
            primary_stem="noreverb",
            secondary_stem="reverb",
            primary_key="is_primary_stem_only",
            secondary_key="is_secondary_stem_only",
        )
        settings = Settings.defaults()
        for invalid_focus in ("Vocals", "raw:noreverb"):
            with self.subTest(focus=invalid_focus):
                settings.process.stem_focus = invalid_focus
                restored = state.read(settings)
                self.assertIsInstance(restored, ExclusiveView)
                assert isinstance(restored, ExclusiveView)
                self.assertEqual(restored.choice, _TOGGLE_ALL)
        settings.process.stem_focus = "effect.reverb"
        restored = state.read(settings)
        self.assertIsInstance(restored, ExclusiveView)
        assert isinstance(restored, ExclusiveView)
        self.assertEqual(restored.choice, state.routes[0].concept)

    def test_legacy_bucket_focus_does_not_activate_subset_or_demucs_quick_state(self) -> None:
        from bundled.constants import ALL_STEMS, BASS_STEM, VOCAL_STEM
        from core.stem_selection import (
            _FOCUS_VOCALS,
            _SUBSET_CUSTOM,
            DemucsView,
            StemSelectionState,
            SubsetView,
        )
        from core.stems import StemBucket

        settings = Settings.defaults()
        settings.mdx.stems_selected = [VOCAL_STEM]
        settings.process.stem_focus = "Vocals"
        subset = StemSelectionState()
        subset.configure_subset(
            stems=[VOCAL_STEM, BASS_STEM],
            primary_key="is_primary_stem_only",
            secondary_key="is_secondary_stem_only",
        )
        subset_view = subset.read(settings)
        self.assertIsInstance(subset_view, SubsetView)
        assert isinstance(subset_view, SubsetView)
        self.assertEqual(subset_view.mode, _SUBSET_CUSTOM)

        settings.demucs.stems = VOCAL_STEM
        demucs = StemSelectionState()
        demucs.configure_demucs(
            focus_stems=[ALL_STEMS, _FOCUS_VOCALS, BASS_STEM],
            primary_key="is_primary_stem_only_Demucs",
            secondary_key="is_secondary_stem_only_Demucs",
        )
        demucs_view = demucs.read(settings)
        self.assertIsInstance(demucs_view, DemucsView)
        assert isinstance(demucs_view, DemucsView)
        self.assertEqual(demucs_view.active, StemBucket.VOCALS.value)


class CliStemSelectionStateTests(unittest.TestCase):
    def _snapshot(self, settings: Settings) -> tuple[object, ...]:
        return (
            settings.process.stem_focus,
            settings.mdx.stems,
            list(settings.mdx.stems_selected or []),
            settings.demucs.stems,
        )

    def test_vocals_matches_write_cli_concept(self) -> None:
        from bundled.constants import ALL_STEMS, VOCAL_STEM
        from core.settings import Settings
        from core.stem_selection import StemSelectionState, apply_stem_selection

        via_apply = Settings.defaults()
        via_state = Settings.defaults()
        self.assertEqual(apply_stem_selection(via_apply, "vocals"), "vocals")
        StemSelectionState().write_cli_concept(via_state, "vocal.vocals")
        self.assertEqual(self._snapshot(via_apply), self._snapshot(via_state))
        self.assertEqual(via_apply.process.stem_focus, "vocal.vocals")
        self.assertEqual(via_apply.mdx.stems_selected, [VOCAL_STEM])
        self.assertEqual(via_apply.demucs.stems, VOCAL_STEM)
        self.assertNotEqual(via_apply.mdx.stems, ALL_STEMS)

    def test_vocal_alias_resolves_through_select_stem_routes(self) -> None:
        from core.settings import Settings
        from core.stem_selection import StemSelectionState, apply_stem_selection

        settings = Settings.defaults()
        self.assertEqual(apply_stem_selection(settings, "vocal"), "vocals")
        self.assertEqual(settings.process.stem_focus, "vocal.vocals")
        via_state = Settings.defaults()
        StemSelectionState().write_cli_concept(via_state, "vocal.vocals")
        self.assertEqual(via_state.process.stem_focus, "vocal.vocals")

    def test_primary_writes_sentinel_without_vocals_bucket(self) -> None:
        from bundled.constants import VOCAL_STEM
        from core.settings import Settings
        from core.stem_selection import StemSelectionState, apply_stem_selection
        from core.stems import FOCUS_PRIMARY, StemBucket

        settings = Settings.defaults()
        settings.process.stem_focus = StemBucket.VOCALS.value
        self.assertEqual(apply_stem_selection(settings, "primary"), "primary")
        self.assertEqual(settings.process.stem_focus, FOCUS_PRIMARY)
        self.assertNotEqual(settings.process.stem_focus, VOCAL_STEM)

        via_state = Settings.defaults()
        via_state.process.stem_focus = StemBucket.VOCALS.value
        StemSelectionState().write_cli_positional(via_state, "primary")
        self.assertEqual(self._snapshot(settings), self._snapshot(via_state))


class SubsetConceptSelectionTests(unittest.TestCase):
    def test_custom_bass_roundtrip_uses_concept_and_native_sidecar(self) -> None:
        from bundled.constants import BASS_STEM, DRUM_STEM, VOCAL_STEM
        from core.settings import Settings
        from core.stem_selection import _SUBSET_CUSTOM, StemSelectionState, SubsetView
        from core.stems import StemBucket

        settings = Settings.defaults()
        state = StemSelectionState()
        state.configure_subset(
            stems=[VOCAL_STEM, BASS_STEM, DRUM_STEM],
            primary_key="is_primary_stem_only",
            secondary_key="is_secondary_stem_only",
        )
        state.write(
            settings,
            SubsetView(
                mode=_SUBSET_CUSTOM,
                selected={StemBucket.BASS.value},
                custom_all=False,
            ),
        )
        self.assertEqual(settings.mdx.stems_selected, [BASS_STEM])
        self.assertEqual(settings.process.stem_focus, "instrument.bass")

        view = state.read(settings)
        assert isinstance(view, SubsetView)
        self.assertEqual(view.mode, _SUBSET_CUSTOM)
        self.assertEqual(view.selected, {StemBucket.BASS.value})

    def test_yaml_vocals_maps_through_select_stem_routes(self) -> None:
        from bundled.constants import BASS_STEM, DRUM_STEM
        from core.settings import Settings
        from core.stem_selection import _SUBSET_CUSTOM, StemSelectionState, SubsetView
        from core.stems import StemBucket

        settings = Settings.defaults()
        state = StemSelectionState()
        state.configure_subset(
            stems=["vocals", BASS_STEM, DRUM_STEM],
            primary_key="is_primary_stem_only",
            secondary_key="is_secondary_stem_only",
        )
        state.write(
            settings,
            SubsetView(
                mode=_SUBSET_CUSTOM,
                selected={"vocals"},
                custom_all=False,
            ),
        )
        self.assertEqual(settings.mdx.stems_selected, ["vocals"])
        self.assertEqual(settings.process.stem_focus, "vocal.vocals")

        view = state.read(settings)
        assert isinstance(view, SubsetView)
        self.assertEqual(view.selected, {StemBucket.VOCALS.value})

    def test_quick_vocals_keeps_gtk_flags_not_cli_concept_table(self) -> None:
        from bundled.constants import BASS_STEM, VOCAL_STEM
        from core.settings import Settings
        from core.stem_selection import _QUICK_VOCALS, StemSelectionState, SubsetView

        settings = Settings.defaults()
        state = StemSelectionState()
        state.configure_subset(
            stems=[VOCAL_STEM, BASS_STEM],
            primary_key="is_primary_stem_only",
            secondary_key="is_secondary_stem_only",
        )
        state.write(
            settings,
            SubsetView(mode=_QUICK_VOCALS, selected=set(), custom_all=False),
        )
        self.assertEqual(settings.process.stem_focus, "vocal.vocals")
        self.assertEqual(settings.mdx.stems_selected, [VOCAL_STEM])


class DemucsConceptSelectionTests(unittest.TestCase):
    def test_native_bass_roundtrip_uses_concept_and_native_sidecar(self) -> None:
        from bundled.constants import ALL_STEMS, BASS_STEM
        from core.settings import Settings
        from core.stem_selection import DemucsView, StemSelectionState
        from core.stems import StemBucket

        settings = Settings.defaults()
        state = StemSelectionState()
        state.configure_demucs(
            focus_stems=[ALL_STEMS, BASS_STEM],
            primary_key="is_primary_stem_only_Demucs",
            secondary_key="is_secondary_stem_only_Demucs",
        )
        state.write(
            settings,
            DemucsView(
                active=StemBucket.BASS.value,
                export_choice=StemBucket.BASS.value,
                export_filter_visible=True,
            ),
        )
        self.assertEqual(settings.demucs.stems, BASS_STEM)
        self.assertEqual(settings.process.stem_focus, "instrument.bass")

        view = state.read(settings)
        assert isinstance(view, DemucsView)
        self.assertEqual(view.active, StemBucket.BASS.value)
        self.assertEqual(view.export_choice, StemBucket.BASS.value)

    def test_namespaced_vocals_focus_is_focus_vocals(self) -> None:
        from bundled.constants import ALL_STEMS, BASS_STEM
        from core.settings import Settings
        from core.stem_selection import (
            _FOCUS_VOCALS,
            DemucsView,
            StemSelectionState,
        )

        settings = Settings.defaults()
        settings.demucs.stems = "vocals"
        settings.process.stem_focus = "vocal.vocals"
        state = StemSelectionState()
        state.configure_demucs(
            focus_stems=[ALL_STEMS, _FOCUS_VOCALS, BASS_STEM],
            primary_key="is_primary_stem_only_Demucs",
            secondary_key="is_secondary_stem_only_Demucs",
        )
        view = state.read(settings)
        assert isinstance(view, DemucsView)
        self.assertEqual(view.active, _FOCUS_VOCALS)


if __name__ == "__main__":
    unittest.main()
