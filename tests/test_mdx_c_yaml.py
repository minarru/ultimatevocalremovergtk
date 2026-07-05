import os
import tempfile
import unittest

from core.model_data import load_mdx_c_config


class LoadMdxCConfigTests(unittest.TestCase):
    def test_python_tuple_tag(self):
        payload = (
            "model:\n"
            "  multi_stft_resolutions_window_sizes: !!python/tuple\n"
            "  - 4096\n"
            "  - 256\n"
        )
        with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False) as handle:
            handle.write(payload)
            path = handle.name
        try:
            data = load_mdx_c_config(path)
            self.assertEqual(data["model"]["multi_stft_resolutions_window_sizes"], (4096, 256))
        finally:
            os.remove(path)


if __name__ == "__main__":
    unittest.main()
