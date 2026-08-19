import json
import os
import shutil
import tempfile
import unittest
from unittest.mock import patch

from bundled.constants import MDX_ARCH_TYPE
from core import paths
from core.downloads import DownloadManager
from core.mdx_c_registry import compute_checkpoint_hash
from core.model_config import ModelConfig
from core.model_repository import ModelRepository


class ModelDataMergeTests(unittest.TestCase):
    def test_local_hash_json_merges_with_mapper_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            model_hash = "77dd1942c0feb5c04ad0b4effa34fbc6"
            hash_mapper = {
                model_hash: {
                    "config_yaml": "config_musdb18_scnet_large.yaml",
                    "is_roformer": True,
                    "model_type": "SCNet",
                }
            }
            with open(os.path.join(tmp, f"{model_hash}.json"), "w", encoding="utf-8") as handle:
                json.dump({"is_roformer": False}, handle)

            model_data = ModelConfig.__new__(ModelConfig)
            model_data.model_hash = model_hash
            model_data.is_dry_check = True
            model_data.is_get_hash_dir_only = False
            model_data.repo = None

            merged = model_data.get_model_data(tmp, hash_mapper)
            assert isinstance(merged, dict)
            self.assertEqual(merged["config_yaml"], "config_musdb18_scnet_large.yaml")
            self.assertFalse(merged["is_roformer"])
            self.assertEqual(merged["model_type"], "SCNet")

    def test_catalog_fallback_before_popup(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            hash_dir = os.path.join(tmp, "model_data")
            config_dir = os.path.join(hash_dir, "mdx_c_configs")
            models_dir = os.path.join(tmp, "models")
            os.makedirs(config_dir)
            os.makedirs(models_dir)

            checkpoint = os.path.join(models_dir, "fallback_model.ckpt")
            yaml_name = "config_musdb18_scnet.yaml"
            with open(checkpoint, "wb") as handle:
                handle.write(b"catalog fallback checkpoint")
            shutil.copyfile(
                os.path.join(paths.MDX_C_CONFIG_PATH, yaml_name), os.path.join(config_dir, yaml_name)
            )

            original_hash_dir = paths.MDX_HASH_DIR
            original_config_dir = paths.MDX_C_CONFIG_PATH
            try:
                paths.MDX_HASH_DIR = hash_dir
                paths.MDX_C_CONFIG_PATH = config_dir

                model_data = ModelConfig.__new__(ModelConfig)
                model_data.model_hash = compute_checkpoint_hash(checkpoint)
                model_data.process_method = MDX_ARCH_TYPE
                model_data.is_mdx_ckpt = True
                model_data.model_path = checkpoint
                model_data.is_dry_check = True
                model_data.repo = ModelRepository()
                model_data.repo.on_unrecognized_model = lambda _self: {"should": "not run"}

                index = {"fallback_model.ckpt": yaml_name}
                with patch("core.mdx_c_registry.load_mdx_catalog_index", return_value=index):
                    result = model_data.get_model_data(hash_dir, {})
            finally:
                paths.MDX_HASH_DIR = original_hash_dir
                paths.MDX_C_CONFIG_PATH = original_config_dir

            self.assertIsNotNone(result)
            assert isinstance(result, dict)
            self.assertEqual(result["config_yaml"], yaml_name)
            self.assertEqual(result["model_type"], "SCNet")


if __name__ == "__main__":
    unittest.main()
