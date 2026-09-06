"""Public parser ownership and pure shared command projections."""

from __future__ import annotations

import unittest


class CommandBoundaryTests(unittest.TestCase):
    def test_parser_dispatches_to_command_family_owners(self) -> None:
        from cli.main import build_parser

        parser = build_parser()
        for argv, owner in (
            (["models", "list"], "cli.commands.models"),
            (
                ["models", "register", "sample.pt", "--family", "mdx"],
                "cli.commands.model_registration",
            ),
            (["models", "catalog"], "cli.commands.model_catalogue"),
            (["ensembles", "list"], "cli.commands.ensembles"),
            (["settings", "show"], "cli.commands.settings"),
            (["devices", "list"], "cli.commands.devices"),
            (["completion", "bash"], "cli.commands.completion"),
        ):
            with self.subTest(argv=argv):
                self.assertEqual(parser.parse_args(argv).func.__module__, owner)

    def test_shared_settings_provider_keeps_nested_paths(self) -> None:
        from cli.commands.settings_fields import setting_paths

        paths = setting_paths()
        self.assertIn("process.stem_focus", paths)
        self.assertIn("process.save_format", paths)
        self.assertEqual(paths, sorted(paths))
