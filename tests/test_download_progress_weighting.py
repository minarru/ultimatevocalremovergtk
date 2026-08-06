"""Overall download progress must track bytes, not file count.

A typical MDX-C model is two jobs: a ~400 MB checkpoint and a ~4 KB YAML
config. Weighting them equally puts the checkpoint — 99.999% of the transfer —
in the first half of the bar, so it reads as "stuck at 50%".
"""

from __future__ import annotations

import io
import os
import tempfile
import typing
import unittest
from unittest import mock

from core import downloads as downloads_mod
from core.downloads import DownloadManager

_CHUNK = 64 * 1024


class _FakeResponse(io.BytesIO):
    def __init__(self, payload: bytes) -> None:
        super().__init__(payload)
        self._len = len(payload)

    def getheader(self, name: str) -> typing.Optional[str]:
        return str(self._len) if name == "Content-Length" else None

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, *_args: object) -> None:
        return None


class ProgressWeightingTests(unittest.TestCase):
    def _run(
        self,
        sizes: dict[str, int],
        *,
        preexisting: tuple[str, ...] = (),
        known_sizes: bool = True,
    ) -> list[float]:
        """Drive the real ``download()`` and return every reported fraction."""
        seen: list[float] = []
        with tempfile.TemporaryDirectory() as tmp:
            jobs: list[tuple[str, str]] = []
            bodies: dict[str, bytes] = {}
            for name, size in sizes.items():
                url = f"https://example.test/{name}"
                jobs.append((url, os.path.join(tmp, name)))
                bodies[url] = b"x" * size
            for name in preexisting:
                with open(os.path.join(tmp, name), "wb") as handle:
                    handle.write(b"already here")

            pending_bytes = sum(
                size for name, size in sizes.items() if name not in preexisting
            )
            pending_count = len(sizes) - len(preexisting)
            estimate = (
                (pending_bytes, pending_count, pending_count)
                if known_sizes
                else (None, pending_count, 0)
            )

            with mock.patch.object(
                downloads_mod, "_urlopen", side_effect=lambda url: _FakeResponse(bodies[url])
            ), mock.patch.object(
                downloads_mod, "estimate_jobs_size", return_value=estimate
            ):
                DownloadManager().download(
                    jobs, on_progress=seen.append, on_info=lambda _text: None
                )
        return seen

    def test_checkpoint_fills_the_bar_not_half_of_it(self) -> None:
        """The 4 KB config must not own half the bar."""
        seen = self._run({"model.ckpt": _CHUNK * 20, "config.yaml": 4})

        # Last report before the tiny config starts is the end of the checkpoint.
        at_checkpoint_end = max(seen[:-2])
        self.assertGreater(
            at_checkpoint_end,
            0.99,
            f"bar was at {at_checkpoint_end:.0%} once the checkpoint finished",
        )

    def test_half_the_checkpoint_reads_as_half_the_bar(self) -> None:
        seen = self._run({"model.ckpt": _CHUNK * 20, "config.yaml": 4})
        midpoint = seen[9]  # 10 of 20 chunks
        self.assertAlmostEqual(midpoint, 0.5, delta=0.02)

    def test_preexisting_config_does_not_cap_the_bar(self) -> None:
        """A config already on disk used to leave the bar pinned at 50%.

        The skipped file stayed in the denominator while never reporting, so
        the only movement was the checkpoint's half.
        """
        seen = self._run(
            {"model.ckpt": _CHUNK * 20, "config.yaml": 4},
            preexisting=("config.yaml",),
        )
        before_final = max(seen[:-1])
        self.assertGreater(
            before_final,
            0.99,
            f"bar peaked at {before_final:.0%} with the config already on disk",
        )

    def test_progress_never_goes_backwards(self) -> None:
        seen = self._run({"model.ckpt": _CHUNK * 8, "extra.ckpt": _CHUNK * 2})
        self.assertEqual(seen, sorted(seen))

    def test_falls_back_to_pending_file_count_when_sizes_unknown(self) -> None:
        """No HEAD sizes: still weight over *pending* files only."""
        seen = self._run(
            {"model.ckpt": _CHUNK * 8, "config.yaml": 4},
            preexisting=("config.yaml",),
            known_sizes=False,
        )
        # One pending file of two jobs — it owns the whole bar, not half.
        before_final = max(seen[:-1])
        self.assertGreater(before_final, 0.99)

    def test_unknown_sizes_split_two_pending_files_evenly(self) -> None:
        seen = self._run(
            {"a.ckpt": _CHUNK * 4, "b.ckpt": _CHUNK * 4}, known_sizes=False
        )
        self.assertAlmostEqual(seen[3], 0.5, delta=0.02)


if __name__ == "__main__":
    unittest.main()
