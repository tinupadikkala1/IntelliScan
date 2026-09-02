"""Batch 7 tests — file timeline (B7-7)."""

import os
import sys
from datetime import datetime, timedelta

import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)


@pytest.fixture
def session_factory(tmp_path):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from database.models import Base
    from database.migrations import run_migrations

    engine = create_engine(f"sqlite:///{tmp_path / 't.db'}", echo=False)
    Base.metadata.create_all(engine)
    run_migrations(engine)
    sf = sessionmaker(bind=engine)
    yield sf
    engine.dispose()


def _seed(sf):
    from database.models import Recent
    from services.sqlite_indexer import IndexedFile

    now = datetime.now()
    with sf() as s:
        s.add(IndexedFile(
            filename="old.pdf", absolute_path="/ws/old.pdf", size=10,
            extension=".pdf", checksum="a" * 64,
            created_date=now - timedelta(days=60),
            modified_date=now - timedelta(days=30),
            indexing_status="completed",
        ))
        s.add(IndexedFile(
            filename="new.txt", absolute_path="/ws/new.txt", size=5,
            extension=".txt", checksum="b" * 64,
            created_date=now - timedelta(days=2),
            modified_date=now - timedelta(hours=5),
            indexing_status="completed",
        ))
        s.add(Recent(path="/ws/old.pdf", name="old.pdf", opened=now - timedelta(days=1)))
        s.add(Recent(path="/ws/new.txt", name="new.txt", opened=now - timedelta(hours=2)))
        s.commit()


class TestTimeline:
    def test_events_ordered_newest_first(self, session_factory):
        from services.timeline_service import TimelineService

        _seed(session_factory)
        svc = TimelineService(session_factory)
        events = svc.events(days=90)
        assert len(events) >= 4  # 2 created + 2 modified + 2 opened
        times = [e["time"] for e in events]
        assert times == sorted(times, reverse=True)

    def test_kinds(self, session_factory):
        from services.timeline_service import TimelineService

        _seed(session_factory)
        svc = TimelineService(session_factory)
        created = svc.events(days=90, kinds=["created"])
        assert all(e["kind"] == "created" for e in created)
        opened = svc.events(days=90, kinds=["opened"])
        assert all(e["kind"] == "opened" for e in opened)
        assert len(opened) == 2

    def test_extension_filter(self, session_factory):
        from services.timeline_service import TimelineService

        _seed(session_factory)
        svc = TimelineService(session_factory)
        pdfs = svc.events(days=90, extension=".pdf")
        assert pdfs
        assert all(e["extension"] == ".pdf" for e in pdfs)
        assert all("new.txt" not in e["filename"] for e in pdfs)

    def test_folder_filter(self, session_factory):
        from services.timeline_service import TimelineService

        _seed(session_factory)
        svc = TimelineService(session_factory)
        other = svc.events(days=90, folder="/other")
        assert other == []
        ws = svc.events(days=90, folder="/ws")
        assert ws

    def test_days_window(self, session_factory):
        from services.timeline_service import TimelineService

        _seed(session_factory)
        svc = TimelineService(session_factory)
        recent = svc.events(days=7)
        # old.pdf created 60d ago must be excluded within 7-day window.
        filenames = [e["filename"] for e in recent]
        assert "old.pdf" not in filenames or all(
            e["kind"] != "created" for e in recent if e["filename"] == "old.pdf"
        )

    def test_grouped(self, session_factory):
        from services.timeline_service import TimelineService

        _seed(session_factory)
        svc = TimelineService(session_factory)
        groups = svc.grouped(days=90)
        assert groups
        assert groups[0]["day"] >= groups[-1]["day"]
        assert sum(g["count"] for g in groups) == len(svc.events(days=90))

    def test_stats(self, session_factory):
        from services.timeline_service import TimelineService

        _seed(session_factory)
        svc = TimelineService(session_factory)
        stats = svc.stats(days=90)
        assert stats["total"] >= 4
        assert stats["by_kind"].get("opened", 0) == 2

    def test_empty_database(self, session_factory):
        from services.timeline_service import TimelineService

        svc = TimelineService(session_factory)
        assert svc.events(days=90) == []
        assert svc.grouped(days=90) == []

    def test_no_fabrication(self, session_factory):
        """Only recorded events appear — never invented ones."""
        from services.timeline_service import TimelineService

        svc = TimelineService(session_factory)
        assert svc.events(days=365 * 5) == []  # no rows → no events


class TestTimelineDialog:
    def test_dialog_constructs(self, qapp, session_factory):
        from services.timeline_service import TimelineService
        from ui.dialogs.timeline_dialog import TimelineDialog

        _seed(session_factory)
        svc = TimelineService(session_factory)
        dlg = TimelineDialog(svc)
        assert dlg.list_widget.count() > 0
        dlg.close()

    def test_dialog_refresh_with_kind_filter(self, qapp, session_factory):
        from services.timeline_service import TimelineService
        from ui.dialogs.timeline_dialog import TimelineDialog

        _seed(session_factory)
        svc = TimelineService(session_factory)
        dlg = TimelineDialog(svc)
        idx = dlg.kind_combo.findText("Opened")
        dlg.kind_combo.setCurrentIndex(idx)
        dlg.refresh()
        # Opened-only view: still shows the 2 Recent rows + day headers.
        assert dlg.list_widget.count() >= 2
        dlg.close()
