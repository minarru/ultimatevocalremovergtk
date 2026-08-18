"""Vocal-splitter stem pairing across community MDX-C yaml shapes."""

from __future__ import annotations

import unittest
from typing import Any
from unittest.mock import MagicMock, patch

import numpy as np

from bundled.constants import (
    BV_VOCAL_STEM,
    BV_VOCAL_STEM_LABEL,
    INST_STEM,
    LEAD_VOCAL_STEM,
    LEAD_VOCAL_STEM_LABEL,
    VOCAL_STEM,
)
from core.model_stem_semantics import (
    pick_backing_key,
    pick_instrumental_key,
    pick_vocal_key,
    vocal_inst_from_sources,
    vocal_split_source_roles,
)
from core.stems import StemBucket, bucket_for_model_stem
from engines.base import SeperateAttributes
from engines.mdx_c import SeperateMDXC, mdx_vocal_split_chain_sources
from engines.orchestration import process_chain_model


def _arr(fill: float) -> np.ndarray:
    return np.full((2, 4), fill, dtype=np.float32)


def _split_bucket(stem: str | None, *, is_bv: bool = False) -> StemBucket:
    """The splitter-role concept for a native stem (the old remap's job)."""
    return bucket_for_model_stem(
        stem or "", stem_count=2, is_bv=is_bv, is_vocal_split=True
    )


class VocalSplitRoleBucketTests(unittest.TestCase):
    """The 2x2 splitter table, now owned by ``bucket_for_model_stem``.

    These assertions moved off the deleted ``vocal_split_primary_stem`` /
    ``vocal_split_write_logic_stem`` helpers, which encoded the same table a
    second time. ``lead_only``/``backing_only`` are input aliases only; a run
    resolves to ``LEAD_VOCALS``/``BACKING_VOCALS`` instead.
    """

    def test_title_case_vocals_is_lead(self) -> None:
        self.assertEqual(_split_bucket("Vocals"), StemBucket.LEAD_VOCALS)

    def test_lowercase_vocals_is_lead(self) -> None:
        self.assertEqual(_split_bucket("vocals"), StemBucket.LEAD_VOCALS)

    def test_bv_model_inverts(self) -> None:
        self.assertEqual(_split_bucket("Vocals", is_bv=True), StemBucket.BACKING_VOCALS)
        self.assertEqual(_split_bucket("other", is_bv=True), StemBucket.LEAD_VOCALS)

    def test_other_native_is_backing(self) -> None:
        self.assertEqual(_split_bucket("other"), StemBucket.BACKING_VOCALS)
        self.assertEqual(_split_bucket("Instrumental"), StemBucket.BACKING_VOCALS)

    def test_lead_only_alias_still_reads_as_lead(self) -> None:
        self.assertEqual(_split_bucket(LEAD_VOCAL_STEM), StemBucket.LEAD_VOCALS)
        self.assertEqual(_split_bucket(BV_VOCAL_STEM), StemBucket.BACKING_VOCALS)

    def test_empty_and_unknown_are_unknown_not_backing(self) -> None:
        # The old helper defaulted a missing/unrecognized stem to backing
        # vocals; UNKNOWN makes write_audio skip it instead of mislabelling it.
        for stem in ("", None, "center"):
            with self.subTest(stem=stem):
                self.assertEqual(_split_bucket(stem), StemBucket.UNKNOWN)


