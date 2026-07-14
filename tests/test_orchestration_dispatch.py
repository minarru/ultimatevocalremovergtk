"""Orchestration engine dispatch and nested cleanup."""

import unittest
from types import SimpleNamespace
from unittest import mock

from bundled.constants import VR_ARCH_TYPE
from engines.mix import gather_sources
from engines.orchestration import _build_seperator, _run_seperator


class OrchestrationDispatchTests(unittest.TestCase):
    def test_unknown_process_method_raises(self) -> None:
        model = SimpleNamespace(process_method="Unknown Engine", is_mdx_c=False)
        with self.assertRaises(NotImplementedError):
            _build_seperator(model, {})

    @mock.patch("engines.orchestration.release_separator")
    def test_run_seperator_always_releases(self, release_mock: mock.MagicMock) -> None:
        separator = mock.MagicMock()
        separator.seperate.return_value = {"Vocals": [1]}
        result = _run_seperator(separator)
        separator.seperate.assert_called_once_with()
        release_mock.assert_called_once_with(separator)
        self.assertEqual(result, {"Vocals": [1]})

    @mock.patch("engines.orchestration.release_separator")
    def test_run_seperator_releases_on_exception(self, release_mock: mock.MagicMock) -> None:
        separator = mock.MagicMock()
        separator.seperate.side_effect = RuntimeError("boom")
        with self.assertRaises(RuntimeError):
            _run_seperator(separator)
        release_mock.assert_called_once_with(separator)

    def test_build_seperator_returns_vr_for_vr_arch(self) -> None:
        model = SimpleNamespace(process_method=VR_ARCH_TYPE, is_mdx_c=False)
        with mock.patch("engines.orchestration._engine_classes") as engine_classes:
            vr_cls = mock.MagicMock(name="SeperateVR")
            engine_classes.return_value = (vr_cls, mock.MagicMock(), mock.MagicMock(), mock.MagicMock())
            seperator = _build_seperator(model, {})
            vr_cls.assert_called_once()
            self.assertIs(seperator, vr_cls.return_value)


class GatherSourcesTests(unittest.TestCase):
    def test_exact_key_match_preferred(self) -> None:
        sources = {"Vocals": "v", "No Vocals": "nv"}
        primary, secondary = gather_sources("Vocals", "No Vocals", sources)
        self.assertEqual(primary, "v")
        self.assertEqual(secondary, "nv")

    def test_substring_fallback_when_exact_missing(self) -> None:
        sources = {"lead_vocals": "lead"}
        primary, secondary = gather_sources("lead_vocals_track", "instrumental", sources)
        self.assertEqual(primary, "lead")
        self.assertFalse(secondary)


if __name__ == "__main__":
    unittest.main()
