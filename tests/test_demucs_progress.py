"""Exercise Demucs progress recursion without weights or a GTK display."""

from __future__ import annotations

import unittest
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from typing import cast
from unittest.mock import patch

import torch

from core.run_control import ProcessStopped, pausable_callback
from ui.run_progress import RunProgressPresenter
from vendor.demucs.apply import BagOfModels, Model, apply_model
from vendor.demucs.utils import apply_model_v1, apply_model_v2


class TinyDemucs(torch.nn.Module):
    sources = ("drums", "bass", "other", "vocals")
    samplerate = 8
    audio_channels = 2
    segment = 1
    segment_length = 8

    def __init__(self, before_forward: Callable[[], object]):
        super().__init__()
        self.weight = torch.nn.Parameter(torch.ones(()))
        self.before_forward = before_forward

    def valid_length(self, length: int) -> int:
        return length

    def forward(self, mix: torch.Tensor) -> torch.Tensor:
        self.before_forward()
        return mix[:, None].repeat(1, 4, 1, 1) * self.weight


class DemucsProgressTests(unittest.TestCase):
    def exercise(
        self,
        version: int,
        *,
        bag_size: int = 1,
        shifts: int = 1,
        split: bool = True,
        workers: int = 0,
    ) -> list[float]:
        ticks: list[float] = []
        during_inference: list[float] = []

        def callback(step: float, iterations: float = 0) -> None:
            ticks.append(step + iterations)

        models = [TinyDemucs(lambda: during_inference.append(ticks[-1])) for _ in range(bag_size)]
        mix = torch.ones(1, 2, 96)
        # Fix shift lengths so the output and per-model milestones are deterministic.
        with patch("vendor.demucs.apply.random.randint", return_value=4):
            if version == 4:
                model = BagOfModels(cast(list[Model], models)) if bag_size > 1 else models[0]
                output = apply_model(
                    model,
                    mix,
                    shifts=shifts,
                    split=split,
                    num_workers=workers,
                    set_progress_bar=callback,
                )
            else:
                apply = apply_model_v1 if version == 1 else apply_model_v2
                output = apply(
                    models[0], mix[0], shifts=shifts, split=split, set_progress_bar=callback
                )[None]
        torch.testing.assert_close(output, mix[:, None].repeat(1, 4, 1, 1))
        self.assertTrue(during_inference)
        self.assertLess(max(during_inference), 0.9, "Saving was reported before inference finished")
        self.assertAlmostEqual(ticks[0], 0.1)
        self.assertAlmostEqual(ticks[-1], 0.9)
        for before, after in zip(ticks, ticks[1:], strict=False):
            self.assertGreaterEqual(after + 1e-12, before, "Progress moved backwards")
        if split or shifts > 1 or bag_size > 1:
            self.assertTrue(any(0.1 < tick < 0.9 for tick in ticks))
        return ticks

    def test_ft_bag_never_reports_saving_between_segments_or_models(self):
        ticks = self.exercise(4, bag_size=4, shifts=2)
        presenter = RunProgressPresenter()
        presenter.reset(0)
        for index, tick in enumerate(ticks[:-1]):
            presentation = presenter.update(
                tick, index + 1, local_step=tick, pass_index=1, pass_total=1
            )
            self.assertIsNotNone(presentation)
            assert presentation is not None
            self.assertEqual(presentation.title, "Processing")
        # All four FT members contribute; none can complete the whole pass alone.
        for milestone in (0.3, 0.5, 0.7):
            self.assertTrue(any(abs(tick - milestone) < 1e-12 for tick in ticks))

    def test_single_model_split_and_unsplit_with_and_without_shifts(self):
        for split in (False, True):
            for shifts in (0, 1, 2):
                with self.subTest(split=split, shifts=shifts):
                    self.exercise(4, split=split, shifts=shifts)

    def test_cpu_parallel_segments_report_ordered_parent_progress(self):
        self.exercise(4, bag_size=4, workers=2)

    def test_legacy_demucs_nested_segments_and_shifts(self):
        for version in (1, 2):
            for split in (False, True):
                for shifts in (0, 2):
                    with self.subTest(version=version, split=split, shifts=shifts):
                        self.exercise(version, split=split, shifts=shifts)

    def test_stop_prevents_queued_cpu_segments_from_entering_the_model(self):
        runner = SimpleNamespace(_is_paused=False, _is_stopped=False)
        forwards = []

        def stop_during_inference():
            forwards.append(True)
            runner._is_stopped = True

        model = TinyDemucs(stop_during_inference)
        callback = pausable_callback(runner, lambda *_: None)
        # A single worker makes the cancellation boundary deterministic: the
        # first chunk requests Stop; every queued chunk must check before work.
        with ThreadPoolExecutor(1) as pool:
            with self.assertRaises(ProcessStopped):
                apply_model(
                    model, torch.ones(1, 2, 96), shifts=0, pool=pool, set_progress_bar=callback
                )
        self.assertEqual(len(forwards), 1)
