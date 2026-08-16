from __future__ import annotations

import os
import shutil
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock

from cli.execution import _promote, preflight_collisions
from core.export_naming import OutputNamingContext, format_stem_basename
from core.job_plan import PlannedInput, PlannedOutput


def _planned(path: str, output: str, track_base: str, stems: tuple[str, ...] = ("Vocals", "Instrumental")):
    naming = OutputNamingContext(
        input_path=path, track="song", track_base=track_base,
        export_directory=output, extension="wav",
    )
    outputs = tuple(
        PlannedOutput(os.path.join(output, f"{format_stem_basename(track_base, stem)}.wav"), stem)
        for stem in stems
    )
    return PlannedInput(path, naming, outputs)


class PromotionTests(unittest.TestCase):
    def test_add_model_name_does_not_double_suffix(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            stage = os.path.join(root, "stage")
            output = os.path.join(root, "out")
            os.makedirs(stage)
            planned = "song Model"
            for stem in ("Vocals", "Instrumental"):
                name = f"{format_stem_basename(planned, stem)}.wav"
                open(os.path.join(stage, name), "wb").write(b"x")
            promoted = _promote(
                stage, output, "fail",
                destinations=[
                    os.path.join(output, f"{format_stem_basename(planned, stem)}.wav")
                    for stem in ("Vocals", "Instrumental")
                ],
            )
            self.assertTrue(os.path.isfile(os.path.join(output, "song Model (Vocals).wav")))
            self.assertFalse(os.path.isfile(os.path.join(output, "song Model Model (Vocals).wav")))
            self.assertEqual(len(promoted), 2)

    def test_rename_uses_one_suffix_for_the_unit(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            stage = os.path.join(root, "stage")
            output = os.path.join(root, "out")
            os.makedirs(stage)
            os.makedirs(output)
            open(os.path.join(output, "song (Vocals).wav"), "wb").write(b"old")
            for stem in ("Vocals", "Instrumental"):
                open(os.path.join(stage, f"song ({stem}).wav"), "wb").write(b"new")
            promoted = _promote(
                stage, output, "rename",
                destinations=[
                    os.path.join(output, f"song ({stem}).wav")
                    for stem in ("Vocals", "Instrumental")
                ],
            )
            names = sorted(os.path.basename(path) for path in promoted)
            self.assertEqual(names, ["song_2 (Instrumental).wav", "song_2 (Vocals).wav"])

    def test_preflight_ignores_unrelated_prefix(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            output = os.path.join(root, "out")
            os.makedirs(output)
            open(os.path.join(output, "song_live (Vocals).wav"), "wb").write(b"x")
            job = SimpleNamespace(
                inputs=[os.path.join(root, "song.wav")],
                output=output,
                resolved=SimpleNamespace(inputs=(
                    _planned(os.path.join(root, "song.wav"), output, "song"),
                )),
            )
            collided = preflight_collisions(job, "fail")  # type: ignore[arg-type]
            self.assertEqual(collided, set())

    def test_overwrite_restores_backup_when_second_move_fails(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            stage = os.path.join(root, "stage")
            output = os.path.join(root, "out")
            os.makedirs(stage)
            os.makedirs(output)
            # Seed collision on the first sorted name so the successful first
            # replace must be rolled back from a real backup, not only moved.
            open(os.path.join(output, "song (Instrumental).wav"), "wb").write(b"old-i")
            open(os.path.join(output, "song (Vocals).wav"), "wb").write(b"old-v")
            open(os.path.join(stage, "song (Vocals).wav"), "wb").write(b"new-v")
            open(os.path.join(stage, "song (Instrumental).wav"), "wb").write(b"new-i")
            destinations = [
                os.path.join(output, "song (Vocals).wav"),
                os.path.join(output, "song (Instrumental).wav"),
            ]
            real_replace = os.replace
            calls = {"n": 0}

            def flaky_replace(src: str, dst: str, *args: object, **kwargs: object) -> None:
                calls["n"] += 1
                if calls["n"] == 2:
                    raise OSError("simulated promote failure")
                real_replace(src, dst, *args, **kwargs)

            with mock.patch("cli.execution.os.replace", flaky_replace):
                with self.assertRaises(OSError):
                    _promote(stage, output, "overwrite", destinations=destinations)

            with open(os.path.join(output, "song (Instrumental).wav"), "rb") as fh:
                self.assertEqual(fh.read(), b"old-i")
            with open(os.path.join(output, "song (Vocals).wav"), "rb") as fh:
                self.assertEqual(fh.read(), b"old-v")
            self.assertTrue(os.path.isfile(os.path.join(stage, "song (Vocals).wav")))
            self.assertTrue(os.path.isfile(os.path.join(stage, "song (Instrumental).wav")))

    def test_overwrite_cleans_partial_backups_when_copy_fails(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            stage = os.path.join(root, "stage")
            output = os.path.join(root, "out")
            os.makedirs(stage)
            os.makedirs(output)
            open(os.path.join(output, "song (Instrumental).wav"), "wb").write(b"old-i")
            open(os.path.join(output, "song (Vocals).wav"), "wb").write(b"old-v")
            open(os.path.join(stage, "song (Vocals).wav"), "wb").write(b"new-v")
            open(os.path.join(stage, "song (Instrumental).wav"), "wb").write(b"new-i")
            destinations = [
                os.path.join(output, "song (Vocals).wav"),
                os.path.join(output, "song (Instrumental).wav"),
            ]
            real_copy2 = shutil.copy2
            calls = {"n": 0}

            def flaky_copy2(src: str, dst: str, *args: object, **kwargs: object) -> object:
                calls["n"] += 1
                if calls["n"] == 2:
                    raise OSError("simulated backup failure")
                return real_copy2(src, dst, *args, **kwargs)

            with mock.patch("cli.execution.shutil.copy2", flaky_copy2):
                with self.assertRaises(OSError):
                    _promote(stage, output, "overwrite", destinations=destinations)

            leftover = [
                name for name in os.listdir(output)
                if "uvr-overwrite.bak" in name
            ]
            self.assertEqual(leftover, [])
            with open(os.path.join(output, "song (Instrumental).wav"), "rb") as fh:
                self.assertEqual(fh.read(), b"old-i")
            with open(os.path.join(output, "song (Vocals).wav"), "rb") as fh:
                self.assertEqual(fh.read(), b"old-v")

    def test_overwrite_removes_backups_after_success(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            stage = os.path.join(root, "stage")
            output = os.path.join(root, "out")
            os.makedirs(stage)
            os.makedirs(output)
            open(os.path.join(output, "song (Vocals).wav"), "wb").write(b"old-v")
            open(os.path.join(output, "song (Instrumental).wav"), "wb").write(b"old-i")
            open(os.path.join(stage, "song (Vocals).wav"), "wb").write(b"new-v")
            open(os.path.join(stage, "song (Instrumental).wav"), "wb").write(b"new-i")
            destinations = [
                os.path.join(output, "song (Vocals).wav"),
                os.path.join(output, "song (Instrumental).wav"),
            ]
            promoted = _promote(stage, output, "overwrite", destinations=destinations)
            self.assertEqual(len(promoted), 2)
            with open(os.path.join(output, "song (Vocals).wav"), "rb") as fh:
                self.assertEqual(fh.read(), b"new-v")
            with open(os.path.join(output, "song (Instrumental).wav"), "rb") as fh:
                self.assertEqual(fh.read(), b"new-i")
            leftover = [
                name for name in os.listdir(output)
                if "uvr-overwrite.bak" in name
            ]
            self.assertEqual(leftover, [])

    def test_rename_retries_after_lock_recheck(self) -> None:
        # destinations collide on song (Vocals).wav; a race makes song_2 busy
        # after the first free-index check so promotion must land on song_3.
        with tempfile.TemporaryDirectory() as root:
            stage = os.path.join(root, "stage")
            output = os.path.join(root, "out")
            os.makedirs(stage)
            os.makedirs(output)
            open(os.path.join(output, "song (Vocals).wav"), "wb").write(b"old")
            open(os.path.join(stage, "song (Vocals).wav"), "wb").write(b"new")
            destinations = [os.path.join(output, "song (Vocals).wav")]
            song_2 = os.path.join(output, "song_2 (Vocals).wav")
            real_exists = os.path.exists
            song_2_checks = {"n": 0}

            def exists(path: str) -> bool:
                if os.path.abspath(path) == os.path.abspath(song_2):
                    song_2_checks["n"] += 1
                    # First rename candidate looks free, then busy after recheck.
                    return song_2_checks["n"] > 1
                return real_exists(path)

            with mock.patch("cli.execution.os.path.exists", exists):
                promoted = _promote(
                    stage, output, "rename", destinations=destinations,
                )

            self.assertEqual(
                [os.path.basename(path) for path in promoted],
                ["song_3 (Vocals).wav"],
            )
            self.assertTrue(os.path.isfile(os.path.join(output, "song_3 (Vocals).wav")))
            self.assertFalse(
                os.path.isfile(os.path.join(output, "song_2 (Vocals)_2.wav"))
            )

    def test_rename_mid_move_extra_stem_does_not_hang(self) -> None:
        # destinations only list Vocals; stage also has Bass. Unit index 2 is free
        # for Vocals but song_2 (Bass).wav already exists — promote must not spin.
        with tempfile.TemporaryDirectory() as root:
            stage = os.path.join(root, "stage")
            output = os.path.join(root, "out")
            os.makedirs(stage)
            os.makedirs(output)
            open(os.path.join(output, "song (Vocals).wav"), "wb").write(b"old")
            open(os.path.join(output, "song_2 (Bass).wav"), "wb").write(b"busy")
            open(os.path.join(stage, "song (Vocals).wav"), "wb").write(b"new-v")
            open(os.path.join(stage, "song (Bass).wav"), "wb").write(b"new-b")
            destinations = [os.path.join(output, "song (Vocals).wav")]

            promoted = _promote(
                stage, output, "rename", destinations=destinations,
            )

            names = sorted(os.path.basename(path) for path in promoted)
            self.assertEqual(names, ["song_3 (Bass).wav", "song_3 (Vocals).wav"])
            self.assertTrue(os.path.isfile(os.path.join(output, "song_2 (Bass).wav")))
            with open(os.path.join(output, "song_2 (Bass).wav"), "rb") as fh:
                self.assertEqual(fh.read(), b"busy")

    def test_rename_noop_extra_name_does_not_hang(self) -> None:
        # Remappable Vocals collide so unit index advances, but sidecar.txt is a
        # non-matching name that _with_unit_suffix cannot change and already exists.
        with tempfile.TemporaryDirectory() as root:
            stage = os.path.join(root, "stage")
            output = os.path.join(root, "out")
            os.makedirs(stage)
            os.makedirs(output)
            open(os.path.join(output, "song (Vocals).wav"), "wb").write(b"old")
            open(os.path.join(output, "sidecar.txt"), "wb").write(b"busy")
            open(os.path.join(stage, "song (Vocals).wav"), "wb").write(b"new-v")
            open(os.path.join(stage, "sidecar.txt"), "wb").write(b"new-s")
            destinations = [os.path.join(output, "song (Vocals).wav")]

            promoted = _promote(
                stage, output, "rename", destinations=destinations,
            )

            names = sorted(os.path.basename(path) for path in promoted)
            self.assertEqual(names, ["sidecar_2.txt", "song_2 (Vocals).wav"])
            with open(os.path.join(output, "sidecar.txt"), "rb") as fh:
                self.assertEqual(fh.read(), b"busy")
            with open(os.path.join(output, "sidecar_2.txt"), "rb") as fh:
                self.assertEqual(fh.read(), b"new-s")


if __name__ == "__main__":
    unittest.main()
