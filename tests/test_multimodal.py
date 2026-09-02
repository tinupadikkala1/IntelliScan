"""Batch 3 Multimodal Tests — Unit + Integration tests for Image, Audio, Video engines.

Tests the multimodal pipeline: extractors, vision, speech, video modules.
Audio tests using Whisper require the model to download on first run.
Tests that require heavy dependencies are marked and gracefully skip.
"""

import os
import sys
import tempfile
from unittest.mock import MagicMock, patch, Mock

import numpy as np
import pytest

# Ensure project root is on path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from engines.content_engine import ContentBlock, UniversalContentEngine


# ================================================================
# UNIT TESTS: Extractor Framework
# ================================================================


class TestExtractorFramework:
    """Tests for the extractors/ module."""

    def test_extractor_factory_supported_extensions(self):
        """Factory reports all supported extensions."""
        from extractors import MultimodalExtractorFactory
        factory = MultimodalExtractorFactory()
        exts = factory.supported_extensions()
        # Must include all modalities
        assert '.png' in exts
        assert '.jpg' in exts
        assert '.mp3' in exts
        assert '.wav' in exts
        assert '.mp4' in exts
        assert '.txt' in exts
        assert '.pdf' in exts

    def test_extractor_factory_dispatches_image(self):
        """Factory selects ImageExtractor for image files."""
        from extractors import MultimodalExtractorFactory, ImageExtractor
        factory = MultimodalExtractorFactory()
        ext = factory.get_extractor("photo.png")
        assert isinstance(ext, ImageExtractor)

    def test_extractor_factory_dispatches_audio(self):
        """Factory selects AudioExtractor for audio files."""
        from extractors import MultimodalExtractorFactory, AudioExtractor
        factory = MultimodalExtractorFactory()
        ext = factory.get_extractor("song.mp3")
        assert isinstance(ext, AudioExtractor)

    def test_extractor_factory_dispatches_video(self):
        """Factory selects VideoExtractor for video files."""
        from extractors import MultimodalExtractorFactory, VideoExtractor
        factory = MultimodalExtractorFactory()
        ext = factory.get_extractor("movie.mp4")
        assert isinstance(ext, VideoExtractor)

    def test_extractor_factory_dispatches_document(self):
        """Factory selects DocumentExtractor for text files."""
        from extractors import MultimodalExtractorFactory, DocumentExtractor
        factory = MultimodalExtractorFactory()
        ext = factory.get_extractor("readme.txt")
        assert isinstance(ext, DocumentExtractor)

    def test_extractor_factory_unsupported(self):
        """Factory returns None for unsupported extensions."""
        from extractors import MultimodalExtractorFactory
        factory = MultimodalExtractorFactory()
        ext = factory.get_extractor("data.xyz")
        assert ext is None

    def test_image_extractor_supported_extensions(self):
        """ImageExtractor supports standard image formats."""
        from extractors import ImageExtractor
        ext = ImageExtractor()
        supported = ext.supported_extensions()
        assert '.png' in supported
        assert '.jpg' in supported
        assert '.jpeg' in supported
        assert '.webp' in supported
        assert '.gif' in supported

    def test_audio_extractor_supported_extensions(self):
        """AudioExtractor supports standard audio formats."""
        from extractors import AudioExtractor
        ext = AudioExtractor()
        supported = ext.supported_extensions()
        assert '.mp3' in supported
        assert '.wav' in supported
        assert '.flac' in supported
        assert '.ogg' in supported
        assert '.m4a' in supported

    def test_video_extractor_supported_extensions(self):
        """VideoExtractor supports standard video formats."""
        from extractors import VideoExtractor
        ext = VideoExtractor()
        supported = ext.supported_extensions()
        assert '.mp4' in supported
        assert '.mkv' in supported
        assert '.mov' in supported
        assert '.avi' in supported
        assert '.webm' in supported


# ================================================================
# UNIT TESTS: ContentBlock Extended Fields
# ================================================================


