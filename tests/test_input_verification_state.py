"""Completed probes belong to the current application verification generation."""

import unittest
from unittest.mock import patch

from core.settings import Settings
from ui.context import AppContext


class InputVerificationStateTests(unittest.TestCase):
    def setUp(self):
        with patch('ui.context.Settings.load', return_value=Settings.defaults()):
            self.context = AppContext()
        self.context.settings.process.input_paths = ['fixed', 'unchecked', 'new']
        self.context.unreadable_input_paths = {'fixed', 'unchecked', 'new'}

    def test_partial_results_clear_only_rechecked_paths_and_do_not_restore_removed_inputs(self):
        generation = self.context.begin_input_verification()
        self.assertTrue(
            self.context.apply_input_verification(generation, ['fixed', 'removed'], ['removed'])
        )
        self.assertEqual(self.context.unreadable_input_paths, {'unchecked', 'new'})
        self.assertEqual(self.context.settings.process.input_paths, ['fixed', 'unchecked', 'new'])

    def test_old_scan_cannot_overwrite_a_new_scan(self):
        old = self.context.begin_input_verification()
        new = self.context.begin_input_verification()
        self.context.apply_input_verification(new, ['fixed'], ['fixed'])
        self.assertFalse(self.context.apply_input_verification(old, ['fixed'], []))
        self.assertIn('fixed', self.context.unreadable_input_paths)
