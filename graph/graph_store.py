"""Graph store — SQLite persistence for graph entities, relationships and
evidence links.

Normalized names prevent duplicate nodes; relationships are deduplicated by
(source, relation, target); deletion cascades per file.
"""

from __future__ import annotations

import json
import logging
from typing import List, Optional

from database.models import GraphEntity, GraphEvidenceLink, GraphRelationship

from .graph_models import EntityDetail, EntityRecord, RelationshipRecord, normalize_entity_name

logger = logging.getLogger(__name__)


class GraphPersistenceError(Exception):
    """Raised when a graph write cannot be completed."""


class GraphStore:
    """Persistence for the knowledge graph."""

    def __init__(self, session_factory) -> None:
        self._session_factory = session_factory

    # ------------------------------------------------------------------ #
    # Entities
    # ------------------------------------------------------------------ #
    def upsert_entity(self, record: EntityRecord) -> int:
        """Create or merge an entity by normalized name; return its id."""
        normalized = record.normalized_name
        if not normalized:
            raise GraphPersistenceError("Entity name is empty after normalization")
        try:
            with self._session_factory() as session:
                existing = (
                    session.query(GraphEntity)
                    .filter(GraphEntity.normalized_name == normalized)
                    .first()
                )
                if existing is not None:
                    if record.name != existing.canonical_name:
                        aliases = self._aliases(existing) | {record.name}
                        existing.metadata_json = json.dumps({"aliases": sorted(aliases)})
                    session.commit()
                    return existing.id
                entity = GraphEntity(
                    canonical_name=record.name,
                    normalized_name=normalized,
                    entity_type=record.entity_type,
                    metadata_json=json.dumps({"aliases": sorted(set(record.aliases))}),
                )
                session.add(entity)
                session.commit()
                return entity.id
        except GraphPersistenceError:
            raise
        except Exception as e:
            logger.error("Failed to upsert entity: %s", e)
            raise GraphPersistenceError(f"Could not upsert entity '{record.name}': {e}") from e

    def get_entity_by_id(self, entity_id: int) -> Optional[GraphEntity]:
        try:
            with self._session_factory() as session:
                return session.get(GraphEntity, entity_id)
        except Exception:
            return None

    def get_entity_by_name(self, name: str) -> Optional[GraphEntity]:
        normalized = normalize_entity_name(name)
        try:
            with self._session_factory() as session:
                return (
                    session.query(GraphEntity)
                    .filter(GraphEntity.normalized_name == normalized)
                    .first()
                )
        except Exception:
            return None

    def search_entities(self, query: str, limit: int = 50) -> List[dict]:
        """Search entities by name fragment (canonical or normalized)."""
        q = f"%{query.strip()}%"
        try:
            with self._session_factory() as session:
                rows = (
                    session.query(GraphEntity)
                    .filter(
                        (GraphEntity.canonical_name.like(q))
                        | (GraphEntity.normalized_name.like(q.lower()))
                    )
                    .order_by(GraphEntity.canonical_name)
                    .limit(limit)
                    .all()
                )
                return [
                    {
                        "id": r.id,
                        "name": r.canonical_name,
                        "type": r.entity_type,
                    }
                    for r in rows
                ]
        except Exception:
            return []

    # ------------------------------------------------------------------ #
    # Relationships
    # ------------------------------------------------------------------ #
    def add_relationship(self, rel: RelationshipRecord, source_id: int, target_id: int) -> int:
        """Create a relationship (deduped) and attach its evidence link."""
        if rel.confidence < 0.0 or rel.confidence > 1.0:
            rel.confidence = 1.0
        try:
            with self._session_factory() as session:
                existing = (
                    session.query(GraphRelationship)
                    .filter(
                        GraphRelationship.source_entity_id == source_id,
                        GraphRelationship.target_entity_id == target_id,
                        GraphRelationship.relationship_type == rel.relation,
                    )
                    .first()
                )
                if existing is not None:
                    if rel.confidence > (existing.confidence or 0.0):
                        existing.confidence = rel.confidence
                    rel_id = existing.id
                else:
                    row = GraphRelationship(
                        source_entity_id=source_id,
                        target_entity_id=target_id,
                        relationship_type=rel.relation,
                        confidence=rel.confidence,
                    )
                    session.add(row)
                    session.flush()
                    rel_id = row.id

                if rel.chunk_id or rel.file_path:
                    session.add(GraphEvidenceLink(
                        relationship_id=rel_id,
                        chunk_id=rel.chunk_id,
                        file_path=rel.file_path,
                        source_label=rel.source_label,
                        source_index=rel.source_index,
                        metadata_json=json.dumps({"confidence": rel.confidence}),
                    ))
                session.commit()
                return rel_id
        except Exception as e:
            logger.error("Failed to add relationship: %s", e)
            raise GraphPersistenceError(
                f"Could not add relationship '{rel.source} -{rel.relation}-> {rel.target}': {e}"
            ) from e

    def get_relationships(self, entity_id: int) -> List[dict]:
        """Return relationships (in and out) for an entity with names."""
        try:
            with self._session_factory() as session:
                rows = (
                    session.query(GraphRelationship)
                    .filter(
                        (GraphRelationship.source_entity_id == entity_id)
                        | (GraphRelationship.target_entity_id == entity_id)
                    )
                    .all()
                )
                out = []
                for r in rows:
                    src = session.get(GraphEntity, r.source_entity_id)
                    tgt = session.get(GraphEntity, r.target_entity_id)
                    out.append({
                        "id": r.id,
                        "source": src.canonical_name if src else "?",
                        "target": tgt.canonical_name if tgt else "?",
                        "relation": r.relationship_type,
                        "confidence": r.confidence,
                        "direction": "out" if r.source_entity_id == entity_id else "in",
                    })
                return out
        except Exception:
            return []

    def get_evidence_links(self, relationship_id: int, limit: int = 20) -> List[dict]:
        try:
            with self._session_factory() as session:
                rows = (
                    session.query(GraphEvidenceLink)
                    .filter(GraphEvidenceLink.relationship_id == relationship_id)
                    .limit(limit)
                    .all()
                )
                return [
                    {
                        "chunk_id": r.chunk_id,
                        "file_path": r.file_path,
                        "source_label": r.source_label,
                        "source_index": r.source_index,
                    }
                    for r in rows
                ]
        except Exception:
            return []

    def related_files(self, entity_id: int) -> List[str]:
        """Distinct file paths connected to an entity via any relationship."""
        try:
            with self._session_factory() as session:
                rel_ids = [
                    r.id
                    for r in session.query(GraphRelationship).filter(
                        (GraphRelationship.source_entity_id == entity_id)
                        | (GraphRelationship.target_entity_id == entity_id)
                    )
                ]
                if not rel_ids:
                    return []
                rows = (
                    session.query(GraphEvidenceLink.file_path)
                    .filter(GraphEvidenceLink.relationship_id.in_(rel_ids))
                    .distinct()
                    .all()
                )
                return [r[0] for r in rows]
        except Exception:
            return []

    def files_sharing_entities(self, file_path: str, limit: int = 50) -> List[str]:
        """Distinct files that share at least one entity with ``file_path``.

        Used by B5-06 (related-file discovery via the knowledge graph).
        Files connected to the same entity (through any relationship) are
        considered semantically related; the source file is excluded.
        """
        try:
            with self._session_factory() as session:
                # Entities evidenced in the source file.
                entity_ids = [
                    e.id
                    for e in session.query(GraphEntity).all()
                    if (
                        session.query(GraphEvidenceLink)
                        .filter(
                            GraphEvidenceLink.file_path == file_path,
                            GraphEvidenceLink.relationship_id.in_(
                                session.query(GraphRelationship.id)
                                .filter(
                                    (GraphRelationship.source_entity_id == e.id)
                                    | (GraphRelationship.target_entity_id == e.id)
                                )
                            ),
                        )
                        .count()
                        > 0
                    )
                ]
                if not entity_ids:
                    return []
                # All relationships touching those entities.
                rel_ids = [
                    r.id
                    for r in session.query(GraphRelationship).filter(
                        (GraphRelationship.source_entity_id.in_(entity_ids))
                        | (GraphRelationship.target_entity_id.in_(entity_ids))
                    )
                ]
                if not rel_ids:
                    return []
                rows = (
                    session.query(GraphEvidenceLink.file_path)
                    .filter(
                        GraphEvidenceLink.relationship_id.in_(rel_ids),
                        GraphEvidenceLink.file_path != file_path,
                    )
                    .distinct()
                    .limit(limit)
                    .all()
                )
                return [r[0] for r in rows]
        except Exception:
            return []

    # ------------------------------------------------------------------ #
    # Deletion
    # ------------------------------------------------------------------ #
    def remove_file(self, file_path: str) -> int:
        """Remove a file's evidence links, orphaned relationships and entities.

        Returns the number of evidence links removed.
        """
        try:
            with self._session_factory() as session:
                links = (
                    session.query(GraphEvidenceLink)
                    .filter(GraphEvidenceLink.file_path == file_path)
                    .all()
                )
                removed = len(links)
                rel_ids = {l.relationship_id for l in links}
                for l in links:
                    session.delete(l)
                session.flush()

                # Relationships that lost all evidence are removed.
                for rel_id in list(rel_ids):
                    remaining = (
                        session.query(GraphEvidenceLink)
                        .filter(GraphEvidenceLink.relationship_id == rel_id)
                        .count()
                    )
                    if remaining == 0:
                        rel = session.get(GraphRelationship, rel_id)
                        if rel is not None:
                            session.delete(rel)

                session.flush()
                # Entities that now have no relationships are removed (safe).
                entity_ids = [
                    e.id
                    for e in session.query(GraphEntity).all()
                    if (
                        session.query(GraphRelationship)
                        .filter(
                            (GraphRelationship.source_entity_id == e.id)
                            | (GraphRelationship.target_entity_id == e.id)
                        )
                        .count()
                        == 0
                    )
                ]
                for eid in entity_ids:
                    e = session.get(GraphEntity, eid)
                    if e is not None:
                        session.delete(e)

                session.commit()
                logger.info("Graph: removed %d evidence links for %s", removed, file_path)
                return removed
        except Exception as e:
            logger.error("Failed to remove graph data for %s: %s", file_path, e)
            raise GraphPersistenceError(f"Could not remove graph data for {file_path}: {e}") from e

    def stats(self) -> dict:
        try:
            with self._session_factory() as session:
                return {
                    "entities": session.query(GraphEntity).count(),
                    "relationships": session.query(GraphRelationship).count(),
                    "evidence_links": session.query(GraphEvidenceLink).count(),
                }
        except Exception:
            return {"entities": 0, "relationships": 0, "evidence_links": 0}

    @staticmethod
    def _aliases(entity: GraphEntity) -> set:
        try:
            meta = json.loads(entity.metadata_json or "{}") or {}
            return set(meta.get("aliases", []))
        except (json.JSONDecodeError, TypeError):
            return set()
