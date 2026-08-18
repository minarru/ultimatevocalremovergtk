"""Boundary tests for the extracted Save Stems state module."""

from __future__ import annotations

import unittest
from pathlib import Path

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
        state.write(settings, ExclusiveView(choice="is_secondary_stem_only"))
        self.assertEqual(settings.process.stem_focus, INST_STEM)

        state.configure_exclusive(
            primary_stem=INST_STEM,
            secondary_stem=VOCAL_STEM,
            primary_key="is_primary_stem_only",
            secondary_key="is_secondary_stem_only",
        )
        view = state.read(settings)
        assert isinstance(view, ExclusiveView)
        self.assertEqual(view.choice, "is_primary_stem_only")
        self.assertTrue(settings.process.primary_stem_only)
        self.assertFalse(settings.process.secondary_stem_only)

    def test_empty_focus_uses_legacy_booleans(self) -> None:
        from bundled.constants import INST_STEM, VOCAL_STEM
        from core.settings import Settings
        from core.stem_selection import ExclusiveView, StemSelectionState

        settings = Settings.defaults()
        settings.process.primary_stem_only = True
        state = StemSelectionState()
        state.configure_exclusive(
            primary_stem=VOCAL_STEM,
            secondary_stem=INST_STEM,
            primary_key="is_primary_stem_only",
            secondary_key="is_secondary_stem_only",
        )
        view = state.read(settings)
        assert isinstance(view, ExclusiveView)
        self.assertEqual(view.choice, "is_primary_stem_only")

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
        self.assertTrue(settings.process.secondary_stem_only)
        self.assertFalse(settings.process.primary_stem_only)

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
        self.assertTrue(settings.process.primary_stem_only)

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
        self.assertTrue(settings.demucs.is_secondary_stem_only)


if __name__ == "__main__":
    unittest.main()
