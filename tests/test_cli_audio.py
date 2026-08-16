from __future__ import annotations

import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from cli.main import build_parser, main
from bundled.constants import CHANGE_PITCH
from core.audio_plan import AudioJobResolver, AudioJobSpec
from core.job_plan import ValidationLevel
from core.settings import Settings


class AudioCliSurfaceTests(unittest.TestCase):
    def test_all_audio_commands_and_validation_parse(self) -> None:
        parser = build_parser()
        commands = {
            "ensemble": ["a.wav", "b.wav", "-o", "out"],
            "stretch": ["a.wav", "-o", "out", "--rate", "1.2"],
            "pitch": ["a.wav", "-o", "out", "--semitones", "2"],
            "align": ["--pair", "a.wav", "b.wav", "-o", "out"],
            "match": ["--pair", "a.wav", "b.wav", "-o", "out"],
            "restore": ["a.wav", "-o", "out", "--model", "apollo:test"],
        }
        for command, tail in commands.items():
            with self.subTest(command=command):
                self.assertTrue(callable(parser.parse_args(["audio", command, *tail]).func))
                self.assertTrue(callable(parser.parse_args(["validate", "audio", command, *tail]).func))

    def test_dry_run_creates_no_output_and_emits_resolved_plan(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            source = os.path.join(root, "song.wav")
            open(source, "wb").close()
            output = os.path.join(root, "out")
            stdout = io.StringIO()
            with redirect_stdout(stdout):
                code = main([
                    "audio", "stretch", source, "-o", output, "--rate", "1.25",
                    "--dry-run", "--report", "json",
                ])
            payload = json.loads(stdout.getvalue())
            self.assertEqual(code, 0)
            self.assertFalse(os.path.exists(output))
            self.assertEqual(payload["plan"]["units"][0]["outputs"], [
                os.path.join(output, "song time stretched.wav")
            ])

    def test_manual_ensemble_requires_two_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            source = os.path.join(root, "song.wav")
            open(source, "wb").close()
            stdout = io.StringIO()
            with redirect_stdout(stdout):
                code = main([
                    "audio", "ensemble", source, "-o", os.path.join(root, "out"),
                    "--dry-run", "--report", "json",
                ])
            self.assertEqual(code, 2)
            self.assertFalse(json.loads(stdout.getvalue())["ok"])

    def test_pair_directory_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            source = os.path.join(root, "song.wav")
            open(source, "wb").close()
            stdout = io.StringIO()
            with redirect_stdout(stdout):
                code = main([
                    "audio", "align", "--pair", root, source, "-o", os.path.join(root, "out"),
                    "--dry-run", "--report", "json",
                ])
            self.assertEqual(code, 2)


class AudioPlanTests(unittest.TestCase):
    def test_config_plan_is_immutable_snapshot_with_exact_names(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            source = os.path.join(root, "track.wav")
            open(source, "wb").close()
            output = os.path.join(root, "out")
            settings = Settings.defaults()
            settings.audio_tools.pitch_rate = -3
            plan = AudioJobResolver(object()).resolve(
                AudioJobSpec(CHANGE_PITCH, settings, output, (source,)),
                ValidationLevel.CONFIG,
            )
            settings.audio_tools.pitch_rate = 5
            self.assertTrue(plan.ok)
            self.assertEqual(plan.settings.audio_tools.pitch_rate, -3)
            self.assertEqual(plan.units[0].outputs, (os.path.join(output, "track pitch shifted.wav"),))


if __name__ == "__main__":
    unittest.main()
