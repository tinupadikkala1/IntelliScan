"""Image quality analysis service — B7-4 (#20).

Transparent, deterministic local quality metrics — no LLM required:

  - resolution (width × height), aspect ratio
  - sharpness (variance of Laplacian on a downscaled grayscale sample)
  - contrast (std of pixel intensities)
  - brightness / exposure (mean intensity)
  - file size
  - optional noise estimate (mean absolute difference vs 3×3 local mean)

Produces a 0..1 quality score, a human label and the metric breakdown.
Persists to ``ai_analysis.quality_score`` / ``quality_json`` keyed by
SHA-256 (rename/move-safe). Degrades gracefully when the image cannot be
decoded or when an optional imaging library is missing.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, Optional

from engines.config import IMAGE_QUALITY_VERSION

logger = logging.getLogger(__name__)


@dataclass
class QualityResult:
    """Deterministic image quality analysis result."""

    score: float
    label: str
    width: int = 0
    height: int = 0
    aspect_ratio: float = 0.0
    sharpness: float = 0.0
    contrast: float = 0.0
    brightness: float = 0.0
    noise: float = 0.0
    file_size: int = 0
    metrics: Dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "score": round(self.score, 4),
            "label": self.label,
            "width": self.width,
            "height": self.height,
            "aspect_ratio": round(self.aspect_ratio, 3),
            "sharpness": round(self.sharpness, 4),
            "contrast": round(self.contrast, 4),
            "brightness": round(self.brightness, 4),
            "noise": round(self.noise, 4),
            "file_size": self.file_size,
            "metrics": {k: round(v, 4) for k, v in self.metrics.items()},
        }


class ImageQualityService:
    """Computes and persists deterministic image-quality metrics."""

    def __init__(
        self,
        session_factory=None,
        version: str = IMAGE_QUALITY_VERSION,
    ) -> None:
        self._session_factory = session_factory
        self._version = version

    # ------------------------------------------------------------------ #
    def is_supported(self, file_path: str) -> bool:
        ext = os.path.splitext(file_path)[1].lower()
        from engines.config import IMAGE_EXTENSIONS
        return ext in IMAGE_EXTENSIONS

    def analyze(self, file_path: str) -> Optional[QualityResult]:
        """Compute quality metrics for an image file (None when unreadable)."""
        if not self.is_supported(file_path) or not os.path.isfile(file_path):
            return None
        try:
            return self._analyze_inner(file_path)
        except Exception as exc:
            logger.debug("Image quality analysis failed for %s: %s", file_path, exc)
            return None

    # ------------------------------------------------------------------ #
    def _analyze_inner(self, file_path: str) -> QualityResult:
        size = os.path.getsize(file_path)
        try:
            from PIL import Image
            img = Image.open(file_path)
            img.load()
        except Exception:
            return None
        width, height = img.size
        if width <= 0 or height <= 0:
            return None

        # Grayscale, downscaled sample (max 256 px on the long edge) so the
        # math is fast and CPU-friendly even for huge images.
        sample = img.convert("L")
        long_edge = max(width, height)
        if long_edge > 256:
            ratio = 256.0 / long_edge
            sample = sample.resize(
                (max(1, int(width * ratio)), max(1, int(height * ratio)))
            )
        px = list(sample.getdata())
        n = len(px)
        mean = sum(px) / n
        variance = sum((p - mean) ** 2 for p in px) / n
        contrast = variance ** 0.5

        # Sharpness: mean absolute difference between each pixel and its
        # right neighbour (cheap Laplacian-style edge energy).
        w, h = sample.size
        sharp_sum = 0.0
        count = 0
        for y in range(h):
            row_start = y * w
            for x in range(w - 1):
                sharp_sum += abs(px[row_start + x] - px[row_start + x + 1])
                count += 1
        sharpness = (sharp_sum / count) if count else 0.0

        # Noise estimate: mean |pixel - 3x3 local mean| on a small grid.
        noise = self._estimate_noise(sample)

        brightness = mean / 255.0
        contrast_n = min(contrast / 90.0, 1.0)
        sharp_n = min(sharpness / 40.0, 1.0)
        noise_n = max(0.0, 1.0 - noise / 30.0)

        # Resolution factor: reward reasonable resolution, penalize
        # extreme tiny images; huge images are fine (capped at 1.0).
        megapixels = (width * height) / 1_000_000
        res_n = min(megapixels / 0.3, 1.0)

        # Exposure: penalize very dark or very bright images.
        exposure_n = 1.0 - abs(brightness - 0.5) * 1.4
        exposure_n = max(0.0, min(exposure_n, 1.0))

        score = (
            0.30 * sharp_n
            + 0.20 * contrast_n
            + 0.15 * exposure_n
            + 0.15 * res_n
            + 0.10 * noise_n
            + 0.10 * min(1.0, (brightness if brightness > 0 else 0.0) + 0.5)
        )
        score = max(0.0, min(score, 1.0))

        if score >= 0.75:
            label = "Good"
        elif score >= 0.50:
            label = "Fair"
        elif score >= 0.30:
            label = "Poor"
        else:
            label = "Very Poor"

        return QualityResult(
            score=score,
            label=label,
            width=width,
            height=height,
            aspect_ratio=width / height if height else 0.0,
            sharpness=sharpness,
            contrast=contrast,
            brightness=brightness,
            noise=noise,
            file_size=size,
            metrics={
                "sharpness": sharp_n,
                "contrast": contrast_n,
                "exposure": exposure_n,
                "resolution": res_n,
                "noise": noise_n,
            },
        )

    @staticmethod
    def _estimate_noise(img) -> float:
        """Mean absolute deviation from a local 3x3 mean (sampled grid)."""
        w, h = img.size
        if w < 4 or h < 4:
            return 0.0
        px = img.load()
        total = 0.0
        count = 0
        step_x = max(1, w // 40)
        step_y = max(1, h // 40)
        for y in range(1, h - 1, step_y):
            for x in range(1, w - 1, step_x):
                vals = []
                for dy in (-1, 0, 1):
                    for dx in (-1, 0, 1):
                        if dx == 0 and dy == 0:
                            continue
                        vals.append(px[x + dx, y + dy])
                local_mean = sum(vals) / len(vals)
                total += abs(px[x, y] - local_mean)
                count += 1
        return total / count if count else 0.0

    # ------------------------------------------------------------------ #
    def persist(self, file_path: str, result: Optional[QualityResult]) -> bool:
        """Persist quality data on ai_analysis keyed by SHA-256."""
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
                if result is None:
                    row.quality_score = None
                    row.quality_json = None
                else:
                    row.quality_score = result.score
                    row.quality_json = json.dumps(result.to_dict())
                session.commit()
                return True
        except Exception as exc:
            logger.error("Failed to persist quality for %s: %s", file_path, exc)
            return False

    def get(self, file_path: str) -> Optional[QualityResult]:
        """Load a persisted quality result (None when absent)."""
        if self._session_factory is None:
            return None
        try:
            from services.file_identity import calculate_sha256_safe
            file_hash = calculate_sha256_safe(file_path)
            if not file_hash:
                return None
            from database.models import AIAnalysis
            with self._session_factory() as session:
                row = session.query(AIAnalysis).filter_by(file_hash=file_hash).first()
                if row is None or not row.quality_json:
                    return None
                data = json.loads(row.quality_json)
                return QualityResult(
                    score=data.get("score", 0.0),
                    label=data.get("label", "Unknown"),
                    width=data.get("width", 0),
                    height=data.get("height", 0),
                    aspect_ratio=data.get("aspect_ratio", 0.0),
                    sharpness=data.get("sharpness", 0.0),
                    contrast=data.get("contrast", 0.0),
                    brightness=data.get("brightness", 0.0),
                    noise=data.get("noise", 0.0),
                    file_size=data.get("file_size", 0),
                    metrics=data.get("metrics", {}),
                )
        except Exception as exc:
            logger.debug("Failed to load quality for %s: %s", file_path, exc)
            return None
