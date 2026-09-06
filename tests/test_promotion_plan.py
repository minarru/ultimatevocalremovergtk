"""Literal staged-unit association and suffix planning contracts."""

from __future__ import annotations

import unittest


class PromotionPlanTests(unittest.TestCase):
    def test_suffix_remaps_originals_and_leaves_sidecars_for_file_fallback(self) -> None:
        from cli.promotion_plan import PromotionPlan

        plan = PromotionPlan.associate(
            (
                ("/stage/song (Vocals).wav", "/out/song (Vocals).wav"),
                ("/stage/song Model (Vocals).wav", "/out/song Model (Vocals).wav"),
                ("/stage/sidecar.txt", "/out/sidecar.txt"),
            ),
            expected_track_base=None,
            destinations=("/out/song (Vocals).wav",),
            ensemble_member_prefix="song",
        )
        self.assertEqual(
            plan.remap(2),
            (
                ("/stage/song (Vocals).wav", "/out/song_2 (Vocals).wav"),
                ("/stage/song Model (Vocals).wav", "/out/song_2 Model (Vocals).wav"),
                ("/stage/sidecar.txt", "/out/sidecar.txt"),
            ),
        )
        self.assertEqual(plan.remap(3)[0][1], "/out/song_3 (Vocals).wav")
        self.assertEqual(plan.entries[0][1], "/out/song (Vocals).wav")

    def test_association_rejects_unrelated_staged_output(self) -> None:
        from cli.promotion_plan import PromotionPlan

        with self.assertRaisesRegex(
            OSError, "unexpected staged separation output 'other.wav' for track 'song'"
        ):
            PromotionPlan.associate(
                (("/stage/other.wav", "/out/other.wav"),),
                expected_track_base="song",
                destinations=None,
                ensemble_member_prefix=None,
            )

    def test_suffix_candidate_identifies_only_progressable_names(self) -> None:
        from cli.promotion_plan import PromotionPlan, suffix_candidate

        plan = PromotionPlan.associate(
            (("/stage/song.wav", "/out/song.wav"), ("/stage/sidecar.txt", "/out/sidecar.txt")),
            expected_track_base=None,
            destinations=("/out/song.wav",),
            ensemble_member_prefix=None,
        )
        candidate = suffix_candidate(plan, 4)
        self.assertEqual(
            candidate.entries,
            (("/stage/song.wav", "/out/song_4.wav"), ("/stage/sidecar.txt", "/out/sidecar.txt")),
        )
        self.assertEqual(candidate.rewritten_targets, ("/out/song_4.wav",))
        self.assertEqual(candidate.progressable_sources, frozenset({"/stage/song.wav"}))
