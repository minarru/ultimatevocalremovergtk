import unittest

from data.constants import FLAC, WAV
from uvr_gtk.shared_settings import SharedFileOptions, apply_shared_file_options, read_shared_file_options


class _FakeSettings:
    def __init__(self, data):
        self._data = dict(data)

    def get(self, key, default=None):
        return self._data.get(key, default)


class _FakeInputRow:
    def __init__(self):
        self.paths = None
        self.notify = None

    def set_paths(self, paths, notify=True):
        self.paths = list(paths)
        self.notify = notify


class _FakeOutputRow:
    def __init__(self):
        self.path = None
        self.notify = None

    def set_path(self, path, notify=True):
        self.path = path
        self.notify = notify


class _FakeSwitchRow:
    def __init__(self):
        self.active = None

    def set_active(self, active):
        self.active = active


class _FakeSampleRow:
    def __init__(self):
        self.title = None
        self.active = None

    def set_title(self, title):
        self.title = title

    def set_active(self, active):
        self.active = active


class _FakeFormatRow:
    def __init__(self):
        self.selected = None


def _set_combo_value(row, value):
    row.selected = value


class ReadSharedFileOptionsTests(unittest.TestCase):
    def test_reads_defaults(self):
        settings = _FakeSettings({})
        options = read_shared_file_options(settings)
        self.assertEqual(
            options,
            SharedFileOptions(
                input_paths=[],
                export_path="",
                save_format=WAV,
                is_gpu_conversion=False,
                sample_duration=30,
                model_sample_mode=False,
            ),
        )

    def test_reads_stored_values(self):
        settings = _FakeSettings(
            {
                "input_paths": ["/music/song.wav"],
                "export_path": "/out",
                "save_format": FLAC,
                "is_gpu_conversion": True,
                "model_sample_mode_duration": 45,
                "model_sample_mode": True,
            }
        )
        options = read_shared_file_options(settings)
        self.assertEqual(options.input_paths, ["/music/song.wav"])
        self.assertEqual(options.export_path, "/out")
        self.assertEqual(options.save_format, FLAC)
        self.assertTrue(options.is_gpu_conversion)
        self.assertEqual(options.sample_duration, 45)
        self.assertTrue(options.model_sample_mode)


class ApplySharedFileOptionsTests(unittest.TestCase):
    def setUp(self):
        import uvr_gtk.shared_settings as shared_settings

        self._original_set_combo = shared_settings.set_combo_value
        shared_settings.set_combo_value = _set_combo_value
        self.addCleanup(setattr, shared_settings, "set_combo_value", self._original_set_combo)

    def test_applies_to_rows_without_notify(self):
        settings = _FakeSettings(
            {
                "input_paths": ["/in/a.wav"],
                "export_path": "/out",
                "save_format": FLAC,
                "is_gpu_conversion": True,
                "model_sample_mode_duration": 15,
                "model_sample_mode": True,
            }
        )
        input_row = _FakeInputRow()
        output_row = _FakeOutputRow()
        format_row = _FakeFormatRow()
        gpu_row = _FakeSwitchRow()
        sample_row = _FakeSampleRow()

        apply_shared_file_options(
            settings,
            input_row=input_row,
            output_row=output_row,
            format_row=format_row,
            gpu_row=gpu_row,
            sample_row=sample_row,
        )

        self.assertEqual(input_row.paths, ["/in/a.wav"])
        self.assertFalse(input_row.notify)
        self.assertEqual(output_row.path, "/out")
        self.assertFalse(output_row.notify)
        self.assertEqual(format_row.selected, FLAC)
        self.assertTrue(gpu_row.active)
        self.assertTrue(sample_row.active)
        self.assertIn("15", sample_row.title)


if __name__ == "__main__":
    unittest.main()
