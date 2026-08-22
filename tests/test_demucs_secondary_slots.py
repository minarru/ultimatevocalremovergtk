"""Unit tests for per-stem secondary model resolution in the Demucs 4-stem path."""

from __future__ import annotations

import unittest
from typing import Any, cast

from bundled.constants import (
    BASS_STEM,
    DEMUCS_4_SOURCE_MAPPER,
    DRUM_STEM,
    OTHER_STEM,
    VOCAL_STEM,
)
from engines.demucs_engine import secondary_4_stem_slot


class _Model:
    """Stand-in for a ModelConfig; only identity matters here."""

    def __init__(self, name: str) -> None:
        self.name = name
        # Default to a 4-stem Demucs-like identity so the Demucs inversion's
        # 2-source special-case has a predictable false branch.
        self.demucs_stem_count = 4

    def __repr__(self) -> str:  # pragma: no cover - failure output only
        return f"<{self.name}>"


class Secondary4StemSlotTests(unittest.TestCase):
    def test_configured_slot_returns_its_own_model_and_scale(self) -> None:
        models = [_Model("bass"), _Model("drums"), _Model("other"), _Model("vocals")]
        scales = [0.5, 0.6, 0.7, 0.9]
        for index, model in enumerate(models):
            self.assertEqual(
                secondary_4_stem_slot(models, scales, index), (model, scales[index])
            )

    def test_unconfigured_slot_does_not_inherit_previous_stem(self) -> None:
        """The regression: only Bass has a secondary model.

        ``is_secondary_model_activated`` is true when *any* stem has one, so the
        export loop runs for every stem. Drums/Other/Vocals must come back empty
        rather than reusing the Bass model and its blend scale, which would mix
        bass audio into three unrelated stems.
        """
        bass = _Model("bass")
        models = [bass, None, None, None]
        scales = [0.5, None, None, None]

        self.assertEqual(
            secondary_4_stem_slot(models, scales, DEMUCS_4_SOURCE_MAPPER[BASS_STEM]),
            (bass, 0.5),
        )
        for stem in (DRUM_STEM, OTHER_STEM, VOCAL_STEM):
            with self.subTest(stem=stem):
                self.assertEqual(
                    secondary_4_stem_slot(
                        models, scales, DEMUCS_4_SOURCE_MAPPER[stem]
                    ),
                    (None, None),
                )

    def test_gap_between_configured_slots_stays_empty(self) -> None:
        bass, vocals = _Model("bass"), _Model("vocals")
        models = [bass, None, None, vocals]
        scales = [0.5, None, None, 0.9]

        resolved = [secondary_4_stem_slot(models, scales, i) for i in range(4)]
        self.assertEqual(
            resolved, [(bass, 0.5), (None, None), (None, None), (vocals, 0.9)]
        )

    def test_six_stem_extra_slots_are_empty(self) -> None:
        """Guitar/piano (indices 4-5) have no secondary entries at all."""
        models = [_Model("bass"), _Model("drums"), _Model("other"), _Model("vocals")]
        scales = [0.5, 0.6, 0.7, 0.9]
        for index in (4, 5):
            with self.subTest(index=index):
                self.assertEqual(
                    secondary_4_stem_slot(models, scales, index), (None, None)
                )

    def test_empty_or_missing_configuration_is_empty(self) -> None:
        self.assertEqual(secondary_4_stem_slot([], [], 0), (None, None))
        self.assertEqual(secondary_4_stem_slot(None, None, 0), (None, None))

    def test_model_without_scale_returns_none_scale(self) -> None:
        """A scale list shorter than the model list must not IndexError."""
        model = _Model("bass")
        self.assertEqual(secondary_4_stem_slot([model], [], 0), (model, None))


