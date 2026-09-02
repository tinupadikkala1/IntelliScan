"""Batch 4 — Persistent Conversations.

Layers:
    conversation_store       — SQLite persistence (conversations/messages/citations)
    conversation_manager     — orchestration (retrieval → context → RAG → citations)
    conversation_service     — worker entry point used by the UI thread pool
    context_builder          — bounded LLM context from history + evidence
    citation_builder         — evidence → persisted citation records
    scope_manager            — file/folder/workspace scope resolution
"""

from .conversation_store import ConversationStore
from .conversation_manager import ConversationManager
from .conversation_service import run_chat

__all__ = [
    "ConversationStore",
    "ConversationManager",
    "run_chat",
]
