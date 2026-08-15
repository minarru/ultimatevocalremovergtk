"""Unit tests for the headless CLI front end (no GPU / no real separation)."""

from __future__ import annotations
import typing

import io
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
                    "--json-out",
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

    @mock.patch("cli.bench.subprocess.run")
    @mock.patch("cli.bench.compare_stem_dirs")
    def test_bench_ab_json_owns_stdout(
        self, mock_compare: typing.Any, mock_run: typing.Any
    ) -> None:
        mock_run.return_value = mock.Mock(returncode=0)
        from core.bench_metrics import StemCompareReport

        mock_compare.return_value = StemCompareReport(pairs=[], only_a=[], only_b=[])
        with tempfile.TemporaryDirectory() as tmp:
            wav = os.path.join(tmp, "in.wav")
            open(wav, "wb").close()
            out = os.path.join(tmp, "ab")
            with mock.patch("sys.stdout", new_callable=io.StringIO) as mock_stdout:
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
                    ]
                )
            self.assertEqual(code, 0)
            payload = json.loads(mock_stdout.getvalue())
            self.assertIn("speedup_a_over_b", payload)
            self.assertEqual(mock_run.call_count, 2)
            for call in mock_run.call_args_list:
                child_argv = call.args[0]
                self.assertIn("--quiet", child_argv)
                self.assertIs(call.kwargs.get("stdout"), subprocess.DEVNULL)

    @mock.patch("cli.bench.subprocess.run")
    def test_bench_ab_json_leg_failure_emits_document(
        self, mock_run: typing.Any
    ) -> None:
        mock_run.return_value = mock.Mock(returncode=3)
        with tempfile.TemporaryDirectory() as tmp:
            wav = os.path.join(tmp, "in.wav")
            open(wav, "wb").close()
            out = os.path.join(tmp, "ab")
            with mock.patch("sys.stdout", new_callable=io.StringIO) as mock_stdout:
                with mock.patch("sys.stderr", new_callable=io.StringIO) as mock_stderr:
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
                        ]
                    )
            self.assertEqual(code, 1)
            payload = json.loads(mock_stdout.getvalue())
            self.assertIs(payload["ok"], False)
            self.assertIn("A failed with exit code 3", payload["error"]["message"])
            self.assertIn("error:", mock_stderr.getvalue())
            self.assertEqual(mock_stderr.getvalue().count("error:"), 1)

    @mock.patch("cli.bench.subprocess.run")
    def test_bench_ab_json_out_failure_emits_one_document(
        self, mock_run: typing.Any
    ) -> None:
        mock_run.return_value = mock.Mock(returncode=0)
        with tempfile.TemporaryDirectory() as tmp:
            wav = os.path.join(tmp, "in.wav")
            open(wav, "wb").close()
            out = os.path.join(tmp, "ab")
            json_out = os.path.join(tmp, "missing", "summary.json")
            with mock.patch("sys.stdout", new_callable=io.StringIO) as mock_stdout:
                with mock.patch("sys.stderr", new_callable=io.StringIO) as mock_stderr:
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
                            "--json-out",
                            json_out,
                        ]
                    )
            self.assertEqual(code, 2)
            payload = json.loads(mock_stdout.getvalue())
            self.assertIs(payload["ok"], False)
            self.assertEqual(payload["error"]["type"], "FileNotFoundError")
            self.assertIn(json_out, payload["error"]["message"])
            self.assertEqual(mock_stderr.getvalue().count("error:"), 1)

    @mock.patch("cli.bench.subprocess.run")
    def test_bench_ab_child_130_skips_leg_b(self, mock_run: typing.Any) -> None:
        mock_run.return_value = mock.Mock(returncode=130)
        with tempfile.TemporaryDirectory() as tmp:
            wav = os.path.join(tmp, "in.wav")
            open(wav, "wb").close()
            out = os.path.join(tmp, "ab")
            with mock.patch("sys.stdout", new_callable=io.StringIO) as mock_stdout:
                with mock.patch("sys.stderr", new_callable=io.StringIO) as mock_stderr:
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
                        ]
                    )
            self.assertEqual(code, 130)
            self.assertEqual(mock_run.call_count, 1)
            payload = json.loads(mock_stdout.getvalue())
            self.assertIs(payload["ok"], False)
            self.assertTrue(payload["stopped"])
            self.assertIn("interrupted", payload["error"]["message"].lower())
            self.assertIn("interrupted", mock_stderr.getvalue().lower())


