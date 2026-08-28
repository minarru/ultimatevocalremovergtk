"""Tests for unified model display naming."""

import importlib
import json
import os
import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock
from unittest.mock import MagicMock

from bundled.constants import DEMUCS_ARCH_TYPE, MDX_ARCH_TYPE, VR_ARCH_TYPE
from core.model_display import (
    build_demucs_display_index,
    build_vr_display_index,
    display_name_for_basename,
    format_tag_subtitle,
    format_tag_title,
    lookup_mapper_display,
    lookup_mapper_display_exact,
    map_basenames_to_display,
    parse_model_tag,
    resolve_mapper_basename,
    resolve_vr_model_basename,
    sanitize_catalogue_label,
    sanitize_demucs_catalogue_label,
    sanitize_vr_catalogue_label,
)


class SanitizeCatalogueLabelTests(unittest.TestCase):
    def test_strips_mdx_net_model_prefix(self) -> None:
        self.assertEqual(
            sanitize_catalogue_label("MDX-Net Model: UVR-MDX-NET Main"),
            "UVR-MDX-NET Main",
        )

    def test_keeps_community_author_suffix(self) -> None:
        label = "Roformer Model: MelBand Roformer Kim | FT v2 by Unwa"
        self.assertEqual(
            sanitize_catalogue_label(label),
            "MelBand Roformer Kim | FT v2 by Unwa",
        )

    def test_strips_mdx23c_model_and_vip_prefixes(self) -> None:
        self.assertEqual(
            sanitize_catalogue_label("MDX23C Model: Example"),
            "Example",
        )
        self.assertEqual(
            sanitize_catalogue_label("MDX23C Model VIP: Example VIP"),
            "Example VIP",
        )
        self.assertEqual(
            sanitize_catalogue_label("MDX-Net Model VIP: UVR VIP"),
            "UVR VIP",
        )

    def test_strips_bandit_plus_and_v2_prefixes(self) -> None:
        self.assertEqual(
            sanitize_catalogue_label("Bandit Plus: Cinema"),
            "Cinema",
        )
        self.assertEqual(
            sanitize_catalogue_label("Bandit v2: Speech"),
            "Speech",
        )


class SanitizeVrCatalogueLabelTests(unittest.TestCase):
    def test_strips_single_model_prefix(self) -> None:
        self.assertEqual(
            sanitize_vr_catalogue_label("VR Arch Single Model v5: 1_HP-UVR"),
            "v5: 1_HP-UVR",
        )


class SanitizeDemucsCatalogueLabelTests(unittest.TestCase):
    def test_converts_to_mapper_style(self) -> None:
        self.assertEqual(
            sanitize_demucs_catalogue_label("Demucs v4: htdemucs"),
            "v4 | htdemucs",
        )


class MapperLookupTests(unittest.TestCase):
    def test_exact_key_beats_substring(self) -> None:
        mapper = {
            "Kim_Vocal_1": "Kim Vocal 1",
            "Kim_Vocal_10": "Kim Vocal 10",
        }
        self.assertEqual(lookup_mapper_display("Kim_Vocal_1", mapper), "Kim Vocal 1")
        self.assertEqual(resolve_mapper_basename("Kim Vocal 1", mapper), "Kim_Vocal_1")

    def test_exact_stem_match(self) -> None:
        mapper = {"model.ckpt": "Display Name"}
        self.assertEqual(lookup_mapper_display("model", mapper), "Display Name")


