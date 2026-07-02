import unittest

from data.constants import MDX_ARCH_TYPE, VR_ARCH_PM, VR_ARCH_TYPE
from uvr_gtk.window import _METHOD_SETTING_ALIASES


class MethodSettingAliasTests(unittest.TestCase):
    def test_vr_arc_maps_to_vr_architecture(self):
        self.assertEqual(_METHOD_SETTING_ALIASES[VR_ARCH_TYPE], VR_ARCH_PM)

    def test_unknown_method_passes_through(self):
        self.assertNotIn(MDX_ARCH_TYPE, _METHOD_SETTING_ALIASES)


if __name__ == "__main__":
    unittest.main()
