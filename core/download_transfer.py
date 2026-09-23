"""Sequential artifact transfer with cancellation, fallback, and byte progress.

This service performs transfer only. Model registration, usability checks and
repository publication stay at the frontend's model-install boundary.
"""

from __future__ import annotations

import errno
import os
import time
import typing
from typing import Any, Callable, List, Optional, Tuple

from bundled.constants import NO_MODEL

from .debug_log import debug
from .download_sizes import format_download_size


class DownloadTransferService:
    def __init__(
        self,
        *,
        open_url: Callable[[Any], Any],
        estimate_jobs_size: Callable[[List[Tuple[str, str]]], Tuple[int | None, int, int]],
        fallback_url: Callable[[str], str | None],
        info_update_interval_s: float = 0.25,
    ) -> None:
        self._open_url = open_url
        self._estimate_jobs_size = estimate_jobs_size
        self._fallback_url = fallback_url
        self._info_update_interval_s = info_update_interval_s

    def download(
        self,
        jobs: List[Tuple[str, str]],
        on_progress: Optional[Callable[[float], None]] = None,
        on_info: Optional[Callable[[str], None]] = None,
        stop_event: typing.Any = None,
    ) -> str:
        """Download every ``(url, save_path)`` job sequentially.

        Transfer only. Registration, usability verification and repository
        publication belong to ``core.model_install.finalize_downloaded_model``,
        which both frontends call once per logical model -- doing any of it here
        published models before all of their artifacts had landed.

        Reports overall progress in ``[0, 1]`` via ``on_progress`` and a short
        status string via ``on_info``. Honours a ``threading.Event``-style
        ``stop_event`` for cooperative cancellation (checked between chunks).
        Returns one of ``"complete"`` / ``"stopped"`` / ``"exists"``; raises on
        network/IO error so the caller can surface it through the error log.
        """
        from .debug_log import debug, debug_elapsed

        if not jobs:
            if on_info:
                on_info(NO_MODEL)
            return "exists"

        started = time.perf_counter()
        debug("download", f"download start jobs={len(jobs)}")
        pending_jobs = [(url, path) for url, path in jobs if not os.path.isfile(path)]
        total_bytes, file_count, known = self._estimate_jobs_size(pending_jobs)

        # Weight the bar by bytes, not by file count. A model is typically a
        # ~400 MB checkpoint plus a ~4 KB config; splitting the bar evenly
        # between them pins it at 50% for the whole transfer. Sizes have to be
        # known for *every* pending file or the denominator is short and the
        # fraction runs past 1.0, so fall back to counting pending files —
        # already-present ones never report and must stay out of both halves.
        byte_weighted = bool(total_bytes) and known == file_count and file_count > 0
        pending_total = max(1, file_count)
        bytes_done = 0
        pending_index = 0

        def report(downloaded: int, file_total: int) -> None:
            if on_progress is None:
                return
            if byte_weighted and total_bytes:
                overall = (bytes_done + downloaded) / total_bytes
            elif file_total:
                overall = (pending_index + downloaded / file_total) / pending_total
            else:
                return
            on_progress(max(0.0, min(1.0, overall)))

        any_downloaded = False
        for _index, (url, save_path) in enumerate(jobs):
            if stop_event is not None and stop_event.is_set():
                debug("download", "download stopped by user")
                return "stopped"
            if os.path.isfile(save_path):
                continue
            any_downloaded = True
            if on_info:
                if total_bytes is not None:
                    on_info(f"Downloading ({format_download_size(total_bytes)})")
                else:
                    on_info("Downloading…")
            self._download_file(url, save_path, report, stop_event, on_info)
            if stop_event is not None and stop_event.is_set():
                # Remove the partial file so a retry restarts cleanly.
                if os.path.isfile(save_path):
                    try:
                        os.remove(save_path)
                    except OSError:
                        pass
                return "stopped"
            # Advance the baseline by what actually landed on disk, so a
            # short read or an HF-fallback retry cannot double-count.
            try:
                bytes_done += os.path.getsize(save_path)
            except OSError:
                pass
            pending_index += 1

        if on_progress:
            on_progress(1.0)
        result = "complete" if any_downloaded else "exists"
        debug_elapsed("download", f"download done status={result}", started)
        return result

    @staticmethod
    def _download_stopped(stop_event: typing.Any) -> bool:
        return stop_event is not None and stop_event.is_set()

    def _finalize_part_file(self, tmp_path: str, save_path: str, stop_event: typing.Any) -> None:
        """Rename a completed ``.part`` file unless the download was cancelled."""
        if self._download_stopped(stop_event):
            return
        if not os.path.isfile(tmp_path):
            raise FileNotFoundError(
                errno.ENOENT,
                os.strerror(errno.ENOENT),
                tmp_path,
            )
        os.replace(tmp_path, save_path)

    def _download_file(
        self,
        url: typing.Any,
        save_path: typing.Any,
        report: typing.Any,
        stop_event: typing.Any,
        on_info: typing.Any = None,
    ) -> None:
        os.makedirs(os.path.dirname(save_path), exist_ok=True)
        tmp_path = f"{save_path}.part"
        try:
            self._download_file_url(url, tmp_path, report, stop_event, on_info)
            if self._download_stopped(stop_event):
                return
            self._finalize_part_file(tmp_path, save_path, stop_event)
        except Exception:
            if self._download_stopped(stop_event):
                return
            fallback = self._fallback_url(url)
            if fallback and fallback != url:
                debug("download", f"hf fallback {os.path.basename(save_path)}")
                try:
                    if os.path.isfile(tmp_path):
                        os.remove(tmp_path)
                except OSError:
                    pass
                self._download_file_url(fallback, tmp_path, report, stop_event, on_info)
                if self._download_stopped(stop_event):
                    return
                self._finalize_part_file(tmp_path, save_path, stop_event)
                return
            if os.path.isfile(tmp_path):
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass
            raise

    def _download_file_url(
        self,
        url: typing.Any,
        tmp_path: typing.Any,
        report: typing.Any,
        stop_event: typing.Any,
        on_info: typing.Any = None,
    ) -> None:
        try:
            with self._open_url(url) as response:
                length_header = response.getheader("Content-Length")
                file_total = (
                    int(length_header)
                    if isinstance(length_header, str) and length_header.isdigit()
                    else 0
                )
                downloaded = 0
                last_info_at = 0.0
                last_info_text = ""
                with open(tmp_path, "wb") as out_file:
                    while True:
                        if stop_event is not None and stop_event.is_set():
                            out_file.close()
                            if os.path.isfile(tmp_path):
                                try:
                                    os.remove(tmp_path)
                                except OSError:
                                    pass
                            return
                        chunk = response.read(64 * 1024)
                        if not chunk:
                            break
                        out_file.write(chunk)
                        downloaded += len(chunk)
                        if report is not None:
                            report(downloaded, file_total)
                        if on_info and file_total:
                            info_text = (
                                f"{format_download_size(downloaded)} / "
                                f"{format_download_size(file_total)}"
                            )
                            now = time.monotonic()
                            if info_text != last_info_text and (
                                now - last_info_at >= self._info_update_interval_s
                                or downloaded >= file_total
                            ):
                                last_info_at = now
                                last_info_text = info_text
                                on_info(info_text)
                if file_total and downloaded != file_total:
                    raise OSError(
                        f"Incomplete download: received {downloaded} bytes, expected {file_total}"
                    )
        except Exception:
            if os.path.isfile(tmp_path):
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass
            raise
