import os
import unittest

from bundled.constants import DEMUCS_V4
from core import paths
from core.demucs_models import (
    demucs_bag_owner_basename,
    demucs_pretrained_load_name,
    demucs_yaml_bag_member_sigs,
    is_demucs_bag_member_weight,
    resolve_demucs_model_file,
)


class DemucsBagMemberTests(unittest.TestCase):
    def test_hdemucs_mmi_bag_lists_member_sig(self):
        yaml_path = os.path.join(paths.DEMUCS_NEWER_REPO_DIR, "hdemucs_mmi.yaml")
        if not os.path.isfile(yaml_path):
            self.skipTest("hdemucs_mmi.yaml not present (downloaded weights only)")
        sigs = demucs_yaml_bag_member_sigs(paths.DEMUCS_NEWER_REPO_DIR)
        self.assertIn("75fc33f5", sigs)

    def test_bag_member_weight_is_detected(self):
        self.assertTrue(
            is_demucs_bag_member_weight("75fc33f5-1941ce65", {"75fc33f5"})
        )
        self.assertFalse(
            is_demucs_bag_member_weight("demucs-e07c671f", {"75fc33f5"})
        )

    def test_bag_owner_basename_for_member_th(self):
        owner = demucs_bag_owner_basename("75fc33f5-1941ce65")
        if owner is not None:
            self.assertEqual(owner, "hdemucs_mmi")
        self.assertIsNone(demucs_bag_owner_basename("hdemucs_mmi"))

    def test_pretrained_load_name_for_yaml_bag(self):
        yaml_path = os.path.join(paths.DEMUCS_NEWER_REPO_DIR, "hdemucs_mmi.yaml")
        if os.path.isfile(yaml_path):
            self.assertEqual(demucs_pretrained_load_name(yaml_path), "hdemucs_mmi")

    def test_pretrained_load_name_for_member_weight(self):
        th_path = os.path.join(paths.DEMUCS_NEWER_REPO_DIR, "75fc33f5-1941ce65.th")
        if os.path.isfile(th_path):
            self.assertEqual(demucs_pretrained_load_name(th_path), "75fc33f5")

    def test_resolve_member_weight_path(self):
        resolved = resolve_demucs_model_file("75fc33f5-1941ce65", DEMUCS_V4)
        expected = os.path.join(paths.DEMUCS_NEWER_REPO_DIR, "75fc33f5-1941ce65.th")
        if os.path.isfile(expected):
            self.assertEqual(resolved, expected)


if __name__ == "__main__":
    unittest.main()