class _StubSeperateDemucs:
    """Minimal harness that drives the real ``seperate`` 4-stem export loop.

    Reaches the loop via the primary-source cache path, so no Demucs model,
    torch, or audio decode is involved; every I/O boundary is recorded instead.
    """

    def __init__(self, secondary_models: Any, secondary_scales: Any) -> None:
        import numpy as np

        from bundled.constants import ALL_STEMS
        from core.stems import StemId, StemRoute, StemRouteKind

        self.model_basename = "demucs-test"
        self.model_cache_key = "demucs-test"
        self.model_display_label = "demucs-test"
        self.primary_model_name = "demucs-test"
        # 4 stems x 2 channels x 8 frames, each stem a distinct constant.
        self.primary_sources = np.stack(
            [np.full((2, 8), float(i + 1)) for i in range(4)]
        )
        self.demucs_stem_count = 4
        self.pre_proc_model = None
        self.is_vocal_split_model = False
        self.demucs_stems = ALL_STEMS
        self.is_4_stem_ensemble = False
        self.is_return_dual = False
        self.is_match_mix_level = False
        self.is_prevent_export_clipping = False
        self.is_secondary_model_activated = True
        self.is_secondary_model = False
        self.is_pre_proc_model = False
        self.is_sec_bv_rebalance = True
        self.secondary_model_4_stem = secondary_models
        self.secondary_model_4_stem_scale = secondary_scales
        self.demucs_source_map = {}
        # For inversion, the real implementation exports through
        # ``export_source_map``, which depends on export routes.
        # Seed a minimal native + derived inventory so export doesn't become
        # a no-op.
        self.available_stem_routes = (
            StemRoute(
                native=StemId("drums"),
                concept="Drums",
                label="Drums",
                filename_tag="Drums",
                kind=StemRouteKind.NATIVE,
            ),
            StemRoute(
                native=StemId("bass"),
                concept="Bass",
                label="Bass",
                filename_tag="Bass",
                kind=StemRouteKind.NATIVE,
            ),
            StemRoute(
                native=StemId("other"),
                concept="Other",
                label="Other",
                filename_tag="Other",
                kind=StemRouteKind.NATIVE,
            ),
            StemRoute(
                native=StemId("vocals"),
                concept="Vocals",
                label="Vocals",
                filename_tag="Vocals",
                kind=StemRouteKind.NATIVE,
            ),
            # Derived complement needed by pair gathering / demucs pre-proc.
            StemRoute(
                native=None,
                concept="Instrumental",
                label="Instrumental",
                filename_tag="Instrumental",
                kind=StemRouteKind.DERIVED,
            ),
        )
        self.selected_stem_routes = self.available_stem_routes
        self.process_data = type("PD", (), {"is_ensemble_master": False})()
        self.blend_calls: list[tuple[str, object, object]] = []
        # In the legacy writer loop, ``stem_export_wav_path`` was called before
        # ``process_secondary_stem`` so tests inferred which stem was blended
        # from a side effect. The inversion moves export later, so record stem
        # identity from the constant-valued stub audio instead.
        self._stem_by_constant = {
            1.0: BASS_STEM,
            2.0: DRUM_STEM,
            3.0: OTHER_STEM,
            4.0: VOCAL_STEM,
        }
        self._current_stem = ""

    # -- stubbed boundaries -------------------------------------------------
    def load_cached_sources(self) -> None:
        pass

    def cache_source(self, sources: Any) -> None:
        pass

    def begin_save_phase(self, total: int) -> None:
        pass

    def stem_export_wav_path(self, stem: str) -> str:
        self._current_stem = stem
        return f"/dev/null/{stem}.wav"

    def process_secondary_stem(
        self,
        stem_source: Any,
        secondary_model_source: Any = None,
        model_scale: Any = None,
    ) -> Any:
        import numpy as np

        # Both (2, N) and (N, 2) stub arrays start with the stem's constant.
        first = float(np.asarray(stem_source).reshape(-1)[0])
        stem_name = self._stem_by_constant.get(first, self._current_stem)
        self.blend_calls.append(
            (stem_name, secondary_model_source, model_scale)
        )
        return stem_source

    def write_audio(self, *args: Any, **kwargs: Any) -> None:
        pass

    def process_vocal_split_chain(self, stems: Any) -> None:  # pragma: no cover
        pass


