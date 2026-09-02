"""Database migration system with FTS5 and vector schema support."""

from __future__ import annotations

import logging
from typing import Any, Callable

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker

from database.models import Base, SchemaVersion

# Import models that use the shared Base so they are registered
# before create_all() is called.
from services.sqlite_indexer import IndexedFile  # noqa: F401

log = logging.getLogger(__name__)

MigrationFn = Callable[[Any], None]


def get_current_version(engine) -> int:
    inspector = inspect(engine)
    if not inspector.has_table("schema_version"):
        return 0
    Session = sessionmaker(bind=engine, future=True)
    with Session() as session:
        row = session.execute(
            text("SELECT version FROM schema_version ORDER BY version DESC LIMIT 1")
        ).first()
        return row[0] if row else 0


def set_version(engine, version: int) -> None:
    Session = sessionmaker(bind=engine, future=True)
    with Session() as session:
        session.execute(text("DELETE FROM schema_version"))
        session.add(SchemaVersion(version=version))
        session.commit()


def add_fts5_index(engine) -> None:
    """Create FTS5 virtual table for full-text search on file content."""
    log.info("Applying migration 2: FTS5 index")
    with engine.connect() as conn:
        # FTS5 virtual table for file content search
        conn.execute(text("""
            CREATE VIRTUAL TABLE IF NOT EXISTS file_content_fts USING fts5(
                path,
                name,
                content,
                tokenize='porter unicode61'
            )
        """))
        # Trigger to keep FTS in sync with files table
        conn.execute(text("""
            CREATE TRIGGER IF NOT EXISTS file_content_fts_insert
            AFTER INSERT ON files
            BEGIN
                INSERT INTO file_content_fts (path, name, content)
                VALUES (new.path, new.name, '');
            END
        """))
        conn.execute(text("""
            CREATE TRIGGER IF NOT EXISTS file_content_fts_update
            AFTER UPDATE ON files
            BEGIN
                UPDATE file_content_fts
                SET path = new.path, name = new.name
                WHERE path = old.path;
            END
        """))
        conn.execute(text("""
            CREATE TRIGGER IF NOT EXISTS file_content_fts_delete
            AFTER DELETE ON files
            BEGIN
                DELETE FROM file_content_fts WHERE path = old.path;
            END
        """))
        conn.commit()


def add_embedding_table(engine) -> None:
    """Create embeddings table for vector storage."""
    log.info("Applying migration 3: Embedding table")
    with engine.connect() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS embeddings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                file_id INTEGER NOT NULL,
                model TEXT NOT NULL,
                vector BLOB NOT NULL,
                created TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (file_id) REFERENCES files(id) ON DELETE CASCADE
            )
        """))
        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_embeddings_file_model
            ON embeddings (file_id, model)
        """))
        conn.commit()


def add_evidence_modality_columns(engine) -> None:
    """Add modality-aware columns to the evidence table (Batch 3).

    SQLite supports ALTER TABLE ADD COLUMN; each addition is guarded so the
    migration is idempotent for databases at various states.
    """
    log.info("Applying migration 6: evidence modality columns")
    column_defs = [
        ("modality", "VARCHAR(16) DEFAULT 'document'"),
        ("timestamp_start", "FLOAT DEFAULT 0.0"),
        ("timestamp_end", "FLOAT DEFAULT 0.0"),
        ("confidence", "FLOAT DEFAULT 1.0"),
        ("metadata_json", "TEXT"),
    ]
    with engine.connect() as conn:
        existing = {
            row[1] for row in conn.execute(text("PRAGMA table_info(evidence)"))
        }
        for col, coltype in column_defs:
            if col in existing:
                continue
            try:
                conn.execute(
                    text(f"ALTER TABLE evidence ADD COLUMN {col} {coltype}")
                )
            except Exception as exc:  # pragma: no cover - defensive
                log.warning("Could not add evidence column %s: %s", col, exc)
        conn.commit()


