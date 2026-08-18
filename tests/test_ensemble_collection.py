"""Ensemble members written by the export path must be collectible.

This is the guard for the one failure mode that no other test catches: if a
bucket tag does not survive ``format_stem_basename`` and the collection regex,
``get_files_to_ensemble_for_stem`` silently returns fewer members, the ensemble
emits one member's audio, and every unit test still passes.
"""

from __future__ import annotations

import os
import tempfile
import typing
import unittest

from core.export_naming import format_stem_basename
from core.ensembler import Ensembler
from core.model_stem_semantics import (
    BUCKET_INST_WITH_BV,
    BUCKET_LEAD_VOCALS,
    ensemble_pair_buckets,
    export_stem_label,
)
from core.stems import EnsemblePair


class _Model:
    def __init__(self, *, is_karaoke: bool = False, is_bv: bool = False,
                 stem_count: int = 2, demucs_stem_count: int = 0,
                 primary_stem: str = "Vocals") -> None:
        self.is_karaoke = is_karaoke
        self.is_bv_model = is_bv
        self.mdx_stem_count = stem_count
        self.demucs_stem_count = demucs_stem_count
        self.mdx_model_stems: list = []
        self.demucs_source_list: list = []
        self.primary_stem = primary_stem


def _collector() -> typing.Any:
    """An Ensembler without running __init__ (which would read settings.json).

    ``get_files_to_ensemble_for_stem`` only lists a directory and matches names.
    """
    return object.__new__(Ensembler)


def _write_member(folder: str, track: str, model_name: str,
                  model: _Model, stem: str) -> str:
    tag = export_stem_label(model, stem, for_ensemble=True)
    name = format_stem_basename(f"{track} {model_name}", tag) + ".wav"
    with open(os.path.join(folder, name), "wb") as handle:
        handle.write(b"")
    return name


class MemberCollectionTests(unittest.TestCase):
    def test_two_members_with_different_stem_casing_collect_together(self) -> None:
        # One model's yaml says 'vocals', another says 'Vocals'.
        with tempfile.TemporaryDirectory() as folder:
            _write_member(folder, "Song", "ModelA", _Model(), "vocals")
            _write_member(folder, "Song", "ModelB", _Model(), "Vocals")
            found = _collector().get_files_to_ensemble_for_stem(
                folder=folder, prefix="Song", stem_tag="Vocals"
            )
        self.assertEqual(len(found), 2)

    def test_two_stem_other_collects_with_instrumental(self) -> None:
        # mbr_inst2_unwa declares 'other'; it is an instrumental.
        with tempfile.TemporaryDirectory() as folder:
            _write_member(folder, "Song", "ModelA", _Model(), "other")
            _write_member(folder, "Song", "ModelB", _Model(), "Instrumental")
            found = _collector().get_files_to_ensemble_for_stem(
                folder=folder, prefix="Song", stem_tag="Instrumental"
            )
        self.assertEqual(len(found), 2)

    def test_karaoke_does_not_contaminate_the_clean_instrumental_bucket(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            _write_member(folder, "Song", "Clean", _Model(), "Instrumental")
            _write_member(folder, "Song", "Kara", _Model(is_karaoke=True), "Instrumental")
            collector = _collector()
            clean = collector.get_files_to_ensemble_for_stem(
                folder=folder, prefix="Song", stem_tag="Instrumental"
            )
            karaoke = collector.get_files_to_ensemble_for_stem(
                folder=folder, prefix="Song", stem_tag="Instrumental_WithBackingVocals"
            )
        self.assertEqual(len(clean), 1)
        self.assertEqual(len(karaoke), 1)
        self.assertIn("Clean", os.path.basename(clean[0]))
        self.assertIn("Kara", os.path.basename(karaoke[0]))

    def test_every_karaoke_stem_round_trips(self) -> None:
        model = _Model(is_karaoke=True)
        with tempfile.TemporaryDirectory() as folder:
            for stem in ("Vocals", "Instrumental", "lead_only"):
                name = _write_member(folder, "Song", "Kara", model, stem)
                tag = export_stem_label(model, stem, for_ensemble=True)
                found = _collector().get_files_to_ensemble_for_stem(
                    folder=folder, prefix="Song", stem_tag=tag
                )
                with self.subTest(stem=stem):
                    self.assertTrue(
                        any(os.path.basename(f) == name for f in found),
                        f"{name!r} was written but not collected under {tag!r}",
                    )


class EnsemblerPairBucketTests(unittest.TestCase):
    """Combine tags must be filename buckets, not UI pair display labels."""

    def test_karaoke_pair_buckets_match_export_labels(self) -> None:
        primary, secondary = ensemble_pair_buckets(EnsemblePair.KARAOKE)
        self.assertEqual(primary, BUCKET_LEAD_VOCALS)
        self.assertEqual(secondary, BUCKET_INST_WITH_BV)
        model = _Model(is_karaoke=True)
        self.assertEqual(export_stem_label(model, "Vocals", for_ensemble=True), primary)
        self.assertEqual(
            export_stem_label(model, "Instrumental", for_ensemble=True), secondary
        )

    def test_ensembler_stores_karaoke_buckets_not_display_labels(self) -> None:
        ensembler = object.__new__(Ensembler)
        # Minimal stand-in for Ensembler.__init__'s pair-bucket assignment.
        primary, secondary = ensemble_pair_buckets(EnsemblePair.KARAOKE)
        ensembler.ensemble_primary_stem = primary
        ensembler.ensemble_secondary_stem = secondary
        self.assertEqual(ensembler.ensemble_primary_stem, BUCKET_LEAD_VOCALS)
        self.assertEqual(ensembler.ensemble_secondary_stem, BUCKET_INST_WITH_BV)
        self.assertNotEqual(ensembler.ensemble_primary_stem, "Lead Vocals")

    def test_flipped_karaoke_primary_still_exports_pair_buckets(self) -> None:
        # VR karaoke: primary Instrumental / secondary Vocals.
        model = _Model(is_karaoke=True, primary_stem="Instrumental")
        self.assertEqual(
            export_stem_label(model, "Instrumental", for_ensemble=True),
            BUCKET_INST_WITH_BV,
        )
        self.assertEqual(
            export_stem_label(model, "Vocals", for_ensemble=True),
            BUCKET_LEAD_VOCALS,
        )
        primary, secondary = ensemble_pair_buckets(EnsemblePair.KARAOKE)
        with tempfile.TemporaryDirectory() as folder:
            _write_member(folder, "Song", "VRKara", model, "Instrumental")
            _write_member(folder, "Song", "VRKara", model, "Vocals")
            collector = _collector()
            self.assertEqual(
                len(collector.get_files_to_ensemble_for_stem(
                    folder=folder, prefix="Song", stem_tag=primary
                )),
                1,
            )
            self.assertEqual(
                len(collector.get_files_to_ensemble_for_stem(
                    folder=folder, prefix="Song", stem_tag=secondary
                )),
                1,
            )

    def test_vocal_pair_unchanged(self) -> None:
        self.assertEqual(
            ensemble_pair_buckets(EnsemblePair.VOCALS_INSTRUMENTAL),
            ("Vocals", "Instrumental"),
        )


if __name__ == "__main__":
    unittest.main()
