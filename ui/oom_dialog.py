"""CUDA OOM recovery dialog (Export / Stop / Retry with segment backoff)."""

from __future__ import annotations

import typing
from typing import Callable

from gi.repository import Adw

from core.oom_choice import (
    OOM_CHOICE_EXPORT,
    OOM_CHOICE_RETRY,
    OOM_CHOICE_STOP,
    OomChoiceRequest,
)

if typing.TYPE_CHECKING:
    from gi.repository import Gtk


def mock_oom_request(*, separation: bool = False) -> OomChoiceRequest:
    """Build a forced full-options request for ``UVR_DEBUG_OOM`` visual QA."""
    from core.oom_segment import backoff_candidates

    current = 2208
    default = 256
    candidates = backoff_candidates(current, default)
    return OomChoiceRequest(
        process_kind="separation" if separation else "ensemble",
        model_label="SCNet — Tran 4 Stems · ZFTurbo",
        current_segment=current,
        default_segment=default,
        first_retry_segment=candidates[0] if candidates else None,
        can_export=not separation,
        can_retry=True,
        completed_members=0 if separation else 2,
        is_debug_mock=True,
    )


def present_oom_choice_dialog(
    parent: Gtk.Window,
    request: OomChoiceRequest,
    *,
    on_choice: Callable[[str], None],
) -> Adw.AlertDialog:
    """Present the OOM recovery dialog and invoke ``on_choice`` with the response id."""
    if request.is_debug_mock:
        heading = "GPU out of memory (debug mock)"
    else:
        heading = "GPU out of memory"

    lines = [
        f"Model: {request.model_label}" if request.model_label else "",
        f"Current segment size: {request.current_segment}",
        f"Model default segment: {request.default_segment}",
    ]
    if request.can_retry and request.first_retry_segment is not None:
        lines.append(
            f"Retry will try segment {request.first_retry_segment} first "
            f"(then smaller sizes), for this run only."
        )
    if request.can_export:
        lines.append(
            f"{request.completed_members} completed ensemble member(s) can be "
            "exported to your output folder (no combine)."
        )
    if request.is_debug_mock:
        lines.append("Debug mock — no inference or files are affected.")
    body = "\n".join(line for line in lines if line)

    dialog = Adw.AlertDialog(heading=heading, body=body)
    if request.can_export:
        dialog.add_response(OOM_CHOICE_EXPORT, "Export completed")
    dialog.add_response(OOM_CHOICE_STOP, "Stop")
    if request.can_retry:
        dialog.add_response(OOM_CHOICE_RETRY, "Retry with smaller segment")
        dialog.set_response_appearance(OOM_CHOICE_RETRY, Adw.ResponseAppearance.SUGGESTED)
    dialog.set_response_appearance(OOM_CHOICE_STOP, Adw.ResponseAppearance.DESTRUCTIVE)
    dialog.set_default_response(
        OOM_CHOICE_RETRY if request.can_retry else OOM_CHOICE_STOP
    )
    dialog.set_close_response(OOM_CHOICE_STOP)

    settled = {"done": False}

    def finish(choice: str) -> None:
        if settled["done"]:
            return
        settled["done"] = True
        on_choice(choice)

    def on_response(_dlg: Adw.AlertDialog, response: str) -> None:
        choice = response if response in (
            OOM_CHOICE_EXPORT,
            OOM_CHOICE_STOP,
            OOM_CHOICE_RETRY,
        ) else OOM_CHOICE_STOP
        finish(choice)

    def on_closed(_dlg: Adw.AlertDialog) -> None:
        finish(OOM_CHOICE_STOP)

    dialog.connect("response", on_response)
    dialog.connect("closed", on_closed)
    dialog.present(parent)
    return dialog