def add_batch4_tables(engine) -> None:
    """Create Batch 4 conversation + knowledge graph tables.

    Idempotent: models are also created by ``create_all``; this migration
    adds the supporting indexes and records the schema version.
    """
    log.info("Applying migration 7: Batch 4 conversation + graph tables")
    statements = [
        """CREATE TABLE IF NOT EXISTS conversations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title VARCHAR NOT NULL DEFAULT 'New Conversation',
            scope_type VARCHAR DEFAULT 'workspace',
            scope_path VARCHAR DEFAULT '',
            created_at DATETIME,
            updated_at DATETIME,
            status VARCHAR DEFAULT 'active',
            model_name VARCHAR,
            metadata_json TEXT
        )""",
        """CREATE TABLE IF NOT EXISTS conversation_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            conversation_id INTEGER NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
            role VARCHAR NOT NULL,
            content TEXT NOT NULL,
            created_at DATETIME,
            sequence_number INTEGER DEFAULT 0,
            metadata_json TEXT
        )""",
        """CREATE TABLE IF NOT EXISTS message_citations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            message_id INTEGER NOT NULL REFERENCES conversation_messages(id) ON DELETE CASCADE,
            chunk_id VARCHAR(32),
            file_path VARCHAR NOT NULL,
            source_label VARCHAR,
            source_index INTEGER,
            char_start INTEGER,
            char_end INTEGER,
            timestamp_start FLOAT DEFAULT 0.0,
            timestamp_end FLOAT DEFAULT 0.0,
            citation_order INTEGER DEFAULT 0,
            metadata_json TEXT
        )""",
        """CREATE TABLE IF NOT EXISTS graph_entities (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            canonical_name VARCHAR NOT NULL,
            normalized_name VARCHAR NOT NULL,
            entity_type VARCHAR NOT NULL,
            metadata_json TEXT,
            created_at DATETIME,
            updated_at DATETIME
        )""",
        """CREATE TABLE IF NOT EXISTS graph_relationships (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_entity_id INTEGER NOT NULL REFERENCES graph_entities(id) ON DELETE CASCADE,
            target_entity_id INTEGER NOT NULL REFERENCES graph_entities(id) ON DELETE CASCADE,
            relationship_type VARCHAR NOT NULL,
            confidence FLOAT DEFAULT 1.0,
            metadata_json TEXT,
            created_at DATETIME
        )""",
        """CREATE TABLE IF NOT EXISTS graph_evidence_links (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            relationship_id INTEGER NOT NULL REFERENCES graph_relationships(id) ON DELETE CASCADE,
            chunk_id VARCHAR(32),
            file_path VARCHAR NOT NULL,
            source_label VARCHAR,
            source_index INTEGER,
            char_start INTEGER,
            char_end INTEGER,
            metadata_json TEXT
        )""",
    ]
    indexes = [
        "CREATE INDEX IF NOT EXISTS idx_conversations_updated ON conversations (updated_at)",
        "CREATE INDEX IF NOT EXISTS idx_messages_conv ON conversation_messages (conversation_id)",
        "CREATE INDEX IF NOT EXISTS idx_messages_seq ON conversation_messages (sequence_number)",
        "CREATE INDEX IF NOT EXISTS idx_citations_message ON message_citations (message_id)",
        "CREATE INDEX IF NOT EXISTS idx_citations_chunk ON message_citations (chunk_id)",
        "CREATE INDEX IF NOT EXISTS idx_graph_entities_normalized ON graph_entities (normalized_name)",
        "CREATE INDEX IF NOT EXISTS idx_graph_entities_type ON graph_entities (entity_type)",
        "CREATE INDEX IF NOT EXISTS idx_graph_rels_source ON graph_relationships (source_entity_id)",
        "CREATE INDEX IF NOT EXISTS idx_graph_rels_target ON graph_relationships (target_entity_id)",
        "CREATE INDEX IF NOT EXISTS idx_graph_ev_file ON graph_evidence_links (file_path)",
    ]
    with engine.connect() as conn:
        for stmt in statements:
            conn.execute(text(stmt))
        for idx in indexes:
            conn.execute(text(idx))
        conn.commit()


