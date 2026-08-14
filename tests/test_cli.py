"""Unit tests for the headless CLI front end (no GPU / no real separation)."""

from __future__ import annotations
import typing

import json
import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from cli.main import build_parser, main
from core.headless_run import HeadlessResult
from core.settings import Settings


class CliArgparseTests(unittest.TestCase):
    def test_separate_parser(self) -> None:
        parser = build_parser()
        args = parser.parse_args(
            ["separate", "in.wav", "-o", "/tmp/out", "--method", "mdx", "--cpu"]
        )
        self.assertEqual(args.command, "separate")
        self.assertEqual(args.method, "mdx")
        self.assertTrue(args.cpu)

    def test_bench_ab_requires_two_env(self) -> None:
        parser = build_parser()
        args = parser.parse_args(
            [
                "bench-ab",
                "in.wav",
                "-o",
                "/tmp/out",
                "--env",
                "UVR_AUTOCAST=0",
                "--env",
                "UVR_AUTOCAST=1",
            ]
        )
        self.assertEqual(len(args.env), 2)

    @mock.patch("cli.separate.run_separation_sync")
    @mock.patch("cli.separate.build_settings")
    def test_separate_main_success(self, mock_build: typing.Any, mock_run: typing.Any) -> None:
        mock_build.return_value = Settings.defaults()
        mock_run.return_value = HeadlessResult(
            ok=True, elapsed_s=1.25, export_path="/tmp/out"
        )
        with tempfile.NamedTemporaryFile(suffix=".wav") as fh:
            code = main(["separate", fh.name, "-o", "/tmp/out", "--method", "mdx"])
        self.assertEqual(code, 0)
        mock_run.assert_called_once()

    @mock.patch("cli.bench.subprocess.run")
    @mock.patch("cli.bench.compare_stem_dirs")
    def test_bench_ab_subprocess_wiring(self, mock_compare: typing.Any, mock_run: typing.Any) -> None:
        mock_run.return_value = mock.Mock(returncode=0)
        from core.bench_metrics import StemCompareReport

        mock_compare.return_value = StemCompareReport(pairs=[], only_a=[], only_b=[])
        with tempfile.TemporaryDirectory() as tmp:
            wav = os.path.join(tmp, "in.wav")
            open(wav, "wb").close()
            out = os.path.join(tmp, "ab")
            summary = os.path.join(tmp, "summary.json")
            code = main(
                [
                    "bench-ab",
                    wav,
                    "-o",
                    out,
                    "--env",
                    "UVR_AUTOCAST=0",
                    "--env",
                    "UVR_AUTOCAST=1",
                    "--json",
                    summary,
                ]
            )
            self.assertEqual(code, 0)
            self.assertEqual(mock_run.call_count, 2)
            env0 = mock_run.call_args_list[0].kwargs["env"]
            env1 = mock_run.call_args_list[1].kwargs["env"]
            self.assertEqual(env0.get("UVR_AUTOCAST"), "0")
            self.assertEqual(env1.get("UVR_AUTOCAST"), "1")
            with open(summary, encoding="utf-8") as fh:
                payload = json.load(fh)
            self.assertIn("speedup_a_over_b", payload)


class TrampolineTests(unittest.TestCase):
    def test_core_cli_delegates_to_cli_main(self) -> None:
        import core.cli

        with mock.patch("cli.main.main", return_value=7) as delegate:
            self.assertEqual(core.cli.main(["separate", "x", "-o", "y"]), 7)
        delegate.assert_called_once_with(["separate", "x", "-o", "y"])

    def test_importing_core_does_not_import_cli(self) -> None:
        script = (
            "import sys; import core; "
            "print('cli' in sys.modules or 'cli.main' in sys.modules)"
        )
        proc = subprocess.run(
            [sys.executable, "-c", script],
            cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            capture_output=True,
            text=True,
            check=True,
        )
        self.assertEqual(proc.stdout.strip(), "False")


if __name__ == "__main__":
    unittest.main()
