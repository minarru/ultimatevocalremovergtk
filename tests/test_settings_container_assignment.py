"""A container setting may be set from a matching container value."""

import unittest

from core.settings import Settings
from core.settings.access import (
    apply_settings_overrides,
    validate_setting_value,
)


class ContainerAssignmentTests(unittest.TestCase):
    def test_a_list_field_accepts_a_list(self) -> None:
        """The sweep's ensemble job passes a real list and was rejected anyway."""
        validate_setting_value(
            Settings(), "ensemble.selected_models", ["mdx:a", "mdx:b"]
        )

    def test_a_list_field_accepts_a_tuple(self) -> None:
        validate_setting_value(Settings(), "ensemble.selected_models", ("mdx:a",))

    def test_a_list_field_still_rejects_a_scalar(self) -> None:
        """--set ensemble.selected_models=x must not silently land a string."""
        with self.assertRaises(ValueError) as ctx:
            validate_setting_value(Settings(), "ensemble.selected_models", "mdx:a")
        self.assertIn("container", str(ctx.exception))

    def test_assignments_apply_a_list(self) -> None:
        settings = Settings()
        apply_settings_overrides(
            settings, [("ensemble.selected_models", ["mdx:a", "mdx:b"])]
        )
        self.assertEqual(settings.ensemble.selected_models, ["mdx:a", "mdx:b"])

    def test_assignments_still_reject_a_scalar_for_a_list(self) -> None:
        settings = Settings()
        with self.assertRaises(ValueError):
            apply_settings_overrides(settings, [("ensemble.selected_models", "mdx:a")])
        self.assertEqual(settings.ensemble.selected_models, [])

    def test_an_unknown_path_is_still_rejected(self) -> None:
        with self.assertRaises(ValueError):
            apply_settings_overrides(Settings(), [("ensemble.nope", ["a"])])


if __name__ == "__main__":
    unittest.main()