def add_batch5_tables(engine) -> None:
    """Create Batch 5 organization tables + support indexes.

    Batch 5 §6.1 migration 8. Idempotent: models are also created by
    ``create_all``; this migration adds the supporting indexes, the
    checksum index on ``indexed_files`` and the normalized columns on
    ``ai_analysis`` for existing databases.
    """
    log.info("Applying migration 8: Batch 5 organization tables")
    statements = [
        """CREATE TABLE IF NOT EXISTS collections (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name VARCHAR NOT NULL,
            description TEXT DEFAULT '',
            criteria_json TEXT,
            is_smart BOOLEAN DEFAULT 0,
            created_at DATETIME,
            updated_at DATETIME
        )""",
        """CREATE TABLE IF NOT EXISTS collection_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            collection_id INTEGER NOT NULL REFERENCES collections(id) ON DELETE CASCADE,
            file_path VARCHAR NOT NULL,
            added_at DATETIME,
            source VARCHAR DEFAULT 'manual'
        )""",
        """CREATE TABLE IF NOT EXISTS saved_searches (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name VARCHAR NOT NULL,
            query TEXT NOT NULL,
            scope VARCHAR DEFAULT 'workspace',
            scope_path VARCHAR DEFAULT '',
            modality VARCHAR DEFAULT 'all',
            filters_json TEXT,
            created_at DATETIME,
            updated_at DATETIME,
            last_run DATETIME
        )""",
        """CREATE TABLE IF NOT EXISTS file_relationships (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_path VARCHAR NOT NULL,
            target_path VARCHAR NOT NULL,
            relationship_type VARCHAR NOT NULL,
            confidence FLOAT DEFAULT 1.0,
            evidence_json TEXT,
            created_at DATETIME,
            updated_at DATETIME
        )""",
        """CREATE TABLE IF NOT EXISTS organization_suggestions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            file_path VARCHAR NOT NULL,
            suggested_target VARCHAR NOT NULL,
            target_type VARCHAR DEFAULT 'collection',
            reason TEXT DEFAULT '',
            confidence FLOAT DEFAULT 0.0,
            status VARCHAR DEFAULT 'pending',
            created_at DATETIME,
            updated_at DATETIME
        )""",
    ]
    indexes = [
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_collection_item ON collection_items (collection_id, file_path)",
        "CREATE INDEX IF NOT EXISTS ix_collection_item_path ON collection_items (file_path)",
        "CREATE INDEX IF NOT EXISTS ix_saved_searches_name ON saved_searches (name)",
        "CREATE INDEX IF NOT EXISTS ix_file_relationships_source ON file_relationships (source_path)",
        "CREATE INDEX IF NOT EXISTS ix_file_relationships_target ON file_relationships (target_path)",
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_file_relationship_edge ON file_relationships (source_path, target_path, relationship_type)",
        "CREATE INDEX IF NOT EXISTS ix_org_suggestions_file ON organization_suggestions (file_path)",
        "CREATE INDEX IF NOT EXISTS ix_org_suggestions_status ON organization_suggestions (status)",
        # Scalable exact-duplicate grouping (Batch 5 §3.2)
        "CREATE INDEX IF NOT EXISTS ix_indexed_files_checksum ON indexed_files (checksum)",
    ]
    ai_columns = [
        ("normalized_category", "VARCHAR"),
        ("classification_version", "VARCHAR"),
        ("classified_at", "DATETIME"),
        ("normalized_tags", "TEXT"),
        ("tagging_version", "VARCHAR"),
        ("tagged_at", "DATETIME"),
    ]
    with engine.connect() as conn:
        for stmt in statements:
            conn.execute(text(stmt))
        for idx in indexes:
            conn.execute(text(idx))
        # Add normalized AI-analysis columns to existing databases.
        try:
            existing = {row[1] for row in conn.execute(text("PRAGMA table_info(ai_analysis)"))}
        except Exception:
            existing = set()
        for col, coltype in ai_columns:
            if col in existing:
                continue
            try:
                conn.execute(text(f"ALTER TABLE ai_analysis ADD COLUMN {col} {coltype}"))
            except Exception as exc:  # pragma: no cover - defensive
                log.warning("Could not add ai_analysis column %s: %s", col, exc)
        conn.commit()


def add_batch6_objects(engine) -> None:
    """Create Batch 6 objects — migration 9.

    Batch 6 §12: v8 → v9 with an idempotent migration that preserves existing
    data. Adds the image-caption columns on ``ai_analysis`` (B6-01), the
    ``folder_classifications`` table (B6-02) and the
    ``duplicate_suggestions`` table (B6-04).
    """
    log.info("Applying migration 9: Batch 6 caption, folder classification, duplicate suggestions")
    statements = [
        """CREATE TABLE IF NOT EXISTS folder_classifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            folder_path VARCHAR NOT NULL UNIQUE,
            dominant_category VARCHAR NOT NULL,
            distribution_json TEXT,
            classified_count INTEGER DEFAULT 0,
            unclassified_count INTEGER DEFAULT 0,
            classification_version VARCHAR,
            generated_at DATETIME,
            updated_at DATETIME
        )""",
        """CREATE TABLE IF NOT EXISTS duplicate_suggestions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            group_checksum VARCHAR(64) NOT NULL,
            keep_path VARCHAR NOT NULL,
            remove_path VARCHAR NOT NULL,
            duplicate_type VARCHAR DEFAULT 'exact',
            confidence FLOAT DEFAULT 0.0,
            reason TEXT DEFAULT '',
            evidence_json TEXT,
            status VARCHAR DEFAULT 'pending',
            created_at DATETIME,
            updated_at DATETIME
        )""",
    ]
    indexes = [
        "CREATE INDEX IF NOT EXISTS ix_folder_classifications_path ON folder_classifications (folder_path)",
        "CREATE INDEX IF NOT EXISTS ix_dup_suggestions_checksum ON duplicate_suggestions (group_checksum)",
        "CREATE INDEX IF NOT EXISTS ix_dup_suggestions_remove ON duplicate_suggestions (remove_path)",
        "CREATE INDEX IF NOT EXISTS ix_dup_suggestions_status ON duplicate_suggestions (status)",
    ]
    caption_columns = [
        ("caption", "TEXT"),
        ("caption_model", "VARCHAR"),
        ("caption_version", "VARCHAR"),
        ("captioned_at", "DATETIME"),
    ]
    with engine.connect() as conn:
        for stmt in statements:
            conn.execute(text(stmt))
        for idx in indexes:
            conn.execute(text(idx))
        # Add caption columns to existing databases.
        try:
            existing = {row[1] for row in conn.execute(text("PRAGMA table_info(ai_analysis)"))}
        except Exception:
            existing = set()
        for col, coltype in caption_columns:
            if col in existing:
                continue
            try:
                conn.execute(text(f"ALTER TABLE ai_analysis ADD COLUMN {col} {coltype}"))
            except Exception as exc:  # pragma: no cover - defensive
                log.warning("Could not add ai_analysis column %s: %s", col, exc)
        conn.commit()


