"""Batch 5 store — SQLite persistence for collections, saved searches,
file relationships and organization suggestions.

Follows the GraphStore pattern: per-call sessions, shared Base, deduped
writes, and PersistenceError on failure (Batch 4 M0-06 convention).
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import List, Optional

from sqlalchemy import func

from database.models import (
    Collection,
    CollectionItem,
    DuplicateSuggestion,
    FileRelationship,
    OrganizationSuggestion,
    SavedSearch,
)

from .batch5_models import (
    CollectionInfo,
    DuplicateRemovalSuggestion,
    FileRelationshipInfo,
    SavedSearchInfo,
    SuggestionInfo,
)

logger = logging.getLogger(__name__)


class Batch5PersistenceError(Exception):
    """Raised when a Batch 5 database write cannot be completed."""


class Batch5Store:
    """Persistence for Batch 5 organization tables."""

    def __init__(self, session_factory) -> None:
        self._session_factory = session_factory

    # ================================================================ #
    # Collections (B5-03)
    # ================================================================ #
    def create_collection(
        self,
        name: str,
        description: str = "",
        is_smart: bool = False,
        criteria: Optional[dict] = None,
    ) -> int:
        try:
            with self._session_factory() as session:
                col = Collection(
                    name=name,
                    description=description or "",
                    is_smart=is_smart,
                    criteria_json=json.dumps(criteria or {}),
                )
                session.add(col)
                session.commit()
                return col.id
        except Exception as e:
            logger.error("Failed to create collection '%s': %s", name, e)
            raise Batch5PersistenceError(f"Could not create collection '{name}': {e}") from e

    def list_collections(self) -> List[CollectionInfo]:
        try:
            with self._session_factory() as session:
                rows = session.query(Collection).order_by(Collection.name).all()
                out = []
                for r in rows:
                    count = (
                        session.query(CollectionItem)
                        .filter(CollectionItem.collection_id == r.id)
                        .count()
                    )
                    out.append(self._collection_info(r, count))
                return out
        except Exception as e:
            logger.error("Failed to list collections: %s", e)
            raise Batch5PersistenceError(f"Could not list collections: {e}") from e

    def get_collection(self, collection_id: int) -> Optional[CollectionInfo]:
        try:
            with self._session_factory() as session:
                r = session.get(Collection, collection_id)
                if r is None:
                    return None
                count = (
                    session.query(CollectionItem)
                    .filter(CollectionItem.collection_id == collection_id)
                    .count()
                )
                return self._collection_info(r, count)
        except Exception as e:
            logger.error("Failed to get collection %s: %s", collection_id, e)
            raise Batch5PersistenceError(f"Could not load collection {collection_id}: {e}") from e

    def rename_collection(self, collection_id: int, name: str) -> bool:
        try:
            with self._session_factory() as session:
                r = session.get(Collection, collection_id)
                if r is None:
                    return False
                r.name = name
                r.updated_at = datetime.now()
                session.commit()
                return True
        except Exception as e:
            logger.error("Failed to rename collection %s: %s", collection_id, e)
            raise Batch5PersistenceError(f"Could not rename collection {collection_id}: {e}") from e

    def update_collection_criteria(self, collection_id: int, criteria: dict) -> bool:
        try:
            with self._session_factory() as session:
                r = session.get(Collection, collection_id)
                if r is None:
                    return False
                r.criteria_json = json.dumps(criteria or {})
                r.updated_at = datetime.now()
                session.commit()
                return True
        except Exception as e:
            logger.error("Failed to update criteria for %s: %s", collection_id, e)
            raise Batch5PersistenceError(f"Could not update collection criteria: {e}") from e

    def delete_collection(self, collection_id: int) -> bool:
        try:
            with self._session_factory() as session:
                r = session.get(Collection, collection_id)
                if r is None:
                    return False
                session.delete(r)  # cascade removes collection_items
                session.commit()
                return True
        except Exception as e:
            logger.error("Failed to delete collection %s: %s", collection_id, e)
            raise Batch5PersistenceError(f"Could not delete collection {collection_id}: {e}") from e

    # ------------------------------------------------------------------ #
    # Collection items
    # ------------------------------------------------------------------ #
    def add_item(self, collection_id: int, file_path: str, source: str = "manual") -> bool:
        """Add a member; deduped on (collection_id, file_path)."""
        try:
            with self._session_factory() as session:
                col = session.get(Collection, collection_id)
                if col is None:
                    return False
                existing = (
                    session.query(CollectionItem)
                    .filter(
                        CollectionItem.collection_id == collection_id,
                        CollectionItem.file_path == file_path,
                    )
                    .first()
                )
                if existing is None:
                    session.add(CollectionItem(
                        collection_id=collection_id,
                        file_path=file_path,
                        source=source,
                    ))
                session.commit()
                return True
        except Exception as e:
            logger.error("Failed to add item to collection %s: %s", collection_id, e)
            raise Batch5PersistenceError(f"Could not add item to collection: {e}") from e

    def remove_item(self, collection_id: int, file_path: str) -> bool:
        try:
            with self._session_factory() as session:
                existing = (
                    session.query(CollectionItem)
                    .filter(
                        CollectionItem.collection_id == collection_id,
                        CollectionItem.file_path == file_path,
                    )
                    .first()
                )
                if existing is None:
                    return False
                session.delete(existing)
                session.commit()
                return True
        except Exception as e:
            logger.error("Failed to remove item from collection %s: %s", collection_id, e)
            raise Batch5PersistenceError(f"Could not remove item from collection: {e}") from e

    def clear_collection_items(self, collection_id: int) -> int:
        """Remove all members of a collection (smart refresh)."""
        try:
            with self._session_factory() as session:
                count = (
                    session.query(CollectionItem)
                    .filter(CollectionItem.collection_id == collection_id)
                    .delete(synchronize_session=False)
                )
                session.commit()
                return count or 0
        except Exception as e:
            logger.error("Failed to clear collection %s items: %s", collection_id, e)
            raise Batch5PersistenceError(f"Could not clear collection items: {e}") from e

    def collection_paths(self, collection_id: int) -> List[str]:
        try:
            with self._session_factory() as session:
                rows = (
                    session.query(CollectionItem.file_path)
                    .filter(CollectionItem.collection_id == collection_id)
                    .all()
                )
                return [r[0] for r in rows]
        except Exception as e:
            logger.error("Failed to load collection %s paths: %s", collection_id, e)
            return []

    def collections_for_path(self, file_path: str) -> List[int]:
        """Collection ids that contain a given path (membership)."""
        try:
            with self._session_factory() as session:
                rows = (
                    session.query(CollectionItem.collection_id)
                    .filter(CollectionItem.file_path == file_path)
                    .all()
                )
                return [r[0] for r in rows]
        except Exception as e:
            logger.error("Failed to load collections for %s: %s", file_path, e)
            return []

    def all_collection_paths(self) -> dict:
        """Map collection_id → list of member paths (for sync/refresh)."""
        try:
            with self._session_factory() as session:
                rows = session.query(CollectionItem).all()
                out: dict = {}
                for r in rows:
                    out.setdefault(r.collection_id, []).append(r.file_path)
                return out
        except Exception as e:
            logger.error("Failed to load all collection paths: %s", e)
            return {}

    # ================================================================ #
    # Saved searches (B5-09)
    # ================================================================ #
    def create_saved_search(
        self,
        name: str,
        query: str,
        scope: str = "workspace",
        scope_path: str = "",
        modality: str = "all",
        filters: Optional[dict] = None,
    ) -> int:
        try:
            with self._session_factory() as session:
                row = SavedSearch(
                    name=name,
                    query=query,
                    scope=scope,
                    scope_path=scope_path,
                    modality=modality,
                    filters_json=json.dumps(filters or {}),
                )
                session.add(row)
                session.commit()
                return row.id
        except Exception as e:
            logger.error("Failed to create saved search '%s': %s", name, e)
            raise Batch5PersistenceError(f"Could not create saved search '{name}': {e}") from e

    def list_saved_searches(self) -> List[SavedSearchInfo]:
        try:
            with self._session_factory() as session:
                rows = (
                    session.query(SavedSearch)
                    .order_by(SavedSearch.name)
                    .all()
                )
                return [self._saved_search_info(r) for r in rows]
        except Exception as e:
            logger.error("Failed to list saved searches: %s", e)
            raise Batch5PersistenceError(f"Could not list saved searches: {e}") from e

    def get_saved_search(self, search_id: int) -> Optional[SavedSearchInfo]:
        try:
            with self._session_factory() as session:
                r = session.get(SavedSearch, search_id)
                return self._saved_search_info(r) if r else None
        except Exception as e:
            logger.error("Failed to get saved search %s: %s", search_id, e)
            raise Batch5PersistenceError(f"Could not load saved search {search_id}: {e}") from e

    def rename_saved_search(self, search_id: int, name: str) -> bool:
        try:
            with self._session_factory() as session:
                r = session.get(SavedSearch, search_id)
                if r is None:
                    return False
                r.name = name
                r.updated_at = datetime.now()
                session.commit()
                return True
        except Exception as e:
            logger.error("Failed to rename saved search %s: %s", search_id, e)
            raise Batch5PersistenceError(f"Could not rename saved search {search_id}: {e}") from e

    def update_saved_search_config(
        self,
        search_id: int,
        scope: Optional[str] = None,
        scope_path: Optional[str] = None,
        modality: Optional[str] = None,
        filters: Optional[dict] = None,
    ) -> bool:
        try:
            with self._session_factory() as session:
                r = session.get(SavedSearch, search_id)
                if r is None:
                    return False
                if scope is not None:
                    r.scope = scope
                if scope_path is not None:
                    r.scope_path = scope_path
                if modality is not None:
                    r.modality = modality
                if filters is not None:
                    r.filters_json = json.dumps(filters)
                r.updated_at = datetime.now()
                session.commit()
                return True
        except Exception as e:
            logger.error("Failed to update saved search %s: %s", search_id, e)
            raise Batch5PersistenceError(f"Could not update saved search: {e}") from e

    def touch_saved_search(self, search_id: int) -> None:
        try:
            with self._session_factory() as session:
                r = session.get(SavedSearch, search_id)
                if r is not None:
                    r.last_run = datetime.now()
                    session.commit()
        except Exception as e:
            logger.debug("Failed to touch saved search %s: %s", search_id, e)

    def delete_saved_search(self, search_id: int) -> bool:
        try:
            with self._session_factory() as session:
                r = session.get(SavedSearch, search_id)
                if r is None:
                    return False
                session.delete(r)
                session.commit()
                return True
        except Exception as e:
            logger.error("Failed to delete saved search %s: %s", search_id, e)
            raise Batch5PersistenceError(f"Could not delete saved search {search_id}: {e}") from e

    # ================================================================ #
    # File relationships (B5-07)
    # ================================================================ #
    def upsert_relationship(
        self,
        source_path: str,
        target_path: str,
        relationship_type: str,
        confidence: float = 1.0,
        evidence: Optional[dict] = None,
    ) -> int:
        """Create or update a deduped edge; returns its id."""
        if source_path == target_path:
            raise Batch5PersistenceError("Cannot create a self-referencing relationship")
        try:
            with self._session_factory() as session:
                existing = (
                    session.query(FileRelationship)
                    .filter(
                        FileRelationship.source_path == source_path,
                        FileRelationship.target_path == target_path,
                        FileRelationship.relationship_type == relationship_type,
                    )
                    .first()
                )
                if existing is not None:
                    if confidence > (existing.confidence or 0.0):
                        existing.confidence = confidence
                        existing.evidence_json = json.dumps(evidence or {})
                        existing.updated_at = datetime.now()
                        session.commit()
                    return existing.id
                row = FileRelationship(
                    source_path=source_path,
                    target_path=target_path,
                    relationship_type=relationship_type,
                    confidence=confidence,
                    evidence_json=json.dumps(evidence or {}),
                )
                session.add(row)
                session.commit()
                return row.id
        except Batch5PersistenceError:
            raise
        except Exception as e:
            logger.error("Failed to upsert relationship %s->%s: %s", source_path, target_path, e)
            raise Batch5PersistenceError(f"Could not upsert relationship: {e}") from e

    def relationships_for_path(self, path: str) -> List[FileRelationshipInfo]:
        try:
            with self._session_factory() as session:
                rows = (
                    session.query(FileRelationship)
                    .filter(
                        (FileRelationship.source_path == path)
                        | (FileRelationship.target_path == path)
                    )
                    .order_by(FileRelationship.confidence.desc())
                    .all()
                )
                return [self._relationship_info(r) for r in rows]
        except Exception as e:
            logger.error("Failed to load relationships for %s: %s", path, e)
            return []

    def relationships_by_type(self, relationship_type: str, limit: int = 200) -> List[FileRelationshipInfo]:
        try:
            with self._session_factory() as session:
                rows = (
                    session.query(FileRelationship)
                    .filter(FileRelationship.relationship_type == relationship_type)
                    .order_by(FileRelationship.confidence.desc())
                    .limit(limit)
                    .all()
                )
                return [self._relationship_info(r) for r in rows]
        except Exception as e:
            logger.error("Failed to load relationships of type %s: %s", relationship_type, e)
            return []

    def all_relationships(self, limit: int = 1000) -> List[FileRelationshipInfo]:
        try:
            with self._session_factory() as session:
                rows = (
                    session.query(FileRelationship)
                    .order_by(FileRelationship.confidence.desc())
                    .limit(limit)
                    .all()
                )
                return [self._relationship_info(r) for r in rows]
        except Exception as e:
            logger.error("Failed to load all relationships: %s", e)
            return []

    def delete_relationship(self, relationship_id: int) -> bool:
        try:
            with self._session_factory() as session:
                r = session.get(FileRelationship, relationship_id)
                if r is None:
                    return False
                session.delete(r)
                session.commit()
                return True
        except Exception as e:
            logger.error("Failed to delete relationship %s: %s", relationship_id, e)
            raise Batch5PersistenceError(f"Could not delete relationship {relationship_id}: {e}") from e

    def clear_relationships(self) -> int:
        try:
            with self._session_factory() as session:
                count = session.query(FileRelationship).delete()
                session.commit()
                return count or 0
        except Exception as e:
            logger.error("Failed to clear relationships: %s", e)
            raise Batch5PersistenceError(f"Could not clear relationships: {e}") from e

    # ================================================================ #
    # Organization suggestions (B5-08)
    # ================================================================ #
    def create_suggestion(
        self,
        file_path: str,
        suggested_target: str,
        target_type: str = "collection",
        reason: str = "",
        confidence: float = 0.0,
    ) -> int:
        try:
            with self._session_factory() as session:
                row = OrganizationSuggestion(
                    file_path=file_path,
                    suggested_target=suggested_target,
                    target_type=target_type,
                    reason=reason or "",
                    confidence=confidence,
                    status="pending",
                )
                session.add(row)
                session.commit()
                return row.id
        except Exception as e:
            logger.error("Failed to create suggestion for %s: %s", file_path, e)
            raise Batch5PersistenceError(f"Could not create suggestion: {e}") from e

    def list_suggestions(self, status: Optional[str] = None, limit: int = 200) -> List[SuggestionInfo]:
        try:
            with self._session_factory() as session:
                q = session.query(OrganizationSuggestion)
                if status:
                    q = q.filter(OrganizationSuggestion.status == status)
                rows = q.order_by(OrganizationSuggestion.confidence.desc()).limit(limit).all()
                return [self._suggestion_info(r) for r in rows]
        except Exception as e:
            logger.error("Failed to list suggestions: %s", e)
            return []

    def suggestions_for_path(self, file_path: str) -> List[SuggestionInfo]:
        try:
            with self._session_factory() as session:
                rows = (
                    session.query(OrganizationSuggestion)
                    .filter(OrganizationSuggestion.file_path == file_path)
                    .order_by(OrganizationSuggestion.confidence.desc())
                    .all()
                )
                return [self._suggestion_info(r) for r in rows]
        except Exception as e:
            logger.error("Failed to load suggestions for %s: %s", file_path, e)
            return []

    def set_suggestion_status(self, suggestion_id: int, status: str) -> bool:
        try:
            with self._session_factory() as session:
                r = session.get(OrganizationSuggestion, suggestion_id)
                if r is None:
                    return False
                r.status = status
                r.updated_at = datetime.now()
                session.commit()
                return True
        except Exception as e:
            logger.error("Failed to set suggestion %s status: %s", suggestion_id, e)
            raise Batch5PersistenceError(f"Could not update suggestion status: {e}") from e

    def get_suggestion(self, suggestion_id: int) -> Optional[SuggestionInfo]:
        try:
            with self._session_factory() as session:
                r = session.get(OrganizationSuggestion, suggestion_id)
                return self._suggestion_info(r) if r else None
        except Exception as e:
            logger.error("Failed to get suggestion %s: %s", suggestion_id, e)
            return None

    def update_suggestion_reason(self, suggestion_id: int, reason: str) -> bool:
        """Attach an LLM-generated explanation to a pending suggestion."""
        try:
            with self._session_factory() as session:
                r = session.get(OrganizationSuggestion, suggestion_id)
                if r is None:
                    return False
                r.reason = reason
                r.updated_at = datetime.now()
                session.commit()
                return True
        except Exception as e:
            logger.error("Failed to update suggestion %s reason: %s", suggestion_id, e)
            return False

    # ================================================================ #
    # Duplicate removal suggestions (B6-04)
    # ================================================================ #
    def create_duplicate_suggestion(
        self,
        group_checksum: str,
        keep_path: str,
        remove_path: str,
        duplicate_type: str = "exact",
        confidence: float = 0.0,
        reason: str = "",
        evidence: Optional[dict] = None,
    ) -> int:
        """Persist one removal recommendation; deduped on (group, remove)."""
        try:
            with self._session_factory() as session:
                existing = (
                    session.query(DuplicateSuggestion)
                    .filter(
                        DuplicateSuggestion.group_checksum == group_checksum,
                        DuplicateSuggestion.remove_path == remove_path,
                    )
                    .first()
                )
                if existing is not None:
                    existing.keep_path = keep_path
                    existing.duplicate_type = duplicate_type
                    existing.confidence = confidence
                    existing.reason = reason or ""
                    existing.evidence_json = json.dumps(evidence or {})
                    existing.updated_at = datetime.now()
                    session.commit()
                    return existing.id
                row = DuplicateSuggestion(
                    group_checksum=group_checksum,
                    keep_path=keep_path,
                    remove_path=remove_path,
                    duplicate_type=duplicate_type,
                    confidence=confidence,
                    reason=reason or "",
                    evidence_json=json.dumps(evidence or {}),
                    status="pending",
                )
                session.add(row)
                session.commit()
                return row.id
        except Exception as e:
            logger.error("Failed to create duplicate suggestion: %s", e)
            raise Batch5PersistenceError(f"Could not create duplicate suggestion: {e}") from e

    def list_duplicate_suggestions(
        self, status: Optional[str] = None, limit: int = 300
    ) -> List[DuplicateRemovalSuggestion]:
        try:
            with self._session_factory() as session:
                q = session.query(DuplicateSuggestion)
                if status:
                    q = q.filter(DuplicateSuggestion.status == status)
                rows = q.order_by(DuplicateSuggestion.confidence.desc()).limit(limit).all()
                return [self._dup_suggestion_info(r) for r in rows]
        except Exception as e:
            logger.error("Failed to list duplicate suggestions: %s", e)
            return []

    def duplicate_suggestions_for_checksum(
        self, group_checksum: str
    ) -> List[DuplicateRemovalSuggestion]:
        try:
            with self._session_factory() as session:
                rows = (
                    session.query(DuplicateSuggestion)
                    .filter(DuplicateSuggestion.group_checksum == group_checksum)
                    .order_by(DuplicateSuggestion.confidence.desc())
                    .all()
                )
                return [self._dup_suggestion_info(r) for r in rows]
        except Exception as e:
            logger.error("Failed to load duplicate suggestions for %s: %s", group_checksum, e)
            return []

    def get_duplicate_suggestion(self, suggestion_id: int) -> Optional[DuplicateRemovalSuggestion]:
        try:
            with self._session_factory() as session:
                r = session.get(DuplicateSuggestion, suggestion_id)
                return self._dup_suggestion_info(r) if r else None
        except Exception as e:
            logger.error("Failed to get duplicate suggestion %s: %s", suggestion_id, e)
            return None

    def set_duplicate_suggestion_status(self, suggestion_id: int, status: str) -> bool:
        try:
            with self._session_factory() as session:
                r = session.get(DuplicateSuggestion, suggestion_id)
                if r is None:
                    return False
                r.status = status
                r.updated_at = datetime.now()
                session.commit()
                return True
        except Exception as e:
            logger.error("Failed to set duplicate suggestion %s status: %s", suggestion_id, e)
            return False

    def clear_duplicate_suggestions_for_group(self, group_checksum: str) -> int:
        try:
            with self._session_factory() as session:
                count = (
                    session.query(DuplicateSuggestion)
                    .filter(DuplicateSuggestion.group_checksum == group_checksum)
                    .delete(synchronize_session=False)
                )
                session.commit()
                return count or 0
        except Exception as e:
            logger.error("Failed to clear duplicate suggestions for %s: %s", group_checksum, e)
            return 0

    @staticmethod
    def _dup_suggestion_info(row: DuplicateSuggestion) -> DuplicateRemovalSuggestion:
        evidence = {}
        if row.evidence_json:
            try:
                evidence = json.loads(row.evidence_json) or {}
            except (json.JSONDecodeError, TypeError):
                evidence = {}
        return DuplicateRemovalSuggestion(
            id=row.id,
            group_checksum=row.group_checksum,
            keep_path=row.keep_path,
            remove_path=row.remove_path,
            duplicate_type=row.duplicate_type or "exact",
            confidence=row.confidence or 0.0,
            reason=row.reason or "",
            evidence=evidence,
            status=row.status or "pending",
        )

    # ================================================================ #
    # Stats / helpers
    # ================================================================ #
    def stats(self) -> dict:
        try:
            with self._session_factory() as session:
                rows = (
                    session.query(FileRelationship.relationship_type, func.count())
                    .group_by(FileRelationship.relationship_type)
                    .all()
                )
                rel_counts = {rel_type: count for rel_type, count in rows}
                return {
                    "collections": session.query(Collection).count(),
                    "smart_collections": session.query(Collection).filter(Collection.is_smart == True).count(),
                    "collection_items": session.query(CollectionItem).count(),
                    "saved_searches": session.query(SavedSearch).count(),
                    "relationships": session.query(FileRelationship).count(),
                    "relationships_by_type": rel_counts,
                    "suggestions_pending": session.query(OrganizationSuggestion)
                    .filter(OrganizationSuggestion.status == "pending").count(),
                    "suggestions_accepted": session.query(OrganizationSuggestion)
                    .filter(OrganizationSuggestion.status == "accepted").count(),
                    "duplicate_suggestions_pending": session.query(DuplicateSuggestion)
                    .filter(DuplicateSuggestion.status == "pending").count(),
                    "duplicate_suggestions_executed": session.query(DuplicateSuggestion)
                    .filter(DuplicateSuggestion.status == "executed").count(),
                }
        except Exception as e:
            logger.error("Failed to compute Batch 5 stats: %s", e)
            return {
                "collections": 0, "smart_collections": 0, "collection_items": 0,
                "saved_searches": 0, "relationships": 0,
                "relationships_by_type": {}, "suggestions_pending": 0,
                "suggestions_accepted": 0,
            }

    # ------------------------------------------------------------------ #
    @staticmethod
    def _collection_info(row: Collection, member_count: int) -> CollectionInfo:
        criteria = {}
        if row.criteria_json:
            try:
                criteria = json.loads(row.criteria_json) or {}
            except (json.JSONDecodeError, TypeError):
                criteria = {}
        return CollectionInfo(
            id=row.id,
            name=row.name,
            description=row.description or "",
            is_smart=bool(row.is_smart),
            criteria=criteria,
            member_count=member_count,
        )

    @staticmethod
    def _saved_search_info(row: SavedSearch) -> SavedSearchInfo:
        filters = {}
        if row.filters_json:
            try:
                filters = json.loads(row.filters_json) or {}
            except (json.JSONDecodeError, TypeError):
                filters = {}
        return SavedSearchInfo(
            id=row.id,
            name=row.name,
            query=row.query,
            scope=row.scope or "workspace",
            scope_path=row.scope_path or "",
            modality=row.modality or "all",
            filters=filters,
            last_run=str(row.last_run)[:19] if row.last_run else None,
        )

    @staticmethod
    def _relationship_info(row: FileRelationship) -> FileRelationshipInfo:
        evidence = {}
        if row.evidence_json:
            try:
                evidence = json.loads(row.evidence_json) or {}
            except (json.JSONDecodeError, TypeError):
                evidence = {}
        return FileRelationshipInfo(
            id=row.id,
            source_path=row.source_path,
            target_path=row.target_path,
            relationship_type=row.relationship_type,
            confidence=row.confidence or 1.0,
            reason=evidence.get("reason", ""),
            evidence=evidence,
        )

    @staticmethod
    def _suggestion_info(row: OrganizationSuggestion) -> SuggestionInfo:
        return SuggestionInfo(
            id=row.id,
            file_path=row.file_path,
            suggested_target=row.suggested_target,
            target_type=row.target_type or "collection",
            reason=row.reason or "",
            confidence=row.confidence or 0.0,
            status=row.status or "pending",
        )
