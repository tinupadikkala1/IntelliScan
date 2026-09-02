"""Batch 5 end-to-end persistence tests.

Simulates an application restart (a fresh SQLAlchemy engine + session factory
over the same database file) and verifies every persisted Batch-5 artifact
survives:

- classifications (B5-01) and tags (B5-02) — keyed by content hash,
- collections — static members + smart membership (B5-03),
- saved semantic searches (B5-09),
- file relationships (B5-07) — including acceptance status of suggestions
  (B5-08).

The second test also verifies the delete → reindex cycle keeps everything
consistent: deleting a file removes its indexed row, relationships,
collection membership and suggestions; re-indexing it restores the derived
state (duplicate_of edges, classification currency).

All tests run WITHOUT Ollama / FAISS; similarity is stubbed as empty and
classification/tagging use their deterministic paths.
"""

import os
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

_EMPTY_HASH = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"


def _make_session_factory(db_path: str):
    """Create a brand-new SQLAlchemy engine + Session over a DB file.

    Calling this twice on the same path simulates an application restart:
    fresh engine, fresh session, same on-disk data.
    """
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from database.migrations import run_migrations
    from database.models import Base

    engine = create_engine(f"sqlite:///{db_path}", echo=False)
    Base.metadata.create_all(engine)
    run_migrations(engine)
    Session = sessionmaker(bind=engine)
    return Session


def _index_file(sf, path: str, checksum: str, size: int, ext: str) -> None:
    """Insert an indexed_files row (Batch-1 index) for a path."""
    from services.sqlite_indexer import IndexedFile

    with sf() as s:
        s.add(IndexedFile(
            filename=os.path.basename(path),
            absolute_path=os.path.abspath(path),
            size=size,
            mime_type="text/plain",
            extension=ext,
            checksum=checksum,
            extracted_text="content",
            indexing_status="completed",
        ))
        s.commit()


def _seed_workspace(tmp_path) -> dict:
    """Create three files: a duplicate pair (same content) + a distinct file.

    Returns {"a", "b", "c"} absolute paths.
    """
    from services.file_identity import calculate_sha256

    base = tmp_path
    a = str(base / "ml_notes.txt")
    b = str(base / "ml_notes_copy.txt")
    c = str(base / "project_roadmap.md")
    # Identical content → exact duplicates (same SHA-256).
    content = "machine learning research on neural networks.\n" * 30
    Path(a).write_text(content, encoding="utf-8")
    Path(b).write_text(content, encoding="utf-8")
    Path(c).write_text("# Project Roadmap\nPhase 1: index everything.\n" * 20, encoding="utf-8")
    return {"a": a, "b": b, "c": c}


class _EmptySimilarity:
    """Stands in for FileSimilarityService when no FAISS index exists."""

    def similar_files(self, file_path):
        return []

    def near_duplicates(self, file_path):
        return []


class _RelatedStub:
    """Returns one related file for suggestion scoring (no FAISS)."""

    def __init__(self, related_path):
        self._related = related_path

    def related_files(self, file_path):
        from services.batch5_models import RelatedFileResult
        return [RelatedFileResult(file_path=self._related, score=0.9, reason="stub")]


