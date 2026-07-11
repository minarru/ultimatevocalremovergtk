import os
import unittest

from bundled.constants import CKPT, ONNX
from core import paths
from core.model_data import ModelData, ModelRepository
from core.settings import SettingsModel


class MdxModelPathTests(unittest.TestCase):
    def test_unmapped_ckpt_resolves_to_ckpt_not_onnx(self) -> None:
        model_name = "model_BandSplit-Roformer_Karaoke_Frazer_by-becruily"
        ckpt_path = os.path.join(paths.MDX_MODELS_DIR, f"{model_name}{CKPT}")
        if not os.path.isfile(ckpt_path):
            self.skipTest("BandSplit becruily ckpt not present in workspace")

        settings = SettingsModel()
        repo = ModelRepository()
        repo.reload_mappers()
        model_data = ModelData(
            settings,
            repo,
            model_name,
            selected_process_method="MDX-Net",
            is_dry_check=True,
        )

        self.assertTrue(model_data.is_mdx_ckpt)
        self.assertEqual(model_data.model_path, ckpt_path)
        self.assertFalse(model_data.model_path.endswith(ONNX))


if __name__ == "__main__":
    unittest.main()
