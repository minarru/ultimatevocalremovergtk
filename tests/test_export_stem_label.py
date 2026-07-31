"""Ensemble-mode export labels are buckets, so members group correctly."""

import typing
import unittest

from core.model_stem_semantics import (
    BUCKET_INST_WITH_BV,
    BUCKET_OTHER,
    BUCKET_INSTRUMENTAL,
    BUCKET_LEAD_VOCALS,
    BUCKET_VOCALS,
    canonical_ensemble_stem_tag,
    export_stem_label,
)


class _FakeModel:
    def __init__(self, *, is_karaoke: bool = False, is_bv: bool = False,
                 stem_count: int = 2, demucs_stem_count: int = 0,
                 demucs_source_list: typing.Sequence[str] = ()) -> None:
        self.is_karaoke = is_karaoke
        self.is_bv_model = is_bv
        self.mdx_stem_count = stem_count
        self.demucs_stem_count = demucs_stem_count
        self.demucs_source_list = list(demucs_source_list)


class EnsembleExportLabelTests(unittest.TestCase):
    def test_plain_model_folds_case(self) -> None:
        model = _FakeModel()
        self.assertEqual(export_stem_label(model, "vocals", for_ensemble=True), BUCKET_VOCALS)
        self.assertEqual(
            export_stem_label(model, "other", for_ensemble=True), BUCKET_INSTRUMENTAL
        )

    def test_karaoke_model_gets_its_own_tags(self) -> None:
        model = _FakeModel(is_karaoke=True)
        self.assertEqual(
            export_stem_label(model, "Vocals", for_ensemble=True), BUCKET_LEAD_VOCALS
        )
        self.assertEqual(
            export_stem_label(model, "Instrumental", for_ensemble=True), BUCKET_INST_WITH_BV
        )

    def test_karaoke_does_not_land_in_clean_instrumental(self) -> None:
        karaoke = export_stem_label(_FakeModel(is_karaoke=True), "Instrumental", for_ensemble=True)
        clean = export_stem_label(_FakeModel(), "Instrumental", for_ensemble=True)
        self.assertNotEqual(karaoke, clean)


class DemucsStemCountTests(unittest.TestCase):
    """A Demucs model's stem count lives on demucs_stem_count, not mdx_stem_count.

    Regression: reading only mdx_stem_count saw 1 for a 4-stem Demucs model, so
    its MUSDB 'other' residual was labelled Instrumental.
    """

    def test_four_stem_demucs_other_is_not_instrumental(self) -> None:
        model = _FakeModel(stem_count=1, demucs_stem_count=4,
                       demucs_source_list=["drums", "bass", "other", "vocals"])
        self.assertEqual(export_stem_label(model, "other", for_ensemble=True), BUCKET_OTHER)

    def test_four_stem_demucs_other_stems_unaffected(self) -> None:
        model = _FakeModel(stem_count=1, demucs_stem_count=4,
                       demucs_source_list=["drums", "bass", "other", "vocals"])
        self.assertEqual(export_stem_label(model, "vocals", for_ensemble=True), BUCKET_VOCALS)
        self.assertEqual(export_stem_label(model, "drums", for_ensemble=True), "Drums")

    def test_two_stem_demucs_other_is_still_instrumental(self) -> None:
        model = _FakeModel(stem_count=1, demucs_stem_count=2,
                       demucs_source_list=["instrumental", "vocals"])
        self.assertEqual(
            export_stem_label(model, "other", for_ensemble=True), BUCKET_INSTRUMENTAL
        )

    def test_mdx_four_stem_still_resolves(self) -> None:
        # SCNet 4-stem: the count is on mdx_stem_count and already worked.
        model = _FakeModel(stem_count=4)
        self.assertEqual(export_stem_label(model, "other", for_ensemble=True), BUCKET_OTHER)

    def test_unknown_stem_count_keeps_other_literal(self) -> None:
        # Engine objects used to omit mdx_stem_count; guessing 2 would label
        # a 4-stem residual as Instrumental. Unknown must not reinterpret.
        model = object()
        self.assertEqual(export_stem_label(model, "other", for_ensemble=True), BUCKET_OTHER)


class BucketRoundTripTests(unittest.TestCase):
    """The combine stage re-reads tags from filenames; they must survive."""

    def test_new_tags_pass_through_canonical_ensemble_stem_tag(self) -> None:
        for bucket in (BUCKET_INST_WITH_BV, BUCKET_LEAD_VOCALS):
            with self.subTest(bucket=bucket):
                self.assertEqual(canonical_ensemble_stem_tag(bucket), bucket)


if __name__ == "__main__":
    unittest.main()
