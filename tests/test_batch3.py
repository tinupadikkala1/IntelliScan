"""Batch 3 Tests — Unit + Integration tests for IntelliVault engines.

All tests run WITHOUT Ollama. HTTP calls are mocked.
"""

import os
import sys
import uuid
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

# Ensure project root is on path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from engines import (
    Citation,
    ContentBlock,
    ContentEngine,
    EmbeddingEngine,
    EvidenceChunk,
    EvidenceEngine,
    RAGEngine,
    RAGResponse,
    RetrievalEngine,
    RetrievalResponse,
    RetrievalResult,
    RetrievalScope,
    SearchResult,
    VectorEngine,
)
from engines.db_store import EngineDBStore


# ================================================================
# Helpers
# ================================================================

def _make_fake_embedding(dim=768):
    """Return a random normalized vector."""
    v = np.random.randn(dim).astype(np.float32)
    v /= np.linalg.norm(v)
    return v


def _make_correlated_vector(base, noise_scale=0.05):
    """Return a vector correlated to base (base + small noise), normalized."""
    v = base + np.random.randn(len(base)).astype(np.float32) * noise_scale
    v /= np.linalg.norm(v)
    return v


def _make_evidence_chunk(file_path="/tmp/test.txt", idx=0):
    """Create a synthetic EvidenceChunk."""
    return EvidenceChunk(
        chunk_id=uuid.uuid4().hex,
        text=f"This is evidence chunk number {idx} with some content for testing.",
        file_path=file_path,
        file_hash="abc123" * 5,
        source_type="section",
        source_index=idx,
        source_label=f"Section {idx + 1}",
        char_start=idx * 100,
        char_end=(idx + 1) * 100,
    )


