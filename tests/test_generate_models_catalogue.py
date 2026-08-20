import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts"))

from core.catalogue_types import SourceId  # noqa: E402
import generate_models_catalogue as catalogue  # noqa: E402


class UiNoteTests(unittest.TestCase):
    def test_vocals_other_note_only_for_two_stem_models(self):
        entry = catalogue.ModelEntry(
            source="test",
            family="Roformer",
            catalogue_label="MelBand Roformer Kim | Inst v1 by Unwa",
            weight_file="model.ckpt",
            instruments=["other", "vocals"],
            stem_count=2,
        )
        self.assertIn("Vocals / Instrumental", catalogue._ui_note(entry))

    def test_four_stem_vocals_other_uses_subset_row_note(self):
        entry = catalogue.ModelEntry(
            source="test",
            family="SCNet",
            catalogue_label="4-stems SCNet Large",
            weight_file="model.ckpt",
            instruments=["Drums", "Bass", "Other", "Vocals"],
            stem_count=4,
            name_intent="multi_stem",
        )
        self.assertEqual(catalogue._ui_note(entry), "UI: per-stem subset or focus row")

    def test_special_fx_best_result_and_focus(self):
        entry = catalogue.ModelEntry(
            source="test",
            family="VR Architecture",
            catalogue_label="UVR-DeNoise by FoxJoy",
            weight_file="UVR-DeNoise.pth",
            primary_stem="noise",
            name_intent="special_fx",
            metadata_source="community_models.txt",
        )
        catalogue._finalize_entry(entry)
        self.assertIn("Noise", entry.best_result)
        self.assertTrue(entry.backend_focus.startswith("special_fx_primary:"))
        self.assertIn("complement", entry.ui_export_note)

    def test_karaoke_2_gets_karaoke_backend_focus(self):
        entry = catalogue.ModelEntry(
            source="test",
            family="MDX-Net ONNX",
            catalogue_label="MDX-Net Model: UVR-MDX-NET Karaoke 2",
            weight_file="UVR_MDXNET_KARA_2.onnx",
            primary_stem="Instrumental",
            name_intent="karaoke",
            metadata_source="community_models.txt",
        )
        catalogue._finalize_entry(entry)
        self.assertTrue(entry.is_karaoke)
        self.assertEqual(entry.backend_focus, "karaoke_instrumental_primary")

    def test_specialty_stem_flags_old_vocals_mismatch(self):
        entry = catalogue.ModelEntry(
            source="test",
            family="Roformer",
            catalogue_label="BandSplit Roformer | Male-Female by aufr33",
            weight_file="model.ckpt",
            instruments=["male", "female"],
            primary_stem="male",
            name_intent="vocals",
            backend_focus="two_stem",
            metadata_source="remote_yaml:test.yaml",
        )
        flags = catalogue._flag_mismatches(entry)
        self.assertTrue(any("specialty 2-stem" in flag for flag in flags))


class SourceForTests(unittest.TestCase):
    def test_mdx23c_download_list_counts_as_trvlvr(self) -> None:
        trvlvr = {"mdx23c_download_list": {"Some Model": "some_model.ckpt"}}
        self.assertEqual(catalogue._source_for("Some Model", None, trvlvr), "TRvlvr")

    def test_mdx23c_only_in_politrees_is_politrees(self) -> None:
        politrees = {"mdx23c_download_list": {"Some Model": "some_model.ckpt"}}
        self.assertEqual(catalogue._source_for("Some Model", politrees, {}), "Politrees")

    def test_mdx23c_in_both_is_combined(self) -> None:
        politrees = {"mdx23c_download_list": {"Some Model": "some_model.ckpt"}}
        trvlvr = {"mdx23c_download_list": {"Some Model": "some_model.ckpt"}}
        self.assertEqual(
            catalogue._source_for("Some Model", politrees, trvlvr), "TRvlvr+Politrees"
        )

    def test_unknown_label_defaults_to_trvlvr(self) -> None:
        self.assertEqual(catalogue._source_for("Unknown Model", None, {}), "TRvlvr")

    def test_mdx23_download_list_only_in_politrees_is_politrees(self) -> None:
        politrees = {"mdx23_download_list": {"Some Model": "some_model.ckpt"}}
        self.assertEqual(catalogue._source_for("Some Model", politrees, {}), "Politrees")

    def test_scnet_in_upstream_counts_as_trvlvr(self) -> None:
        trvlvr = {"scnet_download_list": {"SCnet: Huge": {"huge.ckpt": "https://u/huge.ckpt"}}}
        politrees = {"scnet_download_list": {"SCnet: Huge": {"huge.ckpt": "https://p/huge.ckpt"}}}
        self.assertEqual(
            catalogue._source_for("SCnet: Huge", politrees, trvlvr), "TRvlvr+Politrees"
        )

    def test_extras_only_is_extras(self) -> None:
        extras = {
            "roformer_download_list": {
                "Roformer Model: BandSplit Roformer | HyperACE": {
                    "bs_hyperace.ckpt": "https://u/bs_hyperace.ckpt"
                }
            }
        }
        self.assertEqual(
            catalogue._source_for("Roformer Model: BandSplit Roformer | HyperACE", extras=extras),
            "extras",
        )

    def test_apollo_in_extras_is_extras(self) -> None:
        extras = {
            "apollo_download_list": {
                "Apollo Model: EDM Restoration by essid": {
                    "apollo_edm_by_essid.ckpt": "https://u/apollo.ckpt"
                }
            }
        }
        self.assertEqual(
            catalogue._source_for("Apollo Model: EDM Restoration by essid", extras=extras),
            "extras",
        )

    def test_mvsepless_only_is_mvsepless(self) -> None:
        mvsepless = {
            "mdx_download_list": {
                "MelBand Roformer Karaoke": {"kara.ckpt": "https://u/kara.ckpt"}
            }
        }
        self.assertEqual(
            catalogue._source_for("MelBand Roformer Karaoke", mvsepless=mvsepless),
            "mvsepless",
        )

    def test_upstream_and_extras_combine_in_merge_order(self) -> None:
        trvlvr = {"mdx_download_list": {"Shared": "shared.onnx"}}
        extras = {"mdx_download_list": {"Shared": {"shared.onnx": "https://u/shared.onnx"}}}
        self.assertEqual(
            catalogue._source_for("Shared", None, trvlvr, extras=extras),
            "TRvlvr+extras",
        )


