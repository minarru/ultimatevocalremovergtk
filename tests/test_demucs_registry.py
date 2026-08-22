from __future__ import annotations

import unittest

from core.model_identity import DemucsSpec


class BundledDemucsSpecTests(unittest.TestCase):
    def test_specs_cover_every_official_mapper_stem(self) -> None:
        from core.demucs_registry import load_bundled_demucs_specs, mapper_stems

        specs = load_bundled_demucs_specs()
        self.assertEqual(set(specs), mapper_stems())

    def test_htdemucs_6s_is_six_source_v4(self) -> None:
        from core.demucs_registry import load_bundled_demucs_specs

        spec = load_bundled_demucs_specs()["demucs:htdemucs_6s"]
        self.assertEqual(spec, DemucsSpec("v4", "6_stem"))

    def test_uvr_bag_is_two_source(self) -> None:
        from core.demucs_registry import load_bundled_demucs_specs

        spec = load_bundled_demucs_specs()["demucs:UVR_Demucs_Model_1"]
        self.assertEqual(spec.source_layout, "2_stem")


class DemucsCatalogueSpecTests(unittest.TestCase):
    def test_explicit_version_is_not_overwritten_by_label(self) -> None:
        from types import SimpleNamespace

        from bundled.constants import DEMUCS_ARCH_TYPE
        from core.model_inventory import _demucs_spec

        entry = SimpleNamespace(
            label="Demucs v4: foo",
            display="v4 — foo",
            demucs_version="v3",
            stems=["drums", "bass", "other", "vocals"],
        )
        self.assertEqual(_demucs_spec(entry), DemucsSpec("v3", "4_stem"))

    def test_explicit_layout_is_not_overwritten_by_stem_count(self) -> None:
        from types import SimpleNamespace

        from core.model_inventory import _demucs_spec

        entry = SimpleNamespace(
            label="Demucs v4: htdemucs_6s",
            display="v4 — htdemucs_6s",
            source_layout="6_stem",
            stems=["drums", "bass", "other", "vocals"],
        )
        self.assertEqual(_demucs_spec(entry), DemucsSpec("v4", "6_stem"))

    def test_colon_label_import_is_accepted(self) -> None:
        from types import SimpleNamespace

        from core.model_inventory import _demucs_spec

        entry = SimpleNamespace(
            label="Demucs v3: mdx",
            display="v3 — mdx",
            stems=["drums", "bass", "other", "vocals"],
        )
        self.assertEqual(_demucs_spec(entry), DemucsSpec("v3", "4_stem"))

    def test_em_dash_display_is_not_imported_for_version(self) -> None:
        from types import SimpleNamespace

        from core.model_inventory import _demucs_spec

        entry = SimpleNamespace(
            label="Demucs v4 — foo",
            display="v4 — foo",
            stems=["drums", "bass", "other", "vocals"],
        )
        self.assertIsNone(_demucs_spec(entry))
