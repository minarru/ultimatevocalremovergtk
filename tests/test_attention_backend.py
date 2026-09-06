"""Attention backend and inference-mode guards.

Upstream pinned the SDPA backend set per GPU; on an A100 that meant flash-only,
which has no fp32 kernel — so running with autocast disabled raised
``RuntimeError: No available kernel``. These tests pin the contract that
attention works for both dtypes on whatever device is available.
"""

from __future__ import annotations

import unittest

import torch

from ml.attend import Attend


class AttendDtypeTests(unittest.TestCase):
    """``Attend`` must work in fp32 as well as fp16 (autocast on *and* off)."""

    def _qkv(self, dtype: torch.dtype, device: str) -> tuple[torch.Tensor, ...]:
        return tuple(
            torch.randn(2, 4, 64, 32, device=device, dtype=dtype) for _ in range(3)
        )

    def test_flash_path_accepts_fp32(self) -> None:
        """The regression: fp32 + flash=True must not raise."""
        attend = Attend(flash=True).eval()
        q, k, v = self._qkv(torch.float32, "cpu")
        with torch.inference_mode():
            out = attend(q, k, v)
        self.assertEqual(out.shape, q.shape)
        self.assertTrue(torch.isfinite(out).all())

    def test_flash_and_manual_paths_agree(self) -> None:
        """flash=True and flash=False must compute the same attention."""
        q, k, v = self._qkv(torch.float32, "cpu")
        with torch.inference_mode():
            flash = Attend(flash=True).eval()(q, k, v)
            manual = Attend(flash=False).eval()(q, k, v)
        torch.testing.assert_close(flash, manual, rtol=1e-4, atol=1e-5)

    def test_no_deprecated_sdp_kernel_call(self) -> None:
        """`torch.backends.cuda.sdp_kernel` is deprecated and slated for removal.

        Checked as an AST attribute reference, not a text search, so prose in
        comments explaining the removal doesn't trip it.
        """
        import ast
        import inspect

        import ml.attend as attend_mod

        tree = ast.parse(inspect.getsource(attend_mod))
        used = {
            node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)
        }
        self.assertNotIn("sdp_kernel", used)

    @unittest.skipUnless(torch.cuda.is_available(), "CUDA required")
    def test_cuda_fp32_and_fp16(self) -> None:
        attend = Attend(flash=True).eval()
        for dtype in (torch.float32, torch.float16):
            with self.subTest(dtype=dtype), torch.inference_mode():
                q, k, v = self._qkv(dtype, "cuda")
                out = attend(q, k, v)
                self.assertEqual(out.shape, q.shape)
                self.assertTrue(torch.isfinite(out).all())


class DemucsEvalModeTests(unittest.TestCase):
    """Every Demucs load branch must leave the model in eval mode."""

    def test_all_load_branches_call_eval(self) -> None:
        """v1 used to be the one branch that skipped ``.eval()``.

        A BatchNorm-carrying checkpoint left in train mode normalises on the
        current chunk rather than the stored running statistics.
        """
        from types import SimpleNamespace
        from unittest.mock import patch

        from bundled.constants import DEMUCS_V1, DEMUCS_V2, DEMUCS_V3, DEMUCS_V4
        from engines.demucs_runtime import DemucsAcquisitionRequest, acquire_demucs_model

        for version in (DEMUCS_V1, DEMUCS_V2, DEMUCS_V3, DEMUCS_V4):
            with self.subTest(version=version):
                model = torch.nn.BatchNorm1d(2)
                self.assertTrue(model.training)
                state = model.state_dict()
                checkpoint = ((lambda model=model: model), (), {}, state) if version == DEMUCS_V1 else state
                request = DemucsAcquisitionRequest("/tmp/fixture.th", version, sources=["vocals"])
                with (
                    patch("engines.demucs_runtime.load_torch_checkpoint", return_value=checkpoint),
                    patch("engines.demucs_runtime.auto_load_demucs_model_v2", return_value=model),
                    patch("engines.demucs_runtime._gm", return_value=model),
                    patch("engines.demucs_runtime.demucs_segments", return_value=model),
                ):
                    loaded = acquire_demucs_model(request, "cpu", weight_cache=SimpleNamespace(get=lambda _key: None), cache_key="fixture")
                self.assertIs(loaded, model)
                self.assertFalse(loaded.training)



if __name__ == "__main__":
    unittest.main()
