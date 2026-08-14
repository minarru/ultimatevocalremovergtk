"""`list-models`: listing shape, method filter, --json, and the offline default."""

from __future__ import annotations

import io
import os
import unittest
from contextlib import redirect_stdout
from unittest import mock

from cli.main import build_parser


class _FakeRepo:
    def list_mdx_models(self) -> list[str]:
        return ["Kim_Vocal_2", "UVR-MDX-NET-Inst_HQ_3"]

    def list_vr_models(self) -> list[str]:
        return ["1_HP-UVR"]

    def list_demucs_models(self) -> list[str]:
        return ["hdemucs_mmi.yaml"]


def _run(argv: list[str]) -> tuple[int, str]:
    from cli.list_models import cmd_list_models

    args = build_parser().parse_args(argv)
    buf = io.StringIO()
    with mock.patch("cli.list_models.ModelRepository", _FakeRepo), \
         mock.patch("cli.list_models.map_basenames_to_display",
                    side_effect=lambda names, arch, repo: [f"D:{n}" for n in names]), \
         redirect_stdout(buf):
        code = cmd_list_models(args)
    return code, buf.getvalue()


class ListModelsTests(unittest.TestCase):
    def test_lists_all_three_families_by_default(self) -> None:
        code, out = _run(["list-models"])
        self.assertEqual(code, 0)
        self.assertIn("Kim_Vocal_2", out)
        self.assertIn("1_HP-UVR", out)
        self.assertIn("hdemucs_mmi.yaml", out)

    def test_method_filter(self) -> None:
        _code, out = _run(["list-models", "--method", "vr"])
        self.assertIn("1_HP-UVR", out)
        self.assertNotIn("Kim_Vocal_2", out)

    def test_json_shape(self) -> None:
        import json

        _code, out = _run(["list-models", "--method", "mdx", "--json"])
        rows = json.loads(out)
        self.assertEqual({"method", "basename", "display"}, set(rows[0]))
        self.assertEqual(rows[0]["method"], "mdx")

    def test_offline_by_default_sets_both_disable_flags(self) -> None:
        seen: dict[str, str | None] = {}

        def spy(names: list[str], arch: object, repo: object) -> list[str]:
            seen["politrees"] = os.environ.get("UVR_DISABLE_POLITREES")
            seen["mvsepless"] = os.environ.get("UVR_DISABLE_MVSEPLESS")
            return list(names)

        args = build_parser().parse_args(["list-models", "--method", "mdx"])
        from cli.list_models import cmd_list_models

        with mock.patch("cli.list_models.ModelRepository", _FakeRepo), \
             mock.patch("cli.list_models.map_basenames_to_display", side_effect=spy), \
             redirect_stdout(io.StringIO()):
            cmd_list_models(args)
        self.assertEqual(seen["politrees"], "1")
        self.assertEqual(seen["mvsepless"], "1")

    def test_online_flag_restores_the_previous_env(self) -> None:
        seen: dict[str, str | None] = {}

        def spy(names: list[str], arch: object, repo: object) -> list[str]:
            seen["politrees"] = os.environ.get("UVR_DISABLE_POLITREES")
            return list(names)

        args = build_parser().parse_args(["list-models", "--method", "mdx", "--online"])
        from cli.list_models import cmd_list_models

        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("UVR_DISABLE_POLITREES", None)
            with mock.patch("cli.list_models.ModelRepository", _FakeRepo), \
                 mock.patch("cli.list_models.map_basenames_to_display", side_effect=spy), \
                 redirect_stdout(io.StringIO()):
                cmd_list_models(args)
        self.assertIsNone(seen["politrees"])

    def test_ensemble_method_lists_saved_and_curated(self) -> None:
        from cli.list_models import cmd_list_models

        args = build_parser().parse_args(["list-models", "--method", "ensemble"])
        buf = io.StringIO()
        with mock.patch("cli.list_models.list_saved_ensembles", return_value=["My Mix"]), \
             mock.patch("cli.list_models.list_curated_ensembles", return_value=["kim_vocal"]), \
             redirect_stdout(buf):
            self.assertEqual(cmd_list_models(args), 0)
        out = buf.getvalue()
        self.assertIn("My Mix", out)
        self.assertIn("Curated:", out)

    def test_ensemble_json_shape(self) -> None:
        import json
        from cli.list_models import cmd_list_models

        args = build_parser().parse_args(["list-models", "--method", "ensemble", "--json"])
        buf = io.StringIO()
        with mock.patch("cli.list_models.list_saved_ensembles", return_value=["My Mix"]), \
             mock.patch("cli.list_models.list_curated_ensembles", return_value=["kim_vocal"]), \
             redirect_stdout(buf):
            self.assertEqual(cmd_list_models(args), 0)
        rows = json.loads(buf.getvalue())
        self.assertTrue(all(row["method"] == "ensemble" for row in rows))
        self.assertEqual({row["kind"] for row in rows}, {"saved", "curated"})
        self.assertIn("basename", rows[0])
        self.assertIn("display", rows[0])


if __name__ == "__main__":
    unittest.main()
