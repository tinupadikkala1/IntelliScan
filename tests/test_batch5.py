"""Batch 5 tests — Intelligent Organization & Knowledge Management.

Covers: file identity, exact duplicates, near duplicates / similarity,
related files, file relationships, classification, auto-tagging, saved
searches, smart collections, organization suggestions, the knowledge
dashboard, deletion cleanup, and the Batch-5 UI dialogs.

All tests run WITHOUT Ollama; AI calls are mocked or avoided.
"""

import os
import sys
import threading
from contextlib import contextmanager

import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)


@contextmanager
def _db_session_factory(tmp_path, name="test_batch5.db"):
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


def _indexed_record(session, path, checksum, size=10, ext=".txt", filename=None):
    from services.sqlite_indexer import IndexedFile
    record = IndexedFile(
        filename=filename or os.path.basename(path),
        absolute_path=path,
        size=size,
        mime_type="text/plain",
        extension=ext,
        checksum=checksum,
        extracted_text="content",
        indexing_status="completed",
    )
    session.add(record)
    return record


_EMPTY_HASH = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"


# ================================================================
# Phase 0 — File identity
# ================================================================

class TestFileIdentity:
    def test_sha256_identical_across_callers(self, tmp_path):
        """Consolidated helper matches the legacy hashing behavior."""
        import hashlib
        from services.file_identity import calculate_sha256

        f = tmp_path / "sample.txt"
        f.write_text("hello world\n" * 100, encoding="utf-8")

        legacy = hashlib.sha256()
        with open(f, "rb") as fh:
            for chunk in iter(lambda: fh.read(8192), b""):
                legacy.update(chunk)

        assert calculate_sha256(str(f)) == legacy.hexdigest()

    def test_empty_file_policy(self, tmp_path):
        from services.file_identity import EMPTY_SHA256, calculate_sha256, is_empty_sha256

        f = tmp_path / "empty.txt"
        f.write_text("", encoding="utf-8")
        digest = calculate_sha256(str(f))
        assert digest == EMPTY_SHA256
        assert is_empty_sha256(digest)

    def test_missing_file_raises(self):
        from services.file_identity import FileIdentityError, calculate_sha256, calculate_sha256_safe
        with pytest.raises(FileIdentityError):
            calculate_sha256("/no/such/file.txt")
        assert calculate_sha256_safe("/no/such/file.txt") is None

    def test_directory_rejected(self, tmp_path):
        from services.file_identity import FileIdentityError, calculate_sha256
        with pytest.raises(FileIdentityError):
            calculate_sha256(str(tmp_path))


# ================================================================
# B5-04 — Exact duplicates
# ================================================================

class TestDuplicateEngine:
    @staticmethod
    def _engine(tmp_path, empty_visible=True):
        from engines.duplicate_engine import DuplicateEngine
        with _db_session_factory(tmp_path) as sf:
            with sf() as s:
                c1 = "a" * 64
                c2 = "b" * 64
                _indexed_record(s, "/tmp/a.txt", c1)
                _indexed_record(s, "/tmp/b.txt", c1)
                _indexed_record(s, "/tmp/c.txt", c2)
                _indexed_record(s, "/tmp/e1.txt", _EMPTY_HASH, size=0)
                _indexed_record(s, "/tmp/e2.txt", _EMPTY_HASH, size=0)
                s.commit()
            return DuplicateEngine(sf, empty_visible=empty_visible)

    def test_groups_same_content(self, tmp_path):
        groups = self._engine(tmp_path).find_exact_duplicates()
        assert len(groups) == 2
        group = next(g for g in groups if not g.is_empty)
        assert set(group.files) == {"/tmp/a.txt", "/tmp/b.txt"}

    def test_empty_group_labeled(self, tmp_path):
        groups = self._engine(tmp_path).find_exact_duplicates()
        empty = next(g for g in groups if g.is_empty)
        assert empty.is_empty
        assert len(empty.files) == 2

    def test_empty_hidden_policy(self, tmp_path):
        groups = self._engine(tmp_path, empty_visible=False).find_exact_duplicates()
        assert len(groups) == 1
        assert not groups[0].is_empty

    def test_for_file(self, tmp_path):
        engine = self._engine(tmp_path)
        group = engine.find_exact_duplicates_for_file("/tmp/a.txt")
        assert group is not None
        assert len(group.files) == 2
        assert engine.find_exact_duplicates_for_file("/tmp/c.txt") is None

    def test_invalid_checksum_excluded(self, tmp_path):
        from engines.duplicate_engine import DuplicateEngine
        with _db_session_factory(tmp_path) as sf:
            with sf() as s:
                _indexed_record(s, "/tmp/x.txt", "")      # empty checksum
                _indexed_record(s, "/tmp/y.txt", "short") # invalid length
                s.commit()
            groups = DuplicateEngine(sf).find_exact_duplicates()
            assert groups == []

    def test_duplicate_stats(self, tmp_path):
        stats = self._engine(tmp_path).duplicate_stats()
        assert stats["groups"] == 2
        assert stats["duplicate_files"] == 2