class SourcePickerTests(unittest.TestCase):
    def test_title_case_voc_inst(self) -> None:
        sources = {"Vocals": 1, "Instrumental": 2}
        self.assertEqual(pick_vocal_key(sources), "Vocals")
        self.assertEqual(pick_backing_key(sources), "Instrumental")
        self.assertEqual(pick_instrumental_key(sources), "Instrumental")

    def test_lowercase_vocals_other(self) -> None:
        sources = {"vocals": 1, "other": 2}
        self.assertEqual(pick_vocal_key(sources), "vocals")
        self.assertEqual(pick_backing_key(sources), "other")
        self.assertEqual(pick_instrumental_key(sources), "other")

    def test_backing_vocal_preferred_over_instrumental(self) -> None:
        sources = {"vocals": 1, "backing_vocal": 2, "instrumental": 3}
        self.assertEqual(pick_vocal_key(sources), "vocals")
        self.assertEqual(pick_backing_key(sources), "backing_vocal")
        self.assertEqual(pick_instrumental_key(sources), "instrumental")

    def test_four_stem_other_is_not_instrumental_or_backing(self) -> None:
        sources = {"drums": 1, "bass": 2, "other": 3, "vocals": 4}
        self.assertEqual(pick_vocal_key(sources), "vocals")
        self.assertIsNone(pick_backing_key(sources))
        self.assertIsNone(pick_instrumental_key(sources))

    def test_missing_vocals(self) -> None:
        sources = {"center": 1, "wide": 2}
        self.assertIsNone(pick_vocal_key(sources))
        self.assertIsNone(pick_backing_key(sources))

    def test_karaoke_roles_vs_bv_roles(self) -> None:
        sources = {"Vocals": 1, "Instrumental": 2}
        self.assertEqual(
            vocal_split_source_roles(sources, is_bv_model=False),
            ("Vocals", "Instrumental"),
        )
        self.assertEqual(
            vocal_split_source_roles(sources, is_bv_model=True),
            ("Instrumental", "Vocals"),
        )


class ChainSourceMergeTests(unittest.TestCase):
    def test_lowercase_demix_fills_empty_maps(self) -> None:
        voc = _arr(1.0)
        inst = _arr(2.0)
        merged = mdx_vocal_split_chain_sources(
            {},
            {"vocals": voc, "other": inst},
        )
        vocal, instrumental = vocal_inst_from_sources(merged)
        self.assertIsInstance(vocal, np.ndarray)
        self.assertIsInstance(instrumental, np.ndarray)
        np.testing.assert_array_equal(vocal, voc.T)
        np.testing.assert_array_equal(instrumental, inst.T)

    def test_four_stem_has_vocals_but_no_instrumental(self) -> None:
        voc = _arr(1.0)
        merged = mdx_vocal_split_chain_sources(
            {},
            {
                "drums": _arr(0.0),
                "bass": _arr(0.0),
                "other": _arr(3.0),
                "vocals": voc,
            },
        )
        vocal, instrumental = vocal_inst_from_sources(merged)
        self.assertIsInstance(vocal, np.ndarray)
        self.assertIsNone(instrumental)

    def test_string_placeholder_is_not_an_array(self) -> None:
        vocal, _inst = vocal_inst_from_sources({VOCAL_STEM: "Vocals"})
        self.assertEqual(vocal, "Vocals")
        self.assertFalse(isinstance(vocal, np.ndarray))


