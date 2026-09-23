"""Review uses resolved outputs and keeps confirmation under run-controller ownership."""

import json
import os
import time
import unittest
from collections.abc import Callable
from dataclasses import replace
from unittest.mock import Mock, patch

from core.export_naming import OutputNamingContext
from core.job_plan_types import (
    Diagnostic,
    ModelDescriptor,
    PlannedInput,
    PlannedOutput,
    ResolvedJob,
    ValidationLevel,
)
from core.settings import Settings
from tests.gtk_layout_helpers import resize_window, wait_for_dialog_open


def resolved_plan(*, ensemble: bool = False, conditional: bool = False):
    settings = Settings.defaults()
    settings.ensemble.save_all_outputs = False
    naming = OutputNamingContext("/music/A & B.wav", "A & B", "A & B", "/out", "flac", 1, 1)
    outputs = (PlannedOutput("/out/Vocals.flac", "Vocals"),)
    if conditional:
        outputs += (PlannedOutput("/out/Lead.flac", "Lead Vocals", conditional=True),)
    return ResolvedJob(
        command="ensemble" if ensemble else "separate",
        settings=settings,
        inputs=(PlannedInput("/music/A & B.wav", naming, outputs),),
        models=(ModelDescriptor("mdx:a", "mdx", "a", "Model <A> & B"),),
        provenance={},
        diagnostics=(),
        validation_level=ValidationLevel.RUNTIME,
        inventory_generation=1,
        settings_fingerprint="test",
        device="cpu",
        output="/out",
    )


class PlanReviewPresentationTests(unittest.TestCase):
    def test_counts_distinguish_conditional_outputs(self):
        from ui.plan_review import review_presentation

        view = review_presentation(resolved_plan(conditional=True))
        self.assertEqual(view.file_summary, "1 planned file · up to 1 conditional file")
        self.assertEqual(view.stems, ("Vocals",))
        self.assertEqual(view.conditional_stems, ("Lead Vocals",))

    def test_retained_ensemble_outputs_are_not_invented_in_count(self):
        from ui.plan_review import review_presentation

        plan = resolved_plan(ensemble=True)
        plan.settings.ensemble.save_all_outputs = True
        plan.settings.process.vocal_splitter_enabled = True
        view = review_presentation(plan)
        self.assertEqual(view.file_summary, "1 planned file")
        self.assertIn("not included", view.additional)
        self.assertIn("Vocal", view.additional)

    def test_details_exclude_unrelated_state_and_use_resolved_selections(self):
        from ui.plan_review import review_presentation

        plan = resolved_plan(conditional=True)
        plan.settings.process.model_hash_table = {"unrelated-checkpoint": "cached-hash"}
        plan.settings.process.input_paths = ["/unrelated/input.wav"]
        plan.settings.process.last_dir = "/unrelated/history"
        plan.settings.vr.model = "vr:inactive-model"
        plan.settings.mdx.model = "mdx:stale-selection"
        plan.settings.mdx.voc_inst_secondary_model = "mdx:disabled-secondary"
        plan.settings.mdx.segment_size = 512
        plan.settings.ensemble.selected_models = ["mdx:inactive-ensemble"]
        plan.settings.audio_tools.apollo_model = "apollo:inactive-tool"
        with patch.object(
            Settings, "to_json_dict", side_effect=AssertionError("Do not serialize global settings")
        ):
            text = review_presentation(plan).technical
        details = json.loads(text.split("\n\n", 1)[1])
        self.assertEqual(details["models"][0]["id"], "mdx:a")
        self.assertEqual(details["inputs"][0]["path"], "/music/A & B.wav")
        self.assertTrue(details["inputs"][0]["outputs"][1]["conditional"])
        self.assertEqual(details["processing"]["mdx"]["segment_size"], 512)
        for excluded in (
            "unrelated",
            "inactive",
            "stale-selection",
            "disabled-secondary",
            "model_hash_table",
            "window_width",
            "inventory_generation",
        ):
            self.assertNotIn(excluded, text)
        self.assertNotIn("vr", details["processing"])
        self.assertNotIn("ensemble", details)

    def test_details_include_ensemble_members_and_active_dependencies(self):
        from core.model_identity import ModelArtifacts, ModelRecord
        from ui.plan_review import review_presentation

        plan = resolved_plan(ensemble=True)
        dependency = ModelRecord(
            id="vr:splitter",
            family="vr",
            basename="splitter",
            display="Splitter",
            backend_name="splitter",
            artifacts=ModelArtifacts("splitter.pth"),
            installed=True,
        )
        plan = replace(plan, model_dependencies={"process.vocal_splitter": dependency})
        plan.settings.process.vocal_splitter_enabled = True
        plan.settings.process.sample_mode = True
        plan.settings.process.sample_mode_duration = 15
        plan.settings.ensemble.save_all_outputs = True
        details = json.loads(review_presentation(plan).technical.split("\n\n", 1)[1])
        self.assertEqual(details["dependencies"]["process.vocal_splitter"]["id"], "vr:splitter")
        self.assertIn("vr", details["processing"])
        self.assertIn("mdx", details["processing"])
        self.assertNotIn("demucs", details["processing"])
        self.assertTrue(details["ensemble"]["save_all_outputs"])
        self.assertEqual(details["processing"]["sample_mode_duration"], 15)

    def test_warnings_and_real_paths_are_preserved(self):
        from ui.plan_review import review_presentation

        plan = replace(
            resolved_plan(), diagnostics=(Diagnostic("test", "Review <this> & that", "warning"),)
        )
        view = review_presentation(plan)
        self.assertEqual(view.warnings, ("Review <this> & that",))
        self.assertIn("/music/A & B.wav", view.technical)
        self.assertIn("mdx:a", view.technical)
        self.assertEqual(view.destination, "/out")


