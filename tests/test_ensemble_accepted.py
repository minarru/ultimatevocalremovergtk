"""Keep the accepted numerical algorithms consistent with the evaluated snapshots."""

import unittest
from pathlib import Path

import numpy as np

from bundled.constants import HYBRID_SPEC, MAX_SPEC, MIN_SPEC
from core.ensemble_blend import blend_kwargs
from core.settings import Settings
from ml.ensemble_spectral import combine_spectra


class AcceptedEnsembleTests(unittest.TestCase):
    def test_defaults_match_independent_ab_reference(self) -> None:
        with np.load(Path(__file__).parent / 'fixtures/ensemble_accepted.npz') as fixture:
            members = list(fixture['inputs'])
            for algorithm in fixture.files:
                if algorithm != 'inputs':
                    with self.subTest(algorithm=algorithm):
                        np.testing.assert_allclose(
                            combine_spectra(algorithm, members),
                            fixture[algorithm],
                            atol=1e-12,
                        )

    def test_min_setting_cannot_change_max_or_hybrid(self) -> None:
        with np.load(Path(__file__).parent / 'fixtures/ensemble_accepted.npz') as fixture:
            for smoothing in (0, 0.25, 1, 4):
                for algorithm in (MAX_SPEC, HYBRID_SPEC):
                    with self.subTest(algorithm=algorithm, smoothing=smoothing):
                        np.testing.assert_allclose(
                            combine_spectra(
                                algorithm, list(fixture['inputs']), smoothing=smoothing
                            ),
                            fixture[algorithm],
                            atol=1e-12,
                        )

    def test_default_settings_preserve_hard_min_and_optional_smoothing(self) -> None:
        settings = Settings.defaults()
        members = [np.full((2, 1, 3), v, dtype=complex) for v in (1, 3)]
        default = blend_kwargs(settings, ['mdx:a', 'mdx:b'])
        hard = combine_spectra(MIN_SPEC, members, smoothing=default['smoothing'])
        np.testing.assert_array_equal(hard, members[0])
        settings.ensemble.smoothing = 1
        optional = blend_kwargs(settings, ['mdx:a', 'mdx:b'])
        soft = combine_spectra(MIN_SPEC, members, smoothing=optional['smoothing'])
        self.assertTrue(np.all((np.real(soft) > 1) & (np.real(soft) < 3)))
