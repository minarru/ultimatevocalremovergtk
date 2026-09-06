"""Source launches rebuild required layouts before starting the UI."""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = ROOT / "run_uvr.sh"


class ResourceLauncherTests(unittest.TestCase):
    def setUp(self) -> None:
        scratch = tempfile.TemporaryDirectory(prefix="uvr launcher ")
        self.addCleanup(scratch.cleanup)
        self.root = Path(scratch.name)
        for directory in ("packaging", ".venv/bin", "resources/ui", "resources/icons", "ui/data"):
            (self.root / directory).mkdir(parents=True)
        shutil.copy2(LAUNCHER, self.root / "run_uvr.sh")
        shutil.copy2(ROOT / "packaging/desktop_entry.sh", self.root / "packaging/desktop_entry.sh")
        self.source = self.root / "resources/ui/sample.blp"
        self.source.write_text("using Gtk 4.0; Gtk.Box {}\n")
        (self.root / "resources/style.css").write_text("window {}\n")
        self.bundle = self.root / "ui/data/uvr.gresource"
        self.bundle.write_bytes(b"previous bundle")
        # The compiler and UI interpreter are external process boundaries.
        # Their markers expose whether the real launcher starts them in order.
        compiler = self.root / "resources/compile_resources.sh"
        compiler.write_text(
            '#!/usr/bin/env bash\nset -eu\n'
            'printf "compile\\n" >> "$LAUNCH_EVENTS"\n'
            'if [[ "$COMPILER_RESULT" != 0 ]]; then exit "$COMPILER_RESULT"; fi\n'
            'printf "rebuilt bundle" > "$(dirname "$0")/../ui/data/uvr.gresource"\n'
        )
        interpreter = self.root / ".venv/bin/python"
        interpreter.write_text(
            '#!/usr/bin/env bash\nset -eu\n'
            'printf "launch\\n" >> "$LAUNCH_EVENTS"\n'
            'printf "%s\\n" "$@" > "$LAUNCH_ARGUMENTS"\n'
        )
        compiler.chmod(0o755)
        interpreter.chmod(0o755)
        for path in self.root.rglob("*"):
            if path.is_file():
                os.utime(path, (100, 100))
        os.utime(self.bundle, (200, 200))
        self.events = self.root / "events"
        self.arguments = self.root / "arguments"

    def launch(self, compiler_result: int = 0) -> subprocess.CompletedProcess[str]:
        env = os.environ.copy()
        for key in ("G_MESSAGES_DEBUG", "UVR_LOG_FILE", "UVR_VERBOSE"):
            env.pop(key, None)
        env.update(
            UVR_SKIP_CHECK="1",
            UVR_AUTO_REBUILD="never",
            XDG_DATA_HOME=str(self.root / "data"),
            XDG_CACHE_HOME=str(self.root / "cache"),
            LAUNCH_EVENTS=str(self.events),
            LAUNCH_ARGUMENTS=str(self.arguments),
            COMPILER_RESULT=str(compiler_result),
        )
        return subprocess.run(
            ["bash", str(self.root / "run_uvr.sh"), "argument with spaces"],
            env=env,
            cwd=self.root,
            text=True,
            capture_output=True,
            check=False,
            timeout=20,
        )

    def test_current_bundle_starts_ui_without_compiler(self) -> None:
        result = self.launch(compiler_result=23)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.events.read_text(), "launch\n")
        self.assertEqual(self.arguments.read_text(), "-m\nui\nargument with spaces\n")

    def test_missing_bundle_is_built_before_ui_starts(self) -> None:
        self.bundle.unlink()
        result = self.launch()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.events.read_text(), "compile\nlaunch\n")
        self.assertEqual(self.bundle.read_bytes(), b"rebuilt bundle")

    def test_changed_blueprint_is_built_before_ui_starts(self) -> None:
        os.utime(self.source, (300, 300))
        result = self.launch()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.events.read_text(), "compile\nlaunch\n")
        self.assertEqual(self.bundle.read_bytes(), b"rebuilt bundle")

    def test_failed_build_prevents_ui_start_and_keeps_previous_bundle(self) -> None:
        os.utime(self.source, (300, 300))
        result = self.launch(compiler_result=23)
        self.assertEqual(result.returncode, 23, result.stderr)
        self.assertEqual(self.events.read_text(), "compile\n")
        self.assertFalse(self.arguments.exists())
        self.assertEqual(self.bundle.read_bytes(), b"previous bundle")
