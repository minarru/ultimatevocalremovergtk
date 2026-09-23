from __future__ import annotations

import unittest

import numpy as np

from ml.ensemble_alignment import AlignmentDiagnostic, align_ensemble_members


class EnsembleAlignmentTests(unittest.TestCase):
    sample_rate = 8_000

    def setUp(self) -> None:
        rng = np.random.default_rng(42)
        self.reference = rng.normal(0.0, 0.2, (2, self.sample_rate * 3)).astype(np.float32)

    def test_diagnostic_only_reports_delay_without_changing_arrays(self) -> None:
        delay = 73
        late = np.pad(self.reference, ((0, 0), (delay, 0)))

        aligned, diagnostics = align_ensemble_members([self.reference, late], self.sample_rate)

        self.assertIs(aligned[0], self.reference)
        self.assertIs(aligned[1], late)
        self.assertEqual(diagnostics[1].delay_samples, delay)
        self.assertFalse(diagnostics[1].applied)
        self.assertEqual(diagnostics[1].reason, "correction disabled")
        self.assertEqual(diagnostics[1].valid_start_samples, 0)
        self.assertEqual(diagnostics[1].valid_end_samples, late.shape[1])

    def test_corrects_late_member_without_padding_tail(self) -> None:
        delay = 91
        late = np.pad(self.reference, ((0, 0), (delay, 0)))

        aligned, diagnostics = align_ensemble_members(
            [self.reference, late], self.sample_rate, correct=True
        )

        np.testing.assert_array_equal(aligned[0], self.reference)
        np.testing.assert_array_equal(aligned[1], self.reference)
        self.assertEqual(
            diagnostics[1],
            AlignmentDiagnostic(
                member_index=1,
                delay_samples=delay,
                confidence=diagnostics[1].confidence,
                applied=True,
                reason="aligned",
                valid_start_samples=0,
                valid_end_samples=self.reference.shape[1],
            ),
        )
        self.assertGreaterEqual(diagnostics[1].confidence, 0.9)

    def test_corrects_early_member_with_invalid_prefix_and_preserves_tail(self) -> None:
        advance = 67
        early = self.reference[:, advance:]

        aligned, diagnostics = align_ensemble_members(
            [self.reference, early], self.sample_rate, correct=True
        )

        self.assertEqual(diagnostics[1].delay_samples, -advance)
        self.assertTrue(diagnostics[1].applied)
        self.assertEqual(diagnostics[1].valid_start_samples, advance)
        self.assertEqual(diagnostics[1].valid_end_samples, self.reference.shape[1])
        self.assertEqual(aligned[1].shape, self.reference.shape)
        np.testing.assert_array_equal(aligned[1][:, :advance], 0.0)
        np.testing.assert_array_equal(aligned[1][:, advance:], self.reference[:, advance:])

    def test_stereo_channels_receive_the_same_shift(self) -> None:
        delay = 49
        stereo = self.reference.copy()
        stereo[1] *= 0.37
        late = np.pad(stereo, ((0, 0), (delay, 0)))

        aligned, diagnostics = align_ensemble_members(
            [stereo, late], self.sample_rate, correct=True
        )

        self.assertTrue(diagnostics[1].applied)
        np.testing.assert_array_equal(aligned[1], stereo)

    def test_unequal_length_keeps_reference_and_member_valid_tail(self) -> None:
        delay = 61
        shortened = self.reference[:, :-257]
        late_shortened = np.pad(shortened, ((0, 0), (delay, 0)))

        aligned, diagnostics = align_ensemble_members(
            [self.reference, late_shortened], self.sample_rate, correct=True
        )

        self.assertIs(aligned[0], self.reference)
        np.testing.assert_array_equal(aligned[1], shortened)
        self.assertEqual(diagnostics[1].valid_start_samples, 0)
        self.assertEqual(diagnostics[1].valid_end_samples, shortened.shape[1])

    def test_silence_is_not_corrected(self) -> None:
        silence = np.zeros_like(self.reference)

        aligned, diagnostics = align_ensemble_members(
            [self.reference, silence], self.sample_rate, correct=True
        )

        self.assertIs(aligned[1], silence)
        self.assertFalse(diagnostics[1].applied)
        self.assertIn("energy", diagnostics[1].reason)
        self.assertEqual(diagnostics[1].confidence, 0.0)

    def test_periodic_signal_is_rejected_as_ambiguous(self) -> None:
        samples = np.arange(self.sample_rate * 3)
        sine = np.sin(2 * np.pi * 200 * samples / self.sample_rate).astype(np.float32)
        reference = np.stack((sine, sine * 0.5))
        delay = 80
        late = np.pad(reference, ((0, 0), (delay, 0)))

        aligned, diagnostics = align_ensemble_members(
            [reference, late], self.sample_rate, correct=True
        )

        self.assertIs(aligned[1], late)
        self.assertFalse(diagnostics[1].applied)
        self.assertEqual(diagnostics[1].reason, "ambiguous correlation")

    def test_polarity_inversion_is_not_corrected(self) -> None:
        inverted = -self.reference

        aligned, diagnostics = align_ensemble_members(
            [self.reference, inverted], self.sample_rate, correct=True
        )

        self.assertIs(aligned[1], inverted)
        self.assertFalse(diagnostics[1].applied)
        self.assertNotEqual(diagnostics[1].reason, "aligned")

    def test_different_outputs_are_not_treated_as_delay(self) -> None:
        rng = np.random.default_rng(99)
        unrelated = rng.normal(0.0, 0.2, self.reference.shape).astype(np.float32)

        aligned, diagnostics = align_ensemble_members(
            [self.reference, unrelated], self.sample_rate, correct=True
        )

        self.assertIs(aligned[1], unrelated)
        self.assertFalse(diagnostics[1].applied)


if __name__ == "__main__":
    unittest.main()
