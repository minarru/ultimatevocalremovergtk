"""Audio-level regressions for reviewed stem recipe execution."""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest import mock

import numpy as np

from core.model_config.config import ModelConfig
from core.model_stem_manifest import (
    StemSemanticsRegistry,
    load_bundled_stem_semantics,
    load_stem_manifest_document,
    resolve_model_stem_semantics,
)
from core.settings import Settings
from core.stem_roles import StemReviewStatus
from core.stems import FOCUS_PRIMARY, FOCUS_SECONDARY
from engines.mdx import SeperateMDX


def _staged_classic_registry() -> StemSemanticsRegistry:
    """Strict planned declarations for classic models promoted in Task 5.

    This verifies today's exact resolver/projection/focus seam without making
    Task 3 depend on future bundled declaration work.
    """
    roles = {
        "vocal.vocals": {
            "display": "Vocals",
            "filename_tag": "Vocals",
            "family": "vocal",
        },
        "mix.instrumental": {
            "display": "Instrumental",
            "filename_tag": "Instrumental",
            "family": "mix",
        },
        "effect.reverb": {
            "display": "Reverb",
            "filename_tag": "Reverb",
            "family": "effect",
        },
        "effect.reverb.removed": {
            "display": "Reverb Removed",
            "filename_tag": "Reverb_Removed",
            "family": "effect",
            "removed_of": "effect.reverb",
        },
        "cinematic.crowd": {
            "display": "Crowd",
            "filename_tag": "Crowd",
            "family": "cinematic",
        },
        "cinematic.crowd.removed": {
            "display": "Crowd Removed",
            "filename_tag": "Crowd_Removed",
            "family": "cinematic",
            "removed_of": "cinematic.crowd",
        },
        "instrument.bass": {
            "display": "Bass",
            "filename_tag": "Bass",
            "family": "instrument",
        },
        "instrument.bass.removed": {
            "display": "Bass Removed",
            "filename_tag": "Bass_Removed",
            "family": "instrument",
            "removed_of": "instrument.bass",
        },
        "instrument.drums": {
            "display": "Drums",
            "filename_tag": "Drums",
            "family": "instrument",
        },
        "instrument.drums.removed": {
            "display": "Drums Removed",
            "filename_tag": "Drums_Removed",
            "family": "instrument",
            "removed_of": "instrument.drums",
        },
        "residual.other": {
            "display": "Residual",
            "filename_tag": "Residual",
            "family": "residual",
        },
        "residual.other.removed": {
            "display": "Residual Removed",
            "filename_tag": "Residual_Removed",
            "family": "residual",
            "removed_of": "residual.other",
        },
    }
    models: dict[str, object] = {
        "mdx:Reverb_HQ_By_FoxJoy": {
            "native_signature": ["Reverb", "No Reverb"],
            "intent": "special_fx",
            "contexts": {
                "full_mix": {
                    "logical_primary": "effect.reverb.removed",
                    "outputs": [
                        {"native": "Reverb", "role": "effect.reverb"},
                        {"native": "No Reverb", "role": "effect.reverb.removed"},
                    ],
                }
            },
            "evidence": "staged exact classic runtime review",
        },
        "mdx:UVR-MDX-NET_Crowd_HQ_1": {
            "native_signature": ["No Crowd", "Crowd"],
            "intent": "specialty_stem",
            "contexts": {
                "full_mix": {
                    "logical_primary": "cinematic.crowd.removed",
                    "outputs": [
                        {"native": "No Crowd", "role": "cinematic.crowd.removed"},
                        {"native": "Crowd", "role": "cinematic.crowd"},
                    ],
                }
            },
            "evidence": "staged exact classic runtime review",
        },
    }
    target_roles = {
        "bass": ("instrument.bass", "instrument.bass.removed"),
        "drums": ("instrument.drums", "instrument.drums.removed"),
        "other": ("residual.other", "residual.other.removed"),
        "vocals": ("vocal.vocals", "mix.instrumental"),
    }
    for variant in ("a", "b"):
        for target, (target_role, inverse_role) in target_roles.items():
            primary = target.title()
            inverse = "Instrumental" if target == "vocals" else f"No {primary}"
            models[f"mdx:kuielab_{variant}_{target}"] = {
                "native_signature": [primary, inverse],
                "intent": "specialty_stem",
                "contexts": {
                    "full_mix": {
                        "logical_primary": target_role,
                        "outputs": [
                            {"native": primary, "role": target_role},
                            {"native": inverse, "role": inverse_role},
                        ],
                    }
                },
                "evidence": "staged exact classic runtime review",
            }
    return load_stem_manifest_document(
        {
            "schema_version": 2,
            "roles": roles,
            "pairs": {},
            "models": models,
            "waivers": {},
        }
    )


