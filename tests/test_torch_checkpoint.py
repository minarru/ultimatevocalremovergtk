import unittest
from unittest.mock import patch

from core.torch_checkpoint import load_torch_checkpoint


class LoadTorchCheckpointTests(unittest.TestCase):
    def test_passes_weights_only_false_on_modern_pytorch(self):
        with patch("core.torch_checkpoint.torch.load", return_value={"ok": True}) as mock_load:
            result = load_torch_checkpoint("model.th", map_location="cpu")
        self.assertEqual(result, {"ok": True})
        mock_load.assert_called_once_with(
            "model.th",
            map_location="cpu",
            weights_only=False,
        )

    def test_falls_back_without_weights_only_kwarg(self):
        def _raise_type_error(*_args, **_kwargs):
            if "weights_only" in _kwargs:
                raise TypeError("unexpected keyword argument 'weights_only'")
            return {"legacy": True}

        with patch("core.torch_checkpoint.torch.load", side_effect=_raise_type_error) as mock_load:
            result = load_torch_checkpoint("model.th", map_location="cpu")
        self.assertEqual(result, {"legacy": True})
        self.assertEqual(mock_load.call_count, 2)
        self.assertNotIn("weights_only", mock_load.call_args_list[-1].kwargs)


if __name__ == "__main__":
    unittest.main()
