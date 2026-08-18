"""Boundary tests for the extracted MDX-C engine."""

from __future__ import annotations

import unittest
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
_MDX = _REPO / "engines" / "mdx.py"
_MDX_C = _REPO / "engines" / "mdx_c.py"


class MdxCModuleBoundaryTests(unittest.TestCase):
    def test_mdx_source_does_not_mention_mdx_c_engine(self) -> None:
        source = _MDX.read_text(encoding="utf-8")
        self.assertNotIn("SeperateMDXC", source)
        self.assertNotIn("demix_roformer", source)
        self.assertNotIn("_build_mdx_c_model", source)
        self.assertNotIn("from .mdx_c import", source)
        self.assertNotIn("from engines.mdx_c import", source)
        self.assertNotIn("import engines.mdx_c", source)

    def test_mdx_c_source_does_not_mention_classic_mdx(self) -> None:
        source = _MDX_C.read_text(encoding="utf-8")
        self.assertNotIn("class SeperateMDX(", source)
        self.assertNotIn("class SeperateMDX ", source)
        self.assertNotIn("from .mdx import", source)
        self.assertNotIn("from engines.mdx import", source)


if __name__ == "__main__":
    unittest.main()
