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
    ):
        self.host = host
        self.scheduler = scheduler
        self.release = release
        self.on_shutdown = on_shutdown
        self.cleanup_target: RunTarget | None = None
        self.cleanup_attempts = 0
        self.shutdown_target: RunTarget | None = None
        self.shutdown_attempts = 0
        self.exit_pending = False
        self.exit_timeout_id: int | None = None
        self.exit_app: Gtk.Application | None = None

    def schedule_inference_cleanup(self, target: RunTarget) -> None:
        debug('cleanup', f'cleanup poll scheduled target={type(target).__name__}')
        self.cleanup_target = target
        self.cleanup_attempts = 0
        self.scheduler.timeout_add(50, self.poll_inference_cleanup)

    def poll_inference_cleanup(self) -> bool:
        target = self.cleanup_target
        if target is None:
            return False
        self.cleanup_attempts += 1
        alive = target.worker_is_running()
        if not alive or self.cleanup_attempts >= 80:
            debug('cleanup', f'poll attempt={self.cleanup_attempts} worker_alive={alive} releasing')
            self.cleanup_target = None
            self.release(force_if_alive=alive)
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
