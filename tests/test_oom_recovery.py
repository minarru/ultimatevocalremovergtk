"""Tests for mid-run CUDA OOM recovery (choice + segment backoff)."""

from __future__ import annotations

import os
import tempfile
import unittest
from types import SimpleNamespace
from typing import Any, Optional
from unittest.mock import MagicMock, patch

from core.job_callbacks import JobCallbacks
from core.job_runner import JobRunner
from core.oom_choice import (
    OOM_CHOICE_AUTO,
    OOM_CHOICE_EXPORT,
    OOM_CHOICE_RETRY,
    OOM_CHOICE_STOP,
    OomChoiceRequest,
)
from core.run_control import ProcessStopped
from core.separator_run import export_ensemble_salvage, run_separator
from core.settings import Settings
from core.types import SaveFormat


class _OomError(RuntimeError):
    """Message-matched OOM without requiring torch.cuda.OutOfMemoryError."""

    def __init__(self) -> None:
        super().__init__("CUDA out of memory. Tried to allocate 1 GiB")


class FakeSeparator:
    def __init__(
        self,
        model: Any,
        *,
        fail_segments: Optional[set[int]] = None,
        always_fail: bool = False,
    ) -> None:
        self.model = model
        self.mdx_segment_size = int(getattr(model, "mdx_segment_size", 256))
        self.is_mdx_c_seg_def = bool(getattr(model, "is_mdx_c_seg_def", False))
        self.model_path = getattr(model, "model_path", "")
        self.device = "cpu"
        self._backend_name = "cpu"
        self._fail_segments = fail_segments or set()
        self._always_fail = always_fail
        self._ensemble_stem_buffers = {
            "Vocals": [[0.0] * 8, [0.0] * 8],
        }
        self._ensemble_stem_paths = {
            "Vocals": f"/tmp/{getattr(model, 'model_basename', 'model')} (Vocals).wav",
        }
        self.demix = True  # supports_segment_backoff sentinel

    def seperate(self) -> None:
        if self._always_fail:
            raise _OomError()
        if int(self.mdx_segment_size) in self._fail_segments:
            raise _OomError()


class OomChoiceRequestTests(unittest.TestCase):
    def test_respond_invokes_reply(self) -> None:
        seen: list[str] = []
        req = OomChoiceRequest(
            process_kind="ensemble",
            model_label="m",
            current_segment=2208,
            default_segment=256,
            first_retry_segment=1088,
            can_export=True,
            can_retry=True,
            completed_members=2,
            reply=seen.append,
        )
        req.respond(OOM_CHOICE_RETRY)
        self.assertEqual(seen, [OOM_CHOICE_RETRY])


class JobCallbacksOomTests(unittest.TestCase):
    def test_request_without_handler_returns_auto(self) -> None:
        callbacks = JobCallbacks()
        runner = MagicMock()
        runner._is_paused = False
        runner._is_stopped = False
        req = OomChoiceRequest(
            process_kind="separation",
            model_label="m",
            current_segment=512,
            default_segment=256,
            first_retry_segment=256,
            can_export=False,
            can_retry=True,
            completed_members=0,
        )
        self.assertEqual(callbacks.request_oom_choice(req, runner), OOM_CHOICE_AUTO)

    def test_request_blocks_until_reply(self) -> None:
        def on_choice(request: OomChoiceRequest) -> None:
            request.respond(OOM_CHOICE_STOP)

        callbacks = JobCallbacks(on_oom_choice=on_choice)
        runner = MagicMock()
        runner._is_paused = False
        runner._is_stopped = False
        req = OomChoiceRequest(
            process_kind="separation",
            model_label="m",
            current_segment=512,
            default_segment=256,
            first_retry_segment=256,
            can_export=False,
            can_retry=True,
            completed_members=0,
        )
        self.assertEqual(callbacks.request_oom_choice(req, runner), OOM_CHOICE_STOP)


class JobRunnerOomRecoveryTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.settings = Settings()
        self.settings.process.export_path = self._tmp.name
        self.settings.mdx.segment_size = 2208
        self.settings.mdx.is_mdx_c_seg_def = False
        self.runner = JobRunner(self.settings)
        self.runner._is_stopped = False
        self.runner._is_paused = False

    def _model(self, segment: int = 2208) -> SimpleNamespace:
        return SimpleNamespace(
            mdx_segment_size=segment,
            is_mdx_c_seg_def=False,
            is_mdx_c=True,
            is_roformer=False,
            process_method="MDX-Net",
            model_basename="scnet_tran",
            model_path="/tmp/scnet_tran.ckpt",
            model_name="SCNet Tran",
            repo=None,
            mdx_c_configs=SimpleNamespace(inference=SimpleNamespace(dim_t=256)),
        )

    @patch("core.separator_run.prepare_separator_vram")
    @patch("core.separator_run._release_inference_resources")
    @patch("core.separator_run.release_separator")
    def test_retry_uses_reduced_segment_without_persisting(
        self, _release_sep: Any, _release_inf: Any, _prep_vram: Any
    ) -> None:
        model = self._model(2208)
        settings_segment_before = self.settings.mdx.segment_size
        builds: list[int] = []

        def rebuild() -> FakeSeparator:
            builds.append(int(model.mdx_segment_size))
            return FakeSeparator(model, fail_segments={2208})

        choices = iter([OOM_CHOICE_RETRY])

        def on_choice(request: OomChoiceRequest) -> None:
            request.respond(next(choices))

        callbacks = JobCallbacks(on_oom_choice=on_choice, on_console=lambda _t: None)
        seperator = rebuild()
        stems = run_separator(
            self.runner,
            seperator,
            callbacks=callbacks,
            model=model,
            process_kind="separation",
            rebuild=rebuild,
        )
        self.assertIn("Vocals", stems)
        self.assertEqual(self.settings.mdx.segment_size, settings_segment_before)
        self.assertEqual(self.runner._mdx_segment_override, 1088)
        self.assertIn(1088, builds)

    @patch("core.separator_run.prepare_separator_vram")
    @patch("core.separator_run._release_inference_resources")
    @patch("core.separator_run.release_separator")
    def test_stop_raises_process_stopped(
        self, _release_sep: Any, _release_inf: Any, _prep_vram: Any
    ) -> None:
        model = self._model(2208)

        def rebuild() -> FakeSeparator:
            return FakeSeparator(model, always_fail=True)

        def on_choice(request: OomChoiceRequest) -> None:
            request.respond(OOM_CHOICE_STOP)

        callbacks = JobCallbacks(on_oom_choice=on_choice, on_console=lambda _t: None)
        with self.assertRaises(ProcessStopped):
            run_separator(
                self.runner,
                rebuild(),
                callbacks=callbacks,
                model=model,
                process_kind="separation",
                rebuild=rebuild,
            )

    @patch("core.separator_run.prepare_separator_vram")
    @patch("core.separator_run._release_inference_resources")
    @patch("core.separator_run.release_separator")
    def test_oom_dialog_prefers_the_carried_identity_display(
        self, _release_sep: Any, _release_inf: Any, _prep_vram: Any
    ) -> None:
        model = self._model(2208)
        model.model_display_label = "SCNet Transient"

        def rebuild() -> FakeSeparator:
            return FakeSeparator(model, always_fail=True)

        def on_choice(request: OomChoiceRequest) -> None:
            self.assertEqual(request.model_label, "SCNet Transient")
            request.respond(OOM_CHOICE_STOP)

        callbacks = JobCallbacks(on_oom_choice=on_choice, on_console=lambda _t: None)
        with self.assertRaises(ProcessStopped):
            run_separator(
                self.runner,
                rebuild(),
                callbacks=callbacks,
                model=model,
                process_kind="separation",
                rebuild=rebuild,
            )

    @patch("core.separator_run.prepare_separator_vram")
    @patch("core.separator_run._release_inference_resources")
    @patch("core.separator_run.release_separator")
    def test_auto_retries_then_reraises(
        self, _release_sep: Any, _release_inf: Any, _prep_vram: Any
    ) -> None:
        model = self._model(2208)

        def rebuild() -> FakeSeparator:
            return FakeSeparator(model, always_fail=True)

        callbacks = JobCallbacks(on_console=lambda _t: None)  # no on_oom_choice → auto
        with self.assertRaises(_OomError):
            run_separator(
                self.runner,
                rebuild(),
                callbacks=callbacks,
                model=model,
                process_kind="separation",
                rebuild=rebuild,
            )
        self.assertIsNotNone(self.runner._mdx_segment_override)

    @patch("core.separator_run.prepare_separator_vram")
    @patch("core.run_loop._write_captured_stems")
    @patch("core.separator_run._release_inference_resources")
    @patch("core.separator_run.release_separator")
    def test_export_writes_salvage_and_stops(
        self,
        _release_sep: Any,
        _release_inf: Any,
        write_stems: Any,
        _prep_vram: Any,
    ) -> None:
        model = self._model(2208)

        self.runner._ensemble_salvage_members = [
            {
                "arrays": {"Vocals": [[0.0, 0.0], [0.0, 0.0]]},
                "paths": {"Vocals": os.path.join(self._tmp.name, "a (Vocals).wav")},
                "audio_file_base": "a",
                "model_label": "A",
            }
        ]

        def rebuild() -> FakeSeparator:
            return FakeSeparator(model, always_fail=True)

        def on_choice(request: OomChoiceRequest) -> None:
            self.assertTrue(request.can_export)
            request.respond(OOM_CHOICE_EXPORT)

        console: list[str] = []
        callbacks = JobCallbacks(on_oom_choice=on_choice, on_console=console.append)
        with self.assertRaises(ProcessStopped):
            run_separator(
                self.runner,
                rebuild(),
                callbacks=callbacks,
                model=model,
                process_kind="ensemble",
                rebuild=rebuild,
            )
        write_stems.assert_called_once()
        self.assertTrue(self.runner._last_oom_exported)

    def test_disk_salvage_is_published_in_the_requested_format(self) -> None:
        import numpy as np
        import soundfile as sf

        with tempfile.TemporaryDirectory() as member_folder:
            member_path = os.path.join(member_folder, "song Model (Side).wav")
            sf.write(member_path, np.zeros((32, 2), dtype=np.float32), 44100)
            self.settings.process.save_format = SaveFormat.FLAC
            self.runner._ensemble_salvage_members = [
                {
                    "arrays": {},
                    "paths": {"Side": member_path},
                    "audio_file_base": "song Model",
                    "model_label": "Model",
                }
            ]

            export_ensemble_salvage(self.runner, JobCallbacks())

        self.assertTrue(os.path.isfile(os.path.join(self._tmp.name, "song Model (Side).flac")))
        self.assertFalse(os.path.isfile(os.path.join(self._tmp.name, "song Model (Side).wav")))

    def test_empty_salvage_member_does_not_report_a_successful_export(self) -> None:
        self.runner._ensemble_salvage_members = [
            {
                "arrays": {},
                "paths": {},
                "audio_file_base": "song Model",
                "model_label": "Model",
            }
        ]

        with self.assertRaisesRegex(RuntimeError, "no usable"):
            export_ensemble_salvage(self.runner, JobCallbacks())

        self.assertFalse(self.runner._last_oom_exported)


