"""Strict exact-ID MDX runtime-contract supplement regressions."""

from __future__ import annotations

import json
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
    reconcile_catalogue_mdx_runtime_signature,
    reconcile_mdx_runtime_signature,
)
from core.model_stem_manifest import BUNDLED_MANIFEST_PATH, load_stem_manifest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

CLASSIC_ID = "mdx:UVR_MDXNET_KARA_2"
CLASSIC_DIGEST = "1d64a6d2c30f709b8c9b4ce1366d96ee"
HASH_RECORD_SOURCE = "models/MDX_Net_Models/model_data/model_data.json"
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

EXPECTED_ARTIFACT_DIGESTS = {
    "mdx:Kim_Inst": "b6bccda408a436db8500083ef3491e8b",
    CLASSIC_ID: CLASSIC_DIGEST,
    "mdx:Kim_Vocal_1": "73492b58195c3b52d34590d5474452f6",
    "mdx:Kim_Vocal_2": "970b3f9492014d18fefeedfe4773cb42",
    "mdx:UVR_MDXNET_1_9703": "a3cd63058945e777505c01d2507daf37",
    "mdx:UVR_MDXNET_2_9682": "d94058f8c7f1fae4164868ae8ae66b20",
    "mdx:UVR_MDXNET_3_9662": "d7bff498db9324db933d913388cba6be",
    "mdx:UVR_MDXNET_9482": "0ddfc0eb5792638ad5dc27850236c246",
    "mdx:UVR_MDXNET_KARA": "2f5501189a2f6db6349916fabe8c90de",
    "mdx:Reverb_HQ_By_FoxJoy": "cd5b2989ad863f116c855db1dfe24e39",
    "mdx:UVR-MDX-NET_Crowd_HQ_1": "b02be2d198d4968a121030cf8950b492",
    "mdx:kuielab_a_bass": "6703e39f36f18aa7855ee1047765621d",
    "mdx:kuielab_b_bass": "c3b29bdce8c4fa17ec609e16220330ab",
    "mdx:kuielab_a_drums": "dc41ede5961d50f277eb846db17f5319",
    "mdx:kuielab_b_drums": "4910e7827f335048bdac11fa967772f9",
    "mdx:kuielab_a_other": "26d308f91f3423a67dc69a6d12a8793d",
    "mdx:kuielab_b_other": "65ab5919372a128e4167f5e01a8fda85",
    "mdx:kuielab_a_vocals": "5f6483271e1efb9bfb59e4a3e6d4d098",
    "mdx:kuielab_b_vocals": "6b31de20e84392859a3d09d43f089515",
    "mdx:MDX23C-8KFFT-InstVoc_HQ": "99b6ceaae542265a3b6d657bf9fde79f",
    "mdx:MDX23C-8KFFT-InstVoc_HQ_2": "116f6f9dabb907b53d847ed9f7a9475f",
    "mdx:melband_roformer_instvoc_duality_v1": "3c15abf122d8eccc4a0eb97bf84a3e58",
    "mdx:melband_roformer_instvox_duality_v2": "9fb197af219c5172ea38703a33aceb79",
    "mdx:melband_roformer_inst_v1": "d7a256bee3e7c620f554bceaab2f68f6",
    "mdx:melband_roformer_inst_v2": "951f8ef420a941a395a9919f5d55cce9",
    "mdx:model_bs_roformer_ep_317_sdr_12.9755": "53f707017bfcbb56f5e1bfac420d6732",
    "mdx:model_bs_roformer_ep_368_sdr_12.9628": "d789065adfd747d6f585b27b495bcdae",
    "mdx:model_bs_roformer_ep_937_sdr_10.5309": "e733736763234047587931fc35322fd9",
    "mdx:model_mel_band_roformer_ep_3005_sdr_11.4360": "63e41acc264bf681a73aa9f7e5f606cc",
}

