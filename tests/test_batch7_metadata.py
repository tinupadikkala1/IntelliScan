"""Batch 7 tests — metadata export (B7-3) + metadata editor (B7-6)."""

import json
import os
import sys
import tempfile

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


def _seed_files(sf, files):
    from datetime import datetime

    from services.sqlite_indexer import IndexedFile

    with sf() as s:
        for f in files:
            s.add(IndexedFile(
                filename=f["name"], absolute_path=f["path"],
                size=f.get("size", 100), mime_type=f.get("mime", "text/plain"),
                extension=f.get("ext", os.path.splitext(f["name"])[1]),
                created_date=f.get("created", datetime(2024, 1, 1)),
                modified_date=f.get("modified", datetime(2024, 6, 1)),
                checksum=f.get("checksum", ""),
                indexing_status="completed",
            ))
        s.commit()


class TestMetadataExport:
    def test_collect_workspace(self, session_factory):
        from services.metadata_export_service import MetadataExportService

        _seed_files(session_factory, [
            {"name": "a.pdf", "path": "/ws/a.pdf", "checksum": "a" * 64},
            {"name": "b.txt", "path": "/ws/b.txt", "checksum": "b" * 64},
        ])
        svc = MetadataExportService(session_factory)
        records = svc.collect(scope="workspace")
        assert len(records) == 2
        assert {r["filename"] for r in records} == {"a.pdf", "b.txt"}

    def test_collect_folder_scope(self, session_factory):
        from services.metadata_export_service import MetadataExportService

        _seed_files(session_factory, [
            {"name": "a.txt", "path": "/ws/sub/a.txt", "checksum": "a" * 64},
            {"name": "b.txt", "path": "/other/b.txt", "checksum": "b" * 64},
        ])
        svc = MetadataExportService(session_factory)
        records = svc.collect(scope="folder", folder="/ws")
        assert [r["filename"] for r in records] == ["a.txt"]

    def test_collect_files_scope(self, session_factory, tmp_path):
        from services.metadata_export_service import MetadataExportService

        p = tmp_path / "a.txt"
        p.write_text("hello")
        _seed_files(session_factory, [
            {"name": "a.txt", "path": str(p), "checksum": "a" * 64},
        ])
        svc = MetadataExportService(session_factory)
        records = svc.collect(scope="files", files=[str(p)])
        assert [r["filename"] for r in records] == ["a.txt"]

    def test_to_json_valid_and_utf8(self, session_factory):
        from services.metadata_export_service import MetadataExportService

        _seed_files(session_factory, [
            {"name": "résumé.txt", "path": "/ws/résumé.txt", "checksum": "a" * 64},
        ])
        svc = MetadataExportService(session_factory)
        body = svc.to_json(svc.collect(scope="workspace"))
        data = json.loads(body)  # valid JSON
        assert data["count"] == 1
        assert "résumé" in body  # UTF-8 preserved

    def test_csv_quoting_and_columns(self, session_factory):
        import csv
        import io

        from services.metadata_export_service import MetadataExportService

        _seed_files(session_factory, [
            {"name": 'a,"weird".txt', "path": "/ws/a.txt", "checksum": "a" * 64},
        ])
        svc = MetadataExportService(session_factory)
        body = svc.to_csv(svc.collect(scope="workspace"))
        reader = csv.DictReader(io.StringIO(body))
        rows = list(reader)
        assert len(rows) == 1
        assert "path" in rows[0]
        assert "checksum" in rows[0]

    def test_export_file_write(self, session_factory, tmp_path):
        from services.metadata_export_service import MetadataExportService

        _seed_files(session_factory, [
            {"name": "a.txt", "path": "/ws/a.txt", "checksum": "a" * 64},
        ])
        svc = MetadataExportService(session_factory)
        dest = str(tmp_path / "out.json")
        report = svc.export(dest, fmt="json", scope="workspace")
        assert report["count"] == 1
        assert os.path.isfile(dest)
        assert json.loads(open(dest, encoding="utf-8").read())["count"] == 1

    def test_export_invalid_format(self, session_factory):
        from services.metadata_export_service import MetadataExportError, MetadataExportService

        svc = MetadataExportService(session_factory)
        with pytest.raises(MetadataExportError):
            svc.export("/tmp/x.xml", fmt="xml", scope="workspace")

    def test_export_bad_destination(self, session_factory):
        from services.metadata_export_service import MetadataExportError, MetadataExportService

        svc = MetadataExportService(session_factory)
        with pytest.raises(MetadataExportError):
            svc.export("/no/such/dir/out.json", fmt="json", scope="workspace")

    def test_ai_fields_included(self, session_factory):
        from database.models import AIAnalysis
        from services.metadata_export_service import MetadataExportService

        _seed_files(session_factory, [
            {"name": "a.txt", "path": "/ws/a.txt", "checksum": "a" * 64},
        ])
        with session_factory() as s:
            s.add(AIAnalysis(
                file_hash="a" * 64,
                summary="A summary",
                normalized_category="document",
                normalized_tags='["finance"]',
                caption="caption text",
                quality_score=0.8,
                objects_json='[{"label":"text","confidence":0.9}]',
            ))
            s.commit()
        svc = MetadataExportService(session_factory)
        records = svc.collect(scope="workspace")
        assert records[0]["category"] == "document"
        assert records[0]["caption"] == "caption text"
        assert records[0]["quality_score"] == 0.8
        assert "text" in records[0]["objects"]


