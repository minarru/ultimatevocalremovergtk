"""Generator collection behavior."""

import os
import unittest
from unittest import mock

# Load the script path before top-level catalogue imports (one module identity).
# isort: off
from tests import generator_fixtures as fixtures

from catalogue import cache as catalogue_cache
from catalogue import collect as catalogue
from catalogue import config_evidence as catalogue_config_evidence
from catalogue import entry_rules as catalogue_entry_rules
from catalogue import evidence as catalogue_evidence
from catalogue import locations as catalogue_locations
from catalogue import types as catalogue_types
from catalogue.stem_audit import audit_catalogue_stems

from core import paths as core_paths
from core.catalogue_types import SourceId




# isort: on

class DemucsBagArtifactTests(unittest.TestCase):
    def test_representative_weight_is_stable_across_json_key_order(self) -> None:
        entries = []
        rows = (
            {
                "mdx.yaml": "https://example.test/mdx.yaml",
                "c511e2ab-fe698775.th": "https://example.test/c511e2ab-fe698775.th",
                "7d865c68-3d5dd56b.th": "https://example.test/7d865c68-3d5dd56b.th",
            },
            {
                "7d865c68-3d5dd56b.th": "https://example.test/7d865c68-3d5dd56b.th",
                "c511e2ab-fe698775.th": "https://example.test/c511e2ab-fe698775.th",
                "mdx.yaml": "https://example.test/mdx.yaml",
            },
        )
        for payload in rows:
            entries.append(
                catalogue._parse_catalogue_entry(
                    source="test",
                    family="Demucs",
                    label="Demucs v3: mdx",
                    payload=payload,
                    ctx=catalogue_types.CatalogueContext(),
                    policy=catalogue_cache.FetchPolicy(allow_network=False),
                )[0]
            )

        self.assertEqual(
            [entry.weight_file for entry in entries],
            ["c511e2ab-fe698775.th", "c511e2ab-fe698775.th"],
        )

    def test_representative_weight_totally_orders_case_equivalent_names(self) -> None:
        weights = []
        for keys in (("A.th", "a.th"), ("a.th", "A.th")):
            payload = {key: f"https://example.test/{key}" for key in keys}
            entry = catalogue._parse_catalogue_entry(
                source="test",
                family="Demucs",
                label="Demucs v3: case collision",
                payload=payload,
                ctx=catalogue_types.CatalogueContext(),
                policy=catalogue_cache.FetchPolicy(allow_network=False),
            )[0]
            weights.append(entry.weight_file)

        self.assertEqual(weights, ["a.th", "a.th"])


