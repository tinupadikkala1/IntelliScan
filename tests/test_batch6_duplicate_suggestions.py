"""Batch 6 §9.7 — smart duplicate removal suggestion tests (B6-04 / #25).

Covers: exact-duplicate recommendation, near-duplicate recommendation,
keep-copy selection heuristics, confidence, accept → reversible trash,
dismiss, safety (no unapproved deletion, invalid target, missing file,
same-path rejection, stale suggestion).
"""

import os
import shutil
import sys
from contextlib import contextmanager

import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

_EMPTY_HASH = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"


@contextmanager
def _db_session_factory(tmp_path, name="test_b6_dup.db"):
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


def _indexed_record(session, path, checksum, size=10, ext=".txt", filename=None):
    from services.sqlite_indexer import IndexedFile
    session.add(IndexedFile(
        filename=filename or os.path.basename(path),
        absolute_path=path,
        size=size,
        mime_type="text/plain",
        extension=ext,
        checksum=checksum,
        extracted_text="content",
        indexing_status="completed",
    ))


def _engine_and_groups(tmp_path, files, empty_visible=True):
    """Index files (same checksum) and return (SuggestionEngine, groups)."""
    from engines.duplicate_engine import DuplicateEngine
    from services.batch5_store import Batch5Store
    from services.suggestion_engine import SuggestionEngine

    with _db_session_factory(tmp_path) as sf:
        with sf() as s:
            for f in files:
                if os.path.isfile(f):
                    _indexed_record(s, f, "c" * 64, size=os.path.getsize(f))
                else:
                    _indexed_record(s, f, _EMPTY_HASH, size=0)
            s.commit()
        de = DuplicateEngine(sf, empty_visible=empty_visible)
        groups = de.find_exact_duplicates()
        store = Batch5Store(sf)
        engine = SuggestionEngine(store=store, session_factory=sf)
        return sf, store, engine, groups


class TestRemovalRecommendation:
    def test_keep_canonical_remove_copy(self, tmp_path):
        orig = tmp_path / "report.txt"
        orig.write_text("same content here")
        copy = tmp_path / "report - copy.txt"
        shutil.copy2(orig, copy)
        sf, store, engine, groups = _engine_and_groups(tmp_path, [str(orig), str(copy)])
        sugs = engine.suggest_duplicate_removals(groups)
        assert sugs, "expected a removal suggestion"
        s = sugs[0]
        assert os.path.basename(s.keep_path) == "report.txt"
        assert os.path.basename(s.remove_path) == "report - copy.txt"
        assert s.duplicate_type == "exact"
        assert s.confidence >= 0.55
        assert "Identical content" in s.reason

    def test_no_duplicates_no_suggestions(self, tmp_path):
        with _db_session_factory(tmp_path) as sf:
            from services.batch5_store import Batch5Store
            from services.suggestion_engine import SuggestionEngine

            engine = SuggestionEngine(store=Batch5Store(sf), session_factory=sf)
            assert engine.suggest_duplicate_removals([]) == []

    def test_keep_newest_when_names_identical(self, tmp_path):
        dir_a = tmp_path / "a"
        dir_b = tmp_path / "b"
        dir_a.mkdir(); dir_b.mkdir()
        a = dir_a / "data.txt"
        b = dir_b / "data.txt"
        a.write_text("x")
        shutil.copy2(a, b)
        os.utime(b, (os.path.getmtime(a) + 100, os.path.getmtime(a) + 100))
        sf, store, engine, groups = _engine_and_groups(tmp_path, [str(a), str(b)])
        sugs = engine.suggest_duplicate_removals(groups)
        assert sugs
        s = sugs[0]
        # The kept copy must be the newer one when both names are identical.
        assert os.path.getmtime(s.keep_path) >= os.path.getmtime(s.remove_path)

    def test_near_duplicate_pairs(self, tmp_path):
        from services.batch5_store import Batch5Store
        from services.suggestion_engine import SuggestionEngine

        with _db_session_factory(tmp_path) as sf:
            engine = SuggestionEngine(store=Batch5Store(sf), session_factory=sf)
            a = tmp_path / "a.txt"; a.write_text("aa")
            b = tmp_path / "b.txt"; b.write_text("bb")
            sugs = engine.suggest_near_duplicate_removals([(str(a), str(b), 0.93)])
            assert sugs
            assert sugs[0].duplicate_type == "near"
            assert sugs[0].confidence >= 0.85

    def test_low_similarity_rejected(self, tmp_path):
        from services.batch5_store import Batch5Store
        from services.suggestion_engine import SuggestionEngine

        with _db_session_factory(tmp_path) as sf:
            engine = SuggestionEngine(store=Batch5Store(sf), session_factory=sf)
            a = tmp_path / "a.txt"; a.write_text("aa")
            b = tmp_path / "b.txt"; b.write_text("bb")
            sugs = engine.suggest_near_duplicate_removals([(str(a), str(b), 0.60)])
            assert sugs == []


