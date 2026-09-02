"""Batch 6 §10.8 — automatic folder organization tests (B6-05 / #29).

Covers: folder-target suggestions (existing folders only), the preview
dialog, safe move execution, collision handling, and full index
synchronization after a move (indexed_files, evidence, vector_map,
relationships, collections, suggestions — SHA-256 identity preserved).
"""

import os
import shutil
import sys
from contextlib import contextmanager

import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)


@contextmanager
def _db_session_factory(tmp_path, name="test_b6_move.db"):
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


class TestFolderTargets:
    def test_category_sibling_folder(self, tmp_path):
        from services.batch5_store import Batch5Store
        from services.suggestion_engine import SuggestionEngine

        with _db_session_factory(tmp_path) as sf:
            parent = tmp_path / "ws"
            docs = parent / "Documents"
            docs.mkdir(parents=True)
            (parent / "Images").mkdir()
            f = parent / "notes.txt"
            f.write_text("hello")
            engine = SuggestionEngine(store=Batch5Store(sf))
            targets = engine.folder_targets_for_file(str(f))
            assert targets, "expected a folder target"
            assert any(t["type"] == "folder" and t["path"] == str(docs) for t in targets)
            assert all(os.path.isdir(t["path"]) for t in targets)

    def test_no_invented_dirs(self, tmp_path):
        from services.batch5_store import Batch5Store
        from services.suggestion_engine import SuggestionEngine

        with _db_session_factory(tmp_path) as sf:
            parent = tmp_path / "ws"
            parent.mkdir()
            f = parent / "notes.txt"
            f.write_text("hello")
            engine = SuggestionEngine(store=Batch5Store(sf))
            targets = engine.folder_targets_for_file(str(f))
            assert targets == []  # no matching sibling folder → no suggestion

    def test_suggest_for_file_includes_folder_targets(self, tmp_path):
        from services.batch5_store import Batch5Store
        from services.suggestion_engine import SuggestionEngine

        with _db_session_factory(tmp_path) as sf:
            parent = tmp_path / "ws"
            (parent / "Images").mkdir(parents=True)
            (parent / "Documents").mkdir()
            f = parent / "photo.png"
            f.write_bytes(b"\x89PNG fake")
            engine = SuggestionEngine(store=Batch5Store(sf))
            sugs = engine.suggest_for_file(str(f))
            assert any(s.target_type == "folder" for s in sugs)