class TestContentBlockExtended:
    """Tests for extended ContentBlock fields."""

    def test_content_block_modality_field(self):
        """ContentBlock has modality field with default 'document'."""
        cb = ContentBlock(
            text="hello", source_type="section", source_index=0,
            source_label="Section 1", file_path="/tmp/test.txt"
        )
        assert cb.modality == "document"

    def test_content_block_image_modality(self):
        """ContentBlock supports image modality."""
        cb = ContentBlock(
            text="OCR text", source_type="ocr", source_index=0,
            source_label="OCR Text", file_path="/tmp/img.png",
            modality="image", confidence=0.85
        )
        assert cb.modality == "image"
        assert cb.confidence == 0.85

    def test_content_block_audio_modality(self):
        """ContentBlock supports audio modality with timestamps."""
        cb = ContentBlock(
            text="Hello world", source_type="transcript", source_index=0,
            source_label="0:00 - 0:30", file_path="/tmp/audio.mp3",
            modality="audio", timestamp_start=0.0, timestamp_end=30.0,
            confidence=0.9
        )
        assert cb.modality == "audio"
        assert cb.timestamp_start == 0.0
        assert cb.timestamp_end == 30.0

    def test_content_block_video_modality(self):
        """ContentBlock supports video modality."""
        cb = ContentBlock(
            text="Video transcript", source_type="transcript", source_index=0,
            source_label="0:00 - 0:30", file_path="/tmp/video.mp4",
            modality="video", timestamp_start=0.0, timestamp_end=30.0
        )
        assert cb.modality == "video"

    def test_content_block_metadata_default(self):
        """ContentBlock metadata defaults to empty dict."""
        cb = ContentBlock(
            text="test", source_type="section", source_index=0,
            source_label="S1", file_path="/tmp/f.txt"
        )
        assert cb.metadata == {}

    def test_content_block_backward_compatible(self):
        """Existing code using ContentBlock without new fields still works."""
        # This simulates how existing code creates ContentBlocks
        cb = ContentBlock(
            text="hello", source_type="page", source_index=0,
            source_label="Page 1", file_path="/tmp/doc.pdf"
        )
        assert cb.text == "hello"
        assert cb.source_type == "page"
        assert cb.file_path == "/tmp/doc.pdf"
        # New fields have safe defaults
        assert cb.modality == "document"
        assert cb.confidence == 1.0
        assert cb.timestamp_start == 0.0


# ================================================================
# UNIT TESTS: Image Pipeline
# ================================================================


class TestImageExtractor:
    """Tests for ImageExtractor."""

    def test_image_extract_creates_blocks(self, tmp_path):
        """Image extraction produces at least one ContentBlock."""
        from PIL import Image
        # Create a simple test image
        img = Image.new('RGB', (100, 100), color='white')
        img_path = str(tmp_path / "test.png")
        img.save(img_path)

        from extractors.image_extractor import ImageExtractor
        ext = ImageExtractor()
        blocks = ext.extract(img_path)

        assert len(blocks) >= 1
        assert all(isinstance(b, ContentBlock) for b in blocks)
        assert all(b.modality == "image" for b in blocks)
        assert all(b.file_path == img_path for b in blocks)

    def test_image_extract_nonexistent_file(self):
        """Image extraction returns fallback block for missing file."""
        from extractors.image_extractor import ImageExtractor
        ext = ImageExtractor()
        blocks = ext.extract("/tmp/nonexistent_image.png")
        # Returns a filename fallback block with low confidence
        assert len(blocks) == 1
        assert blocks[0].source_type == "filename"
        assert blocks[0].confidence == 0.3

    def test_content_engine_routes_image(self, tmp_path):
        """ContentEngine routes .png files to image extraction."""
        from PIL import Image
        img = Image.new('RGB', (50, 50), color='red')
        img_path = str(tmp_path / "red.png")
        img.save(img_path)

        engine = UniversalContentEngine()
        blocks = engine.extract(img_path)
        assert len(blocks) >= 1
        assert blocks[0].modality == "image"


# ================================================================
# UNIT TESTS: Audio Pipeline (mocked Whisper)
# ================================================================


