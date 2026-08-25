"""Ensemble eligibility accepts only complete reviewed role projections."""

from __future__ import annotations

import typing
import unittest
import unittest.mock

from core.model_repository import ModelRepository


class _FakeModel:
    """Dry-check stand-in carrying the exact resolver boundary inputs."""

    def __init__(
        self,
        canonical_id: str,
        native_stems: typing.Sequence[str],
        *,
        backend_primary: str,
        backend_target: str = "",
    ) -> None:
        self.canonical_id = canonical_id
        self.mdx_model_stems = list(native_stems)
        self.demucs_source_list: list[str] = []
        self.primary_stem_native = backend_primary
        self.primary_stem = backend_primary
        self.target_instrument = backend_target


def _eligible(models: typing.Sequence[typing.Any], pair_id: str) -> list[str]:
    """Exercise ``ensemble_model_list`` without probing checkpoint files."""
    with unittest.mock.patch.object(ModelRepository, "stem_check", return_value=models):
        return ModelRepository().ensemble_model_list(typing.cast(typing.Any, None), pair_id)


class ReviewedPairEligibilityTests(unittest.TestCase):
    def test_vocals_instrumental_accepts_reviewed_layouts_not_spelling(self) -> None:
        models = [
            _FakeModel(
                "mdx:MelBandRoformerBigSYHFTV1",
                ["vocals", "other"],
                backend_primary="Vocals",
                backend_target="vocals",
            ),
            _FakeModel(
                "mdx:mbr_inst2_unwa",
                ["other", "vocals"],
                backend_primary="other",
                backend_target="other",
            ),
        ]

        self.assertEqual(
            _eligible(models, "pair.vocals_instrumental"),
            ["mdx:MelBandRoformerBigSYHFTV1", "mdx:mbr_inst2_unwa"],
        )

    def test_ordinary_karaoke_stays_in_the_reviewed_karaoke_pair(self) -> None:
        models = [
            _FakeModel(
                "mdx:UVR_MDXNET_KARA_2",
                ["other", "vocals"],
                backend_primary="Instrumental",
                backend_target="other",
            ),
            _FakeModel(
                "mdx:mbr_karaoke2_gabox",
                ["Vocals", "Instrumental"],
                backend_primary="Vocals",
                backend_target="Vocals",
            ),
        ]

        self.assertEqual(
            _eligible(models, "pair.karaoke"),
            ["mdx:UVR_MDXNET_KARA_2", "mdx:mbr_karaoke2_gabox"],
        )
        self.assertEqual(_eligible(models, "pair.vocals_instrumental"), [])

    def test_vr_bve_is_only_eligible_for_its_reviewed_backing_pair(self) -> None:
        bve = _FakeModel(
            "vr:UVR-BVE-4B_SN-44100-1",
            ["Vocals", "Instrumental"],
            backend_primary="Vocals",
        )

        self.assertEqual(_eligible([bve], "pair.backing_vocals"), [bve.canonical_id])
        self.assertEqual(_eligible([bve], "pair.karaoke"), [])
        self.assertEqual(_eligible([bve], "pair.vocals_instrumental"), [])

    def test_center_side_reconciles_reviewed_native_layouts(self) -> None:
        models = [
            _FakeModel(
                "mdx:bs_mid_side1_gilliaaan",
                ["center", "wide"],
                backend_primary="center",
                backend_target="center",
            ),
            _FakeModel(
                "mdx:mdx23c_mid_side_gilliaaan",
                ["center", "wide"],
                backend_primary="wide",
                backend_target="wide",
            ),
            _FakeModel(
                "mdx:model_mdx23c_ep_271_l1_freq_72.2383",
                ["Similarity", "Difference"],
                backend_primary="Similarity",
                backend_target="Similarity",
            ),
        ]

        self.assertEqual(
            _eligible(models, "pair.center_side"),
            [model.canonical_id for model in models],
        )

    def test_unknown_or_signature_mismatch_never_enters_a_reviewed_pair(self) -> None:
        models = [
            _FakeModel(
                "mdx:unknown-spatial",
                ["center", "wide"],
                backend_primary="center",
            ),
            _FakeModel(
                "mdx:bs_mid_side1_gilliaaan",
                ["center"],
                backend_primary="center",
            ),
        ]

        self.assertEqual(_eligible(models, "pair.center_side"), [])

    def test_four_stem_requires_all_four_exact_reviewed_roles(self) -> None:
        complete = _FakeModel(
            "mdx:model_scnet_ep_54_sdr_9.8051",
            ["Drums", "Bass", "Other", "Vocals"],
            backend_primary="Vocals",
            backend_target="Vocals",
        )
        incomplete = _FakeModel(
            "mdx:model_scnet_ep_54_sdr_9.8051",
            ["Drums", "Bass", "Vocals"],
            backend_primary="Vocals",
        )

        self.assertEqual(
            _eligible([complete, incomplete], "mode.four_stem"), [complete.canonical_id]
        )

    def test_multi_mode_keeps_raw_members_without_making_them_pair_eligible(self) -> None:
        unknown = _FakeModel(
            "mdx:unknown-spatial",
            ["center", "wide"],
            backend_primary="center",
        )

        self.assertEqual(_eligible([unknown], "mode.multi_stem"), [unknown.canonical_id])
        self.assertEqual(_eligible([unknown], "pair.center_side"), [])


if __name__ == "__main__":
    unittest.main()
