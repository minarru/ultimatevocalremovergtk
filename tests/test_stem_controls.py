"""Direct stem controls preserve the existing settings and output contracts."""

from __future__ import annotations

import unittest
from copy import deepcopy
from dataclasses import replace

from bundled.constants import ALL_STEMS
from core.settings import Settings
from core.stem_roles import StemId, StemLiteral, StemRoleId
from core.stem_selection import StemSelectionState
from core.stems import StemRoute, StemRouteKind
from ui.stem_controls import StemControls


def native(key: str, role: str, label: str = '') -> StemRoute:
    return StemRoute(StemId(key), StemRoleId(role), label=label or key)


def subset_state(routes: tuple[StemRoute, ...]) -> StemSelectionState:
    state = StemSelectionState()
    state.configure_subset(
        stems=[r.native.raw for r in routes if r.native],
        primary_key='is_primary_stem_only',
        secondary_key='is_secondary_stem_only',
    )
    state.routes = routes
    return state


def demucs_state(
    count: int = 4, *, raw: bool = False, scope: str = 'scope-a'
) -> StemSelectionState:
    keys = ('vocals', 'drums', 'bass', 'other', 'guitar', 'piano')[:count]
    roles = (
        'vocal.vocals',
        'instrument.drums',
        'instrument.bass',
        'residual.other',
        'instrument.guitar',
        'instrument.piano',
    )[:count]
    state = StemSelectionState()
    state.configure_demucs(
        focus_stems=[ALL_STEMS, *keys],
        primary_key='is_primary_stem_only',
        secondary_key='is_secondary_stem_only',
        demucs_stem_count=count,
    )
    state.routes = tuple(
        StemRoute(StemId(key), StemLiteral(key), label=key.title(), selection_scope=scope)
        if raw
        else native(key, role, key.title())
        for key, role in zip(keys, roles, strict=True)
    )
    return state


def karaoke_routes() -> tuple[StemRoute, ...]:
    return (
        native('Lead', 'vocal.lead', 'Lead Vocals'),
        native('Backing', 'vocal.backing', 'Backing Vocals'),
        native('Instrumental', 'mix.instrumental'),
        StemRoute(
            None,
            StemRoleId('mix.instrumental_with_backing_vocals'),
            label='Instrumental with Backing Vocals',
            kind=StemRouteKind.DERIVED,
            selected_by_default=False,
            derived_from=(StemRoleId('vocal.backing'), StemRoleId('mix.instrumental')),
        ),
    )


