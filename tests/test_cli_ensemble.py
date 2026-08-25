from __future__ import annotations

import argparse
import io
import json
import unittest
from contextlib import redirect_stdout
from types import SimpleNamespace
from unittest.mock import patch

from cli.job import ResolvedJob
from cli.main import UsageError, build_parser, main
from cli.profiles import LoadedProfile
from core.settings import Settings


class EnsembleParserTests(unittest.TestCase):
    def test_members_are_repeatable_and_booleans_symmetric(self) -> None:
        args = build_parser().parse_args(
            [
                "ensemble",
                "in.wav",
                "-o",
                "out",
                "--model",
                "mdx:a",
                "--model",
                "demucs:b",
                "--no-wav-ensemble",
                "--no-save-all-outputs",
            ]
        )
        self.assertEqual(args.models, ["mdx:a", "demucs:b"])
        self.assertFalse(args.wav_ensemble)
        self.assertFalse(args.save_all_outputs)

    def test_main_stem_accepts_exact_semantic_ids_and_advertises_labels(self) -> None:
        parser = build_parser()
        args = parser.parse_args(
            [
                "ensemble",
                "in.wav",
                "-o",
                "out",
                "--model",
                "mdx:a",
                "--model",
                "mdx:b",
                "--main-stem",
                "pair.vocals_instrumental",
            ]
        )
        self.assertEqual(args.main_stem, "pair.vocals_instrumental")
        help_output = io.StringIO()
        with self.assertRaises(SystemExit), redirect_stdout(help_output):
            parser.parse_args(["ensemble", "--help"])
        help_text = help_output.getvalue()
        self.assertIn("pair.vocals_instrumental", help_text)
        self.assertIn("Vocals/Instrumental", help_text)
        with self.assertRaises(UsageError):
            parser.parse_args(
                [
                    "ensemble",
                    "in.wav",
                    "-o",
                    "out",
                    "--model",
                    "mdx:a",
                    "--model",
                    "mdx:b",
                    "--main-stem",
                    "Vocals/Instrumental",
                ]
            )

    def test_dry_run_uses_shared_plan(self) -> None:
        settings = Settings.defaults()
        job = ResolvedJob(
            command="ensemble",
            settings=settings,
            profile=LoadedProfile("defaults", "built-in"),
            inputs=["/in.wav"],
            output="/out",
            plan={
                "identity": {"members": [{"id": "mdx:a"}, {"id": "mdx:b"}]},
                "profile": {"name": "defaults", "source": "built-in"},
                "runtime": {},
                "inputs": [],
                "export_path": "/out",
                "collision_policy": "fail",
                "format": "WAV",
            },
        )
        out = io.StringIO()
        with patch("cli.ensemble.resolve_ensemble_job", return_value=job), redirect_stdout(out):
            code = main(
                [
                    "ensemble",
                    "in.wav",
                    "-o",
                    "out",
                    "--model",
                    "mdx:a",
                    "--model",
                    "mdx:b",
                    "--dry-run",
                    "--report",
                    "json",
                ]
            )
        self.assertEqual(code, 0)
        self.assertTrue(json.loads(out.getvalue())["dry_run"])

    def test_saved_preset_reset_warning_survives_cli_resolution_and_logs_safely(self) -> None:
        from cli.job import resolve_ensemble_job
        from core.model_identity import ModelArtifacts, ModelRecord

        settings = Settings.defaults()
        profile = LoadedProfile("defaults", "built-in")
        records = [
            ModelRecord(
                id="mdx:first",
                family="mdx",
                basename="first",
                display="First",
                backend_name="first",
                artifacts=ModelArtifacts("first.ckpt"),
                installed=True,
            ),
            ModelRecord(
                id="mdx:second",
                family="mdx",
                basename="second",
                display="Second",
                backend_name="second",
                artifacts=ModelArtifacts("second.ckpt"),
                installed=True,
            ),
        ]
        warning = (
            "ensemble_main_stem: unknown semantic pair/mode ID; "
            "choose an ensemble stem pair again and resave"
        )
        args = argparse.Namespace(
            ensemble="/private/preset-secret.json",
            models=None,
            main_stem=None,
            stems=None,
            long_chunk_seconds=None,
            long_chunk_overlap=None,
            algorithm=None,
            wav_ensemble=None,
            save_all_outputs=None,
            device=None,
            on_exists="fail",
            offline=True,
        )
        models = SimpleNamespace(lookup=lambda _value: records.pop(0))
        effective = SimpleNamespace(settings=settings, diagnostics=(), to_dict=lambda: {})

        def apply_preset(target: Settings, _name: str) -> SimpleNamespace:
            target.ensemble.selected_models = ["mdx:first", "mdx:second"]
            target.ensemble.main_stem = ""
            return SimpleNamespace(validation_warnings=(warning,))

        with (
            patch("cli.job._base_resolve", return_value=(settings, profile, ["/in.wav"], "/out")),
            patch("cli.job.Settings.load", return_value=Settings.defaults()),
            patch("cli.job.ModelRepository"),
            patch("cli.job.CliModelLookup", return_value=models),
            patch("cli.job.SettingsResolver") as resolver_cls,
            patch("cli.job._canonicalize_model_references", return_value={}),
            patch("cli.job._device_pairs", return_value=([], False)),
            patch("cli.job.stored_identity_warnings", return_value=[]),
            patch("core.ensemble_service.EnsembleService") as service_cls,
            patch("core.job_plan.JobResolver") as job_resolver_cls,
            patch("core.debug_log.log_event") as log_event,
        ):
            resolver_cls.return_value.resolve.side_effect = lambda incoming, **_kwargs: (
                incoming,
                {},
            )
            service_cls.return_value.apply.side_effect = apply_preset
            job_resolver_cls.return_value.resolve.return_value = effective
            job = resolve_ensemble_job(args)

        self.assertIn(warning, job.validation_warnings)
        log_event.assert_called_once_with(
            "ensemble",
            "preset_persistence_reset",
            level="warning",
            field="ensemble_main_stem",
            reset="invalid_semantic_pair",
        )
        event_text = repr(log_event.call_args)
        self.assertNotIn("/private", event_text)
        self.assertNotIn("secret", event_text)
