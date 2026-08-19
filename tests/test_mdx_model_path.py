import os
import unittest

from bundled.constants import CKPT, ONNX
from core import paths
from core.model_config import ModelConfig
from core.model_repository import ModelRepository
from core.settings import Settings


class MdxModelPathTests(unittest.TestCase):
    def test_unmapped_ckpt_resolves_to_ckpt_not_onnx(self) -> None:
        model_name = "model_BandSplit-Roformer_Karaoke_Frazer_by-becruily"
        ckpt_path = os.path.join(paths.MDX_MODELS_DIR, f"{model_name}{CKPT}")
        if not os.path.isfile(ckpt_path):
            self.skipTest("BandSplit becruily ckpt not present in workspace")

        settings = Settings.defaults()
        repo = ModelRepository()
        repo.reload_mappers()
        model_data = ModelConfig(
            settings,
            repo,
            model_name,
            selected_process_method="MDX-Net",
            is_dry_check=True,
        )

        self.assertTrue(model_data.is_mdx_ckpt)
        self.assertEqual(model_data.model_path, ckpt_path)
        self.assertFalse(model_data.model_path.endswith(ONNX))

    def test_auto_registered_onnx_mapper_key_does_not_double_extension(self) -> None:
        # register_mdx_display_name (core/mdx_c_registry.py) writes mapper
        # keys that already include the file extension, unlike bundled
        # catalogue mapper keys. get_mdx_model_path must not append the
        # extension again for a mapper key that already ends with it.
        class _FakeRepo:
            mdx_name_select_MAPPER = {"some_checkpoint.onnx": "Some Friendly Name"}

            def mdx_catalogue_display_index(self):
                return {}

        model_data = object.__new__(ModelConfig)
        model_data.repo = _FakeRepo()
        model_data.model_name = "Some Friendly Name"
        model_data.is_mdx_ckpt = False

        model_data.get_mdx_model_path()

        self.assertEqual(
            model_data.model_path,
            os.path.join(paths.MDX_MODELS_DIR, "some_checkpoint.onnx"),
        )
        self.assertFalse(model_data.model_path.endswith(".onnx.onnx"))


if __name__ == "__main__":
    unittest.main()
