"""Object detection service — B7-2 (#8).

Implements genuine object detection on top of the existing Ollama vision
model (reuses VisionEngine plumbing, no new engine). The vision model is
prompted for a strict JSON array of detected objects:

    [{"label": "person", "confidence": 0.94, "box": [x1, y1, x2, y2]}]

Results are parsed defensively (malformed output → graceful empty list),
filtered by a minimum confidence threshold, and persisted to
``ai_analysis.objects_json`` keyed by SHA-256 (rename/move-safe).
"""

from __future__ import annotations

import base64
import json
import logging
import os
import re
from dataclasses import dataclass, field
from typing import List, Optional

import requests

from engines.config import OBJECT_DETECTION_VERSION, OLLAMA_BASE_URL

logger = logging.getLogger(__name__)

_JSON_BLOCK = re.compile(r"\[[\s\S]*\]")


@dataclass
class DetectedObject:
    """A single detected object with confidence and optional bounding box."""

    label: str
    confidence: float = 0.0
    box: Optional[List[int]] = None

    def to_dict(self) -> dict:
        return {
            "label": self.label,
            "confidence": round(self.confidence, 4),
            "box": self.box,
        }


class ObjectDetectionService:
    """Detects and persists objects in images via the local vision model."""

    def __init__(
        self,
        session_factory=None,
        vision_engine=None,
        model: str = "moondream:latest",
        base_url: str = OLLAMA_BASE_URL,
        threshold: float = 0.40,
        version: str = OBJECT_DETECTION_VERSION,
        resources=None,
    ) -> None:
        self._session_factory = session_factory
        self._vision = vision_engine
        self._model = model
        self._base_url = base_url.rstrip("/")
        self._threshold = threshold
        self._version = version
        self._resources = resources

    # ------------------------------------------------------------------ #
    def is_supported(self, file_path: str) -> bool:
        ext = os.path.splitext(file_path)[1].lower()
        from engines.config import IMAGE_EXTENSIONS
        return ext in IMAGE_EXTENSIONS

    def is_available(self) -> bool:
        if self._vision is not None and self._vision.is_available():
            return True
        try:
            r = requests.get(f"{self._base_url}/api/tags", timeout=5)
            return r.status_code == 200
        except Exception:
            return False

    # ------------------------------------------------------------------ #
    def detect(self, file_path: str) -> List[DetectedObject]:
        """Detect objects in an image; [] when unavailable/unreadable."""
        if not self.is_supported(file_path) or not os.path.isfile(file_path):
            return []
        if not self.is_available():
            return []
        try:
            with open(file_path, "rb") as f:
                image_b64 = base64.b64encode(f.read()).decode("utf-8")
        except OSError:
            return []

        prompt = (
            "Detect the objects visible in this image. Respond with ONLY a "
            "JSON array, no commentary. Each element must be an object with "
            '"label" (lowercase English noun), "confidence" (0..1), and '
            '"box" ([x1, y1, x2, y2] in pixel coordinates, or null if you '
            "cannot estimate it). Example: "
            '[{"label": "person", "confidence": 0.94, "box": [10, 20, 120, 300]}]. '
            "If no objects are clearly visible, respond with []."
        )
        try:
            if self._resources is not None:
                with self._resources.vision():
                    response = requests.post(
                        f"{self._base_url}/api/generate",
                        json={
                            "model": self._model,
                            "prompt": prompt,
                            "images": [image_b64],
                            "stream": False,
                            "options": {"temperature": 0.1},
                        },
                        timeout=90,
                    )
            else:
                response = requests.post(
                    f"{self._base_url}/api/generate",
                    json={
                        "model": self._model,
                        "prompt": prompt,
                        "images": [image_b64],
                        "stream": False,
                        "options": {"temperature": 0.1},
                    },
                    timeout=90,
                )
            if response.status_code != 200:
                logger.debug("Object detection API returned %d", response.status_code)
                return []
            raw = response.json().get("response", "")
            return self._parse(raw)
        except requests.ConnectionError:
            logger.debug("Cannot connect to Ollama for object detection")
            return []
        except Exception as exc:
            logger.debug("Object detection error: %s", exc)
            return []

    # ------------------------------------------------------------------ #
    def _parse(self, raw: str) -> List[DetectedObject]:
        """Parse the model's JSON array defensively (malformed → [])."""
        if not raw or not raw.strip():
            return []
        text = raw.strip()
        match = _JSON_BLOCK.search(text)
        if match:
            text = match.group(0)
        try:
            data = json.loads(text)
        except (json.JSONDecodeError, TypeError):
            # Last resort: try to extract a JSON array substring.
            try:
                start = text.find("[")
                end = text.rfind("]")
                if start != -1 and end > start:
                    data = json.loads(text[start:end + 1])
                else:
                    return []
            except (json.JSONDecodeError, TypeError):
                return []
        if not isinstance(data, list):
            return []

        out: List[DetectedObject] = []
        for item in data:
            if not isinstance(item, dict):
                continue
            label = str(item.get("label", "")).strip()
            if not label:
                continue
            try:
                conf = float(item.get("confidence", 0.0))
            except (TypeError, ValueError):
                conf = 0.0
            box = item.get("box")
            if isinstance(box, (list, tuple)) and len(box) == 4:
                box = [int(b) for b in box]
            else:
                box = None
            if conf < self._threshold:
                continue
            out.append(DetectedObject(label=label, confidence=conf, box=box))
        return out

    # ------------------------------------------------------------------ #
    def persist(self, file_path: str, objects: List[DetectedObject]) -> bool:
        """Persist detected objects on ai_analysis keyed by SHA-256."""
        if self._session_factory is None:
            return False
        try:
            from services.file_identity import calculate_sha256_safe
            file_hash = calculate_sha256_safe(file_path)
            if not file_hash:
                return False
            from database.models import AIAnalysis
            with self._session_factory() as session:
                row = session.query(AIAnalysis).filter_by(file_hash=file_hash).first()
                if row is None:
                    row = AIAnalysis(file_hash=file_hash)
                    session.add(row)
                row.objects_json = json.dumps([o.to_dict() for o in objects])
                session.commit()
                return True
        except Exception as exc:
            logger.error("Failed to persist objects for %s: %s", file_path, exc)
            return False

    def get(self, file_path: str) -> List[DetectedObject]:
        """Load persisted objects ([] when absent)."""
        if self._session_factory is None:
            return []
        try:
            from services.file_identity import calculate_sha256_safe
            file_hash = calculate_sha256_safe(file_path)
            if not file_hash:
                return []
            from database.models import AIAnalysis
            with self._session_factory() as session:
                row = session.query(AIAnalysis).filter_by(file_hash=file_hash).first()
                if row is None or not row.objects_json:
                    return []
                data = json.loads(row.objects_json)
                return [
                    DetectedObject(
                        label=o.get("label", ""),
                        confidence=float(o.get("confidence", 0.0)),
                        box=o.get("box"),
                    )
                    for o in data if isinstance(o, dict)
                ]
        except Exception as exc:
            logger.debug("Failed to load objects for %s: %s", file_path, exc)
            return []
