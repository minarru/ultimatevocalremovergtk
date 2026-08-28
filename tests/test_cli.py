from __future__ import annotations

import argparse
import io
import json
import os
import sys
import tempfile
import unittest
import warnings
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import Mock, patch

from cli.job import ResolvedJob
from cli.main import UsageError, build_parser, main
from cli.profiles import LoadedProfile
from core.settings import Settings


class ParserSurfaceTests(unittest.TestCase):
    def test_runtime_hooks_install_before_parser_construction(self) -> None:
        order: list[str] = []

        with patch(
            "core.debug_log.configure_bootstrap",
            side_effect=lambda: order.append("bootstrap"),
        ), patch(
            "core.debug_log.install_runtime_hooks",
            side_effect=lambda: order.append("hooks"),
        ), patch(
            "cli.main.build_parser",
            side_effect=lambda: (
                order.append("parser"),
                (_ for _ in ()).throw(RuntimeError("parser failed")),
            )[1],
        ):
            with self.assertRaisesRegex(RuntimeError, "parser failed"):
                main([])

        self.assertEqual(order, ["bootstrap", "hooks", "parser"])

    def test_gui_command_preserves_cli_diagnostic_overrides(self) -> None:
        from cli.main import cmd_gui

        with patch.object(
            sys,
            "argv",
            ["uvr", "--trace", "--debug-sensitive", "gui"],
        ), patch("ui.application.main", return_value=0) as gui_main:
            self.assertEqual(cmd_gui(argparse.Namespace()), 0)

        gui_main.assert_called_once_with(argv=["uvr"], configure_diagnostics=False)

    def test_diagnostic_flags_parse_globally_and_after_processing_command(self) -> None:
        parser = build_parser()

        global_args = parser.parse_args(
            [
                "--trace",
                "--debug-sensitive",
                "--log-file",
                "/tmp/global.log",
                "settings",
                "show",
            ]
        )
        self.assertTrue(global_args.global_trace)
        self.assertTrue(global_args.global_debug_sensitive)
        self.assertEqual(global_args.global_log_file, "/tmp/global.log")

        command_args = parser.parse_args(
            [
                "separate",
                "input.wav",
                "-o",
                "out",
                "--model",
                "mdx:test",
                "--debug",
                "--log-file",
                "/tmp/command.log",
            ]
        )
        self.assertTrue(command_args.debug)
        self.assertFalse(command_args.trace)
        self.assertEqual(command_args.log_file, "/tmp/command.log")

    def test_debug_and_trace_are_mutually_exclusive(self) -> None:
        parser = build_parser()

        with self.assertRaisesRegex(UsageError, "not allowed with argument"):
            parser.parse_args(["--debug", "--trace", "settings", "show"])

    def test_cli_configures_diagnostics_without_treating_verbose_as_debug(self) -> None:
        from types import SimpleNamespace

        args = SimpleNamespace(
            global_report=None,
            global_quiet=False,
            global_verbose=True,
            global_debug=True,
            global_trace=False,
            global_debug_sensitive=True,
            global_log_file="/tmp/uvr-cli.log",
            debug=False,
            trace=False,
            debug_sensitive=False,
            log_file=None,
            func=lambda _args: 0,
        )
        parser = Mock()
        parser.parse_args.return_value = args
        settings = Settings.defaults()

        with patch("cli.main.build_parser", return_value=parser), patch(
            "core.settings.Settings.load", return_value=settings
        ), patch("core.debug_log.configure_from_settings") as configure, patch(
            "core.debug_log.install_runtime_hooks"
        ) as install_hooks:
            self.assertEqual(main([]), 0)

        configure.assert_called_once_with(
            settings,
            level="debug",
            include_sensitive_details=True,
            log_file="/tmp/uvr-cli.log",
        )
        install_hooks.assert_called_once_with()

    def test_main_records_command_lifecycle_with_one_operation_id(self) -> None:
        from types import SimpleNamespace

        from core import debug_log

        with tempfile.TemporaryDirectory() as tmp:
            log_path = os.path.join(tmp, "uvr.log")
            def command(_args: object) -> int:
                debug_log.log_event("settings", "nested_command_work")
                return 0

            args = SimpleNamespace(
                command="settings",
                global_report=None,
                global_quiet=False,
                global_verbose=False,
                global_debug=True,
                global_trace=False,
                global_debug_sensitive=False,
                global_log_file=log_path,
                debug=False,
                trace=False,
                debug_sensitive=False,
                log_file=None,
                report="human",
                quiet=False,
                verbose=False,
                job_id="cli-operation",
                func=command,
            )
            parser = Mock()
            parser.parse_args.return_value = args

            with warnings.catch_warnings(record=True) as captured, patch(
                "cli.main.build_parser", return_value=parser
            ), patch(
                "core.settings.Settings.load", return_value=Settings.defaults()
            ):
                warnings.simplefilter("always")
                self.assertEqual(main([]), 0)

            self.assertFalse(
                any("requires PyGObject" in str(item.message) for item in captured)
            )

            diagnostic = Path(log_path).read_text(encoding="utf-8")
            self.assertIn("event=command_started", diagnostic)
            self.assertIn("event=command_completed", diagnostic)
            self.assertIn("event=nested_command_work", diagnostic)
            lifecycle = [
                line for line in diagnostic.splitlines()
                if any(
                    event in line
                    for event in (
                        "event=command_started",
                        "event=nested_command_work",
                        "event=command_completed",
                    )
                )
            ]
            self.assertEqual(len(lifecycle), 3)
            self.assertTrue(
                all("operation=cli-operation" in line for line in lifecycle)
            )
            self.assertIsNone(debug_log.current_operation_id())
            debug_log.configure(level="errors", log_file="")

    def test_gui_session_policy_changes_do_not_discard_cli_overrides(self) -> None:
        from types import SimpleNamespace

        from core import debug_log

        observed: list[tuple[str, bool]] = []

        def gui_command(_args: object) -> int:
            debug_log.update_policy(level="errors", include_sensitive=False)
            observed.append(
                (debug_log.current_level(), debug_log.include_sensitive())
            )
            return 0

        args = SimpleNamespace(
            command="gui",
            global_report=None,
            global_quiet=False,
            global_verbose=False,
            global_debug=False,
            global_trace=True,
            global_debug_sensitive=True,
            global_log_file="",
            debug=False,
            trace=False,
            debug_sensitive=False,
            log_file=None,
            report="human",
            quiet=False,
            verbose=False,
            job_id="gui-cli-operation",
            func=gui_command,
        )
        parser = Mock()
        parser.parse_args.return_value = args

        with patch("cli.main.build_parser", return_value=parser), patch(
            "core.settings.Settings.load", return_value=Settings.defaults()
        ):
            self.assertEqual(main([]), 0)

        self.assertEqual(observed, [("trace", True)])
        debug_log.configure(level="errors", log_file="")

    def test_public_hierarchy(self) -> None:
        parser = build_parser()
        for argv in (
            ["models", "list"],
            ["ensembles", "list"],
            ["devices", "list"],
            ["settings", "show"],
            ["completion", "bash"],
            ["models", "catalog", "--offline"],
            ["update", "check"],
        ):
            self.assertTrue(callable(parser.parse_args(argv).func))

    def test_separate_has_no_method_or_json_flag(self) -> None:
        parser = build_parser()
        subcommands = next(
            action for action in parser._actions
            if isinstance(action, argparse._SubParsersAction)
        )
        help_text = subcommands.choices["separate"].format_help()
        self.assertNotIn("--method", help_text)
        self.assertNotIn("--json ", help_text)
        self.assertIn("--report", help_text)
        self.assertIn("--accept-inherited", help_text)
        self.assertNotIn("clear process.stem_focus", help_text)
        self.assertIn("process.stem_focus", help_text)

    def test_apollo_registration_and_administration_commands_parse(self) -> None:
        parser = build_parser()
        self.assertEqual(
            parser.parse_args([
                "models", "register", "model.ckpt", "--family", "apollo",
                "--config", "model.json",
            ]).family,
            "apollo",
        )
        for argv in (
            ["models", "configure", "apollo:model", "--reset"],
            ["ensembles", "delete", "mix"],
            ["update", "check"],
        ):
            self.assertTrue(callable(parser.parse_args(argv).func))

    def test_argument_error_is_json_aware(self) -> None:
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = main(["separate", "--report", "json"])
        self.assertEqual(code, 2)
        payload = json.loads(out.getvalue())
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"]["kind"], "usage")
        self.assertEqual(len([line for line in out.getvalue().splitlines() if line.startswith("{")]), 1)

    def test_report_option_is_also_global(self) -> None:
        out = io.StringIO()
        with redirect_stdout(out):
            code = main(["--report", "json", "settings", "show"])
        self.assertEqual(code, 0)
        self.assertTrue(json.loads(out.getvalue())["ok"])


