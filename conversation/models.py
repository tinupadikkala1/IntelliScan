"""Service-layer dataclasses for conversations (independent of ORM rows)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class CitationRecord:
    """A citation attached to an assistant message.

    Carries full evidence location so the UI can invoke EvidenceNavigator.
    """

    chunk_id: str = ""
    file_path: str = ""
    source_label: str = ""
    source_index: int = 0
    source_type: str = ""
    char_start: int = 0
    char_end: int = 0
    timestamp_start: float = 0.0
    timestamp_end: float = 0.0
    snippet: str = ""
    score: float = 0.0
    modality: str = "document"

    def to_dict(self) -> dict:
        return {
            "chunk_id": self.chunk_id,
            "file_path": self.file_path,
            "source_label": self.source_label,
            "source_index": self.source_index,
            "source_type": self.source_type,
            "char_start": self.char_start,
            "char_end": self.char_end,
            "timestamp_start": self.timestamp_start,
            "timestamp_end": self.timestamp_end,
            "snippet": self.snippet,
            "score": self.score,
            "modality": self.modality,
        }


@dataclass
class ChatMessage:
    """A single message (user or assistant) with its citations."""

    role: str  # user | assistant
    content: str
    citations: List[CitationRecord] = field(default_factory=list)
    sequence_number: int = 0
    metadata: dict = field(default_factory=dict)


@dataclass
class ConversationInfo:
    """Summary of a conversation (history list item)."""

    id: int
    title: str
    scope_type: str
    scope_path: str
    created_at: object = None
    updated_at: object = None
    message_count: int = 0


@dataclass
class ChatResult:
    """Result of one chat turn."""

    answer: str
    citations: List[CitationRecord]
    grounded: bool
    conversation_id: int
    resolved_query: str = ""
    elapsed_ms: float = 0.0
    error: Optional[str] = None
