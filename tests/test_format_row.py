"""Combined output-format + quality row."""

from __future__ import annotations

import os
import typing
import unittest

from bundled.constants import FLAC, MP3, OPUS, WAV
from ui.widgets.format_row import quality_spec


class QualitySpecTests(unittest.TestCase):
    def test_wav_maps_to_wav_type(self):
        spec = quality_spec(WAV)
        self.assertEqual(spec.setting_key, "wav_type_set")
        self.assertEqual(spec.label, "WAV type")
        self.assertIn("PCM_16", spec.values)
        self.assertEqual(spec.default, "PCM_16")

    def test_mp3_maps_to_bitrate(self):
        spec = quality_spec(MP3)
        self.assertEqual(spec.setting_key, "mp3_bit_set")
        self.assertEqual(spec.label, "MP3 bitrate")
        self.assertIn("320k", spec.values)
        self.assertEqual(spec.default, "320k")

    def test_flac_maps_to_bit_depth(self):
        spec = quality_spec(FLAC)
        self.assertEqual(spec.setting_key, "flac_bit_set")
        self.assertEqual(spec.label, "FLAC bit depth")
        self.assertIn("24-bit", spec.values)
        self.assertEqual(spec.default, "16-bit")

    def test_opus_maps_to_target_bitrate(self):
        spec = quality_spec(OPUS)
        self.assertEqual(spec.setting_key, "opus_bit_set")
        self.assertEqual(spec.label, "Opus bitrate")
        self.assertEqual(spec.default, "192k")
        self.assertEqual(spec.values, ("64k", "96k", "128k", "160k", "192k", "256k"))

    def test_unknown_format_falls_back_to_wav(self):
        self.assertEqual(quality_spec("OGG").setting_key, "wav_type_set")

    def test_every_default_is_a_valid_choice(self):
        for fmt in (WAV, MP3, FLAC, OPUS):
            spec = quality_spec(fmt)
            self.assertIn(spec.default, spec.values)


