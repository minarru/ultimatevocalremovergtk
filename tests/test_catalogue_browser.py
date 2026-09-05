"""Browser policy preserves independent row search, counting and queue order."""

import unittest
from types import SimpleNamespace
from typing import Any, cast

from bundled.constants import MDX_ARCH_TYPE, VR_ARCH_TYPE
from core.model_scores import PURPOSE_ALL
from ui.catalogue_browser import (
    BrowserFilters,
    BrowserRow,
    CatalogueBrowserState,
    LiveCatalogueEntry,
    project_live_counts,
)


class CatalogueBrowserTests(unittest.TestCase):
    def test_display_only_search_does_not_change_raw_counts(self):
        browser = CatalogueBrowserState()
        browser.replace_rows((BrowserRow((MDX_ARCH_TYPE, 'raw'), 'Unique title', MDX_ARCH_TYPE),))
        filters = BrowserFilters(purpose=PURPOSE_ALL, query='Unique')
        self.assertTrue(browser.matches(browser.rows[(MDX_ARCH_TYPE, 'raw')], filters))
        counts = project_live_counts(
            (LiveCatalogueEntry((MDX_ARCH_TYPE, "raw"), MDX_ARCH_TYPE),), filters
        )
        self.assertEqual(counts.matching_count(MDX_ARCH_TYPE), 0)

    def test_selection_order_removal_and_replacement(self):
        browser = CatalogueBrowserState()
        a = BrowserRow((MDX_ARCH_TYPE, 'same'), 'Z', MDX_ARCH_TYPE)
        b = BrowserRow((VR_ARCH_TYPE, 'same'), 'A', VR_ARCH_TYPE)
        unsupported = BrowserRow((VR_ARCH_TYPE, 'bad'), 'Bad', VR_ARCH_TYPE, reason='unsupported')
        browser.replace_rows((a, b, unsupported))
        for row in (b, unsupported, a):
            browser.set_selected(row.key, True)
        self.assertEqual(browser.selected_keys(), (a.key, b.key))
        browser.pin(cast(Any, SimpleNamespace(vr={'same': 'old'}, mdx={}, demucs={}, apollo={})))
        self.assertEqual(browser.remove_missing({b.key, unsupported.key}), (a.key,))
        self.assertEqual(browser.selected_keys(), (b.key,))
        self.assertEqual(browser.pinned_catalogue(VR_ARCH_TYPE), {'same': 'old'})
        browser.replace_rows((b,))
        self.assertEqual(browser.selected_keys(), (b.key,))

    def test_explicit_score_and_filename_fallback(self):
        from core.model_scores import parse_sdr_score
        from ui.catalogue_browser import project_row

        name = 'Vocals SDR 12.34'
        row = project_row(MDX_ARCH_TYPE, name, raw=None, meta=None, score=('Vocals', 9.5))
        self.assertEqual((row.sdr_stem, row.sdr), ('Vocals', 9.5))
        fallback = project_row(MDX_ARCH_TYPE, name, raw=None, meta=None)
        self.assertEqual(fallback.sdr, parse_sdr_score(name))

    def test_presentation_keeps_display_only_empty_state_and_global_counts(self):
        from ui.catalogue_browser import project_browser

        browser = CatalogueBrowserState()
        browser.available = {MDX_ARCH_TYPE: ['raw']}
        browser.replace_rows((BrowserRow((MDX_ARCH_TYPE, 'raw'), 'Unique title', MDX_ARCH_TYPE),))
        filters = BrowserFilters(query='Unique')
        counts = project_live_counts(
            (LiveCatalogueEntry((MDX_ARCH_TYPE, 'raw'), MDX_ARCH_TYPE),), filters
        )
        view = project_browser(browser, filters, online=True, live_counts=counts)
        self.assertEqual(view.visible_keys, ((MDX_ARCH_TYPE, 'raw'),))
        self.assertEqual(view.placeholder_count, 1)
        self.assertEqual(view.title, 'No matching models')
        self.assertEqual(browser.available_count(), 1)

    def test_unsupported_sort_priority_is_global_across_networks(self):
        from core.model_scores import SORT_NAME

        supported = BrowserRow((MDX_ARCH_TYPE, 'z'), 'z', MDX_ARCH_TYPE)
        unsupported = BrowserRow((VR_ARCH_TYPE, 'a'), 'a', VR_ARCH_TYPE, reason='new build')
        self.assertLess(supported.sort_key(SORT_NAME), unsupported.sort_key(SORT_NAME))


