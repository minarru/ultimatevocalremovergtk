import unittest

from ui.views.base import apply_name_mapper


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


if __name__ == "__main__":
    unittest.main()
