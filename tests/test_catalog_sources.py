"""The single merge path shared by Download Center and the runtime pickers."""

import json
import os
import typing
import unittest
import unittest.mock
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

from bundled.constants import DEMUCS_ARCH_TYPE, MDX_ARCH_TYPE, VR_ARCH_TYPE
from core import catalog_sources
from core.catalogue_identity import catalogue_model_id
from core.catalogue_types import CatalogueEvidenceState
from core.mdx_runtime_contract import MdxConfigEvidence
from core.stem_roles import StemReviewStatus

#: ``_supplemental_sources`` takes no arguments and returns supplements only,
#: so patching it leaves the real base merge under test.
_NO_SUPPLEMENTS = ({}, {}, {}, {})

_BECRUILY_SOURCE_DELTA_FIXTURE = (
    Path(__file__).parent / "fixtures" / "catalogue" / "becruily_source_delta.json"
)

# Merges still see curated Apollo YAML URLs; keep the stem-cache worker off
# unless a test is specifically about it (see test_catalog_stem_merge).
_STEM_CACHE_OFF = unittest.mock.patch.dict(
    os.environ, {"UVR_DISABLE_CATALOGUE_STEMS": "1"}, clear=False
)


def _with_supplements(supplements: typing.Any) -> typing.Any:
    return unittest.mock.patch.object(
        catalog_sources, "_supplemental_sources", return_value=supplements
    )


@_STEM_CACHE_OFF
class MergeOrderTests(unittest.TestCase):
    def setUp(self) -> None:
        catalog_sources.invalidate_catalogue_merge()

    def test_upstream_label_is_never_overwritten(self) -> None:
        with _with_supplements(({}, {"Shared": {"other.ckpt": "u2"}}, {}, {})):
            merged = catalog_sources.merged_catalogues(
                vr={}, mdx={"Shared": {"first.ckpt": "u1"}}, demucs={}
            )
        self.assertEqual(merged.mdx["Shared"], {"first.ckpt": "u1"})

    def test_supplemental_entries_are_added(self) -> None:
        with _with_supplements(({}, {"New": {"new.ckpt": "u2"}}, {}, {})):
            merged = catalog_sources.merged_catalogues(vr={}, mdx={}, demucs={})
        self.assertIn("New", merged.mdx)

    def test_base_and_supplement_both_survive(self) -> None:
        with _with_supplements(({}, {"FromSupplement": {"b.ckpt": "u"}}, {}, {})):
            merged = catalog_sources.merged_catalogues(
                vr={}, mdx={"FromBase": {"a.ckpt": "u"}}, demucs={}
            )
        self.assertEqual(set(merged.mdx), {"FromBase", "FromSupplement"})

    def test_vr_and_demucs_merge_independently(self) -> None:
        with _with_supplements(({"V": "v.pth"}, {}, {"D": {"d.yaml": "u"}}, {})):
            merged = catalog_sources.merged_catalogues(vr={}, mdx={}, demucs={})
        self.assertIn("V", merged.vr)
        self.assertIn("D", merged.demucs)


