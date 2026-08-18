"""Boundary tests for the extracted Save Stems state module."""

from __future__ import annotations

import unittest
from pathlib import Path

from core.settings import Settings

_REPO = Path(__file__).resolve().parents[1]
_STATE = _REPO / "core" / "stem_selection.py"
_JOB_RESOLUTION = _REPO / "core" / "settings" / "job_resolution.py"
_STEM_ONLY = _REPO / "ui" / "widgets" / "stem_only.py"


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
        self.assertEqual(settings.process.stem_focus, INST_STEM)

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
        from core.stem_selection import ExclusiveView, StemSelectionState, _TOGGLE_ALL

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
        from core.stem_selection import StemSelectionState, SubsetView, _QUICK_INSTRUMENTAL
        from core.stems import StemBucket as Bucket

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
        self.assertEqual(settings.process.stem_focus, Bucket.INSTRUMENTAL.value)

    def test_subset_quick_vocals_persist(self) -> None:
        from bundled.constants import BASS_STEM, VOCAL_STEM
        from core.settings import Settings
        from core.stem_selection import StemSelectionState, SubsetView, _QUICK_VOCALS
        from core.stems import StemBucket

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
        self.assertEqual(settings.process.stem_focus, StemBucket.VOCALS.value)

    def test_demucs_all_clears_focus(self) -> None:
        from bundled.constants import ALL_STEMS, BASS_STEM, VOCAL_STEM
        from core.settings import Settings
        from core.stem_selection import (
            DemucsView,
            StemSelectionState,
            _QUICK_ALL,
            _TOGGLE_ALL,
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
            DemucsView,
            StemSelectionState,
            _FOCUS_INSTRUMENTAL,
            _TOGGLE_ALL,
        )
        from core.stems import StemBucket

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
        self.assertEqual(settings.process.stem_focus, StemBucket.INSTRUMENTAL.value)
        self.assertEqual(settings.demucs.stems, VOCAL_STEM)


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
        from core.stems import StemBucket

        via_apply = Settings.defaults()
        via_state = Settings.defaults()
        self.assertEqual(apply_stem_selection(via_apply, "vocals"), "vocals")
        StemSelectionState().write_cli_concept(via_state, StemBucket.VOCALS.value)
        self.assertEqual(self._snapshot(via_apply), self._snapshot(via_state))
        self.assertEqual(via_apply.process.stem_focus, StemBucket.VOCALS.value)
        self.assertEqual(via_apply.mdx.stems_selected, [VOCAL_STEM])
        self.assertEqual(via_apply.demucs.stems, VOCAL_STEM)
        self.assertNotEqual(via_apply.mdx.stems, ALL_STEMS)

    def test_vocal_alias_resolves_through_select_stem_routes(self) -> None:
        from core.settings import Settings
        from core.stem_selection import StemSelectionState, apply_stem_selection
        from core.stems import StemBucket

        settings = Settings.defaults()
        self.assertEqual(apply_stem_selection(settings, "vocal"), "vocals")
        self.assertEqual(settings.process.stem_focus, StemBucket.VOCALS.value)
        via_state = Settings.defaults()
        StemSelectionState().write_cli_concept(via_state, "vocal")
        self.assertEqual(via_state.process.stem_focus, StemBucket.VOCALS.value)

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
        from core.stem_selection import StemSelectionState, SubsetView, _SUBSET_CUSTOM
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
        self.assertEqual(settings.process.stem_focus, StemBucket.BASS.value)

        view = state.read(settings)
        assert isinstance(view, SubsetView)
        self.assertEqual(view.mode, _SUBSET_CUSTOM)
        self.assertEqual(view.selected, {StemBucket.BASS.value})

    def test_yaml_vocals_maps_through_select_stem_routes(self) -> None:
        from bundled.constants import BASS_STEM, DRUM_STEM
        from core.settings import Settings
        from core.stem_selection import StemSelectionState, SubsetView, _SUBSET_CUSTOM
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
        self.assertEqual(settings.process.stem_focus, StemBucket.VOCALS.value)

        view = state.read(settings)
        assert isinstance(view, SubsetView)
        self.assertEqual(view.selected, {StemBucket.VOCALS.value})

    def test_quick_vocals_keeps_gtk_flags_not_cli_concept_table(self) -> None:
        from bundled.constants import BASS_STEM, VOCAL_STEM
        from core.settings import Settings
        from core.stem_selection import StemSelectionState, SubsetView, _QUICK_VOCALS
        from core.stems import StemBucket

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
        self.assertEqual(settings.process.stem_focus, StemBucket.VOCALS.value)
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
        self.assertEqual(settings.process.stem_focus, StemBucket.BASS.value)

        view = state.read(settings)
        assert isinstance(view, DemucsView)
        self.assertEqual(view.active, StemBucket.BASS.value)
        self.assertEqual(view.export_choice, StemBucket.BASS.value)

    def test_lowercase_vocals_plus_vocals_focus_is_focus_vocals(self) -> None:
        from bundled.constants import ALL_STEMS, BASS_STEM
        from core.settings import Settings
        from core.stem_selection import (
            DemucsView,
            StemSelectionState,
            _FOCUS_VOCALS,
        )
        from core.stems import StemBucket

        settings = Settings.defaults()
        settings.demucs.stems = "vocals"
        settings.process.stem_focus = StemBucket.VOCALS.value
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
