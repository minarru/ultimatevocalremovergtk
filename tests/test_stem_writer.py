"""Boundary tests for the extracted stem writer."""

from __future__ import annotations

import ast
import json
import subprocess
import sys
import unittest
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
_WRITER = _REPO / "engines" / "stem_writer.py"


class StemWriterModuleBoundaryTests(unittest.TestCase):
    def test_stem_writer_source_does_not_mention_engines_base(self) -> None:
        source = _WRITER.read_text(encoding="utf-8")
        self.assertNotIn("engines.base", source)
        self.assertNotIn("SeperateAttributes", source)
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                module = node.module or ""
                self.assertNotEqual(module, "base")
                self.assertNotEqual(module, "engines.base")
                self.assertNotIn(
                    "SeperateAttributes", [alias.name for alias in node.names]
                )

    def test_importing_stem_writer_does_not_import_engines_base(self) -> None:
        script = f"""
import importlib.util
import sys
import types
from pathlib import Path

root = Path({json.dumps(str(_REPO))})
pkg = types.ModuleType("engines")
pkg.__path__ = [str(root / "engines")]
pkg.__package__ = "engines"
sys.modules["engines"] = pkg
path = root / "engines" / "stem_writer.py"
spec = importlib.util.spec_from_file_location(
    "engines.stem_writer",
    path,
    submodule_search_locations=[str(root / "engines")],
)
assert spec is not None and spec.loader is not None
mod = importlib.util.module_from_spec(spec)
sys.modules["engines.stem_writer"] = mod
spec.loader.exec_module(mod)
print("engines.base" in sys.modules)
print(callable(getattr(mod, "write_audio", None)))
"""
        proc = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True,
            text=True,
            check=False,
            cwd=str(_REPO),
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        lines = proc.stdout.strip().splitlines()
        self.assertEqual(lines[0], "False")
        self.assertEqual(lines[1], "True")


if __name__ == "__main__":
    unittest.main()