class HumanReportTests(unittest.TestCase):
    def test_fail_records_structured_error_without_contaminating_json_stdout(self) -> None:
        from types import SimpleNamespace

        from cli.reporting import fail
        from core import debug_log

        with tempfile.TemporaryDirectory() as tmp:
            log_path = os.path.join(tmp, "uvr.log")
            debug_log.configure(level="errors", log_file=log_path)
            self.addCleanup(debug_log.configure, level="errors", log_file="")
            args = SimpleNamespace(report="json", quiet=False, job_id="job-9")
            out, err = io.StringIO(), io.StringIO()

            with redirect_stdout(out), redirect_stderr(err):
                code = fail(
                    args,
                    "output write failed",
                    exit_code=2,
                    exc=RuntimeError("boom"),
                    kind="runtime",
                )

            self.assertEqual(code, 2)
            self.assertFalse(json.loads(out.getvalue())["ok"])
            diagnostic = Path(log_path).read_text(encoding="utf-8")
            self.assertIn("event=command_failed", diagnostic)
            self.assertIn("operation=job-9", diagnostic)
            self.assertIn("kind='runtime'", diagnostic)

    def test_single_input_failure_prints_error_on_stderr(self) -> None:
        from cli.reporting import emit_document

        args = argparse.Namespace(report="human", job_id="j")
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            emit_document(
                args,
                {
                    "status": "failed",
                    "elapsed_s": 1.0,
                    "export_path": "/tmp/out",
                    "inputs": [
                        {
                            "input": "/a.wav",
                            "status": "failed",
                            "error": "ONNXRuntimeError: boom",
                        }
                    ],
                },
            )
        self.assertIn("status=failed", out.getvalue())
        self.assertNotIn("ONNXRuntimeError", out.getvalue())
        self.assertIn("error[/a.wav]=ONNXRuntimeError: boom", err.getvalue())

    def test_multi_input_failures_still_print_each_error(self) -> None:
        from cli.reporting import emit_document

        args = argparse.Namespace(report="human", job_id="j")
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            emit_document(
                args,
                {
                    "status": "failed",
                    "inputs": [
                        {"input": "/a.wav", "status": "failed", "error": "bad-a"},
                        {"input": "/b.wav", "status": "failed", "error": "bad-b"},
                    ],
                },
            )
        self.assertIn("inputs=2", out.getvalue())
        self.assertIn("error[/a.wav]=bad-a", err.getvalue())
        self.assertIn("error[/b.wav]=bad-b", err.getvalue())

    def test_single_success_prints_no_error_line(self) -> None:
        from cli.reporting import emit_document

        args = argparse.Namespace(report="human", job_id="j")
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            emit_document(
                args,
                {
                    "status": "success",
                    "inputs": [{"input": "/a.wav", "status": "success", "outputs": []}],
                },
            )
        self.assertIn("status=success", out.getvalue())
        self.assertNotIn("error[", out.getvalue())
        self.assertNotIn("error[", err.getvalue())


