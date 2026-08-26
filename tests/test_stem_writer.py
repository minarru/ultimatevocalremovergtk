"""Boundary tests for the extracted stem writer."""

from __future__ import annotations

import ast
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
_WRITER = _REPO / "engines" / "stem_writer.py"
_BASE = _REPO / "engines" / "base.py"
_SEPARATOR_RUN = _REPO / "core" / "separator_run.py"
_ORCHESTRATION = _REPO / "engines" / "orchestration.py"
_MDX_C_ENGINE = _REPO / "engines" / "mdx_c_engine.py"
_DEMUCS = _REPO / "engines" / "demucs_engine.py"
_INVERTED_ENGINES = (
    _REPO / "engines" / "vr.py",
    _REPO / "engines" / "mdx.py",
    _MDX_C_ENGINE,
    _DEMUCS,
)


class StemWriterModuleBoundaryTests(unittest.TestCase):
    def test_stem_writer_imports_save_format_from_audio_io(self) -> None:
        source = _WRITER.read_text(encoding="utf-8")
        self.assertIn("from core.audio_io import save_format", source)
        self.assertNotIn("from .export import", source)
        self.assertNotIn("engines.export", source)

    def test_inverted_engines_do_not_import_export_facade(self) -> None:
        for path in _INVERTED_ENGINES:
            with self.subTest(engine=path.name):
                source = path.read_text(encoding="utf-8")
                self.assertNotIn("from .export import", source)
                self.assertNotIn("engines.export", source)

    def test_stem_writer_source_does_not_mention_engines_base(self) -> None:
        source = _WRITER.read_text(encoding="utf-8")
        self.assertNotIn("engines.base", source)
        self.assertNotIn("SeperateAttributes", source)
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                module = node.module or ""
                self.assertNotEqual(module, "base")
                self.assertNotEqual(module, "engines.base")
                self.assertNotIn("SeperateAttributes", [alias.name for alias in node.names])

    def test_importing_stem_writer_does_not_import_engines_base(self) -> None:
        script = f"""
import importlib.util
import sys
import types
from pathlib import Path

root = Path({json.dumps(str(_REPO))})
pkg = types.ModuleType("engines")
pkg.__path__ = [str(root / "engines")]
pkg.__package__ = "engines"
sys.modules["engines"] = pkg
path = root / "engines" / "stem_writer.py"
spec = importlib.util.spec_from_file_location(
    "engines.stem_writer",
    path,
    submodule_search_locations=[str(root / "engines")],
)
assert spec is not None and spec.loader is not None
mod = importlib.util.module_from_spec(spec)
sys.modules["engines.stem_writer"] = mod
spec.loader.exec_module(mod)
print("engines.base" in sys.modules)
print(callable(getattr(mod, "write_audio", None)))
print(callable(getattr(mod, "export_source_map", None)))
"""
        proc = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True,
            text=True,
            check=False,
            cwd=str(_REPO),
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        lines = proc.stdout.strip().splitlines()
        self.assertEqual(lines[0], "False")
        self.assertEqual(lines[1], "True")
        self.assertEqual(lines[2], "True")


class FinishExportBoundaryTests(unittest.TestCase):
    def test_wrappers_do_not_define_export_plan_or_finish_export(self) -> None:
        for path in (_BASE, _SEPARATOR_RUN, _ORCHESTRATION):
            with self.subTest(path=path.name):
                source = path.read_text(encoding="utf-8")
                self.assertNotIn("class ExportPlan", source)
                self.assertNotIn("def finish_export", source)

    def test_inverted_engines_do_not_export_or_split_in_seperate(self) -> None:
        for path in _INVERTED_ENGINES:
            with self.subTest(engine=path.name):
                source = path.read_text(encoding="utf-8")
                self.assertNotIn("export_source_map(", source)
                self.assertNotIn("process_vocal_split_chain(", source)


