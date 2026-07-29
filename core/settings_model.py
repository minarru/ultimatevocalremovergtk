"""Back-compat ``SettingsModel`` constructor over :class:`~core.settings.Settings`.

New code should use :class:`~core.settings.Settings` (``.defaults()``,
``.from_flat()``, ``.load()``). This class keeps
``SettingsModel()`` / ``SettingsModel(flat_dict)`` working for tests and older
call sites during the cutover.
"""

from __future__ import annotations

import copy
from typing import Any, Optional

from core.settings.model import Settings


class SettingsModel(Settings):
    """Settings with the legacy ``SettingsModel(data=None, path=...)`` constructor."""

    def __init__(
        self,
        data: Optional[dict[str, Any]] = None,
        path: str = "",
    ) -> None:
        fresh = Settings.defaults()
        super().__init__(
            schema_version=fresh.schema_version,
            process=copy.deepcopy(fresh.process),
            vr=copy.deepcopy(fresh.vr),
            mdx=copy.deepcopy(fresh.mdx),
            demucs=copy.deepcopy(fresh.demucs),
            ensemble=copy.deepcopy(fresh.ensemble),
            audio_tools=copy.deepcopy(fresh.audio_tools),
            ui=copy.deepcopy(fresh.ui),
            path=path or "",
        )
        if data:
            self.update(data)


__all__ = ["SettingsModel"]
