"""Shared headings and result lines for human-readable worker output."""

from __future__ import annotations

import os
import time


def file_heading(path: str, index: int, total: int) -> str:
    return f"\nFile {index}/{total} — {os.path.basename(path)}\n"


def run_summary(status: str, elapsed_seconds: float) -> str:
    elapsed = time.strftime("%H:%M:%S", time.gmtime(int(elapsed_seconds)))
    return f"\nProcess {status} · Elapsed: {elapsed}\n"
