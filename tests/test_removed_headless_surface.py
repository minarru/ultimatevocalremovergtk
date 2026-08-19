from __future__ import annotations

import importlib
import ast
import os
import subprocess
import sys
import unittest


class RemovedHeadlessSurfaceTests(unittest.TestCase):
    def test_removed_modules_cannot_be_imported(self) -> None:
        for name in (
            "core." + "headless_run", "core." + "cli", "cli." + "blocking",
            "cli." + "inputs", "cli." + "model_ids",
            "engines." + "separate", "engines." + "export",
        ):
            with self.subTest(name=name), self.assertRaises(ModuleNotFoundError):
                importlib.import_module(name)

    def test_core_is_not_a_launcher(self) -> None:
        proc = subprocess.run(
            [sys.executable, "-m", "core"], capture_output=True, text=True,
            cwd=os.path.dirname(os.path.dirname(__file__)),
        )
        self.assertNotEqual(proc.returncode, 0)

    def test_active_python_sources_do_not_reference_removed_modules(self) -> None:
        root = os.path.dirname(os.path.dirname(__file__))
        forbidden = (
            "core." + "headless_run", "core." + "cli", "cli." + "blocking",
            "cli." + "inputs", "cli." + "model_ids",
            "engines." + "separate", "engines." + "export",
        )
        offenders: list[str] = []
        for top in ("core", "cli", "ui", "scripts", "tests"):
            for folder, _dirs, files in os.walk(os.path.join(root, top)):
                for name in files:
                    if not name.endswith(".py"):
                        continue
                    path = os.path.join(folder, name)
                    with open(path, encoding="utf-8") as handle:
                        tree = ast.parse(handle.read(), filename=path)
                    imported = []
                    for node in ast.walk(tree):
                        if isinstance(node, ast.Import):
                            imported.extend(alias.name for alias in node.names)
                        elif isinstance(node, ast.ImportFrom) and node.module:
                            imported.append(node.module)
                    if any(
                        name == token or name.startswith(f"{token}.")
                        for name in imported for token in forbidden
                    ):
                        offenders.append(os.path.relpath(path, root))
        self.assertEqual(offenders, [])

    def test_importing_core_does_not_import_cli(self) -> None:
        script = "import sys, core; print('cli' in sys.modules)"
        proc = subprocess.run(
            [sys.executable, "-c", script], capture_output=True, text=True,
            cwd=os.path.dirname(os.path.dirname(__file__)), check=True,
        )
        self.assertEqual(proc.stdout.strip(), "False")


if __name__ == "__main__":
    unittest.main()