def _build_full_state(sf, paths: dict) -> dict:
    """Create every persisted Batch-5 artifact; returns handles for asserts."""
    from services.batch5_store import Batch5Store
    from services.classification_engine import ClassificationEngine
    from services.collection_engine import CollectionEngine
    from services.file_identity import calculate_sha256
    from services.relationship_engine import RelationshipEngine
    from services.saved_search_manager import SavedSearchManager
    from services.suggestion_engine import SuggestionEngine
    from services.tagging_engine import TaggingEngine

    # Index the three files (Batch-1 index).
    for key in ("a", "b", "c"):
        p = paths[key]
        _index_file(sf, p, calculate_sha256(p), os.path.getsize(p),
                    os.path.splitext(p)[1])

    # B5-01 classification + B5-02 tags (deterministic, no LLM).
    classifier = ClassificationEngine(sf)
    tagger = TaggingEngine(sf)
    categories = {k: classifier.classify_file(paths[k]) for k in ("a", "b", "c")}
    tags = {k: tagger.generate_tags(paths[k]) for k in ("a", "b", "c")}

    # B5-03 collections: static + smart.
    store = Batch5Store(sf)
    col_engine = CollectionEngine(store, classifier=classifier, tagger=tagger)
    static_id = store.create_collection("Static Favorites", description="manual")
    store.add_item(static_id, paths["a"], source="manual")
    store.add_item(static_id, paths["b"], source="manual")
    smart_id = store.create_collection(
        "Markdown docs", is_smart=True, criteria={"extension": ".md"},
    )
    col_engine.refresh(smart_id)  # evaluates criteria → c.md

    # B5-09 saved search.
    search_manager = SavedSearchManager(store, retrieval=None)
    search_id = search_manager.create(
        "ML Papers", "machine learning research", scope="workspace", modality="all",
    )

    # B5-07 file relationships — real DuplicateEngine on the DB.
    from engines.duplicate_engine import DuplicateEngine
    rel_engine = RelationshipEngine(
        store=store,
        duplicates=DuplicateEngine(sf),
        similarity=_EmptySimilarity(),
        graph_store=None,
    )
    created_rels = rel_engine.build_for_file(paths["a"])  # a --duplicate_of--> b

    # B5-08 organization suggestions — deterministic scoring via stub.
    sug_engine = SuggestionEngine(
        store=store,
        related=_RelatedStub(paths["b"]),
        classifier=classifier,
        tagger=tagger,
        collection_engine=col_engine,
        rag=None,
        min_confidence=0.5,
    )
    suggestions = sug_engine.suggest_for_file(paths["a"])
    # The related stub points at a real static member (b), so a suggestion
    # for "Static Favorites" must be produced deterministically.
    assert suggestions, "expected at least one suggestion for the static collection"
    accepted_suggestion_id = suggestions[0].id
    assert sug_engine.accept(accepted_suggestion_id)

    return {
        "store": store,
        "classifier": classifier,
        "tagger": tagger,
        "categories": categories,
        "tags": tags,
        "static_id": static_id,
        "smart_id": smart_id,
        "search_id": search_id,
        "rel_engine": rel_engine,
        "created_rels": created_rels,
        "accepted_suggestion_id": accepted_suggestion_id,
    }


# ================================================================
# Restart survival
# ================================================================

class TestRestartPersistence:
    def test_full_state_survives_restart(self, tmp_path):
        db_path = str(tmp_path / "e2e_restart.db")
        sf1 = _make_session_factory(db_path)
        paths = _seed_workspace(tmp_path)
        handles = _build_full_state(sf1, paths)

        # Fresh engine + session factory over the same file = "app restart".
        sf2 = _make_session_factory(db_path)

        from services.batch5_store import Batch5Store
        from services.classification_engine import ClassificationEngine
        from services.tagging_engine import TaggingEngine

        store2 = Batch5Store(sf2)
        classifier2 = ClassificationEngine(sf2)
        tagger2 = TaggingEngine(sf2)

        # --- Classifications survive (hash-keyed) ---
        for key in ("a", "b", "c"):
            assert classifier2.category_for_path(paths[key]) == handles["categories"][key]
            assert classifier2.is_current(paths[key]), f"classification stale for {key}"

        # --- Tags survive ---
        # a and b share identical content → one ai_analysis row keyed by
        # content hash, so they resolve to the same persisted tag set.
        assert tagger2.tags_for_path(paths["a"]) == tagger2.tags_for_path(paths["b"])
        assert tagger2.tags_for_path(paths["a"])  # non-empty (stem tag)
        assert tagger2.tags_for_path(paths["c"]) == handles["tags"]["c"]

        # --- Collections survive (static members + smart membership) ---
        cols = store2.list_collections()
        by_name = {c.name: c for c in cols}
        assert "Static Favorites" in by_name
        static = by_name["Static Favorites"]
        assert not static.is_smart
        assert set(store2.collection_paths(static.id)) == {
            os.path.abspath(paths["a"]), os.path.abspath(paths["b"]),
        }
        assert "Markdown docs" in by_name
        smart = by_name["Markdown docs"]
        assert smart.is_smart
        assert set(store2.collection_paths(smart.id)) == {os.path.abspath(paths["c"])}

        # --- Saved search survives ---
        saved = store2.get_saved_search(handles["search_id"])
        assert saved is not None
        assert saved.name == "ML Papers"
        assert saved.query == "machine learning research"

        # --- File relationships survive ---
        rels = store2.relationships_for_path(paths["a"])
        dup = [r for r in rels if r.relationship_type == "duplicate_of"]
        assert len(dup) == 1
        assert dup[0].target_path == os.path.abspath(paths["b"])
        assert dup[0].confidence == 1.0
        assert dup[0].evidence.get("reason")

        # --- Suggestions survive, including accepted status ---
        # ``_build_full_state`` guarantees a suggestion was created + accepted.
        sug = store2.get_suggestion(handles["accepted_suggestion_id"])
        assert sug is not None
        assert sug.status == "accepted"
        assert sug.suggested_target == "Static Favorites"

    def test_duplicates_still_grouped_after_restart(self, tmp_path):
        """DuplicateEngine is DB-driven → groups survive a restart."""
        from engines.duplicate_engine import DuplicateEngine

        db_path = str(tmp_path / "e2e_dup.db")
        sf1 = _make_session_factory(db_path)
        paths = _seed_workspace(tmp_path)
        _build_full_state(sf1, paths)

        sf2 = _make_session_factory(db_path)
        groups = DuplicateEngine(sf2).find_exact_duplicates()
        assert len(groups) == 1
        assert set(groups[0].files) == {os.path.abspath(paths["a"]), os.path.abspath(paths["b"])}


