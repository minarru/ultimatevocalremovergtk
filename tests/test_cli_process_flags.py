"""Named process flags compile to validated (path, value) override pairs."""

from __future__ import annotations

import argparse
import unittest

from cli.process_flags import add_process_args, collect_overrides
from core.settings import Settings
from core.settings.access import apply_settings_overrides


def _parse(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="test")
    add_process_args(parser)
    return parser.parse_args(argv)


class CollectOverridesTests(unittest.TestCase):
    def test_no_flags_yields_no_overrides(self) -> None:
        self.assertEqual(collect_overrides(_parse([])), [])

    def test_cpu_and_gpu_are_mutually_exclusive(self) -> None:
        with self.assertRaises(SystemExit):
            _parse(["--cpu", "--gpu"])

    def test_gpu_maps_to_use_gpu_true(self) -> None:
        self.assertIn(("process.use_gpu", True), collect_overrides(_parse(["--gpu"])))

    def test_cpu_maps_to_use_gpu_false(self) -> None:
        self.assertIn(("process.use_gpu", False), collect_overrides(_parse(["--cpu"])))

    def test_no_autocast_maps_to_false(self) -> None:
        self.assertIn(
            ("process.autocast", False), collect_overrides(_parse(["--no-autocast"]))
        )

    def test_format_is_case_insensitive(self) -> None:
        self.assertIn(
            ("process.save_format", "FLAC"), collect_overrides(_parse(["--format", "flac"]))
        )

    def test_sample_seconds_maps_to_duration_and_enables_sample_mode(self) -> None:
        overrides = collect_overrides(_parse(["--sample-seconds", "12"]))
        self.assertIn(("process.sample_mode_duration", 12), overrides)
        self.assertIn(("process.sample_mode", True), overrides)

    def test_set_is_repeatable_and_last_wins(self) -> None:
        overrides = collect_overrides(
            _parse(["--set", "process.use_gpu=true", "--set", "process.use_gpu=false"])
        )
        settings = Settings()
        apply_settings_overrides(settings, overrides)
        self.assertIs(settings.process.use_gpu, False)

    def test_set_runs_after_named_flags(self) -> None:
        overrides = collect_overrides(
            _parse(["--cpu", "--set", "process.use_gpu=true"])
        )
        settings = Settings()
        apply_settings_overrides(settings, overrides)
        self.assertIs(settings.process.use_gpu, True)

    def test_set_runs_after_resolved_vocal_splitter(self) -> None:
        args = _parse([
            "--vocal-split", "Splitter X",
            "--set", "process.vocal_splitter_enabled=false",
        ])
        overrides = collect_overrides(
            args, resolved_vocal_splitter="MDX-Net: Splitter X"
        )
        settings = Settings()
        apply_settings_overrides(settings, overrides)
        self.assertEqual(settings.process.vocal_splitter, "MDX-Net: Splitter X")
        self.assertIs(settings.process.vocal_splitter_enabled, False)

    def test_bad_set_token_raises(self) -> None:
        with self.assertRaises(ValueError):
            collect_overrides(_parse(["--set", "nonsense"]))

    def test_every_named_flag_targets_a_real_setting(self) -> None:
        argv = [
            "--gpu", "--autocast", "--normalize", "--match-mix", "--sample",
            "--save-split-inst", "--format", "mp3", "--wav-type", "PCM_24",
            "--mp3-bitrate", "256k", "--flac-depth", "24-bit", "--device", "0",
            "--sample-seconds", "20",
        ]
        settings = Settings()
        apply_settings_overrides(settings, collect_overrides(_parse(argv)))
        self.assertIs(settings.process.use_gpu, True)
        self.assertEqual(settings.process.save_format, "MP3")
        self.assertEqual(settings.process.mp3_bitrate, "256k")
        self.assertEqual(settings.process.device, "0")


if __name__ == "__main__":
    unittest.main()
