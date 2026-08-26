"""Strict exact-ID MDX runtime-contract supplement regressions."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from core.mdx_runtime_contract import (
    BUNDLED_MDX_RUNTIME_CONTRACT_PATH,
    MdxRuntimeContractError,
    load_bundled_mdx_runtime_contracts,
    load_mdx_runtime_contract_document,
    load_mdx_runtime_contracts,
    reconcile_mdx_runtime_signature,
)
from core.model_stem_manifest import BUNDLED_MANIFEST_PATH, load_stem_manifest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

CLASSIC_ID = "mdx:UVR_MDXNET_KARA_2"
ContractExpectation = tuple[str, tuple[str, ...], str, tuple[str, ...]]
EXPECTED_CONTRACTS: dict[str, ContractExpectation] = {
    "mdx:Kim_Inst": ("classic_onnx", ("Instrumental", "Vocals"), "Instrumental", ()),
    CLASSIC_ID: ("classic_onnx", ("Instrumental", "Vocals"), "Instrumental", ()),
    "mdx:Kim_Vocal_1": ("classic_onnx", ("Vocals", "Instrumental"), "Vocals", ()),
    "mdx:Kim_Vocal_2": ("classic_onnx", ("Vocals", "Instrumental"), "Vocals", ()),
    "mdx:UVR_MDXNET_1_9703": (
        "classic_onnx",
        ("Vocals", "Instrumental"),
        "Vocals",
        (),
    ),
    "mdx:UVR_MDXNET_2_9682": (
        "classic_onnx",
        ("Vocals", "Instrumental"),
        "Vocals",
        (),
    ),
    "mdx:UVR_MDXNET_3_9662": (
        "classic_onnx",
        ("Vocals", "Instrumental"),
        "Vocals",
        (),
    ),
    "mdx:UVR_MDXNET_9482": (
        "classic_onnx",
        ("Vocals", "Instrumental"),
        "Vocals",
        (),
    ),
    "mdx:UVR_MDXNET_KARA": (
        "classic_onnx",
        ("Vocals", "Instrumental"),
        "Vocals",
        (),
    ),
    "mdx:Reverb_HQ_By_FoxJoy": (
        "classic_onnx",
        ("Reverb", "No Reverb"),
        "Reverb",
        (),
    ),
    "mdx:UVR-MDX-NET_Crowd_HQ_1": (
        "classic_onnx",
        ("No Crowd", "Crowd"),
        "No Crowd",
        (),
    ),
    "mdx:kuielab_a_bass": ("classic_onnx", ("Bass", "No Bass"), "Bass", ()),
    "mdx:kuielab_b_bass": ("classic_onnx", ("Bass", "No Bass"), "Bass", ()),
    "mdx:kuielab_a_drums": ("classic_onnx", ("Drums", "No Drums"), "Drums", ()),
    "mdx:kuielab_b_drums": ("classic_onnx", ("Drums", "No Drums"), "Drums", ()),
    "mdx:kuielab_a_other": ("classic_onnx", ("Other", "No Other"), "Other", ()),
    "mdx:kuielab_b_other": ("classic_onnx", ("Other", "No Other"), "Other", ()),
    "mdx:kuielab_a_vocals": (
        "classic_onnx",
        ("Vocals", "Instrumental"),
        "Vocals",
        (),
    ),
    "mdx:kuielab_b_vocals": (
        "classic_onnx",
        ("Vocals", "Instrumental"),
        "Vocals",
        (),
    ),
    "mdx:MDX23C-8KFFT-InstVoc_HQ": (
        "mdx_c_multi",
        ("Vocals", "Instrumental"),
        "Vocals",
        ("model_2_stem_full_band_8k.yaml",),
    ),
    "mdx:MDX23C-8KFFT-InstVoc_HQ_2": (
        "mdx_c_multi",
        ("Vocals", "Instrumental"),
        "Vocals",
        ("model_2_stem_full_band_8k.yaml",),
    ),
    "mdx:melband_roformer_instvoc_duality_v1": (
        "mdx_c_multi",
        ("Vocals", "Instrumental"),
        "Vocals",
        ("config_melbandroformer_instvoc_duality.yaml",),
    ),
    "mdx:melband_roformer_instvox_duality_v2": (
        "mdx_c_multi",
        ("Vocals", "Instrumental"),
        "Vocals",
        ("config_melbandroformer_instvoc_duality.yaml",),
    ),
    "mdx:melband_roformer_inst_v1": (
        "mdx_c_target",
        ("Instrumental",),
        "Instrumental",
        ("config_melbandroformer_inst.yaml",),
    ),
    "mdx:melband_roformer_inst_v2": (
        "mdx_c_target",
        ("Instrumental",),
        "Instrumental",
        ("config_melbandroformer_inst_v2.yaml",),
    ),
    "mdx:model_bs_roformer_ep_317_sdr_12.9755": (
        "mdx_c_target",
        ("Vocals",),
        "Vocals",
        (
            "model_bs_roformer_ep_317_sdr_12.9755.yaml",
            "config_bs_roformer_ep_317_sdr_12.9755.yaml",
        ),
    ),
    "mdx:model_bs_roformer_ep_368_sdr_12.9628": (
        "mdx_c_target",
        ("Vocals",),
        "Vocals",
        (
            "model_bs_roformer_ep_368_sdr_12.9628.yaml",
            "config_bs_roformer_ep_368_sdr_12.9628.yaml",
        ),
    ),
    "mdx:model_bs_roformer_ep_937_sdr_10.5309": (
        "mdx_c_target",
        ("No Drum-Bass",),
        "No Drum-Bass",
        ("model_bs_roformer_ep_937_sdr_10.5309.yaml",),
    ),
    "mdx:model_mel_band_roformer_ep_3005_sdr_11.4360": (
        "mdx_c_target",
        ("Vocals",),
        "Vocals",
        ("model_mel_band_roformer_ep_3005_sdr_11.4360.yaml",),
    ),
}
PROMOTION_IDS = frozenset(EXPECTED_CONTRACTS).difference({CLASSIC_ID})


def _evidence() -> dict[str, object]:
    return {
        "artifact_sources": ["https://example.test/UVR_MDXNET_KARA_2.onnx"],
        "runtime_metadata_sources": ["models/MDX_Net_Models/model_data/model_data.json"],
        "review_note": "Exact artifact and checked-in hash metadata reviewed.",
    }


def _contract(
    *,
    backend: str = "classic_onnx",
    signature: list[str] | None = None,
    primary: str = "Instrumental",
    configs: list[str] | None = None,
) -> dict[str, object]:
    return {
        "backend": backend,
        "native_signature": signature or ["Instrumental", "Vocals"],
        "primary_native": primary,
        "config_yamls": [] if configs is None else configs,
        "evidence": _evidence(),
    }


def _document() -> dict[str, object]:
    return {"schema_version": 1, "contracts": {CLASSIC_ID: _contract()}}


class _ContractTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.semantic_registry = load_stem_manifest(BUNDLED_MANIFEST_PATH)

    def load(self, document: object):
        return load_mdx_runtime_contract_document(document, registry=self.semantic_registry)


class MdxRuntimeContractValidationTests(_ContractTestCase):
    def test_schema_version_is_exact_integer_one(self) -> None:
        for invalid in (True, False, 1.0, "1", 0, 2):
            with self.subTest(invalid=invalid):
                document = _document()
                document["schema_version"] = invalid
                with self.assertRaisesRegex(Exception, "exact integer 1"):
                    self.load(document)

    def test_duplicate_json_keys_are_rejected_at_root_and_nested_levels(self) -> None:
        texts = (
            '{"schema_version":1,"schema_version":1,"contracts":{}}',
            '{"schema_version":1,"contracts":{"mdx:x":{"backend":"classic_onnx",'
            '"backend":"classic_onnx"}}}',
            '{"schema_version":1,"contracts":{"mdx:x":{"evidence":{'
            '"review_note":"a","review_note":"b"}}}}',
        )
        for text in texts:
            with self.subTest(text=text), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "contracts.json"
                path.write_text(text, encoding="utf-8")
                with self.assertRaisesRegex(Exception, "duplicate key"):
                    load_mdx_runtime_contracts(path, registry=self.semantic_registry)

    def test_semantic_manifest_parity_failure_is_wrapped_as_contract_error(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            malformed_manifest = Path(directory) / "manifest.json"
            malformed_manifest.write_text("{}", encoding="utf-8")
            with (
                mock.patch(
                    "core.mdx_runtime_contract.BUNDLED_MANIFEST_PATH",
                    malformed_manifest,
                ),
                self.assertRaisesRegex(
                    MdxRuntimeContractError,
                    "semantic_manifest.*semantic manifest parity",
                ),
            ):
                load_mdx_runtime_contracts(BUNDLED_MDX_RUNTIME_CONTRACT_PATH)

    def test_unknown_fields_are_rejected_at_every_closed_object_level(self) -> None:
        cases: list[tuple[str, dict[str, object]]] = []
        root = _document()
        root["extra"] = True
        cases.append(("root", root))
        contract = _document()
        contracts = contract["contracts"]
        assert isinstance(contracts, dict)
        value = contracts[CLASSIC_ID]
        assert isinstance(value, dict)
        value["extra"] = True
        cases.append(("contract", contract))
        evidence = _document()
        contracts = evidence["contracts"]
        assert isinstance(contracts, dict)
        value = contracts[CLASSIC_ID]
        assert isinstance(value, dict)
        raw_evidence = value["evidence"]
        assert isinstance(raw_evidence, dict)
        raw_evidence["extra"] = True
        cases.append(("evidence", evidence))

        for name, document in cases:
            with self.subTest(name=name), self.assertRaisesRegex(Exception, "unknown field"):
                self.load(document)

    def test_strings_are_non_empty_stripped_and_lists_reject_duplicates(self) -> None:
        mutations = (
            ("blank primary", lambda value: value.__setitem__("primary_native", "")),
            (
                "padded stem",
                lambda value: value.__setitem__("native_signature", [" Instrumental", "Vocals"]),
            ),
            (
                "duplicate stem",
                lambda value: value.__setitem__("native_signature", ["Vocals", "Vocals"]),
            ),
            (
                "casefold stem",
                lambda value: value.__setitem__("native_signature", ["Vocals", "vocals"]),
            ),
            (
                "duplicate evidence",
                lambda value: value["evidence"].__setitem__(  # type: ignore[union-attr]
                    "artifact_sources", ["checked-in:a", "checked-in:a"]
                ),
            ),
        )
        for name, mutate in mutations:
            document = _document()
            contracts = document["contracts"]
            assert isinstance(contracts, dict)
            value = contracts[CLASSIC_ID]
            assert isinstance(value, dict)
            mutate(value)
            with self.subTest(name=name), self.assertRaises(MdxRuntimeContractError):
                self.load(document)

    def test_config_names_are_exact_basenames_and_casefold_unique(self) -> None:
        for invalid in (
            ["config.json"],
            ["nested/config.yaml"],
            ["config.yaml", "CONFIG.YAML"],
            [" config.yaml"],
        ):
            document = _document()
            contracts = document["contracts"]
            assert isinstance(contracts, dict)
            contracts[CLASSIC_ID] = _contract(
                backend="mdx_c_target",
                signature=["Instrumental"],
                primary="Instrumental",
                configs=invalid,
            )
            with self.subTest(invalid=invalid), self.assertRaises(MdxRuntimeContractError):
                self.load(document)

    def test_backend_cardinality_and_config_rules_are_closed(self) -> None:
        invalid_contracts = (
            _contract(backend="unknown"),
            _contract(signature=["Vocals"]),
            _contract(configs=["unexpected.yaml"]),
            _contract(
                backend="mdx_c_target", signature=["Vocals", "Instrumental"], configs=["x.yaml"]
            ),
            _contract(backend="mdx_c_target", signature=["Vocals"], primary="Vocals", configs=[]),
            _contract(
                backend="mdx_c_multi", signature=["Vocals"], primary="Vocals", configs=["x.yaml"]
            ),
            _contract(backend="mdx_c_multi", configs=[]),
        )
        for invalid in invalid_contracts:
            document = _document()
            contracts = document["contracts"]
            assert isinstance(contracts, dict)
            contracts[CLASSIC_ID] = invalid
            with self.subTest(invalid=invalid), self.assertRaises(MdxRuntimeContractError):
                self.load(document)

    def test_primary_must_be_a_signature_member_and_id_must_be_mdx(self) -> None:
        document = _document()
        contracts = document["contracts"]
        assert isinstance(contracts, dict)
        value = contracts[CLASSIC_ID]
        assert isinstance(value, dict)
        value["primary_native"] = "Other"
        with self.assertRaisesRegex(Exception, "primary_native"):
            self.load(document)

        document = _document()
        contracts = document["contracts"]
        assert isinstance(contracts, dict)
        contracts["vr:UVR_MDXNET_KARA_2"] = contracts.pop(CLASSIC_ID)
        with self.assertRaisesRegex(Exception, "mdx"):
            self.load(document)

    def test_manifest_parity_is_casefold_set_based_but_contract_order_is_retained(self) -> None:
        document = _document()
        contracts = document["contracts"]
        assert isinstance(contracts, dict)
        value = contracts[CLASSIC_ID]
        assert isinstance(value, dict)
        value["native_signature"] = ["vocals", "instrumental"]
        value["primary_native"] = "instrumental"
        registry = self.load(document)
        self.assertEqual(
            registry.contracts[CLASSIC_ID].native_signature, ("vocals", "instrumental")
        )

        value["native_signature"] = ["Instrumental", "Other"]
        value["primary_native"] = "Instrumental"
        with self.assertRaisesRegex(Exception, "semantic manifest"):
            self.load(document)


class BundledMdxRuntimeContractTests(_ContractTestCase):
    def test_bundled_inventory_has_exact_ids_classes_and_alias_exclusions(self) -> None:
        registry = load_mdx_runtime_contracts(
            BUNDLED_MDX_RUNTIME_CONTRACT_PATH,
            registry=self.semantic_registry,
        )
        expected_ids = PROMOTION_IDS | {CLASSIC_ID}
        self.assertEqual(set(registry.contracts), expected_ids)
        self.assertEqual(
            {
                model_id: (
                    contract.backend,
                    contract.native_signature,
                    contract.primary_native,
                    contract.config_yamls,
                )
                for model_id, contract in registry.contracts.items()
            },
            EXPECTED_CONTRACTS,
        )
        self.assertEqual(
            {
                backend: sum(c.backend == backend for c in registry.contracts.values())
                for backend in ("classic_onnx", "mdx_c_multi", "mdx_c_target")
            },
            {"classic_onnx": 19, "mdx_c_multi": 4, "mdx_c_target": 6},
        )
        self.assertEqual(
            registry.contracts["mdx:melband_roformer_inst_v1"].config_yamls,
            ("config_melbandroformer_inst.yaml",),
        )
        self.assertEqual(
            registry.contracts["mdx:melband_roformer_inst_v2"].config_yamls,
            ("config_melbandroformer_inst_v2.yaml",),
        )
        all_configs = {
            config for contract in registry.contracts.values() for config in contract.config_yamls
        }
        self.assertNotIn("config_melband_roformer_inst.yaml", all_configs)
        self.assertNotIn("config_melband_roformer_inst_v2.yaml", all_configs)
        for model_id, contract in registry.contracts.items():
            with self.subTest(model_id=model_id, evidence="artifact"):
                artifact_name = Path(contract.evidence.artifact_sources[0]).name
                self.assertEqual(Path(artifact_name).stem, model_id.removeprefix("mdx:"))
                self.assertIn(
                    "models/MDX_Net_Models/model_data/model_data.json",
                    contract.evidence.runtime_metadata_sources,
                )
            for config in contract.config_yamls:
                with self.subTest(model_id=model_id, config=config):
                    self.assertIn(
                        f"models/MDX_Net_Models/model_data/mdx_c_configs/{config}",
                        contract.evidence.runtime_metadata_sources,
                    )

    def test_exact_reconciliation_preserves_observed_keys_and_fails_raw_on_disagreement(
        self,
    ) -> None:
        registry = load_mdx_runtime_contracts(
            BUNDLED_MDX_RUNTIME_CONTRACT_PATH,
            registry=self.semantic_registry,
        )
        matching = reconcile_mdx_runtime_signature(
            CLASSIC_ID,
            observed_native_stems=("instrumental", "VOCALS"),
            source="installed",
            contracts=registry,
        )
        self.assertTrue(matching.reviewed)
        self.assertEqual(matching.native_signature, ("instrumental", "VOCALS"))
        self.assertEqual(matching.warning, "")

        for observed in (
            (),
            ("Instrumental",),
            ("Instrumental", "Other"),
            ("Instrumental", "Vocals", "Other"),
        ):
            with self.subTest(observed=observed):
                mismatch = reconcile_mdx_runtime_signature(
                    CLASSIC_ID,
                    observed_native_stems=observed,
                    source="installed",
                    contracts=registry,
                )
                self.assertFalse(mismatch.reviewed)
                self.assertEqual(mismatch.native_signature, observed)
                self.assertIn("runtime-contract-mismatch", mismatch.warning)

    def test_every_backend_class_matches_case_insensitively_and_fails_raw(self) -> None:
        registry = load_mdx_runtime_contracts(
            BUNDLED_MDX_RUNTIME_CONTRACT_PATH,
            registry=self.semantic_registry,
        )
        representatives = (
            CLASSIC_ID,
            "mdx:MDX23C-8KFFT-InstVoc_HQ",
            "mdx:melband_roformer_inst_v1",
        )
        for model_id in representatives:
            contract = registry.contracts[model_id]
            config_yaml = contract.config_yamls[0] if contract.config_yamls else ""
            observed = tuple(native.swapcase() for native in reversed(contract.native_signature))
            matching = reconcile_mdx_runtime_signature(
                model_id,
                observed_native_stems=observed,
                config_yaml=config_yaml.swapcase(),
                source="installed",
                contracts=registry,
            )
            with self.subTest(model_id=model_id, case="case-only"):
                self.assertTrue(matching.reviewed)
                self.assertEqual(matching.native_signature, observed)

            disagreements = {
                "missing": (),
                "changed": ("Changed runtime key", *contract.native_signature[1:]),
                "expanded": (*contract.native_signature, "Unexpected runtime key"),
                "collapsed": contract.native_signature[:-1],
            }
            for case, actual in disagreements.items():
                mismatch = reconcile_mdx_runtime_signature(
                    model_id,
                    observed_native_stems=actual,
                    config_yaml=config_yaml,
                    source="installed",
                    contracts=registry,
                )
                with self.subTest(model_id=model_id, case=case):
                    self.assertFalse(mismatch.reviewed)
                    self.assertEqual(mismatch.native_signature, actual)
                    self.assertIn("runtime-contract-mismatch", mismatch.warning)

    def test_catalogue_lookup_is_exact_artifact_id_only_and_config_checked(self) -> None:
        registry = load_mdx_runtime_contracts(
            BUNDLED_MDX_RUNTIME_CONTRACT_PATH,
            registry=self.semantic_registry,
        )
        exact = reconcile_mdx_runtime_signature(
            "mdx:Kim_Inst",
            observed_native_stems=(),
            source="catalogue",
            contracts=registry,
        )
        self.assertTrue(exact.reviewed)
        self.assertEqual(exact.native_signature, ("Instrumental", "Vocals"))

        unknown = reconcile_mdx_runtime_signature(
            "mdx:Kim_Inst_remaster",
            observed_native_stems=("Instrumental",),
            source="catalogue",
            contracts=registry,
        )
        self.assertIsNone(unknown.contract)
        self.assertFalse(unknown.reviewed)
        self.assertEqual(unknown.warning, "")

        target_id = "mdx:melband_roformer_inst_v1"
        accepted = reconcile_mdx_runtime_signature(
            target_id,
            observed_native_stems=("instrumental",),
            config_yaml="CONFIG_MELBANDROFORMER_INST.YAML",
            source="catalogue",
            contracts=registry,
        )
        self.assertTrue(accepted.reviewed)
        rejected = reconcile_mdx_runtime_signature(
            target_id,
            observed_native_stems=("Instrumental",),
            config_yaml="config_melband_roformer_inst.yaml",
            source="catalogue",
            contracts=registry,
        )
        self.assertFalse(rejected.reviewed)
        self.assertIn("config", rejected.warning)

    def test_application_boundary_logs_once_and_installs_empty_supplement(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            malformed = Path(directory) / "contracts.json"
            malformed.write_text('{"schema_version": 0}', encoding="utf-8")
            load_bundled_mdx_runtime_contracts.cache_clear()
            self.addCleanup(load_bundled_mdx_runtime_contracts.cache_clear)
            with (
                mock.patch(
                    "core.mdx_runtime_contract.BUNDLED_MDX_RUNTIME_CONTRACT_PATH", malformed
                ),
                mock.patch("core.mdx_runtime_contract.log_event") as log,
            ):
                first = load_bundled_mdx_runtime_contracts()
                second = load_bundled_mdx_runtime_contracts()
        self.assertIs(first, second)
        self.assertEqual(first.contracts, {})
        self.assertTrue(first.warning)
        log.assert_called_once()

        reconciled = reconcile_mdx_runtime_signature(
            CLASSIC_ID,
            observed_native_stems=("Installed A", "Installed B"),
            source="installed",
            contracts=first,
        )
        self.assertFalse(reconciled.reviewed)
        self.assertEqual(reconciled.native_signature, ("Installed A", "Installed B"))
        self.assertEqual(reconciled.warning, first.warning)

    def test_generator_boundary_marks_unusable_contract_evidence_unavailable(self) -> None:
        from catalogue import collect

        with tempfile.TemporaryDirectory() as directory:
            paths = (
                Path(directory) / "missing.json",
                Path(directory),
                Path(directory) / "malformed.json",
            )
            paths[2].write_text('{"schema_version": 0}', encoding="utf-8")
            for path in paths:
                with (
                    self.subTest(path=path),
                    mock.patch.object(collect, "BUNDLED_MDX_RUNTIME_CONTRACT_PATH", path),
                    mock.patch.object(
                        collect,
                        "_fetch_cached_bytes",
                        return_value=(
                            b"Model Filename  Architecture  Output Stems  Friendly Name\n",
                            "cache",
                        ),
                    ),
                ):
                    context = collect._build_catalogue_context(policy=collect.OFFLINE_FETCH_POLICY)
                self.assertTrue(
                    any(
                        "MDX runtime contract" in item
                        for item in context.unavailable_supplemental_evidence
                    )
                )


if __name__ == "__main__":
    unittest.main()
