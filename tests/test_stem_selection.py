"""CLI stem selection writes process.stem_focus; assemble matches by concept."""

from __future__ import annotations

import unittest

from bundled.constants import ALL_STEMS, BASS_STEM, INST_STEM, VOCAL_STEM
from cli.job import _resolved_settings
from core.settings import Settings
from core.stem_selection import apply_stem_selection
from core.stems import StemBucket, exclusive_flags_for_focus


class ApplyStemSelectionTests(unittest.TestCase):
    def test_vocals_writes_namespaced_role_not_primary_only(self) -> None:
        settings = Settings.defaults()
        self.assertEqual(apply_stem_selection(settings, "vocals"), "vocals")
        self.assertEqual(settings.process.stem_focus, "vocal.vocals")
        flags = exclusive_flags_for_focus(
            settings.process.stem_focus,
            primary_stem="other",
            secondary_stem="vocals",
            stem_count=2,
        )
        self.assertEqual(flags, (False, True))

    def test_instrumental_writes_namespaced_role(self) -> None:
        settings = Settings.defaults()
        apply_stem_selection(settings, "instrumental")
        self.assertEqual(settings.process.stem_focus, "mix.instrumental")

    def test_primary_writes_positional_sentinel(self) -> None:
        from core.stems import FOCUS_PRIMARY

        settings = Settings.defaults()
        settings.process.stem_focus = StemBucket.VOCALS.value
        apply_stem_selection(settings, "primary")
        self.assertEqual(settings.process.stem_focus, FOCUS_PRIMARY)

    def test_both_clears_focus(self) -> None:
        settings = Settings.defaults()
        settings.process.stem_focus = StemBucket.VOCALS.value
        apply_stem_selection(settings, "both")
        self.assertEqual(settings.process.stem_focus, "")
        self.assertEqual(settings.mdx.stems, ALL_STEMS)

    def test_bass_writes_focus(self) -> None:
        settings = Settings.defaults()
        apply_stem_selection(settings, "bass")
        self.assertEqual(settings.process.stem_focus, "instrument.bass")
        self.assertEqual(settings.demucs.stems, BASS_STEM)

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

    def test_positional_sentinel_is_silent(self) -> None:
        from core.stems import FOCUS_PRIMARY, FOCUS_SECONDARY

        self.assertEqual(
            self._diagnose(FOCUS_PRIMARY, _StubModel("vocals", "other")), []
        )
        self.assertEqual(
            self._diagnose(FOCUS_SECONDARY, _StubModel("vocals", "other")), []
        )

    def test_vocal_splitters_are_exempt(self) -> None:
        model = _StubModel("vocals", "other")
        model.is_vocal_split_model = True
        self.assertEqual(self._diagnose(BASS_STEM, model), [])

    def test_cli_unmatched_focus_is_error_but_inherited_is_warning(self) -> None:
        from core.job_plan import ModelDescriptor, _stem_focus_diagnostics

        settings = Settings.defaults()
        settings.process.stem_focus = BASS_STEM
        model = _StubModel("vocals", "other")
        descriptor = ModelDescriptor("stub", "mdx", "stub", "Stub Model")
        explicit = _stem_focus_diagnostics(
            settings,
            [model],
            [descriptor],
            {"process.stem_focus": "cli"},
        )
        inherited = _stem_focus_diagnostics(
            settings,
            [model],
            [descriptor],
            {"process.stem_focus": "gui"},
        )
        self.assertEqual(explicit[0].severity, "error")
        self.assertEqual(inherited[0].severity, "warning")


class StemSelectionProvenanceTests(unittest.TestCase):
    def test_resolved_settings_records_stem_focus(self) -> None:
        settings, sources = _resolved_settings(
            Settings.defaults(),
            output="/tmp/out",
            method="mdx",
            stems="vocals",
        )
        self.assertEqual(settings.process.stem_focus, "vocal.vocals")
        self.assertEqual(sources["process.stem_focus"], "cli")

    def test_one_settings_object_keeps_its_bytes_while_two_configs_resolve_roles(self) -> None:
        from core.model_config.config import ModelConfig

        def config(model_id: str, natives: list[str], primary: str) -> ModelConfig:
            assembled = ModelConfig.__new__(ModelConfig)
            assembled.settings = settings
            assembled.canonical_id = model_id
            assembled.stem_semantics = None
            assembled.primary_stem = primary
            assembled.primary_stem_native = primary
            assembled.secondary_stem = ""
            assembled.mdx_model_stems = natives
            assembled.demucs_source_list = []
            assembled.mdx_stem_count = len(natives)
            assembled.demucs_stem_count = 0
            assembled.is_vocal_split_model = False
            assembled.is_ensemble_mode = False
            assembled.is_karaoke = False
            assembled.is_bv_model = False
            return assembled

        settings = Settings.defaults()
        settings.process.stem_focus = "primary"
        before = settings.to_json_dict()
        reverse = config(
            "demucs:UVR_Demucs_Model_1", ["Vocals", "Instrumental"], "Vocals"
        )
        ordinary = config("mdx:MDX23C_D1581", ["Instrumental", "Vocals"], "Vocals")

        ModelConfig._apply_stem_focus(reverse)
        ModelConfig._apply_stem_focus(ordinary)

        self.assertEqual(reverse.selected_stem_routes[0].concept, "mix.instrumental")
        self.assertEqual(ordinary.selected_stem_routes[0].concept, "vocal.vocals")
        self.assertEqual(settings.to_json_dict(), before)

    def test_explicit_role_focus_honors_ordinary_model_without_reordering_native_keys(self) -> None:
        from core.model_config.config import ModelConfig

        settings = Settings.defaults()
        settings.process.stem_focus = "mix.instrumental"
        model = ModelConfig.__new__(ModelConfig)
        model.settings = settings
        model.canonical_id = "mdx:MDX23C_D1581"
        model.stem_semantics = None
        model.primary_stem = model.primary_stem_native = "Vocals"
        model.secondary_stem = "Instrumental"
        model.mdx_model_stems = ["Instrumental", "Vocals"]
        model.demucs_source_list = []
        model.mdx_stem_count = 2
        model.demucs_stem_count = 0
        model.is_vocal_split_model = model.is_ensemble_mode = False
        model.is_karaoke = model.is_bv_model = False

        ModelConfig._apply_stem_focus(model)

        self.assertEqual(
            [
                route.native.raw if route.native is not None else ""
                for route in model.available_stem_routes
            ],
            ["Vocals", "Instrumental"],
        )
        self.assertEqual(model.selected_stem_routes[0].concept, "mix.instrumental")
