from __future__ import annotations

import io
import json
import unittest
from contextlib import redirect_stdout
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
