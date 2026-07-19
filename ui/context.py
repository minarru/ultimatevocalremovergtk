"""Shared application context for the GTK front end.

Holds the single :class:`~core.SettingsModel` (loaded from ``data.pkl``) plus
lazily-created :class:`~core.ModelRepository` and :class:`~core.JobRunner`
instances. The repository and runner are created on first use so the window can
be constructed without importing the heavy ML stack (``torch`` / ``separate.py``
are only pulled in once a separation actually starts).

A single context is shared by the window and every method view (and, in later
phases, the settings/ensemble/audio-tool views) so they all read and write the
same settings keys.

The unrecognized-model dialog hook is registered once here so every method view
shares the same :attr:`~core.ModelRepository.on_unrecognized_model` handler.
"""

from typing import Callable, Optional, Sequence

from core import ModelRepository, SettingsModel
from core.debug_log import debug

from .shared_settings import prune_unreadable_paths


class AppContext:
    def __init__(self):
        self.settings = SettingsModel.load()
        self._repo = None
        self._runner = None
        self._get_dialog_parent: Optional[Callable[[], object]] = None
        self._unrecognized_hook_installed = False
        #: Ephemeral: paths that failed the last Verify Inputs run (not persisted).
        self.unreadable_input_paths: set[str] = set()

    def set_unreadable_input_paths(self, paths: Sequence[str]) -> None:
        self.unreadable_input_paths = {p for p in paths if p}

    def prune_unreadable_input_paths(self, current_paths: Sequence[str]) -> None:
        self.unreadable_input_paths = prune_unreadable_paths(
            self.unreadable_input_paths, current_paths
        )

    def clear_unreadable_input_paths(self) -> None:
        self.unreadable_input_paths.clear()

    def install_unrecognized_model_hook(self, get_parent: Callable[[], object]) -> None:
        """Register the GTK unrecognized-model dialog hook (idempotent)."""
        self._get_dialog_parent = get_parent
        if self._repo is not None:
            self._install_unrecognized_model_hook()

    def _install_unrecognized_model_hook(self) -> None:
        repo = self._repo
        if self._unrecognized_hook_installed or self._get_dialog_parent is None or repo is None:
            return
        from .dialogs.model_params import make_unrecognized_handler

        repo.on_unrecognized_model = make_unrecognized_handler(
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
            from core import JobRunner

            self._runner = JobRunner(self.settings, self.repo)
        return self._runner

    def save_settings(self, *, trigger: str = "unspecified") -> None:
        path = self.settings.path
        debug("settings", f"save_settings trigger={trigger} path={path}")
        try:
            self.settings.save()
            debug("settings", f"save_settings ok keys={len(self.settings.to_dict())}")
        except OSError as exc:
            debug("settings", f"save_settings failed error={type(exc).__name__}: {exc}")
            raise

    def stop_all_workers(self, *, force: bool = False) -> None:
        """Cooperatively stop (or force-terminate) every started worker."""
        if self._runner is not None:
            self._runner.stop(force=force)
