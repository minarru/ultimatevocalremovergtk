"""Ensemble-mode export labels are buckets, so members group correctly."""

import unittest

from core.model_stem_semantics import (
    BUCKET_INST_WITH_BV,
    BUCKET_INSTRUMENTAL,
    BUCKET_LEAD_VOCALS,
    BUCKET_VOCALS,
    canonical_ensemble_stem_tag,
    export_stem_label,
)


class _FakeModel:
    def __init__(self, *, is_karaoke: bool = False, is_bv: bool = False,
                 stem_count: int = 2) -> None:
        self.is_karaoke = is_karaoke
        self.is_bv_model = is_bv
        self.mdx_stem_count = stem_count


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


class BucketRoundTripTests(unittest.TestCase):
    """The combine stage re-reads tags from filenames; they must survive."""

    def test_new_tags_pass_through_canonical_ensemble_stem_tag(self) -> None:
        for bucket in (BUCKET_INST_WITH_BV, BUCKET_LEAD_VOCALS):
            with self.subTest(bucket=bucket):
                self.assertEqual(canonical_ensemble_stem_tag(bucket), bucket)


if __name__ == "__main__":
    unittest.main()