EXPECTED_CONFIG_EVIDENCE = {
    "model_2_stem_full_band_8k.yaml": (
        "451765e869b78dcb9ca9188a74da31f581b7254ff0e8b532aa76b974148de947",
        ("Vocals", "Instrumental"),
        None,
        "models/MDX_Net_Models/model_data/mdx_c_configs/model_2_stem_full_band_8k.yaml",
    ),
    "config_melbandroformer_instvoc_duality.yaml": (
        "62dbc3ecf29c7ac99df35003f8cb72da3348d646cb5e6d50e07323551c3d968f",
        ("Vocals", "Instrumental"),
        None,
        "https://raw.githubusercontent.com/TRvlvr/application_data/main/mdx_model_data/mdx_c_configs/config_melbandroformer_instvoc_duality.yaml",
    ),
    "config_melbandroformer_inst.yaml": (
        "723af6755b5624be0a58351a13c930c472b51ef677cf2c7943394fefed7c3d4d",
        ("Instrumental", "Vocals"),
        "Instrumental",
        "https://raw.githubusercontent.com/TRvlvr/application_data/main/mdx_model_data/mdx_c_configs/config_melbandroformer_inst.yaml",
    ),
    "config_melbandroformer_inst_v2.yaml": (
        "4b902a7360a930c178edb4846b30e4e326aa1219d1b2daf660d46a311e0cd50b",
        ("Instrumental", "Vocals"),
        "Instrumental",
        "https://raw.githubusercontent.com/TRvlvr/application_data/main/mdx_model_data/mdx_c_configs/config_melbandroformer_inst_v2.yaml",
    ),
    "model_bs_roformer_ep_317_sdr_12.9755.yaml": (
        "2bfdd16c656bd9519aba757cc4f8834b7ede675eb1e00ec4772d74ae1c41af7f",
        ("Vocals", "Instrumental"),
        "Vocals",
        "https://raw.githubusercontent.com/TRvlvr/application_data/main/mdx_model_data/mdx_c_configs/model_bs_roformer_ep_317_sdr_12.9755.yaml",
    ),
    "config_bs_roformer_ep_317_sdr_12.9755.yaml": (
        "2bfdd16c656bd9519aba757cc4f8834b7ede675eb1e00ec4772d74ae1c41af7f",
        ("Vocals", "Instrumental"),
        "Vocals",
        "https://raw.githubusercontent.com/TRvlvr/application_data/main/mdx_model_data/mdx_c_configs/model_bs_roformer_ep_317_sdr_12.9755.yaml",
    ),
    "model_bs_roformer_ep_368_sdr_12.9628.yaml": (
        "aea599b3f9bd4892a9c6bf5ac7c44787d3c99f717903d16054702665d477c86b",
        ("Vocals", "Instrumental"),
        "Vocals",
        "https://raw.githubusercontent.com/TRvlvr/application_data/main/mdx_model_data/mdx_c_configs/model_bs_roformer_ep_368_sdr_12.9628.yaml",
    ),
    "config_bs_roformer_ep_368_sdr_12.9628.yaml": (
        "aea599b3f9bd4892a9c6bf5ac7c44787d3c99f717903d16054702665d477c86b",
        ("Vocals", "Instrumental"),
        "Vocals",
        "https://raw.githubusercontent.com/TRvlvr/application_data/main/mdx_model_data/mdx_c_configs/model_bs_roformer_ep_368_sdr_12.9628.yaml",
    ),
    "model_bs_roformer_ep_937_sdr_10.5309.yaml": (
        "302b6cee54adf39743b097b145ad4f64c37f3bd31b84791da32f963fb3692d04",
        ("No Drum-Bass", "Drum-Bass"),
        "No Drum-Bass",
        "https://raw.githubusercontent.com/TRvlvr/application_data/main/mdx_model_data/mdx_c_configs/model_bs_roformer_ep_937_sdr_10.5309.yaml",
    ),
    "model_mel_band_roformer_ep_3005_sdr_11.4360.yaml": (
        "d9b083b48dfdd0bd10f8a29a9c18777b0419496d938827f48a1db31bf0193aa3",
        ("Vocals", "Instrumental"),
        "Vocals",
        "https://raw.githubusercontent.com/TRvlvr/application_data/main/mdx_model_data/mdx_c_configs/model_mel_band_roformer_ep_3005_sdr_11.4360.yaml",
    ),
}


