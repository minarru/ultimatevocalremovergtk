"""Types for mid-run CUDA OOM recovery choices."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional

OOM_CHOICE_EXPORT = "export"
OOM_CHOICE_STOP = "stop"
OOM_CHOICE_RETRY = "retry"
OOM_CHOICE_AUTO = "auto"

OomChoice = str


@dataclass
class OomChoiceRequest:
    """Payload shown in the OOM recovery dialog / delivered to headless auto."""

    process_kind: str  # "separation" | "ensemble"
    model_label: str
    current_segment: int
    default_segment: int
    first_retry_segment: Optional[int]
    can_export: bool
    can_retry: bool
    completed_members: int
    is_debug_mock: bool = False
    reply: Optional[Callable[[str], None]] = field(default=None, repr=False)

    def respond(self, choice: str) -> None:
        if self.reply is not None:
            self.reply(choice)
