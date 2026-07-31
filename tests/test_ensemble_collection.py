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
from core.job_runner import Ensembler
from core.model_stem_semantics import export_stem_label


class _Model:
    def __init__(self, *, is_karaoke: bool = False, is_bv: bool = False,
                 stem_count: int = 2) -> None:
        self.is_karaoke = is_karaoke
        self.is_bv_model = is_bv
        self.mdx_stem_count = stem_count


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


if __name__ == "__main__":
    unittest.main()
