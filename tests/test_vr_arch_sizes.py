"""The VR architecture-size table must have exactly one definition."""

import os
import unittest


class VrArchSizeConstantTests(unittest.TestCase):
    def test_the_table_is_the_known_nine_sizes(self) -> None:
        from ml.vr_network.nets import VR_ARCH_SIZES

        self.assertEqual(
            list(VR_ARCH_SIZES),
            [31191, 33966, 56817, 123821, 123812, 129605, 218409, 537238, 537227],
        )

    def test_the_5_1_subset_is_part_of_the_table(self) -> None:
        from ml.vr_network.nets import VR_5_1_ARCH_SIZES, VR_ARCH_SIZES

        self.assertEqual(VR_5_1_ARCH_SIZES, {56817, 218409})
        self.assertTrue(VR_5_1_ARCH_SIZES.issubset(set(VR_ARCH_SIZES)))

    def test_capacity_partitions_cover_every_non_5_1_size(self) -> None:
        """determine_model_capacity must have a branch for each size routed to it.

        A size in the table that no capacity list claims would fall through and
        return an unconfigured network.
        """
        from ml.vr_network import nets

        covered = set(nets._SP_MODEL_ARCH) | set(nets._HP_MODEL_ARCH) | set(nets._HP2_MODEL_ARCH)
        self.assertEqual(covered, set(nets.VR_ARCH_SIZES) - nets.VR_5_1_ARCH_SIZES)

    def test_the_engine_uses_the_shared_table(self) -> None:
        import engines.vr as vr
        from ml.vr_network.nets import VR_5_1_ARCH_SIZES, VR_ARCH_SIZES

        self.assertIs(vr.VR_ARCH_SIZES, VR_ARCH_SIZES)
        self.assertIs(vr.VR_5_1_ARCH_SIZES, VR_5_1_ARCH_SIZES)

    def test_the_probe_uses_the_shared_table(self) -> None:
        import importlib.util
        import os
        import sys

        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        spec = importlib.util.spec_from_file_location(
            "model_probe_const", os.path.join(root, "scripts", "model_probe.py")
        )
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules["model_probe_const"] = module
        spec.loader.exec_module(module)

        from ml.vr_network.nets import VR_5_1_ARCH_SIZES, VR_ARCH_SIZES

        sizes, vr_5_1 = module._vr_arch_tables()
        self.assertIs(sizes, VR_ARCH_SIZES)
        self.assertIs(vr_5_1, VR_5_1_ARCH_SIZES)

    def test_the_probe_does_not_restate_the_table(self) -> None:
        """A local copy is exactly what drifts away from the engine."""
        import os

        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(root, "scripts", "model_probe.py"), encoding="utf-8") as f:
            source = f.read()
        self.assertNotIn("31191", source)

    def test_the_probe_stays_importable_without_torch(self) -> None:
        """model_probe imports heavy dependencies lazily; nets.py pulls in torch."""
        import subprocess
        import sys

        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                "import sys; sys.path.insert(0, '.');"
                " import scripts.model_probe;"
                " print('torch' in sys.modules)",
            ],
            capture_output=True,
            text=True,
            cwd=root,
        )
        self.assertEqual(result.stdout.strip(), "False", result.stderr)


if __name__ == "__main__":
    unittest.main()