# ================================================================
# B5-05 — Near duplicates / file similarity
# ================================================================

class TestFileSimilarity:
    class _MockRetrieval:
        def __init__(self, results):
            self._results = results
            self.indexed_count = len(results)

        def retrieve_similar(self, file_path, top_k=5, threshold=0.3):
            from engines.retrieval_engine import RetrievalResponse
            return RetrievalResponse(
                query=f"similar:{file_path}", scope="similar",
                results=self._results, total_found=len(self._results),
                elapsed_ms=1.0,
            )

    @staticmethod
    def _result(path, score):
        from engines import RetrievalResult
        return RetrievalResult(
            chunk_id=f"{path}-{score}", text="t", score=score, rank=0,
            file_path=path, file_hash="h", source_type="page", source_index=0,
            source_label="Page 1", char_start=0, char_end=1,
        )

    def test_aggregates_per_file_excludes_source(self):
        from services.file_similarity import FileSimilarityService
        results = [
            self._result("/tmp/src.txt", 0.99),
            self._result("/tmp/dup.pdf", 0.95),
            self._result("/tmp/dup.pdf", 0.93),   # 2 chunks
            self._result("/tmp/rel.md", 0.80),
            self._result("/tmp/unrelated.pdf", 0.30),
        ]
        svc = FileSimilarityService(self._MockRetrieval(results),
                                    near_threshold=0.90, similar_threshold=0.75)
        hits = svc.similar_files("/tmp/src.txt")
        assert all(h.file_path != "/tmp/src.txt" for h in hits)
        dup = next(h for h in hits if h.file_path == "/tmp/dup.pdf")
        assert dup.score == 0.95  # best score per file
        assert dup.matched_chunks == 2
        assert dup.score >= 0.90  # near duplicate bucket

    def test_threshold_buckets(self):
        from services.file_similarity import FileSimilarityService
        results = [self._result("/tmp/dup.pdf", 0.95), self._result("/tmp/rel.md", 0.80)]
        svc = FileSimilarityService(self._MockRetrieval(results),
                                    near_threshold=0.90, similar_threshold=0.75)
        all_hits = svc.similar_files("/tmp/src.txt")
        near = svc.near_duplicates("/tmp/src.txt")
        assert len(all_hits) == 2
        assert len(near) == 1
        assert near[0].file_path == "/tmp/dup.pdf"

    def test_low_score_excluded(self):
        from services.file_similarity import FileSimilarityService
        results = [self._result("/tmp/low.pdf", 0.40)]
        svc = FileSimilarityService(self._MockRetrieval(results),
                                    near_threshold=0.90, similar_threshold=0.75)
        assert svc.similar_files("/tmp/src.txt") == []

    def test_empty_index(self):
        from services.file_similarity import FileSimilarityService
        svc = FileSimilarityService(self._MockRetrieval([]))
        assert not svc.has_index
        assert svc.similar_files("/tmp/src.txt") == []


# ================================================================
# B5-06 — Related files
# ================================================================

class TestRelatedFileService:
    class _MockRetrieval:
        _evidence = {}

        def smart_retrieve(self, query, top_k=10, threshold=0.3):
            from engines.retrieval_engine import RetrievalResponse
            return RetrievalResponse(
                query=query, scope="workspace", results=[], total_found=0,
                elapsed_ms=1.0,
            )

    class _MockGraph:
        def files_sharing_entities(self, file_path, limit=50):
            return ["/tmp/entity_shared.pdf"]

    def test_merges_signals_deduped(self):
        from services.batch5_models import SimilarFileResult
        from services.file_similarity import FileSimilarityService
        from services.related_file_service import RelatedFileService

        class Sim:
            def similar_files(self, path):
                return [SimilarFileResult("/tmp/v1.pdf", 0.88, reason="similar content")]

        svc = RelatedFileService(
            retrieval=self._MockRetrieval(),
            similarity=Sim(),
            graph_store=self._MockGraph(),
            max_results=10,
        )
        results = svc.related_files("/tmp/source.pdf")
        paths = {r.file_path for r in results}
        assert "/tmp/source.pdf" not in paths
        assert "/tmp/v1.pdf" in paths
        assert "/tmp/entity_shared.pdf" in paths
        # graph entry has a human reason
        graph_hit = next(r for r in results if r.source == "graph")
        assert "Shared topics/entities" in graph_hit.reason


# ================================================================
# B5-07 — File relationships
# ================================================================

