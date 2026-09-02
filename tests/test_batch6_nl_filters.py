"""Batch 6 §8.8 — natural-language filter parser tests (B6-03 / #18).

Pure parser tests (no DB, no Qt). Verify type / extension / date / size /
scope extraction and — critically — that unknown text stays in the semantic
query (ambiguity rule B6 §8.7).
"""

import os
import sys
from datetime import date, datetime, timedelta

import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from services.nl_filter_parser import describe_filters, parse_query  # noqa: E402


class TestTypeAndExtensionFilters:
    def test_pdf_files(self):
        p = parse_query("PDF files about machine learning")
        assert "pdf" in p.types
        assert ".pdf" in p.extensions
        assert "machine learning" in p.semantic_query

    def test_image_words(self):
        p = parse_query("show me images of the ocean")
        assert "image" in p.types
        assert ".png" in p.extensions  # image extension map applied
        assert "ocean" in p.semantic_query

    def test_explicit_extension(self):
        p = parse_query("find .docx contracts")
        assert ".docx" in p.extensions
        assert "contracts" in p.semantic_query

    def test_generic_type_suppressed_by_specific(self):
        # "PDF files" must NOT pull in every document extension.
        p = parse_query("PDF files about machine learning")
        assert ".pdf" in p.extensions
        assert ".txt" not in p.extensions
        assert ".docx" not in p.extensions

    def test_multiple_filters(self):
        p = parse_query("PDF or DOCX documents about taxes")
        assert set(p.extensions) >= {".pdf", ".docx"}
        assert "taxes" in p.semantic_query

    def test_video_and_audio(self):
        p = parse_query("find videos of the launch")
        assert "video" in p.types
        p2 = parse_query("podcasts about space")
        assert "audio" in p2.types


class TestDateFilters:
    def test_this_month(self):
        p = parse_query("documents modified this month")
        assert p.modified_after is not None
        assert p.modified_after.date() == date.today().replace(day=1)

    def test_yesterday(self):
        p = parse_query("images from yesterday")
        assert p.modified_after is not None
        assert p.modified_after.date() == date.today() - timedelta(days=1)

    def test_this_week(self):
        p = parse_query("files changed this week")
        assert p.modified_after is not None
        assert p.modified_after.date() == date.today() - timedelta(days=date.today().weekday())

    def test_absolute_after(self):
        p = parse_query("documents after 2024-01-15")
        assert p.modified_after is not None
        assert p.modified_after.date() == date(2024, 1, 15)

    def test_absolute_before(self):
        p = parse_query("documents before 2023-06-01")
        assert p.modified_before is not None
        assert p.modified_before.date() == date(2023, 6, 1)


class TestSizeFilters:
    def test_larger_than(self):
        p = parse_query("files larger than 5 MB")
        assert p.size_min == 5 * 1024 * 1024

    def test_smaller_than(self):
        p = parse_query("documents smaller than 2 MB")
        assert p.size_max == 2 * 1024 * 1024

    def test_between(self):
        p = parse_query("files between 1 MB and 5 MB")
        assert p.size_min == 1 * 1024 * 1024
        assert p.size_max == 5 * 1024 * 1024

    def test_gb_unit(self):
        p = parse_query("videos larger than 1 GB")
        assert p.size_min == 1024 ** 3


