from __future__ import annotations

import os
import tempfile
import unittest
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import numpy as np

from bundled.constants import FLAC, WAV
from core.ensembler import CollectedStem, Ensembler
from core.run_hooks import _EnsembleRunHooks
from core.settings import Settings
from core.stem_roles import StemRoleId
from core.types import SaveFormat
from core.types.settings_enums import FlacBitDepth, Mp3Bitrate


def _ensembler(export_path: str) -> Ensembler:
    ensembler = object.__new__(Ensembler)
    ensembler.settings = Settings.defaults()
    ensembler.settings.ensemble.type = "Average/Average"
    ensembler.is_save_all_outputs_ensemble = True
    ensembler.primary_algorithm = "Average"
    ensembler.secondary_algorithm = "Average"
    ensembler.is_normalization = False
    ensembler.amplification_threshold = 0.0
    ensembler.is_wav_ensemble = True
    ensembler.wav_type_set = "PCM_16"
    ensembler.mp3_bit_set = Mp3Bitrate.K320
    ensembler.flac_bit_set = FlacBitDepth.BIT_16
    ensembler.save_format = WAV
    ensembler.main_export_path = export_path
    ensembler.ensemble_folder_name = export_path
    ensembler.append_ensemble_label = None
    side = CollectedStem(StemRoleId("spatial.side"), "Side")
    ensembler.pair_stems = (side,)
    return ensembler


class EnsembleFinalizationTests(unittest.TestCase):
    def test_multi_stem_run_with_no_viable_output_is_an_error(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            settings = Settings.defaults()
            runner = SimpleNamespace(settings=settings, true_model_count=2)
            state: Any = SimpleNamespace(
                scratch={
                    "ensemble_stem_arrays": {},
                    "ensemble_stem_paths": {},
                    "ensemble_stems": {},
                    "ensemble_contributors": {},
                    "ensemble_final_base": "song",
                },
                callbacks=SimpleNamespace(
                    console=lambda _text: None,
                    progress=lambda *_args, **_kwargs: None,
                ),
                progress_sink=SimpleNamespace(fraction=0.9),
                base_text="File 1/1 ",
                file_num=1,
                total_files=1,
            )
            hook = _EnsembleRunHooks(_ensembler(folder), is_multi_stem=True)

            with self.assertRaisesRegex(RuntimeError, "no viable stems"):
                hook.after_file(runner, state)

    def test_explicit_member_paths_are_combined_without_filename_rediscovery(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            member_a = os.path.join(folder, "unrelated-a.wav")
            member_b = os.path.join(folder, "unrelated-b.wav")
            for path in (member_a, member_b):
                with open(path, "wb") as handle:
                    handle.write(b"member")
            ensembler = _ensembler(folder)
            side = ensembler.pair_stems[0]

            def combine(
                _inputs: object,
                _algorithm: object,
                _normalize: object,
                _wav_type: object,
                output: str,
                **_kwargs: object,
            ) -> None:
                with open(output, "wb") as handle:
                    handle.write(b"ensemble")

            with patch("ml.spec_utils.ensemble_inputs", side_effect=combine):
                output = ensembler.ensemble_outputs(
                    "song Ensembled",
                    folder,
                    side,
                    stem_paths={side.group_key: [member_a, member_b]},
                )

            self.assertEqual(output, os.path.join(folder, "song Ensembled (Side).wav"))
            self.assertTrue(os.path.isfile(output))

    def test_retained_flac_members_and_final_output_are_all_published(self) -> None:
        import soundfile as sf

        with tempfile.TemporaryDirectory() as folder:
            member_a = os.path.join(folder, "member-a.wav")
            member_b = os.path.join(folder, "member-b.wav")
            wave = np.zeros((32, 2), dtype=np.float32)
            sf.write(member_a, wave, 44100)
            sf.write(member_b, wave, 44100)
            ensembler = _ensembler(folder)
            ensembler.save_format = FLAC
            side = ensembler.pair_stems[0]

            def combine(
                _inputs: object,
                _algorithm: object,
                _normalize: object,
                _wav_type: object,
                output: str,
                **_kwargs: object,
            ) -> None:
                sf.write(output, wave, 44100)

            with patch("ml.spec_utils.ensemble_inputs", side_effect=combine):
                output = ensembler.ensemble_outputs(
                    "song",
                    folder,
                    side,
                    stem_paths={side.group_key: [member_a, member_b]},
                )

            self.assertEqual(output, os.path.join(folder, "song (Side).flac"))
            self.assertTrue(os.path.isfile(output))
            self.assertTrue(os.path.isfile(os.path.join(folder, "member-a.flac")))
            self.assertTrue(os.path.isfile(os.path.join(folder, "member-b.flac")))
            self.assertFalse(os.path.exists(member_a))
            self.assertFalse(os.path.exists(member_b))

    def test_non_retained_members_combine_from_captured_arrays(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            ensembler = _ensembler(folder)
            ensembler.is_save_all_outputs_ensemble = False
            side = ensembler.pair_stems[0]
            arrays = [
                np.zeros((32, 2), dtype=np.float32),
                np.ones((32, 2), dtype=np.float32),
            ]

            def combine(
                _inputs: object,
                _algorithm: object,
                _normalize: object,
                _wav_type: object,
                output: str,
                **_kwargs: object,
            ) -> None:
                import soundfile as sf

                sf.write(output, arrays[0], 44100)

            with patch("ml.spec_utils.ensemble_inputs", side_effect=combine):
                output = ensembler.ensemble_outputs(
                    "song",
                    folder,
                    side,
                    stem_arrays={side.group_key: arrays},
                    stem_paths={},
                )

            self.assertTrue(os.path.isfile(output))

    def test_requested_stem_with_one_member_is_an_error(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            member = os.path.join(folder, "only.wav")
            with open(member, "wb") as handle:
                handle.write(b"member")
            ensembler = _ensembler(folder)
            side = ensembler.pair_stems[0]

            with self.assertRaisesRegex(RuntimeError, "at least two"):
                ensembler.ensemble_outputs(
                    "song",
                    folder,
                    side,
                    stem_paths={side.group_key: [member]},
                )

    def test_chunked_save_all_writes_member_and_registers_its_actual_path(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            settings = Settings.defaults()
            settings.ensemble.save_all_outputs = True
            settings.process.save_format = SaveFormat.WAV
            runner: Any = SimpleNamespace(settings=settings, _ensemble_salvage_members=[])
            side = CollectedStem(StemRoleId("spatial.side"), "Side")
            member_path = os.path.join(folder, "song Model (Side).wav")
            state: Any = SimpleNamespace(
                chunked=True,
                ov_samples=[],
                scratch={
                    "member_stem_parts": {side: [np.zeros((32, 2), dtype=np.float32)]},
                    "ensemble_stem_arrays": {},
                    "ensemble_stem_paths": {},
                    "member_paths": {side.group_key: member_path},
                    "audio_file_base": "song Model",
                    "model_label": "Model",
                },
                callbacks=SimpleNamespace(console=lambda _text: None),
            )
            hook = _EnsembleRunHooks(_ensembler(folder), is_multi_stem=False)

            hook.after_model(runner, state, SimpleNamespace())

            self.assertTrue(os.path.isfile(member_path))
            self.assertEqual(
                state.scratch["ensemble_stem_paths"][side.group_key],
                [member_path],
            )


if __name__ == "__main__":
    unittest.main()