class TestRelationshipEngine:
    def _setup(self, tmp_path):
        from services.batch5_store import Batch5Store
        from services.relationship_engine import RelationshipEngine
        with _db_session_factory(tmp_path) as sf:
            store = Batch5Store(sf)
            return store, RelationshipEngine(
                store=store, duplicates=_DupEngineStub(), similarity=_SimStub(),
                graph_store=_GraphStub(),
            )

    def test_duplicate_creates_duplicate_of(self, tmp_path):
        store, engine = self._setup(tmp_path)
        created = engine.build_for_file("/tmp/a.txt")
        assert created >= 1
        rels = engine.relationships_for_file("/tmp/a.txt")
        dup = next(r for r in rels if r.relationship_type == "duplicate_of")
        assert dup.target_path == "/tmp/b.txt"
        assert dup.confidence == 1.0
        assert dup.evidence.get("reason")

    def test_invalid_type_rejected(self):
        from engines.config import RELATIONSHIP_TYPES
        assert "duplicate_of" in RELATIONSHIP_TYPES
        assert "fake_type" not in RELATIONSHIP_TYPES

    def test_duplicate_edge_prevented(self, tmp_path):
        store, engine = self._setup(tmp_path)
        store.upsert_relationship("/tmp/a.txt", "/tmp/b.txt", "duplicate_of", 1.0)
        with pytest.raises(Exception):
            store.upsert_relationship("/tmp/a.txt", "/tmp/a.txt", "duplicate_of", 1.0)

    def test_evidence_persisted(self, tmp_path):
        store, engine = self._setup(tmp_path)
        store.upsert_relationship(
            "/tmp/a.txt", "/tmp/b.txt", "duplicate_of", 1.0,
            evidence={"reason": "identical content", "checksum": "abc"},
        )
        rels = store.relationships_for_path("/tmp/a.txt")
        assert rels[0].reason == "identical content"

    def test_restart_persistence(self, tmp_path):
        from services.batch5_store import Batch5Store
        with _db_session_factory(tmp_path) as sf:
            store = Batch5Store(sf)
            store.upsert_relationship("/tmp/a.txt", "/tmp/b.txt", "similar_to", 0.9,
                                      evidence={"reason": "r"})
            store2 = Batch5Store(sf)  # fresh store over same DB (restart)
            rels = store2.relationships_for_path("/tmp/a.txt")
            assert len(rels) == 1
            assert rels[0].relationship_type == "similar_to"


class _DupEngineStub:
    def find_exact_duplicates_for_file(self, path):
        from services.batch5_models import DuplicateGroup
        return DuplicateGroup(checksum="x" * 64, files=["/tmp/a.txt", "/tmp/b.txt"])


class _SimStub:
    def near_duplicates(self, path):
        return []


class _GraphStub:
    def files_sharing_entities(self, path, limit=25):
        return ["/tmp/shared.pdf"]


# ================================================================
# B5-01 — Classification
# ================================================================

class TestClassification:
    def test_taxonomy_normalization(self):
        from services.classification_engine import normalize_category, category_from_extension
        assert normalize_category("Technical") == "code"
        assert normalize_category("technical") == "code"
        assert normalize_category("Research Paper") == "research"
        assert normalize_category("Presentation") == "presentation"
        assert normalize_category("") == "other"
        assert normalize_category("gibberish zzz") == "other"
        assert category_from_extension("/x/foo.py") == "code"
        assert category_from_extension("/x/deck.pptx") == "presentation"
        assert category_from_extension("/x/photo.png") == "image"
        assert category_from_extension("/x/data.xlsx") == "spreadsheet"

    def test_classify_file_persists(self, tmp_path):
        from services.classification_engine import ClassificationEngine
        from services.file_identity import calculate_sha256
        with _db_session_factory(tmp_path) as sf:
            f = tmp_path / "notes.md"
            f.write_text("# Notes\nSome research content here.\n", encoding="utf-8")
            engine = ClassificationEngine(sf)
            cat = engine.classify_file(str(f))
            assert cat is not None
            assert cat in {"document", "research", "other"}
            assert engine.category_for_path(str(f)) == cat
            assert engine.is_current(str(f))

    def test_modified_file_reclassified(self, tmp_path):
        from services.classification_engine import ClassificationEngine
        with _db_session_factory(tmp_path) as sf:
            f = tmp_path / "app.py"
            f.write_text("def main():\n    pass\n", encoding="utf-8")
            engine = ClassificationEngine(sf)
            engine.classify_file(str(f))
            assert engine.category_for_path(str(f)) == "code"
            f.write_text("import research\nimport pandas\n", encoding="utf-8")
            # content changed → recompute (extension still code)
            engine.classify_file(str(f))
            assert engine.category_for_path(str(f)) == "code"

    def test_batch_classification_cancel(self, tmp_path):
        from services.classification_engine import ClassificationEngine
        with _db_session_factory(tmp_path) as sf:
            paths = []
            for i in range(3):
                p = tmp_path / f"f{i}.md"
                p.write_text(f"research topic {i}\n", encoding="utf-8")
                paths.append(str(p))
            cancel = threading.Event()
            cancel.set()  # cancel immediately
            engine = ClassificationEngine(sf)
            result = engine.classify_batch(paths, cancel_event=cancel)
            assert result["classified"] == 0  # cancelled before any work

    def test_cache_invalidation_version(self, tmp_path):
        from services.classification_engine import ClassificationEngine
        with _db_session_factory(tmp_path) as sf:
            f = tmp_path / "x.md"
            f.write_text("content", encoding="utf-8")
            ClassificationEngine(sf, version="1.0").classify_file(str(f))
            assert ClassificationEngine(sf, version="1.0").is_current(str(f))
            assert not ClassificationEngine(sf, version="2.0").is_current(str(f))


