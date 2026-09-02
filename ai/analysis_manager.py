"""Analysis manager providing the public interface for AI-powered file analysis."""

import logging
import os
import time
from datetime import datetime, timezone
from threading import Event
from typing import Callable, Optional

from text_extraction import ExtractorFactory

from .ai_service import AIService
from .config import MODEL_NAME, PROMPT_VERSION

logger = logging.getLogger(__name__)


class AnalysisManager:
    """Public interface for AI-powered document analysis.

    Manages the end-to-end workflow of extracting text from files,
    computing file identity hashes, running AI analysis, persisting
    results to cache, and reporting progress to the caller.

    Supports cooperative cancellation via a threading.Event and
    optional 5-step progress reporting via a callback.
    """

    # Named steps used by progress_callback (current_step, total_steps)
    _TOTAL_STEPS = 5

    def __init__(self, ai_service: AIService, cache_manager=None) -> None:
        """Initialize the analysis manager.

        Args:
            ai_service: The AI service instance for text analysis.
            cache_manager: Optional AICacheManager for persisting results.
                           When provided, results are stored automatically.
        """
        self.ai_service = ai_service
        self.cache_manager = cache_manager
        logger.info("AnalysisManager initialized")

    def analyze_file(
        self,
        file_path: str,
        detail_level: str = "medium",
        progress_callback: Optional[Callable[[int, int], None]] = None,
        cancel_event: Optional[Event] = None,
    ) -> dict:
        """Analyze a file and return structured metadata.

        Runs the full 5-step pipeline:
          1. Validate file & extract text
          2. Build AI prompt
          3. Call Ollama (LLM inference)
          4. Parse JSON response
          5. Persist to cache (if cache_manager provided)

        Args:
            file_path: Path to the file to analyze.
            detail_level: One of 'low', 'medium', 'high'. Controls the depth of
                the summary and number of keywords/tags. Defaults to 'medium'.
            progress_callback: Optional callable(current_step, total_steps).
                Called after each pipeline step completes.
            cancel_event: Optional threading.Event. When set, the pipeline
                exits early and returns None.

        Returns:
            A dictionary containing: summary, keywords, tags, category,
            language, file_hash, generated_time, prompt_version, model_name.
            Returns None if cancelled. On error, returns a dict with an
            'error' key describing the failure.
        """
        logger.info("Starting file analysis: %s (level=%s)", file_path, detail_level)
        start_time = time.time()

        def _progress(step: int) -> None:
            if progress_callback is not None:
                progress_callback(step, self._TOTAL_STEPS)

        def _cancelled() -> bool:
            return cancel_event is not None and cancel_event.is_set()

        try:
            # ── Step 1: Validate file & extract text ──────────────────────────
            _progress(1)
            if _cancelled():
                return None

            if not os.path.exists(file_path):
                logger.error("File does not exist: %s", file_path)
                return {"error": f"File not found: {file_path}"}

            if not os.path.isfile(file_path):
                logger.error("Path is not a file: %s", file_path)
                return {"error": f"Path is not a file: {file_path}"}

            from engines.content_engine import UniversalContentEngine
            engine = UniversalContentEngine()
            text = engine.extract_full_text(file_path)

            if not text or not text.strip():
                logger.error("No text/content extracted from file: %s", file_path)
                return {"error": f"Unsupported file type or empty document — no text could be extracted from: {file_path}"}

            # ── Step 2: Build prompt ──────────────────────────────────────────
            _progress(2)
            if _cancelled():
                return None

            # (PromptBuilder is called inside AIService; step 2 is a logical
            #  checkpoint so callers can show "Building Prompt…" in the UI.)

            # ── Step 3: Call Ollama ───────────────────────────────────────────
            _progress(3)
            if _cancelled():
                return None

            analysis_result = self.ai_service.analyze_text(text, detail_level)

            if "error" in analysis_result:
                elapsed = time.time() - start_time
                logger.error(
                    "AI analysis failed for %s (%.2fs): %s",
                    file_path,
                    elapsed,
                    analysis_result["error"],
                )
                return analysis_result

            # ── Step 4: Parse & enrich ────────────────────────────────────────
            _progress(4)
            if _cancelled():
                return None

            file_hash = self._compute_file_hash(file_path)

            result = {
                "summary": analysis_result["summary"],
                "keywords": analysis_result["keywords"],
                "tags": analysis_result["tags"],
                "category": analysis_result["category"],
                "language": analysis_result["language"],
                "file_hash": file_hash,
                "generated_time": datetime.now(timezone.utc).isoformat(),
                "prompt_version": PROMPT_VERSION,
                "model_name": MODEL_NAME,
            }

            # ── Step 5: Persist to cache ──────────────────────────────────────
            _progress(5)
            if self.cache_manager is not None:
                self.cache_manager.store_analysis(file_hash, result)
                logger.debug("Analysis cached for hash %s", file_hash)

            elapsed = time.time() - start_time
            logger.info("File analysis completed in %.2fs: %s", elapsed, file_path)
            return result

        except Exception as exc:
            elapsed = time.time() - start_time
            logger.error(
                "Unexpected error analyzing file %s (%.2fs): %s",
                file_path,
                elapsed,
                exc,
            )
            return {"error": f"File analysis failed: {exc}"}

    def _compute_file_hash(self, file_path: str) -> str:
        """Compute SHA-256 hash of a file.

        Args:
            file_path: Path to the file to hash.

        Returns:
            Hexadecimal SHA-256 hash string.
        """
        from services.file_identity import calculate_sha256
        return calculate_sha256(file_path)

