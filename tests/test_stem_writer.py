"""Boundary tests for the extracted stem writer."""

from __future__ import annotations

import ast
import json
import subprocess
import sys
import unittest
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
_WRITER = _REPO / "engines" / "stem_writer.py"
_BASE = _REPO / "engines" / "base.py"
_MDXC = _REPO / "engines" / "mdx_c.py"
_DEMUCS = _REPO / "engines" / "demucs_engine.py"
_INVERTED_ENGINES = (
    _REPO / "engines" / "vr.py",
    _REPO / "engines" / "mdx.py",
    _DEMUCS,
)


class StemWriterModuleBoundaryTests(unittest.TestCase):
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
                self.assertNotIn(
                    "SeperateAttributes", [alias.name for alias in node.names]
                )

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


class EngineInversionBoundaryTests(unittest.TestCase):
    def test_vr_and_mdx_do_not_call_legacy_writer_path(self) -> None:
        for path in _INVERTED_ENGINES:
            with self.subTest(engine=path.name):
                source = path.read_text(encoding="utf-8")
                self.assertNotIn("self.write_audio(", source)
                self.assertNotIn("self.final_process(", source)

    def test_vr_and_mdx_use_source_map_post_pass(self) -> None:
        for path in _INVERTED_ENGINES:
            with self.subTest(engine=path.name):
                source = path.read_text(encoding="utf-8")
                self.assertIn("self.process_secondary_stem(", source)
                # Variable name differs between engines (e.g. ``sources`` vs
                # ``export_sources``) so only assert on the call shape.
                self.assertIn("export_source_map(self,", source)

    def test_mdxc_does_not_call_legacy_writer_path(self) -> None:
        source = _MDXC.read_text(encoding="utf-8")
        self.assertNotIn("self.write_audio(", source)
        self.assertNotIn("self.final_process(", source)

    def test_mdxc_uses_source_map_post_pass(self) -> None:
        source = _MDXC.read_text(encoding="utf-8")
        self.assertIn("export_source_map(self, export_sources,", source)

    def test_final_process_remains_a_writer_for_other_engines(self) -> None:
        source = _BASE.read_text(encoding="utf-8")
        tree = ast.parse(source)
        final_process = next(
            node
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == "final_process"
        )
        self.assertIn("self.write_audio(", ast.unparse(final_process))

    def test_base_does_not_own_export_source_map(self) -> None:
        source = _BASE.read_text(encoding="utf-8")
        self.assertNotIn("export_source_map", source)


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
        self.settings = None
        self.writes: list[tuple[str, object, int, str | None]] = []
        self.save_phase_total: int | None = None

    def begin_save_phase(self, total: int) -> None:
        self.save_phase_total = total

    def stem_export_wav_path(self, stem: str) -> str:
        return f"/tmp/{stem}.wav"

    def write_audio(
        self,
        path: str,
        source: object,
        samplerate: int,
        stem_name: str | None = None,
    ) -> None:
        self.writes.append((path, source, samplerate, stem_name))


class ExportSourceMapTests(unittest.TestCase):
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
            [("/tmp/vocals.wav", vocals, 44100, "vocals")],
        )

    def test_derived_route_looks_up_label(self) -> None:
        from core.stems import StemBucket, derived_stem_route
        from engines.stem_writer import export_source_map

        complement = object()
        route = derived_stem_route(StemBucket.INSTRUMENTAL, label="Instrumental")
        sep = _FakeSep((route,))
        export_source_map(sep, {"Instrumental": complement}, samplerate=44100)
        self.assertEqual(
            sep.writes,
            [("/tmp/Instrumental.wav", complement, 44100, "Instrumental")],
        )

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
                ("/tmp/vocals.wav", vocals, 44100, "vocals"),
                ("/tmp/Instrumental.wav", inst, 44100, "Instrumental"),
            ],
        )


if __name__ == "__main__":
    unittest.main()
