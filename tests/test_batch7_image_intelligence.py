"""Batch 7 tests — image quality (B7-4), object detection (B7-2),
reverse image search (B7-1), AI image filtering (B7-10)."""

import os
import sys

import numpy as np
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


@pytest.fixture
def image_dir(tmp_path):
    """Generate deterministic fixture images: sharp, blurred, contrast, tiny."""
    from PIL import Image, ImageFilter

    d = tmp_path / "imgs"
    d.mkdir()

    rng = np.random.default_rng(42)
    sharp = Image.fromarray(
        rng.integers(0, 255, (300, 400, 3), dtype=np.uint8), "RGB"
    )
    sharp.save(d / "sharp.png")

    blurred = sharp.filter(ImageFilter.BoxBlur(6))
    blurred.save(d / "blurred.png")

    dark = Image.fromarray(
        np.full((200, 200, 3), 12, dtype=np.uint8), "RGB"
    )
    dark.save(d / "dark.png")

    tiny = Image.fromarray(
        rng.integers(0, 255, (16, 16, 3), dtype=np.uint8), "RGB"
    )
    tiny.save(d / "tiny.png")

    bad = d / "bad.png"
    bad.write_bytes(b"not an image")

    return d


class TestImageQuality:
    def test_sharp_scores_above_blurred(self, image_dir):
        from services.image_quality_service import ImageQualityService

        svc = ImageQualityService()
        sharp = svc.analyze(str(image_dir / "sharp.png"))
        blurred = svc.analyze(str(image_dir / "blurred.png"))
        assert sharp is not None and blurred is not None
        assert sharp.sharpness > blurred.sharpness
        assert sharp.score >= blurred.score

    def test_dimensions_and_aspect(self, image_dir):
        from services.image_quality_service import ImageQualityService

        svc = ImageQualityService()
        res = svc.analyze(str(image_dir / "sharp.png"))
        assert res.width == 400 and res.height == 300
        assert abs(res.aspect_ratio - 400 / 300) < 0.01
        assert res.file_size > 0

    def test_dark_image_labeled(self, image_dir):
        from services.image_quality_service import ImageQualityService

        svc = ImageQualityService()
        res = svc.analyze(str(image_dir / "dark.png"))
        assert res is not None
        assert res.brightness < 0.2

    def test_invalid_image_returns_none(self, image_dir):
        from services.image_quality_service import ImageQualityService

        svc = ImageQualityService()
        assert svc.analyze(str(image_dir / "bad.png")) is None

    def test_unsupported_file(self, tmp_path):
        from services.image_quality_service import ImageQualityService

        svc = ImageQualityService()
        assert svc.analyze(str(tmp_path / "x.txt")) is None

    def test_persist_and_get(self, session_factory, image_dir):
        from database.models import AIAnalysis
        from services.image_quality_service import ImageQualityService

        from services.file_identity import calculate_sha256
        path = str(image_dir / "sharp.png")
        svc = ImageQualityService(session_factory=session_factory)
        res = svc.analyze(path)
        assert svc.persist(path, res)
        got = svc.get(path)
        assert got is not None
        assert got.label == res.label
        with session_factory() as s:
            row = s.query(AIAnalysis).filter_by(
                file_hash=calculate_sha256(path)
            ).first()
            assert row.quality_score == res.score

    def test_quality_label_scale(self):
        from services.image_quality_service import QualityResult

        assert QualityResult(score=0.9, label="?").score == 0.9


