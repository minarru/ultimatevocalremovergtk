import unittest

from core.stem_selection import StemSelectionState
from ui.stem_presentation import project_stems


class StemPresentationTests(unittest.TestCase):
    def test_hidden_and_repick(self):
        state = StemSelectionState()
        self.assertEqual(project_stems(state).visible_rows, ())
        state.configure_exclusive(
            primary_stem='Vocals',
            secondary_stem='Instrumental',
            primary_key='is_primary_stem_only',
            secondary_key='is_secondary_stem_only',
            has_model=True,
        )
        view = project_stems(state, repick=True)
        self.assertEqual(view.visible_rows, ('exclusive',))
        self.assertEqual(view.expected_count, 0)
        self.assertIn('Choose a stem again', view.export_summary)

    def test_quick_and_custom_paths(self):
        state = StemSelectionState()
        state.configure_subset(
            stems=['Vocals', 'Bass', 'Drums'],
            primary_key='is_primary_stem_only',
            secondary_key='is_secondary_stem_only',
            has_model=True,
        )
        state.subset_mode = 'custom'
        state.custom_selected = {'Bass'}
        state.custom_all = False
        view = project_stems(state, quick_visible=True)
        self.assertEqual(view.export_summary, 'Exporting Bass')
        self.assertEqual(view.custom_subtitle, 'Bass')
        self.assertEqual((view.quick_opacity, view.custom_opacity), (0.55, 1.0))
        self.assertEqual(view.expected_count, 1)
