"""Installed picker contracts independent of GTK and catalogue networking."""

import unittest
from dataclasses import replace
from types import SimpleNamespace
from typing import Any

from core.model_identity import CatalogueRef, ModelArtifacts, ModelRecord
from ui.model_picker_state import PickerFilters, project_installed, visible_models


def record(name: str = 'a', **changes: Any) -> ModelRecord:
    base = ModelRecord(
        id='vr:' + name,
        family='vr',
        basename=name,
        display=name,
        backend_name=name,
        artifacts=ModelArtifacts(name + '.pth'),
        installed=True,
        catalogue_entry=CatalogueRef('vr', name),
    )
    return replace(base, **changes)


class ModelPickerStateTests(unittest.TestCase):
    def test_only_installed_separation_models_and_exact_metadata_association(self):
        meta = SimpleNamespace(stems=('Vocals',), intent='vocals')
        snapshot = SimpleNamespace(
            meta_by_family={'vr': {'a': meta}, 'mdx': {'a': None}}, unsupported={}
        )
        rows = project_installed(
            [record(), record('remote', installed=False), record('apollo', family='apollo')],
            snapshot,
            {},
        )
        self.assertEqual([r.id for r in rows], ['vr:a'])
        self.assertEqual(rows[0].outputs, 'Raw outputs: Vocals')
        self.assertNotIn('VR', rows[0].subtitle('all'))

    def test_filtering_never_recovers_identity_from_display(self):
        rows = project_installed(
            [record('a', display='Identical'), record('b', display='Identical')], None, {}
        )
        found = visible_models(rows, PickerFilters(query='identical'))
        self.assertEqual({r.id for r in found}, {'vr:a', 'vr:b'})
        self.assertEqual(visible_models(rows, PickerFilters(architecture='demucs')), [])

    def test_incomplete_identity_visible_only_when_supported_filter_disabled(self):
        rows = project_installed(
            [record(identity_complete=False, identity_error='Missing YAML')], None, {}
        )
        self.assertEqual(visible_models(rows, PickerFilters()), [])
        self.assertEqual(
            visible_models(rows, PickerFilters(supported_only=False))[0].reason, 'Missing YAML'
        )

    def test_missing_scores_last_both_directions_and_purpose_specific(self):
        rows = project_installed(
            [record('vocals a'), record('vocals b'), record('vocals c')],
            None,
            {'vocals a.pth': {'vocals': 10}, 'vocals b.pth': {'vocals': 12}},
        )
        for descending, expected in [
            (True, ['vr:vocals b', 'vr:vocals a', 'vr:vocals c']),
            (False, ['vr:vocals a', 'vr:vocals b', 'vr:vocals c']),
        ]:
            filters = PickerFilters(purpose='vocals', by_score=True, descending=descending)
            self.assertEqual([r.id for r in visible_models(rows, filters)], expected)
        self.assertIsNone(rows[0].score('instrumental'))

    def test_snapshot_unsupported_reasons_are_family_scoped(self):
        snapshot = SimpleNamespace(
            meta_by_family={}, unsupported={record().arch: [('a', 'Unsupported network')]}
        )
        rows = project_installed([record()], snapshot, {})
        self.assertEqual(rows[0].reason, 'Unsupported network')
