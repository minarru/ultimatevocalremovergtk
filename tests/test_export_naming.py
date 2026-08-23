import os
import typing
import unittest

from core.export_naming import (
    build_output_naming_context,
    format_stem_basename,
    format_track_base,
    preview_output_name,
    sanitize_filename_component,
)
from core.settings import Settings


class SanitizeTests(unittest.TestCase):
    def test_removes_path_separators_keeps_spaces(self):
        self.assertEqual(
            sanitize_filename_component("a/b\\c Instrumental (With Lead Vocals)"),
            "a b c Instrumental (With Lead Vocals)",
        )

    def test_collapses_whitespace_and_strips_trailing_dots(self):
        self.assertEqual(sanitize_filename_component("  song   name. "), "song name")


class FormatTrackBaseTests(unittest.TestCase):
    def test_single_file_no_index(self):
        self.assertEqual(format_track_base(track="song", file_total=1), "song")

    def test_multi_file_hyphen_index(self):
        self.assertEqual(
            format_track_base(track="song", file_index=1, file_total=2),
            "1-song",
        )
        self.assertEqual(
            format_track_base(track="song", file_index=2, file_total=2),
            "2-song",
        )

    def test_model_and_timestamp_segments(self):
        self.assertEqual(
            format_track_base(
                track="song",
                model="UVR-MDX-Net",
                timestamp="1710000000",
            ),
            "1710000000 song UVR-MDX-Net",
        )

    def test_ensemble_segment_without_model(self):
        base = format_track_base(
            track="song",
            file_index=1,
            file_total=2,
            ensemble="Ensembled",
        )
        self.assertEqual(base, "1-song Ensembled")
        self.assertNotIn("UVR", base)


class FormatStemBasenameTests(unittest.TestCase):
    def test_space_before_stem_parens(self):
        self.assertEqual(format_stem_basename("song", "Vocals"), "song (Vocals)")

    def test_multi_file_with_stem(self):
        base = format_track_base(track="song", file_index=1, file_total=2)
        self.assertEqual(format_stem_basename(base, "Vocals"), "1-song (Vocals)")
        base2 = format_track_base(track="song", file_index=2, file_total=2)
        self.assertEqual(format_stem_basename(base2, "Vocals"), "2-song (Vocals)")

    def test_model_name_with_stem(self):
        base = format_track_base(track="song", model="UVR-MDX-Net")
        self.assertEqual(
            format_stem_basename(base, "Instrumental"),
            "song UVR-MDX-Net (Instrumental)",
        )


class EnsembleFinalBaseTests(unittest.TestCase):
    def test_final_base_does_not_strip_model_via_replace(self):
        member = format_track_base(track="song", model="UVR-MDX-Net", file_index=1, file_total=2)
        final = format_track_base(track="song", file_index=1, file_total=2, ensemble="Ensembled")
        self.assertEqual(member, "1-song UVR-MDX-Net")
        self.assertEqual(final, "1-song Ensembled")
        # Rebuild independently — never derive final from member via str.replace.
        self.assertNotEqual(final, member.replace(" UVR-MDX-Net", ""))


class PreviewOutputNameTests(unittest.TestCase):
    def test_defaults(self):
        settings = Settings.from_flat(
            {
                "is_testing_audio": False,
                "is_add_model_name": False,
                "save_format": "WAV",
            }
        )
        self.assertEqual(
            preview_output_name(settings),
            "song (Vocals).wav",
        )

    def test_model_and_timestamp(self):
        settings = Settings.from_flat(
            {
                "is_testing_audio": True,
                "is_add_model_name": True,
                "save_format": "FLAC",
            }
        )
        name = preview_output_name(
            settings
        )
        self.assertEqual(name, "1710000000 song UVR-MDX-Net (Vocals).flac")

    def test_multi_file_preview(self):
        self.assertEqual(
            preview_output_name(
                Settings.from_flat({"save_format": "WAV"}), multi_file=True
            ),
            "1-song (Vocals).wav",
        )


if __name__ == "__main__":
    unittest.main()


class EnrichedModelLabelNamingTests(unittest.TestCase):
    """Filenames and model folders use `ModelRecord.display`, sanitized.

    Sanitization touches filesystem components only. It must never reach the
    canonical id, backend name or artifacts, which stay exactly as resolved.
    """

    _FRIENDLY = "MelBand Roformer — Karaoke · becruily"

    def _naming(self, **overrides: typing.Any):
        from core.export_naming import build_output_naming_context

        settings = Settings.defaults()
        settings.process.add_model_name = True
        for key, value in overrides.pop("settings", {}).items():
            setattr(settings.process, key, value)
        return build_output_naming_context(
            settings,
            "/music/song.wav",
            export_path="/out",
            model_label=overrides.pop("model_label", self._FRIENDLY),
            **overrides,
        )

    def test_add_model_name_uses_the_friendly_display(self) -> None:
        naming = self._naming()

        self.assertEqual(naming.track_base, f"song {self._FRIENDLY}")
        self.assertEqual(
            format_stem_basename(naming.track_base, "Vocals"),
            f"song {self._FRIENDLY} (Vocals)",
        )

    def test_create_model_folder_uses_the_same_sanitized_display(self) -> None:
        naming = self._naming(settings={"create_model_folder": True})

        self.assertEqual(
            naming.export_directory,
            os.path.join("/out", sanitize_filename_component(self._FRIENDLY), "song"),
        )

    def test_unsafe_label_is_sanitized_only_in_path_components(self) -> None:
        unsafe = "Evil/Model\\Name: v2"
        naming = self._naming(
            model_label=unsafe, settings={"create_model_folder": True}
        )

        self.assertNotIn("/", os.path.basename(os.path.dirname(naming.export_directory)))
        self.assertEqual(
            os.path.dirname(naming.export_directory),
            os.path.join("/out", "Evil Model Name v2"),
        )
        # The label itself is carried verbatim; only the path component changed.
        self.assertEqual(naming.model_label, unsafe)

    def test_unknown_custom_model_appends_its_raw_basename(self) -> None:
        naming = self._naming(model_label="my_private_model")

        self.assertEqual(naming.track_base, "song my_private_model")
