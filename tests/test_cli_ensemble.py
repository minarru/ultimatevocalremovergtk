"""The `ensemble` command: member sources, validation, and runner choice."""

from __future__ import annotations

import io
import json
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest import mock

from bundled.constants import (
    CHOOSE_ENSEMBLE_OPTION,
    ENSEMBLE_PARTITION,
    MAX_MIN,
    MDX_ARCH_TYPE,
)
from cli.main import build_parser
from core.settings import Settings
from core.stems import EnsemblePair

_TAG_A = f"{MDX_ARCH_TYPE}{ENSEMBLE_PARTITION}Kim Vocal 2"
_TAG_B = f"{MDX_ARCH_TYPE}{ENSEMBLE_PARTITION}Inst HQ 3"


class _Result:
    ok = True
    elapsed_s = 1.5
    export_path = "/tmp/out"
    error = None
    stopped = False
    console: list[str] = []


class _CmdEnsembleCase(unittest.TestCase):
    """Command-level helpers: patch the by-value import of ``check_runtime_deps``."""

    def setUp(self) -> None:
        deps = mock.patch("cli.ensemble.check_runtime_deps", return_value=None)
        deps.start()
        self.addCleanup(deps.stop)


class EnsembleMemberSourceTests(_CmdEnsembleCase):
    def test_adhoc_models_populate_selected_models(self) -> None:
        parser = build_parser()
        args = parser.parse_args(
            ["ensemble", "a.wav", "-o", "/tmp/o", "--model", _TAG_A, "--model", _TAG_B]
        )
        self.assertEqual(args.models, [_TAG_A, _TAG_B])

    def test_comma_list_is_also_accepted(self) -> None:
        parser = build_parser()
        args = parser.parse_args(
            ["ensemble", "a.wav", "-o", "/tmp/o", "--models", f"{_TAG_A},{_TAG_B}"]
        )
        self.assertEqual(args.models_csv, f"{_TAG_A},{_TAG_B}")

    def test_fewer_than_two_members_exits_two(self) -> None:
        from cli.ensemble import cmd_ensemble

        parser = build_parser()
        args = parser.parse_args([
            "ensemble", "a.wav", "-o", "/tmp/o", "--model", _TAG_A,
            "--main-stem", "vocals_instrumental",
        ])
        err = io.StringIO()
        with mock.patch("cli.ensemble.os.path.isfile", return_value=True), \
             mock.patch("cli.ensemble.os.makedirs"), \
             mock.patch("cli.ensemble.ModelRepository"), \
             mock.patch("cli.ensemble.build_settings", return_value=Settings()), \
             mock.patch("cli.ensemble.resolve_ensemble_members",
                        side_effect=lambda tokens, repo=None: list(tokens)), \
             redirect_stderr(err):
            self.assertEqual(cmd_ensemble(args), 2)
        self.assertIn("at least 2", err.getvalue())

    def test_missing_member_source_exits_two(self) -> None:
        from cli.ensemble import cmd_ensemble

        settings = Settings()
        settings.ensemble.selected_models = [_TAG_A, _TAG_B]
        settings.ensemble.main_stem = EnsemblePair.VOCALS_INSTRUMENTAL
        args = build_parser().parse_args(["ensemble", "a.wav", "-o", "/tmp/o"])
        err = io.StringIO()
        with mock.patch("cli.ensemble.os.path.isfile", return_value=True), \
             mock.patch("cli.ensemble.os.makedirs"), \
             mock.patch("cli.ensemble.build_settings", return_value=settings), \
             redirect_stderr(err):
            self.assertEqual(cmd_ensemble(args), 2)
        self.assertIn("--ensemble", err.getvalue())

    def test_saved_preset_alone_runs_without_main_stem_flag(self) -> None:
        from cli.ensemble import cmd_ensemble

        settings = Settings()
        args = build_parser().parse_args(
            ["ensemble", "a.wav", "-o", "/tmp/o", "--ensemble", "My Mix"]
        )

        def fake_apply(target: Settings, name: str, **_kwargs: object) -> None:
            target.ensemble.selected_models = [_TAG_A, _TAG_B]
            target.ensemble.type = MAX_MIN
            target.ensemble.main_stem = EnsemblePair.VOCALS_INSTRUMENTAL
            target.ensemble.chosen_ensemble = name

        with mock.patch("cli.ensemble.os.path.isfile", return_value=True), \
             mock.patch("cli.ensemble.os.makedirs"), \
             mock.patch("cli.ensemble.ModelRepository"), \
             mock.patch("cli.ensemble.build_settings", return_value=settings), \
             mock.patch("cli.ensemble.apply_saved_ensemble", side_effect=fake_apply), \
             mock.patch("cli.ensemble.run_ensemble_sync", return_value=_Result()) as run:
            self.assertEqual(cmd_ensemble(args), 0)
        run.assert_called_once()
        called = run.call_args.args[0]
        self.assertEqual(called.ensemble.selected_models, [_TAG_A, _TAG_B])
        self.assertEqual(called.ensemble.main_stem, EnsemblePair.VOCALS_INSTRUMENTAL)
        self.assertEqual(called.ensemble.chosen_ensemble, "My Mix")

    def test_saved_preset_is_loaded_then_overridden_by_models(self) -> None:
        from cli.ensemble import cmd_ensemble

        settings = Settings()
        parser = build_parser()
        args = parser.parse_args(
            ["ensemble", "a.wav", "-o", "/tmp/o", "--ensemble", "My Mix",
             "--model", _TAG_A, "--model", _TAG_B]
        )

        def fake_apply(target: Settings, name: str, **_kwargs: object) -> None:
            target.ensemble.selected_models = ["from-preset"]
            target.ensemble.type = MAX_MIN
            target.ensemble.main_stem = EnsemblePair.VOCALS_INSTRUMENTAL

        with mock.patch("cli.ensemble.os.path.isfile", return_value=True), \
             mock.patch("cli.ensemble.os.makedirs"), \
             mock.patch("cli.ensemble.ModelRepository"), \
             mock.patch("cli.ensemble.build_settings", return_value=settings), \
             mock.patch("cli.ensemble.apply_saved_ensemble", side_effect=fake_apply), \
             mock.patch("cli.ensemble.resolve_ensemble_members",
                        side_effect=lambda tokens, repo=None: list(tokens)), \
             mock.patch("cli.ensemble.run_ensemble_sync", return_value=_Result()):
            self.assertEqual(cmd_ensemble(args), 0)
        self.assertEqual(settings.ensemble.selected_models, [_TAG_A, _TAG_B])
        self.assertEqual(settings.ensemble.chosen_ensemble, CHOOSE_ENSEMBLE_OPTION)


