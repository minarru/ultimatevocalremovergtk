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

from cli.bench import build_separate_argv
from cli.main import build_parser, main
from cli.process_flags import collect_overrides
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

    def test_vocal_split_requires_value(self) -> None:
        parser = build_parser()
        with self.assertRaises(SystemExit):
            parser.parse_args(
                ["separate", "--vocal-split", "song.wav", "-o", "/tmp/x"]
            )

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

    def test_bench_ab_forwards_process_and_long_chunk_flags(self) -> None:
        parser = build_parser()
        args = parser.parse_args(
            [
                "bench-ab",
                "in.wav",
                "-o",
                "/tmp/out",
                "--gpu",
                "--format",
                "flac",
                "--set",
                "process.normalization=true",
                "--set",
                "process.match_mix_level=true",
                "--vocal-split",
                "Splitter X",
                "--long-chunk-seconds",
                "90",
                "--long-chunk-overlap",
                "2.5",
                "--env",
                "UVR_AUTOCAST=0",
                "--env",
                "UVR_AUTOCAST=1",
            ]
        )
        argv = build_separate_argv(
            inputs=["in.wav"],
            output="/tmp/out/a",
            method=args.method,
            model=args.model,
            settings=args.settings,
            stems=args.stems,
            print_settings=args.print_settings,
            long_chunk_seconds=args.long_chunk_seconds,
            long_chunk_overlap=args.long_chunk_overlap,
            overrides=collect_overrides(args),
            vocal_split=args.vocal_split,
        )
        self.assertIn("--long-chunk-seconds", argv)
        self.assertIn("90.0", argv)
        self.assertIn("--long-chunk-overlap", argv)
        self.assertIn("2.5", argv)
        self.assertIn("--vocal-split", argv)
        self.assertIn("Splitter X", argv)
        self.assertIn("process.use_gpu=true", argv)
        self.assertIn("process.save_format=FLAC", argv)
        self.assertIn("process.normalization=true", argv)
        self.assertIn("process.match_mix_level=true", argv)

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

    @mock.patch("cli.separate.run_separation_sync")
    @mock.patch("cli.separate.resolve_vocal_splitter", return_value="MDX-Net: Splitter X")
    @mock.patch("cli.separate.build_settings")
    def test_separate_vocal_split_precedence(
        self,
        mock_build: typing.Any,
        mock_resolve: typing.Any,
        mock_run: typing.Any,
    ) -> None:
        settings = Settings.defaults()
        mock_build.return_value = settings
        mock_run.return_value = HeadlessResult(
            ok=True, elapsed_s=0.1, export_path="/tmp/out"
        )
        with tempfile.NamedTemporaryFile(suffix=".wav") as fh:
            with mock.patch("core.model_data.ModelRepository"):
                code = main(
                    [
                        "separate",
                        fh.name,
                        "-o",
                        "/tmp/out",
                        "--method",
                        "mdx",
                        "--vocal-split",
                        "Splitter X",
                        "--set",
                        "process.vocal_splitter_enabled=false",
                    ]
                )
        self.assertEqual(code, 0)
        mock_resolve.assert_called_once()
        self.assertEqual(settings.process.vocal_splitter, "MDX-Net: Splitter X")
        self.assertIs(settings.process.vocal_splitter_enabled, False)

    @mock.patch("cli.separate.run_separation_sync")
    @mock.patch("cli.separate.resolve_vocal_splitter", return_value="MDX-Net: Splitter X")
    @mock.patch("cli.separate.build_settings")
    def test_separate_vocal_split_resolves_offline(
        self,
        mock_build: typing.Any,
        mock_resolve: typing.Any,
        mock_run: typing.Any,
    ) -> None:
        settings = Settings.defaults()
        mock_build.return_value = settings
        mock_run.return_value = HeadlessResult(
            ok=True, elapsed_s=0.1, export_path="/tmp/out"
        )

        def _spy(_model: str, _settings: Settings, _repo: typing.Any) -> str:
            self.assertEqual(os.environ.get("UVR_DISABLE_POLITREES"), "1")
            self.assertEqual(os.environ.get("UVR_DISABLE_MVSEPLESS"), "1")
            return "MDX-Net: Splitter X"

        mock_resolve.side_effect = _spy
        with tempfile.NamedTemporaryFile(suffix=".wav") as fh:
            with mock.patch("core.model_data.ModelRepository"):
                code = main(
                    [
                        "separate",
                        fh.name,
                        "-o",
                        "/tmp/out",
                        "--method",
                        "mdx",
                        "--vocal-split",
                        "Splitter X",
                    ]
                )
        self.assertEqual(code, 0)
        self.assertEqual(settings.process.vocal_splitter, "MDX-Net: Splitter X")
        self.assertIs(settings.process.vocal_splitter_enabled, True)

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
                    "--gpu",
                    "--format",
                    "flac",
                    "--set",
                    "process.normalization=true",
                    "--vocal-split",
                    "Splitter X",
                    "--long-chunk-seconds",
                    "60",
                    "--long-chunk-overlap",
                    "1",
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
            for call in mock_run.call_args_list:
                child_argv = call.args[0]
                self.assertIn("--vocal-split", child_argv)
                self.assertIn("Splitter X", child_argv)
                self.assertIn("--long-chunk-seconds", child_argv)
                self.assertIn("60.0", child_argv)
                self.assertIn("--long-chunk-overlap", child_argv)
                self.assertIn("1.0", child_argv)
                self.assertIn("process.use_gpu=true", child_argv)
                self.assertIn("process.save_format=FLAC", child_argv)
                self.assertIn("process.normalization=true", child_argv)
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
