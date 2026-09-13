"""Settings retain per-role, exact-model blend preferences across entry points."""

import tempfile
import unittest
from unittest.mock import patch

from core.ensemble_blend import blend_kwargs, saved_blend_options
from core.ensemble_service import EnsembleService, save_ensemble
from core.settings import Settings
from core.settings.access import set_path, validate_setting_value


class EnsembleBlendOptionsTests(unittest.TestCase):
    def test_weights_follow_id_and_role_not_member_order(self) -> None:
        settings = Settings.defaults()
        settings.ensemble.member_weights = {
            "*": {"mdx:a": 2},
            "vocal.vocals": {"mdx:b": 3},
        }
        self.assertEqual(
            blend_kwargs(settings, ["mdx:b", "mdx:a"], "vocal.vocals")["weights"], [3, 2]
        )
        self.assertEqual(
            blend_kwargs(settings, ["mdx:b", "mdx:a"], "mix.instrumental")["weights"], [1, 2]
        )

    def test_json_and_saved_preset_round_trip(self) -> None:
        settings = Settings.defaults()
        settings.ensemble.member_weights = {"vocal.vocals": {"mdx:a": 2}}
        settings.ensemble.smoothing = 0.3
        settings.ensemble.soft_strength = 2.0
        settings.ensemble.hybrid_balance = 0.7
        settings.ensemble.alignment_correction = True
        loaded = Settings.from_json_dict(settings.to_json_dict())
        self.assertEqual(saved_blend_options(loaded), saved_blend_options(settings))
        with tempfile.TemporaryDirectory() as directory:
            with patch("core.ensemble_service.paths.ENSEMBLE_CACHE_DIR", directory):
                save_ensemble(
                    "Blend",
                    "pair.vocals_instrumental",
                    "Average/Average",
                    [],
                    blend_options=saved_blend_options(settings),
                )
                applied = Settings.defaults()
                EnsembleService().apply(applied, "Blend")
                self.assertEqual(saved_blend_options(applied), saved_blend_options(settings))

    def test_invalid_settings_are_rejected_at_override_boundary(self) -> None:
        settings = Settings.defaults()
        for path, value in (
            ("ensemble.smoothing", -1),
            ("ensemble.soft_strength", float("nan")),
            ("ensemble.hybrid_balance", 1.1),
            ("ensemble.member_weights", {"*": {"mdx:a": -0.1}}),
        ):
            with self.subTest(path=path):
                with self.assertRaises(ValueError):
                    validate_setting_value(settings, path, value)
        set_path(settings, "ensemble.smoothing", "0.5")
        self.assertEqual(settings.ensemble.smoothing, 0.5)
