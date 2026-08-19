"""Orchestration engine dispatch and nested cleanup."""

import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest import mock

from bundled.constants import VR_ARCH_TYPE
import engines.orchestration as orchestration
from engines.mix import gather_sources
from engines.orchestration import _run_seperator, process_chain_model
from engines.separator_factory import build_seperator

_REPO = Path(__file__).resolve().parents[1]


class OrchestrationDispatchTests(unittest.TestCase):
    def test_unknown_process_method_raises(self) -> None:
        model = SimpleNamespace(process_method="Unknown Engine", is_mdx_c=False)
        with self.assertRaises(NotImplementedError):
            build_seperator(model, {})

    @mock.patch("engines.stem_writer.finish_export")
    @mock.patch("core.separator_run.release_separator")
    def test_run_seperator_always_releases(
        self, release_mock: mock.MagicMock, finish_mock: mock.MagicMock
    ) -> None:
        from engines.stem_writer import ExportPlan

        separator = mock.MagicMock()
        plan = ExportPlan(sources={"Vocals": [1]})
        separator.seperate.return_value = plan
        finish_mock.return_value = {"Vocals": [1]}
        result = _run_seperator(separator)
        separator.seperate.assert_called_once_with()
        finish_mock.assert_called_once_with(separator, plan)
        release_mock.assert_called_once_with(separator)
        self.assertEqual(result, {"Vocals": [1]})

    @mock.patch("core.separator_run.release_separator")
    def test_run_seperator_releases_on_exception(
        self, release_mock: mock.MagicMock
    ) -> None:
        separator = mock.MagicMock()
        separator.seperate.side_effect = RuntimeError("boom")
        with self.assertRaises(RuntimeError):
            _run_seperator(separator)
        release_mock.assert_called_once_with(separator)

    def test_build_seperator_returns_vr_for_vr_arch(self) -> None:
        model = SimpleNamespace(process_method=VR_ARCH_TYPE, is_mdx_c=False)
        with mock.patch("engines.separator_factory._engine_classes") as engine_classes:
            vr_cls = mock.MagicMock(name="SeperateVR")
            engine_classes.return_value = (
                vr_cls,
                mock.MagicMock(),
                mock.MagicMock(),
                mock.MagicMock(),
            )
            seperator = build_seperator(model, {})
            vr_cls.assert_called_once()
            self.assertIs(seperator, vr_cls.return_value)


class SeparatorFactoryBoundaryTests(unittest.TestCase):
    def test_chain_resolves_factory_from_canonical_module(self) -> None:
        model: Any = SimpleNamespace(
            bv_model_rebalance=False,
            process_method=VR_ARCH_TYPE,
        )
        process_data = mock.MagicMock()
        canonical_separator = mock.MagicMock()

        with (
            mock.patch(
                "engines.separator_factory.build_seperator",
                return_value=canonical_separator,
            ) as canonical_build,
            mock.patch(
                "engines.separator_factory._engine_classes",
                return_value=(
                    mock.MagicMock(),
                    mock.MagicMock(),
                    mock.MagicMock(),
                    mock.MagicMock(),
                ),
            ),
            mock.patch("engines.orchestration._run_seperator", return_value=None),
        ):
            process_chain_model(
                model,
                process_data,
                vocal_stem_path=None,
                master_vocal_source=object(),
            )

        canonical_build.assert_called_once()

    def test_job_runner_does_not_dispatch_engine_classes(self) -> None:
        source = (_REPO / "core" / "job_runner.py").read_text(encoding="utf-8")
        self.assertNotIn("SeperateVR", source)
        self.assertNotIn("SeperateMDX", source)
        self.assertNotIn("SeperateMDXC", source)
        self.assertNotIn("SeperateDemucs", source)
        self.assertIn("build_seperator", source)
        self.assertNotIn("engines.separate", source)
        self.assertNotIn("engines=", source)

    def test_factory_exposes_preload_engine_modules(self) -> None:
        import engines.separator_factory as factory

        preload = getattr(factory, "preload_engine_modules", None)
        self.assertTrue(callable(preload))
        assert preload is not None
        with mock.patch.object(factory, "_engine_classes") as engine_classes:
            engine_classes.return_value = (
                mock.MagicMock(),
                mock.MagicMock(),
                mock.MagicMock(),
                mock.MagicMock(),
            )
            self.assertIsNone(preload())
            engine_classes.assert_called_once()

    def test_orchestration_does_not_expose_factory(self) -> None:
        source = (_REPO / "engines" / "orchestration.py").read_text(encoding="utf-8")
        self.assertFalse(hasattr(orchestration, "build_seperator"))
        self.assertNotIn("def build_seperator", source)
        self.assertNotIn("def _build_seperator", source)
        self.assertNotIn("def _engine_classes", source)

    def test_orchestration_does_not_define_separate_pass(self) -> None:
        source = (_REPO / "engines" / "orchestration.py").read_text(encoding="utf-8")
        self.assertNotIn("def finish_export", source)
        self.assertNotIn("class ExportPlan", source)
        self.assertIn("run_separate_pass", source)


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
