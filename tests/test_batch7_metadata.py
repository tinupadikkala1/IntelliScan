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
