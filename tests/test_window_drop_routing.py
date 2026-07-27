"""Which input row a window-level file drop is routed to."""

from __future__ import annotations

import unittest

from ui.window import drop_target_row_name

_DUAL = {"Manual Ensemble", "Align Inputs"}


class DropRoutingTests(unittest.TestCase):
    def test_separation_tab_routes_to_its_input_row(self):
        self.assertEqual(
            drop_target_row_name("separation", None, _DUAL), "separation"
        )

    def test_ensemble_tab_routes_to_its_input_row(self):
        self.assertEqual(drop_target_row_name("ensemble", None, _DUAL), "ensemble")

    def test_single_input_audio_tool_routes_to_its_input_row(self):
        self.assertEqual(
            drop_target_row_name("audio_tools", "Change Pitch", _DUAL), "audio_tools"
        )

    def test_dual_input_audio_tool_is_not_routed(self):
        self.assertIsNone(
            drop_target_row_name("audio_tools", "Manual Ensemble", _DUAL)
        )

    def test_unknown_tab_is_not_routed(self):
        self.assertIsNone(drop_target_row_name("mystery", None, _DUAL))

    def test_missing_tab_name_is_not_routed(self):
        self.assertIsNone(drop_target_row_name(None, None, _DUAL))


if __name__ == "__main__":
    unittest.main()
