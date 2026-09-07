"""Download Center presentation contracts, independent of GTK."""

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from core.model_scores import PURPOSE_INSTRUMENTAL, PURPOSE_VOCALS


class DownloadPresentationTests(unittest.TestCase):
    def test_scores_are_purpose_specific_and_ambiguous_scores_are_absent(self):
        from ui.download_presentation import purpose_score

        self.assertEqual(purpose_score({'vocals': 12, 'other': 9}, PURPOSE_INSTRUMENTAL, 2), 9)
        self.assertIsNone(purpose_score({'vocals': 12, 'other': 9}, PURPOSE_INSTRUMENTAL, 4))
        self.assertIsNone(purpose_score({'vocals': float('nan')}, PURPOSE_VOCALS, 2))
        self.assertIsNone(purpose_score({'vocals': 12}, 'Stems', 2))
        self.assertIsNone(purpose_score({'vocals': 12, 'vocal': 13}, PURPOSE_VOCALS, 2))

    def test_outputs_have_no_architecture_or_duplicate_purpose(self):
        from ui.download_presentation import output_summary

        meta = SimpleNamespace(
            stem_semantics=SimpleNamespace(
                status='reviewed',
                routes=[
                    SimpleNamespace(display='Vocals'),
                    SimpleNamespace(display='Instrumental'),
                    SimpleNamespace(display='Vocals'),
                ],
            ),
            catalogue_evidence_status='ready',
        )
        self.assertEqual(output_summary(meta), 'Vocals, Instrumental')

    def test_polarformer_name_overrides_shared_runtime_architecture(self):
        from ui.download_presentation import architecture_for

        with patch('ui.download_presentation.mdx_kind_from_names', return_value='bs_roformer'):
            self.assertEqual(
                architecture_for('mdx', ('model.ckpt',), 'raw', 'BandSplit PolarFormer — Test')[0],
                'bs_polarformer',
            )

    def test_sort_keeps_unscored_and_unsupported_last_in_both_directions(self):
        from ui.download_presentation import compare_models

        for descending in (True, False):
            self.assertLess(compare_models('A', 5, False, 'B', None, False, True, descending), 0)
            self.assertLess(compare_models('Z', None, False, 'A', 20, True, True, descending), 0)
        self.assertLess(compare_models('A', None, False, 'Z', None, False, False, False), 0)
        self.assertGreater(compare_models('A', None, False, 'Z', None, False, False, True), 0)

    def test_offline_scores_never_fetch_or_write(self):
        from core import model_scores

        with (
            patch.object(model_scores, '_cached_scores', None),
            patch.object(model_scores, '_read_disk_cache', return_value=None),
            patch.object(model_scores, '_read_bundled_scores', return_value={}),
            patch.object(model_scores, '_fetch_model_scores') as fetch,
            patch.object(model_scores, '_write_disk_cache') as write,
        ):
            self.assertEqual(model_scores.load_model_scores(allow_network=False), {})
        fetch.assert_not_called()
        write.assert_not_called()
