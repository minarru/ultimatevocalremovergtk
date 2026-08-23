"""Manual-ensemble export naming with typed ``choose_algorithm``.

``choose_algorithm`` is a ``str, Enum`` since schema v3, so ``str(value)``
yields ``ManualEnsembleOption.MAX_SPEC`` rather than the ``Max Spec`` label.
The algorithm lands in the output filename, so it must resolve through
``.value``.
"""

import os
import tempfile
import unittest
from unittest import mock

from bundled.constants import APOLLO_RESTORE
from core.audio_tools import AudioToolRunner, AudioTools
from core.job_callbacks import JobCallbacks
from core.settings import Settings
from core.settings.coerce import coerce_field
from core.types.settings_enums import ManualEnsembleOption


class ManualEnsembleNamingTests(unittest.TestCase):
    def test_apollo_runner_requires_resolved_backend_before_start(self) -> None:
        runner = AudioToolRunner(Settings.defaults())

        with self.assertRaisesRegex(ValueError, "resolved Apollo backend"):
            runner.start(APOLLO_RESTORE, [], [], JobCallbacks())

    def test_audio_tools_never_uses_canonical_apollo_setting_as_filename(self) -> None:
        settings = Settings.defaults()
        settings.audio_tools.apollo_model = "apollo:restorer"

        tool = AudioTools(settings)

        self.assertIsNone(tool.apollo_model)
        self.assertEqual(tool.apollo_model_location, "")
        with self.assertRaisesRegex(ValueError, "resolved Apollo backend"):
            tool.apollo_process("in.wav", "in", {}, {}, mock.Mock())
    def _run_manual_ensemble(self, algorithm: ManualEnsembleOption) -> str:
        with tempfile.TemporaryDirectory() as export_dir:
            settings = Settings.defaults()
            settings.process.export_path = export_dir
            settings.audio_tools.choose_algorithm = algorithm
            tool = AudioTools(settings)
            with (
                mock.patch("ml.spec_utils.ensemble_inputs") as ensemble_inputs,
                mock.patch("core.audio_tools.save_format"),
            ):
                tool.ensemble_manual(["a.wav", "b.wav"], "song")
            save_path = ensemble_inputs.call_args.args[4]
        return os.path.basename(save_path)

    def test_enum_algorithm_uses_display_label(self) -> None:
        self.assertEqual(
            self._run_manual_ensemble(ManualEnsembleOption.MAX_SPEC),
            "song (Max Spec).wav",
        )

    def test_slash_in_algorithm_is_sanitized(self) -> None:
        self.assertEqual(
            self._run_manual_ensemble(ManualEnsembleOption.MAX_MAG_AVG_PHASE),
            "song (Max Mag Avg Phase).wav",
        )

    def test_algorithm_set_through_coercion(self) -> None:
        """The UI writes the combo label; coercion must land it on the enum."""
        self.assertEqual(
            self._run_manual_ensemble(
                coerce_field("audio_tools", "choose_algorithm", "Median Spec")
            ),
            "song (Median Spec).wav",
        )


if __name__ == "__main__":
    unittest.main()