# ================================================================
# B5-02 — Auto-tagging
# ================================================================

class TestTagging:
    def test_normalization(self):
        from services.tagging_engine import canonical_tag, normalize_tags
        assert canonical_tag("Machine Learning") == "machine-learning"
        assert canonical_tag("machine_learning") == "machine-learning"
        assert canonical_tag(" machine learning ") == "machine-learning"
        assert normalize_tags(["Machine Learning", "machine-learning", "ML"]) == ["machine-learning", "ml"]
        assert normalize_tags(["a"]) == []  # below min length

    def test_generate_and_persist(self, tmp_path):
        from services.tagging_engine import TaggingEngine
        with _db_session_factory(tmp_path) as sf:
            f = tmp_path / "ml_notes.md"
            f.write_text("machine learning research\n", encoding="utf-8")
            engine = TaggingEngine(sf)
            tags = engine.generate_tags(str(f))
            assert tags  # at least the filename stem tag
            assert engine.tags_for_path(str(f)) == tags
            assert engine.is_current(str(f))

    def test_manual_add_remove_rename(self, tmp_path):
        from services.tagging_engine import TaggingEngine
        with _db_session_factory(tmp_path) as sf:
            f = tmp_path / "notes.md"
            f.write_text("content\n", encoding="utf-8")
            engine = TaggingEngine(sf)
            engine.generate_tags(str(f))
            tags = engine.add_tag(str(f), "Important")
            assert "important" in tags
            tags = engine.rename_tag(str(f), "important", "priority")
            assert "priority" in tags and "important" not in tags
            tags = engine.remove_tag(str(f), "priority")
            assert "priority" not in tags


# ================================================================
# B5-09 — Saved searches
# ================================================================

class TestSavedSearches:
    def _manager(self, tmp_path):
        from services.batch5_store import Batch5Store
        from services.saved_search_manager import SavedSearchManager
        with _db_session_factory(tmp_path) as sf:
            store = Batch5Store(sf)
            return SavedSearchManager(store, retrieval=_MockRetrievalSearch())

    def test_crud(self, tmp_path):
        manager = self._manager(tmp_path)
        sid = manager.create("Papers", "neural networks", scope="workspace", modality="all")
        saved = manager.get(sid)
        assert saved.name == "Papers"
        assert saved.query == "neural networks"
        assert manager.rename(sid, "ML Papers")
        assert manager.get(sid).name == "ML Papers"
        assert manager.delete(sid)
        assert manager.get(sid) is None

    def test_empty_name_rejected(self, tmp_path):
        manager = self._manager(tmp_path)
        with pytest.raises(ValueError):
            manager.create("", "query")

    def test_execute_reflects_current_index(self, tmp_path):
        manager = self._manager(tmp_path)
        sid = manager.create("Papers", "neural networks")
        result = manager.execute(sid, top_k=5, threshold=0.0)
        assert result["results"]  # mock returns hits
        # re-run again — fresh against the current index
        result2 = manager.execute(sid)
        assert result2["name"] == "Papers"

    def test_restart_persistence(self, tmp_path):
        from services.batch5_store import Batch5Store
        from services.saved_search_manager import SavedSearchManager
        with _db_session_factory(tmp_path) as sf:
            store = Batch5Store(sf)
            manager = SavedSearchManager(store, retrieval=_MockRetrievalSearch())
            sid = manager.create("Persistent", "query")
            manager2 = SavedSearchManager(Batch5Store(sf), retrieval=_MockRetrievalSearch())
            assert manager2.get(sid) is not None