class EngineInversionBoundaryTests(unittest.TestCase):
    def test_vr_and_mdx_do_not_call_legacy_writer_path(self) -> None:
        for path in _INVERTED_ENGINES:
            with self.subTest(engine=path.name):
                source = path.read_text(encoding="utf-8")
                self.assertNotIn("self.write_audio(", source)
                self.assertNotIn("self.final_process(", source)

    def test_inverted_engines_return_export_plan(self) -> None:
        for path in _INVERTED_ENGINES:
            with self.subTest(engine=path.name):
                source = path.read_text(encoding="utf-8")
                self.assertIn("ExportPlan", source)
                returns_plan = "return ExportPlan" in source or (
                    "plan = ExportPlan(" in source and "return plan" in source
                )
                self.assertTrue(returns_plan)

    def test_base_does_not_own_export_source_map(self) -> None:
        source = _BASE.read_text(encoding="utf-8")
        self.assertNotIn("export_source_map", source)
        self.assertNotIn("final_process", source)


class _FakeSep:
    def __init__(self, routes: tuple) -> None:
        self.selected_stem_routes = routes
        self.available_stem_routes = routes
        self.is_vocal_split_model = False
        self.is_ensemble_mode = False
        self.is_secondary_model = False
        self.is_pre_proc_model = False
        self.is_inst_only_voc_splitter = False
        self.is_sec_bv_rebalance = False
        self.is_karaoke = False
        self.is_bv_model = False
        self.mdx_stem_count = 2
        self.settings = None
        self.capture_stems_only = False
        self.is_save_all_outputs_ensemble = False
        self.is_save_inst_vocal_splitter = False
        self.is_bv_model_rebalenced = False
        self.is_save_vocal_only = False
        self.is_deverb_vocals = False
        self.deverb_vocal_opt = "ALL"
        self.master_vocal_path: str | None = None
        self._ensemble_stem_buffers: dict[str, object] = {}
        self._ensemble_stem_paths: dict[str, str] = {}
        self.console_messages: list[str] = []
        self.writes: list[tuple[str, object, int, str | None]] = []
        self.route_writes: list[object | None] = []
        self.split_calls: list[dict[str, object]] = []
        self.save_phase_total: int | None = None

    def begin_save_phase(self, total: int) -> None:
        self.save_phase_total = total

    def stem_export_wav_path(self, stem: str, *, route: object | None = None) -> str:
        label = getattr(route, "label", stem)
        return f"/tmp/{label}.wav"

    def write_audio(
        self,
        path: str,
        source: object,
        samplerate: int,
        stem_name: str | None = None,
        *,
        route: object | None = None,
    ) -> None:
        self.writes.append((path, source, samplerate, stem_name))
        self.route_writes.append(route)

    def _report_save_progress(self) -> None:
        pass

    def write_to_console(self, message: object, **_kwargs: object) -> None:
        self.console_messages.append(str(message))


class _EngineModelFixture:
    """Minimal ModelConfig-shaped input for the real engine attribute copy."""

    def __init__(
        self,
        *,
        routes: tuple,
        selected: tuple,
        settings: object,
        explicit: bool | None,
    ) -> None:
        self.settings = settings
        self.available_stem_routes = routes
        self.selected_stem_routes = selected
        if explicit is not None:
            self.selected_stem_routes_explicit = explicit
        self.primary_stem = "vocals"
        self.primary_stem_native = "vocals"
        self.secondary_stem = "instrumental"
        self.process_method = ""
        self.is_ensemble_mode = True
        self.model_name = "fixture"
        self.model_basename = "fixture"

    def __getattr__(self, _name: str) -> object:
        if _name == "selected_stem_routes_explicit":
            raise AttributeError(_name)
        return False


def _copy_engine_attributes(model: object):
    from core.process_data import ProcessData
    from engines.base import SeperateAttributes

    process = ProcessData(
        export_path="/tmp",
        audio_file_base="fixture",
        audio_file="/tmp/fixture.wav",
        set_progress_bar=lambda *_args, **_kwargs: None,
        write_to_console=lambda *_args, **_kwargs: None,
        process_iteration=lambda: None,
        check_run_control=lambda: None,
        cached_source_callback=lambda *_args, **_kwargs: (None, None),
        cached_model_source_holder=lambda *_args, **_kwargs: None,
        list_all_models=[],
    )
    return SeperateAttributes(model, process)  # type: ignore[arg-type]


