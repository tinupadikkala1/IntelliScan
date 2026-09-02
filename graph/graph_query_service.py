"""Graph query service — read-side API for the Knowledge Graph UI and the
agent's ``query_knowledge_graph`` tool.

No graph query language (Batch 4 §34): search + expand + evidence lookups.
"""

from __future__ import annotations

import logging
from typing import List, Optional

from .graph_models import EntityDetail
from .graph_store import GraphStore

logger = logging.getLogger(__name__)


class GraphQueryService:
    """Read-only queries over the graph store."""

    def __init__(self, store: GraphStore) -> None:
        self._store = store

    def search_entities(self, query: str, limit: int = 50) -> List[dict]:
        return self._store.search_entities(query, limit=limit)

    def entity_details(self, entity_id: int) -> Optional[EntityDetail]:
        entity = self._store.get_entity_by_id(entity_id)
        if entity is None:
            return None
        aliases = []
        try:
            import json
            meta = json.loads(entity.metadata_json or "{}") or {}
            aliases = meta.get("aliases", []) or []
        except Exception:
            aliases = []
        relationships = self._store.get_relationships(entity.id)
        related_files = self._store.related_files(entity.id)
        return EntityDetail(
            id=entity.id,
            name=entity.canonical_name,
            entity_type=entity.entity_type,
            aliases=aliases,
            relationship_count=len(relationships),
            related_files=related_files,
            relationships=relationships,
        )

    def relationships_with_evidence(self, entity_id: int) -> List[dict]:
        """Relationships enriched with their evidence links."""
        out = []
        for rel in self._store.get_relationships(entity_id):
            evidence = self._store.get_evidence_links(rel["id"])
            out.append({**rel, "evidence": evidence})
        return out

    def neighbors(self, entity_id: int) -> List[dict]:
        """Connected entities (name + relation) for graph exploration."""
        result = []
        for rel in self._store.get_relationships(entity_id):
            if rel["direction"] == "out":
                result.append({"name": rel["target"], "relation": rel["relation"], "relationship_id": rel["id"]})
            else:
                result.append({"name": rel["source"], "relation": rel["relation"], "relationship_id": rel["id"]})
        return result

    def stats(self) -> dict:
        return self._store.stats()
