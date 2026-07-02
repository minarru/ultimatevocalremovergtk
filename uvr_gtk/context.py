"""Shared application context for the GTK front end.

Holds the single :class:`~uvr_core.SettingsModel` (loaded from ``data.pkl``) plus
lazily-created :class:`~uvr_core.ModelRepository` and :class:`~uvr_core.JobRunner`
instances. The repository and runner are created on first use so the window can
be constructed without importing the heavy ML stack (``torch`` / ``separate.py``
are only pulled in once a separation actually starts).

A single context is shared by the window and every method view (and, in later
phases, the settings/ensemble/audio-tool views) so they all read and write the
same settings keys.

The unrecognized-model dialog hook is registered once here so every method view
shares the same :attr:`~uvr_core.ModelRepository.on_unrecognized_model` handler.
"""

from typing import Callable, Optional

from uvr_core import ModelRepository, SettingsModel


class AppContext:
    def __init__(self):
        self.settings = SettingsModel.load()
        self._repo = None
        self._runner = None
        self._get_dialog_parent: Optional[Callable[[], object]] = None
        self._unrecognized_hook_installed = False

    def install_unrecognized_model_hook(self, get_parent: Callable[[], object]) -> None:
        """Register the GTK unrecognized-model dialog hook (idempotent)."""
        self._get_dialog_parent = get_parent
        if self._repo is not None:
            self._install_unrecognized_model_hook()

    def _install_unrecognized_model_hook(self) -> None:
        if self._unrecognized_hook_installed or self._get_dialog_parent is None:
            return
        from .dialogs.model_params import make_unrecognized_handler

        self._repo.on_unrecognized_model = make_unrecognized_handler(
            self, self._get_dialog_parent
        )
        self._unrecognized_hook_installed = True

    @property
    def repo(self) -> ModelRepository:
        if self._repo is None:
            self._repo = ModelRepository()
            self._install_unrecognized_model_hook()
        return self._repo

    @property
    def runner(self):
        if self._runner is None:
            from uvr_core import JobRunner

            self._runner = JobRunner(self.settings, self.repo)
        return self._runner

    def save_settings(self) -> None:
        self.settings.save()
