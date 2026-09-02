"""Batch 7 tests — automatic file renaming (B7-9).

Validates suggestion generation, safety rules, and the approved rename
execution path (file_mover.rename_file) with full multi-layer sync.
"""

import os
import sys

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


def _seed_meta(sf, path, checksum, category="document", tags=None, caption="", title=""):
    from database.models import AIAnalysis
    from services.sqlite_indexer import IndexedFile

    import json
    with sf() as s:
        s.add(IndexedFile(
            filename=os.path.basename(path), absolute_path=path, size=10,
            extension=os.path.splitext(path)[1], checksum=checksum,
            indexing_status="completed",
            user_metadata_json=json.dumps({"title": title}) if title else None,
        ))
        s.add(AIAnalysis(
            file_hash=checksum,
            normalized_category=category or None,
            normalized_tags=json.dumps(tags or []),
            caption=caption or None,
        ))
        s.commit()


class TestRenameSuggestion:
    def test_suggest_uses_category_and_title(self, session_factory, tmp_path):
        from services.rename_suggestion_service import RenameSuggestionService

        path = str(tmp_path / "report v2.pdf")
        _seed_meta(session_factory, path, "a" * 64, category="document",
                   tags=["finance"], title="Annual Report")
        svc = RenameSuggestionService(session_factory)
        sug = svc.suggest(path)
        assert sug.proposed_name.lower().startswith("document_annual report".lower()) or \
            "annual report" in sug.proposed_name.lower()
        assert sug.proposed_name.endswith(".pdf")
        assert sug.is_valid()

    def test_extension_preserved(self, session_factory, tmp_path):
        from services.rename_suggestion_service import RenameSuggestionService

        path = str(tmp_path / "notes.txt")
        _seed_meta(session_factory, path, "b" * 64, category="notes", title="My Notes")
        svc = RenameSuggestionService(session_factory)
        sug = svc.suggest(path)
        assert sug.proposed_name.endswith(".txt")

    def test_caption_as_title_fallback(self, session_factory, tmp_path):
        from services.rename_suggestion_service import RenameSuggestionService

        path = str(tmp_path / "img.png")
        _seed_meta(session_factory, path, "c" * 64, category="image",
                   caption="A red car on a road")
        svc = RenameSuggestionService(session_factory)
        sug = svc.suggest(path)
        assert "car" in sug.proposed_name.lower()

    def test_validate_empty_name(self):
        from services.rename_suggestion_service import RenameSuggestionService

        svc = RenameSuggestionService(session_factory=None)
        assert svc.validate("/tmp/a.txt", "")  # non-empty error list

    def test_validate_forbidden_chars(self):
        from services.rename_suggestion_service import RenameSuggestionService

        svc = RenameSuggestionService(session_factory=None)
        assert svc.validate("/tmp/a.txt", "bad/name.txt")
        assert svc.validate("/tmp/a.txt", "bad\\name.txt")

    def test_validate_extension_change(self):
        from services.rename_suggestion_service import RenameSuggestionService

        svc = RenameSuggestionService(session_factory=None)
        assert svc.validate("/tmp/a.pdf", "new.txt")
        assert svc.validate("/tmp/a.txt", "new.pdf")

    def test_validate_same_name(self):
        from services.rename_suggestion_service import RenameSuggestionService

        svc = RenameSuggestionService(session_factory=None)
        assert svc.validate("/tmp/a.txt", "a.txt")

    def test_validate_length(self):
        from services.rename_suggestion_service import RenameSuggestionService

        svc = RenameSuggestionService(session_factory=None)
        assert svc.validate("/tmp/a.txt", "x" * 300 + ".txt")

    def test_validate_collision(self, tmp_path):
        from services.rename_suggestion_service import RenameSuggestionService

        (tmp_path / "exists.txt").write_text("x")
        svc = RenameSuggestionService(session_factory=None)
        assert svc.validate(str(tmp_path / "a.txt"), "exists.txt")

    def test_valid_name_passes(self, tmp_path):
        from services.rename_suggestion_service import RenameSuggestionService

        (tmp_path / "a.txt").write_text("x")
        svc = RenameSuggestionService(session_factory=None)
        assert svc.validate(str(tmp_path / "a.txt"), "new name.txt") == []

    def test_unsafe_characters_stripped_from_token(self):
        from services.rename_suggestion_service import RenameSuggestionService

        svc = RenameSuggestionService(session_factory=None)
        assert "/" not in svc._safe_token("a/b:c")

    def test_suggest_from_content_with_llm(self, tmp_path):
        from unittest.mock import MagicMock
        from services.rename_suggestion_service import RenameSuggestionService

        doc_file = tmp_path / "notes.txt"
        doc_file.write_text("This is a comprehensive summary of the 2026 Q2 financial budget report.")

        mock_rag = MagicMock()
        mock_rag._generate.return_value = "2026_Q2_Financial_Budget"

        svc = RenameSuggestionService(session_factory=None, rag_engine=mock_rag)
        sug = svc.suggest_from_content(str(doc_file))

        assert sug.is_valid()
        assert sug.proposed_name == "2026_Q2_Financial_Budget.txt"
        assert sug.reason == "AI LLM Content Summarization"

    def test_suggest_from_content_fallback_when_no_llm(self, session_factory, tmp_path):
        from services.rename_suggestion_service import RenameSuggestionService

        path = str(tmp_path / "report.pdf")
        _seed_meta(session_factory, path, "d" * 64, category="report", title="Sales Report")
        svc = RenameSuggestionService(session_factory=session_factory, rag_engine=None)
        sug = svc.suggest_from_content(path)

        assert sug.is_valid()
        assert sug.proposed_name.endswith(".pdf")



