"""Batch 7 tests — folder intelligence completion (#31) + AI folder summary (B7-8)."""

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
    from database.models import AIAnalysis
    from services.sqlite_indexer import IndexedFile

    now = datetime.now()
    with sf() as s:
        s.add(IndexedFile(
            filename="a.pdf", absolute_path="/ws/sub/a.pdf", size=1000,
            extension=".pdf", checksum="a" * 64,
            created_date=now - timedelta(days=10), modified_date=now - timedelta(days=1),
            indexing_status="completed",
        ))
        s.add(IndexedFile(
            filename="b.txt", absolute_path="/ws/sub/b.txt", size=2000,
            extension=".txt", checksum="b" * 64,
            created_date=now - timedelta(days=5), modified_date=now - timedelta(days=2),
            indexing_status="completed",
        ))
        s.add(IndexedFile(
            filename="c.png", absolute_path="/ws/other/c.png", size=500,
            extension=".png", checksum="c" * 64,
            created_date=now - timedelta(days=1), modified_date=now,
            indexing_status="completed",
        ))
        s.add(AIAnalysis(
            file_hash="a" * 64, normalized_category="document",
            summary="Quarterly report about revenue growth",
            keywords='["revenue","growth"]',
        ))
        s.add(AIAnalysis(
            file_hash="b" * 64, normalized_category="notes",
            summary="Meeting notes project planning",
            keywords='["planning"]',
        ))
        s.commit()


class TestFolderIntelligence:
    def test_stats_under_folder(self, session_factory):
        from services.folder_intelligence_service import FolderIntelligenceService

        _seed(session_factory)
        svc = FolderIntelligenceService(session_factory)
        info = svc.analyze("/ws/sub")
        assert info.total_files == 2
        assert info.total_size == 3000
        assert info.file_type_distribution.get("document", 0) == 2
        assert ".pdf" in info.extension_distribution

    def test_excludes_sibling_folder(self, session_factory):
        from services.folder_intelligence_service import FolderIntelligenceService

        _seed(session_factory)
        svc = FolderIntelligenceService(session_factory)
        info = svc.analyze("/ws/sub")
        assert "c.png" not in str(info.newest_file or "")

    def test_date_range(self, session_factory):
        from services.folder_intelligence_service import FolderIntelligenceService

        _seed(session_factory)
        svc = FolderIntelligenceService(session_factory)
        info = svc.analyze("/ws/sub")
        assert info.date_range  # "YYYY-MM-DD → YYYY-MM-DD"
        assert info.newest_file and info.oldest_file

    def test_categories_and_keywords(self, session_factory):
        from services.folder_intelligence_service import FolderIntelligenceService

        _seed(session_factory)
        svc = FolderIntelligenceService(session_factory)
        info = svc.analyze("/ws/sub")
        assert info.dominant_category in ("document", "notes")
        assert info.top_keywords  # from summaries
        assert info.classified_count == 2

    def test_empty_folder(self, session_factory, tmp_path):
        from services.folder_intelligence_service import FolderIntelligenceService

        svc = FolderIntelligenceService(session_factory)
        info = svc.analyze(str(tmp_path / "empty"))
        assert info.total_files == 0
        assert info.total_size == 0

    def test_to_dict(self, session_factory):
        from services.folder_intelligence_service import FolderIntelligenceService

        _seed(session_factory)
        svc = FolderIntelligenceService(session_factory)
        d = svc.analyze("/ws/sub").to_dict()
        assert d["total_files"] == 2
        assert d["file_type_distribution"]


