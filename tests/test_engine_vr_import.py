"""VR engine import and 5.1 model-network wiring."""

import unittest


class VRNetsImportTests(unittest.TestCase):
    def test_vr_module_imports_nets_new(self) -> None:
        import engines.vr as vr_mod
        from ml.vr_network import nets_new as expected

        self.assertIs(vr_mod.nets_new, expected)
        self.assertTrue(hasattr(vr_mod.nets_new, "CascadedNet"))


if __name__ == "__main__":
    unittest.main()