class ExactMapperLookupTests(unittest.TestCase):
    """`lookup_mapper_display_exact` maps basename -> display, exactly."""

    def test_exact_mapper_lookup_accepts_basename_and_known_extension(self) -> None:
        mapper = {
            "model.ckpt": "Friendly CKPT",
            "other": "Other",
        }
        self.assertEqual(
            lookup_mapper_display_exact("model", mapper),
            "Friendly CKPT",
        )

    def test_exact_mapper_lookup_rejects_substring_candidate(self) -> None:
        self.assertIsNone(
            lookup_mapper_display_exact(
                "model",
                {"model_v2.ckpt": "Wrong model"},
            )
        )

    def test_bare_basename_key(self) -> None:
        self.assertEqual(
            lookup_mapper_display_exact("Kim_Vocal_1", {"Kim_Vocal_1": "Kim Vocal 1"}),
            "Kim Vocal 1",
        )

    def test_every_recognized_extension(self) -> None:
        for ext in (".ckpt", ".pth", ".onnx", ".yaml", ".th", ".gz"):
            with self.subTest(extension=ext):
                self.assertEqual(
                    lookup_mapper_display_exact("model", {f"model{ext}": "Friendly"}),
                    "Friendly",
                )

    def test_unrecognized_extension_is_ignored(self) -> None:
        self.assertIsNone(lookup_mapper_display_exact("model", {"model.bin": "Friendly"}))

    def test_empty_and_malformed_mappers(self) -> None:
        self.assertIsNone(lookup_mapper_display_exact("model", None))
        self.assertIsNone(lookup_mapper_display_exact("model", {}))
        self.assertIsNone(lookup_mapper_display_exact("", {"model": "Friendly"}))

    def test_prefers_bare_key_over_extension_key(self) -> None:
        mapper = {"model": "Bare", "model.ckpt": "Extended"}
        self.assertEqual(lookup_mapper_display_exact("model", mapper), "Bare")

    def test_returns_str_for_non_str_value(self) -> None:
        self.assertEqual(
            lookup_mapper_display_exact("model", {"model": 5}),  # type: ignore[dict-item]
            "5",
        )

    def test_does_not_perform_casefold_matching(self) -> None:
        self.assertIsNone(lookup_mapper_display_exact("MODEL", {"model.ckpt": "Friendly"}))


class VrDisplayIndexTests(unittest.TestCase):
    def test_maps_flat_vr_catalogue_entry(self) -> None:
        catalogues = [{"VR Arch Single Model v5: 1_HP-UVR": "1_HP-UVR.pth"}]
        index = build_vr_display_index(catalogues)
        self.assertEqual(index["1_HP-UVR"], "v5: 1_HP-UVR")


class DemucsDisplayIndexTests(unittest.TestCase):
    def test_maps_yaml_stem(self) -> None:
        catalogues = [
            {
                "Demucs v4: htdemucs": {
                    "htdemucs.yaml": "https://example.com/htdemucs.yaml",
                }
            }
        ]
        index = build_demucs_display_index(catalogues)
        self.assertEqual(index["htdemucs"], "v4 | htdemucs")


class ParseModelTagTests(unittest.TestCase):
    def test_splits_on_first_colon_space_only(self) -> None:
        tag = "VR Arc: v5: 1_HP-UVR"
        self.assertEqual(parse_model_tag(tag), ("VR Arc", "v5: 1_HP-UVR"))

    def test_format_tag_subtitle_returns_arch(self) -> None:
        self.assertEqual(format_tag_subtitle("MDX-Net: Kim Vocal 2"), "MDX-Net")

    def test_canonical_id_splits_to_arch_and_basename(self) -> None:
        self.assertEqual(parse_model_tag("mdx:Kim_Vocal_2"), (MDX_ARCH_TYPE, "Kim_Vocal_2"))
        self.assertEqual(format_tag_subtitle("mdx:Kim_Vocal_2"), MDX_ARCH_TYPE)
        self.assertEqual(format_tag_subtitle("vr:1_HP-UVR"), VR_ARCH_TYPE)
        self.assertEqual(format_tag_subtitle("demucs:htdemucs"), DEMUCS_ARCH_TYPE)


class FormatTagTitleTests(unittest.TestCase):
    def test_uses_repo_display_helper(self) -> None:
        repo = MagicMock()
        repo.mdx_name_select_MAPPER = {"Kim_Vocal_2": "Kim Vocal 2"}
        repo.mdx_catalogue_display_index.return_value = {}
        title = format_tag_title("MDX-Net: Kim Vocal 2", repo)
        self.assertEqual(title, "Kim Vocal 2")

    def test_canonical_id_uses_same_display_as_legacy_tag(self) -> None:
        repo = MagicMock()
        repo.mdx_name_select_MAPPER = {"Kim_Vocal_2": "Kim Vocal 2"}
        repo.mdx_catalogue_display_index.return_value = {}
        legacy = format_tag_title("MDX-Net: Kim Vocal 2", repo)
        canonical = format_tag_title("mdx:Kim_Vocal_2", repo)
        self.assertEqual(legacy, "Kim Vocal 2")
        self.assertEqual(canonical, "Kim Vocal 2")