def _classic_fake(
    *,
    canonical_id: str,
    signature: tuple[str, str],
    backend_primary: str,
    focus: str,
) -> SimpleNamespace:
    mix = np.array(
        [[20.0, 21.0, 22.0, 23.0], [30.0, 31.0, 32.0, 33.0]],
        dtype=np.float32,
    )
    source = np.array(
        [[2.0, 3.0, 4.0, 5.0], [7.0, 8.0, 9.0, 10.0]],
        dtype=np.float32,
    )
    secondary = next(native for native in signature if native != backend_primary)
    settings = Settings.defaults()
    settings.process.stem_focus = focus
    return SimpleNamespace(
        settings=settings,
        canonical_id=canonical_id,
        stem_semantics=None,
        mdx_model_stems=list(signature),
        mdxnet_stems_selected=[],
        demucs_source_list=[],
        mdx_stem_count=2,
        demucs_stem_count=0,
        target_instrument="",
        primary_stem_native=backend_primary,
        primary_model_name="classic-fixture",
        model_cache_key="classic-fixture",
        primary_sources=(mix, source),
        load_cached_sources=lambda: None,
        primary_stem=backend_primary,
        secondary_stem=secondary,
        secondary_source=None,
        primary_source=None,
        secondary_source_primary=None,
        secondary_source_secondary=None,
        is_match_frequency_pitch=False,
        is_secondary_model_activated=False,
        secondary_model=None,
        is_invert_spec=False,
        process_secondary_stem=lambda stem, secondary=None: stem,
        is_vocal_split_model=False,
        is_secondary_model=False,
        is_pre_proc_model=False,
        is_inst_only_voc_splitter=False,
        is_sec_bv_rebalance=False,
        is_ensemble_mode=False,
        is_karaoke=False,
        is_bv_model=False,
        primary_mix=mix,
        primary_demix=source,
    )