class StemControlsTests(unittest.TestCase):
    def controller(
        self, state: StemSelectionState, settings: Settings | None = None
    ) -> StemControls:
        controls = StemControls(state, model_id='mdx:test')
        controls.sync_from_settings(settings or Settings.defaults())
        return controls

    def test_last_selected_output_cannot_be_unchecked(self):
        settings = Settings.defaults()
        controls = self.controller(subset_state(karaoke_routes()), settings)
        for choice in controls.snapshot().choices[1:]:
            self.assertTrue(controls.toggle_output(choice.id, False))
        controls.persist_to_settings(settings)
        before = deepcopy(settings)
        last = controls.snapshot().choices[0]
        self.assertFalse(controls.toggle_output(last.id, False))
        controls.persist_to_settings(settings)
        self.assertEqual(settings, before)
        self.assertEqual(controls.snapshot().main_count, 1)

    def test_default_excludes_optional_output_and_derived_clears_sidecar(self):
        settings = Settings.defaults()
        controls = self.controller(subset_state(karaoke_routes()), settings)
        self.assertEqual(controls.snapshot().main_count, 3)
        self.assertEqual(len(controls.snapshot().choices), 3)
        for choice in controls.snapshot().choices[1:]:
            controls.toggle_output(choice.id, False)
        controls.persist_to_settings(settings)
        self.assertEqual(settings.mdx.stems_selected, ['Lead'])
        combined = controls.snapshot().modes[1][0]
        self.assertTrue(controls.choose_mode(combined))
        self.assertEqual(controls.snapshot().main_count, 1)
        controls.persist_to_settings(settings)
        self.assertEqual(settings.process.stem_focus, 'mix.instrumental_with_backing_vocals')
        self.assertEqual(settings.mdx.stems_selected, [])
        self.assertEqual(settings.mdx.stems, ALL_STEMS)
        controls.sync_from_settings(settings)
        self.assertEqual(controls.snapshot().mode, 'derived')
        self.assertTrue(controls.choose_mode('native_subset'))
        self.assertEqual(
            [
                c.route.native.raw
                for c in controls.snapshot().choices
                if c.selected and c.route.native
            ],
            ['Lead'],
        )

    def test_sync_and_open_do_not_rewrite_imported_positional_settings(self):
        state = StemSelectionState()
        state.configure_exclusive(
            primary_stem='Vocals',
            secondary_stem='Instrumental',
            primary_key='is_primary_stem_only',
            secondary_key='is_secondary_stem_only',
        )
        settings = Settings.defaults()
        settings.process.stem_focus = 'secondary'
        before = deepcopy(settings)
        controls = self.controller(state, settings)
        self.assertEqual(controls.snapshot().main_count, 1)
        controls.persist_to_settings(settings)
        self.assertEqual(settings, before)

    def test_label_refresh_preserves_selection_but_rejects_old_callbacks(self):
        routes = karaoke_routes()
        controls = self.controller(subset_state(routes))
        for choice in controls.snapshot().choices[1:]:
            controls.toggle_output(choice.id, False)
        before = controls.snapshot()
        controls.configure(
            'mdx:test', subset_state(tuple(replace(r, label='Renamed') for r in routes))
        )
        after = controls.snapshot()
        self.assertEqual(after.selected_ids, before.selected_ids)
        self.assertEqual(after.summary, 'Renamed')
        self.assertFalse(
            controls.toggle_output(after.choices[1].id, True, revision=before.revision)
        )
        self.assertFalse(after.review_required)

    def test_removed_selection_requires_explicit_replacement(self):
        routes = karaoke_routes()
        controls = self.controller(subset_state(routes))
        for choice in controls.snapshot().choices[1:]:
            controls.toggle_output(choice.id, False)
        controls.configure('mdx:test', subset_state(routes[1:3]))
        self.assertTrue(controls.snapshot().review_required)
        self.assertEqual(controls.snapshot().main_count, 0)
        self.assertTrue(controls.toggle_output(controls.snapshot().choices[0].id, True))
        self.assertFalse(controls.snapshot().review_required)
        self.assertEqual(controls.snapshot().main_count, 1)

    def test_same_labels_remain_distinct_and_specialists_have_no_vocal_presets(self):
        routes = (
            native('alto', 'vocal.alto', 'Voice'),
            native('bass', 'vocal.bass', 'Voice'),
            native('tenor', 'vocal.tenor', 'Voice'),
        )
        settings = Settings.defaults()
        controls = self.controller(subset_state(routes), settings)
        self.assertEqual(len({c.id for c in controls.snapshot().choices}), 3)
        self.assertEqual([p[0] for p in controls.snapshot().presets], ['all'])
        controls.toggle_output(controls.snapshot().choices[0].id, False)
        controls.persist_to_settings(settings)
        self.assertEqual(settings.mdx.stems_selected, ['bass', 'tenor'])

    def test_scoped_raw_focus_is_read_and_scope_change_requires_review(self):
        routes = tuple(
            StemRoute(StemId(key), StemLiteral(key), label=key, selection_scope='scope-a')
            for key in ('One', 'Two', 'Three')
        )
        settings = Settings.defaults()
        settings.process.stem_focus = 'raw:two#scope=scope-a'
        controls = self.controller(subset_state(routes), settings)
        self.assertEqual(controls.snapshot().summary, 'Two')
        controls.configure(
            'mdx:test', subset_state(tuple(replace(r, selection_scope='scope-b') for r in routes))
        )
        self.assertTrue(controls.snapshot().review_required)
        controls.sync_from_settings(settings)
        self.assertTrue(controls.snapshot().review_required)

    def test_unknown_focus_and_removed_sidecar_do_not_silently_select_all(self):
        for focus, sidecar in [('vocal.removed', []), ('', ['Missing'])]:
            with self.subTest(focus=focus):
                settings = Settings.defaults()
                settings.process.stem_focus = focus
                settings.mdx.stems_selected = sidecar
                controls = self.controller(subset_state(karaoke_routes()), settings)
                self.assertTrue(controls.snapshot().review_required)
                self.assertEqual(controls.snapshot().main_count, 0)
                self.assertTrue(controls.select_all())
                self.assertFalse(controls.snapshot().review_required)

    def test_large_inventory_preserves_sparse_native_order_and_round_trip(self):
        routes = tuple(
            StemRoute(
                StemId(f'Source {i}'),
                StemLiteral(f'source {i}'),
                label=f'Source {i}',
                selection_scope='53',
            )
            for i in range(53)
        )
        settings = Settings.defaults()
        controls = self.controller(subset_state(routes), settings)
        for i, choice in enumerate(controls.snapshot().choices):
            if i not in (0, 23, 52):
                controls.toggle_output(choice.id, False)
        controls.persist_to_settings(settings)
        self.assertEqual(settings.mdx.stems_selected, ['Source 0', 'Source 23', 'Source 52'])
        controls.sync_from_settings(settings)
        self.assertEqual(controls.snapshot().main_count, 3)
        controls.select_all()
        self.assertEqual(controls.snapshot().main_count, 53)

    def test_unsafe_native_sidecar_toggle_is_disabled_and_rejected(self):
        from tests.stem_control_cases import KARAOKE_THREE, selection_state

        settings = Settings.defaults()
        controls = self.controller(selection_state(KARAOKE_THREE), settings)
        lead = next(c for c in controls.snapshot().choices if c.route.concept == 'vocal.lead')
        self.assertFalse(lead.enabled)
        self.assertIn('not supported', lead.explanation)
        self.assertFalse(controls.toggle_output(lead.id, False))
        self.assertEqual(controls.snapshot().main_count, 3)
        instrumental = next(
            c for c in controls.snapshot().choices if c.route.concept == 'mix.instrumental'
        )
        self.assertTrue(controls.toggle_output(instrumental.id, False))
        lead = next(c for c in controls.snapshot().choices if c.route.concept == 'vocal.lead')
        self.assertTrue(lead.enabled)
        self.assertTrue(controls.toggle_output(lead.id, False))
        controls.persist_to_settings(settings)
        self.assertEqual(settings.process.stem_focus, 'vocal.backing')

    def test_recipe_refresh_updates_note_without_overwriting_selection(self):
        settings = Settings.defaults()
        controls = self.controller(subset_state(karaoke_routes()), settings)
        for choice in controls.snapshot().choices[1:]:
            controls.toggle_output(choice.id, False)
        before = controls.snapshot().selected_ids
        settings.mdx.is_mdx_include_stem_complement = True
        controls.refresh_options(settings)
        self.assertTrue(controls.snapshot().additional_output_note)
        self.assertEqual(controls.snapshot().selected_ids, before)
        settings.mdx.is_mdx_include_stem_complement = False
        controls.refresh_options(settings)
        self.assertFalse(controls.snapshot().additional_output_note)

    def test_same_model_layout_change_keeps_removed_selection_review(self):
        routes = tuple(
            StemRoute(StemId(key), StemLiteral(key), label=key, selection_scope='scope')
            for key in ('One', 'Two', 'Three')
        )
        settings = Settings.defaults()
        settings.mdx.stems_selected = ['Three']
        controls = self.controller(subset_state(routes), settings)
        self.assertEqual(controls.snapshot().summary, 'Three')
        pair = StemSelectionState()
        pair.configure_exclusive(
            primary_stem='One',
            secondary_stem='Two',
            primary_key='is_primary_stem_only',
            secondary_key='is_secondary_stem_only',
        )
        pair.routes = routes[:2]
        controls.configure('mdx:test', pair)
        controls.sync_from_settings(settings)
        self.assertTrue(controls.snapshot().review_required)
        self.assertEqual(controls.snapshot().main_count, 0)

    def test_return_to_native_discards_removed_temporary_subset(self):
        routes = karaoke_routes()
        controls = self.controller(subset_state(routes))
        for choice in controls.snapshot().choices[1:]:
            controls.toggle_output(choice.id, False)
        controls.choose_mode(controls.snapshot().modes[1][0])
        controls.configure('mdx:test', subset_state(routes[1:]))
        self.assertTrue(controls.choose_mode('native_subset'))
        self.assertEqual(controls.snapshot().main_count, 2)
        self.assertFalse(controls.snapshot().review_required)

    def test_imported_unsafe_native_subset_requires_review(self):
        from tests.stem_control_cases import KARAOKE_THREE, selection_state

        settings = Settings.defaults()
        settings.mdx.stems_selected = ['backing_vocal', 'instrumental']
        before = deepcopy(settings)
        controls = self.controller(selection_state(KARAOKE_THREE), settings)
        self.assertTrue(controls.snapshot().review_required)
        self.assertEqual(controls.snapshot().main_count, 0)
        controls.persist_to_settings(settings)
        self.assertEqual(settings, before)
        self.assertTrue(controls.select_all())
        controls.persist_to_settings(settings)
        self.assertEqual(settings.mdx.stems_selected, [])

    def test_demucs_native_subsets_round_trip_for_four_and_six_sources(self):
        for count in (4, 6):
            for raw in (False, True):
                with self.subTest(count=count, raw=raw):
                    settings = Settings.defaults()
                    controls = self.controller(demucs_state(count, raw=raw), settings)
                    snapshot = controls.snapshot()
                    self.assertEqual(snapshot.mode, 'native_subset')
                    self.assertEqual(snapshot.main_count, count)
                    self.assertEqual(snapshot.focus_choices, ())
                    self.assertEqual(snapshot.modes, ())
                    self.assertTrue(all(c.editable and c.enabled for c in snapshot.choices))
                    for choice in snapshot.choices:
                        assert choice.route.native is not None
                        if choice.route.native.raw not in ('drums', 'bass'):
                            self.assertTrue(controls.toggle_output(choice.id, False))
                    controls.persist_to_settings(settings)
                    self.assertEqual(settings.demucs.stems_selected, ['drums', 'bass'])
                    self.assertEqual(settings.demucs.stems, ALL_STEMS)
                    self.assertEqual(settings.process.stem_focus, '')
                    restored = self.controller(demucs_state(count, raw=raw), settings)
                    self.assertEqual(restored.snapshot().summary, 'Drums, Bass')
                    self.assertTrue(restored.select_all())
                    restored.persist_to_settings(settings)
                    self.assertEqual(settings.demucs.stems_selected, [])
                    self.assertEqual(restored.snapshot().main_count, count)

    def test_demucs_legacy_native_focus_is_displayed_without_migrating_until_edit(self):
        for raw, focus in ((False, 'instrument.bass'), (True, 'raw:bass#scope=scope-a')):
            with self.subTest(raw=raw):
                settings = Settings.defaults()
                settings.demucs.stems = 'bass'
                settings.process.stem_focus = focus
                before = deepcopy(settings)
                controls = self.controller(demucs_state(raw=raw), settings)
                self.assertEqual(controls.snapshot().mode, 'native_subset')
                self.assertEqual(controls.snapshot().summary, 'Bass')
                self.assertFalse(controls.snapshot().review_required)
                controls.persist_to_settings(settings)
                self.assertEqual(settings, before)
                bass = next(c for c in controls.snapshot().choices if c.selected)
                self.assertFalse(controls.toggle_output(bass.id, False))
                drums = next(
                    c
                    for c in controls.snapshot().choices
                    if c.route.native and c.route.native.raw == 'drums'
                )
                self.assertTrue(controls.toggle_output(drums.id, True))
                controls.persist_to_settings(settings)
                self.assertEqual(settings.demucs.stems_selected, ['drums', 'bass'])
                self.assertEqual(settings.demucs.stems, ALL_STEMS)
                self.assertEqual(settings.process.stem_focus, '')

    def test_demucs_invalid_legacy_focus_requires_review_and_all_recovers(self):
        for raw, focus in (
            (False, 'instrument.bass.removed'),
            (False, 'No Bass'),
            (False, ''),
            (False, 'mix.instrumental'),
            (True, 'instrument.bass'),
            (True, 'raw:bass#scope=old'),
        ):
            with self.subTest(raw=raw, focus=focus):
                settings = Settings.defaults()
                settings.demucs.stems = 'bass'
                settings.process.stem_focus = focus
                before = deepcopy(settings)
                controls = self.controller(demucs_state(raw=raw), settings)
                self.assertTrue(controls.snapshot().review_required)
                self.assertEqual(controls.snapshot().main_count, 0)
                controls.persist_to_settings(settings)
                self.assertEqual(settings, before)
                self.assertTrue(controls.select_all())
                controls.persist_to_settings(settings)
                self.assertFalse(controls.snapshot().review_required)
                self.assertEqual(settings.demucs.stems, ALL_STEMS)
                self.assertEqual(settings.process.stem_focus, '')

    def test_demucs_stale_focus_with_all_scalar_requires_review(self):
        settings = Settings.defaults()
        settings.process.stem_focus = 'instrument.removed'
        controls = self.controller(demucs_state(), settings)
        self.assertTrue(controls.snapshot().review_required)
        self.assertTrue(controls.select_all())

    def test_demucs_sidecar_requires_exact_native_keys(self):
        for selected in (['Missing'], ['instrument.bass'], ['Bass']):
            with self.subTest(selected=selected):
                settings = Settings.defaults()
                settings.demucs.stems_selected = selected
                controls = self.controller(demucs_state(), settings)
                self.assertTrue(controls.snapshot().review_required)
                self.assertEqual(controls.snapshot().main_count, 0)
                self.assertTrue(controls.select_all())

    def test_demucs_malformed_sidecar_requires_review_without_rewriting(self):
        for selected in ([['bass']], [None], 'bass', {'bass': True}):
            with self.subTest(selected=selected):
                settings = Settings.from_json_dict({'demucs': {'stems_selected': selected}})
                before = deepcopy(settings)
                controls = self.controller(demucs_state(), settings)
                self.assertTrue(controls.snapshot().review_required)
                controls.persist_to_settings(settings)
                self.assertEqual(settings, before)
                self.assertTrue(controls.select_all())

    def test_demucs_refresh_preserves_selection_and_scoped_context_review(self):
        settings = Settings.defaults()
        controls = self.controller(demucs_state(raw=True), settings)
        for choice in controls.snapshot().choices:
            assert choice.route.native is not None
            if choice.route.native.raw != 'bass':
                controls.toggle_output(choice.id, False)
        before = controls.snapshot()
        renamed = demucs_state(raw=True)
        renamed.routes = tuple(replace(r, label='Renamed') for r in renamed.routes)
        controls.configure('mdx:test', renamed)
        self.assertEqual(controls.snapshot().selected_ids, before.selected_ids)
        self.assertFalse(controls.select_all(revision=before.revision))
        controls.configure('mdx:test', demucs_state(raw=True, scope='scope-b'))
        self.assertTrue(controls.snapshot().review_required)
        self.assertTrue(controls.select_all())

    def test_demucs_native_choices_ignore_optional_derived_union(self):
        state = demucs_state()
        state.routes += (
            StemRoute(
                None,
                StemRoleId('mix.instrumental'),
                kind=StemRouteKind.DERIVED,
                selected_by_default=False,
                derived_from=(StemRoleId('instrument.bass'),),
            ),
        )
        controls = self.controller(state)
        self.assertEqual(controls.snapshot().main_count, 4)
        self.assertTrue(all(c.route.native for c in controls.snapshot().choices))
        self.assertEqual(controls.snapshot().modes, ())
        self.assertFalse(controls.choose_mode('mix.instrumental'))

    def test_missing_model_has_no_invented_outputs(self):
        controls = self.controller(StemSelectionState())
        self.assertEqual(controls.snapshot().mode, 'unavailable')
        self.assertFalse(controls.select_all())
        self.assertEqual(controls.snapshot().choices, ())
