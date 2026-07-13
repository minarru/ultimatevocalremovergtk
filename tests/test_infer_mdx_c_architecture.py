"""Tests for unrecognized-model MDX-C architecture inference."""

import os
import tempfile
import unittest

from core import paths
from core.mdx_c_registry import infer_mdx_c_architecture


class InferMdxCArchitectureTests(unittest.TestCase):
    def test_scnet_yaml(self) -> None:
        payload = (
            "model:\n"
            "  sources: [drums, bass, other, vocals]\n"
            "  band_SR: [0.175, 0.392, 0.433]\n"
            "  hop_size: 1024\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            original = paths.MDX_C_CONFIG_PATH
            try:
                paths.MDX_C_CONFIG_PATH = tmp
                with open(os.path.join(tmp, "fixture_scnet.yaml"), "w", encoding="utf-8") as handle:
                    handle.write(payload)
                arch, is_roformer = infer_mdx_c_architecture("fixture_scnet.yaml")
            finally:
                paths.MDX_C_CONFIG_PATH = original
        self.assertEqual(arch, "SCNet")
        self.assertTrue(is_roformer)

    def test_bandit_v2_yaml(self) -> None:
        payload = (
            "cls: Bandit\n"
            "kwargs:\n"
            "  in_channels: 1\n"
            "  stems: [speech, music, sfx]\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            original = paths.MDX_C_CONFIG_PATH
            try:
                paths.MDX_C_CONFIG_PATH = tmp
                with open(os.path.join(tmp, "fixture_bandit.yaml"), "w", encoding="utf-8") as handle:
                    handle.write(payload)
                arch, is_roformer = infer_mdx_c_architecture("fixture_bandit.yaml")
            finally:
                paths.MDX_C_CONFIG_PATH = original
        self.assertEqual(arch, "Bandit")
        self.assertTrue(is_roformer)


if __name__ == "__main__":
    unittest.main()