class TestRenameExecution:
    def test_rename_preserves_sha256_and_syncs(self, session_factory, tmp_path):
        from pathlib import Path as _Path
        from database.models import FileRelationship
        from services.file_identity import calculate_sha256
        from services.file_mover import rename_file

        src_path = tmp_path / "old name.txt"
        src_path.write_text("content-123")
        src = str(src_path)
        checksum = calculate_sha256(src)
        _seed_meta(session_factory, src, checksum, category="notes", title="New Title")

        with session_factory() as s:
            s.add(FileRelationship(source_path=src, target_path="/other/x.txt",
                                   relationship_type="related_to"))
            s.commit()

        result = rename_file(src, "new name.txt",
                             session_factory=session_factory)
        assert result.ok
        dst = result.destination
        assert os.path.isfile(dst)
        assert not os.path.exists(src)
        # SHA-256 identity preserved.
        assert calculate_sha256(dst) == checksum
        # Derived layers synced.
        with session_factory() as s:
            from services.sqlite_indexer import IndexedFile
            row = s.query(IndexedFile).filter_by(absolute_path=dst).first()
            assert row is not None
            assert row.checksum == checksum
            rel = s.query(FileRelationship).filter_by(source_path=dst).first()
            assert rel is not None

    def test_collision_never_overwrites(self, session_factory, tmp_path):
        from services.file_mover import MoveError, rename_file

        src_path = tmp_path / "a.txt"
        src_path.write_text("original")
        src = str(src_path)
        (tmp_path / "b.txt").write_text("occupied")
        _seed_meta(session_factory, src, "a" * 64)
        with pytest.raises(MoveError):
            rename_file(src, "b.txt", session_factory=session_factory)
        assert (tmp_path / "b.txt").read_text() == "occupied"
        assert (tmp_path / "a.txt").read_text() == "original"

    def test_missing_source(self, session_factory, tmp_path):
        from services.file_mover import MoveError, rename_file

        with pytest.raises(MoveError):
            rename_file(str(tmp_path / "missing.txt"), "new.txt",
                        session_factory=session_factory)

    def test_extension_change_rejected(self, session_factory, tmp_path):
        from services.file_mover import MoveError, rename_file

        src_path = tmp_path / "a.txt"
        src_path.write_text("x")
        src = str(src_path)
        _seed_meta(session_factory, src, "b" * 64)
        with pytest.raises(MoveError):
            rename_file(src, "a.pdf", session_factory=session_factory)

    def test_path_traversal_rejected(self, session_factory, tmp_path):
        from services.file_mover import MoveError, rename_file

        src_path = tmp_path / "a.txt"
        src_path.write_text("x")
        src = str(src_path)
        _seed_meta(session_factory, src, "c" * 64)
        with pytest.raises(MoveError):
            rename_file(src, "../evil.txt", session_factory=session_factory)

    def test_metadata_editor_preserved_across_rename(self, session_factory, tmp_path):
        from services.file_identity import calculate_sha256
        from services.file_mover import rename_file
        from services.metadata_editor_service import MetadataEditorService

        src_path = tmp_path / "m.txt"
        src_path.write_text("body")
        src = str(src_path)
        checksum = calculate_sha256(src)
        _seed_meta(session_factory, src, checksum)
        editor = MetadataEditorService(session_factory)
        editor.save(src, {"title": "User Title"})
        result = rename_file(src, "renamed.txt", session_factory=session_factory)
        # User metadata is keyed by path; the mover rewrites the indexed row
        # path so the same metadata row follows the file.
        row_path = result.destination
        with session_factory() as s:
            from services.sqlite_indexer import IndexedFile
            row = s.query(IndexedFile).filter_by(absolute_path=row_path).first()
            assert row is not None
            assert row.user_metadata_json is not None