class WriteAudioGuardTests(unittest.TestCase):
    def test_empty_stem_name_returns_without_saving(self) -> None:
        sep = SeperateAttributes.__new__(SeperateAttributes)
        sep.is_vocal_split_model = True
        sep.is_bv_model = False
        sep.write_audio("/tmp/x.wav", _arr(1.0).T, 44100, stem_name="")

    def _secondary_writer(self) -> SeperateAttributes:
        """Skip disk writes; still run ``master_vocal_path`` recording."""
        sep = SeperateAttributes.__new__(SeperateAttributes)
        sep.is_vocal_split_model = False
        sep.is_bv_model = False
        sep.is_bv_model_rebalenced = False
        sep.is_inst_only_voc_splitter = False
        sep.is_save_vocal_only = False
        sep.is_sec_bv_rebalance = False
        sep.is_ensemble_mode = False
        sep.is_secondary_model = True
        sep.master_vocal_path = None
        return sep

    def test_yaml_lowercase_vocals_records_master_vocal_path(self) -> None:
        """Community MDX-C yamls (InstVoc Duality, etc.) write ``vocals``.

        Exact ``== VOCAL_STEM`` left ``master_vocal_path`` unset, so the
        vocal-split chain crashed in ``os.path.basename(None)``.
        """
        sep = self._secondary_writer()
        path = "/tmp/song_(Vocals).wav"
        sep.write_audio(path, _arr(1.0).T, 44100, stem_name="vocals")
        self.assertEqual(sep.master_vocal_path, path)

    def test_canonical_vocals_still_records_master_vocal_path(self) -> None:
        sep = self._secondary_writer()
        path = "/tmp/song_(Vocals).wav"
        sep.write_audio(path, _arr(1.0).T, 44100, stem_name=VOCAL_STEM)
        self.assertEqual(sep.master_vocal_path, path)

    def test_instrumental_does_not_record_master_vocal_path(self) -> None:
        sep = self._secondary_writer()
        sep.write_audio("/tmp/song_(Instrumental).wav", _arr(1.0).T, 44100, stem_name=INST_STEM)
        self.assertIsNone(sep.master_vocal_path)

    def _vocal_split_writer(self) -> SeperateAttributes:
        sep = SeperateAttributes.__new__(SeperateAttributes)
        sep.is_vocal_split_model = True
        sep.is_bv_model = False
        sep.is_karaoke = False
        sep.is_bv_model_rebalenced = False
        sep.is_inst_only_voc_splitter = False
        sep.is_save_vocal_only = False
        sep.is_sec_bv_rebalance = False
        sep.is_ensemble_mode = True
        sep.capture_stems_only = True
        sep.is_secondary_model = False
        sep.is_save_inst_vocal_splitter = False
        sep.is_deverb_vocals = False
        sep.deverb_vocal_opt = "ALL"
        sep.is_normalization = False
        sep.is_prevent_export_clipping = False
        sep.amplification_threshold = 0
        sep.save_format = "WAV"
        sep.wav_type_set = "PCM_16"
        sep.audio_file_base_voc_split = lambda name: f"/tmp/{name}.wav"
        sep.write_to_console = lambda *a, **k: None
        sep._report_save_progress = lambda: None
        sep.master_vocal_path = None
        return sep

    def test_vocal_split_yaml_vocals_writes_lead_not_backing(self) -> None:
        sep = self._vocal_split_writer()
        sep.write_audio("/tmp/x.wav", _arr(1.0).T, 44100, stem_name="vocals")
        paths = getattr(sep, "_ensemble_stem_paths", {})
        self.assertIn("/tmp/Lead Vocals.wav", paths.values())
        self.assertNotIn("/tmp/Backing Vocals.wav", paths.values())

    def test_vocal_split_yaml_vocals_is_deverb_eligible(self) -> None:
        from core.stems import StemBucket, stem_concept

        sep = self._vocal_split_writer()
        sep.mdx_stem_count = 2
        self.assertEqual(stem_concept(sep, "vocals"), StemBucket.LEAD_VOCALS)

    def test_deverb_all_does_not_process_splitter_instrumental(self) -> None:
        sep = self._vocal_split_writer()
        sep.capture_stems_only = False
        sep.is_deverb_vocals = True
        sep.is_save_inst_vocal_splitter = True
        sep.master_inst_source = _arr(2.0).T
        sep.device = "cpu"
        sep.DEVERBER_MODEL = "/tmp/deverb.pth"
        sep.settings = MagicMock()
        sep.mp3_bit_set = "320k"
        sep.flac_bit_set = "PCM_16"
        sep.deverb_progress_callback = MagicMock(return_value=None)
        sep.check_run_control = MagicMock()
        with (
            patch("engines.base.vr_denoiser", return_value=(_arr(0.5).T, _arr(0.5).T)) as deverb,
            patch("engines.base.sf.write"),
        ):
            sep.write_audio("/tmp/x.wav", _arr(1.0).T, 44100, stem_name="vocals")
        deverb.assert_called_once()


