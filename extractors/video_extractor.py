"""Video extractor — audio transcription + keyframe captioning."""

from __future__ import annotations

import logging
import os
import subprocess
import tempfile
from typing import List

from engines.config import (
    KEYFRAME_INTERVAL_SECONDS,
    MAX_KEYFRAMES_PER_VIDEO,
    OLLAMA_BASE_URL,
    VIDEO_EXTENSIONS,
    VISION_MODEL,
)
from engines.content_engine import ContentBlock
from .base_extractor import BaseMultimodalExtractor

logger = logging.getLogger(__name__)

_VIDEO_EXT = VIDEO_EXTENSIONS


class VideoExtractor(BaseMultimodalExtractor):
    """Extracts content from video files.

    Pipeline:
    1. Extract audio track → Whisper transcription → timestamped text
    2. Extract keyframes → Vision captioning (optional)
    3. Merge into ContentBlock objects
    """

    def __init__(self, model_size: str = "base") -> None:
        """Initialize the video extractor.

        Args:
            model_size: Whisper model size for audio transcription.
        """
        self._model_size = model_size

    def supported_extensions(self) -> set:
        return _VIDEO_EXT

    def extract(self, file_path: str) -> List[ContentBlock]:
        """Extract content from a video file.

        Extracts the audio track, transcribes it, and optionally
        extracts keyframe descriptions.

        Args:
            file_path: Path to the video file.

        Returns:
            List of ContentBlock objects with transcription and captions.
        """
        file_path = os.path.abspath(file_path)
        blocks: List[ContentBlock] = []

        # Step 1: Extract audio and transcribe
        transcript_blocks = self._transcribe_audio(file_path)
        blocks.extend(transcript_blocks)

        # Step 2: Extract keyframes and caption (optional enhancement)
        keyframe_blocks = self._extract_keyframes(file_path)
        blocks.extend(keyframe_blocks)

        if not blocks:
            # Fallback
            basename = os.path.basename(file_path)
            blocks.append(ContentBlock(
                text=f"Video file: {basename}",
                source_type="filename",
                source_index=0,
                source_label="Filename",
                file_path=file_path,
                modality="video",
                confidence=0.3,
            ))

        return blocks

    def _transcribe_audio(self, file_path: str) -> List[ContentBlock]:
        """Extract audio from video and transcribe with Whisper.

        Args:
            file_path: Path to the video file.

        Returns:
            List of transcript ContentBlocks with timestamps.
        """
        # Extract audio to temp WAV file
        audio_path = self._extract_audio_track(file_path)
        if not audio_path:
            return []

        try:
            from .audio_extractor import AudioExtractor
            audio_ext = AudioExtractor(model_size=self._model_size)
            blocks = audio_ext.extract(audio_path)

            # Update blocks to reference the video file, not the temp audio
            for block in blocks:
                block.file_path = file_path
                block.modality = "video"
                block.source_type = "transcript"

            return blocks
        except Exception as e:
            logger.error("Video transcription failed: %s", e)
            return []
        finally:
            # Cleanup temp audio
            try:
                if audio_path and os.path.exists(audio_path):
                    os.unlink(audio_path)
            except OSError:
                pass

    def _extract_audio_track(self, file_path: str) -> str | None:
        """Extract audio track from video using ffmpeg.

        Args:
            file_path: Path to the video file.

        Returns:
            Path to extracted WAV file, or None on failure.
        """
        try:
            import shutil
            if not shutil.which("ffmpeg"):
                logger.error("ffmpeg not found in PATH")
                return None

            # Create temp file for audio
            fd, audio_path = tempfile.mkstemp(suffix=".wav")
            os.close(fd)

            # Extract audio with ffmpeg
            result = subprocess.run(
                [
                    "ffmpeg", "-y", "-i", file_path,
                    "-vn",  # No video
                    "-acodec", "pcm_s16le",  # PCM WAV
                    "-ar", "16000",  # 16kHz for Whisper
                    "-ac", "1",  # Mono
                    audio_path,
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=120,
            )

            if result.returncode != 0 or not os.path.exists(audio_path):
                logger.error("ffmpeg audio extraction failed for: %s", file_path)
                return None

            if os.path.getsize(audio_path) == 0:
                os.unlink(audio_path)
                logger.warning("Extracted audio is empty: %s", file_path)
                return None

            return audio_path

        except subprocess.TimeoutExpired:
            logger.error("ffmpeg timed out extracting audio from: %s", file_path)
            return None
        except Exception as e:
            logger.error("Audio track extraction error: %s", e)
            return None

    def _extract_keyframes(self, file_path: str) -> List[ContentBlock]:
        """Extract keyframes from video and generate captions.

        Uses OpenCV to extract frames at intervals, then uses
        vision model for captioning (if available).

        Args:
            file_path: Path to the video file.

        Returns:
            List of ContentBlocks with frame descriptions.
        """
        try:
            import cv2
            import base64
            import requests

            cap = cv2.VideoCapture(file_path)
            if not cap.isOpened():
                return []

            fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
            total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            duration = total_frames / fps if fps > 0 else 0

            # Extract frames at a configurable interval (resource-conscious)
            max_frames = MAX_KEYFRAMES_PER_VIDEO
            interval = max(KEYFRAME_INTERVAL_SECONDS, duration / max_frames)
            blocks: List[ContentBlock] = []
            frame_times = []

            t = 0.0
            while t < duration and len(frame_times) < max_frames:
                frame_times.append(t)
                t += interval

            for idx, frame_time in enumerate(frame_times):
                frame_num = int(frame_time * fps)
                cap.set(cv2.CAP_PROP_POS_FRAMES, frame_num)
                ret, frame = cap.read()
                if not ret:
                    continue

                # Try to caption the frame
                caption = self._caption_frame(frame)
                if caption:
                    from .audio_extractor import AudioExtractor
                    label = f"Frame at {AudioExtractor._format_time(frame_time)}"
                    blocks.append(ContentBlock(
                        text=caption,
                        source_type="keyframe",
                        source_index=idx,
                        source_label=label,
                        file_path=file_path,
                        modality="video",
                        timestamp_start=frame_time,
                        timestamp_end=frame_time,
                        confidence=0.6,
                    ))

            cap.release()
            return blocks

        except ImportError:
            logger.debug("OpenCV not available for keyframe extraction")
            return []
        except Exception as e:
            logger.debug("Keyframe extraction failed: %s", e)
            return []

    def _caption_frame(self, frame) -> str:
        """Generate a caption for a video frame using vision model.

        Args:
            frame: OpenCV frame (numpy array).

        Returns:
            Caption string, or empty string if unavailable.
        """
        try:
            import cv2
            import base64
            import requests

            # Encode frame to base64 JPEG
            _, buffer = cv2.imencode('.jpg', frame)
            image_b64 = base64.b64encode(buffer).decode('utf-8')

            url = f"{OLLAMA_BASE_URL.rstrip('/')}/api/generate"
            response = requests.post(
                url,
                json={
                    "model": VISION_MODEL,
                    "prompt": "Briefly describe what you see in this video frame.",
                    "images": [image_b64],
                    "stream": False,
                },
                timeout=30,
            )

            if response.status_code == 200:
                return response.json().get("response", "").strip()
            return ""
        except Exception:
            return ""