class TestMetadataEditor:
    def test_save_and_get(self, session_factory):
        from services.metadata_editor_service import MetadataEditorService

        _seed_files(session_factory, [{"name": "a.txt", "path": "/ws/a.txt", "checksum": "a" * 64}])
        svc = MetadataEditorService(session_factory)
        svc.save("/ws/a.txt", {"title": "My File", "description": "Desc",
                               "user_tags": "one, two", "custom": {"project": "X"}})
        data = svc.get("/ws/a.txt")
        assert data["title"] == "My File"
        assert data["description"] == "Desc"
        assert data["user_tags"] == ["one", "two"]
        assert data["custom"] == {"project": "X"}

    def test_restart_persistence(self, session_factory, tmp_path):
        # Fresh engine over the same DB file = restart.
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker

        from database.models import Base
        from database.migrations import run_migrations
        from services.metadata_editor_service import MetadataEditorService

        _seed_files(session_factory, [{"name": "a.txt", "path": "/ws/a.txt", "checksum": "a" * 64}])
        svc = MetadataEditorService(session_factory)
        svc.save("/ws/a.txt", {"title": "Persisted"})

        engine2 = create_engine(session_factory().bind.url, echo=False)
        Base.metadata.create_all(engine2)
        run_migrations(engine2)
        sf2 = sessionmaker(bind=engine2)
        svc2 = MetadataEditorService(sf2)
        assert svc2.get("/ws/a.txt")["title"] == "Persisted"
        engine2.dispose()

    def test_ai_metadata_never_overwritten(self, session_factory):
        from database.models import AIAnalysis
        from services.metadata_editor_service import MetadataEditorService

        _seed_files(session_factory, [{"name": "a.txt", "path": "/ws/a.txt", "checksum": "a" * 64}])
        with session_factory() as s:
            s.add(AIAnalysis(file_hash="a" * 64, summary="AI summary",
                             normalized_category="document"))
            s.commit()
        svc = MetadataEditorService(session_factory)
        svc.save("/ws/a.txt", {"title": "User title"})
        with session_factory() as s:
            from database.models import AIAnalysis
            ai = s.query(AIAnalysis).filter_by(file_hash="a" * 64).first()
            assert ai.summary == "AI summary"
            assert ai.normalized_category == "document"

    def test_validation_rejects_too_many_tags(self, session_factory):
        from services.metadata_editor_service import MetadataEditorError, MetadataEditorService

        _seed_files(session_factory, [{"name": "a.txt", "path": "/ws/a.txt", "checksum": "a" * 64}])
        svc = MetadataEditorService(session_factory)
        with pytest.raises(MetadataEditorError):
            svc.save("/ws/a.txt", {"user_tags": [f"t{i}" for i in range(30)]})

    def test_custom_must_be_dict(self, session_factory):
        from services.metadata_editor_service import MetadataEditorError, MetadataEditorService

        _seed_files(session_factory, [{"name": "a.txt", "path": "/ws/a.txt", "checksum": "a" * 64}])
        svc = MetadataEditorService(session_factory)
        with pytest.raises(MetadataEditorError):
            svc.save("/ws/a.txt", {"custom": ["not", "a", "dict"]})

    def test_clear(self, session_factory):
        from services.metadata_editor_service import MetadataEditorService

        _seed_files(session_factory, [{"name": "a.txt", "path": "/ws/a.txt", "checksum": "a" * 64}])
        svc = MetadataEditorService(session_factory)
        svc.save("/ws/a.txt", {"title": "X"})
        svc.clear("/ws/a.txt")
        assert svc.get("/ws/a.txt") == {}

    def test_unindexed_file_rejected(self, session_factory):
        from services.metadata_editor_service import MetadataEditorError, MetadataEditorService

        svc = MetadataEditorService(session_factory)
        with pytest.raises(MetadataEditorError):
            svc.save("/ws/not_indexed.txt", {"title": "X"})

    def test_user_metadata_chunk_creation(self):
        from services.metadata_editor_service import build_user_metadata_chunk

        chunk = build_user_metadata_chunk(
            "/path/to/diagram.png",
            {
                "title": "Shortest Path Graph",
                "description": "dijkstras algorithm visualization",
                "notes": "Time complexity is O(E + V log V)",
                "user_tags": ["algorithm", "graph"],
            },
            file_hash="hash123",
        )
        assert chunk is not None
        assert chunk.modality == "image"
        assert chunk.source_type == "user_metadata"
        assert "dijkstras algorithm" in chunk.text
        assert "O(E + V log V)" in chunk.text
        assert chunk.confidence == 1.0

    def test_user_metadata_live_sync_and_smart_retrieve(self, session_factory, tmp_path):
        from unittest.mock import MagicMock
        import numpy as np
        from engines.retrieval_engine import RetrievalEngine
        from services.metadata_editor_service import MetadataEditorService

        img_path = str(tmp_path / "algorithm_graph.png")
        _seed_files(session_factory, [
            {"name": "algorithm_graph.png", "path": img_path, "checksum": "img_hash_123"}
        ])

        # Mock vector engine and embedding engine
        mock_vector = MagicMock()
        mock_vector.size = 0
        mock_vector.dimension = 384
        mock_vector.search.return_value = []
        mock_vector.remove_by_chunk_ids.return_value = 0

        mock_embedding = MagicMock()
        mock_embedding.embed_documents.return_value = [np.zeros(384, dtype=np.float32)]

        retrieval = RetrievalEngine(
            embedding_engine=mock_embedding,
            vector_engine=mock_vector,
            session_factory=session_factory,
        )

        svc = MetadataEditorService(
            session_factory=session_factory,
            retrieval_engine=retrieval,
        )

        # Save metadata containing "dijkstras algorithm"
        svc.save(img_path, {
            "title": "Graph Traversal",
            "description": "dijkstras algorithm implementation",
            "notes": "Single source shortest path",
            "user_tags": ["dijkstras", "shortest_path"],
        })

        # Test smart_retrieve for "dijkstras algorithm"
        res = retrieval.smart_retrieve("dijkstras algorithm")
        assert len(res.results) >= 1
        top = res.results[0]
        assert top.file_path == img_path
        assert top.score >= 0.95
        assert top.source_type == "user_metadata"

        # Test modality query "dijkstras algorithm image"
        res_mod = retrieval.smart_retrieve("dijkstras algorithm image")
        assert len(res_mod.results) >= 1
        assert res_mod.results[0].file_path == img_path
        assert res_mod.results[0].modality == "image"

    def test_user_metadata_clear_removes_from_retrieval(self, session_factory, tmp_path):
        from unittest.mock import MagicMock
        from engines.retrieval_engine import RetrievalEngine
        from services.metadata_editor_service import MetadataEditorService

        img_path = str(tmp_path / "diagram.jpg")
        _seed_files(session_factory, [
            {"name": "diagram.jpg", "path": img_path, "checksum": "diag_123"}
        ])

        mock_vector = MagicMock()
        mock_vector.size = 0
        mock_vector.search.return_value = []
        mock_embedding = MagicMock()

        retrieval = RetrievalEngine(
            embedding_engine=mock_embedding,
            vector_engine=mock_vector,
            session_factory=session_factory,
        )
        svc = MetadataEditorService(session_factory=session_factory, retrieval_engine=retrieval)

        svc.save(img_path, {"description": "dijkstras algorithm"})
        res = retrieval.smart_retrieve("dijkstras algorithm")
        assert len(res.results) == 1

        # Clear metadata
        svc.clear(img_path)
        res_after = retrieval.smart_retrieve("dijkstras algorithm")
        assert len(res_after.results) == 0

    def test_user_metadata_in_rag_direct_ask(self, session_factory, tmp_path):
        from unittest.mock import MagicMock, patch
        from engines.rag_engine import RAGEngine

        img_path = str(tmp_path / "graph.png")
        _seed_files(session_factory, [
            {"name": "graph.png", "path": img_path, "checksum": "graph_123"}
        ])

        # Write user metadata to SQLite
        from services.metadata_editor_service import MetadataEditorService
        svc = MetadataEditorService(session_factory)
        svc.save(img_path, {
            "title": "Shortest Path",
            "notes": "Explains Dijkstra's Algorithm in detail with edge relaxation steps.",
        })

        rag = RAGEngine(
            retrieval_engine=MagicMock(),
            session_factory=session_factory,
        )

        user_text = rag._get_user_metadata_text(img_path)
        assert "Dijkstra's Algorithm" in user_text
        assert "Shortest Path" in user_text

        with patch.object(rag, "_generate", return_value="This image describes Dijkstra's algorithm."):
            resp = rag._ask_image_direct("What algorithm is this?", img_path, 0.0)
            assert resp.grounded is True
            assert "Dijkstra's" in resp.answer
            assert len(resp.citations) == 1
            assert resp.citations[0].file_path == img_path

