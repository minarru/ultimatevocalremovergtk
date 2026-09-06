import importlib
import sys
import typing
import unittest
from unittest.mock import patch

import torch

from core.torch_checkpoint import (
    as_model_state_dict,
    ensure_demucs_import_aliases,
    ensure_optional_checkpoint_stubs,
    load_torch_checkpoint,
)


class DemucsImportAliasTests(unittest.TestCase):
    def test_demucs_hdemucs_resolves_to_vendor_package(self):
        ensure_demucs_import_aliases()
        mod = importlib.import_module("demucs.hdemucs")
        self.assertEqual(mod.__name__, "vendor.demucs.hdemucs")

    def test_missing_aliases_are_repaired_after_initial_install(self):
        import core.torch_checkpoint as checkpoint

        with patch.object(checkpoint, "_DEMUCS_ALIASES_INSTALLED", False):
            ensure_demucs_import_aliases()
            aliases = (
                "demucs",
                *(f"demucs.{sub}" for sub in checkpoint._DEMUCS_ALIAS_SUBMODULES),
            )
            expected = {alias: sys.modules[alias] for alias in aliases}

            with patch.dict(sys.modules):
                for alias in expected:
                    sys.modules.pop(alias, None)

                ensure_demucs_import_aliases()

                for alias, module in expected.items():
                    self.assertIs(sys.modules.get(alias), module, alias)


class OptionalCheckpointStubTests(unittest.TestCase):
    def test_stubs_bitsandbytes_adamw8bit_when_missing(self):
        # Force the stub path even if a real install appears later.
        import core.torch_checkpoint as mod

        mod._OPTIONAL_STUBS_INSTALLED = False
        with patch.dict(sys.modules):
            sys.modules.pop("bitsandbytes", None)
            sys.modules.pop("bitsandbytes.optim", None)
            sys.modules.pop("bitsandbytes.optim.adamw", None)
            with patch(
                "core.torch_checkpoint.importlib.import_module",
                side_effect=ImportError("no bitsandbytes"),
            ):
                ensure_optional_checkpoint_stubs()
            adamw = sys.modules["bitsandbytes.optim.adamw"]
            self.assertTrue(hasattr(adamw, "AdamW8bit"))
            instance = adamw.AdamW8bit()
            instance.__setstate__({"foo": 1})
            self.assertEqual(instance.foo, 1)


class AsModelStateDictTests(unittest.TestCase):
    def test_unwraps_model_state_dict(self):
        weights = {"layer.weight": torch.zeros(2)}
        wrapped = {
            "epoch": 3,
            "optimizer_state_dict": {"state": {}},
            "model_state_dict": weights,
        }
        self.assertIs(as_model_state_dict(wrapped), weights)

    def test_leaves_raw_state_dict_unchanged(self):
        weights = {"layer.weight": torch.zeros(2)}
        self.assertIs(as_model_state_dict(weights), weights)

    def test_leaves_apollo_style_envelope_for_state_dict_key_when_values_are_tensors(self):
        # MDX path wants the nested weights; Apollo keeps the outer envelope by
        # calling load_torch_checkpoint without as_model_state_dict.
        weights = {"w": torch.ones(1)}
        self.assertIs(as_model_state_dict({"state_dict": weights, "model_name": "X"}), weights)


class LoadTorchCheckpointTests(unittest.TestCase):
    def test_installs_demucs_aliases_before_load(self):
        with patch("core.torch_checkpoint.torch.load", return_value={}) as mock_load:
            with patch(
                "core.torch_checkpoint.ensure_demucs_import_aliases"
            ) as mock_aliases:
                with patch(
                    "core.torch_checkpoint.ensure_optional_checkpoint_stubs"
                ) as mock_stubs:
                    load_torch_checkpoint("model.th", map_location="cpu")
        mock_aliases.assert_called_once_with()
        mock_stubs.assert_called_once_with()
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
        def _raise_type_error(*_args: typing.Any, **_kwargs: typing.Any):
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
