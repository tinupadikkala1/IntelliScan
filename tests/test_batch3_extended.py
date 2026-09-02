"""Batch 3 Extended Tests — persistence hydration, evidence navigation,
match strength, modality filtering, embedded document images and the
unified multimodal search dialog.

All tests run WITHOUT Ollama; HTTP calls and heavy models are mocked.
"""

import os
import sys
import uuid
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from engines import EvidenceChunk, RetrievalResult, RetrievalEngine
from engines.db_store import EngineDBStore


# ================================================================
# Helpers
# ================================================================

def _make_evidence_chunk(
    file_path="/tmp/test.txt",
    idx=0,
    modality="document",
    timestamp_start=0.0,
    timestamp_end=0.0,
    source_type="section",
    confidence=1.0,
):
    """Create a synthetic EvidenceChunk with modality/timestamp fields."""
    return EvidenceChunk(
        chunk_id=uuid.uuid4().hex,
        text=f"This is evidence chunk number {idx} with some content for testing.",
        file_path=file_path,
        file_hash="abc123" * 5,
        source_type=source_type,
        source_index=idx,
        source_label=f"{modality} source {idx + 1}",
        char_start=idx * 100,
        char_end=(idx + 1) * 100,
        modality=modality,
        timestamp_start=timestamp_start,
        timestamp_end=timestamp_end,
        confidence=confidence,
    )


