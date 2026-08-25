"""Target-instrument ``other`` models are Instrumental + Vocals."""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import MagicMock, patch

from bundled.constants import INST_STEM, VOCAL_STEM
from core import Settings
from core.model_config import ModelConfig
from core.model_identity import MdxSpec, ModelArtifacts, ModelRecord
from core.model_repository import ModelRepository
from core.stem_roles import StemRoleId
from core.stems import StemRouteKind, export_stem_label

_TARGET_OTHER_TAGS = (
    "mdx:model_BandSplit-Roformer_Resurrection_Instrumental_by-Unwa",
    "mdx:mbr_inst2_unwa",
    "mdx:melband_roformer_inst_v1e_plus",
)


class TargetOtherStemTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.settings = Settings()
        cls.repo = ModelRepository()

    def _dry(self, tag: str) -> ModelConfig | None:
        try:
            model = ModelConfig(self.settings, self.repo, tag, is_dry_check=True)
        except Exception:
            return None
        if not model.model_status:
            return None
        return model

    def test_installed_target_other_models_are_voc_inst(self) -> None:
        found = 0
        for tag in _TARGET_OTHER_TAGS:
            model = self._dry(tag)
            if model is None:
                continue
            found += 1
            with self.subTest(tag=tag):
                self.assertTrue(model.is_target_instrument)
                self.assertEqual(model.primary_stem, INST_STEM)
                self.assertEqual(model.secondary_stem, VOCAL_STEM)
                self.assertNotEqual(str(model.secondary_stem).casefold(), "no other")
                self.assertEqual(export_stem_label(model, "other", for_ensemble=True), INST_STEM)
                self.assertEqual(
                    export_stem_label(model, VOCAL_STEM, for_ensemble=True), VOCAL_STEM
                )
        if found == 0:
            self.skipTest("no target-other Unwa models installed")

    def test_noninstalled_target_config_assembles_native_plus_derived_routes(self) -> None:
        """A fixture checkpoint exercises live ModelConfig without user models."""
        with TemporaryDirectory() as directory:
            root = Path(directory)
            model_dir = root / "models"
            config_dir = root / "configs"
            model_dir.mkdir()
            config_dir.mkdir()
            checkpoint = model_dir / "mbr_inst2_unwa.ckpt"
            checkpoint.write_bytes(b"fixture")
            (config_dir / "mbr_inst2_unwa_config.yaml").write_text(
                """\
audio:
  sample_rate: 44100
model:
  stereo: true
  depth: 1
  num_bands: 1
training:
  instruments: [other, vocals]
  target_instrument: other
inference:
  dim_t: 256
""",
                encoding="utf-8",
            )
            model_hash = "fixture-target-other"
            repo = MagicMock()
            repo.model_hash_table = {str(checkpoint): model_hash}
            repo.mdx_hash_MAPPER = {
                model_hash: {
                    "config_yaml": "mbr_inst2_unwa_config.yaml",
                    "is_roformer": True,
                }
            }
            repo.mdx_name_select_MAPPER = {}
            repo.on_unrecognized_model = None
            record = ModelRecord(
                id="mdx:mbr_inst2_unwa",
                family="mdx",
                basename="mbr_inst2_unwa",
                display="Fixture target-other",
                backend_name="mbr_inst2_unwa",
                artifacts=ModelArtifacts(checkpoint.name),
                installed=False,
                mdx=MdxSpec("mel_band_roformer"),
            )

            with (
                patch("core.paths.MDX_MODELS_DIR", str(model_dir)),
                patch("core.paths.MDX_C_CONFIG_PATH", str(config_dir)),
            ):
                model = ModelConfig(
                    Settings.defaults(),
                    repo,
                    record.display,
                    selected_process_method=record.arch,
                    is_dry_check=True,
                    identity=record,
                    model_dependencies={},
                )

        self.assertTrue(model.model_status)
        self.assertTrue(model.is_target_instrument)
        self.assertEqual(model.mdx_model_stems, ["other"])
        self.assertEqual(
            [route.role for route in model.available_stem_routes],
            [StemRoleId("mix.instrumental"), StemRoleId("vocal.vocals")],
        )
        self.assertEqual(
            [route.kind for route in model.available_stem_routes],
            [StemRouteKind.NATIVE, StemRouteKind.DERIVED],
        )
        self.assertEqual(
            model.available_stem_routes[1].complement_of,
            StemRoleId("mix.instrumental"),
        )

    def test_target_other_eligible_for_vocal_pair_not_removed_pseudo_pair(self) -> None:
        eligible_vocal = set(
            self.repo.ensemble_model_list(self.settings, "pair.vocals_instrumental")
        )
        eligible_other = set(self.repo.ensemble_model_list(self.settings, "other"))
        found = 0
        for tag in _TARGET_OTHER_TAGS:
            model = self._dry(tag)
            if model is None:
                continue
            found += 1
            with self.subTest(tag=tag):
                self.assertIn(tag, eligible_vocal)
                self.assertNotIn(tag, eligible_other)
        if found == 0:
            self.skipTest("no target-other Unwa models installed")


if __name__ == "__main__":
    unittest.main()