class TestRemovalExecutionSafety:
    def test_accept_moves_to_trash(self, tmp_path):
        orig = tmp_path / "report.txt"
        orig.write_text("same content here")
        copy = tmp_path / "report - copy.txt"
        shutil.copy2(orig, copy)
        sf, store, engine, groups = _engine_and_groups(tmp_path, [str(orig), str(copy)])
        sugs = engine.suggest_duplicate_removals(groups)
        s = sugs[0]
        result = engine.accept_duplicate_removal(s.id)
        assert result["ok"] is True
        assert not os.path.exists(s.remove_path), "file must leave its original location"
        assert os.path.exists(result["trash_path"]), "file must exist in reversible trash"
        assert store.get_duplicate_suggestion(s.id).status == "executed"
        assert os.path.exists(s.keep_path), "kept copy untouched"

    def test_dismiss_does_not_touch_file(self, tmp_path):
        orig = tmp_path / "report.txt"
        orig.write_text("same content here")
        copy = tmp_path / "report - copy.txt"
        shutil.copy2(orig, copy)
        sf, store, engine, groups = _engine_and_groups(tmp_path, [str(orig), str(copy)])
        sugs = engine.suggest_duplicate_removals(groups)
        s = sugs[0]
        assert engine.dismiss_duplicate_removal(s.id) is True
        assert os.path.exists(s.remove_path), "dismiss must not move the file"
        assert store.get_duplicate_suggestion(s.id).status == "dismissed"

    def test_no_suggestion_never_deletes(self, tmp_path):
        orig = tmp_path / "only.txt"
        orig.write_text("single file")
        sf, store, engine, groups = _engine_and_groups(tmp_path, [str(orig)])
        assert engine.suggest_duplicate_removals(groups) == []
        assert os.path.exists(orig)

    def test_missing_remove_file_graceful(self, tmp_path):
        from services.batch5_store import Batch5Store
        from services.suggestion_engine import SuggestionEngine

        with _db_session_factory(tmp_path) as sf:
            store = Batch5Store(sf)
            keep = tmp_path / "keep.txt"; keep.write_text("k")
            remove = tmp_path / "remove.txt"  # does not exist
            sid = store.create_duplicate_suggestion(
                group_checksum="d" * 64, keep_path=str(keep),
                remove_path=str(remove), confidence=0.9,
            )
            engine = SuggestionEngine(store=store, session_factory=sf)
            result = engine.accept_duplicate_removal(sid)
            assert result["ok"] is False
            assert store.get_duplicate_suggestion(sid).status == "expired"

    def test_same_path_rejected(self, tmp_path):
        from services.batch5_store import Batch5Store
        from services.suggestion_engine import SuggestionEngine

        with _db_session_factory(tmp_path) as sf:
            store = Batch5Store(sf)
            f = tmp_path / "x.txt"; f.write_text("x")
            sid = store.create_duplicate_suggestion(
                group_checksum="d" * 64, keep_path=str(f),
                remove_path=str(f), confidence=0.9,
            )
            engine = SuggestionEngine(store=store, session_factory=sf)
            result = engine.accept_duplicate_removal(sid)
            assert result["ok"] is False
            assert os.path.exists(f)

    def test_already_executed_rejected(self, tmp_path):
        orig = tmp_path / "report.txt"
        orig.write_text("same content here")
        copy = tmp_path / "report - copy.txt"
        shutil.copy2(orig, copy)
        sf, store, engine, groups = _engine_and_groups(tmp_path, [str(orig), str(copy)])
        sugs = engine.suggest_duplicate_removals(groups)
        s = sugs[0]
        assert engine.accept_duplicate_removal(s.id)["ok"] is True
        result = engine.accept_duplicate_removal(s.id)
        assert result["ok"] is False  # already executed

    def test_removal_updates_index(self, tmp_path):
        """After approval, the removed file is gone from the duplicate query."""
        from services.sqlite_indexer import IndexedFile

        orig = tmp_path / "report.txt"
        orig.write_text("same content here")
        copy = tmp_path / "report - copy.txt"
        shutil.copy2(orig, copy)
        sf, store, engine, groups = _engine_and_groups(tmp_path, [str(orig), str(copy)])
        sugs = engine.suggest_duplicate_removals(groups)
        engine.accept_duplicate_removal(sugs[0].id)
        with sf() as s:
            remaining = s.query(IndexedFile).filter(
                IndexedFile.absolute_path == str(copy)
            ).count()
        assert remaining == 0, "indexed row for the removed copy must be cleaned up"


class TestDuplicateDialog:
    def test_dialog_renders_with_suggestion(self, qapp, qtbot, tmp_path):
        from services.batch5_models import DuplicateGroup, DuplicateRemovalSuggestion
        from ui.dialogs.duplicate_dialog import DuplicateDialog

        g = DuplicateGroup(checksum="c" * 64, files=[str(tmp_path / "a.txt"), str(tmp_path / "b.txt")])
        s = DuplicateRemovalSuggestion(
            id=1, group_checksum="c" * 64, keep_path=str(tmp_path / "a.txt"),
            remove_path=str(tmp_path / "b.txt"), confidence=0.82,
            reason="Identical content (same SHA-256)",
        )
        dlg = DuplicateDialog([g], removal_suggestions=[s])
        qtbot.addWidget(dlg)
        assert dlg.accept_removal_btn.isEnabled()
        assert "a.txt" in dlg.suggestion_box.text()
        dlg.close()

    def test_dialog_no_suggestion(self, qapp, qtbot, tmp_path):
        from services.batch5_models import DuplicateGroup
        from ui.dialogs.duplicate_dialog import DuplicateDialog

        g = DuplicateGroup(checksum="c" * 64, files=[str(tmp_path / "a.txt")])
        dlg = DuplicateDialog([g])
        qtbot.addWidget(dlg)
        assert not dlg.accept_removal_btn.isEnabled()
        dlg.close()