@_STEM_CACHE_OFF
class EntryMetaTests(unittest.TestCase):
    def setUp(self) -> None:
        catalog_sources.invalidate_catalogue_merge()

    def test_meta_carries_canonical_display_and_checkpoint(self) -> None:
        with _with_supplements(_NO_SUPPLEMENTS):
            merged = catalog_sources.merged_catalogues(
                vr={},
                mdx={
                    "Roformer Model: Mel-Band Roformer | Inst v2 by Unwa": {
                        "mbr_inst2_unwa.ckpt": "u",
                        "mbr_inst2_unwa.yaml": "c",
                    }
                },
                demucs={},
            )
        meta = merged.meta["Roformer Model: Mel-Band Roformer | Inst v2 by Unwa"]
        self.assertEqual(meta.display, "MelBand Roformer — Inst v2 · Unwa")
        self.assertEqual(meta.checkpoint, "mbr_inst2_unwa.ckpt")
        self.assertEqual(meta.files["mbr_inst2_unwa.yaml"], "c")

    def test_mvsepless_metadata_reaches_meta(self) -> None:
        with _with_supplements(
            (
                {},
                {"M": {"m.ckpt": "u", "m.yaml": "c"}},
                {},
                {
                    "M": {
                        "stems": ["Vocals", "other"],
                        "target_instrument": "Vocals",
                        "intent": "vocals",
                    }
                },
            )
        ):
            merged = catalog_sources.merged_catalogues(vr={}, mdx={}, demucs={})
        meta = merged.meta["M"]
        self.assertEqual(meta.stems, ["Vocals", "other"])
        self.assertEqual(meta.target_instrument, "Vocals")

    def test_normalized_alias_metadata_enriches_retained_source(self) -> None:
        retained = "Roformer Model: MelBand Roformer | Vocals by Someone"
        alias = "Mel-Band Roformer Vocals by Someone"
        with _with_supplements(
            (
                {},
                {alias: {"alias.ckpt": "https://x/alias.ckpt"}},
                {},
                {
                    alias: {
                        "stems": ["vocals", "other"],
                        "target_instrument": "vocals",
                        "intent": "vocals",
                    }
                },
            )
        ):
            merged = catalog_sources.merged_catalogues(
                vr={},
                mdx={retained: {"retained.ckpt": "https://x/retained.ckpt"}},
                demucs={},
            )

        self.assertIn(retained, merged.mdx)
        self.assertNotIn(alias, merged.mdx)
        self.assertEqual(merged.meta[retained].stems, ["vocals", "other"])
        self.assertEqual(merged.meta[retained].intent, "vocals")

    def test_entry_without_mvsepless_metadata_still_gets_meta(self) -> None:
        with _with_supplements(_NO_SUPPLEMENTS):
            merged = catalog_sources.merged_catalogues(
                vr={}, mdx={"Plain": {"p.ckpt": "u"}}, demucs={}
            )
        meta = merged.meta["Plain"]
        self.assertEqual(meta.stems, [])
        self.assertIsNone(meta.target_instrument)

    def test_vr_plain_string_value_becomes_a_files_map(self) -> None:
        # VR catalogue entries are bare filenames, not {file: url} dicts.
        with _with_supplements(_NO_SUPPLEMENTS):
            merged = catalog_sources.merged_catalogues(
                vr={"VR Arch Single Model v5: 1_HP-UVR": "1_HP-UVR.pth"}, mdx={}, demucs={}
            )
        meta = merged.meta["VR Arch Single Model v5: 1_HP-UVR"]
        self.assertEqual(meta.checkpoint, "1_HP-UVR.pth")

    def test_meta_covers_every_arch(self) -> None:
        with _with_supplements(_NO_SUPPLEMENTS):
            merged = catalog_sources.merged_catalogues(
                vr={"V": "v.pth"}, mdx={"M": {"m.ckpt": "u"}}, demucs={"D": {"d.yaml": "u"}}
            )
        for label in ("V", "M", "D"):
            with self.subTest(label=label):
                self.assertIn(label, merged.meta)

    def test_evidence_state_is_independent_from_review_status_and_identity(self) -> None:
        values = tuple(state.value for state in CatalogueEvidenceState)
        self.assertEqual(
            values,
            ("ready", "pending", "unavailable", "stale", "not_applicable"),
        )
        self.assertTrue(set(values).isdisjoint(status.value for status in StemReviewStatus))

        meta = catalog_sources.EntryMeta(
            label="VR Arch Single Model v5: UVR-BVE-4B_SN-44100-1",
            display="BVE",
            arch=VR_ARCH_TYPE,
            files={"UVR-BVE-4B_SN-44100-1.pth": ""},
            checkpoint="UVR-BVE-4B_SN-44100-1.pth",
        )
        before = catalogue_model_id("vr", meta.label, meta.files, meta)
        changed = replace(
            meta,
            catalogue_evidence_status=CatalogueEvidenceState.STALE,
            catalogue_evidence_warning="temporary validation failure",
        )

        self.assertEqual(meta.catalogue_evidence_status, CatalogueEvidenceState.UNAVAILABLE)
        self.assertEqual(changed.stem_semantics, meta.stem_semantics)
        self.assertEqual(catalogue_model_id("vr", changed.label, changed.files, changed), before)

    def test_entry_meta_keeps_the_existing_positional_stem_projection_slot(self) -> None:
        projection = catalog_sources.EntryMeta("", "", "").stem_semantics
        meta = catalog_sources.EntryMeta(
            "M",
            "M",
            MDX_ARCH_TYPE,
            {},
            None,
            [],
            None,
            "",
            "unknown",
            "unknown",
            projection,
        )

        self.assertIs(meta.stem_semantics, projection)
        self.assertEqual(meta.catalogue_evidence_status, CatalogueEvidenceState.UNAVAILABLE)