def _route_result(model: object) -> tuple[str, object]:
    from core.stems import run_export_routes

    try:
        routes = run_export_routes(model)
    except RuntimeError as exc:
        return "error", str(exc)
    return "routes", tuple(route.concept for route in routes)


class FinishExportTests(unittest.TestCase):
    def test_empty_plan_skips_export_and_split(self) -> None:
        from engines.stem_writer import ExportPlan, finish_export

        sep = _FakeSep(())

        def _split(payload: dict) -> None:
            sep.split_calls.append(payload)

        sep.process_vocal_split_chain = _split  # type: ignore[method-assign]
        result = finish_export(sep, ExportPlan())
        self.assertEqual(result, {})
        self.assertEqual(sep.writes, [])
        self.assertEqual(sep.split_calls, [])

    def test_export_then_split_from_sources_by_default(self) -> None:
        from core.stems import StemId, StemRoute, StemRouteKind
        from engines.stem_writer import ExportPlan, finish_export

        vocals = object()
        routes = (
            StemRoute(
                native=StemId("vocals"),
                concept="Vocals",
                label="Vocals",
                filename_tag="Vocals",
                kind=StemRouteKind.NATIVE,
            ),
        )
        sep = _FakeSep(routes)
        split_calls: list[dict] = []
        sep.process_vocal_split_chain = lambda payload: split_calls.append(dict(payload))  # type: ignore[method-assign]
        plan = ExportPlan(sources={"vocals": vocals})
        result = finish_export(sep, plan)
        self.assertEqual(result, {"vocals": vocals})
        self.assertEqual(len(sep.writes), 1)
        self.assertEqual(split_calls, [{"vocals": vocals}])

    def test_extra_sources_and_explicit_split_payload(self) -> None:
        from core.stems import StemId, StemRoute, StemRouteKind
        from engines.stem_writer import ExportPlan, finish_export

        vocals = object()
        inst = object()
        chain = {"Vocals": vocals}
        routes = (
            StemRoute(
                native=StemId("vocals"),
                concept="Vocals",
                label="Vocals",
                filename_tag="Vocals",
                kind=StemRouteKind.NATIVE,
            ),
        )
        sep = _FakeSep(routes)
        split_calls: list[dict] = []
        sep.process_vocal_split_chain = lambda payload: split_calls.append(dict(payload))  # type: ignore[method-assign]
        plan = ExportPlan(
            sources={"vocals": vocals},
            extra_sources={"Instrumental": inst},
            split_sources=chain,
        )
        finish_export(sep, plan)
        self.assertEqual(
            sep.writes,
            [
                ("/tmp/Vocals.wav", vocals, 44100, "Vocals"),
                ("/tmp/Instrumental.wav", inst, 44100, "Instrumental"),
            ],
        )
        self.assertEqual(split_calls, [chain])

    def test_empty_split_sources_skips_chain(self) -> None:
        from engines.stem_writer import ExportPlan, finish_export

        sep = _FakeSep(())
        split_calls: list[dict] = []
        sep.process_vocal_split_chain = lambda payload: split_calls.append(dict(payload))  # type: ignore[method-assign]
        finish_export(
            sep,
            ExportPlan(sources={"Vocals": object()}, split_sources={}),
        )
        self.assertEqual(split_calls, [])

    def test_return_sources_override_export_map(self) -> None:
        from engines.stem_writer import ExportPlan, finish_export

        sep = _FakeSep(())
        export = {"Instrumental": object()}
        returned = {"Vocals": object(), "Instrumental": object()}
        result = finish_export(
            sep,
            ExportPlan(sources=export, return_sources=returned, split_sources={}),
        )
        self.assertEqual(result, returned)


