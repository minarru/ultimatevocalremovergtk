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
        import ast
        import inspect
        import textwrap

        from engines.demucs_engine import SeperateDemucs

        src = textwrap.dedent(inspect.getsource(SeperateDemucs.seperate))
        tree = ast.parse(src)

        # Locate the if/elif chain dispatching on self.demucs_version, then
        # check every branch of it — including the trailing else.
        def is_version_test(node: ast.AST) -> bool:
            return "self.demucs_version ==" in ast.unparse(node)

        chain: ast.If | None = None
        for node in ast.walk(tree):
            if isinstance(node, ast.If) and is_version_test(node.test):
                chain = node
                break
        self.assertIsNotNone(chain, "demucs_version dispatch chain not found")

        bodies: list[tuple[str, list[ast.stmt]]] = []
        node = chain
        while isinstance(node, ast.If):
            bodies.append((ast.unparse(node.test), node.body))
            nxt = node.orelse
            if len(nxt) == 1 and isinstance(nxt[0], ast.If):
                node = nxt[0]
            else:
                if nxt:
                    bodies.append(("else", nxt))
                break

        self.assertGreaterEqual(len(bodies), 3, "expected v1 / v2 / newer branches")
        for label, body in bodies:
            block = ast.unparse(ast.Module(body=body, type_ignores=[]))
            if "self.demucs = " not in block:
                continue  # not a model-construction branch
            with self.subTest(branch=label[:60]):
                self.assertIn(
                    ".eval()", block, f"branch {label!r} loads a model without .eval()"
                )


if __name__ == "__main__":
    unittest.main()
