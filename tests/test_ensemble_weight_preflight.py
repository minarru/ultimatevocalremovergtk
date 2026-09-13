"""Excluded members are checked before inference, respecting output selection."""

import unittest

from core.job_diagnostics import ensemble_pair_diagnostics
from core.job_plan_types import ModelDescriptor
from core.settings import Settings
from core.stem_roles import StemRoleId
from core.stems import StemId, StemRoute, StemRouteKind


class EnsembleWeightPreflightTests(unittest.TestCase):
    def setUp(self) -> None:
        self.settings = Settings.defaults()
        self.settings.ensemble.main_stem = "pair.vocals_instrumental"
        vocals = StemRoleId("vocal.vocals")
        instrumental = StemRoleId("mix.instrumental")
        routes = (
            StemRoute(StemId("Vocals"), vocals, "Vocals", "Vocals", StemRouteKind.NATIVE),
            StemRoute(None, instrumental, "Instrumental", "Instrumental", StemRouteKind.DERIVED, complement_of=vocals),
        )
        self.members = tuple(ModelDescriptor(f"mdx:{name}", "mdx", name, name, routes=routes) for name in ("a", "b"))

    def test_zero_weight_blocks_insufficient_contributors(self) -> None:
        self.settings.ensemble.member_weights = {"vocal.vocals": {"mdx:a": 0}}
        diagnostics = ensemble_pair_diagnostics(self.settings, self.members, command="ensemble")
        self.assertEqual([d.code for d in diagnostics], ["ensemble.weights_insufficient"])

    def test_unselected_output_does_not_block(self) -> None:
        self.settings.ensemble.member_weights = {"vocal.vocals": {"mdx:a": 0}}
        self.settings.process.stem_focus = "secondary"
        self.assertEqual(ensemble_pair_diagnostics(self.settings, self.members, command="ensemble"), ())

    def test_derived_residual_uses_native_weights_even_when_only_residual_saved(self) -> None:
        self.settings.ensemble.member_weights = {"vocal.vocals": {"mdx:a": 0}}
        self.settings.process.stem_focus = "secondary"
        self.settings.ensemble.derive_complement_from_mix = True
        diagnostics = ensemble_pair_diagnostics(self.settings, self.members, command="ensemble")
        self.assertEqual([d.code for d in diagnostics], ["ensemble.weights_insufficient"])
