from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from core.access_policy import AccessPolicy, access_policy, current_access_policy


class AccessPolicyTests(unittest.TestCase):
    def test_default_allows_network_and_writes(self) -> None:
        self.assertEqual(
            current_access_policy(),
            AccessPolicy(allow_network=True, allow_metadata_writes=True),
        )

    def test_context_restores_previous_policy(self) -> None:
        with access_policy(allow_network=False, allow_metadata_writes=False):
            self.assertFalse(current_access_policy().allow_network)
            with access_policy(allow_network=True, allow_metadata_writes=False):
                self.assertTrue(current_access_policy().allow_network)
                self.assertFalse(current_access_policy().allow_metadata_writes)
            self.assertFalse(current_access_policy().allow_network)
        self.assertTrue(current_access_policy().allow_network)

    def test_does_not_mutate_process_environment(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            with access_policy(allow_network=False, allow_metadata_writes=False):
                self.assertNotIn("UVR_DISABLE_POLITREES", os.environ)
                self.assertNotIn("UVR_DISABLE_MVSEPLESS", os.environ)