def _job(*, inherited: bool = False) -> ResolvedJob:
    settings = Settings.defaults()
    plan = {
        "identity": {"id": "mdx:test", "path": "/models/test.onnx", "hash": "abc"},
        "profile": {"name": "defaults", "source": "built-in"},
        "runtime": {"use_gpu": False, "autocast": False},
        "inputs": [{"input": "/input.wav"}],
        "export_path": "/out",
        "format": "WAV",
        "collision_policy": "fail",
    }
    effective = Mock()
    effective.diagnostics = ()
    effective.to_dict.return_value = plan
    return ResolvedJob(
        command="separate", settings=settings,
        profile=LoadedProfile("defaults", "built-in"), inputs=["/input.wav"],
        output="/out", plan=plan, identity_inherited=inherited,
        resolved=effective,
    )


class SeparateCommandTests(unittest.TestCase):
    def test_dry_run_emits_versioned_document_without_runner(self) -> None:
        out = io.StringIO()
        with patch("cli.separate.resolve_separate_job", return_value=_job()), patch(
            "cli.separate.run_batch"
        ) as runner, redirect_stdout(out):
            code = main([
                "separate", "input.wav", "-o", "out", "--model", "mdx:test",
                "--dry-run", "--report", "json",
            ])
        self.assertEqual(code, 0)
        self.assertFalse(runner.called)
        payload = json.loads(out.getvalue())
        self.assertEqual(payload["schema_version"], 1)
        self.assertTrue(payload["dry_run"])

    def test_machine_profile_identity_requires_acceptance(self) -> None:
        out = io.StringIO()
        with patch("cli.separate.resolve_separate_job", return_value=_job(inherited=True)), redirect_stdout(out):
            code = main([
                "separate", "input.wav", "-o", "out", "--profile", "named",
                "--report", "json",
            ])
        self.assertEqual(code, 2)
        self.assertIn("accept-inherited", json.loads(out.getvalue())["error"]["message"])

    def test_negative_confirmation_does_not_run(self) -> None:
        args = build_parser().parse_args(["separate", "input.wav", "-o", "out", "--profile", "named"])
        fake_stdin = io.StringIO("\n")
        fake_stdin.isatty = lambda: True  # type: ignore[attr-defined]
        with patch("cli.separate.resolve_separate_job", return_value=_job(inherited=True)), patch(
            "cli.separate.run_batch"
        ) as runner, patch("sys.stdin", fake_stdin):
            code = args.func(args)
        self.assertEqual(code, 2)
        self.assertFalse(runner.called)

    def test_jsonl_has_planned_and_finished(self) -> None:
        from cli.execution import BatchOutcome

        out = io.StringIO()
        outcome = BatchOutcome("success", 1.0, [{"input": "/input.wav", "status": "success", "outputs": []}])
        with patch("cli.separate.resolve_separate_job", return_value=_job()), patch(
            "cli.separate.check_runtime_deps", return_value=None
        ), patch("cli.separate.run_batch", return_value=outcome), patch(
            "cli.separate.write_manifest", return_value=None
        ), redirect_stdout(out):
            code = main([
                "separate", "input.wav", "-o", "out", "--model", "mdx:test",
                "--report", "jsonl", "--quiet",
            ])
        self.assertEqual(code, 0)
        events = [json.loads(line)["event"] for line in out.getvalue().splitlines()]
        self.assertEqual(events, ["planned", "started", "finished"])

    def test_interrupted_batch_exits_130_with_uniform_json(self) -> None:
        from cli.execution import BatchOutcome

        out, err = io.StringIO(), io.StringIO()
        outcome = BatchOutcome(
            "failed", 0.25,
            [{"input": "/input.wav", "status": "failed", "error": "interrupted", "outputs": []}],
            interrupted=True,
        )
        with patch("cli.separate.resolve_separate_job", return_value=_job()), patch(
            "cli.separate.check_runtime_deps", return_value=None
        ), patch("cli.separate.run_batch", return_value=outcome), patch(
            "cli.separate.write_manifest", return_value=None
        ), redirect_stdout(out), redirect_stderr(err):
            code = main([
                "separate", "input.wav", "-o", "out", "--model", "mdx:test",
                "--report", "json",
            ])
        payload = json.loads(out.getvalue())
        self.assertEqual(code, 130)
        self.assertFalse(payload["ok"])
        self.assertTrue(payload["stopped"])
        self.assertEqual(payload["inputs"][0]["error"], "interrupted")

    def test_main_keyboard_interrupt_uses_same_json_contract(self) -> None:
        out, err = io.StringIO(), io.StringIO()
        with patch(
            "cli.separate.resolve_separate_job", side_effect=KeyboardInterrupt
        ), redirect_stdout(out), redirect_stderr(err):
            code = main([
                "separate", "input.wav", "-o", "out", "--model", "mdx:test",
                "--report", "json",
            ])
        payload = json.loads(out.getvalue())
        self.assertEqual(code, 130)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["status"], "failed")
        self.assertTrue(payload["stopped"])

    def test_interrupted_jsonl_finished_event_is_stopped(self) -> None:
        from cli.execution import BatchOutcome

        out = io.StringIO()
        outcome = BatchOutcome("failed", 0.1, [], interrupted=True)
        with patch("cli.separate.resolve_separate_job", return_value=_job()), patch(
            "cli.separate.check_runtime_deps", return_value=None
        ), patch("cli.separate.run_batch", return_value=outcome), patch(
            "cli.separate.write_manifest", return_value=None
        ), redirect_stdout(out):
            code = main([
                "separate", "input.wav", "-o", "out", "--model", "mdx:test",
                "--report", "jsonl", "--quiet",
            ])
        finished = json.loads(out.getvalue().splitlines()[-1])
        self.assertEqual(code, 130)
        self.assertEqual(finished["event"], "finished")
        self.assertTrue(finished["stopped"])


