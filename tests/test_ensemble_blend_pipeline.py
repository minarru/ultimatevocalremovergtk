from __future__ import annotations

import unittest
from types import SimpleNamespace
from typing import Any, cast

import numpy as np

from bundled.constants import AUDIO_AVERAGE, CHUNK_MIN, MAX_SPEC, MIN_SPEC
from core.ensembler import CollectedStem, Ensembler
from core.run_hooks import _EnsembleRunHooks
from core.settings import Settings
from core.stem_roles import StemRoleId
from core.stems import StemId, StemRoute
from ml.ensemble_alignment import AlignmentDiagnostic
from ml.spec_utils import combine_ensemble_waveforms


class EnsembleWaveformPipelineTests(unittest.TestCase):
    def test_weighted_average_renormalizes_when_short_member_ends(self) -> None:
        short = np.full((2, 3), 2.0, dtype=np.float32)
        long = np.full((2, 5), 10.0, dtype=np.float32)

        output, _rate = combine_ensemble_waveforms(
            [short, long],
            AUDIO_AVERAGE,
            is_array=True,
            weights=[3.0, 1.0],
        )

        expected = np.full((2, 5), 10.0, dtype=np.float32)
        expected[:, :3] = 4.0
        np.testing.assert_allclose(output, expected)

    def test_wave_min_and_max_do_not_vote_with_missing_tail(self) -> None:
        low_short = np.full((2, 3), 1.0, dtype=np.float32)
        high_long = np.full((2, 5), 5.0, dtype=np.float32)
        high_short = np.full((2, 3), 9.0, dtype=np.float32)

        minimum, _rate = combine_ensemble_waveforms(
            [low_short, high_long], MIN_SPEC, is_wave=True, is_array=True
        )
        maximum, _rate = combine_ensemble_waveforms(
            [high_short, high_long], MAX_SPEC, is_wave=True, is_array=True
        )

        expected_min = high_long.copy()
        expected_min[:, :3] = 1.0
        expected_max = high_long.copy()
        expected_max[:, :3] = 9.0
        np.testing.assert_array_equal(minimum, expected_min)
        np.testing.assert_array_equal(maximum, expected_max)

    def test_empty_and_tiny_members_preserve_real_samples(self) -> None:
        empty = np.empty((2, 0), dtype=np.float32)
        tiny = np.array([[0.25], [-0.5]], dtype=np.float32)

        for algorithm in (AUDIO_AVERAGE, MIN_SPEC, MAX_SPEC):
            with self.subTest(algorithm=algorithm):
                output, _rate = combine_ensemble_waveforms(
                    [empty, tiny], algorithm, is_wave=True, is_array=True
                )
                np.testing.assert_array_equal(output, tiny)

    def test_all_empty_members_return_an_empty_stereo_timeline(self) -> None:
        members = [
            np.empty((2, 0), dtype=np.float32),
            np.empty((2, 0), dtype=np.float32),
        ]

        for algorithm, is_wave in (
            (AUDIO_AVERAGE, False),
            (MIN_SPEC, True),
            (MIN_SPEC, False),
        ):
            with self.subTest(algorithm=algorithm, is_wave=is_wave):
                output, _rate = combine_ensemble_waveforms(
                    members, algorithm, is_wave=is_wave, is_array=True
                )
                self.assertEqual(output.shape, (2, 0))

    def test_spectral_minimum_excludes_short_member_beyond_real_tail(self) -> None:
        rng = np.random.default_rng(31)
        long = rng.normal(0.0, 0.2, (2, 16_384)).astype(np.float32)
        short = (long[:, :4_096] * 0.1).copy()

        combined, _rate = combine_ensemble_waveforms(
            [long, short], MIN_SPEC, is_array=True, smoothing=0
        )
        long_only, _rate = combine_ensemble_waveforms([long], MIN_SPEC, is_array=True, smoothing=0)

        np.testing.assert_allclose(combined[:, 8_192:], long_only[:, 8_192:], atol=1e-7)

    def test_spectral_minimum_ignores_empty_member(self) -> None:
        rng = np.random.default_rng(37)
        empty = np.empty((2, 0), dtype=np.float32)
        member = rng.normal(0.0, 0.2, (2, 4_096)).astype(np.float32)

        combined, _rate = combine_ensemble_waveforms(
            [empty, member], MIN_SPEC, is_array=True, smoothing=0
        )
        member_only, _rate = combine_ensemble_waveforms(
            [member], MIN_SPEC, is_array=True, smoothing=0
        )

        np.testing.assert_allclose(combined, member_only, atol=1e-7)

    def test_correction_preserves_timeline_stereo_and_reports_offsets(self) -> None:
        sample_rate = 44_100
        rng = np.random.default_rng(123)
        reference = rng.normal(0.0, 0.1, (2, sample_rate)).astype(np.float32)
        reference[1] *= 0.43
        late_by = 137
        early_by = 89
        late = np.pad(reference[:, :-late_by], ((0, 0), (late_by, 0)))
        early = np.pad(reference[:, early_by:], ((0, 0), (0, early_by)))
        reports: list[AlignmentDiagnostic] = []

        output, _rate = combine_ensemble_waveforms(
            [reference, late, early],
            AUDIO_AVERAGE,
            is_array=True,
            align=True,
            on_alignment=lambda diagnostics: reports.extend(diagnostics),
        )

        self.assertEqual(output.shape, reference.shape)
        np.testing.assert_allclose(output, reference, atol=1e-7)
        self.assertEqual([item.delay_samples for item in reports], [0, late_by, -early_by])
        self.assertEqual([item.applied for item in reports], [False, True, True])
        self.assertEqual(reports[2].valid_start_samples, early_by)
        self.assertEqual(reports[1].valid_end_samples, reference.shape[-1] - late_by)

    def test_zero_weight_filter_keeps_original_diagnostic_member_indices(self) -> None:
        sample_rate = 44_100
        rng = np.random.default_rng(9)
        reference = rng.normal(0.0, 0.1, (2, sample_rate)).astype(np.float32)
        delay = 101
        excluded = np.zeros((2, sample_rate + 500), dtype=np.float32)
        late = np.pad(reference[:, :-delay], ((0, 0), (delay, 0)))
        reports: list[AlignmentDiagnostic] = []

        output, _rate = combine_ensemble_waveforms(
            [excluded, reference, late],
            AUDIO_AVERAGE,
            is_array=True,
            weights=[0.0, 1.0, 1.0],
            on_alignment=lambda diagnostics: reports.extend(diagnostics),
        )

        self.assertEqual(output.shape, reference.shape)
        self.assertEqual([item.member_index for item in reports], [1, 2])
        self.assertEqual(reports[1].delay_samples, delay)

    def test_chunk_min_applies_alignment_and_reports_diagnostics(self) -> None:
        sample_rate = 44_100
        rng = np.random.default_rng(71)
        reference = rng.normal(0.0, 0.1, (2, sample_rate)).astype(np.float32)
        delay = 700
        late = np.pad(reference[:, :-delay], ((0, 0), (delay, 0)))
        reports: list[AlignmentDiagnostic] = []

        output, _rate = combine_ensemble_waveforms(
            [reference, late],
            CHUNK_MIN,
            is_array=True,
            align=True,
            on_alignment=lambda diagnostics: reports.extend(diagnostics),
        )

        self.assertEqual(output.shape, reference.shape)
        np.testing.assert_array_equal(output, reference)
        self.assertEqual([item.delay_samples for item in reports], [0, delay])
        self.assertTrue(reports[1].applied)


