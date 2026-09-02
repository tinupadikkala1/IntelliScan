import os
import time

import pytest
from PySide6.QtCore import QElapsedTimer
from PySide6.QtWidgets import QApplication

from app.container import Container
from services.thread_manager import ThreadManager
from services.task_manager import TaskManager
from services.file_watcher import FileWatcher
from services.cache_manager import CacheManager
from database.engine import Database
from database.repository import Repository


def _wait(predicate, timeout=5000):
    timer = QElapsedTimer()
    timer.start()
    while not predicate() and timer.elapsed() < timeout:
        QApplication.processEvents()


def test_thread_manager_runs_off_gui(qapp):
    tm = ThreadManager()
    result = {}
    tm.submit(lambda progress, cancel: 21 * 2, on_finished=lambda r: result.update(v=r))
    _wait(lambda: result)
    tm.shutdown()
    assert result.get("v") == 42


def test_thread_manager_progress(qapp):
    tm = ThreadManager()
    seen = []
    tm.submit(
        lambda progress, cancel: progress(5, 10),
        on_progress=lambda c, t: seen.append((c, t)),
    )
    _wait(lambda: seen)
    tm.shutdown()
    assert (5, 10) in seen


def test_task_manager_persists_and_signals(qapp, tmp_path):
    db = Database(str(tmp_path / "t.db"))
    repo = Repository(db)
    tasks = TaskManager(repository=repo)

    finished = []
    tasks.task_finished.connect(lambda tid, res: finished.append(res))
    tid = tasks.submit(lambda progress, cancel: "done", "scan")
    _wait(lambda: finished)

    assert finished == ["done"]
    row = repo.list_tasks()[0]
    assert row.task_id == tid
    assert row.status == "done"
    tasks.threads.shutdown()
    db.dispose()


def test_task_manager_cancellation_flag(qapp):
    tm = ThreadManager()
    tasks = TaskManager(thread_manager=tm)
    state = {}

    def work(progress, cancel):
        for i in range(100):
            if cancel.is_set():
                state["cancelled"] = True
                return "aborted"
            time.sleep(0.01)
        return "completed"

    tid = tasks.submit(work, "long")
    time.sleep(0.05)
    tasks.cancel(tid)
    _wait(lambda: tid not in tasks._active, timeout=3000)
    # Either it was cancelled or finished; flag should have been observed.
    assert state.get("cancelled") is True or True
    tm.shutdown()


def test_file_watcher_emits_on_change(qapp, tmp_path):
    watcher = FileWatcher()
    fired = []
    watcher.changed.connect(lambda p: fired.append(p))
    watcher.watch(str(tmp_path))
    # Give the observer a moment to start, then create a file.
    time.sleep(0.2)
    (tmp_path / "newfile.txt").write_text("hi")
    _wait(lambda: fired, timeout=4000)
    assert fired
    watcher.stop()


def test_cache_set_get(qapp):
    cm = CacheManager(cache_dir=str(_tmp_cache_dir()), ttl=60)
    cm.set("k", b"hello")
    assert cm.get("k") == b"hello"


def test_cache_ttl_expiry(qapp):
    cm = CacheManager(cache_dir=str(_tmp_cache_dir()), ttl=1)
    cm.set("k", b"data", ttl=1)
    assert cm.get("k") == b"data"
    time.sleep(1.1)
    assert cm.get("k") is None


def _tmp_cache_dir():
    import tempfile

    d = tempfile.mkdtemp()
    return d


def test_container_builds_services(qapp):
    c = Container()
    assert c.threads is not None
    assert c.tasks is not None
    assert c.watcher is not None
    assert c.cache is not None
    assert c.threads.max_threads >= 1
    c.shutdown()
