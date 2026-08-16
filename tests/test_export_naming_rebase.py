from __future__ import annotations

import os
import unittest

from core.export_naming import OutputNamingContext, rebase_output_naming


class RebaseOutputNamingTests(unittest.TestCase):
    def test_preserves_track_base_and_rewrites_directory(self) -> None:
        naming = OutputNamingContext(
            input_path="/in/song.wav",
            track="song",
            track_base="2-song Model",
            export_directory="/out/Model/song",
            extension="wav",
            file_index=2,
            file_total=3,
            model_label="Model",
        )
        rebased = rebase_output_naming(naming, "/stage/1", "/out")
        self.assertEqual(rebased.track_base, "2-song Model")
        self.assertEqual(rebased.export_directory, os.path.join("/stage/1", "Model", "song"))

    def test_root_export_stays_at_stage_root(self) -> None:
        naming = OutputNamingContext(
            input_path="/in/song.wav", track="song", track_base="song",
            export_directory="/out", extension="wav",
        )
        rebased = rebase_output_naming(naming, "/stage/1", "/out")
        self.assertEqual(rebased.export_directory, "/stage/1")


if __name__ == "__main__":
    unittest.main()