@unittest.skipUnless(
    os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"),
    "GTK widget construction needs a display",
)
class OutputFormatRowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        import gi

        gi.require_version("Gtk", "4.0")
        gi.require_version("Adw", "1")
        from gi.repository import Adw

        cls._app = Adw.Application(application_id="org.uvr.test.format-row")
        cls._app.register()

    def _settings(self, **overrides: typing.Any):
        from core.settings import Settings

        settings = Settings.defaults()
        for key, value in overrides.items():
            settings.set(key, value)
        return settings

    def test_format_and_quality_emit_distinct_events(self):
        from ui.widgets.format_row import OutputFormatRow
        events = []
        row = OutputFormatRow(lambda *event: events.append(event))
        row.apply_from_settings(self._settings(save_format=WAV))
        self.assertEqual(events, [])
        row.set_save_format(MP3)
        row._quality_drop.set_selected(0)
        self.assertEqual(len(events), 2)
        self.assertNotEqual(events[0], events[1])

    def _session_row(self, settings: typing.Any):
        from ui.shared_settings import SharedSettingsSession, shared_settings_bindings
        from ui.widgets.format_row import OutputFormatRow
        row = OutputFormatRow(lambda event: session.format_changed(event))
        session = SharedSettingsSession(settings, shared_settings_bindings(format_row=row), can_commit=lambda: True)
        session.refresh(lambda: row.apply_from_settings(settings))
        return row, session

    def test_quality_edit_does_not_revert_a_newer_format(self):
        from core.types import SaveFormat
        from core.types.settings_enums import WavType
        settings = self._settings(save_format=WAV, wav_type_set="PCM_16")
        row, session = self._session_row(settings)
        other, _ = self._session_row(settings)
        other.set_save_format(MP3)
        row._select_quality_value("PCM_24", quality_spec(WAV))
        session.commit()
        self.assertEqual(settings.process.save_format, SaveFormat.MP3)
        self.assertEqual(settings.process.wav_type, WavType.PCM_24)

    def test_format_adopts_restored_quality_without_claiming_an_edit(self):
        from core.types.settings_enums import WavType
        settings = self._settings(save_format=WAV, wav_type_set="PCM_24")
        row, session = self._session_row(settings)
        row.set_save_format(MP3)
        settings.process.wav_type = WavType.FLOAT_32
        row.set_save_format(WAV)
        self.assertEqual(row.quality_value, "32-bit Float")
        settings.process.wav_type = WavType.PCM_16
        session.commit()
        self.assertEqual(settings.process.wav_type, WavType.PCM_16)
        row._select_quality_value("PCM_24", quality_spec(WAV))
        self.assertEqual(settings.process.wav_type, WavType.PCM_24)

    def test_session_round_trips_all_active_quality_enum_types(self):
        from core.types import SaveFormat
        from core.types.settings_enums import FlacBitDepth, Mp3Bitrate, OpusBitrate, WavType
        settings = self._settings(save_format=WAV)
        row, session = self._session_row(settings)
        for fmt, value in ((WAV, "PCM_24"), (MP3, "128k"), (FLAC, "24-bit"), (OPUS, "256k")):
            row.set_save_format(fmt)
            row._select_quality_value(value, quality_spec(fmt))
            session.commit()
            self.assertIsInstance(settings.process.save_format, SaveFormat)
        self.assertIs(settings.process.wav_type, WavType.PCM_24)
        self.assertIs(settings.process.mp3_bitrate, Mp3Bitrate.K128)
        self.assertIs(settings.process.flac_bit_depth, FlacBitDepth.BIT_24)
        self.assertIs(settings.process.opus_bitrate, OpusBitrate.K256)
        row.set_save_format(WAV)
        self.assertEqual(row.quality_value, "PCM_24")

    def test_applies_stored_format_and_quality(self):
        from ui.widgets.format_row import OutputFormatRow

        row = OutputFormatRow(lambda _event: None)
        row.apply_from_settings(self._settings(save_format=MP3, mp3_bit_set="128k"))
        self.assertEqual(row.save_format, MP3)
        self.assertEqual(row.quality_value, "128k")

    def test_applies_stored_opus_bitrate(self):
        from ui.widgets.format_row import OutputFormatRow

        row = OutputFormatRow(lambda _event: None)
        row.apply_from_settings(self._settings(save_format=OPUS, opus_bit_set="128k"))
        self.assertEqual(row.save_format, OPUS)
        self.assertEqual(row.quality_value, "128k")

    def test_switching_format_swaps_the_quality_model(self):
        from ui.widgets.format_row import OutputFormatRow

        row = OutputFormatRow(lambda _event: None)
        row.apply_from_settings(self._settings(save_format=WAV))
        row.set_save_format(FLAC)
        self.assertEqual(row.quality_key, "flac_bit_set")
        self.assertIn(row.quality_value, quality_spec(FLAC).values)

    def test_persist_writes_both_keys(self):
        from ui.widgets.format_row import OutputFormatRow

        settings = self._settings(save_format=WAV)
        row = OutputFormatRow(lambda _event: None)
        row.apply_from_settings(settings)
        row.set_save_format(MP3)
        row.persist_to_settings(settings)
        self.assertEqual(settings.get("save_format"), MP3)
        self.assertIn(settings.get("mp3_bit_set"), quality_spec(MP3).values)

    def test_switching_away_and_back_keeps_the_other_format_setting(self):
        from ui.widgets.format_row import OutputFormatRow

        settings = self._settings(save_format=WAV, wav_type_set="PCM_24")
        row = OutputFormatRow(lambda _event: None)
        row.apply_from_settings(settings)
        row.set_save_format(MP3)
        row.persist_to_settings(settings)
        self.assertEqual(settings.get("wav_type_set"), "PCM_24")

    def test_switching_away_and_back_restores_the_dropdown_and_completes_the_round_trip(self):
        """The full WAV -> MP3 -> WAV round trip promised by the module docstring.

        Regression test: an interactive format switch used to reset the
        quality dropdown to its spec *default* rather than restoring the
        format's own stored value, so switching back to WAV after a detour
        through MP3 silently overwrote a non-default ``wav_type_set`` (e.g.
        "PCM_24") with "PCM_16" the moment the round trip was persisted.
        """
        from ui.widgets.format_row import OutputFormatRow

        settings = self._settings(save_format=WAV, wav_type_set="PCM_24")
        row = OutputFormatRow(lambda _event: None)
        row.apply_from_settings(settings)

        row.set_save_format(MP3)
        row.persist_to_settings(settings)
        self.assertEqual(settings.get("wav_type_set"), "PCM_24")
        self.assertEqual(settings.get("mp3_bit_set"), "320k")

        row.set_save_format(WAV)
        self.assertEqual(row.quality_value, "PCM_24", "dropdown must show the restored value")
        row.persist_to_settings(settings)

        self.assertEqual(settings.get("wav_type_set"), "PCM_24")

    def test_on_changed_fires_for_both_dropdowns(self):
        from ui.widgets.format_row import OutputFormatRow

        calls = []
        row = OutputFormatRow(lambda _event: calls.append(1))
        row.apply_from_settings(self._settings(save_format=WAV))
        before = len(calls)
        row.set_save_format(FLAC)
        self.assertGreater(len(calls), before)

    def test_selecting_a_new_quality_value_fires_on_changed_and_persists(self):
        """Covers ``_on_quality_selected`` -> ``on_changed`` (Task 7 review gap).

        Driving the quality dropdown directly (post ``apply_from_settings``, so
        ``_syncing`` is false) must fire ``on_changed`` the same way switching
        format does; otherwise a page's ``persist_to_settings`` call never runs
        and a new MP3 bitrate silently fails to save.
        """
        from gi.repository import Gtk

        from ui.widgets.format_row import OutputFormatRow

        calls = []
        row = OutputFormatRow(lambda _event: calls.append(1))
        settings = self._settings(save_format=MP3, mp3_bit_set="320k")
        row.apply_from_settings(settings)
        self.assertEqual(calls, [])

        model = row._quality_drop.get_model()
        assert isinstance(model, Gtk.StringList)
        current_index = row._quality_drop.get_selected()
        new_index = next(
            i
            for i in range(model.get_n_items())
            if model.get_string(i) != model.get_string(current_index)
        )
        new_value = model.get_string(new_index)

        row._quality_drop.set_selected(new_index)

        self.assertEqual(len(calls), 1, "on_changed should fire once for the new selection")

        row.persist_to_settings(settings)
        self.assertEqual(settings.get("mp3_bit_set"), new_value)

    def test_each_dropdown_has_a_tooltip(self):
        from gi.repository import Gtk

        from ui.widgets.format_row import OutputFormatRow

        row = OutputFormatRow(lambda _event: None)
        row.apply_from_settings(self._settings(save_format=MP3))
        # The row title only names the first control, so the quality dropdown
        # must carry its own tooltip. GTK4/PyGObject exposes no read-back for
        # accessible properties (Gtk.Accessible has no getter), so this only
        # checks the tooltip text, not the accessible label itself.
        for drop in (row._format_drop, row._quality_drop):
            self.assertIsInstance(drop, Gtk.DropDown)
            self.assertTrue(drop.get_tooltip_text())


if __name__ == "__main__":
    unittest.main()
