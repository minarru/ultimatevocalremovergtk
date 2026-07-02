"""Shared application context for the GTK front end.

Holds the single :class:`~uvr_core.SettingsModel` (loaded from ``data.pkl``) plus
lazily-created :class:`~uvr_core.ModelRepository` and :class:`~uvr_core.JobRunner`
instances. The repository and runner are created on first use so the window can
be constructed without importing the heavy ML stack (``torch`` / ``separate.py``
are only pulled in once a separation actually starts).

A single context is shared by the window and every method view (and, in later
phases, the settings/ensemble/audio-tool views) so they all read and write the
same settings keys.
"""

from uvr_core import ModelRepository, SettingsModel


class AppContext:
    def __init__(self):
        self.settings = SettingsModel.load()
        self._repo = None
        self._runner = None

    @property
    def repo(self) -> ModelRepository:
        if self._repo is None:
            self._repo = ModelRepository()
        return self._repo

    @property
    def runner(self):
        if self._runner is None:
            from uvr_core import JobRunner

            self._runner = JobRunner(self.settings, self.repo)
        return self._runner

    def save_settings(self) -> None:
        self.settings.save()
