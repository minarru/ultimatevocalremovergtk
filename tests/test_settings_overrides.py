"""Validated (path, value) settings overrides shared by --set and named flags."""

from __future__ import annotations

import unittest

from core.settings import Settings
from core.settings.access import (
    apply_settings_overrides,
    parse_setting_assignment,
    validate_setting_path,
)


class ValidateSettingPathTests(unittest.TestCase):
    def setUp(self) -> None:
        self.settings = Settings()

    def test_accepts_known_path(self) -> None:
        self.assertEqual(
            validate_setting_path(self.settings, "process.use_gpu"),
            ("process", "use_gpu"),
        )

    def test_unknown_field_raises_value_error(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            validate_setting_path(self.settings, "process.use_gpau")
        self.assertIn("use_gpau", str(ctx.exception))

    def test_unknown_section_raises_value_error(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            validate_setting_path(self.settings, "nosuchsection.field")
        self.assertIn("nosuchsection", str(ctx.exception))

    def test_missing_dot_raises_value_error(self) -> None:
        with self.assertRaises(ValueError):
            validate_setting_path(self.settings, "use_gpu")

    def test_container_field_rejected(self) -> None:
        with self.assertRaises(ValueError):
            validate_setting_path(self.settings, "process.input_paths")


class ApplySettingsOverridesTests(unittest.TestCase):
    def setUp(self) -> None:
        self.settings = Settings()

    def test_applies_and_coerces(self) -> None:
        apply_settings_overrides(
            self.settings,
            [("process.use_gpu", "true"), ("process.sample_mode_duration", "45")],
        )
        self.assertIs(self.settings.process.use_gpu, True)
        self.assertEqual(self.settings.process.sample_mode_duration, 45)

    def test_coerces_enum_field_to_enum(self) -> None:
        apply_settings_overrides(self.settings, [("process.save_format", "FLAC")])
        self.assertEqual(self.settings.process.save_format, "FLAC")
        self.assertEqual(f"{self.settings.process.save_format.value}", "FLAC")

    def test_unknown_path_raises_before_any_write(self) -> None:
        with self.assertRaises(ValueError):
            apply_settings_overrides(
                self.settings, [("process.use_gpau", "true")]
            )
        self.assertFalse(hasattr(self.settings.process, "use_gpau"))

    def test_later_override_wins(self) -> None:
        apply_settings_overrides(
            self.settings, [("process.use_gpu", True), ("process.use_gpu", False)]
        )
        self.assertIs(self.settings.process.use_gpu, False)

    def test_invalid_numeric_value_is_not_silently_coerced(self) -> None:
        with self.assertRaisesRegex(ValueError, "invalid integer"):
            apply_settings_overrides(
                self.settings, [("mdx.segment_size", "not-a-number")]
            )


class ParseSettingAssignmentTests(unittest.TestCase):
    def test_splits_on_first_equals(self) -> None:
        self.assertEqual(
            parse_setting_assignment("process.export_path=/tmp/a=b"),
            ("process.export_path", "/tmp/a=b"),
        )

    def test_missing_equals_raises(self) -> None:
        with self.assertRaises(ValueError):
            parse_setting_assignment("process.use_gpu")

    def test_empty_path_raises(self) -> None:
        with self.assertRaises(ValueError):
            parse_setting_assignment("=true")


if __name__ == "__main__":
    unittest.main()