@_STEM_CACHE_OFF
class ExactEvidencePrecedenceTests(unittest.TestCase):
    def setUp(self) -> None:
        catalog_sources.invalidate_catalogue_merge()

    def test_bundled_exact_configs_beat_lower_authority_summary_metadata(self) -> None:
        fixtures = (
            (
                "mdx:mbr_guitar_becruily",
                "Mel-Band Roformer Instrumental by Becruily [mbr_guitar_becruily]",
                "mbr_guitar_becruily.ckpt",
                "mbr_guitar_becruily_config.yaml",
                ["Instrumental", "Vocals"],
                "Instrumental",
                ["Guitar", "Other"],
                "Guitar",
                (("Guitar", "instrument.guitar"), (None, "instrument.guitar.removed")),
            ),
            (
                "mdx:mel_band_roformer_karaoke_aufr33_viperx_sdr_10.1956",
                "Roformer Model: MelBand Roformer | Karaoke by Aufr33 & Viperx",
                "mel_band_roformer_karaoke_aufr33_viperx_sdr_10.1956.ckpt",
                "config_melband_roformer_karaoke_aufr33_viperx_sdr_10.1956.yaml",
                ["karaoke", "other"],
                "other",
                ["Vocals", "Instrumental"],
                "Vocals",
                (
                    ("Vocals", "vocal.lead"),
                    (None, "mix.instrumental_with_backing_vocals"),
                ),
            ),
            (
                "mdx:dereverb-echo_mel_band_roformer_sdr_10.0169",
                "Roformer Model: MelBand Roformer | DeReverb-Echo by Sucial",
                "dereverb-echo_mel_band_roformer_sdr_10.0169.ckpt",
                "config_melband_roformer_dereverb-echo.yaml",
                ["dry", "other"],
                None,
                ["dry", "No dry"],
                None,
                (("dry", "effect.reverb_echo.removed"), ("No dry", "effect.reverb_echo")),
            ),
        )
        for (
            model_id,
            label,
            checkpoint,
            config,
            summary_stems,
            summary_target,
            expected_stems,
            expected_target,
            expected_routes,
        ) in fixtures:
            with self.subTest(model_id=model_id):
                evidence = MdxConfigEvidence(
                    training_instruments=tuple(expected_stems),
                    target_instrument=expected_target,
                    content_sha256="a" * 64,
                    sources=(f"fixture:{config}",),
                )

                def exact_evidence(
                    requested_model_id: str,
                    requested_config: str,
                    *,
                    expected_model_id: str = model_id,
                    expected_config: str = config,
                    expected_evidence: MdxConfigEvidence = evidence,
                ) -> MdxConfigEvidence | None:
                    if (
                        requested_model_id == expected_model_id
                        and requested_config.casefold() == expected_config.casefold()
                    ):
                        return expected_evidence
                    return None

                with unittest.mock.patch(
                    "core.model_manifest.runtime.bundled_catalogue_config_evidence",
                    side_effect=exact_evidence,
                ):
                    meta = catalog_sources._build_meta(
                        {
                            label: {
                                checkpoint: f"https://example.test/{checkpoint}",
                                config: f"https://example.test/{config}",
                            }
                        },
                        MDX_ARCH_TYPE,
                        {
                            label: {
                                "stems": summary_stems,
                                "target_instrument": summary_target,
                                "intent": "instrumental",
                            }
                        },
                        {},
                    )[label]

                self.assertEqual(meta.stems, expected_stems)
                self.assertEqual(meta.target_instrument, expected_target)
                self.assertEqual(meta.stem_semantics.status, StemReviewStatus.REVIEWED.value)
                self.assertEqual(meta.catalogue_evidence_status, CatalogueEvidenceState.READY)
                self.assertEqual(
                    tuple((route.native, route.role) for route in meta.stem_semantics.routes),
                    expected_routes,
                )

    def test_unified_non_config_records_drive_runtime_download_and_generator_signatures(
        self,
    ) -> None:
        from scripts.catalogue.collect import reviewed_stem_signature

        fixtures = (
            (
                "demucs:htdemucs_6s",
                "Demucs v4: htdemucs_6s",
                {
                    "5c90dfd2-34c22ccb.th": "https://example.test/weights.th",
                    "htdemucs_6s.yaml": "https://example.test/htdemucs_6s.yaml",
                },
                DEMUCS_ARCH_TYPE,
                ("drums", "bass", "other", "vocals", "guitar", "piano"),
            ),
            (
                "vr:UVR-BVE-4B_SN-44100-1",
                "VR Arch Single Model v5: UVR-BVE-4B_SN-44100-1",
                "UVR-BVE-4B_SN-44100-1.pth",
                VR_ARCH_TYPE,
                ("Vocals", "Instrumental"),
            ),
        )
        for model_id, label, raw, arch, expected in fixtures:
            with self.subTest(model_id=model_id):
                meta = catalog_sources._build_meta({label: raw}, arch, {}, {})[label]
                download_signature = tuple(
                    route.native for route in meta.stem_semantics.routes if route.native is not None
                )
                self.assertEqual(download_signature, expected)
                self.assertEqual(reviewed_stem_signature(model_id, ()), expected)
                self.assertEqual(meta.catalogue_evidence_status, CatalogueEvidenceState.READY)

    def test_demucs_model_yaml_is_not_misclassified_as_live_mdx_config_evidence(self) -> None:
        from core.catalogue_stem_cache import StemCacheHit

        label = "Demucs v4: htdemucs_6s"
        files = {
            "5c90dfd2-34c22ccb.th": "https://example.test/weights.th",
            "htdemucs_6s.yaml": "https://example.test/htdemucs_6s.yaml",
        }
        misleading = StemCacheHit(
            stems=("Wrong",),
            target_instrument="Wrong",
            ok=True,
            content_sha256="f" * 64,
        )
        with unittest.mock.patch("core.catalogue_stem_cache.lookup_stems", return_value=misleading):
            meta = catalog_sources._build_meta({label: files}, DEMUCS_ARCH_TYPE, {}, {})[label]

        self.assertEqual(meta.catalogue_evidence_status, CatalogueEvidenceState.READY)
        self.assertEqual(
            tuple(route.native for route in meta.stem_semantics.routes),
            ("drums", "bass", "other", "vocals", "guitar", "piano"),
        )

    def test_apollo_stem_waiver_is_not_applicable_not_unavailable(self) -> None:
        from core.extra_catalog import apollo_download_list

        label, raw = next(iter(apollo_download_list().items()))
        meta = catalog_sources._build_meta({label: raw}, "Apollo", {}, {})[label]

        self.assertEqual(meta.stem_semantics.status, StemReviewStatus.WAIVED.value)
        self.assertEqual(
            meta.catalogue_evidence_status,
            CatalogueEvidenceState.NOT_APPLICABLE,
        )
        self.assertFalse(catalog_sources._needs_catalogue_config_evidence(meta))