@unittest.skipUnless(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"), "Needs GTK")
class PlanReviewDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import gi

        gi.require_version("Gtk", "4.0")
        gi.require_version("Adw", "1")
        from tests.private_gtk import require_private_gtk

        require_private_gtk()

    def setUp(self):
        from gi.repository import Adw

        from ui.run_control import RunController

        Adw.init()
        self.parent = Adw.Window()
        self.parent.set_default_size(900, 800)
        self.parent.present()
        self.addCleanup(self.parent.close)
        self.host = Mock(dialog_parent=self.parent)
        self.controller = RunController(self.host)
        self.controller._operation_id = "current"
        self.accept = Mock()
        self.finish = Mock()
        self.controller._accept_plan = self.accept
        self.controller._finish_operation = self.finish
        self.plan = resolved_plan()
        self.target = Mock()

    def wait_for(self, predicate: Callable[[], bool]):
        from gi.repository import GLib

        deadline = time.monotonic() + 5
        while not predicate():
            self.assertLess(time.monotonic(), deadline)
            GLib.MainContext.default().iteration(False)
            time.sleep(0.005)

    def test_start_uses_existing_plan_acceptance_once(self):
        from ui.dialogs.plan_review import ReviewPlanDialog

        self.controller._present_plan_confirmation(self.target, "fingerprint", self.plan)
        dialog = self.controller._plan_dialog
        assert isinstance(dialog, ReviewPlanDialog)
        wait_for_dialog_open(dialog)
        self.addCleanup(dialog.force_close)
        self.assertEqual(dialog.model_row.get_subtitle(), "Model <A> & B")
        self.assertFalse(dialog.model_row.get_use_markup())
        dialog.start_button.emit("clicked")
        self.wait_for(lambda: self.accept.called)
        self.accept.assert_called_once_with(self.target, "fingerprint", self.plan)
        self.assertIsNone(self.controller._plan_dialog)

    def test_close_cancels_and_stale_close_cannot_accept(self):
        from ui.dialogs.plan_review import ReviewPlanDialog

        for stale in (False, True):
            self.controller._operation_id = "current"
            self.controller._present_plan_confirmation(self.target, "fingerprint", self.plan)
            dialog = self.controller._plan_dialog
            assert isinstance(dialog, ReviewPlanDialog)
            wait_for_dialog_open(dialog)
            closed = Mock()
            dialog.connect("closed", closed)
            if stale:
                self.controller._operation_id = "new"
                dialog.start_button.emit("clicked")
            dialog.force_close()
            self.wait_for(lambda closed=closed: closed.called)
        self.accept.assert_not_called()
        self.finish.assert_called_once_with("run_cancelled", reason="plan_confirmation")

    def test_large_plan_fits_wide_and_narrow_windows(self):
        from ui.dialogs.plan_review import ReviewPlanDialog

        base = resolved_plan(ensemble=True)
        roles = ("Vocals", "Drums", "Bass", "Other", "Guitar", "Piano")
        outputs = tuple(PlannedOutput(f"/out/{stem}.wav", stem) for stem in roles)
        plan = replace(
            base,
            inputs=tuple(
                replace(
                    base.inputs[0],
                    path=f"/music/{'Long album directory ' * 8}/Track {index}.wav",
                    outputs=outputs,
                )
                for index in range(40)
            ),
            models=tuple(
                ModelDescriptor(f"mdx:{index}", "mdx", str(index), "Long model title " * 12)
                for index in range(8)
            ),
            diagnostics=(Diagnostic("test", "A detailed warning. " * 30, "warning"),),
        )
        for width in (900, 390):
            with self.subTest(width=width):
                resize_window(self.parent, width, 800)
                self.wait_for(lambda width=width: self.parent.get_width() == width)
                dialog = ReviewPlanDialog(plan)
                dialog.present(self.parent)
                wait_for_dialog_open(dialog)
                self.wait_for(dialog.start_button.get_mapped)
                self.assertEqual(dialog.result.get_label(), "240 planned files")
                for row in (dialog.members, dialog.inputs, dialog.stems, dialog.technical):
                    row.set_expanded(True)
                self.wait_for(lambda dialog=dialog: dialog.plan_text.get_height() > 0)
                self.assertLessEqual(dialog.get_width(), self.parent.get_width())
                self.assertLessEqual(dialog.get_height(), self.parent.get_height())
                self.assertTrue(dialog.start_button.get_mapped())
                closed = Mock()
                dialog.connect("closed", closed)
                dialog.force_close()
                self.wait_for(lambda closed=closed: closed.called)
