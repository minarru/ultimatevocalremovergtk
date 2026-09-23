"""Separation stages announce their phase before doing blocking work."""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import patch

import numpy as np

from core.processing_phase import ProcessingPhase as Phase
from engines.base import SeperateAttributes
from engines.stem_writer import _save_with_message


class SeparationPhaseTests(unittest.TestCase):
    def test_ensemble_reports_current_output_before_work_and_retains_eta(self):
        from core.ensembler import CollectedStem, Ensembler
        from core.job_callbacks import JobCallbacks
        from core.run_hooks import _EnsembleRunHooks
        from core.run_loop import FileState
        from core.settings import Settings
        from core.stem_roles import StemRoleId
        from ui.run_progress import RunProgressPresenter

        ensemble = Ensembler.__new__(Ensembler)
        stems = (
            CollectedStem(StemRoleId("vocal.vocals"), "Vocals"),
            CollectedStem(StemRoleId("mix.instrumental"), "Instrumental"),
        )
        ensemble.pair_stems = stems
        ensemble.ensemble_folder_name = "/unused"
        ensemble.append_ensemble_label = None
        settings = Settings.defaults()
        settings.ensemble.derive_complement_from_mix = False
        settings.process.stem_focus = ""
        runner = SimpleNamespace(settings=settings, true_model_count=2)
        clock = [100.0]
        seen = []
        presenter = RunProgressPresenter()

        def progress(fraction: float, **meta: Any):
            result = presenter.update(fraction, clock[0], **meta)
            if result is not None:
                seen.append(result)

        state = SimpleNamespace(
            callbacks=JobCallbacks(on_progress=progress),
            scratch={
                "ensemble_stem_arrays": {stem.group_key: [1, 2] for stem in stems},
                "ensemble_final_base": "Song",
            },
            progress_sink=SimpleNamespace(fraction=0.9),
            file_num=1,
            total_files=1,
        )
        calls = []

        def combine(*args: Any, **kwargs: Any):
            calls.append(seen[-1].text)
            clock[0] += 10
            return np.zeros((8, 2))

        def write(*args: Any, **kwargs: Any):
            clock[0] += 2
            return "unused.wav"

        with (
            patch.object(ensemble, "_collect_member_files", return_value=[]),
            patch.object(ensemble, "combine_stem_waveforms", side_effect=combine),
            patch.object(ensemble, "write_stem_waveform", side_effect=write),
            patch.object(ensemble, "publish_member_files"),
        ):
            _EnsembleRunHooks(ensemble, is_multi_stem=False).after_file(
                runner, cast(FileState, state)
            )
        self.assertIn("Combining outputs (1/2)", calls[0])
        self.assertIn("Combining outputs (2/2)", calls[1])
        self.assertIn("~0:12 left", calls[1])

    def test_loading_and_inference_have_role_specific_phases(self):
        for flag, load, infer in (
            (None, Phase.LOADING_MODEL, Phase.SEPARATING),
            ("is_secondary_model", Phase.LOADING_SECONDARY, Phase.SEPARATING_SECONDARY),
            ("is_pre_proc_model", Phase.LOADING_PREPROCESS, Phase.PREPROCESSING),
            ("is_vocal_split_model", Phase.LOADING_SPLITTER, Phase.SPLITTING_VOCALS),
        ):
            with self.subTest(role=flag):
                phases = []
                messages = []
                sep = SimpleNamespace(
                    process_data=SimpleNamespace(report_phase=phases.append),
                    is_secondary_model=False,
                    is_pre_proc_model=False,
                    is_vocal_split_model=False,
                    process_method="MDX-Net",
                    model_display_label="Model",
                    write_to_console=lambda text, messages=messages, phases=phases, **kwargs: (
                        messages.append((text, phases[-1] if phases else None))
                    ),
                    set_progress_bar=lambda _: None,
                )
                if flag:
                    setattr(sep, flag, True)
                SeperateAttributes.start_inference_console_write(cast(SeperateAttributes, sep))
                self.assertEqual(phases[-1:], [load])
                SeperateAttributes.running_inference_console_write(cast(SeperateAttributes, sep))
                self.assertEqual(phases[-1], infer)
                self.assertEqual(messages[-1][1], infer)

    def test_buffered_stems_are_collected_not_reported_as_disk_writes(self):
        for capture, ensemble in ((True, False), (False, True), (False, False)):
            with self.subTest(capture=capture, ensemble=ensemble):
                phases = []
                messages = []
                writes = []
                sep = SimpleNamespace(
                    process_data=SimpleNamespace(report_phase=phases.append),
                    capture_stems_only=capture,
                    is_ensemble_mode=ensemble,
                    is_vocal_split_model=False,
                    is_save_all_outputs_ensemble=False,
                    is_deverb_vocals=False,
                    is_normalization=False,
                    amplification_threshold=0,
                    is_prevent_export_clipping=False,
                    save_format="WAV",
                    wav_type_set="FLOAT",
                    mp3_bit_set="320k",
                    flac_bit_set="PCM_16",
                    opus_bit_set="192k",
                    write_to_console=lambda text, messages=messages, phases=phases, **kwargs: (
                        messages.append(text)
                    ),
                )
                with patch(
                    "engines.stem_writer.sf.write",
                    side_effect=lambda *a, writes=writes, phases=phases, **k: writes.append(
                        phases[-1] if phases else None
                    ),
                ):
                    _save_with_message(
                        sep,
                        "vocals.wav",
                        "Vocals",
                        np.zeros((8, 2)),
                        samplerate=44100,
                        buffer_stem_name="Vocals",
                        is_not_ensemble=False,
                    )
                phase = Phase.BUFFERING if capture or ensemble else Phase.SAVING
                self.assertEqual(phases[-1:], [phase])
                if capture or ensemble:
                    self.assertEqual(writes, [])
                    self.assertEqual("".join(messages), "Collecting Vocals... Done!\n")
                else:
                    self.assertEqual(writes, [Phase.SAVING])
                    self.assertEqual("".join(messages), "Saving Vocals... Done!\n")

    def test_deverb_announces_processing_before_batches_and_saving_before_writes(self):
        from engines.stem_writer import _deverb_vocals

        phases = []
        operations = []
        sep = SimpleNamespace(
            process_data=SimpleNamespace(report_phase=phases.append),
            write_to_console=lambda *a, **k: None,
            device="cpu",
            DEVERBER_MODEL="deverb.pth",
            settings=None,
            deverb_progress_callback=lambda: None,
            check_run_control=lambda: None,
            capture_stems_only=False,
            is_ensemble_mode=False,
            is_vocal_split_model=False,
            is_prevent_export_clipping=False,
            is_normalization=False,
            amplification_threshold=0,
            save_format="WAV",
            wav_type_set="FLOAT",
        )
        wave = np.zeros((8, 2))

        def denoise(*args: Any, **kwargs: Any):
            operations.append(("deverb", phases[-1]))
            return wave, wave

        with (
            patch("engines.stem_writer.vr_denoiser", side_effect=denoise),
            patch(
                "engines.stem_writer.sf.write",
                side_effect=lambda *a, **k: operations.append(("write", phases[-1])),
            ),
        ):
            _deverb_vocals(
                sep,
                "vocals.wav",
                wave,
                samplerate=44100,
                buffer_stem_name="Vocals",
                is_not_ensemble=False,
            )
        self.assertEqual(
            operations,
            [("deverb", Phase.DEVERBING), ("write", Phase.SAVING), ("write", Phase.SAVING)],
        )

    def test_ensemble_labels_combination_and_export_at_their_boundaries(self):
        from core.ensembler import CollectedStem, Ensembler
        from core.stem_roles import StemRoleId

        phases = []
        operations = []
        ensemble = Ensembler.__new__(Ensembler)
        stem = CollectedStem(StemRoleId("vocal.vocals"), "Vocals")

        def combine(*args: Any, **kwargs: Any):
            operations.append(("combine", phases[-1]))
            return np.zeros((8, 2))

        def write(*args: Any, **kwargs: Any):
            operations.append(("write", phases[-1]))
            return "vocals.wav"

        with (
            patch.object(ensemble, "_collect_member_files", return_value=[]),
            patch.object(ensemble, "combine_stem_waveforms", side_effect=combine),
            patch.object(ensemble, "write_stem_waveform", side_effect=write),
            patch.object(ensemble, "publish_member_files"),
        ):
            ensemble.ensemble_outputs(
                "song",
                "/tmp",
                stem,
                stem_arrays={stem.group_key: [0, 0]},
                report_phase=phases.append,
            )
        self.assertEqual(operations, [("combine", Phase.COMBINING), ("write", Phase.SAVING)])

    def test_demucs_skipped_preprocess_still_announces_main_inference(self):
        from engines.demucs_engine import SeperateDemucs
        from engines.demucs_runtime import infer_demucs_native

        phases = []
        sep = SimpleNamespace(
            process_data=SimpleNamespace(report_phase=phases.append),
            primary_model_name=None,
            model_cache_key="model",
            pre_proc_model=object(),
            primary_stem="Vocals",
            audio_file=np.zeros((2, 8)),
            model_display_label="Demucs",
            demucs_version="v4",
            device="cpu",
            is_secondary_model=False,
            is_pre_proc_model=False,
            is_vocal_split_model=False,
            write_to_console=lambda *a, **k: None,
            set_progress_bar=lambda _: None,
        )
        sep.start_inference_console_write = lambda: (
            SeperateAttributes.start_inference_console_write(cast(SeperateAttributes, sep))
        )
        sep.running_inference_console_write = lambda **kwargs: (
            SeperateAttributes.running_inference_console_write(
                cast(SeperateAttributes, sep), **kwargs
            )
        )

        def infer(_mix: Any):
            self.assertEqual(phases[-1], Phase.SEPARATING)
            raise RuntimeError("test inference boundary")

        sep.demix_demucs = infer
        with (
            patch("engines.demucs_runtime.DemucsAcquisitionRequest.from_separator"),
            patch("engines.demucs_runtime.acquire_demucs_model"),
        ):
            with self.assertRaisesRegex(RuntimeError, "test inference boundary"):
                infer_demucs_native(
                    cast(SeperateDemucs, sep),
                    prepare_mix=lambda audio: audio,
                    process_secondary_model=lambda *a, **k: None,
                )
