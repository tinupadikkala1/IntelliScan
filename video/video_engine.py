"""Video Engine - coordinates audio transcription and keyframe analysis."""

from __future__ import annotations

import logging
import os
import subprocess
import tempfile
from typing import List, Optional

from engines.content_engine import ContentBlock
from speech.speech_engine import SpeechEngine
from .keyframe_engine import KeyframeEngine

logger = logging.getLogger(__name__)


class VideoEngine:
    """Coordinates video content extraction.

    Pipeline:
    1. Extract audio track from video (ffmpeg)
    2. Transcribe audio (Whisper via SpeechEngine)
    3. Extract keyframes (OpenCV via KeyframeEngine)
    4. Optionally caption keyframes (VisionEngine)
    5. Merge all into ContentBlocks
    """

    def __init__(
        self,
        speech_engine: Optional[SpeechEngine] = None,
        keyframe_engine: Optional[KeyframeEngine] = None,
    ) -> None:
        """Initialize video engine.

        Args:
            speech_engine: SpeechEngine instance (created if not provided).
            keyframe_engine: KeyframeEngine instance (created if not provided).
        """
        self._speech = speech_engine or SpeechEngine()
        self._keyframes = keyframe_engine or KeyframeEngine()

    def extract_audio_track(self, video_path: str) -> Optional[str]:
        """Extract audio track from video to a temp WAV file.

        Args:
            video_path: Path to the video file.

        Returns:
            Path to the temp WAV file, or None on failure.
        """
        import shutil
        if not shutil.which("ffmpeg"):
            logger.error("ffmpeg not found")
            return None

        try:
            fd, audio_path = tempfile.mkstemp(suffix=".wav")
            os.close(fd)

            result = subprocess.run(
                [
                    "ffmpeg", "-y", "-i", video_path,
                    "-vn", "-acodec", "pcm_s16le",
                    "-ar", "16000", "-ac", "1",
                    audio_path,
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=120,
            )

            if result.returncode != 0 or os.path.getsize(audio_path) == 0:
                os.unlink(audio_path)
                return None

            return audio_path
        except Exception as e:
            logger.error("Audio extraction failed: %s", e)
            return None

    def process(self, video_path: str) -> List[ContentBlock]:
        """Process a video file and extract all content.

        Args:
            video_path: Path to the video file.

        Returns:
            List of ContentBlock objects (transcript + keyframes).
        """
        video_path = os.path.abspath(video_path)
        blocks: List[ContentBlock] = []

        # Transcribe audio
        audio_path = self.extract_audio_track(video_path)
        if audio_path:
            try:
                result = self._speech.transcribe(audio_path)
                if result and result.segments:
                    # Group segments into ~30s blocks
                    blocks.extend(
                        self._segments_to_blocks(result.segments, video_path)
                    )
                elif result and result.text:
                    blocks.append(ContentBlock(
                        text=result.text,
                        source_type="transcript",
                        source_index=0,
                        source_label="Full Transcript",
                        file_path=video_path,
                        modality="video",
                        timestamp_start=0.0,
                        timestamp_end=result.duration,
                        confidence=0.9,
                    ))
            finally:
                try:
                    os.unlink(audio_path)
                except OSError:
                    pass

        import gc
        gc.collect()
        return blocks


    def _segments_to_blocks(self, segments, video_path: str) -> List[ContentBlock]:
        """Convert transcript segments to ContentBlocks grouped by time."""
        GROUP_DURATION = 30.0
        blocks: List[ContentBlock] = []
        current_texts = []
        group_start = 0.0
        group_end = 0.0
        idx = 0

        for seg in segments:
            if not seg.text.strip():
                continue
            if not current_texts:
                group_start = seg.start
            current_texts.append(seg.text)
            group_end = seg.end

            if (group_end - group_start) >= GROUP_DURATION:
                blocks.append(ContentBlock(
                    text=" ".join(current_texts),
                    source_type="transcript",
                    source_index=idx,
                    source_label=f"{self._fmt(group_start)} - {self._fmt(group_end)}",
                    file_path=video_path,
                    modality="video",
                    timestamp_start=group_start,
                    timestamp_end=group_end,
                    confidence=0.9,
                ))
                idx += 1
                current_texts = []

        if current_texts:
            blocks.append(ContentBlock(
                text=" ".join(current_texts),
                source_type="transcript",
                source_index=idx,
                source_label=f"{self._fmt(group_start)} - {self._fmt(group_end)}",
                file_path=video_path,
                modality="video",
                timestamp_start=group_start,
                timestamp_end=group_end,
                confidence=0.9,
            ))

        return blocks

    @staticmethod
    def _fmt(seconds: float) -> str:
        s = int(seconds)
        if s >= 3600:
            return f"{s // 3600}:{(s % 3600) // 60:02d}:{s % 60:02d}"
        return f"{s // 60}:{s % 60:02d}"
