"""Ensemble eligibility resolves by bucket, not by raw stem string."""

import typing
import unittest
import unittest.mock

from core.model_data import ModelRepository
from core.stems import EnsemblePair


class _FakeModel:
    """Stands in for a dry-check ModelConfig without hashing a checkpoint.

    Carries every attribute ``model_list`` reads, so these tests exercise the
    real method instead of re-asserting the resolver from the bucket tests.
    """

    def __init__(self, tag: str, primary: str, stems: typing.Sequence[str], *,
                 is_karaoke: bool = False, is_bv: bool = False,
                 demucs_sources: typing.Sequence[str] = (),
                 demucs_stem_count: int = 0) -> None:
        self.model_and_process_tag = tag
        self.primary_stem = primary
        self.mdx_model_stems = list(stems)
        self.mdx_stem_count = len(stems) or 1
        self.is_karaoke = is_karaoke
        self.is_bv_model = is_bv
        self.demucs_source_list = list(demucs_sources)
        self.demucs_stem_count = demucs_stem_count


def _eligible(models: typing.Sequence[typing.Any], main_stem: typing.Any) -> typing.List[str]:
    """Run the real ``ensemble_model_list`` over fake ``stem_check`` output.

    ``settings`` is only forwarded to ``stem_check``, which is patched out here,
    so ``None`` never reaches anything that reads it.
    """
    with unittest.mock.patch.object(ModelRepository, "stem_check", return_value=models):
        return ModelRepository().ensemble_model_list(
            typing.cast(typing.Any, None), main_stem
        )


class PreviouslyExcludedModelTests(unittest.TestCase):
    """The models measured as wrongly excluded from vocals_instrumental."""

    def test_lowercase_vocals_becomes_eligible(self) -> None:
        # mel_band_roformer_kim_ft2_bleedless_unwa
        models = [_FakeModel("MDX-Net: kim_ft2", "vocals", ["vocals"])]
        self.assertEqual(
            _eligible(models, EnsemblePair.VOCALS_INSTRUMENTAL), ["MDX-Net: kim_ft2"]
        )

    def test_two_stem_other_becomes_eligible(self) -> None:
        # mbr_inst2_unwa, melband_roformer_inst_v1e_plus, Resurrection
        models = [_FakeModel("MDX-Net: inst2_unwa", "other", ["other"])]
        self.assertEqual(
            _eligible(models, EnsemblePair.VOCALS_INSTRUMENTAL.value),
            ["MDX-Net: inst2_unwa"],
        )

    def test_instrument_variant_becomes_eligible(self) -> None:
        # bs_inst_hyperace2_unwa
        models = [_FakeModel("MDX-Net: hyperace2", "instrument", ["instrument"])]
        self.assertEqual(
            _eligible(models, EnsemblePair.VOCALS_INSTRUMENTAL),
            ["MDX-Net: hyperace2"],
        )

    def test_four_stem_lowercase_vocals_becomes_eligible(self) -> None:
        # huge_scnet_4stems_bleedless / _fullness
        models = [_FakeModel("MDX-Net: scnet4", "vocals",
                             ["drums", "bass", "other", "vocals"])]
        self.assertEqual(
            _eligible(models, EnsemblePair.VOCALS_INSTRUMENTAL), ["MDX-Net: scnet4"]
        )

    def test_phantom_centre_stays_excluded(self) -> None:
        # Correct today, but by accident. Now it is by rule.
        models = [_FakeModel("MDX-Net: phantom", "Similarity", ["Similarity"])]
        self.assertEqual(_eligible(models, EnsemblePair.VOCALS_INSTRUMENTAL), [])


class OtherPairTests(unittest.TestCase):
    """'other' must stay a real stem for the Other pair."""

    def test_four_stem_other_matches_the_other_pair(self) -> None:
        models = [_FakeModel("MDX-Net: scnet4", "other",
                             ["drums", "bass", "other", "vocals"])]
        self.assertEqual(_eligible(models, EnsemblePair.OTHER), ["MDX-Net: scnet4"])

    def test_two_stem_other_does_not_match_the_other_pair(self) -> None:
        # This model's 'other' is an instrumental, not a MUSDB residual.
        models = [_FakeModel("MDX-Net: inst2_unwa", "other", ["other"])]
        self.assertEqual(_eligible(models, EnsemblePair.OTHER), [])