class TestObjectDetection:
    def test_parse_valid_json(self):
        from services.object_detection_service import ObjectDetectionService

        svc = ObjectDetectionService(threshold=0.3)
        objs = svc._parse(
            '[{"label": "person", "confidence": 0.94, "box": [1,2,3,4]}, '
            '{"label": "dog", "confidence": 0.5, "box": null}]'
        )
        assert len(objs) == 2
        assert objs[0].label == "person"
        assert objs[0].box == [1, 2, 3, 4]
        assert objs[1].box is None

    def test_parse_threshold_filtering(self):
        from services.object_detection_service import ObjectDetectionService

        svc = ObjectDetectionService(threshold=0.6)
        objs = svc._parse('[{"label": "low", "confidence": 0.4}, {"label": "high", "confidence": 0.9}]')
        assert [o.label for o in objs] == ["high"]

    def test_parse_malformed(self):
        from services.object_detection_service import ObjectDetectionService

        svc = ObjectDetectionService()
        assert svc._parse("not json at all") == []
        assert svc._parse("") == []
        assert svc._parse("Here are the objects: [{bad") == []

    def test_parse_embedded_json_in_text(self):
        from services.object_detection_service import ObjectDetectionService

        svc = ObjectDetectionService()
        objs = svc._parse(
            'Sure! [{"label": "car", "confidence": 0.88}] That is all.'
        )
        assert len(objs) == 1 and objs[0].label == "car"

    def test_detect_requires_existing_file(self, tmp_path):
        from services.object_detection_service import ObjectDetectionService

        svc = ObjectDetectionService()
        assert svc.detect(str(tmp_path / "missing.png")) == []

    def test_persist_and_get_roundtrip(self, session_factory, image_dir):
        from services.object_detection_service import DetectedObject, ObjectDetectionService

        path = str(image_dir / "sharp.png")
        svc = ObjectDetectionService(session_factory=session_factory)
        assert svc.persist(path, [DetectedObject("text", 0.9, [0, 0, 5, 5])])
        got = svc.get(path)
        assert len(got) == 1
        assert got[0].label == "text"

    def test_parse_box_invalid(self):
        from services.object_detection_service import ObjectDetectionService

        svc = ObjectDetectionService()
        objs = svc._parse('[{"label": "x", "confidence": 0.8, "box": [1, 2]}]')
        assert objs[0].box is None


class _FakeClip:
    def __init__(self, available=True):
        self._available = available

    def is_available(self):
        return self._available

    def embed_image(self, path):
        return np.zeros(768, dtype=np.float32)

    def embed_text(self, text):
        return np.ones(768, dtype=np.float32)


class _FakeRetrieval:
    def __init__(self, evidence=None, results=None):
        self._vector = _FakeVector(results or [])
        self._evidence = evidence or {}

    @property
    def indexed_count(self):
        return len(self._evidence)


class _FakeVector:
    def __init__(self, results):
        self._results = results
        self.dimension = 768

    def search(self, vector, top_k=10, threshold=0.0):
        return self._results


class TestReverseImageSearch:
    def test_unavailable_service(self):
        from services.reverse_image_service import ReverseImageService

        svc = ReverseImageService(retrieval=None, clip_engine=None)
        assert svc.is_available() is False
        assert svc.search_by_image("/x.png") == []

    def test_missing_query_file(self, tmp_path):
        from services.reverse_image_service import ReverseImageService

        svc = ReverseImageService(
            retrieval=_FakeRetrieval(), clip_engine=_FakeClip()
        )
        assert svc.search_by_image(str(tmp_path / "nope.png")) == []

    def test_results_filtered_to_images(self, tmp_path):
        from engines.evidence_engine import EvidenceChunk
        from engines.vector_engine import SearchResult
        from services.reverse_image_service import ReverseImageService

        img_chunk = EvidenceChunk(
            chunk_id="img1", text="[Image: a.png]", file_path="/ws/a.png",
            file_hash="a" * 64, source_type="clip_visual", source_index=0,
            source_label="Visual Content", modality="image",
            char_start=0, char_end=0,
        )
        doc_chunk = EvidenceChunk(
            chunk_id="doc1", text="text", file_path="/ws/b.pdf",
            file_hash="b" * 64, source_type="page", source_index=0,
            source_label="Page 1", modality="document",
            char_start=0, char_end=4,
        )
        results = [
            SearchResult(chunk_id="img1", score=0.9, rank=0),
            SearchResult(chunk_id="doc1", score=0.95, rank=1),  # higher but wrong modality
        ]
        svc = ReverseImageService(
            retrieval=_FakeRetrieval({"img1": img_chunk, "doc1": doc_chunk}, results),
            clip_engine=_FakeClip(),
            min_similarity=0.0,
        )
        path = tmp_path / "q.png"
        path.write_bytes(b"x")
        out = svc.search_by_image(str(path))
        assert [r.file_path for r in out] == ["/ws/a.png"]

    def test_threshold_filters(self, tmp_path):
        from engines.evidence_engine import EvidenceChunk
        from engines.vector_engine import SearchResult
        from services.reverse_image_service import ReverseImageService

        chunk = EvidenceChunk(
            chunk_id="c1", text="[Image]", file_path="/ws/a.png",
            file_hash="a" * 64, source_type="clip_visual", source_index=0,
            source_label="V", modality="image",
            char_start=0, char_end=0,
        )
        svc = ReverseImageService(
            retrieval=_FakeRetrieval({"c1": chunk},
                                     [SearchResult(chunk_id="c1", score=0.4, rank=0)]),
            clip_engine=_FakeClip(),
            min_similarity=0.9,
        )
        path = tmp_path / "q.png"
        path.write_bytes(b"x")
        assert svc.search_by_image(str(path)) == []


