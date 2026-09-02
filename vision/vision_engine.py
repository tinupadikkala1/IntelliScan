"""Vision Engine for image captioning and understanding.

Uses Ollama's vision-capable models to generate descriptions of images.
Falls back gracefully if no vision model is available.
"""

from __future__ import annotations

import base64
import logging
import os
from dataclasses import dataclass
from typing import Optional

import requests

from engines.config import OLLAMA_BASE_URL, VISION_MODEL

logger = logging.getLogger(__name__)


@dataclass
class VisionResult:
    """Result from vision analysis."""
    caption: str
    objects: list
    confidence: float


class VisionEngine:
    """Generates image captions and descriptions using Ollama vision models.

    Uses multimodal LLMs (e.g., llava, qwen-vl) to understand image content.
    """

    def __init__(
        self,
        model: str = None,
        base_url: str = OLLAMA_BASE_URL,
    ) -> None:
        """Initialize vision engine.

        Args:
            model: Ollama model name (must support images). Defaults to the
                centrally-configured vision model (moondream:latest).
            base_url: Ollama server URL.
        """
        self._model = model or VISION_MODEL
        self._base_url = base_url.rstrip("/")

    def caption_image(self, image_path: str) -> Optional[VisionResult]:
        """Generate a caption for an image.

        Args:
            image_path: Path to the image file.

        Returns:
            VisionResult with caption, or None if unavailable.
        """
        if not os.path.isfile(image_path):
            return None

        try:
            with open(image_path, "rb") as f:
                image_b64 = base64.b64encode(f.read()).decode("utf-8")

            response = requests.post(
                f"{self._base_url}/api/generate",
                json={
                    "model": self._model,
                    "prompt": (
                        "Describe this image in detail. Include: "
                        "1) Main subject or scene "
                        "2) Any visible text "
                        "3) Colors and layout "
                        "4) Any notable objects"
                    ),
                    "images": [image_b64],
                    "stream": False,
                    "options": {"temperature": 0.3},
                },
                timeout=60,
            )

            if response.status_code != 200:
                logger.debug("Vision API returned %d", response.status_code)
                return None

            caption = response.json().get("response", "").strip()
            if caption:
                return VisionResult(
                    caption=caption,
                    objects=[],
                    confidence=0.7,
                )

        except requests.ConnectionError:
            logger.debug("Cannot connect to Ollama for vision")
        except Exception as e:
            logger.debug("Vision captioning error: %s", e)

        return None

    def caption_frame(self, frame_array) -> Optional[str]:
        """Generate a caption for a video frame (numpy array).

        Args:
            frame_array: OpenCV frame (numpy BGR array).

        Returns:
            Caption string or None.
        """
        try:
            import cv2

            _, buffer = cv2.imencode('.jpg', frame_array)
            image_b64 = base64.b64encode(buffer).decode('utf-8')

            response = requests.post(
                f"{self._base_url}/api/generate",
                json={
                    "model": self._model,
                    "prompt": "Briefly describe what you see in this frame.",
                    "images": [image_b64],
                    "stream": False,
                },
                timeout=30,
            )

            if response.status_code == 200:
                return response.json().get("response", "").strip()
        except Exception:
            pass
        return None

    def is_available(self) -> bool:
        """Check if vision model is available.

        Returns:
            True if Ollama is reachable (vision capability depends on model).
        """
        try:
            r = requests.get(f"{self._base_url}/api/tags", timeout=5)
            return r.status_code == 200
        except Exception:
            return False