class _MockRetrievalSearch:
    def smart_retrieve(self, query, top_k=10, threshold=0.3):
        from engines.retrieval_engine import RetrievalResponse
        from engines import RetrievalResult
        return RetrievalResponse(
            query=query, scope="workspace",
            results=[RetrievalResult(
                chunk_id="c1", text="result", score=0.8, rank=0,
                file_path="/tmp/hit.pdf", file_hash="h", source_type="page",
                source_index=0, source_label="Page 1", char_start=0, char_end=5,
            )],
            total_found=1, elapsed_ms=1.0,
        )


# ================================================================
# B5-03 — Smart collections
# ================================================================

class TestCollections:
    def _setup(self, tmp_path):
        from services.batch5_store import Batch5Store
        from services.collection_engine import CollectionEngine
        with _db_session_factory(tmp_path) as sf:
            store = Batch5Store(sf)
            return store, CollectionEngine(store)

    def test_crud(self, tmp_path):
        store, engine = self._setup(tmp_path)
        cid = engine.create("Research", is_smart=False)
        assert cid > 0
        assert engine.rename(cid, "Research Papers")
        assert engine.get(cid).name == "Research Papers"
        assert engine.delete(cid)
        assert engine.get(cid) is None

    def test_static_membership_deduped(self, tmp_path):
        store, engine = self._setup(tmp_path)
        cid = engine.create("Favorites")
        assert engine.add_member(cid, "/tmp/a.txt")
        assert engine.add_member(cid, "/tmp/a.txt")  # dedup
        assert engine.member_paths(cid) == ["/tmp/a.txt"]

    def test_smart_criteria_extension(self, tmp_path):
        store, engine = self._setup(tmp_path)
        cid = engine.create("PDFs", is_smart=True, criteria={"extension": ".pdf"})
        with store._session_factory() as s:
            _indexed_record(s, "/tmp/a.pdf", "a" * 64, ext=".pdf")
            _indexed_record(s, "/tmp/b.txt", "b" * 64, ext=".txt")
            s.commit()
        matches = engine.evaluate_criteria({"extension": ".pdf"})
        assert matches == ["/tmp/a.pdf"]

    def test_smart_refresh_replaces_membership(self, tmp_path):
        store, engine = self._setup(tmp_path)
        cid = engine.create("PDFs", is_smart=True, criteria={"extension": ".pdf"})
        with store._session_factory() as s:
            _indexed_record(s, "/tmp/a.pdf", "a" * 64, ext=".pdf")
            s.commit()
        assert engine.refresh(cid) == 1
        # add another matching file → refresh includes it
        with store._session_factory() as s:
            _indexed_record(s, "/tmp/b.pdf", "b" * 64, ext=".pdf")
            s.commit()
        assert engine.refresh(cid) == 2

    def test_deleted_file_cleanup(self, tmp_path):
        from services.file_cleanup import _remove_collection_membership
        store, engine = self._setup(tmp_path)
        cid = engine.create("X")
        engine.add_member(cid, "/tmp/gone.pdf")
        _remove_collection_membership(store._session_factory, "/tmp/gone.pdf")
        assert engine.member_paths(cid) == []


# ================================================================
# B5-08 — Organization suggestions
# ================================================================

class TestSuggestions:
    def _setup(self, tmp_path):
        from services.batch5_store import Batch5Store
        from services.suggestion_engine import SuggestionEngine
        with _db_session_factory(tmp_path) as sf:
            store = Batch5Store(sf)
            return store, SuggestionEngine(store=store)

    def test_no_collections_no_suggestions(self, tmp_path):
        store, engine = self._setup(tmp_path)
        f = tmp_path / "notes.md"
        f.write_text("content\n", encoding="utf-8")
        assert engine.suggest_for_file(str(f)) == []

    def test_suggestion_persistence_and_status(self, tmp_path):
        store, engine = self._setup(tmp_path)
        sid = store.create_suggestion("/tmp/a.txt", "ML", "collection", "related", 0.9)
        assert store.get_suggestion(sid).status == "pending"
        assert store.set_suggestion_status(sid, "accepted")
        assert store.get_suggestion(sid).status == "accepted"

    def test_dismiss(self, tmp_path):
        store, engine = self._setup(tmp_path)
        sid = store.create_suggestion("/tmp/a.txt", "ML", "collection", "r", 0.8)
        assert engine.dismiss(sid)
        assert store.get_suggestion(sid).status == "dismissed"

    def test_invalid_target_rejected(self, tmp_path):
        store, engine = self._setup(tmp_path)
        sid = store.create_suggestion("/tmp/a.txt", "NonExistent", "collection", "r", 0.9)
        # accept fails when no matching collection exists → expired
        assert not engine.accept(sid)
        assert store.get_suggestion(sid).status == "expired"


# ================================================================
# B5-10 — Knowledge dashboard
# ================================================================

