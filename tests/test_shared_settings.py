import os
import tempfile
import unittest

from bundled.constants import FLAC, WAV
from ui.shared_settings import (
    INPUT_FILES_MAX,
    INPUT_FILES_WARN,
    SharedFileOptions,
    apply_shared_file_options,
    export_path_blocked_reason,
    export_path_is_valid,
    input_paths_blocked_reason,
    prune_unreadable_paths,
    read_shared_file_options,
    remove_unreadable_from_paths,
    sanitize_input_paths,
)


class _FakeSettings:
    def __init__(self, data):
        self._data = dict(data)

    def get(self, key, default=None):
        return self._data.get(key, default)

    def set(self, key, value):
        self._data[key] = value


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


class ExportPathValidationTests(unittest.TestCase):
    def test_missing_path(self):
        self.assertEqual(export_path_blocked_reason(""), "Choose an output folder")
        self.assertEqual(export_path_blocked_reason("   "), "Choose an output folder")

    def test_stale_path(self):
        self.assertEqual(
            export_path_blocked_reason("/definitely/not/a/real/folder"),
            "Output folder no longer exists — select a new folder",
        )

    def test_valid_path(self):
        self.assertIsNone(export_path_blocked_reason(os.path.abspath(os.getcwd())))
        self.assertTrue(export_path_is_valid(os.path.abspath(os.getcwd())))


class InputPathValidationTests(unittest.TestCase):
    def test_blocked_when_empty(self):
        self.assertEqual(input_paths_blocked_reason([]), "Select an input audio file")

    def test_blocked_when_all_missing(self):
        self.assertEqual(
            input_paths_blocked_reason(["/missing/a.wav", "/missing/b.wav"]),
            "Select an input audio file",
        )

    def test_ready_when_any_file_exists(self):
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as handle:
            path = handle.name
        try:
            self.assertIsNone(input_paths_blocked_reason(["/missing/a.wav", path]))
        finally:
            os.remove(path)

    def test_unreadable_blocks_start(self):
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as handle:
            path = handle.name
        try:
            self.assertEqual(
                input_paths_blocked_reason([path], unreadable_paths={path}),
                "Remove unreadable inputs",
            )
        finally:
            os.remove(path)

    def test_unreadable_cleared_when_path_removed(self):
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as good:
            good_path = good.name
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as bad:
            bad_path = bad.name
        try:
            unreadable = {bad_path}
            remaining = remove_unreadable_from_paths([good_path, bad_path], unreadable)
            self.assertEqual(remaining, [good_path])
            pruned = prune_unreadable_paths(unreadable, remaining)
            self.assertEqual(pruned, set())
            self.assertIsNone(
                input_paths_blocked_reason(remaining, unreadable_paths=pruned)
            )
        finally:
            os.remove(good_path)
            os.remove(bad_path)

    def test_never_verified_does_not_block(self):
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as handle:
            path = handle.name
        try:
            self.assertIsNone(
                input_paths_blocked_reason([path], unreadable_paths=set())
            )
        finally:
            os.remove(path)

    def test_prune_keeps_only_selected_failures(self):
        self.assertEqual(
            prune_unreadable_paths({"/a.wav", "/b.wav"}, ["/a.wav", "/c.wav"]),
            {"/a.wav"},
        )

    def test_sanitize_drops_missing_and_dedupes(self):
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as first:
            first_path = first.name
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as second:
            second_path = second.name
        try:
            cleaned, result = sanitize_input_paths(
                [first_path, "/missing.wav", first_path, second_path]
            )
            self.assertEqual(cleaned, [first_path, second_path])
            self.assertEqual(result.removed_missing, 1)
            self.assertEqual(result.truncated_count, 0)
            self.assertFalse(result.large_batch)
        finally:
            os.remove(first_path)
            os.remove(second_path)

    def test_sanitize_truncates_to_max(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths = []
            for index in range(INPUT_FILES_MAX + 5):
                path = os.path.join(tmp, f"track_{index:03d}.wav")
                with open(path, "wb"):
                    pass
                paths.append(path)
            cleaned, result = sanitize_input_paths(paths)
            self.assertEqual(len(cleaned), INPUT_FILES_MAX)
            self.assertEqual(result.truncated_count, 5)
            self.assertTrue(result.large_batch)

    def test_sanitize_marks_large_batch_at_warn_threshold(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths = []
            for index in range(INPUT_FILES_WARN):
                path = os.path.join(tmp, f"track_{index:03d}.wav")
                with open(path, "wb"):
                    pass
                paths.append(path)
            cleaned, result = sanitize_input_paths(paths)
            self.assertEqual(len(cleaned), INPUT_FILES_WARN)
            self.assertTrue(result.large_batch)


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
        import ui.shared_settings as shared_settings

        self._original_set_combo = shared_settings.set_combo_value
        shared_settings.set_combo_value = _set_combo_value
        self.addCleanup(setattr, shared_settings, "set_combo_value", self._original_set_combo)

    def test_applies_to_rows_without_notify(self):
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as handle:
            input_path = handle.name
        try:
            settings = _FakeSettings(
                {
                    "input_paths": [input_path],
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

            self.assertEqual(input_row.paths, [input_path])
            self.assertFalse(input_row.notify)
            self.assertEqual(output_row.path, "/out")
            self.assertFalse(output_row.notify)
            self.assertEqual(format_row.selected, FLAC)
            self.assertTrue(gpu_row.active)
            self.assertTrue(sample_row.active)
            self.assertIn("15", sample_row.title or "")
        finally:
            os.remove(input_path)

    def test_apply_prunes_missing_paths_from_settings(self):
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as handle:
            input_path = handle.name
        try:
            settings = _FakeSettings(
                {
                    "input_paths": [input_path, "/missing/file.wav"],
                }
            )
            input_row = _FakeInputRow()
            apply_shared_file_options(settings, input_row=input_row)
            self.assertEqual(input_row.paths, [input_path])
            self.assertEqual(settings.get("input_paths"), [input_path])
        finally:
            os.remove(input_path)


if __name__ == "__main__":
    unittest.main()