class InvalidUnifiedManifestPresentationTests(unittest.TestCase):
    def test_module_reload_falls_back_to_raw_when_unified_manifest_is_invalid(self) -> None:
        import core.model_naming as naming
        from core.model_manifest import ModelManifestError

        try:
            with mock.patch(
                "core.model_manifest.load_model_manifest",
                side_effect=ModelManifestError(
                    ("author_aliases",),
                    "missing required field",
                ),
            ):
                reloaded = importlib.reload(naming)
                self.assertEqual(
                    reloaded.project_model_display("mdx:unknown_custom_model"),
                    "unknown_custom_model",
                )
        finally:
            importlib.reload(naming)


class ResolveVrModelBasenameTests(unittest.TestCase):
    def test_resolves_sanitized_display(self) -> None:
        index = {"1_HP-UVR": "v5: 1_HP-UVR"}
        self.assertEqual(
            resolve_vr_model_basename("v5: 1_HP-UVR", catalogue_index=index),
            "1_HP-UVR",
        )

    def test_resolves_upstream_catalogue_key(self) -> None:
        index = {"1_HP-UVR": "v5: 1_HP-UVR"}
        self.assertEqual(
            resolve_vr_model_basename(
                "VR Arch Single Model v5: 1_HP-UVR",
                catalogue_index=index,
            ),
            "1_HP-UVR",
        )


class DisplayNameForBasenameTests(unittest.TestCase):
    def test_catalogue_priority_over_mapper(self) -> None:
        mapper = {"known": "Mapper Name"}
        catalogue = {"known": "Catalogue Name"}
        self.assertEqual(
            display_name_for_basename("known", mapper, catalogue_index=catalogue),
            "Catalogue Name",
        )

    def test_mapper_fallback_when_not_in_catalogue(self) -> None:
        mapper = {"custom": "Custom Label"}
        catalogue = {"other": "Catalogue Name"}
        self.assertEqual(
            display_name_for_basename("custom", mapper, catalogue_index=catalogue),
            "Custom Label",
        )

    def test_stem_fallback_when_unmapped(self) -> None:
        self.assertEqual(
            display_name_for_basename("manual_stem", {}, catalogue_index={}),
            "manual_stem",
        )

    def test_mapper_when_catalogue_echoes_basename(self) -> None:
        mapper = {"MDX23C_D1581.ckpt": "MDX23C-InstVoc D1581"}
        catalogue = {"MDX23C_D1581": "MDX23C_D1581"}
        self.assertEqual(
            display_name_for_basename("MDX23C_D1581", mapper, catalogue_index=catalogue),
            "MDX23C-InstVoc D1581",
        )


class MapBasenamesToDisplayTests(unittest.TestCase):
    def test_demucs_catalogue_priority_over_mapper(self) -> None:
        repo = MagicMock()
        repo.demucs_name_select_MAPPER = {"htdemucs": "Short Alias"}
        repo.demucs_catalogue_display_index.return_value = {"htdemucs": "v4 | htdemucs"}
        self.assertEqual(
            map_basenames_to_display(["htdemucs"], DEMUCS_ARCH_TYPE, repo),
            ["v4 | htdemucs"],
        )