class TestFolderSummary:
    def test_generate_with_rag(self, session_factory):
        from services.folder_summary_service import FolderSummaryService

        _seed(session_factory)

        class _FakeRag:
            def _generate(self, prompt):
                return "This folder contains quarterly reports and meeting notes."

        svc = FolderSummaryService(
            session_factory=session_factory,
            rag_engine=_FakeRag(),
        )
        summary = svc.generate("/ws/sub")
        assert summary and "reports" in summary

    def test_persist_and_get(self, session_factory):
        from database.models import FolderClassification
        from services.folder_summary_service import FolderSummaryService

        _seed(session_factory)

        class _FakeRag:
            def _generate(self, prompt):
                return "A persisted folder summary."

        svc = FolderSummaryService(session_factory=session_factory, rag_engine=_FakeRag())
        svc.generate("/ws/sub")
        got = svc.get("/ws/sub")
        assert got is not None
        assert got["summary"] == "A persisted folder summary."
        assert got["model"] == "qwen-local:latest"
        with session_factory() as s:
            row = s.query(FolderClassification).filter_by(folder_path="/ws/sub").first()
            assert row.summary is not None

    def test_restart_persistence(self, session_factory, tmp_path):
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker

        from database.models import Base
        from database.migrations import run_migrations
        from services.folder_summary_service import FolderSummaryService

        _seed(session_factory)

        class _FakeRag:
            def _generate(self, prompt):
                return "Survives restart."

        svc = FolderSummaryService(session_factory=session_factory, rag_engine=_FakeRag())
        svc.generate("/ws/sub")

        engine2 = create_engine(session_factory().bind.url, echo=False)
        Base.metadata.create_all(engine2)
        run_migrations(engine2)
        sf2 = sessionmaker(bind=engine2)
        svc2 = FolderSummaryService(session_factory=sf2)
        assert svc2.get("/ws/sub")["summary"] == "Survives restart."
        engine2.dispose()

    def test_no_rag_returns_none(self, session_factory):
        from services.folder_summary_service import FolderSummaryService

        _seed(session_factory)
        svc = FolderSummaryService(session_factory=session_factory, rag_engine=None)
        # Stats exist → no crash; without a generator the summary stays None.
        assert svc.generate("/ws/sub") is None or svc.get("/ws/sub") is None

    def test_rag_failure_handled(self, session_factory):
        from services.folder_summary_service import FolderSummaryService

        _seed(session_factory)

        class _BoomRag:
            def _generate(self, prompt):
                raise RuntimeError("ollama down")

        svc = FolderSummaryService(session_factory=session_factory, rag_engine=_BoomRag())
        assert svc.generate("/ws/sub") is None

    def test_empty_folder_generates_none(self, session_factory, tmp_path):
        from services.folder_summary_service import FolderSummaryService

        svc = FolderSummaryService(session_factory=session_factory, rag_engine=None)
        assert svc.generate(str(tmp_path / "empty")) is None


class TestFolderIntelligenceDialog:
    def test_dialog_constructs(self, qapp, session_factory):
        from services.folder_classification import FolderClassificationService
        from ui.dialogs.folder_intelligence_dialog import FolderIntelligenceDialog

        _seed(session_factory)
        svc = FolderClassificationService(session_factory)
        dlg = FolderIntelligenceDialog("/ws/sub", svc)
        dlg.close()

    def test_dialog_with_stats_and_summary(self, qapp, session_factory):
        from services.folder_classification import FolderClassificationService
        from services.folder_intelligence_service import FolderIntelligenceService
        from services.folder_summary_service import FolderSummaryService
        from ui.dialogs.folder_intelligence_dialog import FolderIntelligenceDialog

        _seed(session_factory)

        class _FakeRag:
            def _generate(self, prompt):
                return "Folder summary text."

        cls = FolderClassificationService(session_factory)
        intel = FolderIntelligenceService(session_factory)
        summ = FolderSummaryService(session_factory=session_factory, rag_engine=_FakeRag())
        dlg = FolderIntelligenceDialog("/ws/sub", cls)
        dlg.set_intelligence_service(intel)
        dlg.set_summary_service(summ)
        dlg.refresh()
        assert "Total files: 2" in dlg.stats_label.text()
        assert "No AI summary" in dlg.ai_summary_label.text()
        dlg.close()
