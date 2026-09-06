"""Worker/download polling and application hold/release during shutdown."""

from __future__ import annotations

from typing import TYPE_CHECKING, Callable, Protocol

from core.debug_log import debug, verbose

from .lifetime import TimerScheduler
from .protocols import RunHost, RunTarget

if TYPE_CHECKING:
    from gi.repository import Gtk


class ReleaseMemory(Protocol):
    def __call__(
        self,
        *,
        wait_for_stop: float = 0.0,
        force_if_alive: bool = False,
        clear_weight_cache: bool = False,
        park_weights: bool = False,
        on_done: Callable[[], None] | None = None,
    ) -> None: ...


class RunShutdownCoordinator:
    def __init__(
        self,
        host: RunHost,
        scheduler: TimerScheduler,
        release: ReleaseMemory,
        on_shutdown: Callable[[], None],
        on_stop_cleanup: Callable[[RunTarget], None] | None = None,
    ):
        self.host = host
        self.scheduler = scheduler
        self.release = release
        self.on_shutdown = on_shutdown
        self.on_stop_cleanup = on_stop_cleanup
        self.cleanup_target: RunTarget | None = None
        self.cleanup_attempts = 0
        self._cleanup_generation = 0
        self._cleanup_release_started = False
        self._cleanup_release_finished = False
        self.shutdown_target: RunTarget | None = None
        self.shutdown_attempts = 0
        self.exit_pending = False
        self.exit_timeout_id: int | None = None
        self.exit_app: Gtk.Application | None = None

    def schedule_inference_cleanup(self, target: RunTarget) -> None:
        debug('cleanup', f'cleanup poll scheduled target={type(target).__name__}')
        self.cleanup_target = target
        self.cleanup_attempts = 0
        self._cleanup_generation += 1
        self._cleanup_release_started = False
        self._cleanup_release_finished = False
        self.scheduler.timeout_add(50, self.poll_inference_cleanup)

    def poll_inference_cleanup(self) -> bool:
        target = self.cleanup_target
        if target is None:
            return False
        self.cleanup_attempts += 1
        alive = target.worker_is_running()
        if self._cleanup_release_started:
            if not self._cleanup_release_finished:
                return False
            if alive:
                return True
            self.cleanup_target = None
            if self.on_stop_cleanup is not None:
                self.on_stop_cleanup(target)
            return False
        if not alive or self.cleanup_attempts >= 80:
            debug('cleanup', f'poll attempt={self.cleanup_attempts} worker_alive={alive} releasing')
            self._cleanup_release_started = True
            generation = self._cleanup_generation

            def released() -> None:
                # A cooperative terminal callback may already have cancelled
                # this cleanup, or the same page may have started a later run.
                if self.cleanup_target is not target or self._cleanup_generation != generation:
                    return
                self._cleanup_release_finished = True
                if self.poll_inference_cleanup():
                    self.scheduler.timeout_add(50, self.poll_inference_cleanup)

            self.release(force_if_alive=alive, on_done=released)
            return False
        if verbose():
            debug('cleanup', f'poll attempt={self.cleanup_attempts} worker_alive=True')
        return True

    def schedule_shutdown_poll(self, target: RunTarget | None) -> None:
        debug(
            'cleanup', f'shutdown poll scheduled target={type(target).__name__ if target else None}'
        )
        self.shutdown_target = target
        self.shutdown_attempts = 0
        self.scheduler.timeout_add(50, self.poll_shutdown)

    def poll_shutdown(self) -> bool:
        target = self.shutdown_target
        self.shutdown_attempts += 1
        worker_alive = target.worker_is_running() if target is not None else False
        downloads_alive = self.host.active_download_count() > 0
        if not (worker_alive or downloads_alive) or self.shutdown_attempts >= 80:
            debug(
                'cleanup',
                f'shutdown poll attempt={self.shutdown_attempts} worker_alive={worker_alive} downloads_alive={downloads_alive}',
            )
            self.shutdown_target = None
            self.on_shutdown()
            return False
        return True

    def begin_exit_cleanup(self) -> None:
        if self.exit_pending:
            return
        self.exit_pending = True
        self.exit_app = self.host.get_application()
        if self.exit_app is not None:
            self.exit_app.hold()
        if self.exit_timeout_id is not None:
            self.scheduler.source_remove(self.exit_timeout_id)
        self.exit_timeout_id = self.scheduler.timeout_add(10000, self.on_exit_cleanup_timeout)
        self.release(force_if_alive=True, clear_weight_cache=True, on_done=self.finish_exit_cleanup)

    def on_exit_cleanup_timeout(self) -> bool:
        self.exit_timeout_id = None
        if self.exit_pending:
            debug('cleanup', 'exit cleanup timed out; forcing worker stop and quit')
            self.host.stop_all_workers(force=True)
            self.finish_exit_cleanup()
        return False

    def finish_exit_cleanup(self) -> None:
        if not self.exit_pending:
            return
        self.exit_pending = False
        if self.exit_timeout_id is not None:
            self.scheduler.source_remove(self.exit_timeout_id)
            self.exit_timeout_id = None
        app = self.exit_app or self.host.get_application()
        self.exit_app = None
        if app is not None:
            debug('ui', 'exit cleanup finish: release and quit')
            app.release()
            app.quit()
        else:
            from .shutdown import finalize_process_exit

            finalize_process_exit(0)