class CoreEnsembleIdentityTests(unittest.TestCase):
    role = StemRoleId("vocal.vocals")
    stem = CollectedStem(role, "Vocals")

    def make_ensembler(self) -> Ensembler:
        ensembler = object.__new__(Ensembler)
        ensembler.settings = Settings.defaults()
        ensembler.primary_algorithm = AUDIO_AVERAGE
        ensembler.secondary_algorithm = MIN_SPEC
        ensembler.pair_stems = (self.stem,)
        ensembler.is_wav_ensemble = True
        ensembler.ensemble_folder_name = ""
        ensembler.reset_member_identities()
        return ensembler

    def test_core_weights_follow_exact_array_member_identity(self) -> None:
        first = np.full((2, 5), 1.0, dtype=np.float32)
        second = np.full((2, 5), 3.0, dtype=np.float32)
        ensembler = self.make_ensembler()
        ensembler.settings.ensemble.member_weights = {
            str(self.role): {"mdx:first": 1.0, "mdx:second": 3.0}
        }
        ensembler.remember_member("mdx:first", array=first)
        ensembler.remember_member("mdx:second", array=second)

        output = ensembler.combine_stem_waveforms(
            self.stem,
            is_multi_stem=False,
            stem_arrays={self.stem.group_key: [first, second]},
            stem_paths={},
        )

        np.testing.assert_allclose(output, 2.5)

    def test_missing_canonical_id_cannot_silently_use_display_fallback(self) -> None:
        member = np.ones((2, 5), dtype=np.float32)
        ensembler = self.make_ensembler()
        ensembler.settings.ensemble.member_weights = {"*": {"mdx:exact": 2.0}}
        route = StemRoute(StemId("Vocals"), self.role, "Vocals", "Vocals")
        model = SimpleNamespace(
            canonical_id="",
            model_and_process_tag="Display Name",
            selected_stem_routes=(route,),
        )
        state = SimpleNamespace(
            scratch={
                "last_member_stems": {},
                "ensemble_stems": {},
                "ensemble_contributors": {},
                "ensemble_member_routes": {},
                "ensemble_stem_arrays": {},
                "member_paths": {},
            }
        )
        hooks = _EnsembleRunHooks(ensembler, is_multi_stem=False)

        hooks.after_chunk(
            SimpleNamespace(),
            cast(Any, state),
            model,
            {"Vocals": member},
            {},
            chunked=False,
        )

        with self.assertRaisesRegex(ValueError, "canonical model ID|exact member identities"):
            ensembler._blend_options([member], self.stem, arrays=True)


if __name__ == "__main__":
    unittest.main()
