"""Conversation manager — orchestration layer for chat turns.

Pipeline per turn (Batch 4 §17, §23):
    question
      → follow-up resolution (LLM, original retained)
      → scoped retrieval (file/folder/workspace)
      → multi-document evidence context
      → bounded conversation history
      → RAG generation (qwen) with contradiction instructions
      → citations
      → persistence (user + assistant messages, citations)

All LLM/retrieval work happens in the calling worker thread; this class
never touches Qt widgets.
"""

from __future__ import annotations

import logging
import os
import time
from typing import List, Optional

from engines.config import (
    CONVERSATION_DEFAULT_SCOPE,
    MAX_CHUNKS_PER_FILE,
    SIMILARITY_THRESHOLD,
    TOP_K_DEFAULT,
)
from engines.rag_engine import RAGEngine
from engines.retrieval_engine import RetrievalEngine, RetrievalScope

from .citation_builder import CitationBuilder
from .context_builder import ConversationContextBuilder, MultiDocumentContextBuilder
from .conversation_store import ConversationStore
from .models import ChatMessage, ChatResult, ConversationInfo
from .scope_manager import ChatScope, ScopeManager

logger = logging.getLogger(__name__)


class ConversationManager:
    """Owns the chat pipeline and conversation persistence."""

    def __init__(
        self,
        store: ConversationStore,
        retrieval: RetrievalEngine,
        rag: RAGEngine,
        scope_manager: Optional[ScopeManager] = None,
        graph=None,
    ) -> None:
        self._store = store
        self._retrieval = retrieval
        self._rag = rag
        self._scope = scope_manager or ScopeManager()
        self._history_builder = ConversationContextBuilder()
        self._multidoc = MultiDocumentContextBuilder()
        self._graph = graph

    # ------------------------------------------------------------------ #
    # Conversation CRUD (delegated to the store)
    # ------------------------------------------------------------------ #
    def start(
        self,
        scope_type: str = CONVERSATION_DEFAULT_SCOPE,
        scope_path: str = "",
        title: Optional[str] = None,
    ) -> int:
        return self._store.create_conversation(
            scope_type=scope_type,
            scope_path=scope_path,
            title=title,
            model_name=getattr(self._rag, "_model", ""),
        )

    def list_conversations(self, limit: int = 200) -> List[ConversationInfo]:
        return self._store.list_conversations(limit=limit)

    def get_conversation(self, conversation_id: int) -> Optional[ConversationInfo]:
        return self._store.get_conversation(conversation_id)

    def rename(self, conversation_id: int, title: str) -> bool:
        return self._store.rename_conversation(conversation_id, title)

    def delete(self, conversation_id: int) -> bool:
        return self._store.delete_conversation(conversation_id)

    def messages(self, conversation_id: int) -> List[ChatMessage]:
        return self._store.get_messages(conversation_id)

    # ------------------------------------------------------------------ #
    # Chat turn
    # ------------------------------------------------------------------ #
    def ask(
        self,
        conversation_id: int,
        question: str,
        top_k: int = TOP_K_DEFAULT,
        threshold: float = SIMILARITY_THRESHOLD,
        max_chunks_per_file: int = MAX_CHUNKS_PER_FILE,
        cancel_event=None,
    ) -> ChatResult:
        """Run one chat turn against a conversation, persisting everything."""
        start = time.time()
        question = (question or "").strip()
        if not question:
            return ChatResult(
                answer="", citations=[], grounded=False,
                conversation_id=conversation_id, error="Empty question",
            )

        conv = self._store.get_conversation(conversation_id)
        if conv is None:
            raise ValueError(f"Conversation {conversation_id} does not exist")

        messages = self._store.get_messages(conversation_id)
        scope = ChatScope(conv.scope_type, conv.scope_path)

        # 1. Follow-up resolution (retain the original question for the LLM).
        resolved = self._resolve(question, messages, cancel_event)

        # 2. Scoped retrieval.
        if cancel_event is not None and cancel_event.is_set():
            return self._cancelled(conversation_id)
        evidence_map = getattr(self._retrieval, "_evidence", {})
        file_filter = self._scope.file_filter(scope, evidence_map)
        graph_files = self._graph_files(resolved, file_filter)
        if graph_files:
            file_filter = list(dict.fromkeys((file_filter or []) + graph_files))
        if hasattr(self._retrieval, "smart_retrieve"):
            response = self._retrieval.smart_retrieve(
                query=resolved,
                top_k=top_k,
                threshold=threshold,
                file_filter=file_filter,
                max_chunks_per_file=max_chunks_per_file,
            )
        else:
            response = self._retrieval.retrieve(
                query=resolved,
                scope=RetrievalScope.WORKSPACE,
                top_k=top_k,
                threshold=threshold,
                file_filter=file_filter,
                max_chunks_per_file=max_chunks_per_file,
            )


        results = self._scope.filter_results(response.results, scope)
        if not response.embedding_available:
            return ChatResult(
                answer="",
                citations=[], grounded=False,
                conversation_id=conversation_id,
                resolved_query=resolved,
                error="embedding_unavailable",
                elapsed_ms=(time.time() - start) * 1000,
            )

        # 3. Build bounded contexts.
        evidence_context = self._multidoc.build(results)
        history = self._history_builder.build_history(messages)

        # 4. Generate the grounded answer (original question, contradiction-aware).
        if cancel_event is not None and cancel_event.is_set():
            return self._cancelled(conversation_id)

        # Dynamic semantic reasoning hints for small local LLMs
        extra_instructions = None
        if hasattr(self._retrieval, "detect_semantic_concepts"):
            try:
                concepts = self._retrieval.detect_semantic_concepts(question)
                hints = []
                if "human" in concepts and "number_2" in concepts:
                    hints.append("Special note: 'a couple' (a man and a woman) explicitly represents two humans. 'Two men', 'two women', and 'a couple' all count as two humans.")
                elif "human" in concepts:
                    hints.append("Note: 'humans' and 'people' includes men, women, couple, individuals, persons.")
                if "finance" in concepts:
                    hints.append("Note: 'invoices' includes bills, billing statements, receipts, and payment accounts.")
                if "vehicle" in concepts:
                    hints.append("Note: 'vehicles' includes cars, automobiles, trucks, buses, bikes.")
                if hints:
                    extra_instructions = "\n".join(hints)
            except Exception:
                pass

        answer = self._rag.answer_multi(question, evidence_context, extra_instructions=extra_instructions)

        if cancel_event is not None and cancel_event.is_set():
            return self._cancelled(conversation_id)

        # 5. Citations.
        citations = CitationBuilder.from_results(results, scope=scope)


        # 6. Persist the turn.
        self._store.append_message(
            conversation_id, "user", question,
            metadata={"resolved_query": resolved} if resolved != question else {},
        )
        self._store.append_message(
            conversation_id, "assistant", answer or "I could not generate an answer.",
            citations=citations,
            metadata={"model": getattr(self._rag, "_model", "")},
        )

        elapsed = (time.time() - start) * 1000
        logger.info(
            "Chat turn %s: %d results, %d citations, %.0f ms",
            conversation_id, len(results), len(citations), elapsed,
        )
        return ChatResult(
            answer=answer,
            citations=citations,
            grounded=bool(answer),
            conversation_id=conversation_id,
            resolved_query=resolved,
            elapsed_ms=elapsed,
        )

    # ------------------------------------------------------------------ #
    def _graph_files(self, query: str, file_filter: Optional[List[str]]) -> List[str]:
        """Supplement retrieval with files connected to graph entities (§40).

        The knowledge graph supplements semantic retrieval; it never replaces
        it. Entity matches for the query add their related files to the
        retrieval file filter (only when a scope filter already exists so
        graph hits never widen a workspace chat unintentionally).
        """
        if self._graph is None or not file_filter:
            return []
        try:
            store = getattr(self._graph, "store", None)
            if store is None:
                return []
            matches = store.search_entities(query, limit=3)
            related: List[str] = []
            filter_set = {os.path.abspath(f) for f in file_filter}
            filter_dirs = {os.path.dirname(os.path.abspath(f)) for f in file_filter}
            for m in matches:
                for rf in store.related_files(m["id"]):
                    rf_abs = os.path.abspath(rf)
                    if rf_abs in filter_set or os.path.dirname(rf_abs) in filter_dirs:
                        related.append(rf)
            return related[:10]

        except Exception as exc:
            logger.debug("Graph supplement skipped: %s", exc)
            return []

    def _resolve(self, question: str, messages: List[ChatMessage], cancel_event) -> str:
        if len(messages) < 2:
            return question

        # Only attempt followup resolution if the question looks like an anaphoric follow-up
        q_lower = question.lower()
        followup_signals = {
            'it', 'its', 'they', 'them', 'their', 'that', 'this', 'these', 'those',
            'more', 'else', 'also', 'and', 'what about', 'how about', 'which one',
            'the first', 'the second', 'the other', 'previous', 'above', 'same',
        }
        words = set(q_lower.split())
        is_likely_followup = bool(words.intersection(followup_signals) or any(s in q_lower for s in ('what about', 'how about', 'tell me more', 'who did', 'why did')))
        if not is_likely_followup:
            return question

        history = self._history_builder.build_history(messages, max_turns=4)
        if not history.strip():
            return question
        if cancel_event is not None and cancel_event.is_set():
            return question
        try:
            return self._rag.resolve_followup(question, history)
        except Exception as exc:  # fallback: original question
            logger.debug("Follow-up resolution failed, using original: %s", exc)
            return question

    @staticmethod
    def _cancelled(conversation_id: int) -> ChatResult:
        return ChatResult(
            answer="", citations=[], grounded=False,
            conversation_id=conversation_id, error="cancelled",
        )