class LiveCatalogueCountsTests(unittest.TestCase):
    def test_live_additions_are_counted_without_changing_pinned_rows(self):
        from ui.catalogue_browser import project_browser

        state = CatalogueBrowserState()
        survivor = BrowserRow((MDX_ARCH_TYPE, 'Survivor'), 'Survivor', MDX_ARCH_TYPE)
        state.replace_rows((survivor,))
        state.available = {MDX_ARCH_TYPE: ['Survivor', 'Added later']}
        entries = tuple(
            LiveCatalogueEntry((MDX_ARCH_TYPE, name), MDX_ARCH_TYPE)
            for name in state.available[MDX_ARCH_TYPE]
        )
        filters = BrowserFilters(query='Added later')
        counts = project_live_counts(entries, filters)
        view = project_browser(state, filters, online=True, live_counts=counts)
        self.assertEqual(counts.matching_count(MDX_ARCH_TYPE), 1)
        self.assertEqual(view.placeholder_count, 2)
        self.assertEqual(view.visible_keys, ())
        self.assertEqual(view.title, '')
        self.assertIs(state.rows[survivor.key], survivor)

    def test_raw_query_network_reason_hide_and_sentinel_matrix(self):
        from bundled.constants import NO_NEW_MODELS
        from core.model_scores import NETWORK_CLASSIC_MDX, NETWORK_MEL_BAND

        entries = (
            LiveCatalogueEntry((MDX_ARCH_TYPE, 'Raw vocals'), NETWORK_CLASSIC_MDX),
            LiveCatalogueEntry((MDX_ARCH_TYPE, 'Added later'), NETWORK_MEL_BAND),
            LiveCatalogueEntry(
                (MDX_ARCH_TYPE, 'Unsupported'), NETWORK_MEL_BAND, reason='newer build'
            ),
            LiveCatalogueEntry((VR_ARCH_TYPE, 'Other'), VR_ARCH_TYPE),
            LiveCatalogueEntry((VR_ARCH_TYPE, NO_NEW_MODELS), VR_ARCH_TYPE),
        )
        cases = (
            (BrowserFilters(), 3, 4),
            (BrowserFilters(query='newer build'), 1, 4),
            (BrowserFilters(query='newer build', hide_unsupported=True), 0, 3),
            (BrowserFilters(network=NETWORK_MEL_BAND), 2, 2),
            (BrowserFilters(network=NETWORK_CLASSIC_MDX), 1, 1),
            (BrowserFilters(network=VR_ARCH_TYPE), 2, 1),
        )
        for filters, matching, placeholder in cases:
            with self.subTest(filters=filters):
                counts = project_live_counts(entries, filters)
                self.assertEqual(counts.matching_count(MDX_ARCH_TYPE), matching)
                self.assertEqual(counts.placeholder_count, placeholder)
                self.assertTrue(counts.any_rows)

    def test_hidden_unsupported_and_sentinel_still_prevent_all_installed(self):
        from bundled.constants import NO_NEW_MODELS
        from core.model_scores import NETWORK_CLASSIC_MDX, NETWORK_MEL_BAND
        from ui.catalogue_browser import project_browser

        state = CatalogueBrowserState()
        filters = BrowserFilters(network=NETWORK_CLASSIC_MDX, hide_unsupported=True)
        entries = (
            LiveCatalogueEntry((MDX_ARCH_TYPE, 'Unsupported'), NETWORK_MEL_BAND, reason='reason'),
        )
        counts = project_live_counts(entries, filters)
        self.assertEqual(counts.placeholder_count, 0)
        self.assertTrue(counts.any_rows)
        self.assertEqual(project_browser(state, filters, online=True, live_counts=counts).title, '')
        sentinel = (LiveCatalogueEntry((VR_ARCH_TYPE, NO_NEW_MODELS), VR_ARCH_TYPE),)
        counts = project_live_counts(sentinel, BrowserFilters())
        self.assertEqual(counts.placeholder_count, 0)
        self.assertTrue(counts.any_rows)

    def test_scoped_purpose_evidence_is_independent_per_family(self):
        from core.model_scores import PURPOSE_REMOVAL, PURPOSE_VOCALS
        from core.model_stem_semantics import INTENT_DUAL_VOC_INST, INTENT_SPECIAL_FX

        entries = (
            LiveCatalogueEntry((MDX_ARCH_TYPE, 'Same'), MDX_ARCH_TYPE, intent=INTENT_SPECIAL_FX),
            LiveCatalogueEntry((VR_ARCH_TYPE, 'Same'), VR_ARCH_TYPE, intent=INTENT_DUAL_VOC_INST),
        )
        for purpose, expected in ((PURPOSE_REMOVAL, (1, 0)), (PURPOSE_VOCALS, (0, 1))):
            counts = project_live_counts(entries, BrowserFilters(purpose=purpose))
            self.assertEqual(
                (counts.matching_count(MDX_ARCH_TYPE), counts.matching_count(VR_ARCH_TYPE)),
                expected,
            )