@contextmanager
def _db_session_factory(tmp_path):
    """Create a SQLAlchemy session factory for a tmp database."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from database.models import Base

    db_path = str(tmp_path / "test_batch3_ext.db")
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
# P0-01 / P0-02 — Persistence + Hydration
# ================================================================

class TestPersistenceHydration:
    """Evidence persisted to SQLite survives a restart (hydrate_from_store)."""

    def test_evidence_roundtrip_preserves_modality_and_timestamps(self, tmp_path):
        """Modality/timestamp/confidence fields survive store → load."""
        with _db_session_factory(tmp_path) as session_factory:
            store = EngineDBStore(session_factory)

            chunks = [
                _make_evidence_chunk(
                    file_path="/tmp/audio.mp3", idx=0,
                    modality="audio", timestamp_start=134.0,
                    timestamp_end=151.0, source_type="transcript",
                ),
                _make_evidence_chunk(
                    file_path="/tmp/img.png", idx=0,
                    modality="image", source_type="ocr", confidence=0.8,
                ),
            ]
            store.store_evidence(chunks)

            loaded = store.get_all_evidence()
            by_modality = {c.modality: c for c in loaded}
            assert "audio" in by_modality
            assert "image" in by_modality
            assert by_modality["audio"].timestamp_start == 134.0
            assert by_modality["audio"].timestamp_end == 151.0
            assert by_modality["audio"].source_type == "transcript"
            assert by_modality["image"].confidence == 0.8

    def test_hydrate_from_store_restores_evidence_map(self, tmp_path):
        """After re-hydration, retrieval results carry the persisted chunks."""
        with _db_session_factory(tmp_path) as session_factory:
            store = EngineDBStore(session_factory)
            chunks = [
                _make_evidence_chunk(file_path="/tmp/persisted.txt", idx=i)
                for i in range(3)
            ]
            store.store_evidence(chunks)

            # FAISS vectors exist (as if saved before restart)
            dim = 768
            from engines import VectorEngine
            vec = VectorEngine(dimension=dim)
            rng = np.random.default_rng(42)
            for c in chunks:
                v = rng.standard_normal(dim).astype(np.float32)
                v /= np.linalg.norm(v)
                vec.add(c.chunk_id, v)

            mock_embed = MagicMock(spec=RetrievalEngine)
            retrieval = RetrievalEngine(embedding_engine=mock_embed, vector_engine=vec)

            hydrated = retrieval.hydrate_from_store(store)
            assert hydrated == 3
            assert retrieval.indexed_count == 3
            assert retrieval._evidence
            # Every FAISS id resolves to an EvidenceChunk (required invariant)
            assert set(retrieval._evidence.keys()) == set(vec.list_chunk_ids())

    def test_hydrate_removes_orphaned_faiss_vectors(self, tmp_path):
        """FAISS vectors without evidence rows are removed on hydration."""
        with _db_session_factory(tmp_path) as session_factory:
            store = EngineDBStore(session_factory)
            chunks = [_make_evidence_chunk(file_path="/tmp/a.txt", idx=0)]
            store.store_evidence(chunks)

            dim = 768
            from engines import VectorEngine
            vec = VectorEngine(dimension=dim)
            rng = np.random.default_rng(7)
            for c in chunks:
                v = rng.standard_normal(dim).astype(np.float32)
                v /= np.linalg.norm(v)
                vec.add(c.chunk_id, v)
            # Orphaned vector — exists in FAISS but not in DB
            orphan_id = "orphan_vector_xyz"
            v = rng.standard_normal(dim).astype(np.float32)
            v /= np.linalg.norm(v)
            vec.add(orphan_id, v)
            assert vec.size == 2

            mock_embed = MagicMock(spec=RetrievalEngine)
            retrieval = RetrievalEngine(embedding_engine=mock_embed, vector_engine=vec)
            retrieval.hydrate_from_store(store)

            # Orphan removed; only real evidence remains
            assert orphan_id not in vec.list_chunk_ids()
            assert vec.size == 1

    def test_vector_map_batch_store(self, tmp_path):
        """Batch vector-map persistence records chunk→file mappings."""
        with _db_session_factory(tmp_path) as session_factory:
            store = EngineDBStore(session_factory)
            ids = [uuid.uuid4().hex for _ in range(4)]
            stored = store.store_vector_maps(ids, "/tmp/vec.txt", "deadbeef", "nomic-embed-text")
            assert stored == 4

            maps = store.get_vector_maps_by_file("/tmp/vec.txt")
            assert len(maps) == 4
            assert {m["chunk_id"] for m in maps} == set(ids)
            assert maps[0]["embedding_model"] == "nomic-embed-text"


# ================================================================
# B3-16 — Match strength / similarity explanation
# ================================================================

class TestMatchStrength:
    """Similarity is labeled (High/Medium/Low), never presented as confidence."""

    def test_high(self):
        assert RetrievalEngine.match_strength(0.91) == "High"
        assert RetrievalEngine.match_strength(0.80) == "High"

    def test_medium(self):
        assert RetrievalEngine.match_strength(0.70) == "Medium"
        assert RetrievalEngine.match_strength(0.60) == "Medium"

    def test_low(self):
        assert RetrievalEngine.match_strength(0.4) == "Low"
        assert RetrievalEngine.match_strength(0.0) == "Low"

    def test_negative_or_out_of_range(self):
        # Out-of-range scores degrade gracefully to Low.
        assert RetrievalEngine.match_strength(-0.5) == "Low"

    def test_result_property(self):
        r = RetrievalResult(
            chunk_id="x", text="t", score=0.85, rank=0,
            file_path="/tmp/f.txt", file_hash="h", source_type="page",
            source_index=0, source_label="Page 1", char_start=0, char_end=5,
        )
        assert r.match_strength == "High"

    def test_explain_match_sources(self):
        r = RetrievalResult(
            chunk_id="x", text="t", score=0.5, rank=0,
            file_path="/tmp/f.png", file_hash="h", source_type="ocr",
            source_index=0, source_label="OCR", char_start=0, char_end=5,
        )
        assert "OCR" in RetrievalEngine.explain_match(r)
        r2 = RetrievalResult(
            chunk_id="x", text="t", score=0.5, rank=0,
            file_path="/tmp/f.mp3", file_hash="h", source_type="transcript",
            source_index=0, source_label="0:00", char_start=0, char_end=5,
        )
        assert "transcript" in RetrievalEngine.explain_match(r2)
        r3 = RetrievalResult(
            chunk_id="x", text="t", score=0.5, rank=0,
            file_path="/tmp/f.txt", file_hash="h", source_type="section",
            source_index=0, source_label="S1", char_start=0, char_end=5,
        )
        assert "similarity" in RetrievalEngine.explain_match(r3)


# ================================================================
# B3-14 — Modality filtering
# ================================================================

class TestModalityFiltering:
    """Explicit UI filter (All/Documents/Images/Audio/Video) filters results."""

    def _make_result(self, file_path, modality, source_type="section", ts=0.0):
        return RetrievalResult(
            chunk_id=uuid.uuid4().hex, text="content", score=0.7, rank=0,
            file_path=file_path, file_hash="h", source_type=source_type,
            source_index=0, source_label="S1", char_start=0, char_end=5,
            modality=modality, timestamp_start=ts, timestamp_end=ts,
        )

    def test_all_returns_everything(self):
        from engines import VectorEngine
        ret = RetrievalEngine(embedding_engine=MagicMock(), vector_engine=VectorEngine(dimension=8))
        results = [
            self._make_result("/tmp/a.pdf", "document"),
            self._make_result("/tmp/b.png", "image"),
            self._make_result("/tmp/c.mp3", "audio"),
            self._make_result("/tmp/d.mp4", "video"),
        ]
        filtered = ret.filter_results_by_modality(results, "all")
        assert len(filtered) == 4

    def test_image_filter(self):
        from engines import VectorEngine
        ret = RetrievalEngine(embedding_engine=MagicMock(), vector_engine=VectorEngine(dimension=8))
        results = [
            self._make_result("/tmp/a.pdf", "document"),
            self._make_result("/tmp/b.png", "image"),
            self._make_result("/tmp/c.mp3", "audio"),
            self._make_result("/tmp/d.mp4", "video"),
        ]
        filtered = ret.filter_results_by_modality(results, "image")
        assert len(filtered) == 1
        assert filtered[0].file_path == "/tmp/b.png"

    def test_audio_and_video_filters(self):
        from engines import VectorEngine
        ret = RetrievalEngine(embedding_engine=MagicMock(), vector_engine=VectorEngine(dimension=8))
        results = [
            self._make_result("/tmp/a.pdf", "document"),
            self._make_result("/tmp/b.png", "image"),
            self._make_result("/tmp/c.mp3", "audio"),
            self._make_result("/tmp/d.mp4", "video"),
        ]
        assert [r.file_path for r in ret.filter_results_by_modality(results, "audio")] == ["/tmp/c.mp3"]
        assert [r.file_path for r in ret.filter_results_by_modality(results, "video")] == ["/tmp/d.mp4"]

    def test_document_filter(self):
        from engines import VectorEngine
        ret = RetrievalEngine(embedding_engine=MagicMock(), vector_engine=VectorEngine(dimension=8))
        results = [
            self._make_result("/tmp/a.pdf", "document"),
            self._make_result("/tmp/b.png", "image"),
        ]
        filtered = ret.filter_results_by_modality(results, "document")
        assert [r.file_path for r in filtered] == ["/tmp/a.pdf"]

    def test_empty_result_for_no_match(self):
        from engines import VectorEngine
        ret = RetrievalEngine(embedding_engine=MagicMock(), vector_engine=VectorEngine(dimension=8))
        results = [self._make_result("/tmp/a.pdf", "document")]
        assert ret.filter_results_by_modality(results, "video") == []

    def test_modality_of_by_extension(self):
        assert RetrievalEngine.modality_of("/tmp/x.png") == "image"
        assert RetrievalEngine.modality_of("/tmp/x.mp3") == "audio"
        assert RetrievalEngine.modality_of("/tmp/x.mp4") == "video"
        assert RetrievalEngine.modality_of("/tmp/x.pdf") == "document"
        assert RetrievalEngine.modality_of("/tmp/x.unknownext") == "document"


# ================================================================
# B3-13 — Evidence navigation
# ================================================================

class TestEvidenceNavigation:
    """EvidenceLocation + EvidenceNavigator dispatch by modality."""

    def test_from_result_pdf_page(self):
        from services.evidence_navigator import EvidenceLocation
        result = RetrievalResult(
            chunk_id="x", text="t", score=0.7, rank=0,
            file_path="/tmp/doc.pdf", file_hash="h", source_type="page",
            source_index=4, source_label="Page 5", char_start=0, char_end=5,
            modality="document",
        )
        loc = EvidenceLocation.from_result(result)
        assert loc.page == 5
        assert loc.modality == "document"
        assert loc.source_index == 4

    def test_from_result_audio_timestamp(self):
        from services.evidence_navigator import EvidenceLocation
        result = RetrievalResult(
            chunk_id="x", text="t", score=0.7, rank=0,
            file_path="/tmp/lec.mp3", file_hash="h", source_type="transcript",
            source_index=0, source_label="02:14 - 02:31", char_start=0, char_end=5,
            modality="audio", timestamp_start=134.0, timestamp_end=151.0,
        )
        loc = EvidenceLocation.from_result(result)
        assert loc.modality == "audio"
        assert loc.timestamp_start == 134.0
        assert loc.timestamp_end == 151.0

    def test_navigate_jumps_pdf_page(self):
        from services.evidence_navigator import EvidenceLocation, EvidenceNavigator
        calls = []
        nav = EvidenceNavigator(jump_pdf=lambda p, pg: calls.append(("pdf", p, pg)))
        loc = EvidenceLocation(
            file_path="/tmp/doc.pdf", modality="document",
            source_type="page", page=5,
        )
        nav.navigate(loc)
        assert calls == [("pdf", "/tmp/doc.pdf", 5)]

    def test_navigate_seeks_audio(self):
        from services.evidence_navigator import EvidenceLocation, EvidenceNavigator
        calls = []
        nav = EvidenceNavigator(play_media=lambda p, s: calls.append(("media", p, s)))
        loc = EvidenceLocation(
            file_path="/tmp/lec.mp3", modality="audio",
            source_type="transcript", timestamp_start=134.0,
        )
        nav.navigate(loc)
        assert calls == [("media", "/tmp/lec.mp3", 134.0)]

    def test_navigate_previews_image(self):
        from services.evidence_navigator import EvidenceLocation, EvidenceNavigator
        calls = []
        nav = EvidenceNavigator(preview_file=lambda p: calls.append(("preview", p)))
        loc = EvidenceLocation(
            file_path="/tmp/arch.png", modality="image", source_type="ocr",
        )
        nav.navigate(loc)
        assert calls == [("preview", "/tmp/arch.png")]

    def test_navigate_falls_back_to_open(self):
        from services.evidence_navigator import EvidenceLocation, EvidenceNavigator
        calls = []
        nav = EvidenceNavigator(open_file=lambda p: calls.append(("open", p)))
        loc = EvidenceLocation(
            file_path="/tmp/doc.docx", modality="document", source_type="section",
        )
        nav.navigate(loc)
        assert calls == [("open", "/tmp/doc.docx")]

    def test_navigate_no_path_is_safe(self):
        from services.evidence_navigator import EvidenceLocation, EvidenceNavigator
        nav = EvidenceNavigator(open_file=lambda p: pytest.fail("should not open"))
        nav.navigate(EvidenceLocation(file_path=""))


# ================================================================
# M3 — Embedded document images
# ================================================================

class TestEmbeddedDocumentImages:
    """OCR/vision on images embedded in documents preserves provenance."""

    def test_pdf_embedded_image_blocks(self, tmp_path):
        """_embedded_image_blocks returns OCR + caption blocks with labels."""
        from engines.content_engine import UniversalContentEngine
        engine = UniversalContentEngine()
        fake_image_bytes = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64

        with patch("extractors.image_extractor.ocr_image_bytes", return_value="ModuleNotFoundError text") as mock_ocr, \
             patch("extractors.image_extractor.caption_image_bytes", return_value="") as mock_cap:
            blocks = engine._embedded_image_blocks(
                "/tmp/report.pdf", fake_image_bytes,
                source_type="embedded_image", source_index=2,
                source_label="Page 3 · Image 1", metadata={"page": 2, "image_index": 0},
            )
        mock_ocr.assert_called_once_with(fake_image_bytes)

        assert len(blocks) == 1
        assert blocks[0].source_type == "ocr"
        assert blocks[0].modality == "document"
        assert "ModuleNotFoundError" in blocks[0].text
        assert blocks[0].metadata.get("embedded") is True
        assert blocks[0].metadata.get("page") == 2
        # Provenance label retained
        assert "Page 3 · Image 1" in blocks[0].source_label

    def test_embedded_image_with_vision_caption(self):
        """Short OCR triggers a vision caption for diagrams."""
        from engines.content_engine import UniversalContentEngine
        engine = UniversalContentEngine()

        with patch("extractors.image_extractor.ocr_image_bytes", return_value="x") as mock_ocr, \
             patch("extractors.image_extractor.caption_image_bytes", return_value="ER diagram with Student entity") as mock_cap:
            blocks = engine._embedded_image_blocks(
                "/tmp/arch.pptx", b"data",
                source_type="embedded_image", source_index=1,
                source_label="Slide 2 · Image 1", metadata={"slide": 1, "image_index": 0},
            )

        assert len(blocks) == 2
        types = {b.source_type for b in blocks}
        assert types == {"ocr", "caption"}
        caption_block = next(b for b in blocks if b.source_type == "caption")
        assert "ER diagram" in caption_block.text
        assert caption_block.modality == "document"

    def test_embedded_image_failure_is_safe(self):
        """OCR/vision exceptions do not break document extraction."""
        from engines.content_engine import UniversalContentEngine
        engine = UniversalContentEngine()
        with patch("extractors.image_extractor.ocr_image_bytes", side_effect=RuntimeError("tesseract down")), \
             patch("extractors.image_extractor.caption_image_bytes", return_value=""):
            blocks = engine._embedded_image_blocks(
                "/tmp/doc.pdf", b"data",
                source_type="embedded_image", source_index=0,
                source_label="Page 1 · Image 1", metadata={},
            )
        assert blocks == []

    def test_embedded_image_ocr_failure_still_captions(self):
        """Vision caption is produced even when OCR fails (M3 requirement)."""
        from engines.content_engine import UniversalContentEngine
        engine = UniversalContentEngine()
        with patch("extractors.image_extractor.ocr_image_bytes", side_effect=RuntimeError("tesseract down")), \
             patch("extractors.image_extractor.caption_image_bytes", return_value="Flowchart: login flow") as mock_cap:
            blocks = engine._embedded_image_blocks(
                "/tmp/doc.pdf", b"data",
                source_type="embedded_image", source_index=0,
                source_label="Page 1 · Image 1", metadata={},
            )
        mock_cap.assert_called_once_with(b"data")
        assert len(blocks) == 1
        assert blocks[0].source_type == "caption"
        assert "Flowchart" in blocks[0].text


# ================================================================
# B3-14/15/16 — Unified search dialog
# ================================================================

class TestSemanticSearchDialog:
    """Unified multimodal search dialog: filters, cards, match strength."""

    def test_default_filter_is_all(self, qapp):
        from ui.dialogs.semantic_search_dialog import SemanticSearchDialog
        dlg = SemanticSearchDialog()
        assert dlg.modality_filter == "all"
        assert dlg.filter_combo.count() == 5  # All/Documents/Images/Audio/Video

    def test_set_modality_filter(self, qapp):
        from ui.dialogs.semantic_search_dialog import SemanticSearchDialog
        dlg = SemanticSearchDialog()
        dlg.set_modality_filter("audio")
        assert dlg.modality_filter == "audio"

    def test_search_emits_query_and_modality(self, qapp, qtbot):
        from ui.dialogs.semantic_search_dialog import SemanticSearchDialog
        dlg = SemanticSearchDialog()
        emitted = []
        dlg.search_requested.connect(lambda q, m: emitted.append((q, m)))
        dlg.search_input.setText("third normal form")
        dlg.set_modality_filter("audio")
        dlg._on_search()
        assert emitted == [("third normal form", "audio")]

    def test_results_render_match_strength(self, qapp):
        from ui.dialogs.semantic_search_dialog import SemanticSearchDialog
        dlg = SemanticSearchDialog()
        dlg.set_results([
            {
                "score": 0.91, "text": "third normal form eliminates transitive dependency",
                "source_label": "02:14 - 02:31", "file_path": "/tmp/lec.mp3",
                "modality": "audio", "match_strength": "High",
            },
            {
                "score": 0.45, "text": "some unrelated text here",
                "source_label": "Page 43", "file_path": "/tmp/notes.pdf",
                "modality": "document", "match_strength": "Low",
            },
        ])
        assert dlg.results_list.count() == 2
        text0 = dlg.results_list.item(0).text()
        text1 = dlg.results_list.item(1).text()
        assert "Similarity: 0.910" in text0
        assert "Match strength: High" in text0
        assert "Match strength: Low" in text1
        assert "02:14 - 02:31" in text0

    def test_double_click_emits_evidence_payload(self, qapp):
        from ui.dialogs.semantic_search_dialog import SemanticSearchDialog
        dlg = SemanticSearchDialog()
        emitted = []
        dlg.evidence_open_requested.connect(lambda r: emitted.append(r))
        dlg.set_results([
            {
                "score": 0.84, "text": "clip content", "source_label": "07:56",
                "file_path": "/tmp/clip.mp4", "modality": "video",
                "source_type": "transcript", "timestamp_start": 476.0,
            },
        ])
        item = dlg.results_list.item(0)
        dlg._on_result_double_clicked(item)
        assert len(emitted) == 1
        assert emitted[0]["file_path"] == "/tmp/clip.mp4"
        assert emitted[0]["timestamp_start"] == 476.0