class TestFileMover:
    def test_valid_move_syncs_all_layers(self, tmp_path):
        from services.file_mover import move_file
        from services.sqlite_indexer import IndexedFile
        from database.models import Evidence, VectorMap, FileRelationship, CollectionItem
        from services.file_identity import calculate_sha256

        src_dir = tmp_path / "src"
        dst_dir = tmp_path / "dst"
        src_dir.mkdir(); dst_dir.mkdir()
        src = src_dir / "doc.txt"
        src.write_text("move me")

        with _db_session_factory(tmp_path) as sf:
            # Seed index + derived state for the source path.
            checksum = calculate_sha256(str(src))
            with sf() as s:
                s.add(IndexedFile(
                    filename="doc.txt", absolute_path=str(src), size=7,
                    extension=".txt", checksum=checksum, indexing_status="completed",
                ))
                s.add(Evidence(chunk_id="a" * 32, file_path=str(src), file_hash=checksum, text="move me"))
                s.add(VectorMap(chunk_id="a" * 32, file_path=str(src), file_hash=checksum))
                rel = FileRelationship(source_path=str(src), target_path=str(tmp_path / "other.txt"),
                                       relationship_type="related_to")
                s.add(rel)
                col = __import__("database.models", fromlist=["Collection"]).Collection(name="c")
                s.add(col); s.flush()
                s.add(CollectionItem(collection_id=col.id, file_path=str(src)))
                s.commit()

            result = move_file(str(src), str(dst_dir), session_factory=sf)
            assert result.ok is True
            dst = dst_dir / "doc.txt"
            assert dst.exists()

            with sf() as s:
                assert s.query(IndexedFile).filter_by(absolute_path=str(dst)).count() == 1
                assert s.query(IndexedFile).filter_by(absolute_path=str(src)).count() == 0
                assert s.query(Evidence).filter_by(file_path=str(dst)).count() == 1
                assert s.query(VectorMap).filter_by(file_path=str(dst)).count() == 1
                assert s.query(FileRelationship).filter_by(source_path=str(dst)).count() == 1
                assert s.query(CollectionItem).filter_by(file_path=str(dst)).count() == 1
                # SHA-256 identity preserved on the row.
                row = s.query(IndexedFile).filter_by(absolute_path=str(dst)).first()
                assert row.checksum == checksum

    def test_collision_never_overwrites(self, tmp_path):
        from services.file_mover import MoveError, move_file

        src_dir = tmp_path / "src"
        dst_dir = tmp_path / "dst"
        src_dir.mkdir(); dst_dir.mkdir()
        src = src_dir / "doc.txt"
        src.write_text("original")
        (dst_dir / "doc.txt").write_text("existing — must survive")

        with _db_session_factory(tmp_path) as sf:
            with pytest.raises(MoveError):
                move_file(str(src), str(dst_dir), session_factory=sf)
            assert src.exists(), "source untouched after collision"
            assert (dst_dir / "doc.txt").read_text() == "existing — must survive"

    def test_missing_source(self, tmp_path):
        from services.file_mover import MoveError, move_file

        dst_dir = tmp_path / "dst"
        dst_dir.mkdir()
        with _db_session_factory(tmp_path) as sf:
            with pytest.raises(MoveError):
                move_file(str(tmp_path / "nope.txt"), str(dst_dir), session_factory=sf)

    def test_missing_destination(self, tmp_path):
        from services.file_mover import MoveError, move_file

        src = tmp_path / "doc.txt"
        src.write_text("x")
        with _db_session_factory(tmp_path) as sf:
            with pytest.raises(MoveError):
                move_file(str(src), str(tmp_path / "nope"), session_factory=sf)

    def test_same_directory_rejected(self, tmp_path):
        from services.file_mover import MoveError, move_file

        src = tmp_path / "doc.txt"
        src.write_text("x")
        with _db_session_factory(tmp_path) as sf:
            with pytest.raises(MoveError):
                move_file(str(src), str(tmp_path), session_factory=sf)

    def test_ai_metadata_preserved_across_move(self, tmp_path):
        """ai_analysis is keyed by hash — a move must not change association."""
        from services.file_mover import move_file
        from database.models import AIAnalysis
        from services.file_identity import calculate_sha256

        src_dir = tmp_path / "src"
        dst_dir = tmp_path / "dst"
        src_dir.mkdir(); dst_dir.mkdir()
        src = src_dir / "doc.txt"
        src.write_text("move me")
        checksum = calculate_sha256(str(src))

        with _db_session_factory(tmp_path) as sf:
            with sf() as s:
                s.add(AIAnalysis(
                    file_hash=checksum, summary="analysis survives",
                    normalized_category="document",
                ))
                s.commit()
            move_file(str(src), str(dst_dir), session_factory=sf)
            with sf() as s:
                row = s.query(AIAnalysis).filter_by(file_hash=checksum).first()
                assert row is not None
                assert row.summary == "analysis survives"


class TestOrganizationPreviewDialog:
    def test_preview_renders_moves(self, qapp, qtbot, tmp_path):
        from ui.dialogs.organization_preview_dialog import OrganizationPreviewDialog

        src = tmp_path / "a.txt"
        src.write_text("x")
        dst = tmp_path / "dst"
        dst.mkdir()
        dlg = OrganizationPreviewDialog(moves=[(str(src), str(dst))], on_execute=lambda s, d: "")
        qtbot.addWidget(dlg)
        assert dlg.moves_list.count() == 1
        assert "a.txt" in dlg.moves_list.item(0).text()
        dlg.close()

    def test_execute_calls_callback(self, qapp, qtbot, tmp_path):
        from ui.dialogs.organization_preview_dialog import OrganizationPreviewDialog

        src = tmp_path / "a.txt"
        src.write_text("x")
        dst = tmp_path / "dst"
        dst.mkdir()
        calls = []
        dlg = OrganizationPreviewDialog(
            moves=[(str(src), str(dst))],
            on_execute=lambda s, d: (calls.append((s, d)) or ""),
        )
        qtbot.addWidget(dlg)
        # Directly exercise the execute path without the modal confirm.
        dlg._execute([(str(src), str(dst))])
        assert calls == [(str(src), str(dst))]
        assert "1 file(s) moved" in dlg.status_label.text()
        dlg.close()
