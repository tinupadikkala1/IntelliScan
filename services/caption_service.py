"""Image caption service — B6-01 (#7).

Thin orchestration layer over the existing :class:`VisionEngine`:

    selected image
      ↓ validate (readable image file)
      ↓ VisionEngine.caption_image()        (reused — no second engine)
      ↓ persist caption on ai_analysis      (keyed by SHA-256 content hash)
      ↓ return caption for display

The caption is keyed by content hash, so renames/moves keep the caption and
regeneration replaces the previous result. Captions persist across restarts
and never touch the rest of the AI analysis row.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime
from typing import Optional

from engines.config import CAPTION_VERSION, VISION_MODEL

logger = logging.getLogger(__name__)

# Extensions this feature will caption (mirrors engines/config IMAGE_EXTENSIONS).
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tiff", ".tif", ".gif", ".svg"}


class CaptionError(Exception):
    """Raised when a caption cannot be generated (user-facing message)."""


class CaptionService:
    """Generates, persists and retrieves image captions."""

    def __init__(
        self,
        session_factory,
        vision_engine=None,
        resources=None,
        version: str = CAPTION_VERSION,
        model: str = VISION_MODEL,
    ) -> None:
        """Args:
            session_factory: DB session factory (ai_analysis persistence).
            vision_engine: VisionEngine instance (created if None).
            resources: AIResourceManager for bounded concurrency.
            version: caption version for regeneration policy.
            model: vision model name recorded on the caption.
        """
        self._session_factory = session_factory
        self._vision = vision_engine
        self._resources = resources
        self._version = version
        self._model = model

    # ------------------------------------------------------------------ #
    def _vision_engine(self):
        if self._vision is None:
            from vision.vision_engine import VisionEngine
            self._vision = VisionEngine(model=self._model)
        return self._vision

    def is_supported(self, file_path: str) -> bool:
        ext = os.path.splitext(file_path)[1].lower()
        return ext in IMAGE_EXTENSIONS

    def generate_caption(self, file_path: str) -> Optional[str]:
        """Generate + persist a caption for an image file.

        Returns the caption text, or None when the model is unavailable.
        Raises CaptionError for user-facing validation failures.
        """
        file_path = os.path.abspath(file_path)
        if not os.path.isfile(file_path):
            raise CaptionError("The selected file does not exist anymore.")
        if not self.is_supported(file_path):
            raise CaptionError(
                f"'{os.path.basename(file_path)}' is not a supported image file. "
                "Supported: png, jpg, jpeg, webp, bmp, tiff, gif."
            )
        # Try to decode the image before invoking the model.
        try:
            from PySide6.QtGui import QImage
            if QImage(file_path).isNull():
                raise CaptionError("The image file is unreadable or corrupted.")
        except CaptionError:
            raise
        except Exception:
            pass  # headless tests may not have Qt image plugins; model call will fail safely

        engine = self._vision_engine()
        if not engine.is_available():
            raise CaptionError(
                "The vision model is unavailable. Ensure Ollama is running with "
                f"the '{engine._model}' vision model installed."
            )

        resource = None
        if self._resources is not None:
            resource = self._resources.acquire("vision")
        try:
            result = engine.caption_image(file_path)
            if result is None or not result.caption.strip():
                raise CaptionError("The vision model returned an empty caption. Try again.")
            caption = result.caption.strip()
        finally:
            if resource is not None:
                self._resources.release(resource)

        self._persist(file_path, caption)
        return caption

    def _persist(self, file_path: str, caption: str) -> None:
        """Store the caption on the ai_analysis row keyed by content hash.

        Creates a minimal row when no AI analysis exists yet; replaces the
        prior caption (regeneration).
        """
        try:
            from services.file_identity import calculate_sha256_safe
            from database.models import AIAnalysis

            file_hash = calculate_sha256_safe(file_path)
            if not file_hash:
                return
            with self._session_factory() as session:
                row = (
                    session.query(AIAnalysis)
                    .filter(AIAnalysis.file_hash == file_hash)
                    .first()
                )
                if row is None:
                    row = AIAnalysis(file_hash=file_hash)
                    session.add(row)
                row.caption = caption
                row.caption_model = self._model
                row.caption_version = self._version
                row.captioned_at = datetime.now()
                session.commit()
        except Exception as exc:
            logger.error("Failed to persist caption for %s: %s", file_path, exc)
            raise CaptionError(f"Could not save the caption: {exc}") from exc

    # ------------------------------------------------------------------ #
    def get_caption(self, file_path: str) -> Optional[str]:
        """Read the persisted caption for a file (None if absent)."""
        try:
            from services.file_identity import calculate_sha256_safe
            from database.models import AIAnalysis

            file_hash = calculate_sha256_safe(file_path)
            if not file_hash:
                return None
            with self._session_factory() as session:
                row = (
                    session.query(AIAnalysis)
                    .filter(AIAnalysis.file_hash == file_hash)
                    .first()
                )
                return row.caption if row else None
        except Exception as exc:
            logger.debug("Failed to load caption for %s: %s", file_path, exc)
            return None

    def caption_version_of(self, file_path: str) -> Optional[str]:
        try:
            from services.file_identity import calculate_sha256_safe
            from database.models import AIAnalysis

            file_hash = calculate_sha256_safe(file_path)
            if not file_hash:
                return None
            with self._session_factory() as session:
                row = (
                    session.query(AIAnalysis)
                    .filter(AIAnalysis.file_hash == file_hash)
                    .first()
                )
                return row.caption_version if row else None
        except Exception:
            return None
