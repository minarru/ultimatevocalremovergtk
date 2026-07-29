import unittest
from unittest.mock import MagicMock

from bundled.constants import CHOOSE_MODEL, VR_ARCH_TYPE
from core import ModelConfig, ModelData, assemble_model, assemble_model_data
from core.model_config import DeviceOptions
from core.settings import SettingsModel


class ModelConfigCompatibilityTests(unittest.TestCase):
    def test_legacy_names_are_identity_aliases(self):
        self.assertIs(ModelData, ModelConfig)
        self.assertIs(assemble_model_data, assemble_model)
        self.assertEqual(ModelConfig.__module__, "core.model_config.config")

    def test_device_options_expose_boolean_gpu_state(self):
        settings = SettingsModel(
            {
                "is_gpu_conversion": 1,
                "device_set": "CUDA: 2",
                "is_use_directml": False,
            }
        )
        repo = MagicMock()
        repo.vr_catalogue_display_index.return_value = {}
        repo.vr_hash_MAPPER = {}
        repo.model_hash_table = {}
        repo.on_unrecognized_model = None

        model = ModelConfig(
            settings,
            repo,
            CHOOSE_MODEL,
            VR_ARCH_TYPE,
            is_dry_check=True,
        )

        self.assertIs(model.use_gpu, True)
        self.assertIs(model.is_gpu_conversion, True)
        self.assertEqual(
            model.device_options,
            DeviceOptions(
                use_gpu=True,
                device_set="2",
                is_use_directml=False,
            ),
        )


if __name__ == "__main__":
    unittest.main()