class KaraokeSeparationTests(unittest.TestCase):
    def test_karaoke_leaves_vocal_instrumental(self) -> None:
        models = [_FakeModel("MDX-Net: kara", "Vocals", ["Vocals"], is_karaoke=True)]
        self.assertEqual(_eligible(models, EnsemblePair.VOCALS_INSTRUMENTAL), [])

    def test_karaoke_appears_under_its_own_pair(self) -> None:
        models = [_FakeModel("MDX-Net: kara", "Vocals", ["Vocals"], is_karaoke=True)]
        self.assertEqual(_eligible(models, EnsemblePair.KARAOKE), ["MDX-Net: kara"])

    def test_plain_model_does_not_appear_under_the_karaoke_pair(self) -> None:
        models = [_FakeModel("MDX-Net: inst_hq4", "Instrumental", ["Instrumental"])]
        self.assertEqual(_eligible(models, EnsemblePair.KARAOKE), [])

    def test_bv_model_also_leaves_vocal_instrumental(self) -> None:
        models = [_FakeModel("MDX-Net: bv", "Vocals", ["Vocals"], is_bv=True)]
        self.assertEqual(_eligible(models, EnsemblePair.VOCALS_INSTRUMENTAL), [])


class SecondaryOtherWantedBucketsTests(unittest.TestCase):
    """Secondary Other slot must use pair buckets, not stem_count=1 request."""

    def test_wanted_buckets_match_ensemble_other_list(self) -> None:
        from bundled.constants import OTHER_STEM
        from core import Settings
        from core.model_stem_semantics import ensemble_pair_buckets

        settings = Settings()
        repo = ModelRepository()
        wanted = set(ensemble_pair_buckets(EnsemblePair.OTHER))
        via_buckets = set(
            repo.model_list(
                settings, OTHER_STEM, "No Other", wanted_buckets=wanted
            )
        )
        via_ensemble = set(repo.ensemble_model_list(settings, EnsemblePair.OTHER))
        via_raw = set(repo.model_list(settings, OTHER_STEM, "No Other"))
        self.assertEqual(via_buckets, via_ensemble)
        # Pre-fix request path selected Instrumental models instead.
        self.assertNotEqual(via_raw, via_ensemble)


class UnchangedBehaviourTests(unittest.TestCase):
    def test_demucs_source_list_still_matches(self) -> None:
        models = [_FakeModel("Demucs: htdemucs", "Vocals", [],
                             demucs_sources=["drums", "bass", "other", "vocals"],
                             demucs_stem_count=4)]
        self.assertEqual(_eligible(models, EnsemblePair.BASS), ["Demucs: htdemucs"])

    def test_four_stem_ensemble_keeps_only_four_source_models(self) -> None:
        models = [
            _FakeModel("MDX-Net: scnet4", "vocals", ["drums", "bass", "other", "vocals"]),
            _FakeModel("MDX-Net: two_stem", "Vocals", ["Vocals", "Instrumental"]),
        ]
        self.assertEqual(
            _eligible(models, EnsemblePair.FOUR_STEM), ["MDX-Net: scnet4"]
        )

    def test_multi_stem_ensemble_keeps_everything(self) -> None:
        models = [
            _FakeModel("MDX-Net: phantom", "Similarity", ["Similarity"]),
            _FakeModel("MDX-Net: kara", "Vocals", ["Vocals"], is_karaoke=True),
        ]
        self.assertEqual(len(_eligible(models, EnsemblePair.MULTI_STEM)), 2)

    def test_choose_stem_pair_returns_nothing(self) -> None:
        models = [_FakeModel("MDX-Net: any", "Vocals", ["Vocals"])]
        self.assertEqual(_eligible(models, EnsemblePair.CHOOSE), [])


if __name__ == "__main__":
    unittest.main()
