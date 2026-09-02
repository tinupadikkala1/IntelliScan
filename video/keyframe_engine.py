"""Keyframe Engine for extracting representative frames from video."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import List, Optional

logger = logging.getLogger(__name__)


@dataclass
class Keyframe:
    """A representative frame extracted from video."""
    frame_array: object  # numpy ndarray
    timestamp: float  # seconds
    frame_number: int


class KeyframeEngine:
    """Extracts keyframes (representative frames) from video files.

    Uses scene-change detection or interval-based sampling to select
    frames that best represent the video content.
    """

    def __init__(self, max_frames: int = 5, interval_seconds: float = 60.0) -> None:
        """Initialize keyframe engine.

        Args:
            max_frames: Maximum number of keyframes to extract.
            interval_seconds: Minimum interval between frames.
        """
        self._max_frames = max_frames
        self._interval_seconds = interval_seconds

    def extract_keyframes(self, video_path: str) -> List[Keyframe]:
        """Extract keyframes from a video file.

        Args:
            video_path: Path to the video file.

        Returns:
            List of Keyframe objects with frame data and timestamps.
        """
        if not os.path.isfile(video_path):
            logger.error("Video file not found: %s", video_path)
            return []

        try:
            import cv2

            cap = cv2.VideoCapture(video_path)
            if not cap.isOpened():
                logger.error("Cannot open video: %s", video_path)
                return []

            fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
            total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            duration = total_frames / fps if fps > 0 else 0

            # Calculate frame extraction points
            interval = max(self._interval_seconds, duration / self._max_frames)
            keyframes: List[Keyframe] = []

            t = 0.0
            while t < duration and len(keyframes) < self._max_frames:
                frame_num = int(t * fps)
                cap.set(cv2.CAP_PROP_POS_FRAMES, frame_num)
                ret, frame = cap.read()

                if ret and frame is not None:
                    keyframes.append(Keyframe(
                        frame_array=frame,
                        timestamp=t,
                        frame_number=frame_num,
                    ))

                t += interval

            cap.release()
            logger.info(
                "Extracted %d keyframes from '%s'",
                len(keyframes), video_path
            )
            return keyframes

        except ImportError:
            logger.error("OpenCV not available for keyframe extraction")
            return []
        except Exception as e:
            logger.error("Keyframe extraction error: %s", e)
            return []

    def is_available(self) -> bool:
        """Check if keyframe extraction is available.

        Returns:
            True if OpenCV is installed.
        """
        try:
            import cv2
            return True
        except ImportError:
            return False
