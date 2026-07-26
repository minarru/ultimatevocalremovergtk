"""Pure-logic tests for audio file dialog filter selection."""

from __future__ import annotations

import os
import tempfile
import unittest

from core.audio_formats import AUDIO_EXTENSIONS, expand_audio_paths, is_audio_filename


class AudioFormatsTests(unittest.TestCase):
    def test_common_extensions_present(self):
        for ext in (".wav", ".flac", ".mp3", ".ogg"):
            self.assertIn(ext, AUDIO_EXTENSIONS)

    def test_is_audio_filename(self):
        self.assertTrue(is_audio_filename("song.WAV"))
        self.assertFalse(is_audio_filename("notes.txt"))

    def test_expands_directory_to_audio_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            audio = os.path.join(tmp, "a.wav")
            other = os.path.join(tmp, "readme.txt")
            with open(audio, "wb") as handle:
                handle.write(b"x")
            with open(other, "wb") as handle:
                handle.write(b"y")
            result = expand_audio_paths([tmp])
            self.assertEqual(result, [audio])

    def test_accept_any_keeps_non_audio_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            other = os.path.join(tmp, "readme.txt")
            with open(other, "wb") as handle:
                handle.write(b"y")
            result = expand_audio_paths([other], accept_any=True)
            self.assertEqual(result, [other])


@unittest.skipUnless(
    os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"),
    "GTK FileFilter construction needs a display",
)
class FileDialogFilterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        import gi

        gi.require_version("Gtk", "4.0")

    def test_default_filter_is_audio_when_accept_any_off(self):
        from ui.widgets.file_dialogs import audio_file_filters

        _filters, default = audio_file_filters(accept_any=False)
        self.assertEqual(default.get_name(), "Audio files")

    def test_default_filter_is_all_when_accept_any_on(self):
        from ui.widgets.file_dialogs import audio_file_filters

        _filters, default = audio_file_filters(accept_any=True)
        self.assertEqual(default.get_name(), "All files")


if __name__ == "__main__":
    unittest.main()
