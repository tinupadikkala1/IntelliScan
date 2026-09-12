"""CLIP-based image embedding engine for visual semantic search.

Uses OpenAI CLIP (ViT-B/32) to embed images into the same vector space
as text, enabling natural language search over images. When you search
"red car", CLIP finds images of red cars without needing OCR.
"""

from __future__ import annotations

import logging
import os
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)

# Global CLIP model cache (heavy, load once)
_clip_model = None
_clip_preprocess = None


def _load_clip():
    """Lazy-load CLIP model (cached globally)."""
    global _clip_model, _clip_preprocess
    if _clip_model is None:
        import clip
        import torch
        try:
            from services.compute import resolve_threads

            torch.set_num_threads(max(1, resolve_threads(0)))
        except Exception:
            torch.set_num_threads(1)
        logger.info("Loading CLIP ViT-B/32 model...")
        _clip_model, _clip_preprocess = clip.load("ViT-B/32", device="cpu")
        logger.info("CLIP model loaded")
    return _clip_model, _clip_preprocess


class CLIPEngine:
    """Generates image embeddings using CLIP for visual semantic search.

    CLIP produces 512-dimensional vectors for both images and text
    in the same vector space. This means you can search images using
    natural language queries.
    """

    def __init__(self) -> None:
        self._dimension = 512  # CLIP ViT-B/32 output dimension

    @property
    def dimension(self) -> int:
        return self._dimension

    def embed_image(self, image_path: str) -> Optional[np.ndarray]:
        """Generate CLIP embedding for an image file.

        Args:
            image_path: Path to the image file.

        Returns:
            Normalized numpy array of shape (512,), or None on failure.
        """
        if not os.path.isfile(image_path):
            logger.error("CLIP: file not found: %s", image_path)
            return None

        try:
            import torch
            from PIL import Image

            try:
                from services.compute import resolve_threads

                torch.set_num_threads(max(1, resolve_threads(0)))
            except Exception:
                torch.set_num_threads(1)
            model, preprocess = _load_clip()

            with Image.open(image_path) as _img:
                image = _img.convert("RGB")
                image_input = preprocess(image).unsqueeze(0)

            with torch.no_grad():
                image_features = model.encode_image(image_input)

            # Normalize
            vector = image_features[0].numpy().astype(np.float32)
            vector = vector / np.linalg.norm(vector)
            return vector

        except Exception as e:
            logger.error("CLIP image embedding failed for '%s': %s", image_path, e)
            return None

    def embed_text(self, text: str) -> Optional[np.ndarray]:
        """Generate CLIP embedding for a text query.

        This allows searching images by text description.

        Args:
            text: Natural language description to search for.

        Returns:
            Normalized numpy array of shape (512,), or None on failure.
        """
        if not text or not text.strip():
            return None

        try:
            import clip
            import torch

            try:
                from services.compute import resolve_threads

                torch.set_num_threads(max(1, resolve_threads(0)))
            except Exception:
                torch.set_num_threads(1)
            model, _ = _load_clip()
            text_input = clip.tokenize([text], truncate=True)

            with torch.no_grad():
                text_features = model.encode_text(text_input)

            vector = text_features[0].numpy().astype(np.float32)
            vector = vector / np.linalg.norm(vector)
            return vector

        except Exception as e:
            logger.error("CLIP text embedding failed: %s", e)
            return None

    def is_available(self) -> bool:
        """Check if CLIP is available."""
        try:
            import clip
            return True
        except ImportError:
            return False
