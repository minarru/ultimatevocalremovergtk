"""GUI write gates must remove models from the effective resolved plan."""

from __future__ import annotations

import tempfile
import unittest
from types import SimpleNamespace
from typing import Any
from unittest.mock import Mock

from bundled.constants import NO_MODEL
from core.job_plan import (
    JobResolver,
    JobSpec,
    ValidationLevel,
    active_model_paths,
)
from core.model_identity import ModelArtifacts, ModelRecord
from core.settings import Settings
from core.types import ProcessMethod


def _record(model_id: str) -> ModelRecord:
    family, basename = model_id.split(":", 1)
    extension = ".pth" if family == "vr" else ".onnx"
    return ModelRecord(
        id=model_id,
        family=family,
        basename=basename,
        display=f"Friendly {basename}",
        backend_name=basename,
        artifacts=ModelArtifacts(f"{basename}{extension}"),
        installed=True,
    )


def _resolve(
    settings: Settings,
    records: dict[str, ModelRecord],
    *,
    command: str = "separate",
):
    with tempfile.NamedTemporaryFile(suffix=".wav") as source:
        return _resolve_spec(JobSpec(command, settings, (source.name,), "/tmp/out"), records)


def _resolve_spec(
    spec: JobSpec,
    records: dict[str, ModelRecord],
):
    repo = Mock(inventory_generation=0)
    repo.karaoke_model_list.return_value = ["vr:gated-splitter"]
    resolver = JobResolver(repo)
    resolver.identities.lookup = Mock(side_effect=records.__getitem__)
    if any(
        section.is_secondary_model_activate
        for section in (spec.settings.vr, spec.settings.mdx, spec.settings.demucs)
    ):
        resolver._assemble = Mock(
            return_value=[
                SimpleNamespace(
                    model_status=True,
                    primary_stem="Vocals",
                    secondary_stem="Instrumental",
                    model_path="",
                    model_hash_dir="",
                    vocal_split_model=None,
                    is_vocal_split_model_activated=False,
                    is_ensemble_mode=False,
                    mdx_model_stems=(),
                    demucs_source_list=(),
                    mdxnet_stems_selected=(),
                )
            ]
        )
    return resolver.resolve(
        spec,
        ValidationLevel.CONFIG,
        allow_network=False,
    )


def _flush_method_view(
    settings: Settings,
    *,
    primary_id: str,
    gated_key: str,
    activate_key: str,
) -> None:
    from ui.views.base import MethodView

    view: Any = MethodView.__new__(MethodView)
    view.settings = settings
    view.model_key = "demucs_model" if primary_id.startswith("demucs:") else "mdx_net_model"
    view._model_write_gated = False
    view.selected_model = lambda: primary_id
    view.save_options = lambda: None
    view._scale_rows = {}
    view._switch_rows = {}
    view._spin_rows = {}
    view._model_combos = [
        {
            "key": gated_key,
            "activate_key": activate_key,
            "write_gated": True,
        }
    ]

    MethodView.save(view, include_stem_only=False)


