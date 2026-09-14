"""Real GTK state after resolving compatible and conflicting model configs."""

import unittest
from types import SimpleNamespace
from typing import Any

from tests.private_gtk import require_private_gtk
from tests.test_stem_runtime_reconciliation import VIPER, runtime_model


class RuntimeStemUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import gi

        gi.require_version('Gtk', '4.0')
        gi.require_version('Adw', '1')
        from gi.repository import Adw, Gdk

        Adw.init()
        require_private_gtk()
        if Gdk.Display.get_default() is None:
            raise unittest.SkipTest('GTK display unavailable')

    def test_method_resolution_refreshes_quickselect_dialog_and_conflict_state(self):
        from gi.repository import Adw

        from core.settings import Settings
        from ui.views.base import MethodView
        from ui.widgets.output_stems import OutputStemsSection
        from ui.widgets.stem_only import SaveStemsSection

        settings = Settings.defaults()
        section = SaveStemsSection(settings=settings, on_changed=lambda: None)
        output = OutputStemsSection(section, Adw.PreferencesGroup())
        view: Any = MethodView.__new__(MethodView)
        view.settings = settings
        view.method_key = 'MDX-Net'
        view.resolution_method_key = ''
        view.primary_only_key = 'is_primary_stem_only'
        view.secondary_only_key = 'is_secondary_stem_only'
        view.save_stems = section
        view.has_model = lambda: True
        view._on_model_resolved = lambda model: None
        view._update_stem_group_metadata = output.refresh
        view.sync_dynamic_option_state = lambda: None
        for model, labels, blocked in (
            (runtime_model(), ['Instrumental', 'Vocals'], False),
            (runtime_model(digest='0' * 32), ['Instrumental', 'Vocals'], True),
            (runtime_model(VIPER, ('vocals',), 'vocals'), ['Vocals', 'Instrumental'], False),
            (runtime_model('mdx:unknown'), ['other'], False),
            (runtime_model(), ['Instrumental', 'Vocals'], False),
        ):
            with self.subTest(model=model.canonical_id, blocked=blocked):
                view.selected_model = lambda model=model: model.canonical_id
                view.context = SimpleNamespace(
                    repo=SimpleNamespace(resolve_model_dry=lambda *args, model=model: model)
                )
                view.update_stem_labels()
                self.assertEqual([label for _, label in output.quick.items][1:], labels)
                self.assertEqual(output.quick.items, output.dialog_quick.items)
                self.assertEqual(
                    [row.get_title() for row, _ in output._output_rows.values()], labels
                )
                self.assertEqual(output.quick.widget.get_sensitive(), not blocked)
                self.assertEqual(section.repick_required, blocked)
                if blocked:
                    self.assertIn('configuration', output.row.get_subtitle() or "")
                    self.assertTrue(
                        all(not check.get_sensitive() for _, check in output._output_rows.values())
                    )
                else:
                    self.assertEqual(output.row.get_subtitle(), ', '.join(labels))
