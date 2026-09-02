"""Agent tool registry (Batch 4 §35).

All tools are read-only and return plain dicts (JSON-serializable) so the
planner can consume observations. Handlers are wired to the retrieval, RAG,
graph and index services; nothing here touches the filesystem beyond reads.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, List

from engines.retrieval_engine import RetrievalScope

from .schemas import ToolInput, ToolSpec

logger = logging.getLogger(__name__)


def _scope(value: str) -> RetrievalScope:
    if value == "folder":
        return RetrievalScope.FOLDER
    if value == "file":
        return RetrievalScope.SELECTED_FILE
    return RetrievalScope.WORKSPACE


class ToolRegistry:
    """Registry of validated tools with engine-backed handlers."""

    def __init__(self, retrieval=None, rag=None, db_store=None,
                 graph_query=None, indexer=None) -> None:
        self._retrieval = retrieval
        self._rag = rag
        self._db_store = db_store
        self._graph_query = graph_query
        self._indexer = indexer
        self._tools: Dict[str, ToolSpec] = {}
        self._register_all()

    # ------------------------------------------------------------------ #
    def register(self, spec: ToolSpec) -> None:
        self._tools[spec.name] = spec

    def get(self, name: str) -> ToolSpec:
        return self._tools[name]

    def names(self) -> List[str]:
        return sorted(self._tools)

    def specs(self) -> List[dict]:
        return [
            {
                "name": s.name,
                "description": s.description,
                "parameters": s.parameters,
                "policy": s.policy,
                "timeout_seconds": s.timeout_seconds,
            }
            for s in self._tools.values()
        ]

    # ------------------------------------------------------------------ #
    def _register_all(self) -> None:
        self.register(ToolSpec(
            name="search",
            description="Semantic search over the workspace or a folder. Returns ranked "
                        "evidence chunks with file paths, scores and source labels.",
            parameters={
                "query": {"type": "string", "required": True, "description": "Search query"},
                "limit": {"type": "integer", "required": False, "default": 5},
                "scope": {"type": "string", "required": False, "default": "workspace",
                          "enum": ["workspace", "folder"]},
            },
            handler=self._handle_search,
            timeout_seconds=45.0,
        ))
        self.register(ToolSpec(
            name="retrieve_evidence",
            description="Retrieve all stored evidence chunks for a specific file path.",
            parameters={
                "file_path": {"type": "string", "required": True, "description": "Absolute file path"},
                "limit": {"type": "integer", "required": False, "default": 10},
            },
            handler=self._handle_retrieve_evidence,
            timeout_seconds=30.0,
        ))
        self.register(ToolSpec(
            name="list_related_files",
            description="List files that are semantically related to a query.",
            parameters={
                "query": {"type": "string", "required": True, "description": "Topic or entity"},
                "limit": {"type": "integer", "required": False, "default": 8},
            },
            handler=self._handle_related_files,
            timeout_seconds=45.0,
        ))
        self.register(ToolSpec(
            name="get_file_metadata",
            description="Get stored metadata (size, modified, indexed info) for a file path.",
            parameters={
                "file_path": {"type": "string", "required": True, "description": "Absolute file path"},
            },
            handler=self._handle_file_metadata,
            timeout_seconds=15.0,
        ))
        self.register(ToolSpec(
            name="query_knowledge_graph",
            description="Search the knowledge graph for an entity and return its type, "
                        "relationships and related files.",
            parameters={
                "entity_name": {"type": "string", "required": True, "description": "Entity name"},
            },
            handler=self._handle_graph_query,
            timeout_seconds=30.0,
        ))
        self.register(ToolSpec(
            name="open_evidence",
            description="Resolve an evidence location (file + source label/index) for navigation. "
                        "Read-only: returns the location, does not modify anything.",
            parameters={
                "file_path": {"type": "string", "required": True, "description": "Absolute file path"},
                "source_label": {"type": "string", "required": False, "default": ""},
                "source_index": {"type": "integer", "required": False, "default": 0},
            },
            handler=self._handle_open_evidence,
            timeout_seconds=15.0,
        ))
        self.register(ToolSpec(
            name="summarize_evidence",
            description="Summarize the stored evidence for a file or the top results for a query.",
            parameters={
                "query": {"type": "string", "required": False, "default": "",
                          "description": "Optional query to focus the summary"},
                "file_path": {"type": "string", "required": False, "default": "",
                              "description": "Optional file path to summarize"},
                "limit": {"type": "integer", "required": False, "default": 5},
            },
            handler=self._handle_summarize,
            timeout_seconds=90.0,
        ))
        self.register(ToolSpec(
            name="compare_documents",
            description="Compare two indexed files and describe how they relate to a question.",
            parameters={
                "query": {"type": "string", "required": True, "description": "Comparison focus"},
                "file_a": {"type": "string", "required": True, "description": "First absolute file path"},
                "file_b": {"type": "string", "required": True, "description": "Second absolute file path"},
            },
            handler=self._handle_compare,
            timeout_seconds=90.0,
        ))

    # ------------------------------------------------------------------ #
    # Handlers
    # ------------------------------------------------------------------ #
    def _handle_search(self, inp: ToolInput) -> dict:
        if self._retrieval is None:
            return {"error": "retrieval unavailable"}
        response = self._retrieval.retrieve(
            query=inp.query,
            scope=_scope(inp.scope or "workspace"),
            top_k=inp.limit,
        )
        return {
            "query": inp.query,
            "total": len(response.results),
            "results": [
                {
                    "file_path": r.file_path,
                    "score": round(r.score, 4),
                    "source_label": r.source_label,
                    "modality": r.modality,
                    "snippet": (r.text or "")[:300],
                }
                for r in response.results
            ],
        }

    def _handle_retrieve_evidence(self, inp: ToolInput) -> dict:
        if self._db_store is None:
            return {"error": "db_store unavailable"}
        if not os.path.exists(inp.file_path):
            return {"error": f"file does not exist: {inp.file_path}"}
        chunks = self._db_store.get_evidence_by_file(inp.file_path)
        return {
            "file_path": inp.file_path,
            "total": len(chunks),
            "chunks": [
                {
                    "chunk_id": c.chunk_id,
                    "source_label": c.source_label,
                    "text": (c.text or "")[:300],
                }
                for c in chunks[: inp.limit]
            ],
        }

    def _handle_related_files(self, inp: ToolInput) -> dict:
        if self._retrieval is None:
            return {"error": "retrieval unavailable"}
        response = self._retrieval.retrieve(
            query=inp.query,
            scope=RetrievalScope.WORKSPACE,
            top_k=inp.limit * 2,
        )
        seen: Dict[str, dict] = {}
        for r in response.results:
            if r.file_path not in seen:
                seen[r.file_path] = {
                    "file_path": r.file_path,
                    "best_score": round(r.score, 4),
                    "source_label": r.source_label,
                }
            if len(seen) >= inp.limit:
                break
        return {"query": inp.query, "files": list(seen.values())}

    def _handle_file_metadata(self, inp: ToolInput) -> dict:
        if self._indexer is None:
            return {"error": "indexer unavailable"}
        record = self._indexer.get_by_path(inp.file_path)
        if record is None:
            return {"error": f"not indexed: {inp.file_path}"}
        return {k: record.get(k) for k in ("filename", "absolute_path", "file_type",
                                            "file_size", "modified", "status", "hash") if k in record}

    def _handle_graph_query(self, inp: ToolInput) -> dict:
        if self._graph_query is None:
            return {"error": "graph unavailable"}
        matches = self._graph_query.search_entities(inp.entity_name, limit=5)
        if not matches:
            return {"query": inp.entity_name, "entities": []}
        detail = self._graph_query.entity_details(matches[0]["id"])
        if detail is None:
            return {"query": inp.entity_name, "entities": []}
        return {
            "entity": detail.name,
            "type": detail.entity_type,
            "aliases": detail.aliases,
            "relationship_count": detail.relationship_count,
            "related_files": detail.related_files[:8],
            "relationships": [
                {"source": r["source"], "relation": r["relation"], "target": r["target"],
                 "confidence": r["confidence"]}
                for r in detail.relationships
            ],
        }

    def _handle_open_evidence(self, inp: ToolInput) -> dict:
        if not os.path.exists(inp.file_path):
            return {"error": f"file does not exist: {inp.file_path}"}
        return {
            "file_path": inp.file_path,
            "source_label": inp.source_label or "",
            "source_index": inp.source_index,
            "action": "open_in_viewer",
        }

    def _handle_summarize(self, inp: ToolInput) -> dict:
        if self._rag is None:
            return {"error": "rag unavailable"}
        if inp.file_path and os.path.exists(inp.file_path):
            response = self._rag.ask_file_direct(inp.query or "Summarize this file's key points.", inp.file_path)
        elif inp.query:
            response = self._rag.ask(inp.query, top_k=inp.limit)
        else:
            return {"error": "provide query or file_path"}
        return {"answer": response.answer, "grounded": response.grounded,
                "citations": len(response.citations)}

    def _handle_compare(self, inp: ToolInput) -> dict:
        if self._rag is None:
            return {"error": "rag unavailable"}
        response = self._rag.ask(
            inp.query,
            scope=RetrievalScope.SELECTED_FILES,
            file_filter=[inp.file_a, inp.file_b],
            top_k=10,
        )
        return {
            "answer": response.answer,
            "grounded": response.grounded,
            "files": [inp.file_a, inp.file_b],
            "citations": len(response.citations),
        }
