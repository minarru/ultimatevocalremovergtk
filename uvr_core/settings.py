"""Tk-free settings model.

``SettingsModel`` is a thin, framework-agnostic wrapper around a plain ``dict``
seeded from :data:`data.constants.DEFAULT_DATA`. It replaces the swarm of
``tk.StringVar`` / ``tk.BooleanVar`` instances that ``UVR.py`` keeps on the root
window, while preserving the exact schema (keys and default values) and the same
``data.pkl`` pickle persistence used today (see ``save_data``/``load_data`` in
``UVR.py``).

The GTK layer (and later phases) bind widgets to these keys and call
:meth:`save` on relevant changes / shutdown, exactly as the Tkinter UI does on
auto-save and app close.
"""

import copy
import pickle
from typing import Any, Dict, Optional

from data.constants import DEFAULT_DATA

from .paths import SETTINGS_DATA_FILE


class SettingsModel:
    """Mutable key/value store backed by ``DEFAULT_DATA`` and persisted as pickle."""

    def __init__(self, data: Optional[Dict[str, Any]] = None, path: str = SETTINGS_DATA_FILE):
        self.path = path
        self._data: Dict[str, Any] = copy.deepcopy(DEFAULT_DATA)
        if data:
            self._data.update(data)

    @classmethod
    def load(cls, path: str = SETTINGS_DATA_FILE) -> "SettingsModel":
        """Load settings from ``path``, falling back to defaults if absent/corrupt.

        Any keys missing from the persisted file are backfilled from
        ``DEFAULT_DATA`` (mirroring ``load_saved_vars`` in ``UVR.py``).
        """
        try:
            with open(path, "rb") as data_file:
                stored = pickle.load(data_file)
            if not isinstance(stored, dict):
                stored = {}
        except (ValueError, EOFError, FileNotFoundError, pickle.UnpicklingError):
            stored = {}
        return cls(stored, path=path)

    def save(self, path: Optional[str] = None) -> None:
        """Persist the full settings dict as pickle, like ``save_data``."""
        target = path or self.path
        with open(target, "wb") as data_file:
            pickle.dump(self._data, data_file)

    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, default)

    def set(self, key: str, value: Any) -> None:
        self._data[key] = value

    def update(self, values: Dict[str, Any]) -> None:
        self._data.update(values)

    def reset_to_default(self) -> None:
        """Restore every key to its ``DEFAULT_DATA`` value."""
        self._data = copy.deepcopy(DEFAULT_DATA)

    def to_dict(self) -> Dict[str, Any]:
        """Return a deep copy of the backing dict."""
        return copy.deepcopy(self._data)

    def __getitem__(self, key: str) -> Any:
        return self._data[key]

    def __setitem__(self, key: str, value: Any) -> None:
        self._data[key] = value

    def __contains__(self, key: str) -> bool:
        return key in self._data
