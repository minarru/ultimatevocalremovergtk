"""Tests for SDR parsing and purpose/sort helpers."""

from __future__ import annotations

import unittest

from core.model_scores import (
    PURPOSE_INSTRUMENTAL,
    PURPOSE_KARAOKE,
    PURPOSE_SPECIALTY,
    PURPOSE_VOCALS,
    filter_labels_by_purpose,
    format_sdr_subtitle,
    parse_sdr_score,
    purpose_for_label,
    sort_labels_by_sdr,
)
from ui.download_center import catalogue_matches


class ParseSdrScoreTests(unittest.TestCase):
    def test_float_sdr_in_filename(self) -> None:
        self.assertAlmostEqual(
            parse_sdr_score("model_bs_roformer_ep_317_sdr_12.9755.ckpt"),
            12.9755,
            places=4,
        )

    def test_int_coded_sdr_in_label(self) -> None:
        self.assertAlmostEqual(parse_sdr_score("MelBand Roformer | SDR 1143 by Viperx"), 11.43)

    def test_viperx_abbreviation(self) -> None:
        self.assertAlmostEqual(parse_sdr_score("BS-Roformer-Viperx-1297"), 12.97)

    def test_missing_score_returns_none(self) -> None:
        self.assertIsNone(parse_sdr_score("UVR-MDX-NET-Inst_HQ_5.onnx"))

    def test_best_of_multiple_texts(self) -> None:
        self.assertAlmostEqual(
            parse_sdr_score("friendly name", "model_sdr_10.2.ckpt", "other_sdr_11.5.ckpt"),
            11.5,
        )


class PurposeAndSortTests(unittest.TestCase):
    def test_purpose_buckets(self) -> None:
        self.assertEqual(purpose_for_label("Roformer Model: Karaoke by Gabox"), PURPOSE_KARAOKE)
        self.assertEqual(
            purpose_for_label("MelBand Roformer | Instrumental by becruily"),
            PURPOSE_INSTRUMENTAL,
        )
        self.assertEqual(
            purpose_for_label("BandSplit Roformer | Resurrection Vocals by Unwa"),
            PURPOSE_VOCALS,
        )
        self.assertEqual(purpose_for_label("SCnet: 4-stem model"), PURPOSE_SPECIALTY)

    def test_filter_labels_by_purpose(self) -> None:
        labels = [
            "Roformer Model: Karaoke by Gabox",
            "MelBand Roformer | Instrumental by becruily",
            "BandSplit Roformer | Resurrection Vocals by Unwa",
        ]
        karaoke = filter_labels_by_purpose(labels, PURPOSE_KARAOKE)
        self.assertEqual(karaoke, ["Roformer Model: Karaoke by Gabox"])

    def test_sort_labels_by_sdr(self) -> None:
        labels = ["alpha", "BS-Roformer-Viperx-1297", "BS-Roformer-Viperx-1143"]
        ordered = sort_labels_by_sdr(labels)
        self.assertEqual(ordered[0], "BS-Roformer-Viperx-1297")
        self.assertEqual(ordered[1], "BS-Roformer-Viperx-1143")
        self.assertEqual(ordered[2], "alpha")

    def test_format_sdr_subtitle(self) -> None:
        self.assertEqual(format_sdr_subtitle(12.97, "180 MB"), "13.0 SDR · 180 MB")
        self.assertEqual(format_sdr_subtitle(None, "180 MB"), "180 MB")
        self.assertEqual(format_sdr_subtitle(11.43), "11.4 SDR")

    def test_catalogue_matches_purpose(self) -> None:
        names = [
            "Roformer Model: Karaoke by Gabox",
            "MelBand Roformer | Instrumental by becruily",
        ]
        matches = catalogue_matches(names, "", purpose=PURPOSE_KARAOKE)
        self.assertEqual(matches, ["Roformer Model: Karaoke by Gabox"])


if __name__ == "__main__":
    unittest.main()