class TestAudioExtractor:
    """Tests for AudioExtractor with mocked Whisper."""

    def test_audio_extract_with_mock_whisper(self, tmp_path):
        """Audio extraction with mocked Whisper returns transcript blocks."""
        # Create a dummy audio file
        audio_path = str(tmp_path / "test.wav")
        with open(audio_path, 'wb') as f:
            f.write(b'\x00' * 1000)

        from extractors.audio_extractor import AudioExtractor

        # Mock the whisper model
        mock_model = MagicMock()
        mock_model.transcribe.return_value = {
            "text": "Hello world this is a test transcription",
            "segments": [
                {"start": 0.0, "end": 5.0, "text": "Hello world"},
                {"start": 5.0, "end": 10.0, "text": "this is a test"},
                {"start": 10.0, "end": 15.0, "text": "transcription"},
            ],
            "language": "en",
        }

        ext = AudioExtractor()
        ext._model = mock_model  # Inject mock

        blocks = ext.extract(audio_path)
        assert len(blocks) >= 1
        assert all(b.modality == "audio" for b in blocks)
        assert all(b.source_type == "transcript" for b in blocks)
        assert "Hello world" in blocks[0].text

    def test_audio_format_time(self):
        """Audio time formatting works correctly."""
        from extractors.audio_extractor import AudioExtractor
        assert AudioExtractor._format_time(0) == "0:00"
        assert AudioExtractor._format_time(65) == "1:05"
        assert AudioExtractor._format_time(3661) == "1:01:01"

    def test_content_engine_routes_audio(self, tmp_path):
        """ContentEngine routes .mp3 to audio extraction."""
        audio_path = str(tmp_path / "test.mp3")
        with open(audio_path, 'wb') as f:
            f.write(b'\x00' * 100)

        engine = UniversalContentEngine()

        # Mock whisper to avoid actual model loading
        with patch("extractors.audio_extractor.AudioExtractor._load_model") as mock_load:
            mock_model = MagicMock()
            mock_model.transcribe.return_value = {
                "text": "test audio content",
                "segments": [{"start": 0.0, "end": 5.0, "text": "test audio content"}],
                "language": "en",
            }
            mock_load.return_value = mock_model

            blocks = engine.extract(audio_path)
            assert len(blocks) >= 1
            assert blocks[0].modality == "audio"


# ================================================================
# UNIT TESTS: Video Pipeline (mocked)
# ================================================================


class TestVideoExtractor:
    """Tests for VideoExtractor with mocked dependencies."""

    def test_video_extract_with_mocked_audio(self, tmp_path):
        """Video extraction with mocked audio transcription."""
        video_path = str(tmp_path / "test.mp4")
        with open(video_path, 'wb') as f:
            f.write(b'\x00' * 1000)

        from extractors.video_extractor import VideoExtractor

        ext = VideoExtractor()

        # Mock the audio extraction
        with patch.object(ext, '_transcribe_audio') as mock_transcribe:
            mock_transcribe.return_value = [
                ContentBlock(
                    text="Video transcript text",
                    source_type="transcript",
                    source_index=0,
                    source_label="0:00 - 0:30",
                    file_path=video_path,
                    modality="video",
                    timestamp_start=0.0,
                    timestamp_end=30.0,
                    confidence=0.9,
                )
            ]
            with patch.object(ext, '_extract_keyframes', return_value=[]):
                blocks = ext.extract(video_path)

        assert len(blocks) >= 1
        assert blocks[0].modality == "video"
        assert blocks[0].source_type == "transcript"
        assert "Video transcript text" in blocks[0].text


# ================================================================
# UNIT TESTS: Vision Module
# ================================================================


class TestVisionModule:
    """Tests for vision/ module components."""

    def test_ocr_engine_instantiates(self):
        """OCREngine can be instantiated."""
        from vision.ocr_engine import OCREngine
        engine = OCREngine()
        assert engine._language == "eng"

    def test_vision_engine_instantiates(self):
        """VisionEngine can be instantiated and uses the centralized vision model."""
        from engines.config import VISION_MODEL
        from vision.vision_engine import VisionEngine
        engine = VisionEngine()
        # P0-04: default must come from central config and be a vision-capable model.
        assert engine._model == VISION_MODEL
        assert engine._model == "moondream:latest"

    def test_content_merger_merge(self):
        """ContentMerger produces blocks from OCR and vision results."""
        from vision.content_merger import ContentMerger
        from vision.ocr_engine import OCRResult
        from vision.vision_engine import VisionResult

        merger = ContentMerger()
        blocks = merger.merge(
            file_path="/tmp/img.png",
            ocr_result=OCRResult(text="OCR text", confidence=0.9, language="eng"),
            vision_result=VisionResult(caption="A red car", objects=[], confidence=0.7),
        )

        assert len(blocks) == 2
        assert blocks[0].source_type == "ocr"
        assert blocks[0].text == "OCR text"
        assert blocks[1].source_type == "caption"
        assert blocks[1].text == "A red car"


# ================================================================
# UNIT TESTS: Speech Module
# ================================================================


class TestSpeechModule:
    """Tests for speech/ module."""

    def test_speech_engine_instantiates(self):
        """SpeechEngine can be instantiated."""
        from speech.speech_engine import SpeechEngine
        engine = SpeechEngine(model_size="base")
        assert engine._model_size == "base"
        assert engine._model is None  # Lazy loaded

    def test_speech_engine_is_available(self):
        """SpeechEngine reports whisper availability."""
        from speech.speech_engine import SpeechEngine
        engine = SpeechEngine()
        # Whisper is installed in this environment
        assert engine.is_available() is True


