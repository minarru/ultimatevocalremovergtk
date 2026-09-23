"""Final ensemble selections agree across settings, planning and export."""

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

from core.ensembler import CollectedStem
from core.job_diagnostics import stem_focus_diagnostics
from core.job_plan_types import ModelDescriptor
from core.job_projection import select_output_routes
from core.job_route_observations import collect_output_route_evidence
from core.run_hooks import _filter_final_collected_stems
from core.settings import Settings
from core.stem_roles import StemRoleId
from core.stems import StemRoute, StemRouteKind


def route(role: str, label: str) -> StemRoute:
    return StemRoute(
        native=None,
        role=StemRoleId(role),
        label=label,
        filename_tag=label,
        kind=StemRouteKind.DERIVED,
        selected_by_default=True,
    )


class EnsembleStemSelectionTests(unittest.TestCase):
    def setUp(self):
        self.settings = Settings.defaults()
        self.settings.ensemble.main_stem = "mode.multi_stem"
        self.routes = (
            route("vocal.vocals", "Vocals"),
            route("instrument.drums", "Drums"),
            route("instrument.bass", "Bass"),
        )
        self.descriptors = [
            ModelDescriptor(
                id=f"mdx:{name}", family="mdx", basename=name, display=name, routes=self.routes
            )
            for name in ("a", "b")
        ]

    def test_multi_subset_filters_final_projection(self):
        self.settings.ensemble.stems_selected = ["instrument.drums", "instrument.bass"]
        evidence = collect_output_route_evidence(
            self.settings, self.descriptors, command="ensemble"
        )
        projection = select_output_routes(
            self.settings, self.descriptors, command="ensemble", evidence=evidence
        )
        self.assertEqual([r.label for r in projection.routes], ["Drums", "Bass"])

    def test_four_stem_subset_uses_final_standard_roles(self):
        self.settings.ensemble.main_stem = "mode.four_stem"
        self.settings.ensemble.stems_selected = ["instrument.bass"]
        evidence = collect_output_route_evidence(
            self.settings, self.descriptors, command="ensemble"
        )
        projection = select_output_routes(
            self.settings, self.descriptors, command="ensemble", evidence=evidence
        )
        self.assertEqual([str(r.role) for r in projection.routes], ["instrument.bass"])

    def test_missing_saved_role_blocks_planning(self):
        self.settings.ensemble.stems_selected = ["instrument.piano"]
        diagnostics = stem_focus_diagnostics(
            self.settings, [], self.descriptors, command="ensemble"
        )
        self.assertTrue(
            any(
                d.severity == "error" and d.code == "stems.ensemble_subset_unmatched"
                for d in diagnostics
            )
        )

    def test_runtime_subset_uses_roles_not_display_text(self):
        stems = [CollectedStem(r.role, "Renamed " + r.label, "source") for r in self.routes]
        selected = _filter_final_collected_stems(stems, "", ["instrument.bass"])
        self.assertEqual(selected, [stems[2]])

    def test_runtime_rejects_unavailable_subset(self):
        stems = [CollectedStem(r.role, r.label, "source") for r in self.routes]
        with self.assertRaises(ValueError):
            _filter_final_collected_stems(stems, "", ["instrument.piano"])

    def test_settings_round_trip_preserves_subset(self):
        self.settings.ensemble.stems_selected = ["instrument.drums"]
        self.assertEqual(
            Settings.from_json_dict(self.settings.to_json_dict()).ensemble.stems_selected,
            ["instrument.drums"],
        )

    def test_cli_both_clears_inherited_ensemble_subset(self):
        from core.stem_selection import apply_stem_selection

        self.settings.ensemble.stems_selected = ["instrument.drums"]
        apply_stem_selection(self.settings, "both")
        self.assertEqual(self.settings.ensemble.stems_selected, [])

    def test_saved_ensemble_restores_outputs(self):
        from core.ensemble_service import EnsembleService, save_ensemble

        with (
            tempfile.TemporaryDirectory() as folder,
            patch("core.paths.ENSEMBLE_CACHE_DIR", folder),
        ):
            save_ensemble(
                "Output test", "mode.multi_stem", "Average", [], stems_selected=["instrument.bass"]
            )
            EnsembleService().apply(self.settings, "Output test")
        self.assertEqual(self.settings.ensemble.stems_selected, ["instrument.bass"])
        self.assertEqual(self.settings.process.stem_focus, "")

    def test_actual_finalization_writes_only_selected_stems(self):
        import numpy as np

        from core.run_hooks import _EnsembleRunHooks
        from tests.test_ensemble_finalization import _ensembler

        self.settings.ensemble.stems_selected = ["instrument.bass"]
        stems = [CollectedStem(r.role, r.label) for r in self.routes]
        arrays = {stem.group_key: [np.zeros((2, 128)), np.zeros((2, 128))] for stem in stems}
        with tempfile.TemporaryDirectory() as folder:
            ensemble = _ensembler(folder)
            state: Any = SimpleNamespace(
                scratch={
                    "ensemble_stem_arrays": arrays,
                    "ensemble_stem_paths": {},
                    "ensemble_stems": {s.group_key: s for s in stems},
                    "ensemble_contributors": {s.group_key: {"a", "b"} for s in stems},
                    "ensemble_final_base": "song",
                },
                callbacks=SimpleNamespace(
                    console=lambda _: None,
                    report_phase=lambda _: None,
                    progress=lambda *a, **k: None,
                ),
                progress_sink=SimpleNamespace(fraction=0.9),
                base_text="File 1/1 ",
                file_num=1,
                total_files=1,
            )
            _EnsembleRunHooks(ensemble, True).after_file(
                SimpleNamespace(settings=self.settings, true_model_count=2), state
            )
            self.assertEqual(
                [path.name for path in Path(folder).glob("*.wav")], ["song (Bass).wav"]
            )
            self.assertEqual(len(state.scratch["ensemble_stems"]), 3)