def _local(source_id: SourceId, payload: dict):
    from core.remote_catalog_cache import RemoteJsonSource

    return RemoteJsonSource(source_id=source_id, local_loader=lambda: payload)


def _disabled(source_id: SourceId):
    from core.remote_catalog_cache import RemoteJsonSource

    return RemoteJsonSource(source_id=source_id, enabled=lambda: False)


class CollectEntriesTests(unittest.TestCase):
    def setUp(self) -> None:
        os.environ["UVR_DISABLE_CATALOGUE_STEMS"] = "1"
        self.addCleanup(lambda: os.environ.pop("UVR_DISABLE_CATALOGUE_STEMS", None))

    def _coordinator(self):
        from core.catalogue_coordinator import CatalogueCoordinator
        from core.catalogue_types import SourceId

        extras = {
            "roformer_download_list": {
                "Roformer Model: BandSplit Roformer | HyperACE": {
                    "bs_hyperace.ckpt": "https://u/bs_hyperace.ckpt"
                }
            },
            "apollo_download_list": {
                "Apollo Model: EDM Restoration by essid": {
                    "apollo_edm_by_essid.ckpt": "https://u/apollo.ckpt"
                }
            },
        }
        mvsepless = {
            "mdx_download_list": {
                "MelBand Roformer Karaoke": {"kara.ckpt": "https://u/kara.ckpt"}
            }
        }
        coordinator = CatalogueCoordinator(
            sources={
                SourceId.UPSTREAM: _local(
                    SourceId.UPSTREAM,
                    {
                        "vr_download_list": {},
                        "mdx_download_list": {},
                        "demucs_download_list": {},
                    },
                ),
                SourceId.POLITREES: _disabled(SourceId.POLITREES),
                SourceId.EXTRAS: _local(SourceId.EXTRAS, extras),
                SourceId.MVSEPLESS: _local(SourceId.MVSEPLESS, mvsepless),
            }
        )
        self.addCleanup(coordinator.close)
        return coordinator

    def test_collect_entries_uses_coordinator_sources(self) -> None:
        ctx = catalogue.CatalogueContext()
        entries = catalogue._collect_entries(
            ctx, allow_network=False, coordinator=self._coordinator()
        )
        by_label = {entry.catalogue_label: entry for entry in entries}
        hyperace = by_label["Roformer Model: BandSplit Roformer | HyperACE"]
        self.assertEqual(hyperace.source, "extras")
        self.assertEqual(hyperace.family, "Roformer")
        apollo = by_label["Apollo Model: EDM Restoration by essid"]
        self.assertEqual(apollo.source, "extras")
        self.assertEqual(apollo.family, "Apollo")
        karaoke = by_label["MelBand Roformer Karaoke"]
        self.assertEqual(karaoke.source, "mvsepless")


