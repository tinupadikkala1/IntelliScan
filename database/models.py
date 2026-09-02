"""Database models for IntelliVault Foundation v1.0.

Eight tables as specified in the blueprint: files, folders, settings,
favorites, recent, tasks, plugins, logs. A ``schema_version`` table records
the applied schema version for future migrations.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import declarative_base

Base = declarative_base()
_now = lambda: datetime.now()


class File(Base):
    __tablename__ = "files"
    id = Column(Integer, primary_key=True)
    path = Column(String, unique=True, index=True)
    name = Column(String)
    parent = Column(String, index=True)
    size = Column(Integer, default=0)
    mime = Column(String)
    modified = Column(DateTime)
    checksum = Column(String)


class Folder(Base):
    __tablename__ = "folders"
    id = Column(Integer, primary_key=True)
    path = Column(String, unique=True, index=True)
    name = Column(String)
    parent = Column(String, index=True)


class Setting(Base):
    __tablename__ = "settings"
    key = Column(String, primary_key=True)
    value = Column(Text)


class Favorite(Base):
    __tablename__ = "favorites"
    id = Column(Integer, primary_key=True)
    path = Column(String, unique=True, index=True)
    name = Column(String)
    added = Column(DateTime, default=_now)


class Recent(Base):
    __tablename__ = "recent"
    id = Column(Integer, primary_key=True)
    path = Column(String, index=True)
    name = Column(String)
    opened = Column(DateTime, default=_now)


class Task(Base):
    __tablename__ = "tasks"
    id = Column(Integer, primary_key=True)
    task_id = Column(String, unique=True, index=True)
    type = Column(String)
    status = Column(String, default="pending")
    progress = Column(Integer, default=0)
    total = Column(Integer, default=0)
    created = Column(DateTime, default=_now)
    finished = Column(DateTime)


class Plugin(Base):
    __tablename__ = "plugins"
    id = Column(Integer, primary_key=True)
    name = Column(String, unique=True, index=True)
    version = Column(String)
    enabled = Column(Boolean, default=True)


class Log(Base):
    __tablename__ = "logs"
    id = Column(Integer, primary_key=True)
    timestamp = Column(DateTime, default=_now)
    level = Column(String)
    logger = Column(String)
    message = Column(Text)


class SchemaVersion(Base):
    __tablename__ = "schema_version"
    version = Column(Integer, primary_key=True)
    applied = Column(DateTime, default=_now)


class AIAnalysis(Base):
    """Stores AI-generated analysis results keyed by file content hash (SHA-256).

    Identity is based on file content (not path/name) so that renames and
    moves preserve existing analysis. If content changes, a new analysis
    is generated.

    Batch 5 extends the row with *normalized* classification/tagging state:
      - normalized_category + classification_version (B5-01)
      - normalized_tags + tagging_version (B5-02)
    The free-form ``category`` / ``tags`` produced by the LLM are preserved;
    the normalized columns are the canonical, searchable values.
    """
    __tablename__ = "ai_analysis"

    id = Column(Integer, primary_key=True)
    file_hash = Column(String(64), unique=True, index=True, nullable=False)
    summary = Column(Text)
    keywords = Column(Text)  # JSON array
    tags = Column(Text)  # JSON array
    category = Column(String)
    language = Column(String)
    ai_generated = Column(Boolean, default=True)
    generated_time = Column(DateTime, default=_now)
    prompt_version = Column(String)
    model_name = Column(String)
    # Batch 5: controlled classification (B5-01)
    normalized_category = Column(String)
    classification_version = Column(String)
    classified_at = Column(DateTime)
    # Batch 5: normalized tags (B5-02)
    normalized_tags = Column(Text)  # JSON array of canonical tags
    tagging_version = Column(String)
    tagged_at = Column(DateTime)
    # Batch 6: image caption (B6-01) — keyed by content hash so renames /
    # moves preserve the caption; regeneration replaces the prior value.
    caption = Column(Text)
    caption_model = Column(String)
    caption_version = Column(String)
    captioned_at = Column(DateTime)
    # Batch 7: image intelligence (B7-2 object detection, B7-4 quality).
    objects_json = Column(Text)      # JSON array [{label, confidence, box}]
    quality_score = Column(Float)    # 0..1 deterministic quality score
    quality_json = Column(Text)      # JSON dict of metric breakdown


# ================================================================
# Batch 3: AI Knowledge & Retrieval Engine tables
# ================================================================

class Evidence(Base):
    """Stores evidence chunks with source provenance for retrieval."""
    __tablename__ = "evidence"

    id = Column(Integer, primary_key=True)
    chunk_id = Column(String(32), unique=True, index=True, nullable=False)
    file_path = Column(String, index=True, nullable=False)
    file_hash = Column(String(64), index=True, nullable=False)
    text = Column(Text, nullable=False)
    source_type = Column(String)  # page, slide, sheet, section
    source_index = Column(Integer)
    source_label = Column(String)
    char_start = Column(Integer)
    char_end = Column(Integer)
    # Batch 3 extension: modality-aware evidence
    modality = Column(String, default="document")
    timestamp_start = Column(Float, default=0.0)
    timestamp_end = Column(Float, default=0.0)
    confidence = Column(Float, default=1.0)
    metadata_json = Column(Text)  # JSON dict (image_index, frame_number, scene_type...)
    indexed_at = Column(DateTime, default=_now)


class VectorMap(Base):
    """Maps chunk_ids to their vector index positions and metadata."""
    __tablename__ = "vector_map"

    id = Column(Integer, primary_key=True)
    chunk_id = Column(String(32), unique=True, index=True, nullable=False)
    file_path = Column(String, index=True, nullable=False)
    file_hash = Column(String(64), index=True, nullable=False)
    embedding_model = Column(String)
    indexed_at = Column(DateTime, default=_now)


class SearchHistory(Base):
    """Records search queries for analytics and recent searches."""
    __tablename__ = "search_history"

    id = Column(Integer, primary_key=True)
    query = Column(Text, nullable=False)
    scope = Column(String)
    results_count = Column(Integer, default=0)
    elapsed_ms = Column(Integer, default=0)
    searched_at = Column(DateTime, default=_now)


# ================================================================
# Batch 4: Conversations, messages and citations
# ================================================================

class Conversation(Base):
    """A persistent chat conversation scoped to a file/folder/workspace."""
    __tablename__ = "conversations"

    id = Column(Integer, primary_key=True)
    title = Column(String, nullable=False, default="New Conversation")
    scope_type = Column(String, default="workspace")  # file | folder | workspace
    scope_path = Column(String, default="")
    created_at = Column(DateTime, default=_now)
    updated_at = Column(DateTime, default=_now, onupdate=_now)
    status = Column(String, default="active")  # active | archived
    model_name = Column(String)
    metadata_json = Column(Text)  # JSON dict


class ConversationMessage(Base):
    """A single message inside a conversation."""
    __tablename__ = "conversation_messages"

    id = Column(Integer, primary_key=True)
    conversation_id = Column(
        Integer, ForeignKey("conversations.id", ondelete="CASCADE"),
        index=True, nullable=False,
    )
    role = Column(String, nullable=False)  # user | assistant | system
    content = Column(Text, nullable=False)
    created_at = Column(DateTime, default=_now)
    sequence_number = Column(Integer, index=True, default=0)
    metadata_json = Column(Text)  # JSON dict (resolved_query, model_name...)


class MessageCitation(Base):
    """A persisted citation linking an assistant message to evidence."""
    __tablename__ = "message_citations"

    id = Column(Integer, primary_key=True)
    message_id = Column(
        Integer, ForeignKey("conversation_messages.id", ondelete="CASCADE"),
        index=True, nullable=False,
    )
    chunk_id = Column(String(32), index=True)
    file_path = Column(String, nullable=False)
    source_label = Column(String)
    source_index = Column(Integer)
    char_start = Column(Integer)
    char_end = Column(Integer)
    timestamp_start = Column(Float, default=0.0)
    timestamp_end = Column(Float, default=0.0)
    citation_order = Column(Integer, default=0)
    metadata_json = Column(Text)  # JSON dict (modality, page, snippet...)


# ================================================================
# Batch 4: Knowledge Graph
# ================================================================

class GraphEntity(Base):
    """A normalized graph node (person, project, technology...)."""
    __tablename__ = "graph_entities"

    id = Column(Integer, primary_key=True)
    canonical_name = Column(String, nullable=False)
    normalized_name = Column(String, index=True, nullable=False)
    entity_type = Column(String, index=True, nullable=False)
    metadata_json = Column(Text)  # JSON dict (aliases, first_seen...)
    created_at = Column(DateTime, default=_now)
    updated_at = Column(DateTime, default=_now, onupdate=_now)


class GraphRelationship(Base):
    """A directed, evidence-backed relationship between two entities."""
    __tablename__ = "graph_relationships"

    id = Column(Integer, primary_key=True)
    source_entity_id = Column(
        Integer, ForeignKey("graph_entities.id", ondelete="CASCADE"),
        index=True, nullable=False,
    )
    target_entity_id = Column(
        Integer, ForeignKey("graph_entities.id", ondelete="CASCADE"),
        index=True, nullable=False,
    )
    relationship_type = Column(String, nullable=False)
    confidence = Column(Float, default=1.0)
    metadata_json = Column(Text)
    created_at = Column(DateTime, default=_now)


class GraphEvidenceLink(Base):
    """Binds a relationship (or entity) to the evidence that supports it."""
    __tablename__ = "graph_evidence_links"

    id = Column(Integer, primary_key=True)
    relationship_id = Column(
        Integer, ForeignKey("graph_relationships.id", ondelete="CASCADE"),
        index=True, nullable=False,
    )
    chunk_id = Column(String(32), index=True)
    file_path = Column(String, index=True, nullable=False)
    source_label = Column(String)
    source_index = Column(Integer)
    char_start = Column(Integer)
    char_end = Column(Integer)
    metadata_json = Column(Text)


# ================================================================
# Batch 5: Intelligent Organization & Knowledge Management
# ================================================================

class Collection(Base):
    """A virtual collection of files (static or smart) — B5-03.

    Smart collections derive membership from ``criteria_json`` (category /
    tag / semantic-query rules); static collections hold explicit members.
    Files are never moved or copied.
    """
    __tablename__ = "collections"

    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    description = Column(Text, default="")
    criteria_json = Column(Text)  # JSON for smart collections
    is_smart = Column(Boolean, default=False)
    created_at = Column(DateTime, default=_now)
    updated_at = Column(DateTime, default=_now, onupdate=_now)


class CollectionItem(Base):
    """A file member of a collection — B5-03."""
    __tablename__ = "collection_items"

    id = Column(Integer, primary_key=True)
    collection_id = Column(
        Integer, ForeignKey("collections.id", ondelete="CASCADE"),
        index=True, nullable=False,
    )
    file_path = Column(String, index=True, nullable=False)
    added_at = Column(DateTime, default=_now)
    source = Column(String, default="manual")  # manual | criteria | suggestion


class SavedSearch(Base):
    """A persisted, re-runnable semantic search — B5-09.

    Re-running always queries the *current* FAISS/evidence state; saved
    result lists are never stored as the source of truth.
    """
    __tablename__ = "saved_searches"

    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    query = Column(Text, nullable=False)
    scope = Column(String, default="workspace")  # workspace | folder | file
    scope_path = Column(String, default="")
    modality = Column(String, default="all")  # all | document | image | audio | video
    filters_json = Column(Text)  # JSON dict
    created_at = Column(DateTime, default=_now)
    updated_at = Column(DateTime, default=_now, onupdate=_now)
    last_run = Column(DateTime)


class FileRelationship(Base):
    """A directed FILE → FILE relationship — B5-07.

    The Batch-4 knowledge graph remains ENTITY → ENTITY; this table is the
    separate file-level relationship layer. Controlled types:
    related_to | duplicate_of | similar_to | references | derived_from |
    belongs_to_project
    """
    __tablename__ = "file_relationships"

    id = Column(Integer, primary_key=True)
    source_path = Column(String, index=True, nullable=False)
    target_path = Column(String, index=True, nullable=False)
    relationship_type = Column(String, nullable=False)
    confidence = Column(Float, default=1.0)
    evidence_json = Column(Text)  # JSON dict (reason, matched_chunks, sources...)
    created_at = Column(DateTime, default=_now)
    updated_at = Column(DateTime, default=_now, onupdate=_now)


class OrganizationSuggestion(Base):
    """A persisted AI organization suggestion — B5-08 / B6-05.

    Suggestions are advisory only: accepting a *collection* suggestion updates
    the virtual organization layer (collection membership); accepting a
    *folder* suggestion (target_type='folder') runs the approved, previewed
    move workflow (B6-05) which is user-confirmed before any file moves.
    Status: pending | accepted | dismissed | expired.
    """
    __tablename__ = "organization_suggestions"

    id = Column(Integer, primary_key=True)
    file_path = Column(String, index=True, nullable=False)
    suggested_target = Column(String, nullable=False)  # collection name / folder
    target_type = Column(String, default="collection")  # collection | folder
    reason = Column(Text, default="")
    confidence = Column(Float, default=0.0)
    status = Column(String, default="pending")
    created_at = Column(DateTime, default=_now)
    updated_at = Column(DateTime, default=_now, onupdate=_now)


class FolderClassification(Base):
    """Aggregated category composition of a folder — B6-02.

    Derived entirely from existing per-file classifications (never re-runs the
    LLM per file). Refreshed on demand / when files change; ``folder_path`` is
    the canonical key.
    """
    __tablename__ = "folder_classifications"

    id = Column(Integer, primary_key=True)
    folder_path = Column(String, unique=True, index=True, nullable=False)
    dominant_category = Column(String, nullable=False)
    distribution_json = Column(Text)  # JSON dict category -> file count
    classified_count = Column(Integer, default=0)
    unclassified_count = Column(Integer, default=0)
    classification_version = Column(String)
    generated_at = Column(DateTime, default=_now)
    updated_at = Column(DateTime, default=_now, onupdate=_now)
    # Batch 7: AI-powered folder summary (B7-8) — persisted LLM summary.
    summary = Column(Text)
    summary_model = Column(String)
    summary_version = Column(String)
    summarized_at = Column(DateTime)


class DuplicateSuggestion(Base):
    """A persisted safe-removal recommendation for a duplicate group — B6-04.

    Advisory only: nothing is deleted unless the user approves, at which point
    the file is moved to the reversible app trash (never permanently removed)
    and the index is synchronized.
    Status: pending | accepted | dismissed | executed.
    """
    __tablename__ = "duplicate_suggestions"

    id = Column(Integer, primary_key=True)
    group_checksum = Column(String(64), index=True, nullable=False)
    keep_path = Column(String, nullable=False)
    remove_path = Column(String, index=True, nullable=False)
    duplicate_type = Column(String, default="exact")  # exact | near
    confidence = Column(Float, default=0.0)
    reason = Column(Text, default="")
    evidence_json = Column(Text)  # JSON dict (similarity, checksum, markers...)
    status = Column(String, default="pending")
    created_at = Column(DateTime, default=_now)
    updated_at = Column(DateTime, default=_now, onupdate=_now)