class TestDashboard:
    def test_aggregates(self, tmp_path):
        from services.batch5_store import Batch5Store
        from services.collection_engine import CollectionEngine
        from services.dashboard_service import DashboardService
        with _db_session_factory(tmp_path) as sf:
            with sf() as s:
                _indexed_record(s, "/tmp/a.pdf", "a" * 64, ext=".pdf")
                _indexed_record(s, "/tmp/b.txt", "b" * 64, ext=".txt")
                s.commit()
            store = Batch5Store(sf)
            engine = CollectionEngine(store)
            engine.create("Research")
            service = DashboardService(session_factory=sf, collection_engine=engine)
            snap = service.snapshot()
            assert snap["files"]["total"] == 2
            assert snap["files"]["by_extension"][".pdf"] == 1
            assert snap["collections"]["total"] == 1

    def test_empty_state(self, tmp_path):
        from services.dashboard_service import DashboardService
        with _db_session_factory(tmp_path) as sf:
            service = DashboardService(session_factory=sf)
            snap = service.snapshot()
            assert snap["files"]["total"] == 0
            assert snap["ai"]["analyzed"] == 0

    def test_stale_file_excluded(self, tmp_path):
        """Dashboard counts only rows present in the index."""
        from services.dashboard_service import DashboardService
        with _db_session_factory(tmp_path) as sf:
            # an ai_analysis row for a hash not in indexed_files must be ignored
            from database.models import AIAnalysis
            with sf() as s:
                s.add(AIAnalysis(file_hash="zz" * 32, summary="stale"))
                s.commit()
            service = DashboardService(session_factory=sf)
            assert service.ai_stats()["analyzed"] == 0

    def test_refresh_method(self, tmp_path):
        """DashboardService.refresh re-queries and returns a fresh snapshot."""
        from services.dashboard_service import DashboardService
        f = tmp_path / "valid.txt"
        f.write_text("sample content")
        with _db_session_factory(tmp_path) as sf:
            with sf() as s:
                _indexed_record(s, str(f), "v" * 64, ext=".txt")
                s.commit()
            service = DashboardService(session_factory=sf)
            snap = service.refresh()
            assert "files" in snap
            assert "ai" in snap
            assert "semantic" in snap
            assert snap["files"]["total"] == 1


# ================================================================
# Deletion cleanup orchestration (Batch 5 §3.1)
# ================================================================

class TestDeletionCleanup:
    def test_cleanup_removes_all_derived_state(self, tmp_path):
        from services.batch5_store import Batch5Store
        from services.file_cleanup import cleanup_deleted_file
        with _db_session_factory(tmp_path) as sf:
            store = Batch5Store(sf)
            # Batch-1 index row + collection membership + relationships + suggestion
            with sf() as s:
                _indexed_record(s, "/tmp/gone.pdf", "g" * 64, ext=".pdf")
                s.commit()
            cid = store.create_collection("X")
            store.add_item(cid, "/tmp/gone.pdf")
            store.upsert_relationship("/tmp/gone.pdf", "/tmp/other.pdf", "related_to")
            store.create_suggestion("/tmp/gone.pdf", "X", "collection", "r", 0.9)

            report = cleanup_deleted_file(
                abs_path="/tmp/gone.pdf",
                session_factory=sf,
            )
            assert report["indexed_row"] is True
            assert report["collection_members"] == 1
            assert report["relationships"] == 1
            assert report["suggestions"] == 1

            # Nothing references the deleted path anymore.
            assert store.collections_for_path("/tmp/gone.pdf") == []
            assert store.relationships_for_path("/tmp/gone.pdf") == []
            assert store.suggestions_for_path("/tmp/gone.pdf") == []

    def test_cleanup_missing_file_safe(self, tmp_path):
        from services.file_cleanup import cleanup_deleted_file
        with _db_session_factory(tmp_path) as sf:
            report = cleanup_deleted_file("/never/existed.pdf", session_factory=sf)
            assert report["indexed_row"] is False

    def test_cleanup_removes_indexed_row(self, tmp_path):
        from services.file_cleanup import cleanup_deleted_file
        with _db_session_factory(tmp_path) as sf:
            with sf() as s:
                _indexed_record(s, "/tmp/gone.txt", "h" * 64)
                s.commit()
            cleanup_deleted_file("/tmp/gone.txt", session_factory=sf)
            from services.sqlite_indexer import IndexedFile
            with sf() as s:
                assert s.query(IndexedFile).filter_by(absolute_path="/tmp/gone.txt").count() == 0


# ================================================================
# UI smoke tests (offscreen)
# ================================================================