class VocalSplitChainHandoffTests(unittest.TestCase):
    def _sep(self, **kwargs: Any) -> SeperateAttributes:
        sep = SeperateAttributes.__new__(SeperateAttributes)
        sep.vocal_split_model = MagicMock()
        sep.process_data = MagicMock()
        sep.is_ensemble_mode = False
        sep.is_karaoke = False
        sep.is_bv_model = False
        sep.master_vocal_path = "/tmp/song_(Vocals).wav"
        for key, value in kwargs.items():
            setattr(sep, key, value)
        return sep

    def test_lowercase_maps_invoke_chain_with_ndarrays(self) -> None:
        sep = self._sep()
        voc = _arr(1.0).T
        inst = _arr(2.0).T
        with patch("engines.base.process_chain_model") as chain:
            sep._process_vocal_split_chain({"vocals": voc, "other": inst})
        chain.assert_called_once()
        kwargs = chain.call_args.kwargs
        self.assertIsInstance(kwargs["master_vocal_source"], np.ndarray)
        self.assertIsInstance(kwargs["master_inst_source"], np.ndarray)

    def test_string_payload_does_not_invoke_chain(self) -> None:
        sep = self._sep()
        with patch("engines.base.process_chain_model") as chain:
            sep._process_vocal_split_chain({VOCAL_STEM: "Vocals"})
        chain.assert_not_called()

    def test_karaoke_primary_skips_chain(self) -> None:
        sep = self._sep(is_karaoke=True)
        with patch("engines.base.process_chain_model") as chain:
            sep._process_vocal_split_chain({VOCAL_STEM: _arr(1.0).T})
        chain.assert_not_called()

    def test_missing_vocal_path_still_passes_a_basename(self) -> None:
        sep = self._sep(master_vocal_path=None, audio_file_base="01. Song")
        voc = _arr(1.0).T
        with patch("engines.base.process_chain_model") as chain:
            sep._process_vocal_split_chain({VOCAL_STEM: voc})
        chain.assert_called_once()
        self.assertIsNone(chain.call_args.kwargs["vocal_stem_path"])
        self.assertEqual(chain.call_args.kwargs["vocal_stem_base"], "01. Song")


class ProcessChainModelPathTests(unittest.TestCase):
    def test_none_vocal_path_does_not_raise_basename_typeerror(self) -> None:
        model = MagicMock()
        model.bv_model_rebalance = False
        process_data = MagicMock()
        with (
            patch("engines.orchestration._build_seperator") as build,
            patch("engines.orchestration._run_seperator", return_value=None),
        ):
            process_chain_model(
                model,
                process_data,
                vocal_stem_path=None,
                master_vocal_source=_arr(1.0).T,
            )
        build.assert_called_once()
        audio, base = build.call_args.kwargs["vocal_stem_path"]
        self.assertIsInstance(audio, np.ndarray)
        self.assertIsInstance(base, str)
        self.assertTrue(base)

    def test_explicit_fallback_base_preserves_dots(self) -> None:
        model = MagicMock()
        model.bv_model_rebalance = False
        process_data = MagicMock()
        with (
            patch("engines.orchestration._build_seperator") as build,
            patch("engines.orchestration._run_seperator", return_value=None),
        ):
            process_chain_model(
                model,
                process_data,
                vocal_stem_path=None,
                vocal_stem_base="01. Song",
                master_vocal_source=_arr(1.0).T,
            )
        _audio, base = build.call_args.kwargs["vocal_stem_path"]
        self.assertEqual(base, "01. Song")