class EntryMetaOverlayTests(unittest.TestCase):
    def test_fills_blank_stems_target_and_unknown_intent(self) -> None:
        from core.catalog_sources import EntryMeta
        from core.model_stem_semantics import INTENT_KARAOKE

        entry = catalogue.ModelEntry(
            source="mvsepless",
            family="Roformer",
            catalogue_label="MelBand Roformer Karaoke",
            weight_file="kara.ckpt",
            name_intent="unknown",
        )
        meta = EntryMeta(
            label=entry.catalogue_label,
            display="MelBand Roformer — Karaoke",
            arch="MDX",
            stems=["vocals", "other"],
            target_instrument="vocals",
            intent=INTENT_KARAOKE,
        )
        catalogue._apply_entry_meta(entry, meta)
        self.assertEqual(entry.instruments, ["vocals", "other"])
        self.assertEqual(entry.target_instrument, "vocals")
        self.assertEqual(entry.primary_stem, "vocals")
        self.assertEqual(entry.name_intent, INTENT_KARAOKE)

    def test_does_not_overwrite_resolved_fields_or_unknown_intent(self) -> None:
        from core.catalog_sources import EntryMeta
        from core.model_stem_semantics import INTENT_UNKNOWN

        entry = catalogue.ModelEntry(
            source="extras",
            family="Roformer",
            catalogue_label="Named",
            weight_file="model.ckpt",
            instruments=["drums", "bass"],
            target_instrument="drums",
            primary_stem="drums",
            name_intent="instrumental",
        )
        meta = EntryMeta(
            label=entry.catalogue_label,
            display="Named",
            arch="MDX",
            stems=["vocals"],
            target_instrument="vocals",
            intent=INTENT_UNKNOWN,
        )
        catalogue._apply_entry_meta(entry, meta)
        self.assertEqual(entry.instruments, ["drums", "bass"])
        self.assertEqual(entry.target_instrument, "drums")
        self.assertEqual(entry.primary_stem, "drums")
        self.assertEqual(entry.name_intent, "instrumental")

        entry.name_intent = "unknown"
        catalogue._apply_entry_meta(entry, meta)
        self.assertEqual(entry.name_intent, "unknown")


class RenderDisplayTests(unittest.TestCase):
    def test_render_uses_canonical_display_name(self) -> None:
        from core.model_naming import canonical_display_name

        label = "Roformer Model: BandSplit Roformer | HyperACE by Unwa"
        entry = catalogue.ModelEntry(
            source="extras",
            family="Roformer",
            catalogue_label=label,
            weight_file="bs_hyperace.ckpt",
            name_intent="instrumental",
            best_result="Instrumental",
            backend_focus="instrumental_primary",
        )
        rendered = catalogue._render([entry])
        display = canonical_display_name(label)
        self.assertIn(display, rendered)
        self.assertNotIn("Roformer Model:", rendered)

    def test_render_header_lists_all_sources(self) -> None:
        rendered = catalogue._render([])
        self.assertIn("TRvlvr + Politrees + extras + mvsepless", rendered)
        self.assertIn(
            "catalogue helper summarizing primary/target",
            rendered,
        )
        self.assertNotIn("what `ModelConfig` uses as `primary_stem`", rendered)

    def test_parse_args_offline(self) -> None:
        args = catalogue._parse_args(["--offline"])
        self.assertTrue(args.offline)


class FetchHelperTests(unittest.TestCase):
    def test_fetch_cached_uses_core_urlopen(self) -> None:
        import tempfile
        from unittest.mock import patch

        class _Resp:
            def read(self) -> bytes:
                return b'{"ok": true}'

            def __enter__(self) -> "_Resp":
                return self

            def __exit__(self, *args: object) -> None:
                return None

        with tempfile.TemporaryDirectory() as tmp, patch(
            "core.mdx_config_fetch._urlopen", return_value=_Resp()
        ):
            path = catalogue._fetch_cached("https://example.invalid/x.json", tmp, "x.json")
            if path is None:
                self.fail("expected a cached file")
            with open(path, encoding="utf-8") as handle:
                self.assertEqual(handle.read(), '{"ok": true}')

    def test_load_yaml_meta_prefers_core_config_fetch(self) -> None:
        import tempfile
        from unittest.mock import patch

        yaml_name = "zz_core_fetch_probe.yaml"
        body = "training:\n  instruments: [vocals, other]\n  target_instrument: vocals\n"

        def fake_fetch(name: str, url: str) -> bool:
            dest = os.path.join(catalogue.paths.MDX_C_CONFIG_PATH, name)
            os.makedirs(catalogue.paths.MDX_C_CONFIG_PATH, exist_ok=True)
            with open(dest, "w", encoding="utf-8") as handle:
                handle.write(body)
            return True

        with tempfile.TemporaryDirectory() as tmp, patch.object(
            catalogue.paths, "MDX_C_CONFIG_PATH", tmp
        ), patch(
            "core.mdx_config_fetch.fetch_mdx_config_url", side_effect=fake_fetch
        ), patch.object(
            catalogue, "_fetch_yaml", side_effect=AssertionError("yaml cache fallback")
        ):
            instruments, target, _arch, source = catalogue._load_yaml_meta(
                yaml_name, "https://example.invalid/x.yaml"
            )
        self.assertEqual(instruments, ["vocals", "other"])
        self.assertEqual(target, "vocals")
        self.assertEqual(source, f"remote_yaml:{yaml_name}")


if __name__ == "__main__":
    unittest.main()