class ValidationAndBenchmarkTests(unittest.TestCase):
    def test_config_validation_stops_before_model_assembly(self) -> None:
        out = io.StringIO()
        with patch(
            "cli.validate.resolve_separate_job", return_value=_job()
        ) as resolver, redirect_stdout(out):
            code = main([
                "validate", "separate", "input.wav", "-o", "out",
                "--model", "mdx:test", "--level", "config",
                "--report", "json",
            ])
        self.assertEqual(code, 0)
        resolver.assert_called_once()
        from core.job_plan import ValidationLevel

        self.assertIs(
            resolver.call_args.kwargs["validation_level"],
            ValidationLevel.CONFIG,
        )
        self.assertEqual(json.loads(out.getvalue())["level"], "config")

    def test_benchmark_rejects_missing_identities_before_children(self) -> None:
        out = io.StringIO()
        with patch("cli.bench._run_child") as child, redirect_stdout(out):
            code = main([
                "bench", "input.wav", "-o", "out", "--report", "json",
            ])
        self.assertEqual(code, 2)
        self.assertFalse(child.called)
        self.assertFalse(json.loads(out.getvalue())["ok"])

    def test_fail_exit_130_sets_stopped(self) -> None:
        from types import SimpleNamespace

        from cli.reporting import fail

        args = SimpleNamespace(report="json", quiet=False, verbose=False)
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = fail(args, "interrupted", exit_code=130)
        payload = json.loads(out.getvalue())
        self.assertEqual(code, 130)
        self.assertTrue(payload["stopped"])
        self.assertFalse(payload["ok"])

    def test_bench_topology_reads_plan_models_not_identity(self) -> None:
        from cli.bench import _stem_topology

        dead = {"identity": {"primary_stem": "Vocals"}}
        live = {"models": [{"primary_stem": "Vocals", "secondary_stem": "Instrumental"}]}
        self.assertNotEqual(_stem_topology(dead), _stem_topology(live))
        self.assertEqual(_stem_topology(live), ("Instrumental", "Vocals"))
        self.assertEqual(_stem_topology({}), ())


class ImportBoundaryTests(unittest.TestCase):
    def test_cli_import_does_not_import_heavy_stacks(self) -> None:
        import subprocess
        import sys

        script = "import sys, cli.main; print(any(x in sys.modules for x in ('gi','torch','onnxruntime')))"
        proc = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, check=True)
        self.assertEqual(proc.stdout.strip(), "False")


if __name__ == "__main__":
    unittest.main()
