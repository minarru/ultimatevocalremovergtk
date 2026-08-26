"""Strict loading and exact resolution for reviewed stem semantics."""

from __future__ import annotations

import json
import re
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any
from unittest.mock import patch

from core.model_stem_manifest import (
    BUNDLED_MANIFEST_PATH,
    StemManifestError,
    load_bundled_stem_semantics,
    load_stem_manifest,
    load_stem_manifest_document,
    resolve_model_stem_semantics,
)
from core.stem_roles import (
    ROLE_ID_RE,
    StemLiteral,
    StemProcessingContext,
    StemProduction,
    StemReviewStatus,
    StemRoleFamily,
    StemRoleId,
)


def _manifest() -> dict[str, Any]:
    """A complete reviewed declaration with a contextual and derived route."""
    return {
        "schema_version": 2,
        "roles": {
            "vocal.vocals": {
                "display": "Vocals",
                "filename_tag": "Vocals",
                "family": "vocal",
            },
            "vocal.lead": {
                "display": "Lead Vocals",
                "filename_tag": "Lead_Vocals",
                "family": "vocal",
            },
            "vocal.backing": {
                "display": "Backing Vocals",
                "filename_tag": "Backing_Vocals",
                "family": "vocal",
            },
            "mix.instrumental": {
                "display": "Instrumental",
                "filename_tag": "Instrumental",
                "family": "mix",
            },
            "residual.other": {
                "display": "Residual",
                "filename_tag": "Residual",
                "family": "residual",
            },
        },
        "pairs": {
            "pair.vocals_instrumental": {
                "display": "Vocals/Instrumental",
                "roles": ["vocal.vocals", "mix.instrumental"],
            }
        },
        "models": {
            "mdx:fixture": {
                "native_signature": ["Vocals", "Other"],
                "intent": "karaoke",
                "contexts": {
                    "full_mix": {
                        "logical_primary": "vocal.vocals",
                        "outputs": [
                            {"native": "Vocals", "role": "vocal.vocals"},
                            {"native": "Other", "role": "mix.instrumental"},
                            {
                                "native": None,
                                "role": "residual.other",
                                "production": "derived",
                                "complement_of": "vocal.vocals",
                            },
                        ],
                    },
                    "vocal_split": {
                        "logical_primary": "vocal.lead",
                        "outputs": [
                            {"native": "Vocals", "role": "vocal.lead"},
                            {"native": "Other", "role": "vocal.backing"},
                        ],
                    },
                },
                "evidence": "fixture review",
            }
        },
        "waivers": {"apollo:restoration": "no separation stem inventory"},
    }


class StemRoleValueTests(unittest.TestCase):
    def test_namespaced_role_ids_accept_only_the_documented_grammar(self) -> None:
        valid = ("vocal.vocals", "instrument.guitar.removed", "effect.reverb_2")
        invalid = ("vocals", "Vocal.vocals", "vocal..vocals", "vocal.-vocals")

        for value in valid:
            with self.subTest(value=value):
                self.assertIsNotNone(ROLE_ID_RE.fullmatch(value))
                self.assertEqual(StemRoleId(value).value, value)
        for value in invalid:
            with self.subTest(value=value):
                self.assertIsNone(ROLE_ID_RE.fullmatch(value))
                with self.assertRaises(ValueError):
                    StemRoleId(value)

    def test_closed_behavior_enums_expose_only_approved_values(self) -> None:
        self.assertEqual(
            tuple(member.value for member in StemProcessingContext),
            ("full_mix", "vocal_split"),
        )
        self.assertEqual(tuple(member.value for member in StemProduction), ("native", "derived"))
        self.assertEqual(
            tuple(member.value for member in StemReviewStatus),
            ("reviewed", "waived", "raw"),
        )
        self.assertEqual(
            tuple(member.value for member in StemRoleFamily),
            ("vocal", "mix", "instrument", "effect", "spatial", "cinematic", "residual"),
        )