class EnsembleSettingsWiringTests(_CmdEnsembleCase):
    def test_uses_run_ensemble_sync_not_run_separation_sync(self) -> None:
        from cli.ensemble import cmd_ensemble

        parser = build_parser()
        args = parser.parse_args(
            ["ensemble", "a.wav", "-o", "/tmp/o", "--model", _TAG_A,
             "--model", _TAG_B, "--main-stem", "vocals_instrumental"]
        )
        with mock.patch("cli.ensemble.os.path.isfile", return_value=True), \
             mock.patch("cli.ensemble.os.makedirs"), \
             mock.patch("cli.ensemble.ModelRepository"), \
             mock.patch("cli.ensemble.build_settings", return_value=Settings()), \
             mock.patch("cli.ensemble.resolve_ensemble_members",
                        side_effect=lambda tokens, repo=None: list(tokens)), \
             mock.patch("cli.ensemble.run_ensemble_sync", return_value=_Result()) as run:
            self.assertEqual(cmd_ensemble(args), 0)
        run.assert_called_once()

    def test_adhoc_members_require_explicit_main_stem(self) -> None:
        from cli.ensemble import cmd_ensemble

        args = build_parser().parse_args(
            ["ensemble", "a.wav", "-o", "/tmp/o", "--model", _TAG_A,
             "--model", _TAG_B]
        )
        with mock.patch("cli.ensemble.os.path.isfile", return_value=True), \
             mock.patch("cli.ensemble.os.makedirs"), \
             mock.patch("cli.ensemble.ModelRepository"), \
             mock.patch("cli.ensemble.build_settings", return_value=Settings()), \
             mock.patch("cli.ensemble.resolve_ensemble_members",
                        side_effect=lambda tokens, repo=None: list(tokens)):
            self.assertEqual(cmd_ensemble(args), 2)

    def test_adhoc_members_clear_stale_saved_name(self) -> None:
        from cli.ensemble import cmd_ensemble

        settings = Settings()
        settings.ensemble.chosen_ensemble = "Old GUI Preset"
        args = build_parser().parse_args(
            ["ensemble", "a.wav", "-o", "/tmp/o", "--model", _TAG_A,
             "--model", _TAG_B, "--main-stem", "vocals_instrumental"]
        )
        with mock.patch("cli.ensemble.os.path.isfile", return_value=True), \
             mock.patch("cli.ensemble.os.makedirs"), \
             mock.patch("cli.ensemble.ModelRepository"), \
             mock.patch("cli.ensemble.build_settings", return_value=settings), \
             mock.patch("cli.ensemble.resolve_ensemble_members",
                        side_effect=lambda tokens, repo=None: list(tokens)), \
             mock.patch("cli.ensemble.run_ensemble_sync", return_value=_Result()):
            self.assertEqual(cmd_ensemble(args), 0)
        self.assertEqual(settings.ensemble.chosen_ensemble, CHOOSE_ENSEMBLE_OPTION)

    def test_main_stem_and_algorithm_land_on_settings(self) -> None:
        from cli.ensemble import cmd_ensemble

        settings = Settings()
        parser = build_parser()
        args = parser.parse_args(
            ["ensemble", "a.wav", "-o", "/tmp/o", "--model", _TAG_A, "--model", _TAG_B,
             "--main-stem", "karaoke", "--algorithm", "Max Spec/Min Spec"]
        )
        with mock.patch("cli.ensemble.os.path.isfile", return_value=True), \
             mock.patch("cli.ensemble.os.makedirs"), \
             mock.patch("cli.ensemble.ModelRepository"), \
             mock.patch("cli.ensemble.build_settings", return_value=settings), \
             mock.patch("cli.ensemble.resolve_ensemble_members",
                        side_effect=lambda tokens, repo=None: list(tokens)), \
             mock.patch("cli.ensemble.run_ensemble_sync", return_value=_Result()):
            self.assertEqual(cmd_ensemble(args), 0)
        self.assertEqual(settings.ensemble.main_stem, EnsemblePair.KARAOKE)
        self.assertEqual(settings.ensemble.type, MAX_MIN)

    def test_set_beats_named_main_stem(self) -> None:
        from cli.ensemble import cmd_ensemble

        settings = Settings()
        args = build_parser().parse_args(
            ["ensemble", "a.wav", "-o", "/tmp/o", "--model", _TAG_A,
             "--model", _TAG_B, "--main-stem", "vocals_instrumental",
             "--set", "ensemble.main_stem=karaoke"]
        )
        with mock.patch("cli.ensemble.os.path.isfile", return_value=True), \
             mock.patch("cli.ensemble.os.makedirs"), \
             mock.patch("cli.ensemble.ModelRepository"), \
             mock.patch("cli.ensemble.build_settings", return_value=settings), \
             mock.patch("cli.ensemble.resolve_ensemble_members",
                        side_effect=lambda tokens, repo=None: list(tokens)), \
             mock.patch("cli.ensemble.run_ensemble_sync", return_value=_Result()):
            self.assertEqual(cmd_ensemble(args), 0)
        self.assertEqual(settings.ensemble.main_stem, EnsemblePair.KARAOKE)

    def test_ineligible_member_warns(self) -> None:
        from cli.ensemble import cmd_ensemble

        fake_repo = mock.MagicMock()
        fake_repo.ensemble_model_list.return_value = [_TAG_A]
        args = build_parser().parse_args(
            ["ensemble", "a.wav", "-o", "/tmp/o", "--model", _TAG_A,
             "--model", _TAG_B, "--main-stem", "vocals_instrumental"]
        )
        err = io.StringIO()
        with mock.patch("cli.ensemble.os.path.isfile", return_value=True), \
             mock.patch("cli.ensemble.os.makedirs"), \
             mock.patch("cli.ensemble.ModelRepository", return_value=fake_repo), \
             mock.patch("cli.ensemble.build_settings", return_value=Settings()), \
             mock.patch("cli.ensemble.resolve_ensemble_members",
                        side_effect=lambda tokens, repo=None: list(tokens)), \
             mock.patch("cli.ensemble.run_ensemble_sync", return_value=_Result()) as run, \
             redirect_stderr(err):
            self.assertEqual(cmd_ensemble(args), 0)
        run.assert_called_once()
        err_text = err.getvalue()
        self.assertIn("warning", err_text)
        self.assertIn(_TAG_B, err_text)

    def test_json_owns_stdout_and_suppresses_console(self) -> None:
        from cli.ensemble import cmd_ensemble

        args = build_parser().parse_args(
            ["ensemble", "a.wav", "-o", "/tmp/o", "--model", _TAG_A,
             "--model", _TAG_B, "--main-stem", "vocals_instrumental", "--json"]
        )
        out = io.StringIO()
        with mock.patch("cli.ensemble.os.path.isfile", return_value=True), \
             mock.patch("cli.ensemble.os.makedirs"), \
             mock.patch("cli.ensemble.ModelRepository"), \
             mock.patch("cli.ensemble.build_settings", return_value=Settings()), \
             mock.patch("cli.ensemble.resolve_ensemble_members",
                        side_effect=lambda tokens, repo=None: list(tokens)), \
             mock.patch("cli.ensemble.run_ensemble_sync", return_value=_Result()) as run, \
             redirect_stdout(out):
            self.assertEqual(cmd_ensemble(args), 0)
        payload = json.loads(out.getvalue())
        self.assertIs(payload["ok"], True)
        self.assertEqual(payload["members"], [_TAG_A, _TAG_B])
        self.assertIs(run.call_args.kwargs.get("print_console"), False)


class SeparateStillRejectsEnsembleTests(unittest.TestCase):
    def test_separate_method_choices_exclude_ensemble(self) -> None:
        parser = build_parser()
        with self.assertRaises(SystemExit):
            parser.parse_args(
                ["separate", "a.wav", "-o", "/tmp/o", "--method", "ensemble"]
            )


if __name__ == "__main__":
    unittest.main()
