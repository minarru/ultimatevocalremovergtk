"""Shared application context for the GTK front end.

Holds the single :class:`~core.settings.Settings` (loaded from ``settings.json``)
plus lazily-created :class:`~core.ModelRepository` and :class:`~core.JobRunner`
instances. The repository and runner are created on first use so the window can
be constructed without importing the heavy ML stack (``torch`` / ``separate.py``
are only pulled in once a separation actually starts).

A single context is shared by the window and every method view (and, in later
phases, the settings/ensemble/audio-tool views) so they all read and write the
same settings keys.

The unrecognized-model dialog hook is registered once here so every method view
shares the same :attr:`~core.ModelRepository.on_unrecognized_model` handler.
"""

import threading
from typing import Any, Callable, Optional, Sequence

from core import ModelRepository
from core.debug_log import debug
from core.input_discovery import prune_unreadable_paths
from core.settings import Settings


class AppContext:
    def __init__(self):
        self.settings = Settings.load()
        self._repo = None
        self._repo_lock = threading.Lock()
        self._runner = None
        self._catalogue = None
        self._catalogue_lock = threading.Lock()
        self._download_manager = None
        self._get_dialog_parent: Optional[Callable[[], object]] = None
        #: Session cache for :func:`core.gpu.list_gpu_devices` (None until probed).
        self.gpu_devices = None
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
    def catalogue(self) -> Any:
        if self._catalogue is None:
            with self._catalogue_lock:
                if self._catalogue is None:
                    from core.catalogue_coordinator import CatalogueCoordinator

                    self._catalogue = CatalogueCoordinator()
        return self._catalogue

    @property
    def download_manager(self) -> Any:
        manager = getattr(self, "_download_manager", None)
        if manager is None:
            from core.downloads import DownloadManager

            manager = DownloadManager(coordinator=self.catalogue)
            self._download_manager = manager
        return manager

    @property
    def repo(self) -> ModelRepository:
        if self._repo is None:
            with self._repo_lock:
                if self._repo is None:
                    from core.model_hash_cache import flatten_trusted

                    repo = ModelRepository(catalogue=self.catalogue)
                    repo.model_hash_table = flatten_trusted(
                        self.settings.process.model_hash_table
                    )
                    self._repo = repo
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

    def try_save_settings(self, *, trigger: str = "unspecified") -> Optional[str]:
        """Save settings, returning an error message instead of raising on failure.

        Call sites on the GTK main thread should prefer this over
        :meth:`save_settings` so a full/read-only home directory surfaces a
        toast rather than silently aborting a ``clicked`` handler.
        """
        try:
            self.save_settings(trigger=trigger)
        except OSError as exc:
            return f"Couldn't save settings: {exc}"
        return None

    def stop_all_workers(self, *, force: bool = False) -> None:
        """Cooperatively stop (or force-terminate) every started worker."""
        if self._runner is not None:
            self._runner.stop(force=force)
        queue = getattr(self, "_download_queue", None)
        if queue is not None:
            queue.cancel_all()
        from core.download_sizes import request_shutdown

        request_shutdown()
        from core.catalogue_stem_cache import request_shutdown as stop_stem_workers

        stop_stem_workers()
        catalogue = getattr(self, "_catalogue", None)
        if catalogue is not None:
            catalogue.close()

    def active_download_count(self) -> int:
        """Return queued/downloading model count without creating a queue."""
        queue = getattr(self, "_download_queue", None)
        return queue.active_count() if queue is not None else 0