class DispatchOomCallbackTests(unittest.TestCase):
    @patch("ui.dispatch.main_thread", side_effect=lambda func: func)
    def test_gtk_job_callbacks_forwards_oom_choice(self, _main: Any) -> None:
        from ui.dispatch import gtk_job_callbacks

        handler = MagicMock()
        callbacks = gtk_job_callbacks(on_oom_choice=handler)
        req = OomChoiceRequest(
            process_kind="ensemble",
            model_label="m",
            current_segment=2208,
            default_segment=256,
            first_retry_segment=1088,
            can_export=True,
            can_retry=True,
            completed_members=1,
        )
        assert callbacks.on_oom_choice is not None
        callbacks.on_oom_choice(req)
        handler.assert_called_once_with(req)


class OomMockPayloadTests(unittest.TestCase):
    def test_mock_request_shows_all_responses(self) -> None:
        from ui.oom_dialog import mock_oom_request

        request = mock_oom_request(separation=False)
        self.assertTrue(request.can_export)
        self.assertTrue(request.can_retry)
        self.assertEqual(request.process_kind, "ensemble")
        self.assertGreaterEqual(request.completed_members, 1)
        self.assertTrue(request.is_debug_mock)
        sep = mock_oom_request(separation=True)
        self.assertFalse(sep.can_export)
        self.assertEqual(sep.process_kind, "separation")


if __name__ == "__main__":
    unittest.main()
