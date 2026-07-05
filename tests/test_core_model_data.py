import unittest
from unittest.mock import MagicMock, patch

from data.constants import DEFAULT, ENSEMBLE_MODE, MDX_ARCH_TYPE, VR_ARCH_TYPE
from uvr_core.model_data import ModelData, assemble_model_data
from uvr_core.settings import SettingsModel


class OverlapMdxDefaultTests(unittest.TestCase):
    def test_default_overlap_mdx_is_float(self):
        settings = SettingsModel({"overlap_mdx": DEFAULT})
        repo = MagicMock()
        repo.vr_hash_MAPPER = {}
        repo.model_hash_table = {}
        repo.on_unrecognized_model = None

        def fake_get_model_hash(self):
            self.model_hash = None
            self.model_status = False

        with patch.object(ModelData, "get_model_hash", fake_get_model_hash):
            model = ModelData(settings, repo, "missing.pth", VR_ARCH_TYPE, is_dry_check=True)
        self.assertEqual(model.overlap_mdx, 0.25)
        self.assertIsInstance(model.overlap_mdx, float)


class AssembleEnsembleTests(unittest.TestCase):
    def test_filters_invalid_members(self):
        settings = SettingsModel(
            {
                "selected_models": [
                    f"{VR_ARCH_TYPE}: good",
                    f"{VR_ARCH_TYPE}: bad",
                ]
            }
        )
        repo = MagicMock()
        repo.on_unrecognized_model = None

        good = MagicMock()
        good.model_status = True
        bad = MagicMock()
        bad.model_status = False

        with patch("uvr_core.model_data.ModelData", side_effect=[good, bad]):
            with self.assertRaises(ValueError):
                assemble_model_data(settings, repo, arch_type=ENSEMBLE_MODE)

    def test_returns_valid_members(self):
        settings = SettingsModel(
            {
                "selected_models": [
                    f"{VR_ARCH_TYPE}: a",
                    f"{VR_ARCH_TYPE}: b",
                ]
            }
        )
        repo = MagicMock()
        repo.on_unrecognized_model = None

        first = MagicMock()
        first.model_status = True
        second = MagicMock()
        second.model_status = True

        with patch("uvr_core.model_data.ModelData", side_effect=[first, second]):
            models = assemble_model_data(settings, repo, arch_type=ENSEMBLE_MODE)
        self.assertEqual(models, [first, second])


if __name__ == "__main__":
    unittest.main()
