"""CLI stem selection writes process.stem_focus; assemble matches by concept."""

from __future__ import annotations

import unittest

from bundled.constants import ALL_STEMS, BASS_STEM, INST_STEM, VOCAL_STEM
from core.settings import Settings
from core.settings.job_resolution import apply_stem_selection
from core.stems import StemBucket, exclusive_flags_for_focus
from cli.job import _resolved_settings


class ApplyStemSelectionTests(unittest.TestCase):
    def test_vocals_writes_vocals_bucket_not_primary_only(self) -> None:
        settings = Settings.defaults()
        self.assertEqual(apply_stem_selection(settings, "vocals"), "vocals")
        self.assertEqual(settings.process.stem_focus, StemBucket.VOCALS.value)
        self.assertFalse(settings.process.primary_stem_only)
        self.assertFalse(settings.process.secondary_stem_only)
        flags = exclusive_flags_for_focus(
            settings.process.stem_focus,
            primary_stem="other",
            secondary_stem="vocals",
            stem_count=2,
        )
        self.assertEqual(flags, (False, True))

    def test_instrumental_writes_instrumental_bucket(self) -> None:
        settings = Settings.defaults()
        apply_stem_selection(settings, "instrumental")
        self.assertEqual(settings.process.stem_focus, StemBucket.INSTRUMENTAL.value)
        self.assertFalse(settings.process.primary_stem_only)

    def test_primary_clears_focus(self) -> None:
        settings = Settings.defaults()
        settings.process.stem_focus = StemBucket.VOCALS.value
        apply_stem_selection(settings, "primary")
        self.assertEqual(settings.process.stem_focus, "")
        self.assertTrue(settings.process.primary_stem_only)
        self.assertFalse(settings.process.secondary_stem_only)

    def test_both_clears_focus(self) -> None:
        settings = Settings.defaults()
        settings.process.stem_focus = StemBucket.VOCALS.value
        apply_stem_selection(settings, "both")
        self.assertEqual(settings.process.stem_focus, "")
        self.assertEqual(settings.mdx.stems, ALL_STEMS)

    def test_bass_writes_focus(self) -> None:
        settings = Settings.defaults()
        apply_stem_selection(settings, "bass")
        self.assertEqual(settings.process.stem_focus, BASS_STEM)
        self.assertEqual(settings.demucs.stems, BASS_STEM)
        self.assertFalse(settings.process.primary_stem_only)

    def test_inherited_lowercase_mdx_stems_match_vocals_concept(self) -> None:
        settings = Settings.defaults()
        settings.mdx.stems = "vocals"
        settings.mdx.stems_selected = ["vocals"]
        settings.process.stem_focus = ""
        flags = exclusive_flags_for_focus(
            VOCAL_STEM,
            primary_stem="vocals",
            secondary_stem="other",
            stem_count=2,
        )
        self.assertEqual(flags, (True, False))
        from core.stems import concept_is

        self.assertTrue(concept_is(settings.mdx.stems, StemBucket.VOCALS, stem_count=2))
        self.assertNotEqual(settings.mdx.stems, INST_STEM)


class _StubModel:
    is_vocal_split_model = False
    is_karaoke = False
    is_bv_model = False
    demucs_stem_count = 0
    demucs_source_list: list[str] = []
    model_basename = "stub"

    def __init__(self, primary: str, secondary: str) -> None:
        self.primary_stem = primary
        self.secondary_stem = secondary
        self.mdx_model_stems = [primary, secondary]
        self.mdx_stem_count = 2


class UnmatchedFocusDiagnosticTests(unittest.TestCase):
    """An unhonorable focus falls back to exporting everything; say so up front."""

    def _diagnose(self, focus: str, model: _StubModel) -> list[str]:
        from core.job_plan import ModelDescriptor, _stem_focus_diagnostics

        settings = Settings.defaults()
        settings.process.stem_focus = focus
        descriptor = ModelDescriptor("stub", "mdx", "stub", "Stub Model")
        return [
            item.message
            for item in _stem_focus_diagnostics(settings, [model], [descriptor])
        ]

    def test_focus_on_a_stem_the_model_lacks_is_reported(self) -> None:
        messages = self._diagnose(BASS_STEM, _StubModel("vocals", "other"))
        self.assertEqual(len(messages), 1)
        self.assertIn("Bass", messages[0])
        self.assertIn("Stub Model", messages[0])
        self.assertIn("exporting all stems", messages[0])

    def test_matching_focus_is_silent(self) -> None:
        self.assertEqual(self._diagnose(VOCAL_STEM, _StubModel("vocals", "other")), [])
        self.assertEqual(self._diagnose(INST_STEM, _StubModel("vocals", "other")), [])

    def test_empty_focus_is_silent(self) -> None:
        self.assertEqual(self._diagnose("", _StubModel("vocals", "other")), [])

    def test_vocal_splitters_are_exempt(self) -> None:
        model = _StubModel("vocals", "other")
        model.is_vocal_split_model = True
        self.assertEqual(self._diagnose(BASS_STEM, model), [])


class StemSelectionProvenanceTests(unittest.TestCase):
    def test_resolved_settings_records_stem_focus(self) -> None:
        settings, sources = _resolved_settings(
            Settings.defaults(),
            output="/tmp/out",
            method="mdx",
            stems="vocals",
        )
        self.assertEqual(settings.process.stem_focus, StemBucket.VOCALS.value)
        self.assertEqual(sources["process.stem_focus"], "cli")
