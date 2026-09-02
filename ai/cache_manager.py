"""AI Analysis cache manager for SQLite persistence.

Provides CRUD operations for storing and retrieving AI-generated analysis
results. Uses SHA-256 file hash as the identity key so that file renames
and moves preserve existing analysis.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Optional

from database.models import AIAnalysis

logger = logging.getLogger(__name__)


class AICacheManager:
    """Manages SQLite caching of AI analysis results.

    All lookups are by file content hash (SHA-256), not by file path.
    This ensures analysis persists across renames and moves.
    """

    def __init__(self, session_factory) -> None:
        """Initialize with a SQLAlchemy session factory.

        Args:
            session_factory: Callable that returns a new SQLAlchemy session.
        """
        self._session_factory = session_factory

    def get_analysis(self, file_hash: str) -> Optional[dict]:
        """Retrieve cached analysis by file content hash.

        Args:
            file_hash: SHA-256 hash of the file content.

        Returns:
            Dict with analysis data if found, None otherwise.
        """
        logger.debug("Looking up analysis for hash: %s", file_hash[:16])
        try:
            with self._session_factory() as session:
                record = session.query(AIAnalysis).filter_by(
                    file_hash=file_hash
                ).first()

                if record is None:
                    logger.debug("No cached analysis found for hash: %s", file_hash[:16])
                    return None

                result = self._record_to_dict(record)
                logger.debug("Found cached analysis for hash: %s", file_hash[:16])
                return result
        except Exception as e:
            logger.error("Error retrieving analysis for hash %s: %s", file_hash[:16], e)
            return None

    def store_analysis(self, file_hash: str, analysis: dict) -> bool:
        """Store or update an AI analysis result.

        Args:
            file_hash: SHA-256 hash of the file content.
            analysis: Dict containing summary, keywords, tags, category, language.

        Returns:
            True if stored successfully, False otherwise.
        """
        logger.info("Storing analysis for hash: %s", file_hash[:16])
        try:
            with self._session_factory() as session:
                existing = session.query(AIAnalysis).filter_by(
                    file_hash=file_hash
                ).first()

                keywords_json = json.dumps(analysis.get("keywords", []))
                tags_json = json.dumps(analysis.get("tags", []))

                if existing:
                    existing.summary = analysis.get("summary", "")
                    existing.keywords = keywords_json
                    existing.tags = tags_json
                    existing.category = analysis.get("category", "")
                    existing.language = analysis.get("language", "")
                    existing.ai_generated = True
                    existing.generated_time = datetime.now()
                    existing.prompt_version = analysis.get("prompt_version", "")
                    existing.model_name = analysis.get("model_name", "")
                    logger.info("Updated existing analysis for hash: %s", file_hash[:16])
                else:
                    record = AIAnalysis(
                        file_hash=file_hash,
                        summary=analysis.get("summary", ""),
                        keywords=keywords_json,
                        tags=tags_json,
                        category=analysis.get("category", ""),
                        language=analysis.get("language", ""),
                        ai_generated=True,
                        generated_time=datetime.now(),
                        prompt_version=analysis.get("prompt_version", ""),
                        model_name=analysis.get("model_name", ""),
                    )
                    session.add(record)
                    logger.info("Inserted new analysis for hash: %s", file_hash[:16])

                session.commit()
                return True
        except Exception as e:
            logger.error("Error storing analysis for hash %s: %s", file_hash[:16], e)
            return False

    def delete_analysis(self, file_hash: str) -> bool:
        """Delete cached analysis by file hash.

        Args:
            file_hash: SHA-256 hash of the file content.

        Returns:
            True if deleted, False otherwise.
        """
        logger.info("Deleting analysis for hash: %s", file_hash[:16])
        try:
            with self._session_factory() as session:
                record = session.query(AIAnalysis).filter_by(
                    file_hash=file_hash
                ).first()
                if record:
                    session.delete(record)
                    session.commit()
                    return True
                return False
        except Exception as e:
            logger.error("Error deleting analysis for hash %s: %s", file_hash[:16], e)
            return False

    def has_analysis(self, file_hash: str) -> bool:
        """Check if analysis exists for a file hash.

        Args:
            file_hash: SHA-256 hash of the file content.

        Returns:
            True if analysis exists, False otherwise.
        """
        try:
            with self._session_factory() as session:
                count = session.query(AIAnalysis).filter_by(
                    file_hash=file_hash
                ).count()
                return count > 0
        except Exception as e:
            logger.error("Error checking analysis for hash %s: %s", file_hash[:16], e)
            return False

    @staticmethod
    def _record_to_dict(record: AIAnalysis) -> dict:
        """Convert an AIAnalysis ORM record to a dictionary.

        Args:
            record: AIAnalysis SQLAlchemy model instance.

        Returns:
            Dictionary representation of the analysis.
        """
        keywords = []
        tags = []
        try:
            keywords = json.loads(record.keywords) if record.keywords else []
        except (json.JSONDecodeError, TypeError):
            pass
        try:
            tags = json.loads(record.tags) if record.tags else []
        except (json.JSONDecodeError, TypeError):
            pass

        return {
            "file_hash": record.file_hash,
            "summary": record.summary or "",
            "keywords": keywords,
            "tags": tags,
            "category": record.category or "",
            "language": record.language or "",
            "ai_generated": record.ai_generated,
            "generated_time": record.generated_time,
            "prompt_version": record.prompt_version or "",
            "model_name": record.model_name or "",
        }