def add_batch7_objects(engine) -> None:
    """Create Batch 7 schema additions — migration 10.

    Batch 7 §16: v9 → v10, idempotent, preserves existing data. Adds:
      - ai_analysis: objects_json, quality_score, quality_json (image
        intelligence: object detection, quality analysis)
      - folder_classifications: summary, summary_model, summary_version,
        summarized_at (AI-powered folder summary)
    No speculative schema: only columns actually used by the implementation.
    """
    log.info("Applying migration 10: Batch 7 image intelligence + folder summary")
    ai_columns = [
        ("objects_json", "TEXT"),
        ("quality_score", "FLOAT"),
        ("quality_json", "TEXT"),
    ]
    folder_columns = [
        ("summary", "TEXT"),
        ("summary_model", "VARCHAR"),
        ("summary_version", "VARCHAR"),
        ("summarized_at", "DATETIME"),
    ]
    # Batch 7: user-edited metadata (B7-6) + last_opened_at tracking on indexed_files.
    indexed_columns = [("user_metadata_json", "TEXT"), ("last_opened_at", "DATETIME")]

    with engine.connect() as conn:
        try:
            ai_existing = {row[1] for row in conn.execute(text("PRAGMA table_info(ai_analysis)"))}
        except Exception:
            ai_existing = set()
        for col, coltype in ai_columns:
            if col in ai_existing:
                continue
            try:
                conn.execute(text(f"ALTER TABLE ai_analysis ADD COLUMN {col} {coltype}"))
            except Exception as exc:  # pragma: no cover - defensive
                log.warning("Could not add ai_analysis column %s: %s", col, exc)
        try:
            folder_existing = {row[1] for row in conn.execute(text("PRAGMA table_info(folder_classifications)"))}
        except Exception:
            folder_existing = set()
        for col, coltype in folder_columns:
            if col in folder_existing:
                continue
            try:
                conn.execute(text(f"ALTER TABLE folder_classifications ADD COLUMN {col} {coltype}"))
            except Exception as exc:  # pragma: no cover - defensive
                log.warning("Could not add folder_classifications column %s: %s", col, exc)
        try:
            indexed_existing = {row[1] for row in conn.execute(text("PRAGMA table_info(indexed_files)"))}
        except Exception:
            indexed_existing = set()
        for col, coltype in indexed_columns:
            if col in indexed_existing:
                continue
            try:
                conn.execute(text(f"ALTER TABLE indexed_files ADD COLUMN {col} {coltype}"))
            except Exception as exc:  # pragma: no cover - defensive
                log.warning("Could not add indexed_files column %s: %s", col, exc)
        conn.commit()


MIGRATIONS: dict[int, MigrationFn] = {
    1: lambda engine: None,  # Initial schema (handled by create_all)
    2: add_fts5_index,
    3: add_embedding_table,
    4: lambda engine: None,  # ai_analysis table (handled by create_all)
    5: lambda engine: None,  # Batch 3: evidence, vector_map, search_history (handled by create_all)
    6: add_evidence_modality_columns,
    7: add_batch4_tables,
    8: add_batch5_tables,
    9: add_batch6_objects,
    10: add_batch7_objects,
}


def run_migrations(engine) -> None:
    # Always ensure column migrations (like last_opened_at, user_metadata_json) are retrofitted
    try:
        add_batch7_objects(engine)
    except Exception as exc:
        log.warning("Column retrofit check failed: %s", exc)

    current = get_current_version(engine)
    latest = max(MIGRATIONS.keys()) if MIGRATIONS else 0

    if current >= latest:
        return


    for version in range(current + 1, latest + 1):
        if version in MIGRATIONS:
            log.info("Applying migration %d...", version)
            MIGRATIONS[version](engine)
            set_version(engine, version)
            log.info("Migration %d applied successfully", version)
        else:
            log.warning("Migration %d not found, skipping", version)


def init_database(path: str):
    url = f"sqlite:///{path}"
    engine = create_engine(
        url,
        future=True,
        pool_pre_ping=True,
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    run_migrations(engine)
    return engine