def _evidence() -> dict[str, object]:
    return {
        "artifact_sources": ["https://example.test/UVR_MDXNET_KARA_2.onnx"],
        "runtime_metadata_sources": [HASH_RECORD_SOURCE],
        "review_note": "Exact artifact and checked-in hash metadata reviewed.",
    }


def _contract(
    *,
    backend: str = "classic_onnx",
    signature: list[str] | None = None,
    primary: str = "Instrumental",
    configs: list[str] | None = None,
) -> dict[str, object]:
    config_names = [] if configs is None else configs
    resolved_signature = signature or ["Instrumental", "Vocals"]
    return {
        "backend": backend,
        "native_signature": resolved_signature,
        "primary_native": primary,
        "config_yamls": config_names,
        "artifact_evidence": [
            {
                "uvr_md5": CLASSIC_DIGEST,
                "hash_record_source": HASH_RECORD_SOURCE,
            }
        ],
        "config_evidence": {
            config: {
                "training_instruments": resolved_signature,
                "target_instrument": primary if backend == "mdx_c_target" else None,
                "content_sha256": "a" * 64,
                "sources": [f"https://example.test/{config}"],
            }
            for config in config_names
        },
        "evidence": _evidence(),
    }


def _document() -> dict[str, object]:
    return {"schema_version": 2, "contracts": {CLASSIC_ID: _contract()}}


class _ContractTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.semantic_registry = load_stem_manifest(BUNDLED_MANIFEST_PATH)

    def load(self, document: object):
        return load_mdx_runtime_contract_document(document, registry=self.semantic_registry)


