"""Service-layer dataclasses for Batch 5 (independent of ORM rows).

Mirrors the Batch-4 pattern (conversation/models.py, graph/graph_models.py):
engines return plain dataclasses so UI and tests never touch SQLAlchemy rows
directly.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class DuplicateGroup:
    """A group of files sharing identical content (B5-04)."""

    checksum: str
    files: List[str] = field(default_factory=list)
    total_size: int = 0
    is_empty: bool = False

    def to_dict(self) -> dict:
        return {
            "checksum": self.checksum,
            "files": self.files,
            "total_size": self.total_size,
            "is_empty": self.is_empty,
            "total_copies": len(self.files),
        }


@dataclass
class SimilarFileResult:
    """A file-level similarity hit (B5-05)."""

    file_path: str
    score: float
    matched_chunks: int = 0
    reason: str = ""
    is_exact: bool = False  # same checksum → also an exact duplicate

    def to_dict(self) -> dict:
        return {
            "file_path": self.file_path,
            "score": self.score,
            "matched_chunks": self.matched_chunks,
            "reason": self.reason,
            "is_exact": self.is_exact,
        }


@dataclass
class RelatedFileResult:
    """A related-file discovery hit (B5-06)."""

    file_path: str
    score: float
    reason: str = ""
    source: str = "similarity"  # similarity | semantic | graph | metadata

    def to_dict(self) -> dict:
        return {
            "file_path": self.file_path,
            "score": self.score,
            "reason": self.reason,
            "source": self.source,
        }


@dataclass
class FileRelationshipInfo:
    """A persisted FILE → FILE relationship edge (B5-07)."""

    id: int
    source_path: str
    target_path: str
    relationship_type: str
    confidence: float = 1.0
    reason: str = ""
    evidence: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "source_path": self.source_path,
            "target_path": self.target_path,
            "relationship_type": self.relationship_type,
            "confidence": self.confidence,
            "reason": self.reason,
            "evidence": self.evidence,
        }


@dataclass
class SuggestionInfo:
    """An organization suggestion (B5-08)."""

    id: int
    file_path: str
    suggested_target: str
    target_type: str = "collection"
    reason: str = ""
    confidence: float = 0.0
    status: str = "pending"

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "file_path": self.file_path,
            "suggested_target": self.suggested_target,
            "target_type": self.target_type,
            "reason": self.reason,
            "confidence": self.confidence,
            "status": self.status,
        }


@dataclass
class SavedSearchInfo:
    """A persisted saved semantic search (B5-09)."""

    id: int
    name: str
    query: str
    scope: str = "workspace"
    scope_path: str = ""
    modality: str = "all"
    filters: dict = field(default_factory=dict)
    last_run: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "query": self.query,
            "scope": self.scope,
            "scope_path": self.scope_path,
            "modality": self.modality,
            "filters": self.filters,
            "last_run": self.last_run,
        }


@dataclass
class CollectionInfo:
    """A virtual collection (B5-03)."""

    id: int
    name: str
    description: str = ""
    is_smart: bool = False
    criteria: dict = field(default_factory=dict)
    member_count: int = 0

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "is_smart": self.is_smart,
            "criteria": self.criteria,
            "member_count": self.member_count,
        }


@dataclass
class DuplicateRemovalSuggestion:
    """A safe removal recommendation for one copy of a duplicate group (B6-04)."""

    id: int
    group_checksum: str
    keep_path: str
    remove_path: str
    duplicate_type: str = "exact"  # exact | near
    confidence: float = 0.0
    reason: str = ""
    evidence: dict = field(default_factory=dict)
    status: str = "pending"  # pending | accepted | dismissed | executed

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "group_checksum": self.group_checksum,
            "keep_path": self.keep_path,
            "remove_path": self.remove_path,
            "duplicate_type": self.duplicate_type,
            "confidence": self.confidence,
            "reason": self.reason,
            "evidence": self.evidence,
            "status": self.status,
        }