class ReportingFlagTests(unittest.TestCase):
    def test_json_is_boolean_on_separate(self) -> None:
        from cli.main import build_parser

        args = build_parser().parse_args(["separate", "a.wav", "-o", "/tmp/o", "--json"])
        self.assertIs(args.json, True)

    def test_bench_ab_uses_json_out_for_the_file(self) -> None:
        from cli.main import build_parser

        args = build_parser().parse_args(
            ["bench-ab", "a.wav", "-o", "/tmp/o", "--env", "A=1", "--env", "B=2",
             "--json-out", "/tmp/s.json"]
        )
        self.assertEqual(args.json_out, "/tmp/s.json")
        self.assertIs(args.json, False)

    def test_parser_builds_without_conflicts(self) -> None:
        from cli.main import build_parser

        build_parser()  # raises argparse.ArgumentError on a duplicate option string


class ProgressPrinterTests(unittest.TestCase):
    def test_none_when_not_a_tty(self) -> None:
        import io

        from cli.reporting import make_progress_printer

        self.assertIsNone(make_progress_printer(io.StringIO()))

    def test_writes_carriage_returned_line_on_a_tty(self) -> None:
        from cli.reporting import make_progress_printer

        class _Tty(io.StringIO):
            def isatty(self) -> bool:
                return True

        stream = _Tty()
        printer = make_progress_printer(stream)
        self.assertIsNotNone(printer)
        assert printer is not None
        printer(0.5, detail="MDX pass 1/2")
        written = stream.getvalue()
        self.assertIn("50.0%", written)
        self.assertIn("MDX pass 1/2", written)
        self.assertTrue(written.startswith("\r"))

    def test_combine_kwargs_appear_in_the_line(self) -> None:
        import io

        from cli.reporting import make_progress_printer

        class _Tty(io.StringIO):
            def isatty(self) -> bool:
                return True

        stream = _Tty()
        printer = make_progress_printer(stream)
        assert printer is not None
        printer(0.8, combine_index=1, combine_total=3, detail="stems")
        self.assertIn("combine 1/3", stream.getvalue())