class ClassicMdxReviewedRoutingTests(unittest.TestCase):
    CASES = (
        (
            "default",
            "mdx:UVR_MDXNET_Main",
            ("Instrumental", "Vocals"),
            "Vocals",
            "",
            ("Vocals", "Instrumental"),
        ),
        (
            "primary-only",
            "mdx:UVR_MDXNET_Main",
            ("Instrumental", "Vocals"),
            "Vocals",
            FOCUS_PRIMARY,
            ("Vocals",),
        ),
        (
            "inverse-only",
            "mdx:UVR_MDXNET_Main",
            ("Instrumental", "Vocals"),
            "Vocals",
            FOCUS_SECONDARY,
            ("Instrumental",),
        ),
        (
            "karaoke",
            "mdx:UVR_MDXNET_KARA_2",
            ("Instrumental", "Vocals"),
            "Instrumental",
            "",
            ("Vocals", "Instrumental"),
        ),
        (
            "reverb",
            "mdx:Reverb_HQ_By_FoxJoy",
            ("Reverb", "No Reverb"),
            "Reverb",
            "",
            ("No Reverb", "Reverb"),
        ),
        (
            "crowd",
            "mdx:UVR-MDX-NET_Crowd_HQ_1",
            ("No Crowd", "Crowd"),
            "No Crowd",
            "",
            ("No Crowd", "Crowd"),
        ),
        (
            "kuielab-a-bass",
            "mdx:kuielab_a_bass",
            ("Bass", "No Bass"),
            "Bass",
            "",
            ("Bass", "No Bass"),
        ),
        (
            "kuielab-b-bass",
            "mdx:kuielab_b_bass",
            ("Bass", "No Bass"),
            "Bass",
            "",
            ("Bass", "No Bass"),
        ),
        (
            "kuielab-a-drums",
            "mdx:kuielab_a_drums",
            ("Drums", "No Drums"),
            "Drums",
            "",
            ("Drums", "No Drums"),
        ),
        (
            "kuielab-b-drums",
            "mdx:kuielab_b_drums",
            ("Drums", "No Drums"),
            "Drums",
            "",
            ("Drums", "No Drums"),
        ),
        (
            "kuielab-a-other",
            "mdx:kuielab_a_other",
            ("Other", "No Other"),
            "Other",
            "",
            ("Other", "No Other"),
        ),
        (
            "kuielab-b-other",
            "mdx:kuielab_b_other",
            ("Other", "No Other"),
            "Other",
            "",
            ("Other", "No Other"),
        ),
        (
            "kuielab-a-vocals",
            "mdx:kuielab_a_vocals",
            ("Vocals", "Instrumental"),
            "Vocals",
            "",
            ("Vocals", "Instrumental"),
        ),
        (
            "kuielab-b-vocals",
            "mdx:kuielab_b_vocals",
            ("Vocals", "Instrumental"),
            "Vocals",
            "",
            ("Vocals", "Instrumental"),
        ),
    )

    @classmethod
    def setUpClass(cls) -> None:
        cls.staged_registry = _staged_classic_registry()

    def test_classic_focus_resolves_reviewed_routes_to_exact_engine_keys(self) -> None:
        bundled = load_bundled_stem_semantics()
        bundled_ids = {"mdx:UVR_MDXNET_Main", "mdx:UVR_MDXNET_KARA_2"}

        def _resolver_for(registry: StemSemanticsRegistry):
            def _resolve_exact(model_id: str, **kwargs: object):
                return resolve_model_stem_semantics(
                    model_id,
                    registry=registry,
                    **kwargs,  # type: ignore[arg-type]
                )

            return _resolve_exact

        for name, model_id, signature, backend_primary, focus, selected_natives in self.CASES:
            with self.subTest(case=name):
                registry = bundled if model_id in bundled_ids else self.staged_registry
                fake = _classic_fake(
                    canonical_id=model_id,
                    signature=signature,
                    backend_primary=backend_primary,
                    focus=focus,
                )

                with (
                    mock.patch("core.stems.resolve_model_stem_semantics", _resolver_for(registry)),
                    mock.patch("core.stems.load_bundled_stem_semantics", return_value=registry),
                ):
                    ModelConfig._apply_stem_focus(fake)  # type: ignore[arg-type]

                self.assertEqual(fake.stem_semantics.status, StemReviewStatus.REVIEWED)
                selected = tuple(fake.selected_stem_routes)
                self.assertEqual(
                    {route.native.raw for route in selected if route.native is not None},
                    set(selected_natives),
                )
                if name in {"default", "primary-only", "inverse-only"}:
                    self.assertEqual(fake.stem_semantics.model_id, "mdx:UVR_MDXNET_Main")
                    self.assertEqual(
                        fake.stem_semantics.evidence,
                        "catalogue_id=mdx:UVR_MDXNET_Main; source=TRvlvr+Politrees; "
                        "metadata_source=community_models.txt; "
                        "native_signature=instrumental|vocals; backend_primary=Vocals; "
                        "backend_target=vocals; reviewed_contexts=full_mix",
                    )
                    self.assertEqual(fake.primary_stem, "Vocals")
                    self.assertEqual(
                        {
                            output.native.raw: output.backend_primary
                            for output in fake.stem_semantics.outputs
                            if output.native is not None
                        },
                        {"Instrumental": False, "Vocals": True},
                    )

                plan = SeperateMDX.seperate(fake)  # type: ignore[arg-type]

                engine_secondary = next(native for native in signature if native != backend_primary)
                expected_keys = tuple(
                    native
                    for native in (engine_secondary, backend_primary)
                    if native in selected_natives
                )
                self.assertEqual(tuple(plan.sources), expected_keys)
                semantic_only_keys = {
                    route.concept
                    for route in selected
                    if route.native is not None and route.concept != route.native.raw
                }
                self.assertFalse(semantic_only_keys.intersection(plan.sources))
                presentation_only_keys = {
                    value
                    for route in selected
                    if route.native is not None
                    for value in (route.label, route.filename_tag)
                    if value != route.native.raw
                }
                self.assertFalse(presentation_only_keys.intersection(plan.sources))
                if engine_secondary in selected_natives:
                    np.testing.assert_array_equal(
                        plan.sources[engine_secondary],
                        (fake.primary_mix - fake.primary_demix).T,
                    )
                if backend_primary in selected_natives:
                    np.testing.assert_array_equal(
                        plan.sources[backend_primary],
                        fake.primary_demix.T,
                    )


if __name__ == "__main__":
    unittest.main()
