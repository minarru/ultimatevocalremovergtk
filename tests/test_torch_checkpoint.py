import importlib
import unittest
from unittest.mock import patch

from core.torch_checkpoint import ensure_demucs_import_aliases, load_torch_checkpoint


class DemucsImportAliasTests(unittest.TestCase):
    def test_demucs_hdemucs_resolves_to_vendor_package(self):
        ensure_demucs_import_aliases()
        mod = importlib.import_module("demucs.hdemucs")
        self.assertEqual(mod.__name__, "vendor.demucs.hdemucs")


class LoadTorchCheckpointTests(unittest.TestCase):
    def test_installs_demucs_aliases_before_load(self):
        with patch("core.torch_checkpoint.torch.load", return_value={}) as mock_load:
            with patch(
                "core.torch_checkpoint.ensure_demucs_import_aliases"
            ) as mock_aliases:
                load_torch_checkpoint("model.th", map_location="cpu")
        mock_aliases.assert_called_once_with()
        mock_load.assert_called_once()

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
