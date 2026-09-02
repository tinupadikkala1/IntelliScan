"""Speech Engine for audio transcription using OpenAI Whisper.

Provides transcription with timestamps, language detection, and
segment-level output suitable for semantic search and citations.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import List, Optional

logger = logging.getLogger(__name__)


@dataclass
class TranscriptSegment:
    """A single segment of transcribed speech."""
    text: str
    start: float  # seconds
    end: float  # seconds
    language: str = ""
    confidence: float = 0.9


@dataclass
class TranscriptionResult:
    """Complete transcription result."""
    text: str
    segments: List[TranscriptSegment] = field(default_factory=list)
    language: str = ""
    duration: float = 0.0


class SpeechEngine:
    """Transcribes audio using OpenAI Whisper (local, CPU).

    Supports configurable model sizes for quality/speed tradeoff:
    - tiny: fastest, lowest quality (~39M params)
    - base: good balance (~74M params)
    - small: higher quality (~244M params)
    """

    def __init__(self, model_size: str = "base") -> None:
        """Initialize the speech engine.

        Args:
            model_size: Whisper model size ('tiny', 'base', 'small').
        """
        self._model_size = model_size
        self._model = None

    def _load_model(self):
        """Lazy-load the Whisper model."""
        if self._model is None:
            import whisper
            logger.info("Loading Whisper '%s' model...", self._model_size)
            self._model = whisper.load_model(self._model_size)
            logger.info("Whisper '%s' model loaded", self._model_size)
        return self._model

    def transcribe(self, audio_path: str) -> Optional[TranscriptionResult]:
        """Transcribe an audio file.

        Args:
            audio_path: Path to the audio file (WAV, MP3, FLAC, etc.)

        Returns:
            TranscriptionResult with full text and timestamped segments,
            or None on failure.
        """
        if not os.path.isfile(audio_path):
            logger.error("Audio file not found: %s", audio_path)
            return None

        try:
            import whisper
            # Safety check: ensure file has actual audio samples before calling transcribe
            try:
                audio_samples = whisper.load_audio(audio_path)
                if audio_samples is None or len(audio_samples) < 1600:
                    logger.warning("Audio file has insufficient audio samples (< 0.1s): %s", audio_path)
                    return None
            except Exception as check_err:
                logger.warning("Could not read audio samples from %s: %s", audio_path, check_err)
                return None

            model = self._load_model()
            logger.info("Transcribing: %s", audio_path)

            result = model.transcribe(
                audio_path,
                fp16=False,
                language=None,  # Auto-detect
            )


            # Build segments
            segments = []
            for seg in result.get("segments", []):
                segments.append(TranscriptSegment(
                    text=seg.get("text", "").strip(),
                    start=seg.get("start", 0.0),
                    end=seg.get("end", 0.0),
                    language=result.get("language", ""),
                ))

            # Calculate duration from last segment
            duration = segments[-1].end if segments else 0.0

            return TranscriptionResult(
                text=result.get("text", "").strip(),
                segments=segments,
                language=result.get("language", ""),
                duration=duration,
            )

        except ImportError:
            logger.error("Whisper not installed — run: pip install openai-whisper")
            return None
        except Exception as e:
            logger.error("Transcription failed for '%s': %s", audio_path, e)
            return None

    def is_available(self) -> bool:
        """Check if Whisper is available.

        Returns:
            True if whisper can be imported.
        """
        try:
            import whisper
            return True
        except ImportError:
            return False
