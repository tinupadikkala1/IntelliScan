"""File watcher.

A thin wrapper around ``watchdog`` that watches a directory and emits a Qt
signal whenever the filesystem changes. The main window re-points it at the
current folder on navigation. Cross-thread watchdog events are relayed through
a Qt signal (queued to the GUI thread automatically).
"""

from __future__ import annotations

import os

from PySide6.QtCore import QObject, Signal

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer


class _Handler(FileSystemEventHandler):
    def __init__(self, signal: Signal) -> None:
        super().__init__()
        self._signal = signal
        self._last: dict[str, float] = {}

    def on_any_event(self, event) -> None:
        try:
            if getattr(event, "is_directory", False):
                return
            import time

            from services.path_utils import norm as _norm

            p = _norm(getattr(event, "src_path", "") or "")
            now = time.monotonic()
            if now - self._last.get(p, 0.0) < 0.8:
                return
            self._last[p] = now
            self._signal.emit(p)
        except Exception:
            try:
                self._signal.emit(getattr(event, "src_path", ""))
            except Exception:
                pass


class FileWatcher(QObject):
    changed = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._handler = _Handler(self.changed)
        self._observer: Observer | None = None
        self._watched: str | None = None

    @property
    def watched_path(self) -> str | None:
        return self._watched

    def watch(self, path: str) -> None:
        if not path or not os.path.isdir(path):
            return
        # Reuse a single Observer/thread across navigations. A stopped
        # observer cannot be restarted, so recreate it in that case.
        if self._observer is None or not self._observer.is_alive():
            self._observer = Observer()
        else:
            try:
                self._observer.unschedule_all()
            except Exception:
                pass
        try:
            self._observer.schedule(self._handler, path, recursive=True)
        except OSError as e:
            # inotify limit (CI/test boxes) — fall back to non-recursive, never crash UI.
            import errno
            import logging

            logging.getLogger(__name__).warning("Watcher recursive failed (%s), fallback flat", e)
            try:
                self._observer.schedule(self._handler, path, recursive=False)
            except Exception:
                return
        if not self._observer.is_alive():
            try:
                self._observer.start()
            except OSError:
                return
        try:
            from services.path_utils import norm as _norm

            self._watched = _norm(path)
        except Exception:
            self._watched = path

    def _stop_observer(self) -> None:
        obs = getattr(self, "_observer", None)
        if obs is None:
            return
        try:
            obs.unschedule_all()
        except Exception:
            pass
        if obs.is_alive():
            obs.stop()
            try:
                obs.join(timeout=1)
            except Exception:
                pass

    def stop(self) -> None:
        self._stop_observer()

    def shutdown(self) -> None:
        self._stop_observer()
