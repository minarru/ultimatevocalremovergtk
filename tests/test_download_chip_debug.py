"""Tests for UVR_DEBUG_QUEUE_CHIP scenario helpers."""

import os
import unittest
from unittest import mock

from ui.download import (
    _CHIP_DEBUG_ORDER,
    chip_debug_items_for,
    parse_chip_debug_scenarios,
)
from ui.widgets.download_queue_indicator import chip_ring_state, summarize_queue


class ChipDebugScenarioTests(unittest.TestCase):
    def test_parse_cycle_aliases(self) -> None:
        for value in ("1", "true", "cycle", "all"):
            with self.subTest(value=value):
                with mock.patch.dict(os.environ, {"UVR_DEBUG_QUEUE_CHIP": value}, clear=False):
                    self.assertEqual(parse_chip_debug_scenarios(), list(_CHIP_DEBUG_ORDER))

    def test_parse_single_scenario(self) -> None:
        with mock.patch.dict(os.environ, {"UVR_DEBUG_QUEUE_CHIP": "cancelled"}, clear=False):
            self.assertEqual(parse_chip_debug_scenarios(), ["cancelled"])

    def test_parse_comma_list(self) -> None:
        with mock.patch.dict(
            os.environ,
            {"UVR_DEBUG_QUEUE_CHIP": "success,partial,unknown"},
            clear=False,
        ):
            self.assertEqual(parse_chip_debug_scenarios(), ["success", "partial"])

    def test_parse_empty_when_unset(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertIsNone(parse_chip_debug_scenarios())

    def test_each_scenario_maps_to_expected_chip_outcome(self) -> None:
        expectations = {
            "active": "active",
            "success": "success",
            "partial": "partial",
            "failed": "failed",
            "cancelled": "cancelled",
        }
        for scenario, outcome in expectations.items():
            with self.subTest(scenario=scenario):
                items = chip_debug_items_for(scenario)
                summary = summarize_queue(items)
                state = chip_ring_state(items, summary)
                self.assertEqual(state.outcome, outcome)
                self.assertTrue(summary.chip_label)


if __name__ == "__main__":
    unittest.main()
