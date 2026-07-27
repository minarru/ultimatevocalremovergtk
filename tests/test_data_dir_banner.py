"""Banner shown when the application data folder is not writable."""

from __future__ import annotations

import os
import stat
import tempfile
import unittest

from ui.window import data_dir_banner_state


class DataDirBannerStateTests(unittest.TestCase):
    def test_writable_folder_hides_the_banner(self):
        with tempfile.TemporaryDirectory() as tmp:
            revealed, _title = data_dir_banner_state(tmp)
            self.assertFalse(revealed)

    @unittest.skipIf(
        os.geteuid() == 0, "os.access(W_OK) ignores file mode for root"
    )
    def test_read_only_folder_reveals_the_banner(self):
        with tempfile.TemporaryDirectory() as tmp:
            os.chmod(tmp, stat.S_IRUSR | stat.S_IXUSR)
            try:
                revealed, _title = data_dir_banner_state(tmp)
            finally:
                os.chmod(tmp, stat.S_IRWXU)
            self.assertTrue(revealed)

    @unittest.skipIf(
        os.geteuid() == 0, "os.access(W_OK) ignores file mode for root"
    )
    def test_title_names_the_offending_folder(self):
        with tempfile.TemporaryDirectory() as tmp:
            os.chmod(tmp, stat.S_IRUSR | stat.S_IXUSR)
            try:
                _revealed, title = data_dir_banner_state(tmp)
            finally:
                os.chmod(tmp, stat.S_IRWXU)
            self.assertIn(tmp, title)

    @unittest.skipIf(
        os.geteuid() == 0, "os.access(W_OK) ignores file mode for root"
    )
    def test_title_does_not_promise_a_chooser(self):
        # There is no in-app data-folder picker, so the copy must not tell the
        # user to "choose a writable location".
        with tempfile.TemporaryDirectory() as tmp:
            os.chmod(tmp, stat.S_IRUSR | stat.S_IXUSR)
            try:
                _revealed, title = data_dir_banner_state(tmp)
            finally:
                os.chmod(tmp, stat.S_IRWXU)
            self.assertNotIn("Choose", title)


if __name__ == "__main__":
    unittest.main()
