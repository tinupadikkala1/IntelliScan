"""Batch 6 §7.7 — AI folder classification tests (B6-02 / #16).

Folder summaries are aggregated from existing per-file classifications and
deterministic extension fallback (never per-file LLM calls). Covers: empty
folder, single-category, mixed, unclassified fallback, persistence, refresh
after add/delete, and restart persistence.
"""

import os
import sys
from contextlib import contextmanager

import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)


@contextmanager
def _db_session_factory(tmp_path, name="test_b6_folder.db"):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from database.models import Base
    from database.migrations import run_migrations

    engine = create_engine(f"sqlite:///{tmp_path / name}", echo=False)
    Base.metadata.create_all(engine)
    run_migrations(engine)
    Session = sessionmaker(bind=engine)

    def session_ctx():
        return Session()

    yield session_ctx
    engine.dispose()


def _index(tmp_path, session_factory, files):
    """Index real files through the Batch-1 pipeline; returns path list."""
    from services.folder_scanner import DiscoveredItem
    from services.metadata_extractor import MetadataExtractor
    from services.text_extractor import TextExtractor
    from services.sqlite_indexer import SQLiteIndexer

    items = []
    for f in files:
        f.write_text("some content " + f.name, encoding="utf-8")
        st = os.stat(f)
        items.append(DiscoveredItem(
            path=str(f), name=f.name, parent=str(f.parent),
            size=st.st_size, modified=None, is_dir=False,
        ))
    md = MetadataExtractor()
    tx = TextExtractor()
    idx = SQLiteIndexer(session_factory)
    idx.index_items(items, md.process_items(items), tx.process_items(items))
    return [str(f) for f in files]


class TestFolderClassification:
    def _service(self, session_factory):
        from services.folder_classification import FolderClassificationService
        return FolderClassificationService(session_factory=session_factory)

    def test_empty_folder(self, tmp_path):
        from services.folder_classification import FolderClassificationService

        with _db_session_factory(tmp_path) as sf:
            svc = FolderClassificationService(session_factory=sf)
            folder = tmp_path / "empty"
            folder.mkdir()
            info = svc.classify_folder(str(folder))
            assert info.total_files == 0
            assert info.dominant_category in ("", "other")

    def test_single_category_folder(self, tmp_path):
        with _db_session_factory(tmp_path) as sf:
            folder = tmp_path / "ws"
            folder.mkdir()
            _index(tmp_path, sf, [folder / "a.txt", folder / "b.md", folder / "c.log"])
            info = self._service(sf).classify_folder(str(folder))
            assert info.total_files == 3
            assert info.dominant_category == "document"
            assert info.distribution.get("document", 0) >= 3

    def test_mixed_folder_distribution(self, tmp_path):
        with _db_session_factory(tmp_path) as sf:
            folder = tmp_path / "ws"
            folder.mkdir()
            _index(tmp_path, sf, [
                folder / "a.txt", folder / "b.pdf",
                folder / "code.py", folder / "s.rb",
                folder / "pic.png",
            ])
            info = self._service(sf).classify_folder(str(folder))
            assert info.total_files == 5
            assert info.distribution.get("document", 0) == 2
            assert info.distribution.get("code", 0) == 2
            assert info.distribution.get("image", 0) == 1
            assert info.dominant_category == "document"

    def test_persisted_and_restart(self, tmp_path):
        with _db_session_factory(tmp_path) as sf1:
            folder = tmp_path / "ws"
            folder.mkdir()
            _index(tmp_path, sf1, [folder / "a.txt", folder / "b.pdf"])
            svc = self._service(sf1)
            info = svc.classify_folder(str(folder))
            assert info.dominant_category == "document"
        # "Restart": fresh engine + session over the same DB file.
        with _db_session_factory(tmp_path) as sf2:
            svc = self._service(sf2)
            loaded = svc.get(str(folder))
            assert loaded is not None
            assert loaded.dominant_category == "document"
            assert loaded.total_files == 2

    def test_add_file_updates_summary(self, tmp_path):
        with _db_session_factory(tmp_path) as sf:
            folder = tmp_path / "ws"
            folder.mkdir()
            _index(tmp_path, sf, [folder / "a.txt"])
            svc = self._service(sf)
            assert svc.classify_folder(str(folder)).total_files == 1
            _index(tmp_path, sf, [folder / "b.py", folder / "c.py"])
            refreshed = svc.classify_folder(str(folder))
            assert refreshed.total_files == 3
            assert refreshed.distribution.get("code", 0) == 2

    def test_ai_classifications_used_when_present(self, tmp_path):
        from services.classification_engine import ClassificationEngine

        with _db_session_factory(tmp_path) as sf:
            folder = tmp_path / "ws"
            folder.mkdir()
            paths = _index(tmp_path, sf, [folder / "mystery.zzz"])
            # Deterministic extension would be "other"; AI classification
            # (simulated via the classification engine) overrides.
            engine = ClassificationEngine(session_factory=sf)
            engine.classify_file(paths[0])  # falls back to extension → other
            # Force a research classification directly.
            from database.models import AIAnalysis
            from services.file_identity import calculate_sha256
            with sf() as s:
                row = s.query(AIAnalysis).filter_by(
                    file_hash=calculate_sha256(paths[0])
                ).first()
                row.normalized_category = "research"
                row.classification_version = "1.0"
                s.commit()
            info = self._service(sf).classify_folder(str(folder))
            assert info.dominant_category == "research"

    def test_folder_intelligence_dialog(self, qapp, qtbot, tmp_path):
        from ui.dialogs.folder_intelligence_dialog import FolderIntelligenceDialog
        from services.folder_classification import FolderClassificationService

        with _db_session_factory(tmp_path) as sf:
            folder = tmp_path / "ws"
            folder.mkdir()
            _index(tmp_path, sf, [folder / "a.txt", folder / "b.pdf"])
            svc = FolderClassificationService(session_factory=sf)
            dlg = FolderIntelligenceDialog(str(folder), service=svc)
            qtbot.addWidget(dlg)
            assert "document" in dlg.summary_label.text()
            assert "Category Distribution" in dlg.distribution_label.text()
            dlg.close()