# ================================================================
# Delete → reindex consistency
# ================================================================

class TestDeleteReindex:
    def test_delete_then_reindex_restores_state(self, tmp_path):
        from services.batch5_store import Batch5Store
        from services.file_cleanup import cleanup_deleted_file

        db_path = str(tmp_path / "e2e_reindex.db")
        sf1 = _make_session_factory(db_path)
        paths = _seed_workspace(tmp_path)
        handles = _build_full_state(sf1, paths)
        store1 = handles["store"]

        # --- DELETE b (the duplicate copy) ---
        report = cleanup_deleted_file(
            abs_path=paths["b"],
            session_factory=sf1,
            retrieval=None,
            db_store=None,
            graph_engine=None,
            vector_engine=None,
        )
        assert report["indexed_row"] is True
        assert report["relationships"] >= 1   # a --duplicate_of--> b removed
        # b was a manual member of the static collection → removed too.
        assert report["collection_members"] == 1

        # Verify no stale state references b.
        assert store1.relationships_for_path(paths["b"]) == []
        assert store1.suggestions_for_path(paths["b"]) == []
        assert paths["b"] not in store1.collection_paths(handles["smart_id"])

        from services.sqlite_indexer import IndexedFile
        with sf1() as s:
            assert s.query(IndexedFile).filter_by(
                absolute_path=os.path.abspath(paths["b"])
            ).count() == 0

        # --- REINDEX b (same content → same hash) ---
        from services.file_identity import calculate_sha256
        _index_file(sf1, paths["b"], calculate_sha256(paths["b"]),
                    os.path.getsize(paths["b"]), os.path.splitext(paths["b"])[1])

        # Classification is immediately current (content hash unchanged).
        assert handles["classifier"].is_current(paths["b"])
        assert handles["classifier"].category_for_path(paths["b"]) == handles["categories"]["b"]

        # Rebuild relationships → duplicate_of edge returns.
        created = handles["rel_engine"].build_for_file(paths["a"])
        assert created >= 1
        rels = store1.relationships_for_path(paths["a"])
        dup = [r for r in rels if r.relationship_type == "duplicate_of"
               and r.target_path == os.path.abspath(paths["b"])]
        assert len(dup) == 1

        # --- Restart after reindex: everything consistent ---
        sf2 = _make_session_factory(db_path)
        store2 = Batch5Store(sf2)
        rels2 = store2.relationships_for_path(paths["a"])
        assert any(
            r.relationship_type == "duplicate_of"
            and r.target_path == os.path.abspath(paths["b"])
            for r in rels2
        )

    def test_delete_removes_suggestion_and_collection(self, tmp_path):
        """Deleting a file also drops its suggestions + collection rows."""
        from services.batch5_store import Batch5Store
        from services.file_cleanup import cleanup_deleted_file

        db_path = str(tmp_path / "e2e_delete.db")
        sf1 = _make_session_factory(db_path)
        paths = _seed_workspace(tmp_path)
        handles = _build_full_state(sf1, paths)
        store1 = handles["store"]

        # Attach a suggestion to b directly and add b to the static collection.
        sug_b = store1.create_suggestion(paths["b"], "Static Favorites", "collection", "manual", 0.7)
        store1.add_item(handles["static_id"], paths["b"], source="manual")

        report = cleanup_deleted_file(abs_path=paths["b"], session_factory=sf1)
        assert report["suggestions"] >= 1
        assert report["collection_members"] >= 1
        assert store1.get_suggestion(sug_b) is None  # gone

        # Static collection keeps the surviving member (a).
        assert store1.collection_paths(handles["static_id"]) == [os.path.abspath(paths["a"])]
