import unittest
from unittest.mock import MagicMock

from bundled.constants import (
    ALL_STEMS,
    BASS_STEM,
    DRUM_STEM,
    INST_STEM,
    PRIMARY_STEM,
    SECONDARY_STEM,
    VOCAL_STEM,
)
from core.settings import Settings
from ui.widgets.stem_only import (
    SaveStemsSection,
    _QUICK_ALL,
    _QUICK_INSTRUMENTAL,
    _QUICK_VOCALS,
    _TOGGLE_ALL,
    _LEAD_VOCAL_PAIR_LABELS,
    build_stem_only_options,
    canonical_stem_name,
    roformer_lead_vocal_label_overrides,
    stem_display_label,
)


class _Settings(Settings):
    def __init__(self, data=None):
        super().__init__()
        self.update(data or {})

    def __getitem__(self, key):
        return self.get(key)

    def __setitem__(self, key, value):
        self.set(key, value)


class StemDisplayLabelTests(unittest.TestCase):
    def test_lowercase_aliases_normalize(self):
        self.assertEqual(canonical_stem_name("other"), "Other")
        self.assertEqual(canonical_stem_name("vocals"), "Vocals")
        self.assertEqual(canonical_stem_name("drums"), "Drums")

    def test_complement_stems_use_friendly_labels(self):
        self.assertEqual(stem_display_label("other"), "Other")
        self.assertEqual(stem_display_label("No other"), "Mix minus Other")
        self.assertEqual(stem_display_label("No Vocals"), "Instrumental")
        self.assertEqual(stem_display_label("No vocals"), "Instrumental")

    def test_build_stem_only_options_use_display_labels(self):
        options = build_stem_only_options(
            primary_stem="other",
            secondary_stem="No other",
            primary_key="is_primary_stem_only",
            secondary_key="is_secondary_stem_only",
        )
        labels = [option.display_label for option in options if option.settings_key]
        self.assertEqual(labels, ["Other", "Mix minus Other"])

    def test_roformer_other_pair_uses_vocals_instrumental_labels(self):
        overrides = dict(_LEAD_VOCAL_PAIR_LABELS)
        self.assertEqual(stem_display_label("other", overrides=overrides), INST_STEM)
        self.assertEqual(stem_display_label("No other", overrides=overrides), VOCAL_STEM)
        options = build_stem_only_options(
            primary_stem="other",
            secondary_stem="No other",
            primary_key="is_primary_stem_only",
            secondary_key="is_secondary_stem_only",
            stem_label_overrides=overrides,
        )
        labels = [option.display_label for option in options if option.settings_key]
        self.assertEqual(labels, [VOCAL_STEM, INST_STEM])

    def test_roformer_vocals_other_overrides_only_for_two_stem_models(self):
        class _Training:
            instruments = ["other", "vocals"]

        class _Config:
            training = _Training()

        class _Model:
            is_roformer = True
            mdx_c_configs = _Config()

        self.assertEqual(roformer_lead_vocal_label_overrides(_Model()), _LEAD_VOCAL_PAIR_LABELS)
        self.assertIsNone(roformer_lead_vocal_label_overrides(None))

    def test_vocals_other_overrides_skipped_for_multi_stem_models(self):
        class _Training:
            instruments = ["other", "vocals", "drums", "bass"]

        class _Config:
            training = _Training()

        class _Model:
            is_roformer = True
            mdx_c_configs = _Config()

        self.assertIsNone(roformer_lead_vocal_label_overrides(_Model()))


