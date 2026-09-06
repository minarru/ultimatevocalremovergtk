"""Blueprint compilation and resource-loading contracts."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

try:
    import gi

    gi.require_version("Gtk", "4.0")
    gi.require_version("Adw", "1")
    from gi.repository import Gtk as _Gtk

    GTK_AVAILABLE = _Gtk is not None
except (ImportError, ValueError):
    GTK_AVAILABLE = False


REPO_ROOT = Path(__file__).resolve().parents[1]
RESOURCE_SCRIPT = REPO_ROOT / "resources" / "compile_resources.sh"
RESOURCE_PREFIX = "/org/uvr/UltimateVocalRemover"


class ResourceBuildTests(unittest.TestCase):
    def _fixture(self, root: Path, blueprints: dict[str, str]) -> tuple[Path, Path]:
        resources = root / "resources"
        (resources / "icons").mkdir(parents=True)
        (resources / "icons" / "index.theme").write_text("[Icon Theme]\n")
        (resources / "style.css").write_text("window { color: white; }\n")
        script = resources / "compile_resources.sh"
        shutil.copy2(RESOURCE_SCRIPT, script)
        for name, source in blueprints.items():
            path = resources / "ui" / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(source)
        output = root / "ui" / "data" / "uvr.gresource"
        output.parent.mkdir(parents=True)
        return script, output

    def _compiler(self) -> str:
        configured = os.environ.get("BLUEPRINT_COMPILER")
        if configured:
            return configured
        found = shutil.which("blueprint-compiler")
        if found is None:
            self.skipTest("blueprint-compiler is required for this build test")
        return found

    def _run(self, script: Path, compiler: str) -> subprocess.CompletedProcess[str]:
        env = os.environ.copy()
        env["BLUEPRINT_COMPILER"] = compiler
        return subprocess.run(
            [str(script)],
            cwd=script.parent.parent,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )

    def test_missing_blueprint_compiler_fails_and_preserves_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            script, output = self._fixture(
                root,
                {"sample.blp": "using Gtk 4.0;\nGtk.Box {}\n"},
            )
            output.write_bytes(b"previous bundle")

            result = self._run(script, str(root / "missing-blueprint-compiler"))

            self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("Blueprint compiler", result.stderr)
            self.assertEqual(output.read_bytes(), b"previous bundle")

    def test_invalid_blueprint_fails_and_preserves_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            script, output = self._fixture(
                root,
                {"broken.blp": "using Gtk 4.0;\nGtk.Box { definitely broken\n"},
            )
            output.write_bytes(b"previous bundle")

            result = self._run(script, self._compiler())

            self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(output.read_bytes(), b"previous bundle")

    def test_build_compiles_every_blueprint_under_stable_ui_alias(self) -> None:
        if shutil.which("gresource") is None:
            self.skipTest("gresource is required to inspect the compiled bundle")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            script, output = self._fixture(
                root,
                {
                    "first.blp": "using Gtk 4.0;\nGtk.Box {}\n",
                    "nested/second.blp": "using Gtk 4.0;\nGtk.Label {}\n",
                },
            )

            result = self._run(script, self._compiler())

            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            listed = subprocess.run(
                ["gresource", "list", str(output)],
                capture_output=True,
                text=True,
                check=True,
            ).stdout.splitlines()
            self.assertIn(f"{RESOURCE_PREFIX}/ui/first.ui", listed)
            self.assertIn(f"{RESOURCE_PREFIX}/ui/nested/second.ui", listed)

    def test_repeat_build_bundles_the_newest_blueprint_output(self) -> None:
        if shutil.which("gresource") is None:
            self.skipTest("gresource is required to inspect the compiled bundle")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            script, output = self._fixture(
                root,
                {"sample.blp": ('using Gtk 4.0;\nGtk.Label { label: "first build"; }\n')},
            )
            compiler = self._compiler()
            first = self._run(script, compiler)
            self.assertEqual(first.returncode, 0, first.stdout + first.stderr)

            (root / "resources" / "ui" / "sample.blp").write_text(
                'using Gtk 4.0;\nGtk.Label { label: "second build"; }\n'
            )
            second = self._run(script, compiler)
            self.assertEqual(second.returncode, 0, second.stdout + second.stderr)

            generated = subprocess.run(
                [
                    "gresource",
                    "extract",
                    str(output),
                    f"{RESOURCE_PREFIX}/ui/sample.ui",
                ],
                capture_output=True,
                text=True,
                check=True,
            ).stdout
            self.assertIn("second build", generated)
            self.assertNotIn("first build", generated)


@unittest.skipUnless(GTK_AVAILABLE, "GTK resource loading needs PyGObject")
class ResourceLoadingTests(unittest.TestCase):
    def _bundle_without_templates(self, root: Path) -> Path:
        (root / "placeholder.txt").write_text("valid resource bundle\n")
        manifest = root / "incomplete.gresource.xml"
        manifest.write_text(
            """<?xml version="1.0" encoding="UTF-8"?>
