from __future__ import annotations

import argparse
import unittest

from cli.process_flags import (
    _BOOL_FLAG_PATHS,
    _VALUE_FLAG_PATHS,
    add_process_args,
    collect_overrides,
)
from core.settings import Settings
from core.settings.access import validate_setting_path


class ProcessFlagTests(unittest.TestCase):
    def parse(self, values: list[str]) -> argparse.Namespace:
        parser = argparse.ArgumentParser()
        add_process_args(parser)
        return parser.parse_args(values)

    def test_boolean_flags_are_symmetric(self) -> None:
        args = self.parse(["--no-normalize", "--no-match-mix", "--no-sample", "--no-autocast"])
        self.assertEqual(dict(collect_overrides(args)), {
            "process.autocast": False,
            "process.normalization": False,
            "process.match_mix_level": False,
            "process.sample_mode": False,
        })

    def test_set_is_applied_last(self) -> None:
        args = self.parse(["--normalize", "--set", "process.normalization=false"])
        self.assertEqual(collect_overrides(args)[-1], ("process.normalization", "false"))

    def test_sample_seconds_enables_sample(self) -> None:
        args = self.parse(["--sample-seconds", "12"])
        self.assertIn(("process.sample_mode", True), collect_overrides(args))

    def test_device_is_not_compiled_as_a_plain_setting(self) -> None:
        args = self.parse(["--device", "cuda:1"])
        self.assertNotIn("process.device", dict(collect_overrides(args)))

    def test_every_named_flag_targets_a_real_scalar_setting(self) -> None:
        settings = Settings.defaults()
        for path in (*_BOOL_FLAG_PATHS.values(), *_VALUE_FLAG_PATHS.values()):
            validate_setting_path(settings, path)

    def test_opus_format_and_bitrate_compile(self) -> None:
        args = self.parse(["--format", "OPUS", "--opus-bitrate", "128k"])
        self.assertEqual(
            dict(collect_overrides(args)),
            {
                "process.save_format": "OPUS",
                "process.opus_bitrate": "128k",
            },
        )