class ManifestValidationTests(unittest.TestCase):
    def test_schema_version_is_exact_integer_two(self) -> None:
        for value in (True, False, 2.0, "2", 1, 3):
            document = _manifest()
            document["schema_version"] = value
            with self.subTest(value=value), self.assertRaises(StemManifestError) as raised:
                load_stem_manifest_document(document)
            self.assertEqual(raised.exception.path, ("schema_version",))

    def test_duplicate_json_keys_are_typed_errors_at_root_and_nested_levels(self) -> None:
        documents = (
            (
                "schema_version",
                '{"schema_version":2,"schema_version":2,"roles":{},"pairs":{},'
                '"models":{},"waivers":{}}',
            ),
            (
                "display",
                '{"schema_version":2,"roles":{"vocal.vocals":{'
                '"display":"Vocals","display":"Again","filename_tag":"Vocals",'
                '"family":"vocal"}},"pairs":{},"models":{},"waivers":{}}',
            ),
        )
        with TemporaryDirectory() as directory:
            path = Path(directory) / "manifest.json"
            for duplicate, text in documents:
                with self.subTest(duplicate=duplicate):
                    path.write_text(text, encoding="utf-8")
                    with self.assertRaisesRegex(
                        StemManifestError, rf"duplicate key.*{re.escape(duplicate)}"
                    ):
                        load_stem_manifest(path)

    def test_unknown_fields_are_rejected_at_every_closed_object_level(self) -> None:
        cases = ("root", "role", "pair", "model", "context", "output")
        for level in cases:
            document = _manifest()
            if level == "root":
                target = document
                expected_path = ("unknown",)
            elif level == "role":
                target = document["roles"]["vocal.vocals"]
                expected_path = ("roles", "vocal.vocals", "unknown")
            elif level == "pair":
                target = document["pairs"]["pair.vocals_instrumental"]
                expected_path = ("pairs", "pair.vocals_instrumental", "unknown")
            elif level == "model":
                target = document["models"]["mdx:fixture"]
                expected_path = ("models", "mdx:fixture", "unknown")
            elif level == "context":
                target = document["models"]["mdx:fixture"]["contexts"]["full_mix"]
                expected_path = (
                    "models",
                    "mdx:fixture",
                    "contexts",
                    "full_mix",
                    "unknown",
                )
            else:
                target = document["models"]["mdx:fixture"]["contexts"]["full_mix"]["outputs"][0]
                expected_path = (
                    "models",
                    "mdx:fixture",
                    "contexts",
                    "full_mix",
                    "outputs",
                    0,
                    "unknown",
                )
            target["unknown"] = "not allowed"
            with self.subTest(level=level), self.assertRaises(StemManifestError) as raised:
                load_stem_manifest_document(document)
            self.assertEqual(raised.exception.path, expected_path)

    def test_selected_by_default_defaults_true_and_explicit_false_round_trips(self) -> None:
        document = _manifest()
        outputs = document["models"]["mdx:fixture"]["contexts"]["full_mix"]["outputs"]
        outputs[1]["selected_by_default"] = False

        registry = load_stem_manifest_document(document)
        parsed = registry.models["mdx:fixture"].contexts[StemProcessingContext.FULL_MIX].outputs

        self.assertIs(parsed[0].selected_by_default, True)
        self.assertIs(parsed[1].selected_by_default, False)

    def test_selected_by_default_rejects_every_non_boolean(self) -> None:
        for value in (0, 1, 0.0, 1.0, "false", None, []):
            document = _manifest()
            document["models"]["mdx:fixture"]["contexts"]["full_mix"]["outputs"][1][
                "selected_by_default"
            ] = value
            with self.subTest(value=value), self.assertRaises(StemManifestError) as raised:
                load_stem_manifest_document(document)
            self.assertEqual(raised.exception.path[-1], "selected_by_default")

    def test_native_outputs_reject_both_dependency_forms(self) -> None:
        for field, value in (
            ("complement_of", "mix.instrumental"),
            ("derived_from", ["vocal.vocals", "mix.instrumental"]),
        ):
            document = _manifest()
            document["models"]["mdx:fixture"]["contexts"]["full_mix"]["outputs"][0][field] = value
            with self.subTest(field=field), self.assertRaises(StemManifestError) as raised:
                load_stem_manifest_document(document)
            self.assertEqual(raised.exception.path[-1], field)

    def test_derived_outputs_require_exactly_one_recipe_form(self) -> None:
        for recipe_count in (0, 2):
            document = _manifest()
            output = document["models"]["mdx:fixture"]["contexts"]["full_mix"]["outputs"][2]
            del output["complement_of"]
            if recipe_count == 2:
                output["complement_of"] = "vocal.vocals"
                output["derived_from"] = ["vocal.vocals", "mix.instrumental"]
            with (
                self.subTest(recipe_count=recipe_count),
                self.assertRaisesRegex(StemManifestError, "exactly one dependency form"),
            ):
                load_stem_manifest_document(document)

    def test_complement_dependency_must_be_one_other_native_output(self) -> None:
        cases = (
            ("missing", "vocal.backing", "not an output"),
            ("self", "residual.other", "self-dependency"),
        )
        for label, dependency, message in cases:
            document = _manifest()
            document["models"]["mdx:fixture"]["contexts"]["full_mix"]["outputs"][2][
                "complement_of"
            ] = dependency
            with self.subTest(label=label), self.assertRaisesRegex(StemManifestError, message):
                load_stem_manifest_document(document)

        document = _manifest()
        outputs = document["models"]["mdx:fixture"]["contexts"]["full_mix"]["outputs"]
        outputs.append(
            {
                "native": None,
                "role": "vocal.backing",
                "production": "derived",
                "complement_of": "residual.other",
            }
        )
        outputs[2]["complement_of"] = "vocal.backing"
        with self.assertRaisesRegex(StemManifestError, "native output"):
            load_stem_manifest_document(document)

    def test_sum_dependencies_require_two_distinct_other_native_outputs(self) -> None:
        cases = (
            ("one", ["vocal.vocals"], "at least two"),
            ("duplicate", ["vocal.vocals", "vocal.vocals"], "duplicate dependency"),
            ("self", ["residual.other", "mix.instrumental"], "self-dependency"),
            ("missing", ["vocal.vocals", "vocal.backing"], "not an output"),
        )
        for label, dependencies, message in cases:
            document = _manifest()
            output = document["models"]["mdx:fixture"]["contexts"]["full_mix"]["outputs"][2]
            del output["complement_of"]
            output["derived_from"] = dependencies
            with self.subTest(label=label), self.assertRaisesRegex(StemManifestError, message):
                load_stem_manifest_document(document)

        document = _manifest()
        outputs = document["models"]["mdx:fixture"]["contexts"]["full_mix"]["outputs"]
        outputs.append(
            {
                "native": None,
                "role": "vocal.backing",
                "production": "derived",
                "complement_of": "vocal.vocals",
            }
        )
        del outputs[2]["complement_of"]
        outputs[2]["derived_from"] = ["vocal.vocals", "vocal.backing"]
        with self.assertRaisesRegex(StemManifestError, "native output"):
            load_stem_manifest_document(document)

    def test_context_rejects_duplicate_native_keys_and_role_ids(self) -> None:
        document = _manifest()
        outputs = document["models"]["mdx:fixture"]["contexts"]["full_mix"]["outputs"]
        outputs[1]["native"] = "vocals"
        with self.assertRaisesRegex(StemManifestError, "duplicate case-folded native key"):
            load_stem_manifest_document(document)

        document = _manifest()
        document["models"]["mdx:fixture"]["contexts"]["full_mix"]["outputs"][2]["role"] = (
            "mix.instrumental"
        )
        with self.assertRaisesRegex(StemManifestError, "duplicate role"):
            load_stem_manifest_document(document)

    def test_native_signature_must_not_be_empty(self) -> None:
        document = _manifest()
        document["models"]["mdx:fixture"]["native_signature"] = []
        with self.assertRaisesRegex(StemManifestError, "at least one native key") as raised:
            load_stem_manifest_document(document)
        self.assertEqual(
            raised.exception.path,
            ("models", "mdx:fixture", "native_signature"),
        )

    def test_logical_primary_is_exactly_one_selected_output(self) -> None:
        document = _manifest()
        document["models"]["mdx:fixture"]["contexts"]["full_mix"]["outputs"][0][
            "selected_by_default"
        ] = False
        with self.assertRaisesRegex(StemManifestError, "selected by default"):
            load_stem_manifest_document(document)

        document = _manifest()
        document["models"]["mdx:fixture"]["contexts"]["full_mix"]["logical_primary"] = "vocal.lead"
        with self.assertRaisesRegex(StemManifestError, "missing logical primary output"):
            load_stem_manifest_document(document)

        document = _manifest()
        document["models"]["mdx:fixture"]["contexts"]["full_mix"]["outputs"][1]["role"] = (
            "vocal.vocals"
        )
        with self.assertRaisesRegex(StemManifestError, "multiple logical primaries"):
            load_stem_manifest_document(document)

    def test_logical_secondary_is_optional_and_marks_one_distinct_output(self) -> None:
        omitted_registry = load_stem_manifest_document(_manifest())
        omitted_context = omitted_registry.models["mdx:fixture"].contexts[
            StemProcessingContext.FULL_MIX
        ]
        omitted = resolve_model_stem_semantics(
            "mdx:fixture",
            native_stems=("Vocals", "Other"),
            registry=omitted_registry,
        )

        self.assertIsNone(omitted_context.logical_secondary)
        self.assertIsNone(omitted.logical_secondary_role)
        self.assertEqual([output.logical_secondary for output in omitted.outputs], [False] * 3)

        document = _manifest()
        document["models"]["mdx:fixture"]["contexts"]["full_mix"]["logical_secondary"] = (
            "mix.instrumental"
        )
        registry = load_stem_manifest_document(document)
        context = registry.models["mdx:fixture"].contexts[StemProcessingContext.FULL_MIX]
        semantics = resolve_model_stem_semantics(
            "mdx:fixture",
            native_stems=("Vocals", "Other"),
            registry=registry,
        )

        self.assertEqual(context.logical_secondary, StemRoleId("mix.instrumental"))
        self.assertEqual(semantics.logical_secondary_role, StemRoleId("mix.instrumental"))
        self.assertEqual(
            [output.logical_secondary for output in semantics.outputs],
            [False, True, False],
        )

    def test_logical_secondary_rejects_invalid_or_ambiguous_membership(self) -> None:
        cases = ("missing", "duplicate", "primary", "non-string")
        for case in cases:
            document = _manifest()
            context = document["models"]["mdx:fixture"]["contexts"]["full_mix"]
            if case == "missing":
                context["logical_secondary"] = "vocal.backing"
                expected = "exactly once"
            elif case == "duplicate":
                context["logical_secondary"] = "mix.instrumental"
                context["outputs"][2]["role"] = "mix.instrumental"
                expected = "exactly once"
            elif case == "primary":
                context["logical_secondary"] = "vocal.vocals"
                expected = "distinct"
            else:
                context["logical_secondary"] = 1
                expected = "non-empty string"
            with (
                self.subTest(case=case),
                self.assertRaisesRegex(StemManifestError, expected) as raised,
            ):
                load_stem_manifest_document(document)
            self.assertEqual(
                raised.exception.path,
                ("models", "mdx:fixture", "contexts", "full_mix", "logical_secondary"),
            )

    def test_role_id_namespace_must_match_declared_family(self) -> None:
        document = _manifest()
        document["roles"]["vocal.vocals"]["family"] = "mix"
        with self.assertRaisesRegex(StemManifestError, "namespace.*family") as raised:
            load_stem_manifest_document(document)
        self.assertEqual(raised.exception.path, ("roles", "vocal.vocals", "family"))

    def test_removed_role_graph_rejects_missing_self_cycle_cross_family_and_bad_name(self) -> None:
        cases = ("missing", "self", "cycle", "cross-family", "bad-name")
        for case in cases:
            document = _manifest()
            if case == "missing":
                document["roles"]["vocal.vocals.removed"] = {
                    "display": "Vocals Removed",
                    "filename_tag": "Vocals_Removed",
                    "family": "vocal",
                    "removed_of": "vocal.missing",
                }
                expected = "missing role reference"
            elif case == "self":
                document["roles"]["vocal.vocals.removed"] = {
                    "display": "Vocals Removed",
                    "filename_tag": "Vocals_Removed",
                    "family": "vocal",
                    "removed_of": "vocal.vocals.removed",
                }
                expected = "cannot reference itself"
            elif case == "cycle":
                document["roles"]["vocal.vocals"]["removed_of"] = "vocal.vocals.removed"
                document["roles"]["vocal.vocals.removed"] = {
                    "display": "Vocals Removed",
                    "filename_tag": "Vocals_Removed",
                    "family": "vocal",
                    "removed_of": "vocal.vocals",
                }
                expected = "cycle"
            elif case == "cross-family":
                document["roles"]["mix.instrumental.removed"] = {
                    "display": "Instrumental Removed",
                    "filename_tag": "Instrumental_Removed",
                    "family": "mix",
                    "removed_of": "vocal.vocals",
                }
                expected = "same family"
            else:
                document["roles"]["vocal.vocals_removed"] = {
                    "display": "Vocals Removed",
                    "filename_tag": "Vocals_Removed",
                    "family": "vocal",
                    "removed_of": "vocal.vocals",
                }
                expected = r"\.removed"
            with self.subTest(case=case), self.assertRaisesRegex(StemManifestError, expected):
                load_stem_manifest_document(document)

    def test_model_and_waiver_ids_must_not_overlap(self) -> None:
        document = _manifest()
        document["waivers"]["mdx:fixture"] = "duplicate disposition"
        with self.assertRaisesRegex(StemManifestError, "both models and waivers") as raised:
            load_stem_manifest_document(document)
        self.assertEqual(raised.exception.path, ("waivers", "mdx:fixture"))

    def test_p5_retains_both_exact_becruily_artifacts(self) -> None:
        registry = load_stem_manifest(BUNDLED_MANIFEST_PATH)

        guitar = registry.models["mdx:mbr_guitar_becruily"]
        guitar_context = guitar.contexts[StemProcessingContext.FULL_MIX]
        self.assertEqual(guitar.native_signature, ("Guitar",))
        self.assertEqual(
            [str(output.role) for output in guitar_context.outputs],
            ["instrument.guitar", "instrument.guitar.removed"],
        )
        self.assertIsNone(guitar_context.outputs[1].native)
        self.assertEqual(
            guitar_context.outputs[1].complement_of,
            StemRoleId("instrument.guitar"),
        )
        self.assertEqual(str(guitar_context.logical_primary), "instrument.guitar")
        self.assertIn("catalogue_id=mdx:mbr_guitar_becruily", guitar.evidence)

        instrumental = registry.models["mdx:mbr_inst_becruily"]
        instrumental_context = instrumental.contexts[StemProcessingContext.FULL_MIX]
        self.assertEqual(instrumental.native_signature, ("Instrumental",))
        self.assertEqual(
            [str(output.role) for output in instrumental_context.outputs],
            ["mix.instrumental", "vocal.vocals"],
        )
        self.assertEqual(str(instrumental_context.logical_primary), "mix.instrumental")
        self.assertIsNone(instrumental_context.outputs[1].native)
        self.assertEqual(
            instrumental_context.outputs[1].complement_of,
            StemRoleId("mix.instrumental"),
        )
        self.assertIn("catalogue_id=mdx:mbr_inst_becruily", instrumental.evidence)

    def test_reviewed_two_output_pairs_and_multistem_residuals_remain_distinct(self) -> None:
        registry = load_stem_manifest(BUNDLED_MANIFEST_PATH)
        for model_id, declaration in registry.models.items():
            outputs = declaration.contexts[StemProcessingContext.FULL_MIX].outputs
            roles = {str(output.role) for output in outputs}
            native_stems = [
                output.native.raw.casefold() if output.native else "" for output in outputs
            ]
            if len(outputs) == 2:
                self.assertNotIn("residual.other", roles, model_id)
            elif "other" in {
                output.native.raw.casefold() for output in outputs if output.native is not None
            }:
                self.assertIn("residual.other", roles, model_id)
            if "denoise" in model_id and native_stems == ["dry", "other"]:
                self.assertEqual(
                    [str(output.role) for output in outputs],
                    ["effect.noise.removed", "effect.noise"],
                )
                self.assertEqual(
                    declaration.contexts[StemProcessingContext.FULL_MIX].logical_primary.value,
                    "effect.noise.removed",
                )
            if (
                "dereverb" in model_id
                or "debigreverb" in model_id
                or "desuperbigreverb" in model_id
            ) and native_stems == ["dry", "other"]:
                self.assertEqual(
                    [str(output.role) for output in outputs],
                    ["effect.reverb.removed", "effect.reverb"],
                )
                self.assertEqual(
                    declaration.contexts[StemProcessingContext.FULL_MIX].logical_primary.value,
                    "effect.reverb.removed",
                )

    def test_melband_bve_ids_use_ordinary_karaoke_roles_in_both_contexts(self) -> None:
        registry = load_stem_manifest(BUNDLED_MANIFEST_PATH)
        for model_id in (
            "mdx:mbr_bve_gonzaluigi",
            "mdx:model_MelBand-Roformer_BVE_by-Gonza",
        ):
            declaration = registry.models[model_id]
            full = declaration.contexts[StemProcessingContext.FULL_MIX]
            split = declaration.contexts[StemProcessingContext.VOCAL_SPLIT]
            self.assertEqual(full.logical_primary, StemRoleId("vocal.lead"))
            self.assertEqual(
                [output.role for output in full.outputs],
                [StemRoleId("vocal.lead"), StemRoleId("mix.instrumental_with_backing_vocals")],
            )
            self.assertEqual(
                [output.role for output in split.outputs],
                [StemRoleId("vocal.lead"), StemRoleId("vocal.backing")],
            )

    def test_vr_bve_uses_exact_context_reversal_with_reviewed_presentation(self) -> None:
        registry = load_stem_manifest(BUNDLED_MANIFEST_PATH)
        model_id = "vr:UVR-BVE-4B_SN-44100-1"

        self.assertNotIn(model_id, registry.waivers)
        declaration = registry.models[model_id]
        self.assertEqual(declaration.native_signature, ("Vocals", "Instrumental"))
        self.assertIn(f"catalogue_id={model_id}", declaration.evidence)
        self.assertIn("source=TRvlvr+Politrees", declaration.evidence)
        self.assertIn("backend_contract=VR two-output complement", declaration.evidence)
        self.assertIn("backend_primary=Vocals", declaration.evidence)
        self.assertIn("reviewed_contexts=full_mix|vocal_split", declaration.evidence)

        expected = {
            StemProcessingContext.FULL_MIX: (
                ["Vocals", "Instrumental"],
                ["vocal.backing", "mix.instrumental_with_lead_vocals"],
                "vocal.backing",
                "pair.backing_vocals",
                ["Backing Vocals", "Instrumental with Lead Vocals"],
                ["Backing_Vocals", "Instrumental_with_Lead_Vocals"],
            ),
            StemProcessingContext.VOCAL_SPLIT: (
                ["Vocals", "Instrumental"],
                ["vocal.backing", "vocal.lead"],
                "vocal.backing",
                "",
                ["Backing Vocals", "Lead Vocals"],
                ["Backing_Vocals", "Lead_Vocals"],
            ),
        }
        for context, (
            native_names,
            role_ids,
            logical_primary,
            pair_id,
            displays,
            tags,
        ) in expected.items():
            with self.subTest(context=context.value):
                resolved = resolve_model_stem_semantics(
                    model_id,
                    native_stems=("Vocals", "Instrumental"),
                    backend_primary="Vocals",
                    context=context,
                    registry=registry,
                )
                self.assertIs(resolved.status, StemReviewStatus.REVIEWED)
                native_outputs = [output.native for output in resolved.outputs]
                self.assertTrue(all(native is not None for native in native_outputs))
                self.assertEqual(
                    [native.raw for native in native_outputs if native is not None], native_names
                )
                self.assertEqual([str(output.role) for output in resolved.outputs], role_ids)
                self.assertEqual(
                    [output.logical_primary for output in resolved.outputs], [True, False]
                )
                self.assertEqual(
                    str(declaration.contexts[context].logical_primary), logical_primary
                )
                reviewed_roles = [
                    output.role
                    for output in resolved.outputs
                    if isinstance(output.role, StemRoleId)
                ]
                self.assertEqual(len(reviewed_roles), len(resolved.outputs))
                definitions = [registry.roles[role] for role in reviewed_roles]
                self.assertEqual([definition.display for definition in definitions], displays)
                self.assertEqual([definition.filename_tag for definition in definitions], tags)
                context_roles = {output.role for output in resolved.outputs}
                matching_pairs = [
                    pair.id
                    for pair in registry.pairs.values()
                    if set(pair.roles).issubset(context_roles)
                ]
                self.assertEqual(matching_pairs, [pair_id] if pair_id else [])

    def test_classic_karaoke_2_uses_exact_runtime_keys_in_both_contexts(self) -> None:
        registry = load_stem_manifest(BUNDLED_MANIFEST_PATH)
        declaration = registry.models["mdx:UVR_MDXNET_KARA_2"]

        self.assertEqual(declaration.native_signature, ("Instrumental", "Vocals"))
        expected = {
            StemProcessingContext.FULL_MIX: (
                ["Instrumental", "Vocals"],
                ["mix.instrumental_with_backing_vocals", "vocal.lead"],
            ),
            StemProcessingContext.VOCAL_SPLIT: (
                ["Instrumental", "Vocals"],
                ["vocal.backing", "vocal.lead"],
            ),
        }
        for context_id, (native, roles) in expected.items():
            with self.subTest(context=context_id.value):
                outputs = declaration.contexts[context_id].outputs
                self.assertEqual(
                    [output.native and output.native.raw for output in outputs], native
                )
                self.assertEqual([str(output.role) for output in outputs], roles)

    def test_p3_exact_specialty_exceptions_have_reviewed_removal_roles(self) -> None:
        registry = load_stem_manifest(BUNDLED_MANIFEST_PATH)
        expected = {
            "mdx:aspiration_mel_band_roformer_less_aggr_sdr_18.1201": (
                ["vocal.aspiration", "vocal.aspiration.removed"],
                "vocal.aspiration",
            ),
            "mdx:aspiration_mel_band_roformer_sdr_18.9845": (
                ["vocal.aspiration", "vocal.aspiration.removed"],
                "vocal.aspiration",
            ),
            "mdx:bs_bowed_str_gilliaaan": (
                ["instrument.bowed_strings", "instrument.bowed_strings.removed"],
                "instrument.bowed_strings",
            ),
            "mdx:bs_drums_gilliaaan": (
                ["instrument.drums", "instrument.drums.removed"],
                "instrument.drums",
            ),
            "mdx:mbr_denoise_yuluoye": (
                ["effect.noise.removed", "effect.noise"],
                "effect.noise.removed",
            ),
        }
        for model_id, (roles, primary) in expected.items():
            with self.subTest(model_id=model_id):
                context = registry.models[model_id].contexts[StemProcessingContext.FULL_MIX]
                self.assertEqual([str(output.role) for output in context.outputs], roles)
                self.assertEqual(str(context.logical_primary), primary)

    def test_bundled_declarations_have_exact_non_placeholder_provenance(self) -> None:
        registry = load_stem_manifest(BUNDLED_MANIFEST_PATH)
        for model_id, declaration in registry.models.items():
            with self.subTest(model_id=model_id):
                self.assertNotEqual(declaration.intent, "reviewed catalogue semantics")
                self.assertIn(f"catalogue_id={model_id}", declaration.evidence)
                self.assertIn("native_signature=", declaration.evidence)
                self.assertIn("metadata_source=", declaration.evidence)
        for model_id, reason in registry.waivers.items():
            with self.subTest(waiver=model_id):
                self.assertIn(f"catalogue_id={model_id}", reason)
                self.assertIn("no native inventory", reason)

    def test_yaml_target_instrument_declarations_match_single_native_runtime_inventory(
        self,
    ) -> None:
        """Real target-instrument configs expose only their target as native.

        The other reviewed side is an engine-derived mix-minus-target route,
        including context-sensitive karaoke declarations. Community-only
        target hints are deliberately outside this runtime-config contract.
        """
        registry = load_stem_manifest(BUNDLED_MANIFEST_PATH)
        declarations = []
        for model_id, declaration in registry.models.items():
            if not re.search(
                r"metadata_source=(?:bundled_yaml|remote_yaml):", declaration.evidence
            ):
                continue
            target_match = re.search(r"(?:^|; )backend_target=([^;]+)", declaration.evidence)
            if target_match is None:
                continue
            declarations.append((model_id, declaration, target_match.group(1)))

        self.assertEqual(len(declarations), 304)
        for model_id, declaration, target in declarations:
            with self.subTest(model_id=model_id):
                self.assertEqual(declaration.native_signature, (target,))
                self.assertIn(f"native_signature={target};", declaration.evidence)
                for context in declaration.contexts.values():
                    native = tuple(
                        output for output in context.outputs if output.native is not None
                    )
                    derived = tuple(output for output in context.outputs if output.native is None)
                    self.assertEqual(len(native), 1)
                    self.assertTrue(native[0].native and native[0].native.matches(target))
                    self.assertEqual(len(derived), 1)
                    self.assertEqual(derived[0].production, StemProduction.DERIVED)
                    self.assertEqual(derived[0].complement_of, native[0].role)
                    self.assertEqual(derived[0].derived_from, ())

    def test_representative_target_declarations_preserve_exact_role_polarity(self) -> None:
        registry = load_stem_manifest(BUNDLED_MANIFEST_PATH)
        expected = {
            "mdx:mbr_inst2_unwa": (
                "other",
                "mix.instrumental",
                "vocal.vocals",
                "mix.instrumental",
            ),
            "mdx:bs_bass_xlancer": (
                "bass",
                "instrument.bass",
                "instrument.bass.removed",
                "instrument.bass",
            ),
            "mdx:mbr_denoise_yuluoye": (
                "other",
                "effect.noise",
                "effect.noise.removed",
                "effect.noise.removed",
            ),
            "mdx:mbr_desuperbigreverb_sucial": (
                "dry",
                "effect.reverb.removed",
                "effect.reverb",
                "effect.reverb.removed",
            ),
            "mdx:mel_band_roformer_bleed_suppressor_v1": (
                "Instrumental",
                "mix.instrumental",
                "mix.bleed",
                "mix.instrumental",
            ),
        }
        for model_id, (target, native_role, derived_role, logical_primary) in expected.items():
            with self.subTest(model_id=model_id):
                declaration = registry.models[model_id]
                context = declaration.contexts[StemProcessingContext.FULL_MIX]
                native = tuple(output for output in context.outputs if output.native is not None)
                derived = tuple(output for output in context.outputs if output.native is None)
                self.assertEqual(declaration.native_signature, (target,))
                self.assertEqual([str(output.role) for output in native], [native_role])
                self.assertEqual([str(output.role) for output in derived], [derived_role])
                self.assertEqual(native[0].native and native[0].native.raw, target)
                self.assertEqual(derived[0].complement_of, StemRoleId(native_role))
                self.assertEqual(str(context.logical_primary), logical_primary)

        karaoke = registry.models["mdx:bs_karaoke_gabox"]
        self.assertEqual(karaoke.native_signature, ("vocals",))
        expected_derived = {
            StemProcessingContext.FULL_MIX: "mix.instrumental_with_backing_vocals",
            StemProcessingContext.VOCAL_SPLIT: "vocal.backing",
        }
        for context_id, derived_role in expected_derived.items():
            with self.subTest(context=context_id.value):
                outputs = karaoke.contexts[context_id].outputs
                self.assertEqual(
                    [str(output.role) for output in outputs], ["vocal.lead", derived_role]
                )
                self.assertIsNone(outputs[1].native)
                self.assertEqual(outputs[1].complement_of, StemRoleId("vocal.lead"))

    def test_exact_two_output_target_complements_never_use_residual_other(self) -> None:
        """A declared target/complement pair keeps the target semantic identity."""
        registry = load_stem_manifest(BUNDLED_MANIFEST_PATH)
        for model_id, declaration in registry.models.items():
            outputs = declaration.contexts[StemProcessingContext.FULL_MIX].outputs
            if len(declaration.native_signature) != 2:
                continue
            roles = {str(output.role) for output in outputs}
            with self.subTest(model_id=model_id):
                self.assertNotIn("residual.other", roles)

    def test_bundled_catalogue_covers_every_current_exact_identity(self) -> None:
        """The checked-in review is exhaustive, never inferred at runtime."""
        registry = load_stem_manifest(BUNDLED_MANIFEST_PATH)

        self.assertEqual(len(registry.models) + len(registry.waivers), 485)
        self.assertFalse(set(registry.models) & set(registry.waivers))

    def test_accepts_all_supported_canonical_model_families(self) -> None:
        for model_id in ("vr:fixture", "mdx:fixture", "demucs:fixture", "apollo:fixture"):
            with self.subTest(model_id=model_id):
                document = _manifest()
                declaration = document["models"].pop("mdx:fixture")
                document["models"][model_id] = declaration

                registry = load_stem_manifest_document(document)

                self.assertIn(model_id, registry.models)

    def test_rejects_noncanonical_model_and_waiver_ids_with_their_paths(self) -> None:
        invalid_ids = (
            "unknown:fixture",
            "MDX:fixture",
            "mdx :fixture",
            "mdx: fixture",
            "mdx:fixture ",
            "mdx:fixture:extra",
            "fixture",
            "vr:",
        )

        for model_id in invalid_ids:
            with self.subTest(section="models", model_id=model_id):
                document = _manifest()
                declaration = document["models"].pop("mdx:fixture")
                document["models"][model_id] = declaration
                with self.assertRaises(StemManifestError) as raised:
                    load_stem_manifest_document(document)
                self.assertEqual(raised.exception.path, ("models", model_id))

            with self.subTest(section="waivers", model_id=model_id):
                document = _manifest()
                reason = document["waivers"].pop("apollo:restoration")
                document["waivers"][model_id] = reason
                with self.assertRaises(StemManifestError) as raised:
                    load_stem_manifest_document(document)
                self.assertEqual(raised.exception.path, ("waivers", model_id))

    def test_bundled_manifest_loads_core_roles_pairs_and_reviewed_catalogue(self) -> None:
        registry = load_stem_manifest(BUNDLED_MANIFEST_PATH)

        self.assertEqual(len(registry.models) + len(registry.waivers), 485)
        self.assertIn(StemRoleId("vocal.vocals"), registry.roles)
        self.assertEqual(
            registry.pairs["pair.center_side"].roles,
            (StemRoleId("spatial.center"), StemRoleId("spatial.side")),
        )

    def test_complete_document_parses_roles_pairs_contexts_outputs_and_waivers(self) -> None:
        registry = load_stem_manifest_document(_manifest())

        self.assertEqual(registry.roles[StemRoleId("vocal.vocals")].display, "Vocals")
        self.assertEqual(
            registry.pairs["pair.vocals_instrumental"].roles,
            (StemRoleId("vocal.vocals"), StemRoleId("mix.instrumental")),
        )
        self.assertEqual(registry.waivers["apollo:restoration"], "no separation stem inventory")
        outputs = registry.models["mdx:fixture"].contexts[StemProcessingContext.FULL_MIX].outputs
        self.assertEqual(outputs[0].production, StemProduction.NATIVE)
        self.assertEqual(outputs[2].production, StemProduction.DERIVED)
        self.assertEqual(outputs[2].complement_of, StemRoleId("vocal.vocals"))

    def test_rejects_invalid_declarations_with_field_paths(self) -> None:
        cases: tuple[tuple[str, object, str], ...] = (
            ("duplicate native", ("models", "mdx:fixture", "native_signature"), "duplicate native"),
            ("duplicate display", ("roles", "vocal.lead", "display"), "duplicate role display"),
            (
                "duplicate filename tag",
                ("roles", "vocal.lead", "filename_tag"),
                "duplicate filename tag",
            ),
            (
                "missing role",
                ("models", "mdx:fixture", "contexts", "full_mix", "outputs", 0, "role"),
                "missing role",
            ),
            (
                "missing pair role",
                ("pairs", "pair.vocals_instrumental", "roles", 1),
                "missing pair role",
            ),
            (
                "missing logical primary",
                ("models", "mdx:fixture", "contexts", "full_mix", "logical_primary"),
                "missing logical primary",
            ),
            (
                "multiple logical primaries",
                ("models", "mdx:fixture", "contexts", "full_mix", "outputs", 1, "role"),
                "multiple logical primaries",
            ),
            (
                "native dependency",
                ("models", "mdx:fixture", "contexts", "full_mix", "outputs", 0, "derived_from"),
                "dependency",
            ),
            (
                "derived dependencies",
                ("models", "mdx:fixture", "contexts", "full_mix", "outputs", 2),
                "exactly one dependency",
            ),
            (
                "missing native",
                ("models", "mdx:fixture", "contexts", "full_mix", "outputs", 0, "native"),
                "missing native key",
            ),
        )

        for label, path, expected in cases:
            document = _manifest()
            if label == "duplicate native":
                document["models"]["mdx:fixture"]["native_signature"] = [  # type: ignore[index]
                    "Vocals",
                    "vocals",
                ]
            elif label == "duplicate display":
                document["roles"]["vocal.lead"]["display"] = "Ｖocals"
            elif label == "duplicate filename tag":
                document["roles"]["vocal.lead"]["filename_tag"] = "VOCALS"  # type: ignore[index]
            elif label == "missing role":
                document["models"]["mdx:fixture"]["contexts"]["full_mix"]["outputs"][0]["role"] = (
                    "vocal.missing"
                )
            elif label == "missing pair role":
                document["pairs"]["pair.vocals_instrumental"]["roles"][1] = "mix.missing"
            elif label == "missing logical primary":
                document["models"]["mdx:fixture"]["contexts"]["full_mix"]["logical_primary"] = (
                    "vocal.lead"
                )
            elif label == "multiple logical primaries":
                document["models"]["mdx:fixture"]["contexts"]["full_mix"]["outputs"][1]["role"] = (
                    "vocal.vocals"
                )
            elif label == "native dependency":
                document["models"]["mdx:fixture"]["contexts"]["full_mix"]["outputs"][0][
                    "derived_from"
                ] = ["vocal.vocals"]
            elif label == "missing native":
                del document["models"]["mdx:fixture"]["contexts"]["full_mix"]["outputs"][0][
                    "native"
                ]
            else:
                output = document["models"]["mdx:fixture"]["contexts"]["full_mix"]["outputs"][2]
                output["derived_from"] = ["vocal.vocals"]

            with (
                self.subTest(label=label),
                self.assertRaisesRegex(StemManifestError, expected) as raised,
            ):
                load_stem_manifest_document(document)
            self.assertIn(str(path[-1]), str(raised.exception))

    def test_accepts_derived_from_as_the_other_valid_derived_dependency_form(self) -> None:
        document = _manifest()
        derived = document["models"]["mdx:fixture"]["contexts"]["full_mix"]["outputs"][2]
        del derived["complement_of"]
        derived["derived_from"] = ["vocal.vocals", "mix.instrumental"]

        registry = load_stem_manifest_document(document)

        output = registry.models["mdx:fixture"].contexts[StemProcessingContext.FULL_MIX].outputs[2]
        self.assertEqual(
            output.derived_from,
            (StemRoleId("vocal.vocals"), StemRoleId("mix.instrumental")),
        )
        self.assertIsNone(output.complement_of)

    def test_rejects_dependency_role_absent_from_the_model_context(self) -> None:
        document = _manifest()
        derived = document["models"]["mdx:fixture"]["contexts"]["full_mix"]["outputs"][2]
        derived["complement_of"] = "vocal.backing"

        with self.assertRaisesRegex(
            StemManifestError, "dependency role is not an output"
        ) as raised:
            load_stem_manifest_document(document)

        self.assertEqual(
            raised.exception.path,
            (
                "models",
                "mdx:fixture",
                "contexts",
                "full_mix",
                "outputs",
                2,
                "complement_of",
            ),
        )


class ExactResolutionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.registry = load_stem_manifest_document(_manifest())

    def test_exact_id_and_complete_unordered_signature_preserve_runtime_native_casing(self) -> None:
        semantics = resolve_model_stem_semantics(
            "mdx:fixture",
            native_stems=("OTHER", "vOcAlS"),
            backend_primary="other",
            registry=self.registry,
        )

        self.assertEqual(semantics.status, StemReviewStatus.REVIEWED)
        self.assertEqual(
            [output.native.raw if output.native else None for output in semantics.outputs],
            ["vOcAlS", "OTHER", None],
        )
        self.assertEqual(
            [output.backend_primary for output in semantics.outputs], [False, True, False]
        )
        self.assertEqual(
            [output.logical_primary for output in semantics.outputs], [True, False, False]
        )

    def test_order_only_signature_change_is_reviewed(self) -> None:
        semantics = resolve_model_stem_semantics(
            "mdx:fixture", native_stems=("Other", "Vocals"), registry=self.registry
        )
        self.assertEqual(semantics.status, StemReviewStatus.REVIEWED)

    def test_cardinality_mismatch_returns_raw_isolated_literals(self) -> None:
        semantics = resolve_model_stem_semantics(
            "mdx:fixture",
            native_stems=("Vocals", "Other", "Extra"),
            registry=self.registry,
        )
        self.assertEqual(semantics.status, StemReviewStatus.RAW)
        self.assertIn("signature-mismatch", semantics.warning)
        self.assertEqual(
            [output.role for output in semantics.outputs],
            [StemLiteral("Vocals"), StemLiteral("Other"), StemLiteral("Extra")],
        )

    def test_missing_context_and_unknown_model_return_raw_with_distinct_diagnostics(self) -> None:
        missing_context_document = _manifest()
        del missing_context_document["models"]["mdx:fixture"]["contexts"]["full_mix"]
        missing_context = resolve_model_stem_semantics(
            "mdx:fixture",
            native_stems=("Vocals", "Other"),
            context=StemProcessingContext("full_mix"),
            registry=load_stem_manifest_document(missing_context_document),
        )
        unknown = resolve_model_stem_semantics(
            "mdx:unknown", native_stems=("Speech",), registry=self.registry
        )
        self.assertIn("missing-context", missing_context.warning)
        self.assertIn("unknown-model", unknown.warning)
        self.assertEqual(unknown.outputs[0].role, StemLiteral("Speech"))

    def test_explicit_vocal_split_context_selects_its_declared_roles(self) -> None:
        semantics = resolve_model_stem_semantics(
            "mdx:fixture",
            native_stems=("Vocals", "Other"),
            context=StemProcessingContext.VOCAL_SPLIT,
            registry=self.registry,
        )
        self.assertEqual(
            [output.role for output in semantics.outputs],
            [StemRoleId("vocal.lead"), StemRoleId("vocal.backing")],
        )


