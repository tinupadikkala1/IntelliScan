"""Thread manager.

Wraps ``QThreadPool`` and provides a ``Worker`` that runs an arbitrary
callable off the GUI thread, forwarding progress/result/error through Qt
signals so the UI stays responsive.
"""

from __future__ import annotations

import threading
from typing import Any, Callable

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal


class WorkerSignals(QObject):
    progress = Signal(int, int)   # current, total
    finished = Signal(object)     # result
    error = Signal(Exception)


class Worker(QRunnable):
    def __init__(self, fn: Callable, args, kwargs, cancel_event: threading.Event | None) -> None:
        super().__init__()
        self.setAutoDelete(False)
        self.fn = fn
        self.args = args
        self.kwargs = kwargs
        self.cancel_event = cancel_event
        self.signals = WorkerSignals()

    def run(self) -> None:
        try:
            result = self.fn(self.signals.progress.emit, self.cancel_event, *self.args, **self.kwargs)
            try:
                self.signals.finished.emit(result)
            except RuntimeError:
                pass
        except Exception as exc:
            try:
                self.signals.error.emit(exc)
            except RuntimeError:
                pass


class ThreadManager:
    def __init__(self, max_threads: int | None = None) -> None:
        self.pool = QThreadPool()
        if max_threads:
            self.pool.setMaxThreadCount(max_threads)
        self._workers: set[Worker] = set()

    @property
    def max_threads(self) -> int:
        return self.pool.maxThreadCount()

    def shutdown(self, timeout_ms: int = 5000) -> None:
        """Block until all worker threads finish; safe to call on exit."""
        self.pool.waitForDone(timeout_ms)

    def submit(
        self,
        fn: Callable,
        *args,
        on_finished: Callable[[Any], None] | None = None,
        on_error: Callable[[Exception], None] | None = None,
        on_progress: Callable[[int, int], None] | None = None,
        cancel_event: threading.Event | None = None,
        **kwargs,
    ) -> Worker:
        worker = Worker(fn, args, kwargs, cancel_event)
        if on_finished:
            worker.signals.finished.connect(on_finished)
        if on_error:
            worker.signals.error.connect(on_error)
        if on_progress:
            worker.signals.progress.connect(on_progress)

        def _cleanup(*_a):
            self._workers.discard(worker)

        worker.signals.finished.connect(_cleanup)
        worker.signals.error.connect(_cleanup)

        self._workers.add(worker)
        self.pool.start(worker)
        return worker