class MvseplessAndExtrasDisplayTests(unittest.TestCase):
    """Regression: models from extras/mvsepless rendered as raw basenames.

    ``load_mdx_catalog_display_index`` read only the upstream cache and
    Politrees, so anything added by the two newest catalogue sources fell back
    to its on-disk basename in the method pickers.

    CI has no live catalogues. Extras are bundled, while the mvsepless test
    enables that source explicitly and seeds its own private on-disk cache.
    """

    EXTRAS_BEFORE = (
        "huge_scnet_4stems_bleedless",
        "huge_scnet_4stems_fullness",
    )
    MVSEPLESS_BEFORE = (
        "bs_inst_hyperace2_unwa",
        "mbr_inst2_unwa",
        "mbr_instfvx_gabox",
    )

    @classmethod
    def _mvsepless_fixture(cls) -> dict[str, dict[str, object]]:
        def entry(
            model_id: str,
            *,
            model_type: str,
            full_name: str,
            stems: list[str],
            target: str,
        ) -> dict[str, object]:
            base = "https://example.invalid/mvsepless"
            return {
                "category": "Instrumental",
                "checkpoint_url": f"{base}/{model_id}.ckpt",
                "config_url": f"{base}/{model_id}_config.yaml",
                "full_name": full_name,
                "id": model_id,
                "model_type": model_type,
                "stems": stems,
                "target_instrument": target,
            }

        return {
            "bs_inst_hyperace2_unwa": entry(
                "bs_inst_hyperace2_unwa",
                model_type="bs_roformer",
                full_name=(
                    "BS Roformer Instrumental HyperACE v2 (finetuned anvuew vocal model) by Unwa"
                ),
                stems=["instrument", "vocals"],
                target="instrument",
            ),
            "mbr_inst2_unwa": entry(
                "mbr_inst2_unwa",
                model_type="mel_band_roformer",
                full_name="Mel-Band Roformer Instrumental v2 by Unwa",
                stems=["other", "vocals"],
                target="other",
            ),
            "mbr_instfvx_gabox": entry(
                "mbr_instfvx_gabox",
                model_type="mel_band_roformer",
                full_name="Mel-Band Roformer Instrumental FvX by GaboxR67",
                stems=["Instrumental", "Vocals"],
                target="Instrumental",
            ),
        }

    @classmethod
    def setUpClass(cls) -> None:
        from core.catalog_sources import invalidate_catalogue_merge
        from core.extra_catalog import clear_extra_catalog_cache
        from core.model_display import clear_display_cache

        os.environ.pop("UVR_DISABLE_EXTRA_MODELS", None)
        clear_extra_catalog_cache()
        invalidate_catalogue_merge()
        clear_display_cache()

    def test_previously_raw_extras_basenames_now_resolve(self) -> None:
        from core.model_display import load_mdx_catalog_display_index

        index = load_mdx_catalog_display_index(allow_network=False)
        missing = [name for name in self.EXTRAS_BEFORE if name not in index]
        self.assertEqual(missing, [], f"still unnamed: {missing}")
        display = index["huge_scnet_4stems_bleedless"]
        self.assertNotEqual(display, "huge_scnet_4stems_bleedless")
        self.assertNotIn("SCnet:", display)

    def test_previously_raw_mvsepless_basenames_now_resolve(self) -> None:
        import core.mvsepless_catalog as mvsepless_catalog
        from core.model_display import load_mdx_catalog_display_index

        with TemporaryDirectory() as directory:
            cache_path = Path(directory, "mvsepless_models.json")
            cache_path.write_text(
                json.dumps(
                    {
                        "fetched_at": time.time(),
                        "data": self._mvsepless_fixture(),
                    }
                ),
                encoding="utf-8",
            )
            with (
                mock.patch.dict(
                    os.environ,
                    {
                        "UVR_DISABLE_EXTRA_MODELS": "0",
                        "UVR_DISABLE_MVSEPLESS": "0",
                        "UVR_DISABLE_POLITREES": "1",
                    },
                ),
                mock.patch.object(
                    mvsepless_catalog,
                    "_cache_path",
                    return_value=str(cache_path),
                ),
                mock.patch.object(
                    mvsepless_catalog,
                    "_urlopen",
                    side_effect=AssertionError("hermetic display test attempted network"),
                ) as opener,
            ):
                mvsepless_catalog.clear_mvsepless_cache()
                try:
                    index = load_mdx_catalog_display_index(allow_network=False)
                finally:
                    mvsepless_catalog.clear_mvsepless_cache()
                opener.assert_not_called()

        missing = [name for name in self.MVSEPLESS_BEFORE if name not in index]
        self.assertEqual(missing, [], f"still unnamed: {missing}")
        display = index["mbr_inst2_unwa"]
        self.assertNotEqual(display, "mbr_inst2_unwa")
        self.assertNotIn("Roformer Model:", display)


if __name__ == "__main__":
    unittest.main()