class TestImageFilter:
    def test_parse_query_objects(self):
        from services.image_filter_service import ImageFilterService

        svc = ImageFilterService(session_factory=None)
        crit = svc.parse_query("images with dogs")
        assert "dog" in crit.objects
        crit2 = svc.parse_query("blurry screenshots")
        assert crit2.quality == "Blurry"

    def test_parse_query_semantic(self):
        from services.image_filter_service import ImageFilterService

        svc = ImageFilterService(session_factory=None)
        crit = svc.parse_query("landscape photos")
        assert "landscape" in crit.objects

    def test_filter_by_objects(self, session_factory, image_dir):
        from database.models import AIAnalysis
        from services.image_filter_service import ImageFilterService
        from services.sqlite_indexer import IndexedFile

        path = str(image_dir / "sharp.png")
        with session_factory() as s:
            s.add(IndexedFile(
                filename="sharp.png", absolute_path=path, size=1,
                extension=".png", checksum="a" * 64, indexing_status="completed",
            ))
            s.add(AIAnalysis(
                file_hash="a" * 64,
                objects_json='[{"label":"person","confidence":0.9}]',
                caption="",
            ))
            s.commit()
        svc = ImageFilterService(session_factory=session_factory)
        hits = svc.filter_images("images with person", folder=str(image_dir))
        assert len(hits) == 1
        assert hits[0].file_path == path

    def test_filter_requires_matching_object(self, session_factory, image_dir):
        from database.models import AIAnalysis
        from services.image_filter_service import ImageFilterService
        from services.sqlite_indexer import IndexedFile

        path = str(image_dir / "sharp.png")
        with session_factory() as s:
            s.add(IndexedFile(
                filename="sharp.png", absolute_path=path, size=1,
                extension=".png", checksum="a" * 64, indexing_status="completed",
            ))
            s.add(AIAnalysis(file_hash="a" * 64, objects_json='[{"label":"cat"}]'))
            s.commit()
        svc = ImageFilterService(session_factory=session_factory)
        assert svc.filter_images("images with dogs", folder=str(image_dir)) == []

    def test_quality_filter(self, session_factory, image_dir):
        from database.models import AIAnalysis
        from services.image_filter_service import ImageFilterService
        from services.sqlite_indexer import IndexedFile

        path = str(image_dir / "blurred.png")
        with session_factory() as s:
            s.add(IndexedFile(
                filename="blurred.png", absolute_path=path, size=1,
                extension=".png", checksum="a" * 64, indexing_status="completed",
            ))
            s.add(AIAnalysis(
                file_hash="a" * 64,
                quality_json='{"label":"Blurry","score":0.2}',
            ))
            s.commit()
        svc = ImageFilterService(session_factory=session_factory)
        hits = svc.filter_images("blurry images", folder=str(image_dir))
        assert len(hits) == 1
        assert hits[0].quality_label == "Blurry"

    def test_text_presence_filter(self, session_factory, image_dir):
        from database.models import AIAnalysis
        from services.image_filter_service import ImageFilterService
        from services.sqlite_indexer import IndexedFile

        path = str(image_dir / "sharp.png")
        with session_factory() as s:
            s.add(IndexedFile(
                filename="sharp.png", absolute_path=path, size=1,
                extension=".png", checksum="a" * 64, indexing_status="completed",
            ))
            s.add(AIAnalysis(file_hash="a" * 64, caption="A screenshot with text UI"))
            s.commit()
        svc = ImageFilterService(session_factory=session_factory)
        hits = svc.filter_images("screenshots with text", folder=str(image_dir))
        assert len(hits) == 1

    def test_empty_query_no_results(self, session_factory):
        from services.image_filter_service import ImageFilterService

        svc = ImageFilterService(session_factory=session_factory)
        assert svc.filter_images("", folder="") == []
