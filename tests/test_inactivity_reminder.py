"""Unit tests for Inactivity Reminder Service & Database Tracking."""

import os
import tempfile
from datetime import datetime, timedelta
import pytest


def test_inactivity_reminder_service(tmp_path):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from database.models import Base
    from database.migrations import run_migrations
    from services.sqlite_indexer import IndexedFile
    from services.inactivity_reminder_service import InactivityReminderService

    # 1. Setup DB
    engine = create_engine(f"sqlite:///{tmp_path / 'test_inactivity.db'}", echo=False)
    Base.metadata.create_all(engine)
    run_migrations(engine)
    sf = sessionmaker(bind=engine)

    # 2. Create test files on disk
    old_file = tmp_path / "old_doc.pdf"
    new_file = tmp_path / "new_doc.pdf"
    old_file.write_text("Old document content")
    new_file.write_text("New document content")

    now = datetime.utcnow()
    twenty_days_ago = now - timedelta(days=20)
    two_days_ago = now - timedelta(days=2)

    with sf() as session:
        session.add(IndexedFile(
            filename="old_doc.pdf",
            absolute_path=str(old_file),
            size=20,
            scan_timestamp=twenty_days_ago,
            created_date=twenty_days_ago,
            indexing_status="completed",
        ))
        session.add(IndexedFile(
            filename="new_doc.pdf",
            absolute_path=str(new_file),
            size=20,
            scan_timestamp=two_days_ago,
            created_date=two_days_ago,
            indexing_status="completed",
        ))
        session.commit()

    service = InactivityReminderService(session_factory=sf)

    # 3. Query inactive files with threshold of 14 days
    inactive = service.find_inactive_files(threshold_days=14)
    assert len(inactive) == 1
    assert inactive[0].file_name == "old_doc.pdf"
    assert inactive[0].days_inactive >= 20

    # 4. Mark old_doc.pdf as opened today
    service.mark_file_opened(str(old_file))

    # 5. Query again — should be empty since old_doc was opened today
    inactive_after = service.find_inactive_files(threshold_days=14)
    assert len(inactive_after) == 0

    engine.dispose()