@_STEM_CACHE_OFF
class CatalogueIntentOverlayTests(unittest.TestCase):
    def setUp(self) -> None:
        catalog_sources.invalidate_catalogue_merge()

    def test_yaml_fields_beat_scratch_category(self) -> None:
        with _with_supplements(
            (
                {},
                {"BGM": {"m.ckpt": "u"}},
                {},
                {
                    "BGM": {
                        "stems": ["vocals", "other"],
                        "target_instrument": "vocals",
                        "intent": "specialty_stem",
                    }
                },
            )
        ):
            merged = catalog_sources.merged_catalogues(vr={}, mdx={}, demucs={})
        self.assertEqual(merged.meta["BGM"].intent, "vocals")

    def test_category_fills_when_fields_are_unknown(self) -> None:
        with _with_supplements(
            (
                {},
                {"Wind": {"w.ckpt": "u"}},
                {},
                {"Wind": {"stems": [], "intent": "specialty_stem"}},
            )
        ):
            merged = catalog_sources.merged_catalogues(vr={}, mdx={}, demucs={})
        self.assertEqual(merged.meta["Wind"].intent, "specialty_stem")

    def test_exact_manifest_intent_overrides_guessed_catalogue_intent(self) -> None:
        """A reviewed identity wins presentation without rewriting audit evidence."""
        label = "Deliberately misleading catalogue label"
        with _with_supplements(
            (
                {},
                {
                    label: {
                        "bs_neo_inst_beta.ckpt": "https://example.test/model.ckpt",
                        "bs_neo_inst_beta_config.yaml": "https://example.test/model.yaml",
                    }
                },
                {},
                {
                    label: {
                        # Training inventory retains the complement even though
                        # target_instrument makes the runtime emit only other.
                        "stems": ["vocals", "other"],
                        "primary_stem": "other",
                        "target_instrument": "other",
                        "intent": "special_fx",
                    }
                },
            )
        ):
            merged = catalog_sources.merged_catalogues(vr={}, mdx={}, demucs={})

        meta = merged.meta[label]
        self.assertEqual(meta.intent, "instrumental")
        self.assertEqual(meta.guessed_intent, "instrumental")
        self.assertEqual(meta.stem_semantics.status, "reviewed")
        self.assertEqual(meta.stem_semantics.logical_primary_role, "mix.instrumental")
        self.assertEqual(meta.stem_semantics.canonical_roles, ("vocal.vocals", "mix.instrumental"))
        self.assertIsNone(meta.stem_semantics.routes[0].native)
        self.assertEqual(meta.stem_semantics.routes[0].display, "Vocals")
        self.assertEqual(meta.stem_semantics.routes[0].production, "derived")
        self.assertEqual(meta.stem_semantics.routes[0].complement_of, "mix.instrumental")
        self.assertTrue(meta.stem_semantics.routes[1].logical_primary)
        self.assertIn("catalogue_id=mdx:bs_neo_inst_beta", meta.stem_semantics.evidence)

    def test_exact_reviewed_vocal_models_do_not_depend_on_two_stem_guessing(self) -> None:
        labels = {
            "VR Arch Single Model v5: 3_HP-Vocal-UVR": "3_HP-Vocal-UVR.pth",
            "VR Arch Single Model v5: 4_HP-Vocal-UVR": "4_HP-Vocal-UVR.pth",
        }
        mdx_label = "MDX23 Model: MDX23C_D1581"
        metadata = {
            label: {
                "stems": ["Instrumental", "Vocals"],
                "primary_stem": "Vocals",
                "intent": "vocals",
            }
            for label in (*labels, mdx_label)
        }
        with _with_supplements(({}, {}, {}, metadata)):
            merged = catalog_sources.merged_catalogues(
                vr=labels,
                mdx={mdx_label: {"MDX23C_D1581.ckpt": "https://example.test/model.ckpt"}},
                demucs={},
            )

        for label in (*labels, mdx_label):
            with self.subTest(label=label):
                projection = merged.meta[label].stem_semantics
                self.assertEqual(projection.status, "reviewed")
                self.assertEqual(merged.meta[label].intent, "vocals")
                self.assertEqual(projection.logical_primary_role, "vocal.vocals")
                self.assertEqual(
                    projection.canonical_roles,
                    ("mix.instrumental", "vocal.vocals"),
                )

    def test_classic_karaoke_2_uses_exact_runtime_sources_for_semantics(self) -> None:
        label = "MDX-Net Model: UVR-MDX-NET Karaoke 2"
        with _with_supplements(
            (
                {},
                {label: {"UVR_MDXNET_KARA_2.onnx": "https://example.test/model.onnx"}},
                {},
                {
                    label: {
                        "stems": ["other", "vocals"],
                        "primary_stem": "Instrumental",
                        "target_instrument": "other",
                        "intent": "karaoke",
                    }
                },
            )
        ):
            merged = catalog_sources.merged_catalogues(vr={}, mdx={}, demucs={})

        meta = merged.meta[label]
        self.assertEqual(meta.stems, ["Instrumental", "Vocals"])
        self.assertEqual(meta.stem_semantics.status, "reviewed")
        self.assertEqual(
            [(route.native, route.role) for route in meta.stem_semantics.routes],
            [
                ("Instrumental", "mix.instrumental_with_backing_vocals"),
                ("Vocals", "vocal.lead"),
            ],
        )

    def test_exact_runtime_contract_promotes_missing_catalogue_inventory(self) -> None:
        label = "Known waived metadata-only model"
        with _with_supplements(
            (
                {},
                {label: {"Kim_Inst.onnx": "https://example.test/Kim_Inst.onnx"}},
                {},
                {label: {"primary_stem": "Instrumental", "intent": "vocals"}},
            )
        ):
            merged = catalog_sources.merged_catalogues(vr={}, mdx={}, demucs={})

        meta = merged.meta[label]
        self.assertEqual(meta.stem_semantics.status, "reviewed")
        self.assertEqual(meta.stem_semantics.logical_primary_role, "mix.instrumental")
        self.assertEqual(
            [(route.native, route.role) for route in meta.stem_semantics.routes],
            [
                ("Instrumental", "mix.instrumental"),
                ("Vocals", "vocal.vocals"),
            ],
        )
        self.assertIn("runtime_contract=model_manifest.json", meta.stem_semantics.evidence)

    def test_runtime_contract_warning_fails_live_projection_raw(self) -> None:
        from core.mdx_runtime_contract import ReconciledMdxRuntimeSignature

        label = "Exact artifact with unavailable runtime contract"
        with (
            _with_supplements(
                (
                    {},
                    {label: {"Kim_Inst.onnx": "https://example.test/Kim_Inst.onnx"}},
                    {},
                    {label: {"primary_stem": "Instrumental"}},
                )
            ),
            unittest.mock.patch.object(
                catalog_sources,
                "reconcile_catalogue_mdx_runtime_signature",
                return_value=ReconciledMdxRuntimeSignature(
                    ("Installed key",),
                    None,
                    False,
                    "runtime-contract-unavailable error=test",
                ),
            ),
        ):
            merged = catalog_sources.merged_catalogues(vr={}, mdx={}, demucs={})

        projection = merged.meta[label].stem_semantics
        self.assertEqual(projection.status, "raw")
        self.assertEqual(projection.routes[0].native, "Installed key")
        self.assertEqual(
            projection.warning,
            "runtime-contract-unavailable error=test",
        )
        self.assertEqual(
            merged.meta[label].catalogue_evidence_warning,
            "runtime-contract-unavailable error=test",
        )

    def test_all_28_promoted_ids_use_bundled_exact_evidence_before_live_cache(self) -> None:
        from core.catalogue_stem_cache import StemCacheHit
        from core.mdx_runtime_contract import load_bundled_mdx_runtime_contracts

        contracts = {
            model_id: contract
            for model_id, contract in load_bundled_mdx_runtime_contracts().contracts.items()
            if model_id != "mdx:UVR_MDXNET_KARA_2"
        }
        self.assertEqual(len(contracts), 28)
        catalogue = {}
        metadata = {}
        model_id_by_label = {}
        hits_by_url = {}
        for index, (model_id, contract) in enumerate(contracts.items()):
            basename = model_id.removeprefix("mdx:")
            label = f"runtime-contract-{index:02d}"
            extension = ".onnx" if contract.backend == "classic_onnx" else ".ckpt"
            files = {f"{basename}{extension}": f"https://example.test/{basename}{extension}"}
            if contract.config_yamls:
                config_name = contract.config_yamls[0]
                config_url = f"https://example.test/config/{index}/{config_name}"
                files[config_name] = config_url
                evidence = contract.config_evidence[config_name]
                source_stems = list(evidence.training_instruments)
                source_target = evidence.target_instrument or ""
                hits_by_url[config_url] = StemCacheHit(
                    stems=evidence.training_instruments,
                    target_instrument=source_target,
                    ok=True,
                    content_sha256=evidence.content_sha256,
                )
            else:
                source_stems = list(contract.native_signature)
                source_target = ""
            catalogue[label] = files
            metadata[label] = {
                "stems": source_stems,
                "primary_stem": contract.primary_native,
                "target_instrument": source_target,
            }
            model_id_by_label[label] = model_id

        with (
            _with_supplements(({}, catalogue, {}, metadata)),
            unittest.mock.patch("core.catalogue_stem_cache.lookup_stems", return_value=None),
        ):
            uncached = catalog_sources.merged_catalogues(vr={}, mdx={}, demucs={})

        self.assertEqual(
            {
                status: sum(
                    uncached.meta[label].stem_semantics.status == status
                    for label in model_id_by_label
                )
                for status in ("reviewed", "raw")
            },
            {"reviewed": 28, "raw": 0},
        )

        catalog_sources.invalidate_catalogue_merge()
        with (
            _with_supplements(({}, catalogue, {}, metadata)),
            unittest.mock.patch(
                "core.catalogue_stem_cache.lookup_stems",
                side_effect=lambda url: hits_by_url.get(url),
            ),
        ):
            merged = catalog_sources.merged_catalogues(vr={}, mdx={}, demucs={})

        self.assertEqual(
            set(merged.meta),
            set(model_id_by_label)
            | {
                "Apollo Model: EDM Restoration Big by essid",
                "Apollo Model: EDM Restoration by essid",
            },
        )
        for label, model_id in model_id_by_label.items():
            with self.subTest(model_id=model_id):
                projection = merged.meta[label].stem_semantics
                self.assertEqual(projection.status, "reviewed")
                self.assertIn(
                    "runtime_contract=model_manifest.json",
                    projection.evidence,
                )
        self.assertEqual(
            {
                status: sum(
                    merged.meta[label].stem_semantics.status == status
                    for label in model_id_by_label
                )
                for status in ("reviewed", "raw")
            },
            {"reviewed": 28, "raw": 0},
        )