class Demucs4StemExportLoopTests(unittest.TestCase):
    """The loop itself must not carry a stem's secondary source into the next."""

    #: A secondary model returning a full per-stem dict. Keyed for every stem so
    #: a leaked model resolves successfully and yields a *wrong* source, rather
    #: than incidentally raising KeyError on a missing key.
    _SECONDARY_DICT = {
        BASS_STEM: "sec-bass",
        DRUM_STEM: "sec-drums",
        OTHER_STEM: "sec-other",
        VOCAL_STEM: "sec-vocals",
    }

    def _run(self, secondary_models: Any, secondary_scales: Any) -> tuple[Any, Any]:
        from unittest import mock

        from engines.demucs_engine import SeperateDemucs

        stub = _StubSeperateDemucs(secondary_models, secondary_scales)
        with mock.patch(
            "engines.demucs_engine.process_secondary_model",
            return_value=dict(self._SECONDARY_DICT),
        ) as run_secondary:
            SeperateDemucs.seperate(stub)  # type: ignore[arg-type]
        return stub.blend_calls, run_secondary

    def test_only_configured_stem_receives_a_secondary_source(self) -> None:
        bass = _Model("bass")
        calls, run_secondary = self._run([bass, None, None, None], [0.5, None, None, None])

        # The decisive assertion: exactly one secondary inference, for Bass.
        self.assertEqual(
            run_secondary.call_count,
            1,
            "a stem with no secondary model of its own ran one anyway",
        )
        self.assertIs(run_secondary.call_args.args[0], bass)

        self.assertEqual(len(calls), 4)
        by_stem = {stem: (src, scale) for stem, src, scale in calls}
        self.assertEqual(by_stem[BASS_STEM], ("sec-bass", 0.5))
        for stem in (DRUM_STEM, OTHER_STEM, VOCAL_STEM):
            with self.subTest(stem=stem):
                self.assertEqual(
                    by_stem[stem],
                    (None, None),
                    f"{stem} inherited the previous stem's secondary model or scale",
                )

    def test_each_configured_stem_uses_its_own_model_and_scale(self) -> None:
        bass, vocals = _Model("bass"), _Model("vocals")
        calls, run_secondary = self._run([bass, None, None, vocals], [0.5, None, None, 0.9])

        self.assertEqual(run_secondary.call_count, 2)
        by_stem = {stem: (src, scale) for stem, src, scale in calls}
        self.assertEqual(by_stem[BASS_STEM], ("sec-bass", 0.5))
        self.assertEqual(by_stem[VOCAL_STEM], ("sec-vocals", 0.9))
        self.assertEqual(by_stem[DRUM_STEM], (None, None))
        self.assertEqual(by_stem[OTHER_STEM], (None, None))

    def test_no_secondary_models_blends_nothing(self) -> None:
        calls, run_secondary = self._run([None] * 4, [None] * 4)
        self.assertEqual(run_secondary.call_count, 0)
        self.assertEqual(
            [(src, scale) for _stem, src, scale in calls], [(None, None)] * 4
        )

    def test_two_source_secondary_model_dict_uses_vocals_slot(self) -> None:
        """Regression target: a 2-source demix should use its Vocals output.

        The legacy ndarray path always selected index 1 (vocals) regardless
        of which 4-stem slot was being blended. The inversion needs the same
        behavior when the nested secondary returns a dict.
        """

        class _TwoSourceDemucs:
            demucs_stem_count = 2

        bass_2s = _TwoSourceDemucs()

        from unittest import mock

        from engines.demucs_engine import SeperateDemucs

        stub = _StubSeperateDemucs([bass_2s, None, None, None], [0.5, None, None, None])

        with mock.patch(
            "engines.demucs_engine.process_secondary_model",
            return_value={"Vocals": "sec-vocals", "Instrumental": "sec-instrumental"},
        ):
            # type: ignore[arg-type]
            SeperateDemucs.seperate(stub)  # type: ignore[arg-type]

        by_stem = {stem: (src, scale) for stem, src, scale in stub.blend_calls}
        self.assertEqual(by_stem[BASS_STEM], ("sec-vocals", 0.5))

    def test_secondary_return_contains_derived_instrumental(self) -> None:
        """A nested 4-stem Demucs secondary should return a dict with Instrumental."""
        from engines.demucs_engine import SeperateDemucs

        stub = _StubSeperateDemucs([None, None, None, None], [None, None, None, None])
        stub.is_secondary_model = True
        stub.is_sec_bv_rebalance = True  # avoid vocal-split side effects

        from engines.stem_writer import ExportPlan

        # type: ignore[arg-type]
        result = SeperateDemucs.seperate(stub)  # type: ignore[arg-type]
        self.assertIsInstance(result, ExportPlan)
        payload = (
            result.return_sources
            if result.return_sources is not None
            else result.sources
        )
        self.assertIn("Instrumental", payload)


if __name__ == "__main__":
    unittest.main()