class TestRenamePreviewDialog:
    def test_dialog_constructs(self, qapp):
        from services.rename_suggestion_service import RenameSuggestion
        from ui.dialogs.rename_preview_dialog import RenamePreviewDialog

        sug = RenameSuggestion(
            file_path="/tmp/a.txt", current_name="a.txt",
            proposed_name="document_a.txt", reason="test",
        )
        dlg = RenamePreviewDialog([sug])
        assert dlg.table.rowCount() == 1
        dlg.close()

    def test_invalid_shown_but_not_approved(self, qapp):
        from services.rename_suggestion_service import RenameSuggestion
        from ui.dialogs.rename_preview_dialog import RenamePreviewDialog

        sug = RenameSuggestion(
            file_path="/tmp/a.txt", current_name="a.txt",
            proposed_name="a.txt", errors=["Name is unchanged"],
        )
        calls = []
        dlg = RenamePreviewDialog([sug], approve=lambda p, n: calls.append((p, n)))
        dlg._approve_all()
        assert calls == []  # invalid suggestion never executed
        dlg.close()

    def test_approve_all_executes(self, qapp):
        from services.rename_suggestion_service import RenameSuggestion
        from ui.dialogs.rename_preview_dialog import RenamePreviewDialog

        sug = RenameSuggestion(
            file_path="/tmp/a.txt", current_name="a.txt",
            proposed_name="document_a.txt",
        )
        calls = []
        dlg = RenamePreviewDialog([sug], approve=lambda p, n: calls.append((p, n)) or {"ok": True})
        dlg._approve_all()
        assert calls == [("/tmp/a.txt", "document_a.txt")]
        dlg.close()


class TestMultiRenameSelectionDialog:
    def test_dialog_populate_and_filter(self, qapp, tmp_path):
        from ui.dialogs.multi_rename_selection_dialog import MultiRenameSelectionDialog
        from PySide6.QtCore import Qt

        # Create some files in a temporary folder
        (tmp_path / "file1.txt").write_text("1")
        (tmp_path / "file2.txt").write_text("2")
        (tmp_path / "another.pdf").write_text("3")
        # And a subdirectory which should be ignored
        (tmp_path / "subdir").mkdir()

        dlg = MultiRenameSelectionDialog(str(tmp_path))
        # Ensure only the files are listed
        assert dlg.list_widget.count() == 3

        # Test filtering
        dlg.filter_edit.setText("file")
        assert dlg.list_widget.item(0).isHidden() is True   # another.pdf
        assert dlg.list_widget.item(1).isHidden() is False  # file1.txt
        assert dlg.list_widget.item(2).isHidden() is False  # file2.txt

        # Test select all / deselect all
        dlg.filter_edit.setText("")  # clear filter
        dlg._deselect_all()
        for i in range(dlg.list_widget.count()):
            assert dlg.list_widget.item(i).checkState() == Qt.Unchecked

        dlg._select_all()
        for i in range(dlg.list_widget.count()):
            assert dlg.list_widget.item(i).checkState() == Qt.Checked

        # Test proceed
        selected = dlg.get_selected_files()
        assert len(selected) == 3
        assert any("file1.txt" in s for s in selected)
        assert any("file2.txt" in s for s in selected)
        assert any("another.pdf" in s for s in selected)
        dlg.close()