class MdxRuntimeContractValidationTests(_ContractTestCase):
    def test_schema_one_is_rejected_without_migration(self) -> None:
        document = _document()
        document["schema_version"] = 1
        with self.assertRaisesRegex(
            MdxRuntimeContractError,
            "schema 1 migration is not supported",
        ):
            self.load(document)

    def test_schema_version_is_exact_integer_two(self) -> None:
        for invalid in (True, False, 2.0, "2", 0, 3):
            with self.subTest(invalid=invalid):
                document = _document()
                document["schema_version"] = invalid
                with self.assertRaisesRegex(Exception, "exact integer 2"):
                    self.load(document)

    def test_duplicate_json_keys_are_rejected_at_root_and_nested_levels(self) -> None:
        texts = (
            '{"schema_version":2,"schema_version":2,"contracts":{}}',
            '{"schema_version":2,"contracts":{"mdx:x":{"backend":"classic_onnx",'
            '"backend":"classic_onnx"}}}',
            '{"schema_version":2,"contracts":{"mdx:x":{"evidence":{'
            '"review_note":"a","review_note":"b"}}}}',
        )
        for text in texts:
            with self.subTest(text=text), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "contracts.json"
                path.write_text(text, encoding="utf-8")
                with self.assertRaisesRegex(Exception, "duplicate key"):
                    load_mdx_runtime_contracts(path, registry=self.semantic_registry)

    def test_unified_manifest_failure_is_wrapped_as_contract_error(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            malformed_manifest = Path(directory) / "manifest.json"
            malformed_manifest.write_text("{}", encoding="utf-8")
            with self.assertRaisesRegex(MdxRuntimeContractError, "author_aliases"):
                load_mdx_runtime_contracts(malformed_manifest)

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
        artifact_evidence = _document()
        contracts = artifact_evidence["contracts"]
        assert isinstance(contracts, dict)
        value = contracts[CLASSIC_ID]
        assert isinstance(value, dict)
        artifacts = value["artifact_evidence"]
        assert isinstance(artifacts, list)
        assert isinstance(artifacts[0], dict)
        artifacts[0]["extra"] = True
        cases.append(("artifact evidence", artifact_evidence))
        config_evidence = _document()
        contracts = config_evidence["contracts"]
        assert isinstance(contracts, dict)
        value = _contract(
            backend="mdx_c_target",
            signature=["Instrumental"],
            primary="Instrumental",
            configs=["config.yaml"],
        )
        raw_configs = value["config_evidence"]
        assert isinstance(raw_configs, dict)
        config = raw_configs["config.yaml"]
        assert isinstance(config, dict)
        config["extra"] = True
        contracts[CLASSIC_ID] = value
        cases.append(("config evidence", config_evidence))

        for name, document in cases:
            with self.subTest(name=name), self.assertRaisesRegex(Exception, "unknown field"):
                self.load(document)

    def test_missing_local_runtime_evidence_source_is_rejected(self) -> None:
        document = _document()
        contracts = document["contracts"]
        assert isinstance(contracts, dict)
        value = contracts[CLASSIC_ID]
        assert isinstance(value, dict)
        evidence = value["evidence"]
        assert isinstance(evidence, dict)
        evidence["runtime_metadata_sources"] = [
            "models/MDX_Net_Models/model_data/absent-runtime-evidence.yaml"
        ]

        with self.assertRaisesRegex(MdxRuntimeContractError, "does not exist"):
            self.load(document)

    def test_missing_local_config_evidence_source_is_rejected(self) -> None:
        document = _document()
        contracts = document["contracts"]
        assert isinstance(contracts, dict)
        value = _contract(
            backend="mdx_c_target",
            signature=["Instrumental"],
            primary="Instrumental",
            configs=["config.yaml"],
        )
        raw_configs = value["config_evidence"]
        assert isinstance(raw_configs, dict)
        config = raw_configs["config.yaml"]
        assert isinstance(config, dict)
        config["sources"] = ["models/absent-runtime-config.yaml"]
        contracts[CLASSIC_ID] = value

        with self.assertRaisesRegex(MdxRuntimeContractError, "does not exist"):
            self.load(document)

    def test_digests_and_exact_public_artifact_association_are_required(self) -> None:
        mutations = (
            (
                "artifact digest",
                lambda value: value["artifact_evidence"][0].__setitem__(  # type: ignore[index,union-attr]
                    "uvr_md5", "A" * 32
                ),
                "lowercase UVR MD5",
            ),
            (
                "artifact URL",
                lambda value: value["evidence"].__setitem__(  # type: ignore[union-attr]
                    "artifact_sources", ["https://example.test/not-the-model.onnx"]
                ),
                "exact public artifact",
            ),
        )
        for name, mutate, message in mutations:
            document = _document()
            contracts = document["contracts"]
            assert isinstance(contracts, dict)
            value = contracts[CLASSIC_ID]
            assert isinstance(value, dict)
            mutate(value)
            with (
                self.subTest(name=name),
                self.assertRaisesRegex(
                    MdxRuntimeContractError,
                    message,
                ),
            ):
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
    def test_checked_in_config_content_and_semantics_are_revalidated(self) -> None:
        from core.model_manifest import load_model_manifest_document

        document = json.loads(BUNDLED_MDX_RUNTIME_CONTRACT_PATH.read_text(encoding="utf-8"))
        config = document["models"]["mdx:MDX23C-8KFFT-InstVoc_HQ"]["config_evidence"][
            "model_2_stem_full_band_8k.yaml"
        ]
        config["content_sha256"] = "a" * 64

        with self.assertRaisesRegex(ValueError, "local source bytes"):
            load_model_manifest_document(document)

    def test_bundled_local_evidence_sources_exist_in_a_fresh_checkout(self) -> None:
        document = json.loads(BUNDLED_MDX_RUNTIME_CONTRACT_PATH.read_text(encoding="utf-8"))
        for model_id, model in document["models"].items():
            contract = model.get("runtime_contract")
            if contract is None:
                continue
            sources = list(contract["evidence"]["runtime_metadata_sources"])
            for config in model.get("config_evidence", {}).values():
                sources.extend(config["sources"])
            for source in sources:
                if source.startswith(("https://", "cache:", "checked-in:")):
                    continue
                with self.subTest(model_id=model_id, source=source):
                    self.assertTrue((Path(ROOT) / source).is_file())

    def test_target_contract_rejects_training_instrument_drift_with_same_target(self) -> None:
        registry = load_mdx_runtime_contracts(
            BUNDLED_MDX_RUNTIME_CONTRACT_PATH,
            registry=self.semantic_registry,
        )
        reconciled = reconcile_catalogue_mdx_runtime_signature(
            "mdx:melband_roformer_inst_v1",
            ("Instrumental", "Changed complement"),
            target_instrument="Instrumental",
            config_yaml="config_melbandroformer_inst.yaml",
            config_sha256="723af6755b5624be0a58351a13c930c472b51ef677cf2c7943394fefed7c3d4d",
            metadata_source="remote_yaml:config_melbandroformer_inst.yaml",
            contracts=registry,
        )

        self.assertFalse(reconciled.reviewed)
        self.assertEqual(reconciled.native_signature, ("Instrumental",))
        self.assertIn("training.instruments", reconciled.warning)

    def test_target_contract_requires_exact_content_order_and_target(self) -> None:
        registry = load_mdx_runtime_contracts(
            BUNDLED_MDX_RUNTIME_CONTRACT_PATH,
            registry=self.semantic_registry,
        )
        cases = (
            (
                "content",
                "a" * 64,
                ("Instrumental", "Vocals"),
                "Instrumental",
                "content SHA-256",
            ),
            (
                "order",
                "723af6755b5624be0a58351a13c930c472b51ef677cf2c7943394fefed7c3d4d",
                ("Vocals", "Instrumental"),
                "Instrumental",
                "training.instruments",
            ),
            (
                "target",
                "723af6755b5624be0a58351a13c930c472b51ef677cf2c7943394fefed7c3d4d",
                ("Instrumental", "Vocals"),
                "Vocals",
                "target_instrument",
            ),
        )
        for name, digest, instruments, target, warning in cases:
            with self.subTest(name=name):
                reconciled = reconcile_catalogue_mdx_runtime_signature(
                    "mdx:melband_roformer_inst_v1",
                    instruments,
                    target_instrument=target,
                    config_yaml="config_melbandroformer_inst.yaml",
                    config_sha256=digest,
                    metadata_source="remote_yaml:config_melbandroformer_inst.yaml",
                    contracts=registry,
                )
                self.assertFalse(reconciled.reviewed)
                self.assertEqual(reconciled.native_signature, (target,))
                self.assertIn(warning, reconciled.warning)

    def test_installed_classic_requires_reviewed_digest_and_hash_record(self) -> None:
        registry = load_mdx_runtime_contracts(
            BUNDLED_MDX_RUNTIME_CONTRACT_PATH,
            registry=self.semantic_registry,
        )
        reconciled = reconcile_mdx_runtime_signature(
            "mdx:Kim_Inst",
            observed_native_stems=("Instrumental", "Vocals"),
            observed_primary_native="Instrumental",
            source="installed",
            contracts=registry,
        )

        self.assertFalse(reconciled.reviewed)
        self.assertEqual(reconciled.native_signature, ("Instrumental", "Vocals"))
        self.assertIn("artifact digest", reconciled.warning)

        observed = ("INSTALLED INSTRUMENTAL", "INSTALLED VOCALS")
        for name, digest, source, warning in (
            ("wrong digest", "f" * 32, HASH_RECORD_SOURCE, "artifact digest"),
            ("wrong provenance", "b6bccda408a436db8500083ef3491e8b", "", "hash-record"),
        ):
            with self.subTest(name=name):
                mismatch = reconcile_mdx_runtime_signature(
                    "mdx:Kim_Inst",
                    observed_native_stems=observed,
                    observed_primary_native=observed[0],
                    artifact_digest=digest,
                    hash_record_source=source,
                    source="installed",
                    contracts=registry,
                )
                self.assertFalse(mismatch.reviewed)
                self.assertFalse(mismatch.artifact_digest_verified)
                self.assertEqual(mismatch.native_signature, observed)
                self.assertIn(warning, mismatch.warning)

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
            {
                model_id: tuple(item.uvr_md5 for item in contract.artifact_evidence)
                for model_id, contract in registry.contracts.items()
            },
            {model_id: (digest,) for model_id, digest in EXPECTED_ARTIFACT_DIGESTS.items()},
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
                    evidence = contract.config_evidence[config]
                    expected_sha, expected_instruments, expected_target, expected_source = (
                        EXPECTED_CONFIG_EVIDENCE[config]
                    )
                    self.assertEqual(
                        (
                            evidence.content_sha256,
                            evidence.training_instruments,
                            evidence.target_instrument,
                            evidence.sources,
                        ),
                        (
                            expected_sha,
                            expected_instruments,
                            expected_target,
                            (expected_source,),
                        ),
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
            artifact_digest=CLASSIC_DIGEST,
            hash_record_source=HASH_RECORD_SOURCE,
            source="installed",
            contracts=registry,
        )
        self.assertTrue(matching.reviewed)
        self.assertEqual(matching.native_signature, ("instrumental", "VOCALS"))
        self.assertEqual(matching.warning, "")
        self.assertTrue(matching.artifact_digest_verified)

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
                    artifact_digest=CLASSIC_DIGEST,
                    hash_record_source=HASH_RECORD_SOURCE,
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
            config_evidence = contract.config_evidence.get(config_yaml)
            artifact = contract.artifact_evidence[0]
            observed = tuple(native.swapcase() for native in reversed(contract.native_signature))
            matching = reconcile_mdx_runtime_signature(
                model_id,
                observed_native_stems=observed,
                config_yaml=config_yaml.swapcase(),
                config_sha256=(config_evidence.content_sha256 if config_evidence else ""),
                training_instruments=(
                    config_evidence.training_instruments if config_evidence else ()
                ),
                target_instrument=(
                    config_evidence.target_instrument
                    if config_evidence and config_evidence.target_instrument
                    else ""
                ),
                artifact_digest=artifact.uvr_md5,
                hash_record_source=artifact.hash_record_source,
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
                    config_sha256=(config_evidence.content_sha256 if config_evidence else ""),
                    training_instruments=(
                        config_evidence.training_instruments if config_evidence else ()
                    ),
                    target_instrument=(
                        config_evidence.target_instrument
                        if config_evidence and config_evidence.target_instrument
                        else ""
                    ),
                    artifact_digest=artifact.uvr_md5,
                    hash_record_source=artifact.hash_record_source,
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
        self.assertFalse(exact.artifact_digest_verified)

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
            config_sha256="723af6755b5624be0a58351a13c930c472b51ef677cf2c7943394fefed7c3d4d",
            training_instruments=("Instrumental", "Vocals"),
            target_instrument="Instrumental",
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


class CurrentCatalogueTargetRuntimeTests(unittest.TestCase):
    def test_invert_clean_training_other_is_not_a_native_runtime_output(self) -> None:
        from core.model_manifest.runtime import bundled_catalogue_config_evidence

        model_id = "mdx:mbr_invert_clean_becruily"
        config_yaml = "mbr_invert_clean_becruily_config.yaml"
        evidence = bundled_catalogue_config_evidence(model_id, config_yaml)
        self.assertIsNotNone(evidence)
        assert evidence is not None
        self.assertEqual(evidence.training_instruments, ("Vocals", "Other"))
        self.assertEqual(evidence.target_instrument, "Vocals")

        projected = reconcile_catalogue_mdx_runtime_signature(
            model_id,
            evidence.training_instruments,
            target_instrument=evidence.target_instrument or "",
            config_yaml=config_yaml,
            config_sha256=evidence.content_sha256,
        )
        self.assertIsNone(projected.contract)
        self.assertEqual(projected.native_signature, ("Vocals",))
        self.assertNotIn("Other", projected.native_signature)


if __name__ == "__main__":
    unittest.main()
