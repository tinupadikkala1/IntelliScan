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
    """Transcribes audio locally (faster-whisper preferred, openai-whisper fallback).

    Modern backend port: uses cached `Systran/faster-whisper-small` (ctranslate2,
    int8, multi-threaded) when installed — ~4x faster than openai-whisper base
    on i3-N305 CPU. Falls back to legacy `whisper.load_model` otherwise.
    Supports configurable model sizes for quality/speed tradeoff:
    - tiny: fastest, lowest quality (~39M params)
    - base: good balance (~74M params)
    - small: higher quality (~244M params)
    """

    def __init__(self, model_size: str = "base", backend: str = "auto") -> None:
        """Initialize the speech engine.

        Args:
            model_size: Whisper model size ('tiny', 'base', 'small').
            backend: 'auto'|'faster-whisper'|'whisper' — auto tries faster first.
        """
        self._model_size = model_size
        self._backend_pref = (backend or "auto").lower()
        self._model = None
        self._backend_used: str | None = None

    def _cpu_threads(self) -> int:
        try:
            from services.compute import resolve_threads

            try:
                from core.config import Config

                _c = Config()
                _t = resolve_threads(int(_c.get("compute.cpu_threads", 0) or 0))
                if bool(_c.get("compute.low_resource_mode", False)):
                    _t = min(_t, 2)
                return _t
            except Exception:
                return resolve_threads(0)
        except Exception:
            import os

            return os.cpu_count() or 4

    def _load_model(self):
        """Lazy-load STT model (faster-whisper preferred)."""
        if self._model is not None:
            return self._model
        # Try faster-whisper first (unless explicitly pinned to legacy)
        if self._backend_pref in ("auto", "faster-whisper", "faster_whisper"):
            try:
                from faster_whisper import WhisperModel

                threads = self._cpu_threads()
                logger.info("Loading faster-whisper '%s' (int8, %d threads)...", self._model_size, threads)
                self._model = WhisperModel(
                    self._model_size if self._model_size in ("tiny", "base", "small", "medium") else "small",
                    device="cpu",
                    compute_type="int8",
                    cpu_threads=threads,
                )
                self._backend_used = "faster-whisper"
                logger.info("faster-whisper '%s' loaded", self._model_size)
                return self._model
            except Exception as e:
                logger.info("faster-whisper unavailable (%s), falling back to openai-whisper", e)
        import whisper
        logger.info("Loading Whisper '%s' model...", self._model_size)
        self._model = whisper.load_model(self._model_size)
        self._backend_used = "whisper"
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
            model = self._load_model()
            logger.info("Transcribing (%s): %s", getattr(self, "_backend_used", "?"), audio_path)

            if getattr(self, "_backend_used", "") == "faster-whisper":
                try:
                    from core.config import Config as _SCfg

                    _low = bool(_SCfg().get("compute.low_resource_mode", False))
                except Exception:
                    _low = False
                fw_segments, fw_info = model.transcribe(audio_path, beam_size=1 if _low else 5)
                segments = []
                texts: list[str] = []
                for seg in fw_segments:
                    t = (getattr(seg, "text", "") or "").strip()
                    texts.append(t)
                    segments.append(TranscriptSegment(
                        text=t,
                        start=float(getattr(seg, "start", 0.0) or 0.0),
                        end=float(getattr(seg, "end", 0.0) or 0.0),
                        language=getattr(fw_info, "language", "") or "",
                    ))
                full = " ".join(texts).strip()
                duration = segments[-1].end if segments else 0.0
                return TranscriptionResult(
                    text=full,
                    segments=segments,
                    language=getattr(fw_info, "language", "") or "",
                    duration=duration,
                )

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
        """Check if any STT backend is available (faster-whisper preferred)."""
        try:
            import faster_whisper  # noqa: F401

            return True
        except ImportError:
            pass
        try:
            import whisper
            return True
        except ImportError:
            return False