@_STEM_CACHE_OFF
class MergeCacheTests(unittest.TestCase):
    def setUp(self) -> None:
        catalog_sources.invalidate_catalogue_merge()

    def test_second_identical_merge_is_cached(self) -> None:
        supplements = ({}, {"New": {"new.ckpt": "https://x/new.ckpt"}}, {}, {})
        with _with_supplements(supplements):
            with unittest.mock.patch.object(
                catalog_sources,
                "dedupe_download_catalogue",
                wraps=catalog_sources.dedupe_download_catalogue,
            ) as dedupe:
                first = catalog_sources.merged_catalogues(vr={}, mdx={}, demucs={})
                calls_after_first = dedupe.call_count
                second = catalog_sources.merged_catalogues(vr={}, mdx={}, demucs={})
        self.assertIs(first, second)
        self.assertGreater(calls_after_first, 0)
        self.assertEqual(dedupe.call_count, calls_after_first)

    def test_invalidate_forces_rebuild(self) -> None:
        supplements = ({}, {"New": {"new.ckpt": "https://x/new.ckpt"}}, {}, {})
        with _with_supplements(supplements):
            with unittest.mock.patch.object(
                catalog_sources,
                "dedupe_download_catalogue",
                wraps=catalog_sources.dedupe_download_catalogue,
            ) as dedupe:
                catalog_sources.merged_catalogues(vr={}, mdx={}, demucs={})
                calls_after_first = dedupe.call_count
                catalog_sources.invalidate_catalogue_merge()
                catalog_sources.merged_catalogues(vr={}, mdx={}, demucs={})
        self.assertGreater(dedupe.call_count, calls_after_first)

    def test_supplement_cache_does_not_publish_after_invalidate(self) -> None:
        calls = {"n": 0}

        def collect(*, allow_network: bool):
            calls["n"] += 1
            if calls["n"] == 1:
                catalog_sources.invalidate_catalogue_merge()
            return ({}, {}, {}, {})

        with unittest.mock.patch.object(
            catalog_sources, "_collect_supplemental_sources", side_effect=collect
        ):
            catalog_sources._supplemental_sources(allow_network=False)
            catalog_sources._supplemental_sources(allow_network=False)
        self.assertEqual(calls["n"], 2)


