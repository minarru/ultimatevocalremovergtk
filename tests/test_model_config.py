import unittest
from unittest.mock import MagicMock

from bundled.constants import CHOOSE_MODEL, VR_ARCH_TYPE
from core import ModelConfig, ProcessData, Settings, assemble_model
from core.model_config import DeviceOptions


class ModelConfigPublicApiTests(unittest.TestCase):
    def test_typed_names_are_public(self):
        self.assertEqual(ModelConfig.__module__, "core.model_config.config")
        self.assertEqual(ProcessData.__module__, "core.process_data")
        self.assertEqual(Settings.__module__, "core.settings.model")
        self.assertEqual(assemble_model.__module__, "core.model_config.assemble")

    def test_device_options_expose_boolean_gpu_state(self):
        settings = Settings.from_flat(
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