class TestScopeAndSemanticPreservation:
    def test_folder_scope(self):
        p = parse_query("find notes in this folder")
        assert p.scope == "folder"

    def test_workspace_scope(self):
        p = parse_query("search all files in this workspace")
        assert p.scope == "workspace"

    def test_plain_query_unchanged(self):
        p = parse_query("machine learning")
        assert p.semantic_query == "machine learning"
        assert not p.has_filters

    def test_ambiguous_phrase_kept(self):
        # "about" stays in the semantic text when nothing else is parsed.
        p = parse_query("notes about quantum physics")
        assert "quantum physics" in p.semantic_query
        assert not p.has_filters

    def test_invalid_size_kept_in_semantic(self):
        p = parse_query("files larger than ten megabytes")
        # "ten" is not a number → nothing parsed → no filter applied.
        assert not p.has_filters or p.size_min is None

    def test_duplicate_intent(self):
        p = parse_query("find duplicate copies of reports")
        assert p.near_duplicate is True

    def test_describe_filters(self):
        p = parse_query("PDF files larger than 5 MB modified this month")
        parts = describe_filters(p)
        joined = " ".join(parts).lower()
        assert "pdf" in joined
        assert "5.0 mb" in joined
        assert "modified" in joined

    def test_combined_query(self):
        p = parse_query("PDF files about machine learning modified this month larger than 5 MB")
        assert "machine learning" in p.semantic_query
        assert ".pdf" in p.extensions
        assert p.size_min == 5 * 1024 * 1024
        assert p.modified_after is not None
        assert p.has_filters


class TestMetadataFilterApplication:
    """Integration: the MainWindow metadata-filter helper narrows retrieval
    results using the Batch-1 index (B6 §8.5 step 3)."""

    def test_extension_and_size_filters(self, qapp, monkeypatch, tmp_path):
        from types import SimpleNamespace

        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker

        from app.container import Container
        from database.models import Base
        from database.migrations import run_migrations
        from services.sqlite_indexer import IndexedFile
        from ui.main_window import MainWindow

        engine = create_engine(f"sqlite:///{tmp_path / 't.db'}", echo=False)
        Base.metadata.create_all(engine)
        run_migrations(engine)
        Session = sessionmaker(bind=engine)
        sf = Session
        with sf() as s:
            s.add(IndexedFile(
                filename="big.pdf", absolute_path="/ws/big.pdf",
                size=10 * 1024 * 1024, extension=".pdf",
                checksum="a" * 64, indexing_status="completed",
            ))
            s.add(IndexedFile(
                filename="small.txt", absolute_path="/ws/small.txt",
                size=1000, extension=".txt",
                checksum="b" * 64, indexing_status="completed",
            ))
            s.commit()

        container = Container()
        monkeypatch.setattr(container.db, "session", sf)
        w = MainWindow(container)
        try:
            parsed = parse_query("PDF files larger than 5 MB")
            results = [
                SimpleNamespace(file_path="/ws/big.pdf"),
                SimpleNamespace(file_path="/ws/small.txt"),
            ]
            filtered = w._apply_search_metadata_filters(results, parsed, "")
            assert [r.file_path for r in filtered] == ["/ws/big.pdf"]
        finally:
            w.close()
            engine.dispose()

    def test_folder_scope_filter(self, qapp, monkeypatch, tmp_path):
        from types import SimpleNamespace

        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker

        from app.container import Container
        from database.models import Base
        from database.migrations import run_migrations
        from services.sqlite_indexer import IndexedFile
        from ui.main_window import MainWindow

        engine = create_engine(f"sqlite:///{tmp_path / 't2.db'}", echo=False)
        Base.metadata.create_all(engine)
        run_migrations(engine)
        Session = sessionmaker(bind=engine)
        sf = Session
        with sf() as s:
            s.add(IndexedFile(
                filename="a.txt", absolute_path="/ws/sub/a.txt", size=5,
                extension=".txt", checksum="c" * 64, indexing_status="completed",
            ))
            s.add(IndexedFile(
                filename="b.txt", absolute_path="/other/b.txt", size=5,
                extension=".txt", checksum="d" * 64, indexing_status="completed",
            ))
            s.commit()

        container = Container()
        monkeypatch.setattr(container.db, "session", sf)
        w = MainWindow(container)
        try:
            parsed = parse_query("find notes in this folder")
            results = [
                SimpleNamespace(file_path="/ws/sub/a.txt"),
                SimpleNamespace(file_path="/other/b.txt"),
            ]
            filtered = w._apply_search_metadata_filters(results, parsed, "/ws")
            assert [r.file_path for r in filtered] == ["/ws/sub/a.txt"]
        finally:
            w.close()
            engine.dispose()
