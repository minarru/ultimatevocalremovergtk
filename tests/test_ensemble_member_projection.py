"""Member projection is independent of GTK and Settings persistence."""

import unittest

from core.model_identity import ModelArtifacts, ModelRecord
from ui.ensemble.member_projection import project_members


def record(name: str, display: str):
    return ModelRecord(f'mdx:{name}', 'mdx', name, display, name, ModelArtifacts(name), True)


class MemberProjectionTests(unittest.TestCase):
    def test_order_pruning_and_duplicate_selection(self):
        rows = (record('z', 'Alpha'), record('a', 'Zulu'))
        result = project_members(
            rows,
            ['mdx:a', 'mdx:z', 'mdx:a', 'mdx:missing'],
            pair_id='pair.vocals',
            eligible_ids={'mdx:a', 'mdx:z'},
        )
        self.assertEqual(result.selected_ids, ('mdx:z', 'mdx:a'))
        self.assertTrue(result.reconcile_after_render)
        self.assertIn('not installed', result.warnings[0])

    def test_malformed_members_are_not_hashed(self):
        result = project_members((), [{}, []], pair_id='pair.vocals', eligible_ids=set())
        self.assertEqual(len(result.warnings), 2)
        self.assertFalse(result.reconcile_after_render)

    def test_previously_gated_member_requires_explicit_pick(self):
        result = project_members(
            (record('a', 'Alpha'),),
            ['mdx:a'],
            pair_id='pair.vocals',
            eligible_ids={'mdx:a'},
            prior_gated_ids=('mdx:a',),
        )
        self.assertEqual(result.selected_ids, ())
        self.assertIn('now available; pick it', result.warnings[0])

    def test_early_return_preserves_gate_record(self):
        result = project_members((), ['mdx:a'], pair_id='', eligible_ids=None)
        self.assertEqual(result.placeholder, 'Choose a stem pair to list models')
        self.assertFalse(result.replace_gate)
        self.assertFalse(result.reconcile_after_render)