class BundledFallbackTests(unittest.TestCase):
    def test_schema_invalid_bundled_manifest_falls_back_to_raw_semantics(self) -> None:
        self.addCleanup(load_bundled_stem_semantics.cache_clear)
        document = _manifest()
        document["unknown"] = "closed-world violation"
        with TemporaryDirectory() as directory:
            broken = Path(directory) / "model_stem_manifest.json"
            broken.write_text(json.dumps(document), encoding="utf-8")

            with self.assertRaises(StemManifestError):
                load_stem_manifest(broken)

            with (
                patch("core.model_stem_manifest.BUNDLED_MANIFEST_PATH", broken),
                patch("core.model_stem_manifest.log_event") as log_event,
            ):
                load_bundled_stem_semantics.cache_clear()
                registry = load_bundled_stem_semantics()
                semantics = resolve_model_stem_semantics(
                    "mdx:fixture", native_stems=("Vocals", "Other")
                )

            self.assertEqual(registry.models, {})
            self.assertEqual(semantics.status, StemReviewStatus.RAW)
            self.assertEqual(
                [output.role for output in semantics.outputs],
                [StemLiteral("Vocals"), StemLiteral("Other")],
            )
            log_event.assert_called_once()

    def test_invalid_utf8_is_a_typed_direct_error_and_a_single_raw_bundled_fallback(
        self,
    ) -> None:
        self.addCleanup(load_bundled_stem_semantics.cache_clear)
        with TemporaryDirectory() as directory:
            broken = Path(directory) / "model_stem_manifest.json"
            broken.write_bytes(b"\xff")

            with self.assertRaisesRegex(StemManifestError, "could not read manifest"):
                load_stem_manifest(broken)

            with (
                patch("core.model_stem_manifest.BUNDLED_MANIFEST_PATH", broken),
                patch("core.model_stem_manifest.log_event") as log_event,
            ):
                load_bundled_stem_semantics.cache_clear()
                first = load_bundled_stem_semantics()
                raw = resolve_model_stem_semantics("mdx:fixture", native_stems=("Vocals",))
                second = load_bundled_stem_semantics()

            self.assertEqual(first, second)
            self.assertEqual(first.models, {})
            self.assertEqual(raw.status, StemReviewStatus.RAW)
            self.assertEqual(raw.outputs[0].role, StemLiteral("Vocals"))
            log_event.assert_called_once()

    def test_corrupt_bundled_manifest_logs_once_and_returns_raw_but_direct_load_raises(
        self,
    ) -> None:
        self.addCleanup(load_bundled_stem_semantics.cache_clear)
        with TemporaryDirectory() as directory:
            broken = Path(directory) / "model_stem_manifest.json"
            broken.write_text("{invalid", encoding="utf-8")
            with (
                patch("core.model_stem_manifest.BUNDLED_MANIFEST_PATH", broken),
                patch("core.model_stem_manifest.log_event") as log_event,
            ):
                load_bundled_stem_semantics.cache_clear()
                first = load_bundled_stem_semantics()
                second = load_bundled_stem_semantics()

            self.assertEqual(first, second)
            self.assertEqual(first.models, {})
            log_event.assert_called_once()
            with self.assertRaises(StemManifestError):
                load_stem_manifest(broken)


if __name__ == "__main__":
    unittest.main()