@contextmanager
def _db_session_factory(tmp_path):
    """Create a SQLAlchemy session factory for a tmp database."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from database.models import Base

    db_path = str(tmp_path / "test_batch3.db")
    engine = create_engine(f"sqlite:///{db_path}", echo=False)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)

    @contextmanager
    def session_ctx():
        s = Session()
        try:
            yield s
        finally:
            s.close()

    yield session_ctx


# ================================================================
# UNIT TESTS
# ================================================================


class TestContentEngine:
    """Tests for UniversalContentEngine."""

    def test_content_engine_txt(self, tmp_path):
        """Extract ContentBlocks from tmp .txt file, verify source_type='section'."""
        txt_file = tmp_path / "sample.txt"
        txt_file.write_text("Hello world. " * 100)  # ~1300 chars, should produce multiple sections

        engine = ContentEngine()
        blocks = engine.extract(str(txt_file))

        assert len(blocks) > 0
        for block in blocks:
            assert isinstance(block, ContentBlock)
            assert block.source_type == "section"
            assert block.file_path == str(txt_file)
            assert block.text.strip() != ""
            assert "Section" in block.source_label

    def test_content_engine_unsupported(self, tmp_path):
        """Returns empty list for .mp3."""
        mp3_file = tmp_path / "audio.mp3"
        mp3_file.write_bytes(b"\x00" * 100)

        engine = ContentEngine()
        blocks = engine.extract(str(mp3_file))

        assert blocks == []


class TestEvidenceEngine:
    """Tests for EvidenceEngine."""

    def test_evidence_engine_chunking(self, tmp_path):
        """Build evidence from .txt, verify chunk_ids unique, overlap working."""
        txt_file = tmp_path / "evidence_test.txt"
        # Create enough text to ensure multiple chunks (chunk_size=400, overlap=50)
        txt_file.write_text("Word " * 500)  # 2500 chars

        engine = EvidenceEngine(chunk_size=400, chunk_overlap=50)
        chunks = engine.build_evidence(str(txt_file))

        assert len(chunks) > 1, "Should produce multiple chunks for large text"

        # Verify all chunk_ids are unique
        chunk_ids = [c.chunk_id for c in chunks]
        assert len(chunk_ids) == len(set(chunk_ids)), "chunk_ids must be unique"

        # Verify overlap: consecutive chunks from same source should overlap
        # Find chunks from the same source_index
        same_source = [c for c in chunks if c.source_index == 0]
        if len(same_source) > 1:
            for i in range(len(same_source) - 1):
                curr = same_source[i]
                nxt = same_source[i + 1]
                # With overlap, next chunk should start before current ends
                assert nxt.char_start < curr.char_end, "Overlap should mean next starts before current ends"

    def test_evidence_engine_source_labels(self, tmp_path):
        """Verify source_label format."""
        txt_file = tmp_path / "label_test.txt"
        txt_file.write_text("Test content for label verification. " * 50)

        engine = EvidenceEngine()
        chunks = engine.build_evidence(str(txt_file))

        assert len(chunks) > 0
        for chunk in chunks:
            # source_label should be 'Section N' format
            assert chunk.source_label.startswith("Section ")
            parts = chunk.source_label.split(" ")
            assert len(parts) == 2
            assert parts[1].isdigit()


class TestEmbeddingEngine:
    """Tests for EmbeddingEngine."""

    def test_embedding_engine_unavailable(self):
        """Mock requests to fail, verify returns None."""
        engine = EmbeddingEngine()

        with patch("engines.embedding_engine.requests.post") as mock_post:
            mock_post.side_effect = Exception("Connection refused")
            result = engine.embed_text("test text")
            assert result is None

        with patch("engines.embedding_engine.requests.get") as mock_get:
            mock_get.side_effect = Exception("Connection refused")
            assert engine.is_available() is False


class TestVectorEngine:
    """Tests for VectorEngine."""

    def test_vector_engine_add_search(self):
        """Add 5 vectors, search, verify results ordered by score."""
        engine = VectorEngine(dimension=768)

        # Create a base query vector
        query = _make_fake_embedding(768)

        # Add 5 vectors with varying similarity to query
        chunk_ids = []
        for i in range(5):
            cid = f"chunk_{i}"
            chunk_ids.append(cid)
            # Vectors closer to query will have higher similarity
            noise_scale = 0.1 * (i + 1)  # increasing noise = less similar
            vec = _make_correlated_vector(query, noise_scale=noise_scale)
            engine.add(cid, vec)

        assert engine.size == 5

        # Search
        results = engine.search(query, top_k=5, threshold=0.0)
        assert len(results) > 0

        # Verify ordered by score (descending)
        for i in range(len(results) - 1):
            assert results[i].score >= results[i + 1].score

    def test_vector_engine_remove(self):
        """Add then remove, verify size decreases."""
        engine = VectorEngine(dimension=768)

        # Add 3 vectors
        ids = ["a", "b", "c"]
        for cid in ids:
            engine.add(cid, _make_fake_embedding(768))

        assert engine.size == 3

        # Remove one
        removed = engine.remove_by_chunk_ids({"b"})
        assert removed == 1
        assert engine.size == 2

    def test_vector_engine_save_load(self, tmp_path):
        """Save to tmp file, load in new instance, verify same size."""
        index_path = str(tmp_path / "test_index.faiss")
        engine1 = VectorEngine(dimension=768, index_path=index_path)

        # Add vectors
        for i in range(4):
            engine1.add(f"chunk_{i}", _make_fake_embedding(768))

        assert engine1.size == 4
        engine1.save()

        # Load in new instance
        engine2 = VectorEngine(dimension=768, index_path=index_path)
        assert engine2.size == 4


class TestRetrievalEngine:
    """Tests for RetrievalEngine."""

    def test_retrieval_engine_retrieve(self):
        """Mock embedding, add chunks, retrieve, verify RetrievalResponse."""
        dim = 768
        base_vector = _make_fake_embedding(dim)

        # Create mock embedding engine
        mock_embed = MagicMock(spec=EmbeddingEngine)
        mock_embed.embed_text.return_value = base_vector
        mock_embed.dimension = dim

        # Create vector engine and add chunks
        vec_engine = VectorEngine(dimension=dim)
        chunks = [_make_evidence_chunk(idx=i) for i in range(3)]

        for chunk in chunks:
            vec = _make_correlated_vector(base_vector, noise_scale=0.02)
            vec_engine.add(chunk.chunk_id, vec)

        # Create retrieval engine
        evidence_store = {c.chunk_id: c for c in chunks}
        ret_engine = RetrievalEngine(
            embedding_engine=mock_embed,
            vector_engine=vec_engine,
            evidence_store=evidence_store,
        )

        # Retrieve
        response = ret_engine.retrieve("test query", scope=RetrievalScope.WORKSPACE)

        assert isinstance(response, RetrievalResponse)
        assert response.query == "test query"
        assert response.scope == "workspace"
        assert len(response.results) > 0
        assert response.embedding_available is True
        for r in response.results:
            assert isinstance(r, RetrievalResult)
            assert r.text != ""

    def test_retrieval_engine_file_filter(self):
        """Verify file_filter restricts results."""
        dim = 768
        base_vector = _make_fake_embedding(dim)

        mock_embed = MagicMock(spec=EmbeddingEngine)
        mock_embed.embed_text.return_value = base_vector
        mock_embed.dimension = dim

        vec_engine = VectorEngine(dimension=dim)

        # Create chunks from different files
        chunk_a = _make_evidence_chunk(file_path="/tmp/file_a.txt", idx=0)
        chunk_b = _make_evidence_chunk(file_path="/tmp/file_b.txt", idx=1)

        vec_engine.add(chunk_a.chunk_id, _make_correlated_vector(base_vector, 0.01))
        vec_engine.add(chunk_b.chunk_id, _make_correlated_vector(base_vector, 0.01))

        evidence_store = {
            chunk_a.chunk_id: chunk_a,
            chunk_b.chunk_id: chunk_b,
        }

        ret_engine = RetrievalEngine(
            embedding_engine=mock_embed,
            vector_engine=vec_engine,
            evidence_store=evidence_store,
        )

        # Retrieve with file_filter for only file_a
        response = ret_engine.retrieve(
            "test", scope=RetrievalScope.SELECTED_FILE,
            file_filter=["/tmp/file_a.txt"],
        )

        # All results should be from file_a
        for r in response.results:
            assert r.file_path == "/tmp/file_a.txt"


class TestRAGEngine:
    """Tests for RAGEngine."""

    def test_rag_engine_ask(self):
        """Mock embedding + mock Ollama, verify RAGResponse with citations."""
        dim = 768
        base_vector = _make_fake_embedding(dim)

        mock_embed = MagicMock(spec=EmbeddingEngine)
        mock_embed.embed_text.return_value = base_vector
        mock_embed.dimension = dim

        vec_engine = VectorEngine(dimension=dim)
        chunks = [_make_evidence_chunk(idx=i) for i in range(3)]

        for chunk in chunks:
            vec = _make_correlated_vector(base_vector, noise_scale=0.02)
            vec_engine.add(chunk.chunk_id, vec)

        evidence_store = {c.chunk_id: c for c in chunks}
        ret_engine = RetrievalEngine(
            embedding_engine=mock_embed,
            vector_engine=vec_engine,
            evidence_store=evidence_store,
        )

        rag_engine = RAGEngine(retrieval_engine=ret_engine)

        # Mock the Ollama generate call
        with patch("engines.rag_engine.requests.post") as mock_post:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "response": "Based on the evidence, the answer is 42."
            }
            mock_post.return_value = mock_response

            response = rag_engine.ask("What is the answer?")

        assert isinstance(response, RAGResponse)
        assert response.question == "What is the answer?"
        assert "42" in response.answer
        assert response.grounded is True
        assert len(response.citations) > 0
        assert response.retrieval_results > 0

    def test_rag_engine_offline(self):
        """Mock connection failure, verify grounded=False."""
        dim = 768
        base_vector = _make_fake_embedding(dim)

        mock_embed = MagicMock(spec=EmbeddingEngine)
        mock_embed.embed_text.return_value = base_vector
        mock_embed.dimension = dim

        vec_engine = VectorEngine(dimension=dim)
        chunks = [_make_evidence_chunk(idx=i) for i in range(2)]

        for chunk in chunks:
            vec = _make_correlated_vector(base_vector, noise_scale=0.02)
            vec_engine.add(chunk.chunk_id, vec)

        evidence_store = {c.chunk_id: c for c in chunks}
        ret_engine = RetrievalEngine(
            embedding_engine=mock_embed,
            vector_engine=vec_engine,
            evidence_store=evidence_store,
        )

        rag_engine = RAGEngine(retrieval_engine=ret_engine)

        # Mock connection failure
        with patch("engines.rag_engine.requests.post") as mock_post:
            mock_post.side_effect = Exception("Connection refused")

            response = rag_engine.ask("What is the answer?")

        assert isinstance(response, RAGResponse)
        assert response.grounded is False


class TestDBStore:
    """Tests for EngineDBStore."""

    def test_db_store_evidence_crud(self, tmp_path):
        """Store, load, delete evidence in tmp DB."""
        with _db_session_factory(tmp_path) as session_factory:
            store = EngineDBStore(session_factory)

            # Create chunks
            chunks = [_make_evidence_chunk(file_path="/tmp/crud_test.txt", idx=i) for i in range(3)]

            # Store
            stored = store.store_evidence(chunks)
            assert stored == 3

            # Load
            loaded = store.get_evidence_by_file("/tmp/crud_test.txt")
            assert len(loaded) == 3
            loaded_ids = {c.chunk_id for c in loaded}
            expected_ids = {c.chunk_id for c in chunks}
            assert loaded_ids == expected_ids

            # Delete
            deleted = store.delete_evidence_by_file("/tmp/crud_test.txt")
            assert deleted == 3

            # Verify empty
            loaded_after = store.get_evidence_by_file("/tmp/crud_test.txt")
            assert len(loaded_after) == 0

    def test_db_store_search_history(self, tmp_path):
        """Record and retrieve search history."""
        with _db_session_factory(tmp_path) as session_factory:
            store = EngineDBStore(session_factory)

            # Record searches
            store.record_search("query one", "workspace", 5, 120)
            store.record_search("query two", "selected_file", 2, 80)

            # Retrieve
            history = store.get_recent_searches(limit=10)
            assert len(history) == 2
            # Most recent first
            assert history[0]["query"] == "query two"
            assert history[1]["query"] == "query one"
            assert history[0]["scope"] == "selected_file"
            assert history[0]["results_count"] == 2


class TestRetrievalScope:
    """Tests for RetrievalScope enum."""

    def test_retrieval_scope_enum(self):
        """Verify all scopes exist."""
        assert RetrievalScope.SELECTED_FILE.value == "selected_file"
        assert RetrievalScope.FOLDER.value == "folder"
        assert RetrievalScope.WORKSPACE.value == "workspace"
        assert RetrievalScope.SELECTED_FILES.value == "selected_files"

        # Ensure we have at least 4 scopes
        assert len(RetrievalScope) >= 4


# ================================================================
# INTEGRATION TESTS
# ================================================================


class TestIntegration:
    """Integration tests combining multiple engines."""

    def test_full_pipeline_txt(self, tmp_path):
        """Create .txt → ContentEngine → EvidenceEngine → verify chunks have proper provenance."""
        # Create a text file
        txt_file = tmp_path / "pipeline_test.txt"
        content = "Integration testing is critical for software quality. " * 40
        txt_file.write_text(content)

        # ContentEngine
        content_engine = ContentEngine()
        blocks = content_engine.extract(str(txt_file))
        assert len(blocks) > 0
        for block in blocks:
            assert block.source_type == "section"
            assert block.file_path == str(txt_file)

        # EvidenceEngine
        evidence_engine = EvidenceEngine(chunk_size=400, chunk_overlap=50)
        chunks = evidence_engine.build_evidence(str(txt_file))
        assert len(chunks) > 0

        # Verify provenance
        for chunk in chunks:
            assert chunk.file_path == str(txt_file)
            assert chunk.source_type == "section"
            assert chunk.source_label.startswith("Section ")
            assert chunk.file_hash != ""
            assert chunk.chunk_id != ""
            assert chunk.char_start >= 0
            assert chunk.char_end > chunk.char_start

    def test_index_and_retrieve(self):
        """Index chunks with mock embedding → retrieve → verify results."""
        dim = 768
        base_vector = _make_fake_embedding(dim)

        mock_embed = MagicMock(spec=EmbeddingEngine)
        mock_embed.embed_text.return_value = base_vector
        mock_embed.dimension = dim

        vec_engine = VectorEngine(dimension=dim)
        chunks = [_make_evidence_chunk(idx=i) for i in range(5)]

        # Use retrieval engine's index_chunks method
        ret_engine = RetrievalEngine(
            embedding_engine=mock_embed,
            vector_engine=vec_engine,
        )

        indexed = ret_engine.index_chunks(chunks)
        assert indexed == 5
        assert ret_engine.indexed_count == 5

        # Now retrieve
        response = ret_engine.retrieve("search query")
        assert isinstance(response, RetrievalResponse)
        assert len(response.results) > 0
        assert response.embedding_available is True

    def test_rag_with_retrieval(self):
        """Full RAG pipeline with mock Ollama → verify answer + citations."""
        dim = 768
        base_vector = _make_fake_embedding(dim)

        mock_embed = MagicMock(spec=EmbeddingEngine)
        mock_embed.embed_text.return_value = base_vector
        mock_embed.dimension = dim

        vec_engine = VectorEngine(dimension=dim)
        chunks = [_make_evidence_chunk(idx=i) for i in range(4)]

        ret_engine = RetrievalEngine(
            embedding_engine=mock_embed,
            vector_engine=vec_engine,
        )
        ret_engine.index_chunks(chunks)

        rag_engine = RAGEngine(retrieval_engine=ret_engine)

        with patch("engines.rag_engine.requests.post") as mock_post:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "response": "According to Section 1, the answer is derived from the evidence."
            }
            mock_post.return_value = mock_response

            response = rag_engine.ask("What does the evidence say?")

        assert response.grounded is True
        assert "evidence" in response.answer.lower()
        assert len(response.citations) > 0
        for citation in response.citations:
            assert isinstance(citation, Citation)
            assert citation.file_path != ""
            assert citation.source_label != ""

    def test_db_persistence_roundtrip(self, tmp_path):
        """Store evidence → reload from DB → verify identical."""
        with _db_session_factory(tmp_path) as session_factory:
            store = EngineDBStore(session_factory)

            # Create and store chunks
            original_chunks = [
                _make_evidence_chunk(file_path="/tmp/persist.txt", idx=i)
                for i in range(5)
            ]
            stored = store.store_evidence(original_chunks)
            assert stored == 5

            # Reload
            loaded = store.get_evidence_by_file("/tmp/persist.txt")
            assert len(loaded) == 5

            # Verify identical content
            orig_map = {c.chunk_id: c for c in original_chunks}
            for loaded_chunk in loaded:
                orig = orig_map[loaded_chunk.chunk_id]
                assert loaded_chunk.text == orig.text
                assert loaded_chunk.file_path == orig.file_path
                assert loaded_chunk.file_hash == orig.file_hash
                assert loaded_chunk.source_type == orig.source_type
                assert loaded_chunk.source_index == orig.source_index
                assert loaded_chunk.source_label == orig.source_label
                assert loaded_chunk.char_start == orig.char_start
                assert loaded_chunk.char_end == orig.char_end

    def test_remove_file_clears_all(self):
        """Index file → remove → verify empty."""
        dim = 768
        base_vector = _make_fake_embedding(dim)

        mock_embed = MagicMock(spec=EmbeddingEngine)
        mock_embed.embed_text.return_value = base_vector
        mock_embed.dimension = dim

        vec_engine = VectorEngine(dimension=dim)
        file_path = "/tmp/removable.txt"
        chunks = [_make_evidence_chunk(file_path=file_path, idx=i) for i in range(3)]

        ret_engine = RetrievalEngine(
            embedding_engine=mock_embed,
            vector_engine=vec_engine,
        )
        ret_engine.index_chunks(chunks)

        assert ret_engine.indexed_count == 3

        # Remove
        removed = ret_engine.remove_file(file_path)
        assert removed == 3
        assert ret_engine.indexed_count == 0