<gresources>
  <gresource prefix="/org/uvr/UltimateVocalRemover">
    <file>placeholder.txt</file>
  </gresource>
</gresources>
"""
        )
        bundle = root / "incomplete.gresource"
        subprocess.run(
            [
                "glib-compile-resources",
                f"--sourcedir={root}",
                f"--target={bundle}",
                str(manifest),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        return bundle

    def _assert_actionable_incomplete_bundle_error(self, bundle: Path, statement: str) -> None:
        env = os.environ.copy()
        for name in ("DISPLAY", "WAYLAND_DISPLAY", "DBUS_SESSION_BUS_ADDRESS"):
            env.pop(name, None)
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                (
                    "import sys\n"
                    "import ui.resources as resources\n"
                    "resources._RESOURCE_PATH = sys.argv[1]\n"
                    "resources._bundle_registered = False\n"
                    "try:\n"
                    f"    {statement}\n"
                    "except RuntimeError as exc:\n"
                    "    assert './resources/compile_resources.sh' in str(exc), str(exc)\n"
                    "else:\n"
                    "    raise AssertionError('expected actionable RuntimeError')\n"
                ),
                str(bundle),
            ],
            cwd=REPO_ROOT,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_console_import_rejects_valid_bundle_missing_its_template(self) -> None:
        if shutil.which("glib-compile-resources") is None:
            self.skipTest("glib-compile-resources is required for this resource test")
        with tempfile.TemporaryDirectory() as tmp:
            bundle = self._bundle_without_templates(Path(tmp))
            self._assert_actionable_incomplete_bundle_error(
                bundle, "from ui.widgets.console import ConsoleView"
            )

    def test_shared_template_widget_imports_reject_an_incomplete_bundle(self) -> None:
        """Template subclasses must validate their exact resource before declaration."""
        if shutil.which("glib-compile-resources") is None:
            self.skipTest("glib-compile-resources is required for this resource test")
        modules = (
            "ui.widgets.format_row",
            "ui.widgets.vocal_split_row",
            "ui.widgets.file_chooser",
            "ui.widgets.dual_inputs",
        )
        with tempfile.TemporaryDirectory() as tmp:
            bundle = self._bundle_without_templates(Path(tmp))
            for module in modules:
                with self.subTest(module=module):
                    self._assert_actionable_incomplete_bundle_error(
                        bundle, f"__import__({module!r})"
                    )

    def test_load_builder_rejects_valid_bundle_missing_its_document(self) -> None:
        if shutil.which("glib-compile-resources") is None:
            self.skipTest("glib-compile-resources is required for this resource test")
        with tempfile.TemporaryDirectory() as tmp:
            bundle = self._bundle_without_templates(Path(tmp))
            self._assert_actionable_incomplete_bundle_error(
                bundle,
                "from ui.template import load_builder; load_builder('missing-document')",
            )

    def test_require_resource_bundle_has_an_actionable_display_free_error(self) -> None:
        import ui.resources as resources

        with (
            mock.patch.object(resources, "_RESOURCE_PATH", "/missing/uvr.gresource"),
            mock.patch.object(resources, "_bundle_registered", False),
        ):
            with self.assertRaisesRegex(RuntimeError, r"\./resources/compile_resources\.sh"):
                resources.require_resource_bundle()

    def test_console_module_imports_without_a_display(self) -> None:
        env = os.environ.copy()
        for name in ("DISPLAY", "WAYLAND_DISPLAY", "DBUS_SESSION_BUS_ADDRESS"):
            env.pop(name, None)
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                (
                    "import gi; "
                    "gi.require_version('Gdk', '4.0'); "
                    "from gi.repository import Gdk; "
                    "assert Gdk.Display.get_default() is None; "
                    "from ui.widgets.console import ConsoleView; "
                    "assert ConsoleView.__name__ == 'ConsoleView'; "
                    "assert Gdk.Display.get_default() is None"
                ),
            ],
            cwd=REPO_ROOT,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_typed_builder_lookup_accepts_expected_type_and_rejects_wrong_type(
        self,
    ) -> None:
        from gi.repository import Gtk

        from ui.template import object_from_builder

        builder = Gtk.Builder.new_from_string(
            '<interface><object class="GtkTextBuffer" id="buffer"/></interface>',
            -1,
        )
        buffer = object_from_builder(builder, "buffer", Gtk.TextBuffer)
        self.assertIsInstance(buffer, Gtk.TextBuffer)
        with self.assertRaisesRegex(TypeError, r"buffer: expected TextView, got TextBuffer"):
            object_from_builder(builder, "buffer", Gtk.TextView)


if __name__ == "__main__":
    unittest.main()
