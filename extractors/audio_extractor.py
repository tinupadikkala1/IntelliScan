"""Audio extractor — Whisper-based speech-to-text transcription."""

from __future__ import annotations

import logging
import os
from typing import List

from engines.content_engine import ContentBlock
from .base_extractor import BaseMultimodalExtractor

logger = logging.getLogger(__name__)

_AUDIO_EXT = {'.mp3', '.wav', '.flac', '.ogg', '.aac', '.m4a', '.wma', '.opus'}

# Global cache for loaded Whisper models to prevent re-loading on each file.
_MODEL_CACHE = {}


class AudioExtractor(BaseMultimodalExtractor):
    """Extracts text content from audio files using Whisper transcription.

    Uses OpenAI Whisper (local, CPU) to transcribe audio into text with
    timestamp segments. Each segment becomes a ContentBlock.
    """

    def __init__(self, model_size: str = "base") -> None:
        """Initialize the audio extractor.

        Args:
            model_size: Whisper model size ('tiny', 'base', 'small').
                       'base' is a good quality/speed tradeoff.
        """
        self._model_size = model_size
        self._model = None

    def supported_extensions(self) -> set:
        return _AUDIO_EXT

    def _load_model(self):
        """Lazy-load the Whisper model and cache it globally."""
        if self._model is not None:
            return self._model
        global _MODEL_CACHE
        if self._model_size not in _MODEL_CACHE:
            try:
                import whisper
                logger.info("Loading Whisper '%s' model...", self._model_size)
                _MODEL_CACHE[self._model_size] = whisper.load_model(self._model_size)
                logger.info("Whisper model loaded successfully")
            except Exception as e:
                logger.error("Failed to load Whisper model: %s", e)
                raise
        self._model = _MODEL_CACHE[self._model_size]
        return self._model

    def extract(self, file_path: str) -> List[ContentBlock]:
        """Extract text content from an audio file via transcription.

        Transcribes the audio using Whisper and returns timestamped
        segments as ContentBlock objects.

        Args:
            file_path: Path to the audio file.

        Returns:
            List of ContentBlock objects with transcribed segments.
        """
        file_path = os.path.abspath(file_path)
        blocks: List[ContentBlock] = []

        try:
            model = self._load_model()
        except Exception:
            logger.error("Cannot transcribe: Whisper model unavailable")
            return []

        try:
            import whisper
            try:
                audio_samples = whisper.load_audio(file_path)
                if audio_samples is None or len(audio_samples) < 1600:
                    logger.warning("Audio file has insufficient audio samples (< 0.1s): %s", file_path)
                    return []
            except Exception as check_err:
                logger.warning("Could not read audio samples from %s: %s", file_path, check_err)
                return []

            logger.info("Transcribing audio: %s", file_path)
            result = model.transcribe(
                file_path,
                fp16=False,  # CPU mode
                language=None,  # Auto-detect
            )


            segments = result.get("segments", [])
            full_text = result.get("text", "").strip()

            if not segments and full_text:
                # No segments but got text — return as single block
                blocks.append(ContentBlock(
                    text=full_text,
                    source_type="transcript",
                    source_index=0,
                    source_label="Full Transcript",
                    file_path=file_path,
                    modality="audio",
                    timestamp_start=0.0,
                    timestamp_end=0.0,
                    confidence=0.9,
                ))
                return blocks

            # Create a ContentBlock per segment (or group of segments)
            # Group into ~30-second windows for reasonable chunk sizes
            GROUP_DURATION = 30.0  # seconds
            current_texts = []
            group_start = 0.0
            group_end = 0.0
            block_index = 0

            for seg in segments:
                seg_start = seg.get("start", 0.0)
                seg_end = seg.get("end", 0.0)
                seg_text = seg.get("text", "").strip()

                if not seg_text:
                    continue

                if not current_texts:
                    group_start = seg_start

                current_texts.append(seg_text)
                group_end = seg_end

                # Flush group if duration exceeded
                if (group_end - group_start) >= GROUP_DURATION:
                    combined = " ".join(current_texts)
                    label = f"{self._format_time(group_start)} - {self._format_time(group_end)}"
                    blocks.append(ContentBlock(
                        text=combined,
                        source_type="transcript",
                        source_index=block_index,
                        source_label=label,
                        file_path=file_path,
                        modality="audio",
                        timestamp_start=group_start,
                        timestamp_end=group_end,
                        confidence=0.9,
                    ))
                    block_index += 1
                    current_texts = []

            # Flush remaining segments
            if current_texts:
                combined = " ".join(current_texts)
                label = f"{self._format_time(group_start)} - {self._format_time(group_end)}"
                blocks.append(ContentBlock(
                    text=combined,
                    source_type="transcript",
                    source_index=block_index,
                    source_label=label,
                    file_path=file_path,
                    modality="audio",
                    timestamp_start=group_start,
                    timestamp_end=group_end,
                    confidence=0.9,
                ))

            logger.info(
                "Audio transcription complete: %d blocks from '%s'",
                len(blocks), file_path
            )
            return blocks

        except Exception as e:
            logger.error("Audio transcription failed for '%s': %s", file_path, e)
            return []

    @staticmethod
    def _format_time(seconds: float) -> str:
        """Format seconds as MM:SS or HH:MM:SS.

        Args:
            seconds: Time in seconds.

        Returns:
            Formatted time string.
        """
        seconds = int(seconds)
        if seconds >= 3600:
            h = seconds // 3600
            m = (seconds % 3600) // 60
            s = seconds % 60
            return f"{h}:{m:02d}:{s:02d}"
        else:
            m = seconds // 60
            s = seconds % 60
            return f"{m}:{s:02d}"
