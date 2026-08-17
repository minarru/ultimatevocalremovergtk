"""Vocal-splitter stem pairing across community MDX-C yaml shapes."""

from __future__ import annotations

import unittest
from typing import Any
from unittest.mock import MagicMock, patch

import numpy as np

from bundled.constants import (
    BV_VOCAL_STEM,
    INST_STEM,
    LEAD_VOCAL_STEM,
    VOCAL_STEM,
)
from core.model_stem_semantics import (
    pick_backing_key,
    pick_instrumental_key,
    pick_vocal_key,
    vocal_inst_from_sources,
    vocal_split_primary_stem,
    vocal_split_source_roles,
    vocal_split_write_logic_stem,
)
from engines.base import SeperateAttributes
from engines.mdx import SeperateMDXC, mdx_vocal_split_chain_sources
from engines.orchestration import process_chain_model


def _arr(fill: float) -> np.ndarray:
    return np.full((2, 4), fill, dtype=np.float32)


class VocalSplitRemapTests(unittest.TestCase):
    def test_title_case_vocals_is_lead(self) -> None:
        self.assertEqual(
            vocal_split_primary_stem(is_bv_model=False, native_stem="Vocals"),
            LEAD_VOCAL_STEM,
        )

    def test_lowercase_vocals_is_lead(self) -> None:
        self.assertEqual(
            vocal_split_primary_stem(is_bv_model=False, native_stem="vocals"),
            LEAD_VOCAL_STEM,
        )

    def test_none_falls_back_to_backing_unless_primary_is_vocal(self) -> None:
        self.assertEqual(
            vocal_split_primary_stem(is_bv_model=False, native_stem=None),
            BV_VOCAL_STEM,
        )
        self.assertEqual(
            vocal_split_primary_stem(is_bv_model=False, native_stem="Vocals"),
            LEAD_VOCAL_STEM,
        )

    def test_bv_model_inverts(self) -> None:
        self.assertEqual(
            vocal_split_primary_stem(is_bv_model=True, native_stem="Vocals"),
            BV_VOCAL_STEM,
        )
        self.assertEqual(
            vocal_split_primary_stem(is_bv_model=True, native_stem="other"),
            LEAD_VOCAL_STEM,
        )

    def test_other_native_is_not_vocal(self) -> None:
        self.assertEqual(
            vocal_split_primary_stem(is_bv_model=False, native_stem="other"),
            BV_VOCAL_STEM,
        )


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


class WriteLogicStemTests(unittest.TestCase):
    def test_lead_only_and_yaml_vocals(self) -> None:
        self.assertEqual(
            vocal_split_write_logic_stem(LEAD_VOCAL_STEM, is_bv_model=False),
            LEAD_VOCAL_STEM,
        )
        self.assertEqual(
            vocal_split_write_logic_stem("Vocals", is_bv_model=False),
            LEAD_VOCAL_STEM,
        )
        self.assertEqual(
            vocal_split_write_logic_stem("vocals", is_bv_model=False),
            LEAD_VOCAL_STEM,
        )

    def test_yaml_inst_is_backing_for_karaoke(self) -> None:
        self.assertEqual(
            vocal_split_write_logic_stem("Instrumental", is_bv_model=False),
            BV_VOCAL_STEM,
        )
        self.assertEqual(
            vocal_split_write_logic_stem("other", is_bv_model=False),
            BV_VOCAL_STEM,
        )

    def test_empty_and_unknown_do_not_become_backing(self) -> None:
        self.assertIsNone(vocal_split_write_logic_stem("", is_bv_model=False))
        self.assertIsNone(vocal_split_write_logic_stem(None, is_bv_model=False))
        self.assertIsNone(vocal_split_write_logic_stem("center", is_bv_model=False))

    def test_bv_model_swaps_yaml_vocals(self) -> None:
        self.assertEqual(
            vocal_split_write_logic_stem("Vocals", is_bv_model=True),
            BV_VOCAL_STEM,
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
        sep = self._sep(master_vocal_path=None, audio_file_base="Ice Cream Truck")
        voc = _arr(1.0).T
        with patch("engines.base.process_chain_model") as chain:
            sep._process_vocal_split_chain({VOCAL_STEM: voc})
        chain.assert_called_once()
        path = chain.call_args.kwargs["vocal_stem_path"]
        self.assertIsInstance(path, str)
        self.assertTrue(path)


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
            [LEAD_VOCAL_STEM, BV_VOCAL_STEM],
        )

    def test_lowercase_and_fusion_single_target_dict(self) -> None:
        self.assertEqual(
            self._save({"vocals": _arr(1.0), INST_STEM: _arr(2.0)}),
            [LEAD_VOCAL_STEM, BV_VOCAL_STEM],
        )

    def test_three_stem_karaoke_skips_splitter_instrumental(self) -> None:
        self.assertEqual(
            self._save(
                {
                    "vocals": _arr(1.0),
                    "backing_vocal": _arr(2.0),
                    "instrumental": _arr(9.0),
                }
            ),
            [LEAD_VOCAL_STEM, BV_VOCAL_STEM],
        )

    def test_secondary_flag_does_not_change_logic_stems(self) -> None:
        self.assertEqual(
            self._save({"Vocals": _arr(1.0), "Instrumental": _arr(2.0)}),
            [LEAD_VOCAL_STEM, BV_VOCAL_STEM],
        )


if __name__ == "__main__":
    unittest.main()
