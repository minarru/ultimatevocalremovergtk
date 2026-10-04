"""Comparison sets built from finished-input reports."""

from __future__ import annotations

import unittest

from core.job_plan import PlannedOutput
from core.listening import REFERENCE_LABEL, ComparisonSet, Track, build_comparison_set


class BuildComparisonSetTests(unittest.TestCase):
    def test_reference_first_then_outputs_with_plan_labels(self) -> None:
        planned = (
            PlannedOutput("/out/song (Vocals).wav", "Vocals"),
            PlannedOutput("/out/song (Instrumental).wav", "Instrumental"),
        )
        result = build_comparison_set(
            "/in/song.wav",
            "/in/song.wav",
            ["/out/song (Vocals).wav", "/out/song (Instrumental).wav"],
            planned,
        )
        assert result is not None
        self.assertEqual(result.name, "song.wav")
        self.assertEqual(
            result.tracks,
            (
                Track(REFERENCE_LABEL, "/in/song.wav", None, True),
                Track("Vocals", "/out/song (Vocals).wav"),
                Track("Instrumental", "/out/song (Instrumental).wav"),
            ),
        )

    def test_reference_defaults_to_source(self) -> None:
        result = build_comparison_set("/in/a.wav", None, ["/out/a (Restored).wav"])
        assert result is not None
        self.assertEqual(result.tracks[0].path, "/in/a.wav")

    def test_sample_clip_reference_is_kept(self) -> None:
        result = build_comparison_set("/in/a.wav", "/tmp/clip.wav", ["/out/a (Vocals).wav"])
        assert result is not None
        self.assertEqual(result.source, "/in/a.wav")
        self.assertEqual(result.tracks[0].path, "/tmp/clip.wav")

    def test_unplanned_outputs_use_parenthesised_filename_tag(self) -> None:
        result = build_comparison_set("/in/a.wav", None, ["/out/1_a_(Restored).wav"])
        assert result is not None
        self.assertEqual(result.tracks[1].label, "Restored")

    def test_unplanned_outputs_strip_the_input_name(self) -> None:
        result = build_comparison_set("/in/take.wav", None, ["/out/take_stretched.wav"])
        assert result is not None
        self.assertEqual(result.tracks[1].label, "stretched")

    def test_unplanned_label_falls_back_to_file_stem(self) -> None:
        result = build_comparison_set("/in/take.wav", None, ["/out/take.flac"])
        assert result is not None
        self.assertEqual(result.tracks[1].label, "take")

    def test_duplicates_dropped_and_order_stable(self) -> None:
        result = build_comparison_set(
            "/in/a.wav", None, ["/out/a (B).wav", "/out/a (A).wav", "/out/a (B).wav"]
        )
        assert result is not None
        self.assertEqual([t.label for t in result.tracks], [REFERENCE_LABEL, "B", "A"])

    def test_no_outputs_returns_none(self) -> None:
        self.assertIsNone(build_comparison_set("/in/a.wav", None, []))

    def test_role_text_is_carried(self) -> None:
        from core.stem_roles import StemRoleId

        role = StemRoleId("uvr.vocals")
        planned = (PlannedOutput("/out/a (Vocals).wav", "Vocals", role=role),)
        result = build_comparison_set("/in/a.wav", None, ["/out/a (Vocals).wav"], planned)
        assert result is not None
        self.assertEqual(result.tracks[1].role, "uvr.vocals")


class ComparisonSetTests(unittest.TestCase):
    def test_is_frozen(self) -> None:
        cset = ComparisonSet("/in/a.wav", (Track(REFERENCE_LABEL, "/in/a.wav", None, True),))
        with self.assertRaises(AttributeError):
            cset.source = "/x"  # type: ignore[misc]


if __name__ == "__main__":
    unittest.main()
