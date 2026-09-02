"""Task manager.

High-level scheduling on top of :class:`ThreadManager`. Each task gets a
unique id, is persisted (when a repository is supplied), reports progress and
completion through both local signals and the shared signal bus, and can be
cancelled via a cancel event.
"""

from __future__ import annotations

import threading
import uuid
from typing import Any, Callable

from PySide6.QtCore import QObject, Signal

from services.thread_manager import ThreadManager


class TaskManager(QObject):
    task_progress = Signal(str, int, int)  # task_id, current, total
    task_finished = Signal(str, object)    # task_id, result
    task_error = Signal(str, object)       # task_id, exception

    def __init__(
        self,
        thread_manager: ThreadManager | None = None,
        repository=None,
        bus=None,
    ) -> None:
        super().__init__()
        self.threads = thread_manager or ThreadManager()
        self.repository = repository
        self.bus = bus
        self._active: dict[str, tuple[Any, threading.Event]] = {}

    # ------------------------------------------------------------------ #
    def submit(
        self,
        fn: Callable,
        type_: str = "generic",
        task_id: str | None = None,
        *args,
        on_finished: Callable[[Any], None] | None = None,
        on_error: Callable[[Exception], None] | None = None,
        on_progress: Callable[[int, int], None] | None = None,
        **kwargs,
    ) -> str:
        task_id = task_id or uuid.uuid4().hex
        cancel = threading.Event()
        if self.repository is not None:
            self.repository.add_task(task_id, type_)

        def _finished(result):
            if self.repository is not None:
                self.repository.update_task(task_id, status="done")
            self.task_finished.emit(task_id, result)
            if self.bus is not None:
                self.bus.task_finished.emit(task_id, result)
            self._active.pop(task_id, None)
            if on_finished:
                on_finished(result)

        def _error(err):
            if self.repository is not None:
                self.repository.update_task(task_id, status="error")
            self.task_error.emit(task_id, err)
            self._active.pop(task_id, None)
            if on_error:
                on_error(err)

        def _progress(cur, tot):
            if self.repository is not None:
                self.repository.update_task(task_id, progress=cur, total=tot)
            self.task_progress.emit(task_id, cur, tot)
            if self.bus is not None:
                self.bus.task_progress.emit(task_id, cur, tot)
            if on_progress:
                on_progress(cur, tot)

        self.threads.submit(
            fn,
            *args,
            on_finished=_finished,
            on_error=_error,
            on_progress=_progress,
            cancel_event=cancel,
            **kwargs,
        )
        self._active[task_id] = (None, cancel)
        return task_id

    def cancel(self, task_id: str) -> None:
        entry = self._active.get(task_id)
        if entry is not None:
            entry[1].set()  # request cancellation inside the worker

    def active_count(self) -> int:
        return len(self._active)

    def prune(self, keep: int = 1000, max_age_days: int = 30) -> int:
        """Prune old completed/failed task rows (Batch 7 task-table hygiene).

        Delegates to the repository; safe no-op when no repository is
        attached. Active tasks are never touched (pruning only considers
        rows with a ``finished`` timestamp).
        """
        if self.repository is None:
            return 0
        try:
            return self.repository.prune_tasks(keep=keep, max_age_days=max_age_days)
        except Exception as exc:  # pragma: no cover - defensive
            if self.bus is not None:
                self.bus.status_message.emit(f"Task cleanup skipped: {exc}")
            return 0