class GatedSeparationPlanTests(unittest.TestCase):
    def test_gated_secondary_is_disabled_in_the_resolved_plan(self) -> None:
        primary = _record("mdx:primary")
        gated = _record("mdx:gated-secondary")
        settings = Settings.defaults()
        settings.process.method = ProcessMethod.MDX
        settings.mdx.model = primary.id
        settings.mdx.is_secondary_model_activate = True
        settings.mdx.voc_inst_secondary_model = gated.id

        _flush_method_view(
            settings,
            primary_id=primary.id,
            gated_key="mdx_voc_inst_secondary_model",
            activate_key="mdx_is_secondary_model_activate",
        )
        plan = _resolve(settings, {primary.id: primary, gated.id: gated})

        self.assertFalse(plan.settings.mdx.is_secondary_model_activate)
        self.assertEqual(plan.settings.mdx.voc_inst_secondary_model, NO_MODEL)
        self.assertEqual(
            active_model_paths(
                plan.settings,
                command="separate",
                primary=primary,
                primary_stems={"mdx.model": "Vocals"},
            ),
            ("mdx.model",),
        )

    def test_gated_preprocess_model_is_disabled_in_the_resolved_plan(self) -> None:
        primary = _record("demucs:primary")
        gated = _record("mdx:gated-preprocess")
        settings = Settings.defaults()
        settings.process.method = ProcessMethod.DEMUCS
        settings.demucs.model = primary.id
        settings.demucs.is_pre_proc_model_activate = True
        settings.demucs.pre_proc_model = gated.id

        _flush_method_view(
            settings,
            primary_id=primary.id,
            gated_key="demucs_pre_proc_model",
            activate_key="is_demucs_pre_proc_model_activate",
        )
        plan = _resolve(settings, {primary.id: primary, gated.id: gated})

        self.assertFalse(plan.settings.demucs.is_pre_proc_model_activate)
        self.assertEqual(plan.settings.demucs.pre_proc_model, NO_MODEL)
        self.assertNotIn("demucs.pre_proc_model", plan.model_dependencies)

    def test_ensemble_job_spec_preserves_gated_splitter_for_readiness_block(self) -> None:
        from ui.ensemble.window import EnsemblePage
        from ui.widgets.vocal_split_row import VocalSplitRow

        first = _record("mdx:first")
        second = _record("vr:second")
        gated = _record("vr:gated-splitter")
        settings = Settings.defaults()
        settings.process.method = ProcessMethod.ENSEMBLE
        settings.ensemble.main_stem = "pair.vocals_instrumental"
        settings.ensemble.selected_models = [first.id, second.id]
        settings.process.vocal_splitter_enabled = True
        settings.process.vocal_splitter = gated.id
        row: Any = VocalSplitRow.__new__(VocalSplitRow)
        row.split_switch = SimpleNamespace(get_active=lambda: True)
        row.save_inst_switch = SimpleNamespace(get_active=lambda: True)
        row.deverb_switch = SimpleNamespace(get_active=lambda: False)
        row.deverb_row = None
        row._populator = SimpleNamespace(ready=True)
        row._splitter_write_gated = True
        row._stored_splitter = gated.id

        with tempfile.NamedTemporaryFile(suffix=".wav") as source:
            page: Any = EnsemblePage.__new__(EnsemblePage)
            page.settings = settings
            page.vocal_split_row = row
            page._models_write_gated = False
            page._model_checks = {
                first.id: SimpleNamespace(get_active=lambda: True),
                second.id: SimpleNamespace(get_active=lambda: True),
            }
            page.save_stems = SimpleNamespace(persist_to_settings=lambda: None)
            page.input_row = SimpleNamespace(paths=[source.name])
            page.output_row = SimpleNamespace(path="/tmp/out")

            spec = EnsemblePage.build_job_spec(page)
            plan = _resolve_spec(
                spec,
                {first.id: first, second.id: second, gated.id: gated},
            )

        self.assertTrue(plan.settings.process.vocal_splitter_enabled)
        self.assertEqual(plan.settings.process.vocal_splitter, gated.id)
        self.assertEqual(plan.model_dependencies["process.vocal_splitter"], gated)


class GatedEnsemblePlanTests(unittest.TestCase):
    def test_gated_member_is_dropped_while_two_checked_members_remain(self) -> None:
        from ui.ensemble.window import EnsemblePage

        first = _record("mdx:first")
        gated = _record("mdx:newly-installed")
        second = _record("vr:second")
        settings = Settings.defaults()
        settings.process.method = ProcessMethod.ENSEMBLE
        settings.ensemble.main_stem = "pair.vocals_instrumental"
        settings.ensemble.selected_models = [first.id, gated.id, second.id]
        page: Any = EnsemblePage.__new__(EnsemblePage)
        page.settings = settings
        page._models_write_gated = True
        page._model_checks = {
            first.id: SimpleNamespace(get_active=lambda: True),
            gated.id: SimpleNamespace(get_active=lambda: False),
            second.id: SimpleNamespace(get_active=lambda: True),
        }
        page.vocal_split_row = SimpleNamespace(persist_to_settings=lambda _settings: None)
        page.save_stems = SimpleNamespace(persist_to_settings=lambda: None)

        EnsemblePage._flush_run_settings(page)
        plan = _resolve(
            settings,
            {first.id: first, gated.id: gated, second.id: second},
            command="ensemble",
        )

        self.assertEqual(plan.settings.ensemble.selected_models, [first.id, second.id])
        self.assertEqual(
            list(plan.model_dependencies),
            ["ensemble.selected_models[0]", "ensemble.selected_models[1]"],
        )
        self.assertEqual(
            [record.id for record in plan.model_dependencies.values()],
            [first.id, second.id],
        )


if __name__ == "__main__":
    unittest.main()