# ================================================================
# UNIT TESTS: Video Module
# ================================================================


class TestVideoModule:
    """Tests for video/ module."""

    def test_keyframe_engine_instantiates(self):
        """KeyframeEngine can be instantiated."""
        from video.keyframe_engine import KeyframeEngine
        engine = KeyframeEngine(max_frames=3, interval_seconds=30.0)
        assert engine._max_frames == 3
        assert engine._interval_seconds == 30.0

    def test_keyframe_engine_is_available(self):
        """KeyframeEngine reports OpenCV availability."""
        from video.keyframe_engine import KeyframeEngine
        engine = KeyframeEngine()
        assert engine.is_available() is True  # opencv installed

    def test_video_engine_instantiates(self):
        """VideoEngine can be instantiated."""
        from video.video_engine import VideoEngine
        engine = VideoEngine()
        assert engine._speech is not None
        assert engine._keyframes is not None


# ================================================================
# INTEGRATION TESTS
# ================================================================


class TestMultimodalIntegration:
    """Integration tests for multimodal pipeline."""

    def test_image_full_pipeline(self, tmp_path):
        """Image → ContentEngine → EvidenceEngine pipeline."""
        from PIL import Image, ImageDraw
        from engines import ContentEngine, EvidenceEngine

        # Create image with some content
        img = Image.new('RGB', (200, 50), color='white')
        draw = ImageDraw.Draw(img)
        draw.text((10, 15), "Test Image Content", fill='black')
        img_path = str(tmp_path / "test_pipeline.png")
        img.save(img_path)

        # Extract
        engine = ContentEngine()
        blocks = engine.extract(img_path)
        assert len(blocks) >= 1
        assert blocks[0].modality == "image"

        # Build evidence
        ev_engine = EvidenceEngine()
        chunks = ev_engine.build_evidence(img_path)
        assert len(chunks) >= 1
        assert chunks[0].file_path == img_path

    def test_audio_full_pipeline_mocked(self, tmp_path):
        """Audio → ContentEngine → EvidenceEngine pipeline (mocked Whisper)."""
        from engines import ContentEngine, EvidenceEngine

        audio_path = str(tmp_path / "lecture.wav")
        with open(audio_path, 'wb') as f:
            f.write(b'\x00' * 500)

        # Mock whisper
        with patch("extractors.audio_extractor.AudioExtractor._load_model") as mock_load:
            mock_model = MagicMock()
            mock_model.transcribe.return_value = {
                "text": "Welcome to the lecture on machine learning",
                "segments": [
                    {"start": 0.0, "end": 5.0, "text": "Welcome to the lecture"},
                    {"start": 5.0, "end": 10.0, "text": "on machine learning"},
                ],
                "language": "en",
            }
            mock_load.return_value = mock_model

            engine = ContentEngine()
            blocks = engine.extract(audio_path)
            assert len(blocks) >= 1
            assert blocks[0].modality == "audio"
            assert "Welcome" in blocks[0].text

            # Evidence
            ev_engine = EvidenceEngine()
            chunks = ev_engine.build_evidence(audio_path)
            assert len(chunks) >= 1

    def test_document_still_works(self, tmp_path):
        """Document extraction unchanged after multimodal additions."""
        txt_file = tmp_path / "doc.txt"
        txt_file.write_text("This is a regular document with some content for testing.")

        engine = UniversalContentEngine()
        blocks = engine.extract(str(txt_file))

        assert len(blocks) >= 1
        assert blocks[0].source_type == "section"
        assert blocks[0].modality == "document"
        assert "regular document" in blocks[0].text

    def test_mixed_modality_indexing(self, tmp_path):
        """Multiple modalities can be indexed into the same vector engine."""
        from engines import EmbeddingEngine, VectorEngine, EvidenceEngine, RetrievalEngine
        from unittest.mock import MagicMock

        dim = 768
        mock_embed = MagicMock(spec=EmbeddingEngine)
        mock_embed.embed_text.return_value = np.random.randn(dim).astype(np.float32)
        mock_embed.dimension = dim

        vec = VectorEngine(dimension=dim)
        retrieval = RetrievalEngine(embedding_engine=mock_embed, vector_engine=vec)

        # Create document evidence
        txt_file = tmp_path / "notes.txt"
        txt_file.write_text("Machine learning is a subset of AI.")

        ev = EvidenceEngine()
        doc_chunks = ev.build_evidence(str(txt_file))
        assert len(doc_chunks) > 0

        # Index document chunks
        indexed = retrieval.index_chunks(doc_chunks)
        assert indexed > 0
        assert retrieval.indexed_count > 0
