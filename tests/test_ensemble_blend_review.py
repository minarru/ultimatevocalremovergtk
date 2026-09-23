"""Regression coverage from the blend-settings integration review."""

from __future__ import annotations

import tempfile
import unittest
from unittest.mock import patch

from cli.profiles import _flatten_settings, apply_profile_values
from core.ensemble_blend import blend_kwargs, restore_blend_options, validate_blend_value
from core.ensemble_service import EnsembleDocument, EnsembleService, save_ensemble
from core.settings import Settings


class EnsembleBlendReviewTests(unittest.TestCase):
    def test_zero_weight_is_a_valid_explicit_member_exclusion(self) -> None:
        settings = Settings.defaults()
        settings.ensemble.member_weights = {"vocal.vocals": {"mdx:a": 0}}

        validated = validate_blend_value("member_weights", settings.ensemble.member_weights)
        options = blend_kwargs(settings, ["mdx:a", "mdx:b"], "vocal.vocals")

        self.assertEqual(validated, {"vocal.vocals": {"mdx:a": 0.0}})
        self.assertEqual(options["weights"], [0.0, 1.0])

    def test_persisted_values_fall_back_per_field_without_losing_valid_fields(self) -> None:
        warnings: list[str] = []
        restored = restore_blend_options(
            {
                "smoothing": "not-a-number",
                "soft_strength": 2.5,
                "alignment_correction": "false",
            },
            warnings,
        )

        self.assertEqual(restored["smoothing"], 0.0)
        self.assertEqual(restored["soft_strength"], 2.5)
        self.assertIs(restored["alignment_correction"], False)
        self.assertEqual(len(warnings), 1)
        self.assertIn("ensemble.smoothing", warnings[0])

    def test_weight_keys_must_be_canonical_model_and_role_ids(self) -> None:
        with self.assertRaisesRegex(ValueError, "canonical model ID"):
            validate_blend_value("member_weights", {"vocal.vocals": {"Display Name": 2}})
        with self.assertRaisesRegex(ValueError, "role ID"):
            validate_blend_value("member_weights", {"Vocals": {"mdx:a": 2}})

    def test_gui_profile_round_trip_retains_typed_blend_options(self) -> None:
        settings = Settings.defaults()
        settings.ensemble.member_weights = {"vocal.vocals": {"mdx:a": 2.0}}
        settings.ensemble.smoothing = 0.4
        settings.ensemble.alignment_correction = True

        flattened = _flatten_settings(settings)
        replayed = Settings.defaults()
        apply_profile_values(replayed, flattened)

        self.assertEqual(replayed.ensemble.member_weights, settings.ensemble.member_weights)
        self.assertEqual(replayed.ensemble.smoothing, 0.4)
        self.assertIs(replayed.ensemble.alignment_correction, True)

    def test_malformed_settings_json_uses_defaults_and_records_warnings(self) -> None:
        payload = Settings.defaults().to_json_dict()
        payload["ensemble"]["smoothing"] = "not-a-number"
        payload["ensemble"]["alignment_correction"] = "false"

        restored = Settings.from_json_dict(payload)

        self.assertEqual(restored.ensemble.smoothing, 0.0)
        self.assertIs(restored.ensemble.alignment_correction, False)
        self.assertTrue(
            any("ensemble.smoothing" in warning for warning in restored.validation_warnings)
        )

    def test_explicit_saved_ensemble_creation_rejects_invalid_blend_values(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with patch("core.ensemble_service.paths.ENSEMBLE_CACHE_DIR", directory):
                with self.assertRaisesRegex(ValueError, "canonical model ID"):
                    save_ensemble(
                        "Invalid",
                        "pair.vocals_instrumental",
                        "Average/Average",
                        [],
                        blend_options={"member_weights": {"*": {"Display Name": 2}}},
                    )

    def test_saved_preset_load_falls_back_and_attaches_warning(self) -> None:
        document = EnsembleDocument(
            {
                "schema_version": 2,
                "ensemble_main_stem": "pair.vocals_instrumental",
                "ensemble_type": "Average/Average",
                "selected_models": [],
                "blend_options": {"hybrid_balance": 7},
            },
            [],
        )
        with patch("core.ensemble_service.load_ensemble", return_value=document):
            preset = EnsembleService().resolve("Stored")

        self.assertEqual(preset.blend_options["hybrid_balance"], 0.5)
        self.assertTrue(
            any("ensemble.hybrid_balance" in warning for warning in preset.validation_warnings)
        )


if __name__ == "__main__":
    unittest.main()
