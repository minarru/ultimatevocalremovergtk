"""Browser policy preserves independent row search, counting and queue order."""

import unittest
from types import SimpleNamespace
from typing import Any, cast

from bundled.constants import MDX_ARCH_TYPE, VR_ARCH_TYPE
from core.model_scores import PURPOSE_ALL
from ui.catalogue_browser import BrowserFilters, BrowserRow, CatalogueBrowserState


class CatalogueBrowserTests(unittest.TestCase):
    def test_display_only_search_does_not_change_raw_counts(self):
        browser = CatalogueBrowserState()
        browser.replace_rows((BrowserRow((MDX_ARCH_TYPE, 'raw'), 'Unique title', MDX_ARCH_TYPE),))
        filters = BrowserFilters(purpose=PURPOSE_ALL, query='Unique')
        self.assertTrue(browser.matches(browser.rows[(MDX_ARCH_TYPE, 'raw')], filters))
        self.assertEqual(browser.matching_count(MDX_ARCH_TYPE, filters), 0)

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
        view = project_browser(browser, BrowserFilters(query='Unique'), online=True)
        self.assertEqual(view.visible_keys, ((MDX_ARCH_TYPE, 'raw'),))
        self.assertEqual(view.placeholder_count, 1)
        self.assertEqual(view.title, 'No matching models')
        self.assertEqual(browser.available_count(), 1)

    def test_unsupported_sort_priority_is_global_across_networks(self):
        from core.model_scores import SORT_NAME

        supported = BrowserRow((MDX_ARCH_TYPE, 'z'), 'z', MDX_ARCH_TYPE)
        unsupported = BrowserRow((VR_ARCH_TYPE, 'a'), 'a', VR_ARCH_TYPE, reason='new build')
        self.assertLess(supported.sort_key(SORT_NAME), unsupported.sort_key(SORT_NAME))
