"""Strict loading and exact resolution for reviewed stem semantics."""

from __future__ import annotations

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
        "schema_version": 1,
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
    def test_reviewed_two_output_pairs_and_multistem_residuals_remain_distinct(self) -> None:
        registry = load_stem_manifest(BUNDLED_MANIFEST_PATH)
        for model_id, declaration in registry.models.items():
            outputs = declaration.contexts[StemProcessingContext.FULL_MIX].outputs
            roles = {str(output.role) for output in outputs}
            native_stems = [
                output.native.raw.casefold() if output.native else "" for output in outputs
            ]
            if len(declaration.native_signature) == 2:
                self.assertNotIn("residual.other", roles, model_id)
            elif "other" in {native.casefold() for native in declaration.native_signature}:
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

        self.assertEqual(len(registry.models) + len(registry.waivers), 484)
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

        self.assertEqual(len(registry.models) + len(registry.waivers), 484)
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
