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

import copy
import os
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

    def start_identity_migration(
        self, callback: Callable[[Any], None]
    ) -> None:
        """Migrate persisted model references without blocking GTK startup."""
        snapshot = copy.deepcopy(self.settings)
        repo = self.repo

        def worker() -> None:
            from core.identity_migration import migrate_identity_storage

            result = migrate_identity_storage(snapshot, repo)
            callback(result)

        threading.Thread(
            target=worker, name="uvr-identity-migration", daemon=True
        ).start()

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
            with self._repo_lock:
                if self._repo is None:
                    from core.model_hash_cache import flatten_trusted

                    repo = ModelRepository()
                    repo.model_hash_table = flatten_trusted(
                        self.settings.process.model_hash_table
                    )
                    self._repo = repo
                    self._install_unrecognized_model_hook()
        return self._repo

    def apply_identity_migration(
        self, result: Any
    ) -> tuple[int, int, Optional[str]]:
        """Apply worker-produced identity patches without reverting live edits."""
        from core.identity_migration import IdentitySettingChange
        from core.json_store import backup_once
        from core.settings.access import get_path, set_path

        applied: list[IdentitySettingChange] = []
        conflicts = 0
        version_change = next(
            (change for change in result.settings_changes
             if change.path == "identity_schema_version"),
            None,
        )
        for change in result.settings_changes:
            if change.path == "identity_schema_version":
                continue
            current = get_path(self.settings, change.path)
            if current != change.old:
                conflicts += 1
                continue
            set_path(self.settings, change.path, copy.deepcopy(change.new))
            applied.append(change)
        if version_change is not None and conflicts == 0:
            if self.settings.identity_schema_version == version_change.old:
                self.settings.identity_schema_version = int(version_change.new)
                applied.append(version_change)
            elif self.settings.identity_schema_version != version_change.new:
                conflicts += 1
        if not applied:
            return 0, conflicts, None
        try:
            if self.settings.path and os.path.isfile(self.settings.path):
                backup_once(self.settings.path)
            self.save_settings(trigger="identity-migration")
        except OSError as exc:
            for change in reversed(applied):
                if change.path == "identity_schema_version":
                    self.settings.identity_schema_version = int(change.old)
                else:
                    set_path(self.settings, change.path, copy.deepcopy(change.old))
            return 0, conflicts, str(exc)
        return len(applied), conflicts, None

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

    def active_download_count(self) -> int:
        """Return queued/downloading model count without creating a queue."""
        queue = getattr(self, "_download_queue", None)
        return queue.active_count() if queue is not None else 0
