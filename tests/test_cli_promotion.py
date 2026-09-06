from __future__ import annotations

import multiprocessing
import os
import tempfile
import threading
import time
import unittest
from collections.abc import Callable
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest import mock

from cli.execution import (
    PromotionSkipped,
    _promote,
    preflight_collisions,
)
from cli.promotion import _move_no_replace, _unique_target
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


def _competing_promotion(stage: str, output: str, barrier: Any, results: Any) -> None:
    """Make independent processes both observe absence before publication."""
    target = os.path.join(output, "song (Vocals).wav")
    real_exists = os.path.lexists
    checks = 0

    def synchronized_exists(path: str) -> bool:
        nonlocal checks
        exists = real_exists(path)
        if path == target:
            checks += 1
            if checks == 2:
                barrier.wait(timeout=10)
        return exists

    try:
        with mock.patch("cli.promotion.os.path.lexists", synchronized_exists):
            _promote(stage, output, "fail")
    except FileExistsError:
        results.put((stage, "collision"))
    except Exception as exc:
        results.put((stage, repr(exc)))
    else:
        results.put((stage, "success"))


class PromotionTests(unittest.TestCase):
    def test_independent_processes_cannot_both_publish_the_same_destination(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            output = Path(root, "out")
            output.mkdir()
            context = multiprocessing.get_context("spawn")
            barrier, results = context.Barrier(2), context.Queue()
            processes = []
            stages = []
            try:
                for index in range(2):
                    stage = Path(root, f"stage{index}")
                    stage.mkdir()
                    (stage / "song (Vocals).wav").write_text(stage.name)
                    stages.append(stage)
                    process = context.Process(
                        target=_competing_promotion,
                        args=(str(stage), str(output), barrier, results),
                    )
                    process.start()
                    processes.append(process)
                for process in processes:
                    process.join(timeout=15)
                    self.assertEqual(process.exitcode, 0)
                outcomes = dict(results.get(timeout=2) for _ in processes)
                self.assertEqual(sorted(outcomes.values()), ["collision", "success"])
                for stage in stages:
                    if outcomes[str(stage)] == "success":
                        self.assertEqual((output / "song (Vocals).wav").read_text(), stage.name)
                    else:
                        self.assertEqual((stage / "song (Vocals).wav").read_text(), stage.name)
            finally:
                for process in processes:
                    if process.is_alive():
                        process.terminate()
                    process.join(timeout=5)
                results.close()
                results.join_thread()

    def test_atomic_move_preserves_existing_destination_with_native_and_fallback(self) -> None:
        for fallback in (False, True):
            with self.subTest(fallback=fallback), tempfile.TemporaryDirectory() as root:
                source, target = Path(root, "source"), Path(root, "target")
                source.write_bytes(b"new")
                target.write_bytes(b"old")
                with mock.patch("cli.promotion.sys.platform", "other") if fallback else nullcontext():
                    with self.assertRaises(FileExistsError):
                        _move_no_replace(str(source), str(target))
                    self.assertEqual(source.read_bytes(), b"new")
                    self.assertEqual(target.read_bytes(), b"old")
                    target.unlink()
                    _move_no_replace(str(source), str(target))
                self.assertFalse(source.exists())
                self.assertEqual(target.read_bytes(), b"new")

    def test_fallback_move_removes_claim_when_source_unlink_fails(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            source, target = Path(root, "source"), Path(root, "target")
            source.write_bytes(b"new")
            real_unlink = os.unlink

            def failing_unlink(path: str) -> None:
                if path == str(source):
                    raise PermissionError("source removal denied")
                real_unlink(path)

            with (
                mock.patch("cli.promotion.sys.platform", "other"),
                mock.patch("cli.promotion.os.unlink", failing_unlink),
                self.assertRaises(PermissionError),
            ):
                _move_no_replace(str(source), str(target))
            self.assertEqual(source.read_bytes(), b"new")
            self.assertFalse(target.exists())

    def test_unique_target_treats_dangling_symlink_as_occupied(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            target = Path(root, "song.wav")
            target.symlink_to(Path(root, "missing.wav"))
            self.assertEqual(_unique_target(str(target)), str(Path(root, "song_2.wav")))

    def test_collision_after_last_check_preserves_other_writer_and_rolls_back(self) -> None:
        for policy in ("fail", "skip", "rename"):
            with self.subTest(policy=policy), tempfile.TemporaryDirectory() as root:
                stage, output = Path(root, "stage"), Path(root, "out")
                stage.mkdir()
                output.mkdir()
                names = ("song (Instrumental).wav", "song (Vocals).wav")
                for name in names:
                    (stage / name).write_bytes(b"new")
                raced = output / names[1]
                real_exists = os.path.lexists
                checks = 0

                def racing_exists(
                    path: str,
                    real_exists: Callable[[str], bool] = real_exists,
                    raced: Path = raced,
                ) -> bool:
                    nonlocal checks
                    exists = real_exists(path)
                    if path == str(raced):
                        checks += 1
                        if checks == 2:
                            # The last absence check is already stale when it
                            # returns: another process has published its file.
                            raced.write_bytes(b"other writer")
                    return exists

                with mock.patch("cli.promotion.os.path.lexists", racing_exists):
                    if policy == "rename":
                        promoted = _promote(
                            str(stage), str(output), policy, expected_track_base="song"
                        )
                        self.assertEqual(
                            sorted(Path(path).name for path in promoted),
                            ["song_2 (Instrumental).wav", "song_2 (Vocals).wav"],
                        )
                    else:
                        exception = FileExistsError if policy == "fail" else PromotionSkipped
                        with self.assertRaises(exception):
                            _promote(str(stage), str(output), policy)
                        for name in names:
                            self.assertEqual((stage / name).read_bytes(), b"new")
                self.assertEqual(raced.read_bytes(), b"other writer")
                self.assertFalse((output / names[0]).exists())

    def test_per_file_rename_retries_a_collision_after_last_check(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            stage, output = Path(root, "stage"), Path(root, "out")
            stage.mkdir()
            output.mkdir()
            (stage / "audio.wav").write_bytes(b"new")
            target = output / "audio.wav"
            real_exists = os.path.lexists

            def racing_exists(path: str) -> bool:
                exists = real_exists(path)
                if path == str(target) and not exists:
                    target.write_bytes(b"other writer")
                return exists

            with mock.patch("cli.promotion.os.path.lexists", racing_exists):
                promoted = _promote(str(stage), str(output), "rename")
            self.assertEqual(promoted, [str(output / "audio_2.wav")])
            self.assertEqual(target.read_bytes(), b"other writer")
            self.assertEqual(Path(promoted[0]).read_bytes(), b"new")

    def test_add_model_name_does_not_double_suffix(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            stage = os.path.join(root, "stage")
            output = os.path.join(root, "out")
            os.makedirs(stage)
            planned = "song Model"
            for stem in ("Vocals", "Instrumental"):
                name = f"{format_stem_basename(planned, stem)}.wav"
                Path(os.path.join(stage, name)).write_bytes(b"x")
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
            Path(os.path.join(output, "song (Vocals).wav")).write_bytes(b"old")
            for stem in ("Vocals", "Instrumental"):
                Path(os.path.join(stage, f"song ({stem}).wav")).write_bytes(b"new")
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
            Path(os.path.join(output, "song_live (Vocals).wav")).write_bytes(b"x")
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
            Path(os.path.join(output, "song (Instrumental).wav")).write_bytes(b"old-i")
            Path(os.path.join(output, "song (Vocals).wav")).write_bytes(b"old-v")
            Path(os.path.join(stage, "song (Vocals).wav")).write_bytes(b"new-v")
            Path(os.path.join(stage, "song (Instrumental).wav")).write_bytes(b"new-i")
            destinations = [
                os.path.join(output, "song (Vocals).wav"),
                os.path.join(output, "song (Instrumental).wav"),
            ]
            real_replace = os.replace
            moves = {"n": 0}

            def flaky_replace(src: str, dst: str, *args: object, **kwargs: object) -> None:
                # Backups and rollbacks also use os.replace; only count promotes.
                if os.path.dirname(src) == stage:
                    moves["n"] += 1
                    if moves["n"] == 2:
                        raise OSError("simulated promote failure")
                real_replace(src, dst, *args, **kwargs)

            with mock.patch("cli.promotion.os.replace", flaky_replace):
                with self.assertRaises(OSError):
                    _promote(stage, output, "overwrite", destinations=destinations)

            with open(os.path.join(output, "song (Instrumental).wav"), "rb") as fh:
                self.assertEqual(fh.read(), b"old-i")
            with open(os.path.join(output, "song (Vocals).wav"), "rb") as fh:
                self.assertEqual(fh.read(), b"old-v")
            self.assertTrue(os.path.isfile(os.path.join(stage, "song (Vocals).wav")))
            self.assertTrue(os.path.isfile(os.path.join(stage, "song (Instrumental).wav")))

    def test_overwrite_restores_targets_when_a_backup_fails(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            stage = os.path.join(root, "stage")
            output = os.path.join(root, "out")
            os.makedirs(stage)
            os.makedirs(output)
            Path(os.path.join(output, "song (Instrumental).wav")).write_bytes(b"old-i")
            Path(os.path.join(output, "song (Vocals).wav")).write_bytes(b"old-v")
            Path(os.path.join(stage, "song (Vocals).wav")).write_bytes(b"new-v")
            Path(os.path.join(stage, "song (Instrumental).wav")).write_bytes(b"new-i")
            destinations = [
                os.path.join(output, "song (Vocals).wav"),
                os.path.join(output, "song (Instrumental).wav"),
            ]
            real_replace = os.replace
            backups = {"n": 0}

            def flaky_replace(src: str, dst: str, *args: object, **kwargs: object) -> None:
                if dst.endswith(".uvr-overwrite.bak"):
                    backups["n"] += 1
                    if backups["n"] == 2:
                        raise OSError("simulated backup failure")
                real_replace(src, dst, *args, **kwargs)

            with mock.patch("cli.promotion.os.replace", flaky_replace):
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

    def test_overwrite_backup_moves_instead_of_copying(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            stage = os.path.join(root, "stage")
            output = os.path.join(root, "out")
            os.makedirs(stage)
            os.makedirs(output)
            Path(os.path.join(output, "song (Vocals).wav")).write_bytes(b"old-v")
            Path(os.path.join(stage, "song (Vocals).wav")).write_bytes(b"new-v")
            destinations = [os.path.join(output, "song (Vocals).wav")]

            with mock.patch("cli.execution.shutil.copy2") as copy2:
                promoted = _promote(
                    stage, output, "overwrite", destinations=destinations
                )

            copy2.assert_not_called()
            self.assertEqual(len(promoted), 1)
            with open(os.path.join(output, "song (Vocals).wav"), "rb") as fh:
                self.assertEqual(fh.read(), b"new-v")

    def test_promote_rolls_back_on_base_exception(self) -> None:
        """A KeyboardInterrupt mid-promote must restore the overwrite backup."""
        with tempfile.TemporaryDirectory() as root:
            stage = os.path.join(root, "stage")
            output = os.path.join(root, "out")
            os.makedirs(stage)
            os.makedirs(output)
            Path(os.path.join(output, "song (Instrumental).wav")).write_bytes(b"old-i")
            Path(os.path.join(output, "song (Vocals).wav")).write_bytes(b"old-v")
            Path(os.path.join(stage, "song (Instrumental).wav")).write_bytes(b"new-i")
            Path(os.path.join(stage, "song (Vocals).wav")).write_bytes(b"new-v")
            destinations = [
                os.path.join(output, "song (Vocals).wav"),
                os.path.join(output, "song (Instrumental).wav"),
            ]
            real_replace = os.replace
            moves = {"n": 0}

            def interrupting_replace(
                src: str, dst: str, *args: object, **kwargs: object
            ) -> None:
                if os.path.dirname(src) == stage:
                    moves["n"] += 1
                    if moves["n"] == 2:
                        raise KeyboardInterrupt
                real_replace(src, dst, *args, **kwargs)

            with mock.patch("cli.promotion.os.replace", interrupting_replace):
                with self.assertRaises(KeyboardInterrupt):
                    _promote(stage, output, "overwrite", destinations=destinations)

            self.assertEqual(
                [name for name in os.listdir(output) if "uvr-overwrite.bak" in name],
                [],
            )
            with open(os.path.join(output, "song (Vocals).wav"), "rb") as fh:
                self.assertEqual(fh.read(), b"old-v")
            with open(os.path.join(output, "song (Instrumental).wav"), "rb") as fh:
                self.assertEqual(fh.read(), b"old-i")
            self.assertTrue(os.path.isfile(os.path.join(stage, "song (Vocals).wav")))
            self.assertTrue(
                os.path.isfile(os.path.join(stage, "song (Instrumental).wav"))
            )

    def test_overwrite_removes_backups_after_success(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            stage = os.path.join(root, "stage")
            output = os.path.join(root, "out")
            os.makedirs(stage)
            os.makedirs(output)
            Path(os.path.join(output, "song (Vocals).wav")).write_bytes(b"old-v")
            Path(os.path.join(output, "song (Instrumental).wav")).write_bytes(b"old-i")
            Path(os.path.join(stage, "song (Vocals).wav")).write_bytes(b"new-v")
            Path(os.path.join(stage, "song (Instrumental).wav")).write_bytes(b"new-i")
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

    def test_rename_retries_when_the_chosen_suffix_is_raced(self) -> None:
        # song_2 is free when the suffix is picked, then a concurrent writer
        # takes it before the move, so promotion must land on song_3.
        with tempfile.TemporaryDirectory() as root:
            stage = os.path.join(root, "stage")
            output = os.path.join(root, "out")
            os.makedirs(stage)
            os.makedirs(output)
            Path(os.path.join(output, "song (Vocals).wav")).write_bytes(b"old")
            Path(os.path.join(stage, "song (Vocals).wav")).write_bytes(b"new")
            destinations = [os.path.join(output, "song (Vocals).wav")]
            song_2 = os.path.join(output, "song_2 (Vocals).wav")
            real_makedirs = os.makedirs
            raced = {"done": False}

            def racing_makedirs(path: str, *args: object, **kwargs: object) -> None:
                # Runs once per entry immediately before its move.
                real_makedirs(path, *args, **kwargs)  # type: ignore[arg-type]
                if not raced["done"]:
                    raced["done"] = True
                    Path(song_2).write_bytes(b"raced")

            with mock.patch("cli.promotion.os.makedirs", racing_makedirs):
                promoted = _promote(
                    stage, output, "rename", destinations=destinations,
                )

            self.assertEqual(
                [os.path.basename(path) for path in promoted],
                ["song_3 (Vocals).wav"],
            )
            with open(os.path.join(output, "song_3 (Vocals).wav"), "rb") as fh:
                self.assertEqual(fh.read(), b"new")
            with open(song_2, "rb") as fh:
                self.assertEqual(fh.read(), b"raced")
            self.assertFalse(
                os.path.isfile(os.path.join(output, "song_2 (Vocals)_2.wav"))
            )

    def test_rename_mid_move_race_keeps_one_suffix_for_the_unit(self) -> None:
        # Instrumental lands on song_2, then song_2 (Vocals) is raced away. The
        # unit must roll back and restart at song_3 rather than split suffixes.
        with tempfile.TemporaryDirectory() as root:
            stage = os.path.join(root, "stage")
            output = os.path.join(root, "out")
            os.makedirs(stage)
            os.makedirs(output)
            Path(os.path.join(output, "song (Vocals).wav")).write_bytes(b"old")
            Path(os.path.join(stage, "song (Vocals).wav")).write_bytes(b"new-v")
            Path(os.path.join(stage, "song (Instrumental).wav")).write_bytes(b"new-i")
            destinations = [
                os.path.join(output, "song (Instrumental).wav"),
                os.path.join(output, "song (Vocals).wav"),
            ]
            song_2_vocals = os.path.join(output, "song_2 (Vocals).wav")
            real_move = _move_no_replace
            raced = {"done": False}

            def racing_move(src: str, dst: str) -> None:
                real_move(src, dst)
                if not raced["done"] and os.path.dirname(src) == stage:
                    raced["done"] = True
                    Path(song_2_vocals).write_bytes(b"raced")

            with mock.patch("cli.promotion._move_no_replace", racing_move):
                promoted = _promote(
                    stage, output, "rename", destinations=destinations,
                )

            self.assertEqual(
                sorted(os.path.basename(path) for path in promoted),
                ["song_3 (Instrumental).wav", "song_3 (Vocals).wav"],
            )
            # The rolled-back first move must not leave a stray unit-2 stem.
            self.assertFalse(
                os.path.exists(os.path.join(output, "song_2 (Instrumental).wav"))
            )
            with open(song_2_vocals, "rb") as fh:
                self.assertEqual(fh.read(), b"raced")
            with open(os.path.join(output, "song_3 (Instrumental).wav"), "rb") as fh:
                self.assertEqual(fh.read(), b"new-i")
            with open(os.path.join(output, "song_3 (Vocals).wav"), "rb") as fh:
                self.assertEqual(fh.read(), b"new-v")

    def test_promotions_to_one_output_directory_serialize(self) -> None:
        """Two promotes on the same abspath(output) never overlap."""
        with tempfile.TemporaryDirectory() as root:
            output = os.path.join(root, "out")
            os.makedirs(output)
            stages = []
            for index in (1, 2):
                stage = os.path.join(root, f"stage{index}")
                os.makedirs(stage)
                Path(os.path.join(stage, f"song{index} (Vocals).wav")).write_bytes(b"x")
                stages.append(stage)

            guard = threading.Lock()
            live = {"now": 0, "peak": 0}
            real_move = _move_no_replace

            def slow_move(src: str, dst: str) -> None:
                with guard:
                    live["now"] += 1
                    live["peak"] = max(live["peak"], live["now"])
                time.sleep(0.05)
                real_move(src, dst)
                with guard:
                    live["now"] -= 1

            # Same directory spelled two ways: the lock key is abspath(output).
            targets = [output, os.path.join(output, ".")]
            errors: list[BaseException] = []

            def promote(index: int) -> None:
                try:
                    _promote(stages[index], targets[index], "fail")
                except BaseException as exc:  # reported below
                    errors.append(exc)

            with mock.patch("cli.promotion._move_no_replace", slow_move):
                threads = [
                    threading.Thread(target=promote, args=(index,))
                    for index in (0, 1)
                ]
                for thread in threads:
                    thread.start()
                for thread in threads:
                    thread.join(timeout=5)

            self.assertEqual(errors, [])
            self.assertEqual(live["peak"], 1)
            self.assertTrue(os.path.isfile(os.path.join(output, "song1 (Vocals).wav")))
            self.assertTrue(os.path.isfile(os.path.join(output, "song2 (Vocals).wav")))

    def test_rename_mid_move_extra_stem_does_not_hang(self) -> None:
        # destinations only list Vocals; stage also has Bass. Unit index 2 is free
        # for Vocals but song_2 (Bass).wav already exists — promote must not spin.
        with tempfile.TemporaryDirectory() as root:
            stage = os.path.join(root, "stage")
            output = os.path.join(root, "out")
            os.makedirs(stage)
            os.makedirs(output)
            Path(os.path.join(output, "song (Vocals).wav")).write_bytes(b"old")
            Path(os.path.join(output, "song_2 (Bass).wav")).write_bytes(b"busy")
            Path(os.path.join(stage, "song (Vocals).wav")).write_bytes(b"new-v")
            Path(os.path.join(stage, "song (Bass).wav")).write_bytes(b"new-b")
            destinations = [os.path.join(output, "song (Vocals).wav")]

            promoted = _promote(
                stage, output, "rename", destinations=destinations,
            )

            names = sorted(os.path.basename(path) for path in promoted)
            self.assertEqual(names, ["song_3 (Bass).wav", "song_3 (Vocals).wav"])
            self.assertTrue(os.path.isfile(os.path.join(output, "song_2 (Bass).wav")))
            with open(os.path.join(output, "song_2 (Bass).wav"), "rb") as fh:
                self.assertEqual(fh.read(), b"busy")

    def test_skip_uses_actual_conditional_outputs_as_one_unit(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            stage = os.path.join(root, "stage")
            output = os.path.join(root, "out")
            os.makedirs(stage)
            os.makedirs(output)
            Path(os.path.join(stage, "song (Vocals).wav")).write_bytes(b"new-v")
            Path(os.path.join(stage, "song (Bass).wav")).write_bytes(b"new-b")
            Path(os.path.join(output, "song (Bass).wav")).write_bytes(b"old-b")

            with self.assertRaises(PromotionSkipped):
                _promote(
                    stage,
                    output,
                    "skip",
                    destinations=[os.path.join(output, "song (Vocals).wav")],
                    expected_track_base="song",
                )

            self.assertFalse(os.path.exists(os.path.join(output, "song (Vocals).wav")))
            self.assertTrue(os.path.exists(os.path.join(stage, "song (Vocals).wav")))

    def test_separation_rejects_unassociated_stage_file(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            stage = os.path.join(root, "stage")
            output = os.path.join(root, "out")
            os.makedirs(stage)
            Path(os.path.join(stage, "sidecar.txt")).write_bytes(b"unexpected")
            with self.assertRaisesRegex(OSError, "unexpected staged separation output"):
                _promote(
                    stage,
                    output,
                    "fail",
                    expected_track_base="song",
                )

    def test_retained_ensemble_members_are_promoted_with_the_final_unit(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            stage = os.path.join(root, "stage")
            output = os.path.join(root, "out")
            members = os.path.join(stage, "Saved_Outputs")
            os.makedirs(members)
            Path(os.path.join(stage, "song Ensemble (Vocals).wav")).write_bytes(b"final")
            Path(os.path.join(members, "song Model A (Vocals).wav")).write_bytes(b"member")

            promoted = _promote(
                stage,
                output,
                "fail",
                expected_track_base="song Ensemble",
                ensemble_member_prefix="song",
            )

            self.assertEqual(len(promoted), 2)
            self.assertTrue(os.path.isfile(os.path.join(output, "song Ensemble (Vocals).wav")))
            self.assertTrue(os.path.isfile(os.path.join(output, "Saved_Outputs", "song Model A (Vocals).wav")))

    def test_retained_ensemble_members_share_the_unit_rename_suffix(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            stage = os.path.join(root, "stage")
            output = os.path.join(root, "out")
            members = os.path.join(stage, "Saved_Outputs")
            old_members = os.path.join(output, "Saved_Outputs")
            os.makedirs(members)
            os.makedirs(old_members)
            final_name = "song Ensemble (Vocals).wav"
            member_name = "song Model A (Vocals).wav"
            Path(os.path.join(stage, final_name)).write_bytes(b"new-final")
            Path(os.path.join(members, member_name)).write_bytes(b"new-member")
            Path(os.path.join(output, final_name)).write_bytes(b"old-final")
            Path(os.path.join(old_members, member_name)).write_bytes(b"old-member")

            promoted = _promote(
                stage,
                output,
                "rename",
                expected_track_base="song Ensemble",
                ensemble_member_prefix="song",
            )

            self.assertEqual(
                sorted(os.path.basename(path) for path in promoted),
                ["song Ensemble_2 (Vocals).wav", "song_2 Model A (Vocals).wav"],
            )

    def test_numbered_retained_member_uses_the_numbered_track_prefix(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            stage = os.path.join(root, "stage")
            output = os.path.join(root, "out")
            os.makedirs(stage)
            Path(os.path.join(stage, "2-song Ensemble (Vocals).wav")).write_bytes(b"final")
            Path(os.path.join(stage, "2-song Model A (Vocals).wav")).write_bytes(b"member")

            promoted = _promote(
                stage,
                output,
                "fail",
                expected_track_base="2-song Ensemble",
                ensemble_member_prefix="2-song",
            )

            self.assertEqual(len(promoted), 2)

    def test_rename_noop_extra_name_does_not_hang(self) -> None:
        # Remappable Vocals collide so unit index advances, but sidecar.txt is a
        # non-matching name that _with_unit_suffix cannot change and already exists.
        with tempfile.TemporaryDirectory() as root:
            stage = os.path.join(root, "stage")
            output = os.path.join(root, "out")
            os.makedirs(stage)
            os.makedirs(output)
            Path(os.path.join(output, "song (Vocals).wav")).write_bytes(b"old")
            Path(os.path.join(output, "sidecar.txt")).write_bytes(b"busy")
            Path(os.path.join(stage, "song (Vocals).wav")).write_bytes(b"new-v")
            Path(os.path.join(stage, "sidecar.txt")).write_bytes(b"new-s")
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
