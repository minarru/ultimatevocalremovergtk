"""Audio-level regressions for reviewed stem recipe execution."""

from __future__ import annotations

import unittest
from types import SimpleNamespace

import numpy as np

from core.stem_roles import StemRoleId
from core.stems import StemId, StemRoute, StemRouteKind
from engines.mdx import SeperateMDX


def _classic_route(native: str, role: str, *, primary: bool) -> StemRoute:
    return StemRoute(
        native=StemId(native),
        role=StemRoleId(role),
        label=f"Presentation {role}",
        filename_tag=f"Filename_{role}",
        kind=StemRouteKind.NATIVE,
        logical_primary=primary,
    )


def _classic_fake(
    primary: str,
    inverse: str,
    routes: tuple[StemRoute, ...],
    selected: tuple[StemRoute, ...],
) -> SimpleNamespace:
    mix = np.array(
        [[20.0, 21.0, 22.0, 23.0], [30.0, 31.0, 32.0, 33.0]],
        dtype=np.float32,
    )
    source = np.array(
        [[2.0, 3.0, 4.0, 5.0], [7.0, 8.0, 9.0, 10.0]],
        dtype=np.float32,
    )
    return SimpleNamespace(
        primary_model_name="classic-fixture",
        model_cache_key="classic-fixture",
        primary_sources=(mix, source),
        load_cached_sources=lambda: None,
        primary_stem=primary,
        secondary_stem=inverse,
        secondary_source=None,
        primary_source=None,
        secondary_source_primary=None,
        secondary_source_secondary=None,
        is_match_frequency_pitch=False,
        is_secondary_model_activated=False,
        secondary_model=None,
        is_invert_spec=False,
        process_secondary_stem=lambda stem, secondary=None: stem,
        available_stem_routes=routes,
        selected_stem_routes=selected,
        is_vocal_split_model=False,
        is_secondary_model=False,
        is_pre_proc_model=False,
        is_inst_only_voc_splitter=False,
        is_sec_bv_rebalance=False,
        is_ensemble_mode=False,
        primary_mix=mix,
        primary_demix=source,
    )


class ClassicMdxReviewedRoutingTests(unittest.TestCase):
    CASES = (
        ("default", "Vocals", "Instrumental", "vocal.vocals", "mix.instrumental", "both"),
        ("primary-only", "Vocals", "Instrumental", "vocal.vocals", "mix.instrumental", "primary"),
        ("inverse-only", "Vocals", "Instrumental", "vocal.vocals", "mix.instrumental", "inverse"),
        (
            "karaoke",
            "Instrumental",
            "Vocals",
            "mix.instrumental_with_backing_vocals",
            "vocal.lead",
            "both",
        ),
        ("reverb", "Reverb", "No Reverb", "effect.reverb", "effect.reverb.removed", "both"),
        (
            "crowd",
            "No Crowd",
            "Crowd",
            "cinematic.crowd.removed",
            "cinematic.crowd",
            "both",
        ),
        ("kuielab-a-bass", "Bass", "No Bass", "instrument.bass", "instrument.bass.removed", "both"),
        ("kuielab-b-bass", "Bass", "No Bass", "instrument.bass", "instrument.bass.removed", "both"),
        (
            "kuielab-a-drums",
            "Drums",
            "No Drums",
            "instrument.drums",
            "instrument.drums.removed",
            "both",
        ),
        (
            "kuielab-b-drums",
            "Drums",
            "No Drums",
            "instrument.drums",
            "instrument.drums.removed",
            "both",
        ),
        (
            "kuielab-a-other",
            "Other",
            "No Other",
            "residual.other",
            "residual.other.removed",
            "both",
        ),
        (
            "kuielab-b-other",
            "Other",
            "No Other",
            "residual.other",
            "residual.other.removed",
            "both",
        ),
        ("kuielab-a-vocals", "Vocals", "Instrumental", "vocal.vocals", "mix.instrumental", "both"),
        ("kuielab-b-vocals", "Vocals", "Instrumental", "vocal.vocals", "mix.instrumental", "both"),
    )

    def test_classic_reviewed_routes_keep_both_exact_engine_source_keys(self) -> None:
        for name, primary, inverse, primary_role, inverse_role, selection in self.CASES:
            with self.subTest(case=name):
                primary_route = _classic_route(primary, primary_role, primary=True)
                inverse_route = _classic_route(inverse, inverse_role, primary=False)
                routes = (primary_route, inverse_route)
                if selection == "primary":
                    selected = (primary_route,)
                elif selection == "inverse":
                    selected = (inverse_route,)
                else:
                    selected = routes
                fake = _classic_fake(primary, inverse, routes, selected)

                plan = SeperateMDX.seperate(fake)  # type: ignore[arg-type]

                expected_keys = [route.native.raw for route in selected if route.native is not None]
                self.assertEqual(list(plan.sources), list(reversed(expected_keys)))
                self.assertFalse(
                    {route.label for route in routes}.intersection(plan.sources),
                    "presentation labels must never become classic backend source keys",
                )
                self.assertFalse(
                    {route.filename_tag for route in routes}.intersection(plan.sources),
                    "filename tags must never become classic backend source keys",
                )
                if inverse_route in selected:
                    np.testing.assert_array_equal(
                        plan.sources[inverse],
                        (fake.primary_mix - fake.primary_demix).T,
                    )
                if primary_route in selected:
                    np.testing.assert_array_equal(plan.sources[primary], fake.primary_demix.T)


if __name__ == "__main__":
    unittest.main()
