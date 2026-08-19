"""format_tag_title should hit a generation-keyed memo after the first call."""

from __future__ import annotations

import os
import unittest
from unittest import mock

from bundled.constants import ENSEMBLE_PARTITION, MDX_ARCH_TYPE
from core import model_display as md
from core.model_repository import ModelRepository


class FormatTagTitleCacheTests(unittest.TestCase):
    def setUp(self) -> None:
        os.environ["UVR_DISABLE_POLITREES"] = "1"
        os.environ["UVR_DISABLE_MVSEPLESS"] = "1"
        os.environ["UVR_DISABLE_CATALOGUE_STEMS"] = "1"
        self.addCleanup(lambda: os.environ.pop("UVR_DISABLE_POLITREES", None))
        self.addCleanup(lambda: os.environ.pop("UVR_DISABLE_MVSEPLESS", None))
        self.addCleanup(lambda: os.environ.pop("UVR_DISABLE_CATALOGUE_STEMS", None))
        md.clear_display_cache()

    def test_second_call_does_not_reenter_display_name(self) -> None:
        tag = f"{MDX_ARCH_TYPE}{ENSEMBLE_PARTITION}Example"
        repo = mock.Mock()
        repo.mdx_name_select_MAPPER = {}
        repo.mdx_catalogue_display_index.return_value = {}
        calls = {"n": 0}
        real = md.display_name_for_model

        def counted(arch: str, name: str, r: ModelRepository) -> str:
            calls["n"] += 1
            return real(arch, name, r)

        with mock.patch.object(md, "display_name_for_model", side_effect=counted):
            first = md.format_tag_title(tag, repo)
            second = md.format_tag_title(tag, repo)

        self.assertEqual(first, second)
        self.assertEqual(calls["n"], 1)

    def test_clear_display_cache_busts_memo(self) -> None:
        tag = f"{MDX_ARCH_TYPE}{ENSEMBLE_PARTITION}Example"
        repo = mock.Mock()
        calls = {"n": 0}

        def counted(arch: str, name: str, r: ModelRepository) -> str:
            calls["n"] += 1
            return f"label-{calls['n']}"

        with mock.patch.object(md, "display_name_for_model", side_effect=counted):
            md.format_tag_title(tag, repo)
            md.clear_display_cache()
            md.format_tag_title(tag, repo)

        self.assertEqual(calls["n"], 2)


if __name__ == "__main__":
    unittest.main()
