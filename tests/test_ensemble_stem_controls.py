import unittest

from core.settings import Settings
from tests.test_ensemble_stem_selection import route
from ui.ensemble.stem_controls import EnsembleStemControls


class EnsembleStemControlsTests(unittest.TestCase):
    def test_edits_use_ensemble_settings_and_reject_stale_dialog_commands(self):
        settings = Settings.defaults()
        settings.mdx.stems_selected = ["leave-this-alone"]
        controls = EnsembleStemControls(settings)
        routes = (route("vocal.vocals", "Vocals"), route("instrument.drums", "Drums"))
        controls.configure(routes)
        revision = controls.snapshot().revision
        self.assertTrue(controls.toggle_output("vocal.vocals", False, revision=revision))
        controls.persist_to_settings()
        self.assertEqual(settings.ensemble.stems_selected, ["instrument.drums"])
        self.assertEqual(settings.mdx.stems_selected, ["leave-this-alone"])
        controls.configure(routes[:1])
        self.assertTrue(controls.snapshot().review_required)
        self.assertFalse(controls.toggle_output("vocal.vocals", True, revision=revision))
        controls.select_all()
        controls.persist_to_settings()
        self.assertEqual(settings.ensemble.stems_selected, [])

    def test_last_output_cannot_be_unchecked(self):
        controls = EnsembleStemControls(Settings.defaults())
        controls.configure((route("vocal.vocals", "Vocals"),))
        self.assertFalse(
            controls.toggle_output("vocal.vocals", False, revision=controls.snapshot().revision)
        )