class CatalogueIdentityAdoptionTests(unittest.TestCase):
    def test_collection_calls_the_neutral_catalogue_identity_boundary(self) -> None:
        entry = catalogue_types.ModelEntry(
            source="test",
            family="MDX-Net ONNX",
            catalogue_label="MDX-Net Model: exact row",
            weight_file="exact-model.onnx",
        )

        with mock.patch.object(
            catalogue_evidence, "catalogue_model_id", wraps=catalogue_evidence.catalogue_model_id
        ) as derive:
            model_id, _display = catalogue_evidence.catalogue_projection(entry)

        self.assertEqual(model_id, "mdx:exact-model")
        self.assertEqual(derive.call_args.args[:2], ("mdx", entry.catalogue_label))


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
        self.assertEqual(catalogue._source_for("Some Model", politrees, trvlvr), "TRvlvr+Politrees")

    def test_unattributed_label_is_unknown_not_trvlvr(self) -> None:
        """No membership anywhere is 'not proven', not positive provenance."""
        self.assertEqual(catalogue._source_for("Unknown Model", None, {}), "unknown")

    def test_failed_upstream_payload_does_not_attribute_everything_to_trvlvr(self) -> None:
        """A source that failed to load yields {}, which must not read as TRvlvr.

        _source_payload returns {} when a source has no content, so under a cold
        cache every label would otherwise be stamped with positive TRvlvr
        provenance on the strength of a failed membership check.
        """
        politrees = {"mdx23c_download_list": {"In Politrees": "a.ckpt"}}
        self.assertEqual(catalogue._source_for("In Politrees", politrees, {}), "Politrees")
        self.assertEqual(catalogue._source_for("In Nothing", politrees, {}), "unknown")

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
            "mdx_download_list": {"MelBand Roformer Karaoke": {"kara.ckpt": "https://u/kara.ckpt"}}
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
            "mdx_download_list": {"MelBand Roformer Karaoke": {"kara.ckpt": "https://u/kara.ckpt"}}
        }
        coordinator = CatalogueCoordinator(
            sources={
                SourceId.UPSTREAM: fixtures._local(
                    SourceId.UPSTREAM,
                    {
                        "vr_download_list": {},
                        "mdx_download_list": {},
                        "demucs_download_list": {},
                    },
                ),
                SourceId.POLITREES: fixtures._disabled(SourceId.POLITREES),
                SourceId.EXTRAS: fixtures._local(SourceId.EXTRAS, extras),
                SourceId.MVSEPLESS: fixtures._local(SourceId.MVSEPLESS, mvsepless),
            }
        )
        self.addCleanup(coordinator.close)
        return coordinator

    def test_collect_entries_uses_coordinator_sources(self) -> None:
        ctx = catalogue_types.CatalogueContext()
        _snapshot, entries = catalogue.collect_entries(
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


class CompactTrvlvrEvidenceTests(unittest.TestCase):
    _ROWS = (
        (
            "mdx:MDX23C-8KFFT-InstVoc_HQ",
            "mdx23c_download_list",
            "MDX23C Model: MDX23C-InstVoc HQ",
            "MDX23C-8KFFT-InstVoc_HQ.ckpt",
            "model_2_stem_full_band_8k.yaml",
            "",
            ("Vocals", "Instrumental"),
            "",
            "Vocals",
            ("Vocals", "Instrumental"),
            "451765e869b78dcb9ca9188a74da31f581b7254ff0e8b532aa76b974148de947",
        ),
        (
            "mdx:MDX23C-8KFFT-InstVoc_HQ_2",
            "mdx23c_download_vip_list",
            "MDX23C Model VIP: MDX23C-InstVoc HQ 2",
            "MDX23C-8KFFT-InstVoc_HQ_2.ckpt",
            "model_2_stem_full_band_8k.yaml",
            "",
            ("Vocals", "Instrumental"),
            "",
            "Vocals",
            ("Vocals", "Instrumental"),
            "451765e869b78dcb9ca9188a74da31f581b7254ff0e8b532aa76b974148de947",
        ),
        (
            "mdx:melband_roformer_inst_v1",
            "roformer_download_list",
            "Roformer Model: MelBand Roformer Kim | Inst V1 by Unwa",
            "melband_roformer_inst_v1.ckpt",
            "config_melbandroformer_inst.yaml",
            "https://raw.githubusercontent.com/TRvlvr/application_data/main/mdx_model_data/mdx_c_configs/config_melbandroformer_inst.yaml",
            ("Instrumental", "Vocals"),
            "Instrumental",
            "Instrumental",
            ("Instrumental",),
            "723af6755b5624be0a58351a13c930c472b51ef677cf2c7943394fefed7c3d4d",
        ),
        (
            "mdx:melband_roformer_inst_v2",
            "roformer_download_list",
            "Roformer Model: MelBand Roformer Kim | Inst V2 by Unwa",
            "melband_roformer_inst_v2.ckpt",
            "config_melbandroformer_inst_v2.yaml",
            "https://raw.githubusercontent.com/TRvlvr/application_data/main/mdx_model_data/mdx_c_configs/config_melbandroformer_inst_v2.yaml",
            ("Instrumental", "Vocals"),
            "Instrumental",
            "Instrumental",
            ("Instrumental",),
            "4b902a7360a930c178edb4846b30e4e326aa1219d1b2daf660d46a311e0cd50b",
        ),
        (
            "mdx:melband_roformer_instvoc_duality_v1",
            "roformer_download_list",
            "Roformer Model: MelBand Roformer Kim | InstVoc Duality V1 by Unwa",
            "melband_roformer_instvoc_duality_v1.ckpt",
            "config_melbandroformer_instvoc_duality.yaml",
            "https://raw.githubusercontent.com/TRvlvr/application_data/main/mdx_model_data/mdx_c_configs/config_melbandroformer_instvoc_duality.yaml",
            ("Vocals", "Instrumental"),
            "",
            "Vocals",
            ("Vocals", "Instrumental"),
            "62dbc3ecf29c7ac99df35003f8cb72da3348d646cb5e6d50e07323551c3d968f",
        ),
        (
            "mdx:melband_roformer_instvox_duality_v2",
            "roformer_download_list",
            "Roformer Model: MelBand Roformer Kim | InstVoc Duality V2 by Unwa",
            "melband_roformer_instvox_duality_v2.ckpt",
            "config_melbandroformer_instvoc_duality.yaml",
            "https://raw.githubusercontent.com/TRvlvr/application_data/main/mdx_model_data/mdx_c_configs/config_melbandroformer_instvoc_duality.yaml",
            ("Vocals", "Instrumental"),
            "",
            "Vocals",
            ("Vocals", "Instrumental"),
            "62dbc3ecf29c7ac99df35003f8cb72da3348d646cb5e6d50e07323551c3d968f",
        ),
        (
            "mdx:model_bs_roformer_ep_317_sdr_12.9755",
            "roformer_download_list",
            "Roformer Model: BS-Roformer-Viperx-1297",
            "model_bs_roformer_ep_317_sdr_12.9755.ckpt",
            "model_bs_roformer_ep_317_sdr_12.9755.yaml",
            "https://raw.githubusercontent.com/TRvlvr/application_data/main/mdx_model_data/mdx_c_configs/model_bs_roformer_ep_317_sdr_12.9755.yaml",
            ("Vocals", "Instrumental"),
            "Vocals",
            "Vocals",
            ("Vocals",),
            "2bfdd16c656bd9519aba757cc4f8834b7ede675eb1e00ec4772d74ae1c41af7f",
        ),
        (
            "mdx:model_bs_roformer_ep_368_sdr_12.9628",
            "roformer_download_list",
            "Roformer Model: BS-Roformer-Viperx-1296",
            "model_bs_roformer_ep_368_sdr_12.9628.ckpt",
            "model_bs_roformer_ep_368_sdr_12.9628.yaml",
            "https://raw.githubusercontent.com/TRvlvr/application_data/main/mdx_model_data/mdx_c_configs/model_bs_roformer_ep_368_sdr_12.9628.yaml",
            ("Vocals", "Instrumental"),
            "Vocals",
            "Vocals",
            ("Vocals",),
            "aea599b3f9bd4892a9c6bf5ac7c44787d3c99f717903d16054702665d477c86b",
        ),
        (
            "mdx:model_bs_roformer_ep_937_sdr_10.5309",
            "roformer_download_list",
            "Roformer Model: BS-Roformer-Viperx-1053",
            "model_bs_roformer_ep_937_sdr_10.5309.ckpt",
            "model_bs_roformer_ep_937_sdr_10.5309.yaml",
            "https://raw.githubusercontent.com/TRvlvr/application_data/main/mdx_model_data/mdx_c_configs/model_bs_roformer_ep_937_sdr_10.5309.yaml",
            ("No Drum-Bass", "Drum-Bass"),
            "No Drum-Bass",
            "No Drum-Bass",
            ("No Drum-Bass",),
            "302b6cee54adf39743b097b145ad4f64c37f3bd31b84791da32f963fb3692d04",
        ),
        (
            "mdx:model_mel_band_roformer_ep_3005_sdr_11.4360",
            "roformer_download_list",
            "Roformer Model: Mel-Roformer-Viperx-1143",
            "model_mel_band_roformer_ep_3005_sdr_11.4360.ckpt",
            "model_mel_band_roformer_ep_3005_sdr_11.4360.yaml",
            "https://raw.githubusercontent.com/TRvlvr/application_data/main/mdx_model_data/mdx_c_configs/model_mel_band_roformer_ep_3005_sdr_11.4360.yaml",
            ("Vocals", "Instrumental"),
            "Vocals",
            "Vocals",
            ("Vocals",),
            "d9b083b48dfdd0bd10f8a29a9c18777b0419496d938827f48a1db31bf0193aa3",
        ),
    )

    def setUp(self) -> None:
        os.environ["UVR_DISABLE_CATALOGUE_STEMS"] = "1"
        self.addCleanup(lambda: os.environ.pop("UVR_DISABLE_CATALOGUE_STEMS", None))

    def _coordinator(self):
        from core.catalogue_coordinator import CatalogueCoordinator

        upstream: dict[str, dict[str, object]] = {
            "vr_download_list": {},
            "demucs_download_list": {},
        }
        other_network: dict[str, object] = {}
        for (
            _model_id,
            list_key,
            label,
            checkpoint,
            config,
            config_url,
            _instruments,
            _target,
            _primary,
            _signature,
            _sha256,
        ) in self._ROWS:
            upstream.setdefault(list_key, {})[label] = {checkpoint: config}
            if config_url:
                other_network[label] = {
                    checkpoint: f"https://weights.test/{checkpoint}",
                    config: config_url,
                }
        upstream["other_network_list"] = other_network
        inst_v1 = self._ROWS[2]
        inst_v2 = self._ROWS[3]
        politrees = {
            "roformer_download_list": {
                "Later rejected Inst V1 alias": {
                    inst_v1[3]: f"https://later.test/{inst_v1[3]}",
                    "config_melband_roformer_inst.yaml": (
                        "https://later.test/config_melband_roformer_inst.yaml"
                    ),
                },
                inst_v2[2]: {
                    inst_v2[3]: f"https://later.test/{inst_v2[3]}",
                    "config_melband_roformer_inst_v2.yaml": (
                        "https://later.test/config_melband_roformer_inst_v2.yaml"
                    ),
                },
            }
        }
        coordinator = CatalogueCoordinator(
            sources={
                SourceId.UPSTREAM: fixtures._local(SourceId.UPSTREAM, upstream),
                SourceId.POLITREES: fixtures._local(SourceId.POLITREES, politrees),
                SourceId.EXTRAS: fixtures._disabled(SourceId.EXTRAS),
                SourceId.MVSEPLESS: fixtures._disabled(SourceId.MVSEPLESS),
            }
        )
        self.addCleanup(coordinator.close)
        return coordinator

    def test_all_ten_compact_ids_reconcile_from_exact_current_evidence(self) -> None:
        from core.model_stem_manifest import load_bundled_stem_semantics

        expected_by_config = {row[4]: row for row in self._ROWS}

        def load_yaml(
            yaml_name: str,
            yaml_url: str = "",
            *,
            policy: object,
        ) -> tuple[list[str], str, str, str, str]:
            del policy
            row = expected_by_config[yaml_name]
            self.assertEqual(yaml_url, row[5])
            metadata_source = (
                f"remote_yaml:{yaml_name}" if yaml_url else f"bundled_yaml:{yaml_name}"
            )
            return list(row[6]), row[7], "Roformer", metadata_source, row[10]

        ctx = catalogue_types.CatalogueContext()
        registry = load_bundled_stem_semantics()
        coordinator = self._coordinator()
        with mock.patch.object(catalogue_config_evidence, "_load_yaml_meta", side_effect=load_yaml):
            snapshot, entries = catalogue.collect_entries(
                ctx,
                allow_network=False,
                coordinator=coordinator,
                registry=registry,
            )

        expected_ids = {row[0] for row in self._ROWS}
        by_id = {
            model_id: entry
            for entry in entries
            if (model_id := catalogue_evidence.catalogue_projection(entry)[0]) in expected_ids
        }
        self.assertEqual(set(by_id), expected_ids)
        for row in self._ROWS:
            with self.subTest(model_id=row[0]):
                entry = by_id[row[0]]
                self.assertEqual(entry.weight_file, row[3])
                self.assertEqual(entry.config_yaml, row[4])
                self.assertEqual(entry.config_url, row[5])
                self.assertEqual(tuple(entry.instruments), row[6])
                self.assertEqual(entry.target_instrument, row[7])
                self.assertEqual(entry.primary_stem, row[8])
                self.assertEqual(entry.config_sha256, row[10])
                self.assertIsNotNone(entry.stem_semantics)
                assert entry.stem_semantics is not None
                self.assertTrue(entry.stem_semantics.reviewed)
                self.assertEqual(entry.stem_semantics.native_signature, row[9])

        self.assertNotIn("Later rejected Inst V1 alias", snapshot.mdx)
        self.assertEqual(snapshot.mdx[self._ROWS[3][2]], {self._ROWS[3][3]: self._ROWS[3][4]})
        result = audit_catalogue_stems(list(by_id.values()), ctx, registry=registry)
        compact_contract_codes = {
            "context-unreviewed",
            "native-signature",
            "pair-context-incomplete",
            "reference-route-set",
        }
        affected = tuple(
            diagnostic
            for diagnostic in result.diagnostics
            if diagnostic.code in compact_contract_codes
            and set(diagnostic.model_ids) & expected_ids
        )
        self.assertEqual(affected, ())

    def test_non_basename_scalar_is_not_config_evidence(self) -> None:
        from core.catalogue_coordinator import CatalogueCoordinator

        coordinator = CatalogueCoordinator(
            sources={
                SourceId.UPSTREAM: fixtures._local(
                    SourceId.UPSTREAM,
                    {
                        "roformer_download_list": {
                            "Roformer Model: Nested": {"nested.ckpt": "configs/nested.yaml"}
                        }
                    },
                ),
                SourceId.POLITREES: fixtures._disabled(SourceId.POLITREES),
                SourceId.EXTRAS: fixtures._disabled(SourceId.EXTRAS),
                SourceId.MVSEPLESS: fixtures._disabled(SourceId.MVSEPLESS),
            }
        )
        self.addCleanup(coordinator.close)
        with mock.patch.object(catalogue_config_evidence, "_load_yaml_meta") as load_yaml:
            _snapshot, entries = catalogue.collect_entries(
                catalogue_types.CatalogueContext(),
                allow_network=False,
                coordinator=coordinator,
            )

        self.assertEqual(entries[0].config_yaml, "")
        self.assertEqual(entries[0].config_url, "")
        load_yaml.assert_not_called()

    def test_mismatched_other_network_pair_does_not_supply_a_url(self) -> None:
        from core.catalogue_coordinator import CatalogueCoordinator

        coordinator = CatalogueCoordinator(
            sources={
                SourceId.UPSTREAM: fixtures._local(
                    SourceId.UPSTREAM,
                    {
                        "roformer_download_list": {
                            "Roformer Model: Mismatch": {"mismatch.ckpt": "mismatch.yaml"}
                        },
                        "other_network_list": {
                            "Roformer Model: Mismatch": {
                                "different.ckpt": "https://weights.test/different.ckpt",
                                "mismatch.yaml": "https://configs.test/mismatch.yaml",
                            }
                        },
                    },
                ),
                SourceId.POLITREES: fixtures._disabled(SourceId.POLITREES),
                SourceId.EXTRAS: fixtures._disabled(SourceId.EXTRAS),
                SourceId.MVSEPLESS: fixtures._disabled(SourceId.MVSEPLESS),
            }
        )
        self.addCleanup(coordinator.close)

        def load_yaml(
            yaml_name: str,
            yaml_url: str = "",
            *,
            policy: object,
        ) -> tuple[list[str], str, str, str, str]:
            del policy
            self.assertEqual(yaml_name, "mismatch.yaml")
            self.assertEqual(yaml_url, "")
            return [], "", "", "unavailable", ""

        with mock.patch.object(catalogue_config_evidence, "_load_yaml_meta", side_effect=load_yaml):
            snapshot, entries = catalogue.collect_entries(
                catalogue_types.CatalogueContext(),
                allow_network=False,
                coordinator=coordinator,
            )

        self.assertEqual(entries[0].config_yaml, "mismatch.yaml")
        self.assertEqual(entries[0].config_url, "")
        self.assertEqual(set(snapshot.mdx), {"Roformer Model: Mismatch"})


class DemucsFinalizationTests(unittest.TestCase):
    """Demucs family facts must land before the single finalization pass.

    The overlay used to run *after* _finalize_entry, so ui_export_note and
    flags were derived from an entry with no instruments and no stem count.
    """

    class _Snapshot:
        def __init__(self, demucs: dict) -> None:
            self.vr: dict = {}
            self.mdx: dict = {}
            self.demucs = demucs
            self.apollo: dict = {}
            self.meta: dict = {}
            self.unsupported: dict = {}

    def _entry(self, label: str, weight: str):
        snapshot = self._Snapshot({label: weight})
        entries = catalogue._entries_from_snapshot(
            snapshot,
            ({}, {}, {}, {}),
            catalogue_types.CatalogueContext(),
            policy=catalogue_cache.OFFLINE_FETCH_POLICY,
        )
        self.assertEqual(len(entries), 1)
        return entries[0]

    def test_six_stem_demucs_gets_its_export_note(self) -> None:
        entry = self._entry("Demucs v4: htdemucs_6s", "htdemucs_6s.th")
        self.assertEqual(entry.stem_count, 6)
        self.assertEqual(entry.ui_export_note, "UI: per-stem subset or focus row")

    def test_four_stem_demucs_gets_its_export_note(self) -> None:
        entry = self._entry("Demucs v4: htdemucs", "htdemucs.th")
        self.assertEqual(entry.stem_count, 4)
        self.assertEqual(entry.ui_export_note, "UI: per-stem subset or focus row")

    def test_two_stem_uvr_demucs_is_not_labelled_multi_stem(self) -> None:
        """The UVR Demucs model emits vocals+instrumental, not a multi-stem set."""
        entry = self._entry("Demucs v3: UVR Model", "UVR_Demucs_Model_1.th")
        self.assertEqual(entry.stem_count, 2)
        self.assertEqual(entry.backend_focus, "two_stem")

    def test_family_specific_best_result_prose_is_preserved(self) -> None:
        self.assertEqual(
            self._entry("Demucs v4: htdemucs_6s", "htdemucs_6s.th").best_result,
            "6-stem Demucs",
        )
        self.assertEqual(
            self._entry("Demucs v4: htdemucs", "htdemucs.th").best_result,
            "4-stem Demucs",
        )
        self.assertEqual(
            self._entry("Demucs v3: UVR Model", "UVR_Demucs_Model_1.th").best_result,
            "2-stem: instrumental + vocals (user picks focus)",
        )

    def test_metadata_source_records_the_exact_unified_declaration(self) -> None:
        self.assertEqual(
            self._entry("Demucs v4: htdemucs", "htdemucs.th").metadata_source,
            "catalogue_demucs_declaration",
        )


class EntryMetaProvenanceTests(unittest.TestCase):
    """Metadata that came from the snapshot must not report as unavailable."""

    def test_entry_meta_supplied_metadata_is_recorded_as_its_source(self) -> None:
        from core.catalog_sources import EntryMeta

        entry = catalogue_types.ModelEntry(
            source="mvsepless",
            family="Roformer",
            catalogue_label="Some Roformer",
            weight_file="model.ckpt",
            name_intent="unknown",
        )
        entry.metadata_source = "unavailable"
        catalogue_entry_rules._apply_entry_meta(
            entry,
            EntryMeta(
                label="Some Roformer",
                display="Some Roformer",
                arch="Roformer",
                stems=["vocals", "other"],
                target_instrument="other",
            ),
        )
        self.assertNotEqual(entry.metadata_source, "unavailable")
        self.assertIn("catalogue_meta", entry.metadata_source)

    def test_entry_meta_that_adds_nothing_leaves_the_source_alone(self) -> None:
        entry = catalogue_types.ModelEntry(
            source="mvsepless",
            family="Roformer",
            catalogue_label="Some Roformer",
            weight_file="model.ckpt",
        )
        entry.metadata_source = "unavailable"
        catalogue_entry_rules._apply_entry_meta(entry, None)
        self.assertEqual(entry.metadata_source, "unavailable")


class SourceAttributionCostTests(unittest.TestCase):
    def test_mvsepless_conversion_is_not_repeated_per_label(self) -> None:
        """_source_for ran a full catalogue conversion once per label (~474x)."""
        from unittest import mock

        class _Snapshot:
            vr = {f"Model {i}": f"m{i}.pth" for i in range(5)}
            mdx: dict = {}
            demucs: dict = {}
            apollo: dict = {}
            meta: dict = {}
            unsupported: dict = {}
            report = None

        mvsepless = {"raw": {"needs": "conversion"}}
        with mock.patch(
            "core.mvsepless_catalog.convert_mvsepless_catalog", return_value={}
        ) as convert:
            catalogue._entries_from_snapshot(
                _Snapshot(),
                ({}, {}, {}, mvsepless),
                catalogue_types.CatalogueContext(),
                policy=catalogue_cache.OFFLINE_FETCH_POLICY,
            )
        self.assertLessEqual(convert.call_count, 1, "converted once per label")


class EntryMetaOverlayTests(unittest.TestCase):
    def test_fills_blank_stems_target_and_unknown_intent(self) -> None:
        from core.catalog_sources import EntryMeta
        from core.model_stem_semantics import INTENT_KARAOKE

        entry = catalogue_types.ModelEntry(
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
        catalogue_entry_rules._apply_entry_meta(entry, meta)
        self.assertEqual(entry.instruments, ["vocals", "other"])
        self.assertEqual(entry.target_instrument, "vocals")
        self.assertEqual(entry.primary_stem, "vocals")
        self.assertEqual(entry.name_intent, INTENT_KARAOKE)

    def test_does_not_overwrite_resolved_fields_or_unknown_intent(self) -> None:
        from core.catalog_sources import EntryMeta
        from core.model_stem_semantics import INTENT_UNKNOWN

        entry = catalogue_types.ModelEntry(
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
        catalogue_entry_rules._apply_entry_meta(entry, meta)
        self.assertEqual(entry.instruments, ["drums", "bass"])
        self.assertEqual(entry.target_instrument, "drums")
        self.assertEqual(entry.primary_stem, "drums")
        self.assertEqual(entry.name_intent, "instrumental")

        entry.name_intent = "unknown"
        catalogue_entry_rules._apply_entry_meta(entry, meta)
        self.assertEqual(entry.name_intent, "unknown")


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

        with (
            tempfile.TemporaryDirectory() as tmp,
            patch("core.mdx_config_fetch._urlopen", return_value=_Resp()),
        ):
            path = catalogue_cache.fetch_cached("https://example.invalid/x.json", tmp, "x.json")
            if path is None:
                self.fail("expected a cached file")
            with open(path, encoding="utf-8") as handle:
                self.assertEqual(handle.read(), '{"ok": true}')

    def test_load_yaml_meta_uses_generator_cache_not_runtime_config_storage(self) -> None:
        import tempfile
        from unittest.mock import patch

        yaml_name = "zz_core_fetch_probe.yaml"
        body = b"training:\n  instruments: [vocals, other]\n  target_instrument: vocals\n"

        class _Response:
            def read(self) -> bytes:
                return body

            def __enter__(self) -> "_Response":
                return self

            def __exit__(self, *_args: object) -> None:
                return None

        with tempfile.TemporaryDirectory() as tmp:
            cache_dir = os.path.join(tmp, "generator-cache")
            runtime_dir = os.path.join(tmp, "runtime-configs")
            with (
                patch.object(catalogue_locations, "YAML_CACHE_DIR", cache_dir),
                patch.object(core_paths, "MDX_C_CONFIG_PATH", runtime_dir),
                patch(
                    "core.mdx_config_fetch.fetch_mdx_config_url",
                    side_effect=AssertionError("runtime config fetch used"),
                ),
                patch("core.mdx_config_fetch._urlopen", return_value=_Response()),
            ):
                instruments, target, _arch, source, _digest = catalogue_config_evidence._load_yaml_meta(
                    yaml_name, "https://example.invalid/x.yaml"
                )

            self.assertEqual(instruments, ["vocals", "other"])
            self.assertEqual(target, "vocals")
            self.assertEqual(source, f"remote_yaml:{yaml_name}")
            self.assertTrue(
                os.path.isfile(
                    catalogue_cache._cache_path(
                        cache_dir,
                        "https://example.invalid/x.yaml",
                        yaml_name,
                    )
                )
            )
            self.assertFalse(os.path.exists(runtime_dir))