class ExportSourceMapTests(unittest.TestCase):
    @staticmethod
    def _stem_mode_settings(*, focus: str = ""):
        from core.settings import Settings

        settings = Settings.defaults()
        settings.ensemble.main_stem = "mode.multi_stem"
        settings.process.stem_focus = focus
        return settings

    @staticmethod
    def _inventory_routes():
        from core.stem_roles import StemRoleId
        from core.stems import StemId, StemRoute, StemRouteKind

        return (
            StemRoute(
                native=StemId("vocals"),
                role=StemRoleId("vocal.vocals"),
                label="Vocals",
                filename_tag="Vocals",
                logical_primary=True,
            ),
            StemRoute(
                native=None,
                role=StemRoleId("mix.instrumental"),
                label="Instrumental Mix",
                filename_tag="Instrumental_Mix",
                kind=StemRouteKind.DERIVED,
                selected_by_default=False,
                logical_secondary=True,
            ),
        )

    def test_engine_copy_preserves_complete_stem_mode_member_inventory(self) -> None:
        from core.stem_roles import StemRoleId
        from core.stems import StemId, StemRoute

        inventory = self._inventory_routes()
        bass = StemRoute(
            StemId("bass"),
            StemRoleId("instrument.bass"),
            label="Bass",
            filename_tag="Bass",
        )
        drums = StemRoute(
            StemId("drums"),
            StemRoleId("instrument.drums"),
            label="Drums",
            filename_tag="Drums",
        )
        cases = (
            (
                "explicit full inventory still excludes optional route",
                inventory,
                inventory,
                True,
                "",
                ("routes", ("vocal.vocals",)),
            ),
            (
                "explicit empty final selection does not narrow member",
                inventory,
                (),
                True,
                "",
                ("routes", ("vocal.vocals",)),
            ),
            (
                "explicit selection and focus do not narrow member",
                (bass, drums),
                (drums,),
                True,
                "instrument.bass",
                ("routes", ("instrument.bass", "instrument.drums")),
            ),
            (
                "legacy unannotated subset does not narrow member",
                inventory,
                inventory[1:],
                None,
                "",
                ("routes", ("vocal.vocals",)),
            ),
            (
                "known unfiltered selection keeps default filtering",
                inventory,
                inventory,
                False,
                "",
                ("routes", ("vocal.vocals",)),
            ),
        )
        for label, routes, selected, explicit, focus, expected in cases:
            with self.subTest(label=label):
                model = _EngineModelFixture(
                    routes=routes,
                    selected=selected,
                    settings=self._stem_mode_settings(focus=focus),
                    explicit=explicit,
                )
                copied = _copy_engine_attributes(model)

                self.assertEqual(_route_result(model), expected)
                self.assertEqual(_route_result(copied), expected)
                self.assertEqual(
                    getattr(copied, "selected_stem_routes_explicit", None),
                    explicit,
                )

    def test_engine_copy_preserves_dual_pair_selection(self) -> None:
        from core.settings import Settings

        routes = self._inventory_routes()
        settings = Settings.defaults()
        settings.ensemble.main_stem = "pair.vocals_instrumental"
        model = _EngineModelFixture(
            routes=routes,
            selected=routes[:1],
            settings=settings,
            explicit=True,
        )
        copied = _copy_engine_attributes(model)

        self.assertEqual(_route_result(model), ("routes", ("vocal.vocals",)))
        self.assertEqual(_route_result(copied), _route_result(model))

    def test_writer_uses_complete_default_stem_mode_member_inventory(self) -> None:
        from core.stem_roles import StemRoleId
        from core.stems import StemId, StemRoute
        from engines.stem_writer import export_source_map

        inventory = self._inventory_routes()
        bass = StemRoute(
            StemId("bass"),
            StemRoleId("instrument.bass"),
            label="Bass",
            filename_tag="Bass",
        )
        drums = StemRoute(
            StemId("drums"),
            StemRoleId("instrument.drums"),
            label="Drums",
            filename_tag="Drums",
        )
        cases = (
            ("full inventory", inventory, inventory, "", [inventory[0]]),
            (
                "explicit empty",
                inventory,
                (),
                "",
                [inventory[0]],
            ),
            (
                "focus conflict",
                (bass, drums),
                (drums,),
                "instrument.bass",
                [bass, drums],
            ),
        )
        for label, routes, selected, focus, expected_writes in cases:
            with self.subTest(label=label):
                model = _EngineModelFixture(
                    routes=routes,
                    selected=selected,
                    settings=self._stem_mode_settings(focus=focus),
                    explicit=True,
                )
                sep = _copy_engine_attributes(model)
                writes: list[object] = []
                sep.begin_save_phase = lambda _total: None  # type: ignore[method-assign]
                sep.stem_export_wav_path = (  # type: ignore[method-assign]
                    lambda stem, *, route=None: f"/tmp/{stem}.wav"
                )
                sep.write_audio = (  # type: ignore[method-assign]
                    lambda _path, _source, _samplerate, stem_name=None, *, route=None, writes=writes: (
                        writes.append(route)
                    )
                )
                sources = {
                    "vocals": object(),
                    "mix.instrumental": object(),
                    "bass": object(),
                    "drums": object(),
                }

                export_source_map(sep, sources, samplerate=44100)

                self.assertEqual(writes, expected_writes)

    def test_vocal_split_schedules_only_the_declared_pair(self) -> None:
        from types import SimpleNamespace

        from core.stems import model_stem_routes
        from engines.stem_writer import export_source_map

        model = SimpleNamespace(
            canonical_id="mdx:bs_karaoke_3stem_giantailab",
            mdx_model_stems=["vocals", "backing_vocal", "instrumental"],
            demucs_source_list=[],
            primary_stem_native="vocals",
            primary_stem="vocals",
            secondary_stem="instrumental",
            target_instrument="",
            is_vocal_split_model=True,
            is_karaoke=True,
            is_bv_model=False,
            mdx_stem_count=3,
            mdxnet_stems_selected=[],
        )
        routes = model_stem_routes(model)
        sep = _FakeSep(routes)
        sep.is_vocal_split_model = True

        export_source_map(
            sep,
            {
                "vocals": object(),
                "backing_vocal": object(),
                "instrumental": object(),
            },
            samplerate=44100,
        )

        self.assertEqual(sep.save_phase_total, 2)
        self.assertEqual(
            [write[3] for write in sep.writes],
            ["Backing Vocals", "Lead Vocals"],
        )

    def test_full_mix_keeps_giantailab_third_route(self) -> None:
        from types import SimpleNamespace

        from core.stems import model_stem_routes
        from engines.stem_writer import export_source_map

        model = SimpleNamespace(
            canonical_id="mdx:bs_karaoke_3stem_giantailab",
            mdx_model_stems=["vocals", "backing_vocal", "instrumental"],
            demucs_source_list=[],
            primary_stem_native="vocals",
            primary_stem="vocals",
            secondary_stem="instrumental",
            target_instrument="",
            is_vocal_split_model=False,
            is_karaoke=True,
            is_bv_model=False,
            mdx_stem_count=3,
            mdxnet_stems_selected=[],
        )
        routes = model_stem_routes(model)
        sep = _FakeSep(tuple(route for route in routes if route.selected_by_default))

        export_source_map(
            sep,
            {
                "vocals": object(),
                "backing_vocal": object(),
                "instrumental": object(),
            },
            samplerate=44100,
        )

        self.assertEqual(sep.save_phase_total, 3)
        self.assertEqual(
            [write[3] for write in sep.writes],
            ["Lead Vocals", "Backing Vocals", "Instrumental"],
        )

    def test_native_lookup_uses_raw_key_but_writes_canonical_route_label(self) -> None:
        from core.stem_roles import StemRoleId
        from core.stems import StemId, StemRoute, StemRouteKind
        from engines.stem_writer import export_source_map

        native = object()
        decoy = object()
        route = StemRoute(
            native=StemId("DrY"),
            role=StemRoleId("effect.reverb.removed"),
            label="Reverb Removed",
            filename_tag="Reverb_Removed",
            kind=StemRouteKind.NATIVE,
            logical_primary=True,
        )
        sep = _FakeSep((route,))

        export_source_map(
            sep,
            {"dry": native, "Reverb Removed": decoy},
            samplerate=44100,
        )

        self.assertEqual(
            sep.writes,
            [("/tmp/Reverb Removed.wav", native, 44100, "Reverb Removed")],
        )
        self.assertEqual(sep.route_writes, [route])

    def test_native_route_never_falls_back_to_label_or_filename_tag(self) -> None:
        from core.stem_roles import StemRoleId
        from core.stems import StemId, StemRoute, StemRouteKind
        from engines.stem_writer import export_source_map

        route = StemRoute(
            native=StemId("dry"),
            role=StemRoleId("effect.reverb.removed"),
            label="Reverb Removed",
            filename_tag="Reverb_Removed",
            kind=StemRouteKind.NATIVE,
        )
        sep = _FakeSep((route,))

        with self.assertRaisesRegex(RuntimeError, "No audio writes"):
            export_source_map(
                sep,
                {"Reverb Removed": object(), "Reverb_Removed": object()},
                samplerate=44100,
            )

        self.assertEqual(sep.writes, [])

    def test_reviewed_role_labels_never_replace_exact_engine_source_keys(self) -> None:
        from unittest import mock

        from core.model_stem_manifest import resolve_model_stem_semantics
        from core.stem_roles import StemRoleId
        from core.stems import _semantic_routes
        from engines.stem_writer import export_source_map

        cases = (
            ("mdx:bs_mega_53stem_hh_mvsep", ("hh",), "instrument.hi_hat", "Hi-Hat"),
            ("mdx:bs_orch_xlancer", ("orch",), "instrument.orchestra", "Orchestra"),
            (
                "vr:UVR-DeEcho-DeReverb",
                ("No Reverb", "Reverb"),
                "effect.reverb_echo",
                "Reverb/Echo",
            ),
        )
        for model_id, signature, role_id, expected_label in cases:
            with self.subTest(model_id=model_id):
                semantics = resolve_model_stem_semantics(
                    model_id,
                    native_stems=signature,
                    backend_primary=signature[0],
                )
                route = next(
                    route
                    for route in _semantic_routes(semantics)
                    if route.role == StemRoleId(role_id)
                )
                assert route.native is not None
                source = object()
                label_decoy = object()
                sep = _FakeSep((route,))

                with mock.patch("engines.stem_writer.log_event") as log_event:
                    export_source_map(
                        sep,
                        {route.native.raw.swapcase(): source, route.label: label_decoy},
                        samplerate=44100,
                    )

                self.assertEqual(route.label, expected_label)
                self.assertEqual(sep.writes[0][1], source)
                self.assertNotEqual(sep.writes[0][1], label_decoy)
                write_log = next(
                    call
                    for call in log_event.call_args_list
                    if len(call.args) >= 2 and call.args[1] == "write_scheduled"
                )
                self.assertEqual(write_log.kwargs["stem"], expected_label)

    def test_reviewed_multistem_writes_components_and_residual_only(self) -> None:
        from types import SimpleNamespace

        from core.stems import model_stem_routes
        from engines.stem_writer import export_source_map

        model = SimpleNamespace(
            canonical_id="demucs:demucs",
            demucs_source_list=["drums", "bass", "other", "vocals"],
            mdx_model_stems=[],
            primary_stem_native="vocals",
            primary_stem="vocals",
            secondary_stem="instrumental",
            target_instrument="",
            is_vocal_split_model=False,
            is_karaoke=False,
            is_bv_model=False,
            demucs_stem_count=4,
            mdx_stem_count=0,
            mdxnet_stems_selected=[],
        )
        routes = model_stem_routes(model)
        sep = _FakeSep(routes)
        values = {name.upper(): object() for name in model.demucs_source_list}

        export_source_map(sep, values, samplerate=44100)

        self.assertEqual(
            [write[3] for write in sep.writes],
            ["Vocals", "Drums", "Bass", "Residual"],
        )
        self.assertNotIn("Drums Removed", [write[3] for write in sep.writes])
        self.assertNotIn("Bass Removed", [write[3] for write in sep.writes])

    def test_reviewed_target_removal_direction_uses_exact_route_names(self) -> None:
        from types import SimpleNamespace

        from core.stems import model_stem_routes
        from engines.stem_writer import export_source_map

        model = SimpleNamespace(
            canonical_id="mdx:mbr_debigreverb_sucial",
            mdx_model_stems=["dry"],
            demucs_source_list=[],
            primary_stem_native="dry",
            primary_stem="dry",
            secondary_stem="other",
            target_instrument="dry",
            is_vocal_split_model=False,
            is_karaoke=False,
            is_bv_model=False,
            mdx_stem_count=2,
            mdxnet_stems_selected=[],
        )
        routes = model_stem_routes(model)
        sep = _FakeSep(routes)

        export_source_map(
            sep,
            {"DRY": object(), "effect.reverb": object()},
            samplerate=44100,
        )

        self.assertEqual(
            [write[3] for write in sep.writes],
            ["Reverb Removed", "Reverb"],
        )

    def test_internal_capture_uses_stable_filename_tag_not_display_label(self) -> None:
        import numpy as np

        from core.stem_roles import StemRoleId
        from core.stems import StemId, StemRoute, StemRouteKind
        from engines.stem_writer import write_audio

        route = StemRoute(
            native=StemId("drum-bass"),
            role=StemRoleId("instrument.drum_bass"),
            label="Drum/Bass",
            filename_tag="Drum_Bass",
            kind=StemRouteKind.NATIVE,
        )
        sep = _FakeSep((route,))
        sep.capture_stems_only = True
        sep.is_ensemble_mode = True
        sep.is_save_all_outputs_ensemble = False
        sep.is_save_inst_vocal_splitter = False
        sep.is_bv_model_rebalenced = False
        sep.is_save_vocal_only = False
        sep.is_deverb_vocals = False
        sep.deverb_vocal_opt = "ALL"
        sep.master_vocal_path = None
        sep._ensemble_stem_buffers = {}
        sep._ensemble_stem_paths = {}
        source = np.ones((4, 2), dtype=np.float32)

        write_audio(
            sep,
            "/tmp/song (Drum-Bass).wav",
            source,
            44100,
            stem_name=route.label,
            route=route,
        )

        self.assertEqual(list(sep._ensemble_stem_buffers), ["Drum_Bass"])
        self.assertEqual(
            sep._ensemble_stem_paths,
            {"Drum_Bass": "/tmp/song (Drum-Bass).wav"},
        )
        self.assertTrue(any("Drum/Bass" in message for message in sep.console_messages))

    def test_writes_selected_routes_and_skips_missing(self) -> None:
        from core.stems import StemId, StemRoute, StemRouteKind
        from engines.stem_writer import export_source_map

        vocals = object()
        routes = (
            StemRoute(
                native=StemId("vocals"),
                concept="Vocals",
                label="Vocals",
                filename_tag="Vocals",
                kind=StemRouteKind.NATIVE,
            ),
            StemRoute(
                native=StemId("other"),
                concept="Instrumental",
                label="Instrumental",
                filename_tag="Instrumental",
                kind=StemRouteKind.NATIVE,
            ),
        )
        sep = _FakeSep(routes)
        export_source_map(sep, {"vocals": vocals}, samplerate=44100)
        self.assertEqual(sep.save_phase_total, 2)
        self.assertEqual(
            sep.writes,
            [("/tmp/Vocals.wav", vocals, 44100, "Vocals")],
        )

    def test_reviewed_derived_route_uses_stable_role_key_not_presentation(self) -> None:
        from core.stem_roles import StemRoleId
        from core.stems import StemRoute, StemRouteKind
        from engines.stem_writer import export_source_map

        complement = object()
        label_decoy = object()
        tag_decoy = object()
        route = StemRoute(
            native=None,
            role=StemRoleId("mix.instrumental"),
            label="Rendered Instrumental",
            filename_tag="Rendered_Instrumental",
            kind=StemRouteKind.DERIVED,
        )
        sep = _FakeSep((route,))
        export_source_map(
            sep,
            {
                "mix.instrumental": complement,
                route.label: label_decoy,
                route.filename_tag: tag_decoy,
            },
            samplerate=44100,
        )
        self.assertEqual(
            sep.writes,
            [
                (
                    "/tmp/Rendered Instrumental.wav",
                    complement,
                    44100,
                    "Rendered Instrumental",
                )
            ],
        )

    def test_karaoke_complement_matches_plain_instrumental_source(self) -> None:
        from core.stems import StemBucket, derived_stem_route
        from engines.stem_writer import export_source_map

        complement = object()
        route = derived_stem_route(StemBucket.INST_WITH_BV)
        sep = _FakeSep((route,))
        sep.is_karaoke = True
        sep.is_bv_model = False
        sep.mdx_stem_count = 2

        export_source_map(sep, {"Instrumental": complement}, samplerate=44100)

        self.assertEqual(
            sep.writes,
            [
                (
                    "/tmp/Instrumental (With Backing Vocals).wav",
                    complement,
                    44100,
                    "Instrumental (With Backing Vocals)",
                )
            ],
        )

    def test_bv_complement_matches_plain_instrumental_source(self) -> None:
        from core.stems import StemBucket, derived_stem_route
        from engines.stem_writer import export_source_map

        complement = object()
        route = derived_stem_route(StemBucket.INST_WITH_LEAD)
        sep = _FakeSep((route,))
        sep.is_karaoke = False
        sep.is_bv_model = True
        sep.mdx_stem_count = 2

        export_source_map(sep, {"Instrumental": complement}, samplerate=44100)

        self.assertEqual(
            sep.writes,
            [
                (
                    "/tmp/Instrumental (With Lead Vocals).wav",
                    complement,
                    44100,
                    "Instrumental (With Lead Vocals)",
                )
            ],
        )

    def test_nonempty_unresolvable_export_raises(self) -> None:
        from core import debug_log
        from core.stems import StemLiteral, derived_stem_route
        from engines.stem_writer import export_source_map

        route = derived_stem_route(StemLiteral("Wanted"))
        sep = _FakeSep((route,))

        with tempfile.TemporaryDirectory() as tmp:
            log_path = Path(tmp) / "uvr.log"
            debug_log.configure(level="errors", log_file=str(log_path))
            self.addCleanup(debug_log.configure, level="errors", log_file="")

            with self.assertRaisesRegex(
                RuntimeError,
                r"Wanted.*available.*Other",
            ):
                export_source_map(sep, {"Other": object()}, samplerate=44100)

            diagnostic = log_path.read_text(encoding="utf-8")
            self.assertIn("event=export_no_writes", diagnostic)
            self.assertIn("component=audio", diagnostic)
            self.assertIn("requested", diagnostic)
            self.assertIn("available", diagnostic)

        self.assertEqual(sep.writes, [])

    def test_ambiguous_derived_source_match_raises(self) -> None:
        from core.stems import StemBucket, derived_stem_route
        from engines.stem_writer import export_source_map

        route = derived_stem_route(StemBucket.INST_WITH_BV)
        sep = _FakeSep((route,))
        sep.is_karaoke = True
        sep.is_bv_model = False
        sep.mdx_stem_count = 2

        with self.assertRaisesRegex(
            RuntimeError,
            r"Ambiguous.*Instrumental.*Other",
        ):
            export_source_map(
                sep,
                {"Instrumental": object(), "Other": object()},
                samplerate=44100,
            )

        self.assertEqual(sep.writes, [])

    def test_empty_routes_do_not_start_save_phase(self) -> None:
        from engines.stem_writer import export_source_map

        sep = _FakeSep(())
        export_source_map(sep, {"vocals": object()}, samplerate=44100)
        self.assertIsNone(sep.save_phase_total)
        self.assertEqual(sep.writes, [])

    def test_extra_sources_write_after_routes(self) -> None:
        """Non-route sidecars should share one save phase.

        The current implementation has no ``extra_sources`` support, so this
        test intentionally fails until Demucs adds the in-engine source-map
        post-pass extension.
        """
        from core.stems import StemId, StemRoute, StemRouteKind
        from engines.stem_writer import export_source_map

        vocals = object()
        inst = object()
        routes = (
            StemRoute(
                native=StemId("vocals"),
                concept="Vocals",
                label="Vocals",
                filename_tag="Vocals",
                kind=StemRouteKind.NATIVE,
            ),
        )
        sep = _FakeSep(routes)

        export_source_map(
            sep,
            {"vocals": vocals},
            samplerate=44100,
            # Explicit sidecar: must write but must not depend on StemRoute.
            extra_sources={"Instrumental": inst},
        )

        self.assertEqual(sep.save_phase_total, 2)
        # Route is written first, then extra sources.
        self.assertEqual(
            sep.writes,
            [
                ("/tmp/Vocals.wav", vocals, 44100, "Vocals"),
                ("/tmp/Instrumental.wav", inst, 44100, "Instrumental"),
            ],
        )


if __name__ == "__main__":
    unittest.main()