@_STEM_CACHE_OFF
class MergePriorityDedupeTests(unittest.TestCase):
    def setUp(self) -> None:
        catalog_sources.invalidate_catalogue_merge()

    def test_extras_hyperace_wins_over_mvsepless_same_etag(self) -> None:
        # Simulate post-supplement catalogue order: extras label first, then
        # mvsepless alias — content_ids make them collide.
        extras_label = "Roformer Model: BandSplit Roformer | HyperACE v2 Instrumental by Unwa"
        mv_label = "BS Roformer Instrumental HyperACE v2 (finetuned anvuew vocal model) by Unwa"
        mdx = {
            extras_label: {
                "bs_roformer_inst_hyperacev2.ckpt": "https://pcunwa/v2_inst.ckpt",
            },
            mv_label: {
                "bs_inst_hyperace2_unwa.ckpt": "https://mvsepless/hyperace2.ckpt",
            },
        }
        content_ids = {
            "https://pcunwa/v2_inst.ckpt": "same-etag",
            "https://mvsepless/hyperace2.ckpt": "same-etag",
        }
        with _with_supplements(_NO_SUPPLEMENTS):
            with unittest.mock.patch(
                "core.download_sizes.content_ids_from_cache",
                return_value=content_ids,
            ):
                merged = catalog_sources.merged_catalogues(vr={}, mdx=mdx, demucs={})
        self.assertIn(extras_label, merged.mdx)
        self.assertNotIn(mv_label, merged.mdx)
        # meta still names both for picker resolution
        self.assertIn(extras_label, merged.meta)
        self.assertIn(mv_label, merged.meta)

    def test_reviewed_becruily_delta_excludes_retired_rows_but_keeps_installed_views(
        self,
    ) -> None:
        from core.catalogue_coordinator import CatalogueCoordinator
        from core.catalogue_types import SourceId
        from core.model_inventory import build_identity_index
        from core.model_manifest import load_model_manifest
        from core.model_stem_manifest import resolve_model_stem_semantics
        from core.remote_catalog_cache import RemoteJsonSource
        from core.stem_roles import StemReviewStatus

        fixture = json.loads(_BECRUILY_SOURCE_DELTA_FIXTURE.read_text(encoding="utf-8"))
        sources = {
            SourceId.UPSTREAM: RemoteJsonSource(
                source_id=SourceId.UPSTREAM,
                local_loader=lambda: {
                    "vr_download_list": {},
                    "mdx_download_list": {},
                    "demucs_download_list": {},
                },
            ),
            SourceId.POLITREES: RemoteJsonSource(
                source_id=SourceId.POLITREES,
                local_loader=lambda: fixture["politrees"],
            ),
            SourceId.EXTRAS: RemoteJsonSource(
                source_id=SourceId.EXTRAS,
                enabled=lambda: False,
            ),
            SourceId.MVSEPLESS: RemoteJsonSource(
                source_id=SourceId.MVSEPLESS,
                local_loader=lambda: fixture["mvsepless"],
            ),
        }
        coordinator = CatalogueCoordinator(sources=sources)
        self.addCleanup(coordinator.close)
        snapshot = coordinator.ensure(allow_network=False)

        visible_ids = {
            catalogue_model_id("mdx", label, raw, snapshot.meta_by_family["mdx"][label])
            for label, raw in snapshot.mdx.items()
        }
        retired_ids = {
            "mdx:mbr_guitar_becruily",
            "mdx:mbr_inst_becruily",
        }
        self.assertEqual(
            visible_ids,
            {
                "mdx:melband_roformer_guitar_becruily",
                "mdx:mel_band_roformer_instrumental_becruily",
                "mdx:mbr_invert_clean_becruily",
            },
        )
        self.assertTrue(retired_ids.isdisjoint(visible_ids))
        self.assertTrue(set(fixture["retired_labels"]).isdisjoint(snapshot.mdx))
        self.assertTrue(set(fixture["retired_labels"]).issubset(snapshot.pre_dedupe_mdx))
        self.assertTrue(set(fixture["retired_labels"]).issubset(snapshot.meta_by_family["mdx"]))

        retired_files = tuple(fixture["retired_artifacts"].values())
        repo = SimpleNamespace(
            _model_artifact_files=lambda family: retired_files if family == "mdx" else (),
            list_vr_models=lambda: [],
            list_mdx_models=lambda: [],
            list_demucs_models=lambda: [],
            inventory_generation=0,
            catalogue_revision="reviewed-becruily-delta",
            naming_revision=0,
            mdx_name_select_MAPPER={},
            demucs_name_select_MAPPER={},
        )
        index = build_identity_index(
            repo,
            snapshot=snapshot,
            bundled_demucs_specs={},
            registered_demucs={},
        )
        manifest = load_model_manifest()
        self.assertEqual(manifest.models["mdx:mbr_invert_clean_becruily"].lifecycle, "current")
        self.assertEqual(
            {manifest.models[model_id].lifecycle for model_id in retired_ids},
            {"retired"},
        )
        expected = {
            "mdx:mbr_guitar_becruily": (
                "MelBand Roformer — Instrumental · Becruily [mbr_guitar_becruily]",
                (("Guitar", "instrument.guitar"), (None, "instrument.guitar.removed")),
            ),
            "mdx:mbr_inst_becruily": (
                "MelBand Roformer — Instrumental · Becruily [mbr_inst_becruily]",
                (("Instrumental", "mix.instrumental"), (None, "vocal.vocals")),
            ),
        }
        for model_id, (display, routes) in expected.items():
            with self.subTest(model_id=model_id):
                record = index.lookup(model_id)
                self.assertTrue(record.installed)
                self.assertEqual(record.display, display)
                declaration = manifest.stems.models[model_id]
                resolved = resolve_model_stem_semantics(
                    model_id,
                    native_stems=declaration.native_signature,
                    backend_primary=declaration.native_signature[0],
                    registry=manifest.stems,
                )
                self.assertEqual(resolved.status, StemReviewStatus.REVIEWED)
                self.assertEqual(
                    tuple(
                        (
                            output.native.raw if output.native is not None else None,
                            str(output.role),
                        )
                        for output in resolved.outputs
                    ),
                    routes,
                )


if __name__ == "__main__":
    unittest.main()