class TestBatch5UI:
    def test_duplicate_dialog_renders(self, qapp, qtbot, tmp_path):
        from services.batch5_models import DuplicateGroup
        from ui.dialogs.duplicate_dialog import DuplicateDialog
        groups = [DuplicateGroup(checksum="a" * 64, files=["/tmp/a.txt", "/tmp/b.txt"])]
        dlg = DuplicateDialog(groups)
        qtbot.addWidget(dlg)
        dlg.show()
        assert dlg.summary_label.text().startswith("1 duplicate group")
        assert dlg.files_list.count() == 2

    def test_duplicate_dialog_empty_state(self, qapp, qtbot):
        from ui.dialogs.duplicate_dialog import DuplicateDialog
        dlg = DuplicateDialog([])
        qtbot.addWidget(dlg)
        assert "No duplicate files" in dlg.summary_label.text()

    def test_similar_dialog_renders(self, qapp, qtbot):
        from services.batch5_models import SimilarFileResult
        from ui.dialogs.similar_files_dialog import SimilarFilesDialog
        dlg = SimilarFilesDialog(
            "/tmp/src.txt",
            similar=[SimilarFileResult("/tmp/dup.pdf", 0.95, matched_chunks=2)],
        )
        qtbot.addWidget(dlg)
        dlg.show()
        assert dlg.results_list.count() == 1
        assert "Very Similar" in dlg.results_list.item(0).text()

    def test_relationships_dialog(self, qapp, qtbot):
        from services.batch5_models import FileRelationshipInfo
        from ui.dialogs.file_relationships_dialog import FileRelationshipsDialog
        dlg = FileRelationshipsDialog(
            "/tmp/a.txt",
            [FileRelationshipInfo(id=1, source_path="/tmp/a.txt", target_path="/tmp/b.txt",
                                  relationship_type="duplicate_of", confidence=1.0)],
        )
        qtbot.addWidget(dlg)
        dlg.show()
        assert dlg.rel_list.count() == 1
        assert "duplicate_of" in dlg.rel_list.item(0).text()

    def test_saved_searches_dialog(self, qapp, qtbot, tmp_path):
        from services.batch5_store import Batch5Store
        from services.saved_search_manager import SavedSearchManager
        from ui.dialogs.saved_searches_dialog import SavedSearchesDialog
        with _db_session_factory(tmp_path) as sf:
            manager = SavedSearchManager(Batch5Store(sf), retrieval=_MockRetrievalSearch())
            manager.create("Papers", "neural networks")
            dlg = SavedSearchesDialog(manager)
            qtbot.addWidget(dlg)
            dlg.show()
            assert dlg.search_list.count() == 1

    def test_collections_dialog(self, qapp, qtbot, tmp_path):
        from services.batch5_store import Batch5Store
        from services.collection_engine import CollectionEngine
        from ui.dialogs.collections_dialog import CollectionsDialog
        with _db_session_factory(tmp_path) as sf:
            engine = CollectionEngine(Batch5Store(sf))
            engine.create("Research")
            dlg = CollectionsDialog(engine)
            qtbot.addWidget(dlg)
            dlg.show()
            assert dlg.collection_list.count() == 1

    def test_suggestion_dialog(self, qapp, qtbot, tmp_path):
        from services.batch5_models import SuggestionInfo
        from ui.dialogs.suggestion_dialog import SuggestionDialog
        dlg = SuggestionDialog(
            engine=None,
            file_path="/tmp/a.txt",
            suggestions=[SuggestionInfo(id=1, file_path="/tmp/a.txt",
                                        suggested_target="ML", confidence=0.9, reason="related")],
        )
        qtbot.addWidget(dlg)
        dlg.show()
        assert dlg.sugg_list.count() == 1

    def test_dashboard_dialog(self, qapp, qtbot, tmp_path):
        from services.dashboard_service import DashboardService
        from ui.dialogs.dashboard_dialog import DashboardDialog
        with _db_session_factory(tmp_path) as sf:
            service = DashboardService(session_factory=sf)
            dlg = DashboardDialog(service)
            qtbot.addWidget(dlg)
            dlg.show()
            assert "0 indexed" in dlg.files_box.layout().itemAt(0).widget().text()
            assert hasattr(dlg, "refresh_btn")
            assert "Last updated:" in dlg.last_updated_label.text()

            # Click refresh button and verify it stays responsive
            dlg.refresh_btn.click()
            assert dlg.refresh_btn.isEnabled()
            assert "Last updated:" in dlg.last_updated_label.text()

    def test_semantic_search_save_flow(self, qapp, qtbot, tmp_path):
        """Save Search inside the semantic search dialog persists via manager."""
        from services.batch5_store import Batch5Store
        from services.saved_search_manager import SavedSearchManager
        from ui.dialogs.semantic_search_dialog import SemanticSearchDialog
        with _db_session_factory(tmp_path) as sf:
            manager = SavedSearchManager(Batch5Store(sf), retrieval=_MockRetrievalSearch())
            dlg = SemanticSearchDialog()
            qtbot.addWidget(dlg)
            dlg.set_saved_search_manager(manager)
            dlg.search_input.setText("quantum computing")
            # Directly exercise the save path.
            from unittest.mock import patch
            with patch("PySide6.QtWidgets.QInputDialog.getText", return_value=("QC", True)):
                dlg._on_save_search()
            assert manager.list()[0].name == "QC"
            assert manager.list()[0].query == "quantum computing"

    def test_dashboard_auto_refreshes_on_signals(self, qapp, qtbot, tmp_path):
        """Dashboard dialog refreshes when any Batch-5 organization signal fires.

        Mirrors the MainWindow wiring: the dialog subscribes to all seven
        SignalBus signals and re-aggregates on every emission.
        """
        from app.signal_bus import SignalBus
        from services.dashboard_service import DashboardService
        from ui.dialogs.dashboard_dialog import DashboardDialog

        with _db_session_factory(tmp_path) as sf:
            bus = SignalBus()
            service = DashboardService(session_factory=sf)
            dlg = DashboardDialog(service)
            qtbot.addWidget(dlg)
            dlg.show()
            for sig in (
                bus.classification_updated,
                bus.tags_updated,
                bus.duplicates_updated,
                bus.relationships_updated,
                bus.collection_updated,
                bus.saved_search_updated,
                bus.organization_suggestion_updated,
            ):
                sig.connect(dlg.refresh)

            refresh_count = []
            original_refresh = dlg.refresh
            def counting_refresh():
                refresh_count.append(1)
                return original_refresh()
            dlg.refresh = counting_refresh  # type: ignore[method-assign]

            # Every signal must actually fire refresh (not a silent no-op).
            bus.classification_updated.emit("/tmp/a.txt")
            bus.tags_updated.emit("/tmp/a.txt")
            bus.duplicates_updated.emit()
            bus.relationships_updated.emit()
            bus.collection_updated.emit(1)
            bus.saved_search_updated.emit(2)
            bus.organization_suggestion_updated.emit(3)
            assert len(refresh_count) == 7, refresh_count

    def test_collections_dialog_on_changed_hook(self, qapp, qtbot, tmp_path):
        """Collections dialog fires on_changed after mutations (dashboard wiring)."""
        from unittest.mock import patch
        from services.batch5_store import Batch5Store
        from services.collection_engine import CollectionEngine
        from ui.dialogs.collections_dialog import CollectionsDialog
        with _db_session_factory(tmp_path) as sf:
            engine = CollectionEngine(Batch5Store(sf))
            engine.create("Research")
            changed = []
            dlg = CollectionsDialog(engine, on_changed=lambda: changed.append(1))
            qtbot.addWidget(dlg)
            dlg.show()

            # Create via the dialog path.
            with patch("PySide6.QtWidgets.QInputDialog.getText", return_value=("ML", True)):
                dlg._on_new()
            assert len(changed) == 1, changed

            # Delete via the dialog path.
            dlg.collection_list.setCurrentRow(0)
            from PySide6.QtWidgets import QMessageBox as _MB
            with patch("PySide6.QtWidgets.QMessageBox.question",
                       return_value=_MB.StandardButton.Yes):
                dlg._on_delete()
            assert len(changed) == 2, changed

    def test_saved_searches_dialog_on_changed_hook(self, qapp, qtbot, tmp_path):
        """Saved Searches dialog fires on_changed on rename/delete."""
        from unittest.mock import patch
        from services.batch5_store import Batch5Store
        from services.saved_search_manager import SavedSearchManager
        from ui.dialogs.saved_searches_dialog import SavedSearchesDialog
        with _db_session_factory(tmp_path) as sf:
            manager = SavedSearchManager(Batch5Store(sf), retrieval=_MockRetrievalSearch())
            manager.create("Papers", "neural networks")
            changed = []
            dlg = SavedSearchesDialog(manager, on_changed=lambda: changed.append(1))
            qtbot.addWidget(dlg)
            dlg.show()
            dlg.search_list.setCurrentRow(0)

            # Rename fires the hook.
            with patch("PySide6.QtWidgets.QInputDialog.getText", return_value=("ML Papers", True)):
                dlg._on_rename_clicked()
            assert len(changed) == 1, changed

            # Re-select after refresh (rename cleared the selection).
            dlg.search_list.setCurrentRow(0)

            # Delete fires the hook.
            from PySide6.QtWidgets import QMessageBox as _MB
            with patch("PySide6.QtWidgets.QMessageBox.question",
                       return_value=_MB.StandardButton.Yes):
                dlg._on_delete_clicked()
            assert len(changed) == 2, changed
