"""Extractors module for multimodal content extraction.

Provides a unified extractor framework that dispatches to modality-specific
extractors (document, image, audio, video) and returns ContentBlock objects.
"""

from .base_extractor import BaseMultimodalExtractor
from .extractor_factory import MultimodalExtractorFactory
from .document_extractor import DocumentExtractor
from .image_extractor import ImageExtractor
from .audio_extractor import AudioExtractor
from .video_extractor import VideoExtractor

__all__ = [
    "BaseMultimodalExtractor",
    "MultimodalExtractorFactory",
    "DocumentExtractor",
    "ImageExtractor",
    "AudioExtractor",
    "VideoExtractor",
]