class _SplitSaveFake:
    def __init__(self, *, is_bv: bool = False) -> None:
        self.is_bv_model = is_bv
        self.written: list[str | None] = []

    def begin_save_phase(self, total: int) -> None:
        return None

    def stem_export_wav_path(self, stem: str) -> str:
        return f"/tmp/{stem}.wav"

    def write_audio(
        self,
        stem_path: str,
        stem_source: Any,
        samplerate: int,
        stem_name: str | None = None,
    ) -> None:
        self.written.append(stem_name)


class MdxcVocalSplitSaveTests(unittest.TestCase):
    def _save(self, sources: dict[str, np.ndarray], *, is_bv: bool = False) -> list[str | None]:
        fake = _SplitSaveFake(is_bv=is_bv)
        SeperateMDXC._write_vocal_split_pair(fake, sources, _arr(3.0), 44100)  # type: ignore[arg-type]
        return fake.written

    def test_title_case_pair_writes_lead_then_backing(self) -> None:
        self.assertEqual(
            self._save({"Vocals": _arr(1.0), "Instrumental": _arr(2.0)}),
            [LEAD_VOCAL_STEM_LABEL, BV_VOCAL_STEM_LABEL],
        )

    def test_lowercase_and_fusion_single_target_dict(self) -> None:
        self.assertEqual(
            self._save({"vocals": _arr(1.0), INST_STEM: _arr(2.0)}),
            [LEAD_VOCAL_STEM_LABEL, BV_VOCAL_STEM_LABEL],
        )

    def test_native_rate_mix_is_restored_before_splitter_complement(self) -> None:
        from types import SimpleNamespace

        fake = SimpleNamespace(
            mdx_c_configs=SimpleNamespace(
                audio=SimpleNamespace(sample_rate=48000),
                training=SimpleNamespace(target_instrument=None, instruments=["Vocals"]),
            ),
            is_roformer=False,
            primary_model_name="main",
            model_basename="main",
            primary_sources=None,
            audio_file="/tmp/song.wav",
            is_vocal_split_model=True,
            is_secondary_model=False,
            is_pre_proc_model=False,
            primary_stem_native="Vocals",
            is_bv_model=False,
            start_inference_console_write=lambda: None,
            write_to_console=lambda *args, **kwargs: None,
            demix=lambda mix: {"Vocals": np.ones((2, 480), dtype=np.float32)},
        )
        captured: dict[str, Any] = {}

        def write_pair(sources: dict[str, Any], mix: Any, samplerate: int) -> dict[str, Any]:
            captured["source_length"] = sources["Vocals"].shape[1]
            captured["mix_length"] = mix.shape[1]
            captured["samplerate"] = samplerate
            return {}

        fake._write_vocal_split_pair = write_pair
        with (
            patch("engines.mdx_c.prepare_mix", return_value=np.ones((2, 441), dtype=np.float32)),
            patch(
                "engines.mdx_c.librosa.resample",
                side_effect=lambda audio, *, orig_sr, target_sr, axis: np.ones(
                    (2, 480 if target_sr == 48000 else 441), dtype=np.float32
                ),
            ),
        ):
            SeperateMDXC.seperate(fake)  # type: ignore[arg-type]

        self.assertEqual(captured, {
            "source_length": 441,
            "mix_length": 441,
            "samplerate": 44100,
        })

    def test_three_stem_karaoke_skips_splitter_instrumental(self) -> None:
        self.assertEqual(
            self._save(
                {
                    "vocals": _arr(1.0),
                    "backing_vocal": _arr(2.0),
                    "instrumental": _arr(9.0),
                }
            ),
            [LEAD_VOCAL_STEM_LABEL, BV_VOCAL_STEM_LABEL],
        )

    def test_secondary_flag_does_not_change_logic_stems(self) -> None:
        self.assertEqual(
            self._save({"Vocals": _arr(1.0), "Instrumental": _arr(2.0)}),
            [LEAD_VOCAL_STEM_LABEL, BV_VOCAL_STEM_LABEL],
        )


if __name__ == "__main__":
    unittest.main()
