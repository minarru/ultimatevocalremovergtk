import unittest

from core.settings import Settings
from ui.settings_bind import get_flat, get_path, set_flat, set_path


class SettingsBindTests(unittest.TestCase):
    def test_get_and_set_nested_path(self) -> None:
        settings = Settings.defaults()

        set_path(settings, "process.use_gpu", True)

        self.assertTrue(get_path(settings, "process.use_gpu"))
        self.assertTrue(settings.process.use_gpu)

    def test_flat_helpers_resolve_through_flat_map(self) -> None:
        settings = Settings.defaults()

        set_flat(settings, "ensemble_type", "Average/Min Spec")

        self.assertEqual(get_flat(settings, "ensemble_type"), "Average/Min Spec")
        self.assertEqual(settings.ensemble.type, "Average/Min Spec")

    def test_unknown_flat_key_matches_bridge_defaults(self) -> None:
        settings = Settings.defaults()

        set_flat(settings, "not_a_setting", "ignored")

        self.assertEqual(get_flat(settings, "not_a_setting", "fallback"), "fallback")


if __name__ == "__main__":
    unittest.main()