class BuildStemOnlyOptionsTests(unittest.TestCase):
    def test_all_stems_is_first_option(self):
        options = build_stem_only_options(
            primary_stem=VOCAL_STEM,
            secondary_stem=INST_STEM,
            primary_key="is_primary_stem_only",
            secondary_key="is_secondary_stem_only",
        )
        self.assertEqual(options[0].name, _TOGGLE_ALL)
        self.assertIsNone(options[0].settings_key)

    def test_named_stems_use_settings_keys(self):
        options = build_stem_only_options(
            primary_stem=VOCAL_STEM,
            secondary_stem=INST_STEM,
            primary_key="is_primary_stem_only",
            secondary_key="is_secondary_stem_only",
        )
        keys = {option.settings_key for option in options if option.settings_key}
        self.assertEqual(keys, {"is_primary_stem_only", "is_secondary_stem_only"})

    def test_fallback_primary_secondary_labels(self):
        options = build_stem_only_options(
            primary_stem=None,
            secondary_stem=None,
            primary_key="is_primary_stem_only",
            secondary_key="is_secondary_stem_only",
        )
        labels = [option.display_label for option in options]
        self.assertIn(PRIMARY_STEM, labels)
        self.assertIn(SECONDARY_STEM, labels)


class SaveStemsSectionTests(unittest.TestCase):
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

    def test_hidden_without_model(self):
        self.section.configure_hidden(has_model=False)
        self.assertEqual(self.section.export_summary(), "Choose a model to configure stem export")
        self.assertFalse(self.section._section_visible)
        self.assertFalse(self.section._exclusive_row.get_visible())

    def test_exclusive_sync_persist_round_trip(self):
        self.settings["is_primary_stem_only"] = True
        self.section.configure_exclusive(
            primary_stem=VOCAL_STEM,
            secondary_stem=INST_STEM,
            primary_key="is_primary_stem_only",
            secondary_key="is_secondary_stem_only",
            has_model=True,
        )
        self.section.sync_from_settings()
        self.assertIn("Vocals", self.section.export_summary())
        self.section.persist_to_settings()
        self.assertTrue(self.settings["is_primary_stem_only"])
        self.assertFalse(self.settings["is_secondary_stem_only"])

    def test_subset_quick_instrumental_persist(self):
        self.settings["is_secondary_stem_only"] = True
        self.settings["mdx_stems_selected"] = [VOCAL_STEM]
        self.section.configure_subset(
            stems=[VOCAL_STEM, BASS_STEM, DRUM_STEM],
            show_quick_export=True,
            primary_key="is_primary_stem_only",
            secondary_key="is_secondary_stem_only",
            has_model=True,
        )
        self.section.sync_from_settings()
        self.assertEqual(self.section._subset_mode, _QUICK_INSTRUMENTAL)
        self.assertFalse(self.section._subset._chips[VOCAL_STEM].get_active())
        self.assertFalse(self.section._subset.is_all_active())
        self.section.persist_to_settings()
        self.assertEqual(self.settings["mdx_stems_selected"], [VOCAL_STEM])
        self.assertTrue(self.settings["is_secondary_stem_only"])
        self.assertFalse(self.settings["is_primary_stem_only"])

    def test_subset_quick_vocals_highlights_vocal_chip(self):
        self.settings["is_primary_stem_only"] = True
        self.settings["mdx_stems_selected"] = [VOCAL_STEM]
        self.section.configure_subset(
            stems=[VOCAL_STEM, BASS_STEM, DRUM_STEM],
            show_quick_export=True,
            primary_key="is_primary_stem_only",
            secondary_key="is_secondary_stem_only",
            has_model=True,
        )
        self.section.sync_from_settings()
        self.assertEqual(self.section._subset_mode, _QUICK_VOCALS)
        self.assertTrue(self.section._subset._chips[VOCAL_STEM].get_active())

    def test_subset_quick_instrumental_ui_clears_chips(self):
        self.section.configure_subset(
            stems=[VOCAL_STEM, BASS_STEM, DRUM_STEM],
            show_quick_export=True,
            primary_key="is_primary_stem_only",
            secondary_key="is_secondary_stem_only",
            has_model=True,
        )
        self.section._quick_export.set_active(_QUICK_INSTRUMENTAL)
        self.section._on_quick_export_changed()
        self.assertFalse(self.section._subset._chips[VOCAL_STEM].get_active())
        self.assertFalse(self.section._subset.is_all_active())

    def test_subset_custom_single_stem_persist(self):
        self.section.configure_subset(
            stems=[VOCAL_STEM, BASS_STEM, DRUM_STEM],
            show_quick_export=True,
            primary_key="is_primary_stem_only",
            secondary_key="is_secondary_stem_only",
            has_model=True,
        )
        self.section._subset_mode = "custom"
        self.section._subset.rebuild([VOCAL_STEM, BASS_STEM, DRUM_STEM])
        self.section._subset.set_selection({BASS_STEM}, full_stems=[VOCAL_STEM, BASS_STEM, DRUM_STEM])
        self.section.persist_to_settings()
        self.assertEqual(self.settings["mdx_stems_selected"], [BASS_STEM])
        self.assertEqual(self.settings["mdx_stems"], BASS_STEM)
        self.assertFalse(self.settings["is_primary_stem_only"])
        self.assertFalse(self.settings["is_secondary_stem_only"])

    def test_subset_all_stems_persist(self):
        self.section.configure_subset(
            stems=[VOCAL_STEM, BASS_STEM],
            show_quick_export=True,
            primary_key="is_primary_stem_only",
            secondary_key="is_secondary_stem_only",
            has_model=True,
        )
        self.section._subset_mode = _QUICK_ALL
        self.section.persist_to_settings()
        self.assertEqual(self.settings["mdx_stems"], ALL_STEMS)
        self.assertEqual(self.settings["mdx_stems_selected"], [])

    def test_demucs_all_stems_hides_export_filter(self):
        self.settings["demucs_stems"] = ALL_STEMS
        self.section.configure_demucs(
            focus_stems=[ALL_STEMS, "focus_instrumental", "focus_vocals", BASS_STEM],
            primary_key="is_primary_stem_only_Demucs",
            secondary_key="is_secondary_stem_only_Demucs",
            has_model=True,
        )
        self.section.sync_from_settings()
        self.assertFalse(self.section._demucs_export_block.get_visible())

    def test_demucs_bass_focus_defaults_primary_only(self):
        self.section.configure_demucs(
            focus_stems=[ALL_STEMS, BASS_STEM],
            primary_key="is_primary_stem_only_Demucs",
            secondary_key="is_secondary_stem_only_Demucs",
            has_model=True,
        )
        self.section._demucs_focus.set_active_name(BASS_STEM)
        self.section._on_demucs_focus_changed()
        self.section.persist_to_settings()
        self.assertEqual(self.settings["demucs_stems"], BASS_STEM)
        self.assertTrue(self.settings["is_primary_stem_only_Demucs"])
        self.assertFalse(self.settings["is_secondary_stem_only_Demucs"])

    def test_subset_hides_quick_export_when_disabled(self):
        self.section.configure_subset(
            stems=[VOCAL_STEM, BASS_STEM, DRUM_STEM],
            show_quick_export=False,
            primary_key="is_primary_stem_only",
            secondary_key="is_secondary_stem_only",
            has_model=True,
        )
        self.assertFalse(self.section._quick_block.get_visible())
        self.assertTrue(self.section._subset_block.get_visible())

    def test_mode_switch_hides_rows(self):
        self.section.configure_subset(
            stems=[VOCAL_STEM, BASS_STEM],
            show_quick_export=True,
            primary_key="is_primary_stem_only",
            secondary_key="is_secondary_stem_only",
            has_model=True,
        )
        self.assertTrue(self.section._subset_block.get_visible())
        self.assertFalse(self.section._exclusive_block.get_visible())
        self.section.configure_exclusive(
            primary_stem=VOCAL_STEM,
            secondary_stem=INST_STEM,
            primary_key="is_primary_stem_only",
            secondary_key="is_secondary_stem_only",
            has_model=True,
        )
        self.assertFalse(self.section._subset_block.get_visible())
        self.assertTrue(self.section._exclusive_block.get_visible())


if __name__ == "__main__":
    unittest.main()
