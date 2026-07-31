"""Tests for SDR parsing and purpose/sort helpers."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
import unittest.mock

from core import model_scores

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
            float(parse_sdr_score("model_bs_roformer_ep_317_sdr_12.9755.ckpt") or 0.0),
            12.9755,
            places=4,
        )

    def test_int_coded_sdr_in_label(self) -> None:
        self.assertAlmostEqual(
            float(parse_sdr_score("MelBand Roformer | SDR 1143 by Viperx") or 0.0),
            11.43,
        )

    def test_viperx_abbreviation(self) -> None:
        self.assertAlmostEqual(
            float(parse_sdr_score("BS-Roformer-Viperx-1297") or 0.0), 12.97
        )

    def test_missing_score_returns_none(self) -> None:
        self.assertIsNone(parse_sdr_score("UVR-MDX-NET-Inst_HQ_5.onnx"))

    def test_best_of_multiple_texts(self) -> None:
        self.assertAlmostEqual(
            float(
                parse_sdr_score(
                    "friendly name", "model_sdr_10.2.ckpt", "other_sdr_11.5.ckpt"
                )
                or 0.0
            ),
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


_FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "model_scores_sample.json")


def _sample() -> dict:
    with open(_FIXTURE, "r", encoding="utf-8") as handle:
        return json.load(handle)


class _IsolatedScoreCache(unittest.TestCase):
    """Redirect the disk cache into a temp dir.

    ``load_model_scores`` writes whatever it fetched to the cache, so without
    this a test that patches the fetch poisons the user's real
    ``~/.cache/uvr/model_scores.json`` with the three-entry fixture — and every
    later run reads the fixture instead of the 115-entry snapshot.
    """

    def setUp(self) -> None:
        model_scores.clear_model_scores_cache()
        self.addCleanup(model_scores.clear_model_scores_cache)
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        cache_path = os.path.join(self._tmp.name, "model_scores.json")
        patcher = unittest.mock.patch.object(
            model_scores, "_cache_path", return_value=cache_path
        )
        patcher.start()
        self.addCleanup(patcher.stop)


class ModelScoreAggregationTests(_IsolatedScoreCache):
    def _loaded(self) -> dict:
        with unittest.mock.patch.object(
            model_scores, "_fetch_model_scores", return_value=_sample()
        ):
            return model_scores.load_model_scores(force=True)

    def test_mean_sdr_per_stem(self) -> None:
        scores = self._loaded()
        entry = scores["model_bs_roformer_ep_317_sdr_12.9755.ckpt"]
        self.assertAlmostEqual(entry["vocals"], 11.5)
        self.assertAlmostEqual(entry["instrumental"], 16.25)

    def test_speed_metric_is_not_a_stem(self) -> None:
        scores = self._loaded()
        entry = scores["model_bs_roformer_ep_317_sdr_12.9755.ckpt"]
        self.assertNotIn("seconds_per_minute_m3", entry)

    def test_zero_track_model_is_unscored_not_an_error(self) -> None:
        scores = self._loaded()
        self.assertEqual(scores.get("uvr-denoise-lite.pth", {}), {})

    def test_lookup_matches_demucs_yaml_key(self) -> None:
        scores = self._loaded()
        found = model_scores.sdr_for_files(
            ["955717e8-8726e21a.th", "htdemucs_ft.yaml"], scores=scores
        )
        self.assertAlmostEqual(found["drums"], 10.0)

    def test_lookup_is_case_insensitive(self) -> None:
        scores = self._loaded()
        found = model_scores.sdr_for_files(["HTDEMUCS_FT.YAML"], scores=scores)
        self.assertAlmostEqual(found["bass"], 12.0)

    def test_lookup_miss_returns_empty(self) -> None:
        scores = self._loaded()
        self.assertEqual(model_scores.sdr_for_files(["nope.ckpt"], scores=scores), {})


class PrimarySdrTests(unittest.TestCase):
    def test_target_stem_wins(self) -> None:
        result = model_scores.primary_sdr({"vocals": 11.5, "instrumental": 16.25}, "vocals")
        self.assertEqual(result, ("vocals", 11.5))

    def test_falls_back_to_highest_when_no_target(self) -> None:
        result = model_scores.primary_sdr({"vocals": 11.5, "instrumental": 16.25}, None)
        self.assertEqual(result, ("instrumental", 16.25))

    def test_empty_returns_none(self) -> None:
        self.assertIsNone(model_scores.primary_sdr({}, "vocals"))


class SdrStemResolutionTests(unittest.TestCase):
    """Score keys are lowercase; model targets are whatever the yaml said."""

    def test_two_stem_other_target_reads_instrumental_score(self) -> None:
        # mbr_inst2_unwa declares target 'other', meaning instrumental.
        scores = {"vocals": 9.0, "instrumental": 16.0}
        result = model_scores.primary_sdr(scores, "other", stem_count=2)
        self.assertEqual(result, ("instrumental", 16.0))

    def test_four_stem_other_target_reads_other_score(self) -> None:
        scores = {"vocals": 9.0, "drums": 10.0, "bass": 12.0, "other": 8.0}
        result = model_scores.primary_sdr(scores, "other", stem_count=4)
        self.assertEqual(result, ("other", 8.0))

    def test_case_mismatch_still_resolves(self) -> None:
        scores = {"vocals": 11.5, "instrumental": 16.25}
        self.assertEqual(
            model_scores.primary_sdr(scores, "Vocals", stem_count=2), ("vocals", 11.5)
        )

    def test_unknown_target_falls_back_to_highest(self) -> None:
        scores = {"vocals": 11.5, "instrumental": 16.25}
        self.assertEqual(
            model_scores.primary_sdr(scores, "Similarity", stem_count=1),
            ("instrumental", 16.25),
        )


class SdrSubtitleTests(unittest.TestCase):
    def test_stem_is_named(self) -> None:
        self.assertEqual(
            model_scores.format_sdr_subtitle(11.43, "1.2 GB", stem="vocals"),
            "vocals 11.4 SDR · 1.2 GB",
        )

    def test_falls_back_to_extra_when_unscored(self) -> None:
        self.assertEqual(
            model_scores.format_sdr_subtitle(None, "890 MB", extra="vocals, other"),
            "vocals, other · 890 MB",
        )

    def test_size_only(self) -> None:
        self.assertEqual(model_scores.format_sdr_subtitle(None, "890 MB"), "890 MB")

    def test_bare_sdr_without_stem_still_renders(self) -> None:
        self.assertEqual(model_scores.format_sdr_subtitle(11.43, ""), "11.4 SDR")


class ModelScoresDisabledTests(_IsolatedScoreCache):
    def test_kill_switch_returns_empty(self) -> None:
        with unittest.mock.patch.dict(os.environ, {"UVR_DISABLE_MODEL_SCORES": "1"}):
            self.assertEqual(model_scores.load_model_scores(force=True), {})


if __name__ == "__main__":
    unittest.main()
