"""Boundary tests for retiring the engines.separate / engines.export barrels."""

from __future__ import annotations

import ast
import importlib
import subprocess
import sys
import unittest
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
_INIT = _REPO / "engines" / "__init__.py"
_FACTORY = _REPO / "engines" / "separator_factory.py"
_CORE_CALLERS = (
    _REPO / "core" / "separate_import.py",
    _REPO / "core" / "run_loop.py",
    _REPO / "core" / "ensembler.py",
    _REPO / "core" / "inference_cleanup.py",
    _REPO / "core" / "job_runner.py",
)


class EngineBarrelRemovalTests(unittest.TestCase):
    def test_separate_and_export_modules_are_gone(self) -> None:
        for name in ("engines.separate", "engines.export"):
            with self.subTest(name=name), self.assertRaises(ModuleNotFoundError):
                importlib.import_module(name)

    def test_core_callers_do_not_import_engine_facades(self) -> None:
        for path in _CORE_CALLERS:
            source = path.read_text(encoding="utf-8")
            with self.subTest(path=path.name):
                self.assertNotIn("engines.separate", source)
                self.assertNotIn("engines.export", source)
                self.assertNotIn("from .export import", source)

    def test_engines_package_init_does_not_import_engine_classes(self) -> None:
        source = _INIT.read_text(encoding="utf-8")
        self.assertNotIn("SeperateVR", source)
        self.assertNotIn("SeperateMDX", source)
        self.assertNotIn("SeperateMDXC", source)
        self.assertNotIn("SeperateDemucs", source)
        self.assertNotIn("SeperateAttributes", source)
        self.assertNotIn("save_format", source)
        self.assertNotIn("clear_gpu_cache", source)
        self.assertNotIn("process_chain_model", source)
        self.assertNotIn("process_secondary_model", source)
        tree = ast.parse(source)
        imports: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                imports.append(node.module or "")
            elif isinstance(node, ast.Import):
                imports.extend(alias.name for alias in node.names)
        self.assertEqual(imports, [])

    def test_factory_source_defines_preload(self) -> None:
        source = _FACTORY.read_text(encoding="utf-8")
        self.assertIn("def preload_engine_modules", source)
        self.assertIn("_engine_classes()", source)


class EngineImportWeightTests(unittest.TestCase):
    def test_import_engines_package_does_not_load_ml_stacks(self) -> None:
        script = (
            "import sys, engines, engines.gpu_cache; "
            "print(any(x in sys.modules for x in ("
            "'torch', 'onnxruntime', 'engines.vr', 'engines.mdx', "
            "'engines.mdx_c_engine', 'engines.demucs_engine', 'engines.separate'"
            ")))"
        )
        proc = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True,
            text=True,
            check=True,
            cwd=str(_REPO),
        )
        self.assertEqual(proc.stdout.strip(), "False")

    def test_import_core_and_job_runner_does_not_load_ml_stacks(self) -> None:
        script = (
            "import sys, core, core.job_runner, core.run_loop; "
            "print(any(x in sys.modules for x in ("
            "'torch', 'onnxruntime', 'gi', 'engines.vr', 'engines.separate'"
            ")))"
        )
        proc = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True,
            text=True,
            check=True,
            cwd=str(_REPO),
        )
        self.assertEqual(proc.stdout.strip(), "False")


if __name__ == "__main__":
    unittest.main()
