from __future__ import annotations

import unittest

from core.ensemble_pair_consistent import (
    PairConsistentPlan,
    resolve_pair_consistent_plan,
)
from core.stem_roles import StemLiteral, StemRoleId
from core.stems import StemId, StemRoute, StemRouteKind

VOCALS = StemRoleId("vocal.vocals")
INST = StemRoleId("mix.instrumental")
LEAD = StemRoleId("vocal.lead")
KARAOKE_INST = StemRoleId("mix.instrumental_with_backing_vocals")
CENTER = StemRoleId("spatial.center")
SIDE = StemRoleId("spatial.side")


def _native(role: StemRoleId, key: str) -> StemRoute:
    return StemRoute(StemId(key), role, key, key, StemRouteKind.NATIVE)


def _complement(role: StemRoleId, of_role: StemRoleId) -> StemRoute:
    return StemRoute(
        None,
        role,
        str(role),
        str(role),
        StemRouteKind.DERIVED,
        complement_of=of_role,
    )


class ResolvePairConsistentPlanTests(unittest.TestCase):
    def test_voc_primary_members_stack_vocals(self) -> None:
        members = (
            (_native(VOCALS, "vocals"), _complement(INST, VOCALS)),
            (_native(VOCALS, "vocals"), _complement(INST, VOCALS)),
        )
        self.assertEqual(
            resolve_pair_consistent_plan((VOCALS, INST), members),
            PairConsistentPlan(VOCALS, INST),
        )

    def test_karaoke_stacks_lead_not_pair_slot_zero(self) -> None:
        members = (
            (_complement(KARAOKE_INST, LEAD), _native(LEAD, "vocals")),
            (_complement(KARAOKE_INST, LEAD), _native(LEAD, "vocals")),
        )
        plan = resolve_pair_consistent_plan((KARAOKE_INST, LEAD), members)
        self.assertEqual(plan, PairConsistentPlan(LEAD, KARAOKE_INST))

    def test_dual_native_center_side_is_noop(self) -> None:
        members = (
            (_native(CENTER, "mid"), _native(SIDE, "side")),
            (_native(CENTER, "mid"), _native(SIDE, "side")),
        )
        self.assertIsNone(resolve_pair_consistent_plan((CENTER, SIDE), members))

    def test_center_only_models_derive_side(self) -> None:
        members = (
            (_native(CENTER, "center"), _complement(SIDE, CENTER)),
            (_native(CENTER, "center"), _complement(SIDE, CENTER)),
        )
        self.assertEqual(
            resolve_pair_consistent_plan((CENTER, SIDE), members),
            PairConsistentPlan(CENTER, SIDE),
        )

    def test_wide_primary_stacks_side(self) -> None:
        members = (
            (_complement(CENTER, SIDE), _native(SIDE, "wide")),
            (_complement(CENTER, SIDE), _native(SIDE, "wide")),
        )
        self.assertEqual(
            resolve_pair_consistent_plan((CENTER, SIDE), members),
            PairConsistentPlan(SIDE, CENTER),
        )

    def test_mixed_voc_and_inst_primary_is_noop(self) -> None:
        members = (
            (_native(VOCALS, "vocals"), _complement(INST, VOCALS)),
            (_complement(VOCALS, INST), _native(INST, "instrumental")),
        )
        self.assertIsNone(resolve_pair_consistent_plan((VOCALS, INST), members))

    def test_raw_literal_does_not_count_as_native_role(self) -> None:
        raw = StemRoute(
            StemId("Vocals"),
            StemLiteral("Vocals"),
            "Vocals",
            "Vocals",
            StemRouteKind.NATIVE,
        )
        members = ((raw, _complement(INST, VOCALS)), (_native(VOCALS, "vocals"),))
        self.assertIsNone(resolve_pair_consistent_plan((VOCALS, INST), members))

    def test_one_native_predictor_is_noop(self) -> None:
        members = ((_native(VOCALS, "vocals"), _complement(INST, VOCALS)),)
        self.assertIsNone(resolve_pair_consistent_plan((VOCALS, INST), members))


class DeriveComplementSettingTests(unittest.TestCase):
    def test_default_is_false(self) -> None:
        from core.settings import Settings

        self.assertFalse(Settings.defaults().ensemble.derive_complement_from_mix)

    def test_set_path_coerces_and_flat_key_round_trips(self) -> None:
        from core.settings import Settings
        from core.settings.access import get_flat, set_flat, set_path

        settings = Settings.defaults()
        set_path(settings, "ensemble.derive_complement_from_mix", "true")
        self.assertTrue(settings.ensemble.derive_complement_from_mix)
        self.assertTrue(get_flat(settings, "is_derive_complement_from_mix"))
        set_flat(settings, "is_derive_complement_from_mix", False)
        self.assertFalse(settings.ensemble.derive_complement_from_mix)
