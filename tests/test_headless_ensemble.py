"""Headless ensemble entry point (no models, no torch — JobRunner is faked)."""

import unittest
from typing import Any, List, Optional, Sequence
from unittest import mock

from bundled.constants import (
    ENSEMBLE_MODE,
    ENSEMBLE_PARTITION,
    MAX_MIN,
    MDX_ARCH_TYPE,
    VR_ARCH_TYPE,
)
from core.headless_run import (
    apply_saved_ensemble,
    build_settings,
    resolve_ensemble_members,
    resolve_method,
    run_ensemble_sync,
)
from core.settings import Settings
from core.stems import EnsemblePair
from core.types import ProcessMethod


class _FakeRunner:
    """Records which start method was used and fires callbacks synchronously."""

    calls: List[str] = []

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._thread = None
        self.error: Optional[BaseException] = None

    def is_running(self) -> bool:
        return False

    def start(self, input_paths: Sequence[str], callbacks: Any) -> None:
        _FakeRunner.calls.append("single")
        callbacks.complete()

    def start_ensemble(self, input_paths: Sequence[str], callbacks: Any) -> None:
        _FakeRunner.calls.append("ensemble")
        callbacks.console("combining\n")
        if self.error is not None:
            callbacks.error(self.error)
        else:
            callbacks.complete()

    def release_inference_memory(self, **kwargs: Any) -> None:
        pass

    def stop(self, **kwargs: Any) -> None:
        pass


class RunEnsembleSyncTests(unittest.TestCase):
    def setUp(self) -> None:
        _FakeRunner.calls = []
        self.settings = Settings()
        self.settings.process.method = ProcessMethod(ENSEMBLE_MODE)
        self.settings.process.export_path = "/tmp/sweep-export"

    def test_uses_start_ensemble(self) -> None:
        with mock.patch("core.headless_run.JobRunner", _FakeRunner):
            result = run_ensemble_sync(self.settings, ["/tmp/in.wav"], print_console=False)
        self.assertEqual(_FakeRunner.calls, ["ensemble"])
        self.assertTrue(result.ok)
        self.assertIn("combining\n", result.console)

    def test_reports_error(self) -> None:
        boom = RuntimeError("member failed")

        def factory(settings: Settings) -> _FakeRunner:
            runner = _FakeRunner(settings)
            runner.error = boom
            return runner

        with mock.patch("core.headless_run.JobRunner", factory):
            result = run_ensemble_sync(self.settings, ["/tmp/in.wav"], print_console=False)
        self.assertFalse(result.ok)
        self.assertIs(result.error, boom)

    def test_requires_input_paths(self) -> None:
        with self.assertRaises(ValueError):
            run_ensemble_sync(self.settings, [], print_console=False)

    def test_requires_export_path(self) -> None:
        self.settings.process.export_path = ""
        with self.assertRaises(ValueError):
            run_ensemble_sync(self.settings, ["/tmp/in.wav"], print_console=False)


class BuildSettingsEnsembleTests(unittest.TestCase):
    def test_rejects_ensemble_by_default(self) -> None:
        settings = Settings()
        settings.process.method = ProcessMethod(ENSEMBLE_MODE)
        with mock.patch("core.headless_run.Settings.load", return_value=settings):
            with self.assertRaises(ValueError):
                build_settings(export_path="/tmp/out")

    def test_allows_ensemble_when_opted_in(self) -> None:
        settings = Settings()
        settings.process.method = ProcessMethod(ENSEMBLE_MODE)
        with mock.patch("core.headless_run.Settings.load", return_value=settings):
            built = build_settings(export_path="/tmp/out", allow_ensemble=True)
        self.assertEqual(built.process.method, ENSEMBLE_MODE)


class _FakeRepo:
    """Minimal stand-in for ModelRepository — no disk, no network."""

    def all_model_tags(self) -> list[str]:
        return [
            f"{MDX_ARCH_TYPE}{ENSEMBLE_PARTITION}Kim Vocal 2",
            f"{MDX_ARCH_TYPE}{ENSEMBLE_PARTITION}Inst HQ 3",
            f"{VR_ARCH_TYPE}{ENSEMBLE_PARTITION}UVR-DeEcho-DeReverb",
        ]


class ResolveEnsembleMembersTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repo = _FakeRepo()

    def test_exact_tag_passes_through(self) -> None:
        tag = f"{MDX_ARCH_TYPE}{ENSEMBLE_PARTITION}Kim Vocal 2"
        self.assertEqual(resolve_ensemble_members([tag], self.repo), [tag])

    def test_unique_substring_resolves(self) -> None:
        self.assertEqual(
            resolve_ensemble_members(["kimvocal2"], self.repo),
            [f"{MDX_ARCH_TYPE}{ENSEMBLE_PARTITION}Kim Vocal 2"],
        )

    def test_ambiguous_token_raises(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            resolve_ensemble_members(["a"], self.repo)
        self.assertIn("ambiguous", str(ctx.exception))

    def test_unknown_token_raises(self) -> None:
        with self.assertRaises(ValueError):
            resolve_ensemble_members(["no-such-model"], self.repo)

    def test_duplicates_collapse_preserving_order(self) -> None:
        members = resolve_ensemble_members(["kimvocal2", "insthq3", "kimvocal2"], self.repo)
        self.assertEqual(
            members,
            [
                f"{MDX_ARCH_TYPE}{ENSEMBLE_PARTITION}Kim Vocal 2",
                f"{MDX_ARCH_TYPE}{ENSEMBLE_PARTITION}Inst HQ 3",
            ],
        )


class ApplySavedEnsembleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.settings = Settings()

    def test_applies_every_field(self) -> None:
        data = {
            "ensemble_main_stem": "vocals_instrumental",
            "ensemble_type": MAX_MIN,
            "selected_models": ["MDX-Net: A", "MDX-Net: B"],
        }
        with mock.patch("core.model_data.load_ensemble", return_value=data):
            apply_saved_ensemble(self.settings, "My Mix")
        self.assertEqual(self.settings.ensemble.main_stem, EnsemblePair.VOCALS_INSTRUMENTAL)
        self.assertEqual(self.settings.ensemble.type, MAX_MIN)
        self.assertEqual(self.settings.ensemble.selected_models, ["MDX-Net: A", "MDX-Net: B"])
        self.assertEqual(self.settings.ensemble.chosen_ensemble, "My Mix")

    def test_missing_preset_raises(self) -> None:
        with mock.patch("core.model_data.load_ensemble", return_value=None), \
             mock.patch("core.model_data.list_saved_ensembles", return_value=["Other"]), \
             mock.patch("core.ensemble_presets.list_curated_ensembles", return_value=["kim_vocal"]), \
             mock.patch("core.ensemble_presets.load_curated_ensemble", return_value=None):
            with self.assertRaises(ValueError) as ctx:
                apply_saved_ensemble(self.settings, "Nope")
        self.assertIn("Nope", str(ctx.exception))

    def test_curated_gui_label_resolves_member_tags(self) -> None:
        data = {
            "ensemble_main_stem": "vocals_instrumental",
            "ensemble_type": MAX_MIN,
            "selected_models": ["MDX-Net: old name"],
        }
        repo = mock.Mock()
        with mock.patch("core.ensemble_presets.load_curated_ensemble", return_value=data), \
             mock.patch(
                 "core.ensemble_presets.resolve_member_tags",
                 return_value=["MDX-Net: New Name"],
             ) as resolve:
            apply_saved_ensemble(self.settings, "Curated: Kim Vocal Inst", repo=repo)
        resolve.assert_called_once()
        self.assertEqual(self.settings.ensemble.selected_models, ["MDX-Net: New Name"])
        self.assertTrue(
            self.settings.ensemble.chosen_ensemble.startswith("Curated:")
        )

    def test_curated_id_without_prefix(self) -> None:
        data = {
            "ensemble_main_stem": "karaoke",
            "ensemble_type": MAX_MIN,
            "selected_models": ["MDX-Net: A", "MDX-Net: B"],
        }
        with mock.patch("core.model_data.load_ensemble", return_value=None), \
             mock.patch("core.ensemble_presets.list_curated_ensembles",
                        return_value=["kim_vocal"]), \
             mock.patch("core.ensemble_presets.load_curated_ensemble", return_value=data), \
             mock.patch("core.ensemble_presets.resolve_member_tags",
                        side_effect=lambda tags, repo: list(tags)):
            apply_saved_ensemble(self.settings, "kim_vocal")
        self.assertEqual(
            self.settings.ensemble.chosen_ensemble, "Curated: kim vocal"
        )

    def test_user_saved_wins_when_name_equals_a_curated_id(self) -> None:
        saved = {
            "ensemble_main_stem": "drums",
            "ensemble_type": MAX_MIN,
            "selected_models": ["VR Arch: A", "VR Arch: B"],
        }
        with mock.patch("core.model_data.load_ensemble", return_value=saved):
            apply_saved_ensemble(self.settings, "kim_vocal")
        self.assertEqual(self.settings.ensemble.chosen_ensemble, "kim_vocal")
        self.assertEqual(self.settings.ensemble.main_stem, EnsemblePair.DRUMS)


class EnsembleMethodAliasTests(unittest.TestCase):
    def test_ensemble_alias_resolves(self) -> None:
        self.assertEqual(resolve_method("ensemble"), ENSEMBLE_MODE)
        self.assertEqual(resolve_method("Ensemble Mode"), ENSEMBLE_MODE)


if __name__ == "__main__":
    unittest.main()
