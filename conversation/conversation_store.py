"""Conversation store — SQLite persistence for conversations, messages, citations.

Follows the EngineDBStore pattern (per-call sessions, shared Base) and the
Batch 4 M0-06 rule: persistence failures raise PersistenceError instead of
silently returning success.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import List, Optional

from database.models import Conversation, ConversationMessage, MessageCitation

from .models import ChatMessage, CitationRecord, ConversationInfo

logger = logging.getLogger(__name__)


class ConversationPersistenceError(Exception):
    """Raised when a conversation cannot be persisted."""


class ConversationStore:
    """CRUD over conversations/messages/citations."""

    def __init__(self, session_factory) -> None:
        self._session_factory = session_factory

    # ------------------------------------------------------------------ #
    # Conversations
    # ------------------------------------------------------------------ #
    def create_conversation(
        self,
        scope_type: str = "workspace",
        scope_path: str = "",
        title: Optional[str] = None,
        model_name: str = "",
        metadata: Optional[dict] = None,
    ) -> int:
        """Create a conversation and return its id."""
        try:
            with self._session_factory() as session:
                conv = Conversation(
                    title=title or "New Conversation",
                    scope_type=scope_type,
                    scope_path=scope_path,
                    model_name=model_name,
                    metadata_json=json.dumps(metadata or {}),
                )
                session.add(conv)
                session.commit()
                return conv.id
        except Exception as e:
            logger.error("Failed to create conversation: %s", e)
            raise ConversationPersistenceError(f"Could not create conversation: {e}") from e

    def list_conversations(self, limit: int = 200) -> List[ConversationInfo]:
        """List conversations, newest first, with message counts."""
        try:
            with self._session_factory() as session:
                rows = (
                    session.query(
                        Conversation,
                        session.query(ConversationMessage)
                        .filter(ConversationMessage.conversation_id == Conversation.id)
                        .count(),
                    )
                    .order_by(Conversation.updated_at.desc())
                    .limit(limit)
                    .all()
                )
                return [
                    ConversationInfo(
                        id=conv.id,
                        title=conv.title,
                        scope_type=conv.scope_type,
                        scope_path=conv.scope_path,
                        created_at=conv.created_at,
                        updated_at=conv.updated_at,
                        message_count=count,
                    )
                    for conv, count in rows
                ]
        except Exception as e:
            logger.error("Failed to list conversations: %s", e)
            raise ConversationPersistenceError(f"Could not list conversations: {e}") from e

    def get_conversation(self, conversation_id: int) -> Optional[ConversationInfo]:
        try:
            with self._session_factory() as session:
                conv = session.get(Conversation, conversation_id)
                if conv is None:
                    return None
                count = (
                    session.query(ConversationMessage)
                    .filter(ConversationMessage.conversation_id == conversation_id)
                    .count()
                )
                return ConversationInfo(
                    id=conv.id,
                    title=conv.title,
                    scope_type=conv.scope_type,
                    scope_path=conv.scope_path,
                    created_at=conv.created_at,
                    updated_at=conv.updated_at,
                    message_count=count,
                )
        except Exception as e:
            logger.error("Failed to get conversation %s: %s", conversation_id, e)
            raise ConversationPersistenceError(
                f"Could not load conversation {conversation_id}: {e}"
            ) from e

    def rename_conversation(self, conversation_id: int, title: str) -> bool:
        try:
            with self._session_factory() as session:
                conv = session.get(Conversation, conversation_id)
                if conv is None:
                    return False
                conv.title = title
                conv.updated_at = datetime.now()
                session.commit()
                return True
        except Exception as e:
            logger.error("Failed to rename conversation %s: %s", conversation_id, e)
            raise ConversationPersistenceError(
                f"Could not rename conversation {conversation_id}: {e}"
            ) from e

    def delete_conversation(self, conversation_id: int) -> bool:
        try:
            with self._session_factory() as session:
                conv = session.get(Conversation, conversation_id)
                if conv is None:
                    return False
                session.delete(conv)  # cascade deletes messages + citations
                session.commit()
                return True
        except Exception as e:
            logger.error("Failed to delete conversation %s: %s", conversation_id, e)
            raise ConversationPersistenceError(
                f"Could not delete conversation {conversation_id}: {e}"
            ) from e

    # ------------------------------------------------------------------ #
    # Messages + citations
    # ------------------------------------------------------------------ #
    def append_message(
        self,
        conversation_id: int,
        role: str,
        content: str,
        citations: Optional[List[CitationRecord]] = None,
        metadata: Optional[dict] = None,
    ) -> int:
        """Append a message (+ citations) and return the message id."""
        try:
            with self._session_factory() as session:
                conv = session.get(Conversation, conversation_id)
                if conv is None:
                    raise ConversationPersistenceError(
                        f"Conversation {conversation_id} does not exist"
                    )
                last_seq = (
                    session.query(ConversationMessage)
                    .filter(ConversationMessage.conversation_id == conversation_id)
                    .order_by(ConversationMessage.sequence_number.desc())
                    .first()
                )
                seq = (last_seq.sequence_number + 1) if last_seq else 0

                msg = ConversationMessage(
                    conversation_id=conversation_id,
                    role=role,
                    content=content,
                    sequence_number=seq,
                    metadata_json=json.dumps(metadata or {}),
                )
                session.add(msg)
                session.flush()  # assign msg.id

                for order, cit in enumerate(citations or []):
                    session.add(MessageCitation(
                        message_id=msg.id,
                        chunk_id=cit.chunk_id,
                        file_path=cit.file_path,
                        source_label=cit.source_label,
                        source_index=cit.source_index,
                        char_start=cit.char_start,
                        char_end=cit.char_end,
                        timestamp_start=cit.timestamp_start,
                        timestamp_end=cit.timestamp_end,
                        citation_order=order,
                        metadata_json=json.dumps(cit.to_dict()),
                    ))

                conv.updated_at = datetime.now()
                session.commit()
                return msg.id
        except ConversationPersistenceError:
            raise
        except Exception as e:
            logger.error("Failed to append message: %s", e)
            raise ConversationPersistenceError(f"Could not append message: {e}") from e

    def get_messages(self, conversation_id: int) -> List[ChatMessage]:
        """Return messages (oldest first) with their citations."""
        try:
            with self._session_factory() as session:
                rows = (
                    session.query(ConversationMessage)
                    .filter(ConversationMessage.conversation_id == conversation_id)
                    .order_by(ConversationMessage.sequence_number.asc())
                    .all()
                )
                messages: List[ChatMessage] = []
                for row in rows:
                    cit_rows = (
                        session.query(MessageCitation)
                        .filter(MessageCitation.message_id == row.id)
                        .order_by(MessageCitation.citation_order.asc())
                        .all()
                    )
                    citations = [self._citation_from_row(c) for c in cit_rows]
                    metadata = {}
                    if row.metadata_json:
                        try:
                            metadata = json.loads(row.metadata_json) or {}
                        except (json.JSONDecodeError, TypeError):
                            metadata = {}
                    messages.append(ChatMessage(
                        role=row.role,
                        content=row.content,
                        citations=citations,
                        sequence_number=row.sequence_number,
                        metadata=metadata,
                    ))
                return messages
        except Exception as e:
            logger.error("Failed to load messages: %s", e)
            raise ConversationPersistenceError(
                f"Could not load messages for conversation {conversation_id}: {e}"
            ) from e

    # ------------------------------------------------------------------ #
    @staticmethod
    def _citation_from_row(row: MessageCitation) -> CitationRecord:
        metadata = {}
        if row.metadata_json:
            try:
                metadata = json.loads(row.metadata_json) or {}
            except (json.JSONDecodeError, TypeError):
                metadata = {}
        return CitationRecord(
            chunk_id=row.chunk_id or "",
            file_path=row.file_path or "",
            source_label=row.source_label or "",
            source_index=row.source_index or 0,
            source_type=metadata.get("source_type", ""),
            char_start=row.char_start or 0,
            char_end=row.char_end or 0,
            timestamp_start=row.timestamp_start or 0.0,
            timestamp_end=row.timestamp_end or 0.0,
            snippet=metadata.get("snippet", ""),
            score=float(metadata.get("score", 0.0) or 0.0),
            modality=metadata.get("modality", "document"),
        )
