import unittest
from unittest.mock import MagicMock

from bundled.constants import MDX_ARCH_TYPE

from ui.views.base import apply_name_mapper, current_display_for_stored_model


class ApplyNameMapperTests(unittest.TestCase):
    def test_empty_mapper_returns_copy(self):
        names = ["model_a.onnx", "model_b.onnx"]
        self.assertEqual(apply_name_mapper(names, None), names)
        self.assertIsNot(apply_name_mapper(names, None), names)

    def test_maps_known_names(self):
        mapper = {"old_name_v1.ckpt": "Friendly Name"}
        self.assertEqual(
            apply_name_mapper(["old_name_v1.ckpt"], mapper),
            ["Friendly Name"],
        )

    def test_leaves_unmapped_names(self):
        mapper = {"other": "Mapped"}
        self.assertEqual(apply_name_mapper(["unknown.onnx"], mapper), ["unknown.onnx"])

    def test_catalogue_index_fallback(self):
        mapper = {}
        catalogue = {"community_model": "Community Label"}
        self.assertEqual(
            apply_name_mapper(["community_model"], mapper, catalogue_index=catalogue),
            ["Community Label"],
        )

    def test_catalogue_wins_over_mapper(self):
        mapper = {"community_model": "Short Alias"}
        catalogue = {"community_model": "Community Label"}
        self.assertEqual(
            apply_name_mapper(["community_model"], mapper, catalogue_index=catalogue),
            ["Community Label"],
        )


class CurrentDisplayForStoredModelTests(unittest.TestCase):
    def test_migrates_mapper_alias_to_catalogue_label(self):
        repo = MagicMock()
        repo.mdx_name_select_MAPPER = {"melband_roformer_inst_v1": "MB-Roformer-Inst-v1"}
        repo.mdx_catalogue_display_index.return_value = {
            "melband_roformer_inst_v1": "MelBand Roformer Kim | Inst v1 by Unwa",
        }
        basenames = ["melband_roformer_inst_v1"]
        self.assertEqual(
            current_display_for_stored_model(
                "MB-Roformer-Inst-v1",
                basenames,
                MDX_ARCH_TYPE,
                repo,
            ),
            "MelBand Roformer Kim | Inst v1 by Unwa",
        )

    def test_migrates_basename_to_catalogue_label(self):
        repo = MagicMock()
        repo.mdx_name_select_MAPPER = {"melband_roformer_inst_v1": "MB-Roformer-Inst-v1"}
        repo.mdx_catalogue_display_index.return_value = {
            "melband_roformer_inst_v1": "MelBand Roformer Kim | Inst v1 by Unwa",
        }
        self.assertEqual(
            current_display_for_stored_model(
                "melband_roformer_inst_v1",
                ["melband_roformer_inst_v1"],
                MDX_ARCH_TYPE,
                repo,
            ),
            "MelBand Roformer Kim | Inst v1 by Unwa",
        )

    def test_leaves_unknown_stored_value(self):
        repo = MagicMock()
        repo.mdx_name_select_MAPPER = {}
        repo.mdx_catalogue_display_index.return_value = {}
        self.assertEqual(
            current_display_for_stored_model(
                "Missing Model",
                ["other_model"],
                MDX_ARCH_TYPE,
                repo,
            ),
            "Missing Model",
        )


if __name__ == "__main__":
    unittest.main()
