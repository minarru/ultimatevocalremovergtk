from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


_ROOT = Path(__file__).resolve().parents[1]


class UvrLauncherTests(unittest.TestCase):
    def _project(self, base: Path) -> tuple[Path, Path, Path]:
        project = base / "project"
        caller = base / "caller"
        python = project / ".venv" / "bin" / "python"
        python.parent.mkdir(parents=True)
        caller.mkdir()
        shutil.copy2(_ROOT / "uvr", project / "uvr")
        python.write_text(
            "#!/bin/sh\nprintf 'cwd=%s\\n' \"$PWD\"\nprintf 'pythonpath=%s\\n' \"$PYTHONPATH\"\nprintf 'arg=%s\\n' \"$@\"\n",
            encoding="utf-8",
        )
        python.chmod(0o755)
        return project, caller, python

    def test_launcher_preserves_callers_working_directory_and_relative_arguments(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            project, caller, _python = self._project(base)

            completed = subprocess.run(
                [str(project / "uvr"), "audio", "inspect", "relative/input.wav"],
                cwd=caller,
                check=True,
                capture_output=True,
                text=True,
                env={**os.environ, "PYTHONPATH": "existing-path"},
            )

        self.assertEqual(
            completed.stdout.splitlines(),
            [
                f"cwd={caller}",
                f"pythonpath={project}:existing-path",
                "arg=-m", "arg=cli", "arg=audio", "arg=inspect",
                "arg=relative/input.wav",
            ],
        )
        self.assertEqual(completed.stderr, "")

    def test_symlinked_launcher_finds_checkout(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            project, caller, _python = self._project(base)
            link = base / "bin" / "uvr"
            link.parent.mkdir()
            link.symlink_to(project / "uvr")
            completed = subprocess.run(
                [str(link), "--version"], cwd=caller, check=True,
                capture_output=True, text=True,
            )
        self.assertIn(f"pythonpath={project}", completed.stdout)

    def test_gui_dispatches_to_repair_launcher(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            project, caller, _python = self._project(base)
            repair = project / "run_uvr.sh"
            repair.write_text(
                "#!/bin/sh\nprintf 'cwd=%s\\n' \"$PWD\"\nprintf 'arg=%s\\n' \"$@\"\n",
                encoding="utf-8",
            )
            repair.chmod(0o755)
            completed = subprocess.run(
                [str(project / "uvr"), "gui", "--example"], cwd=caller,
                check=True, capture_output=True, text=True,
            )
        self.assertEqual(
            completed.stdout.splitlines(),
            [f"cwd={caller}", "arg=--example"],
        )


if __name__ == "__main__":
    unittest.main()
