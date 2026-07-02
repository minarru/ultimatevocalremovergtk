import unittest

from data.constants import INST_STEM, PRIMARY_STEM, SECONDARY_STEM, VOCAL_STEM
from uvr_gtk.widgets.stem_only import _TOGGLE_ALL, build_stem_only_options


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


if __name__ == "__main__":
    unittest.main()