class JsonSeparateTests(unittest.TestCase):
    @mock.patch("cli.separate.run_separation_sync")
    @mock.patch("cli.separate.build_settings")
    @mock.patch("cli.separate.check_runtime_deps", return_value=None)
    def test_json_print_settings_is_one_document(
        self,
        _mock_deps: typing.Any,
        mock_build: typing.Any,
        mock_run: typing.Any,
    ) -> None:
        settings = Settings.defaults()
        mock_build.return_value = settings
        mock_run.return_value = HeadlessResult(
            ok=True, elapsed_s=1.5, export_path="/tmp/o"
        )
        with tempfile.NamedTemporaryFile(suffix=".wav") as fh:
            with mock.patch("sys.stdout", new_callable=io.StringIO) as mock_stdout:
                code = main(
                    [
                        "separate",
                        fh.name,
                        "-o",
                        "/tmp/o",
                        "--method",
                        "mdx",
                        "--json",
                        "--print-settings",
                    ]
                )
        self.assertEqual(code, 0)
        payload = json.loads(mock_stdout.getvalue())
        self.assertIs(payload["ok"], True)
        self.assertIn("settings", payload)
        self.assertIsInstance(payload["settings"], dict)
        mock_run.assert_called_once()
        self.assertIs(mock_run.call_args.kwargs.get("print_console"), False)

    @mock.patch("cli.separate.check_runtime_deps", return_value=None)
    def test_json_missing_input_emits_failure_document(
        self, _mock_deps: typing.Any
    ) -> None:
        missing = "/tmp/uvr-cli-missing-input-does-not-exist.wav"
        with mock.patch("sys.stdout", new_callable=io.StringIO) as mock_stdout:
            with mock.patch("sys.stderr", new_callable=io.StringIO) as mock_stderr:
                code = main(
                    ["separate", missing, "-o", "/tmp/o", "--json"]
                )
        self.assertEqual(code, 2)
        payload = json.loads(mock_stdout.getvalue())
        self.assertIs(payload["ok"], False)
        self.assertIn(missing, payload["error"]["message"])
        self.assertIn("error:", mock_stderr.getvalue())

    def test_stopped_run_exits_130_and_emits_json(self) -> None:
        from cli.main import main
        from core.headless_run import HeadlessResult

        result = HeadlessResult(
            ok=False,
            elapsed_s=0.5,
            export_path="/tmp/o",
            stopped=True,
            interrupted=True,
        )
        buf = io.StringIO()
        err = io.StringIO()
        with mock.patch("cli.separate.check_runtime_deps", return_value=None), \
             mock.patch("cli.separate.os.path.isfile", return_value=True), \
             mock.patch("cli.separate.os.makedirs"), \
             mock.patch("cli.separate.build_settings", return_value=Settings()), \
             mock.patch("cli.separate.run_separation_sync", return_value=result), \
             mock.patch("sys.stdout", buf), \
             mock.patch("sys.stderr", err):
            code = main(["separate", "a.wav", "-o", "/tmp/o", "--json"])
        self.assertEqual(code, 130)
        payload = json.loads(buf.getvalue())
        self.assertFalse(payload["ok"])
        self.assertTrue(payload["stopped"])
        self.assertIn("stopped", err.getvalue().lower())

    def test_main_keyboard_interrupt_emits_json_130(self) -> None:
        buf = io.StringIO()
        err = io.StringIO()
        with mock.patch(
            "cli.separate.check_runtime_deps",
            side_effect=KeyboardInterrupt,
        ), mock.patch("sys.stdout", buf), mock.patch("sys.stderr", err):
            code = main(["separate", "a.wav", "-o", "/tmp/o", "--json"])
        self.assertEqual(code, 130)
        payload = json.loads(buf.getvalue())
        self.assertFalse(payload["ok"])
        self.assertTrue(payload["stopped"])
        self.assertIn("interrupted", err.getvalue().lower())

    def test_json_set_ensemble_mode_emits_failure_document(self) -> None:
        """--set process.method=Ensemble Mode must not leave --json stdout empty."""
        buf = io.StringIO()
        err = io.StringIO()
        with mock.patch("cli.separate.check_runtime_deps", return_value=None), \
             mock.patch("cli.separate.os.path.isfile", return_value=True), \
             mock.patch("cli.separate.os.makedirs"), \
             mock.patch("cli.separate.build_settings", return_value=Settings()), \
             mock.patch("sys.stdout", buf), \
             mock.patch("sys.stderr", err):
            code = main(
                [
                    "separate",
                    "a.wav",
                    "-o",
                    "/tmp/o",
                    "--json",
                    "--set",
                    "process.method=Ensemble Mode",
                ]
            )
        self.assertEqual(code, 2)
        payload = json.loads(buf.getvalue())
        self.assertIs(payload["ok"], False)
        self.assertIn("ensemble", payload["error"]["message"].lower())
        self.assertEqual(payload["error"]["type"], "ValueError")
        self.assertIn("error:", err.getvalue())
        self.assertNotIn("Traceback", err.getvalue())


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
