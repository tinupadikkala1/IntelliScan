"""Bounded context builders for chat and multi-document reasoning.

Batch 4 M0-04 / M6. Never send unbounded history or whole workspaces to the
LLM: history and evidence are capped by explicit character/turn budgets and
evidence is spread across files instead of dominated by one source.
"""

from __future__ import annotations

import logging
from collections import OrderedDict
from typing import List, Optional

from engines.config import (
    CONVERSATION_MAX_HISTORY_CHARS,
    CONVERSATION_MAX_TURNS,
    RAG_MAX_CONTEXT,
)

from .models import ChatMessage

logger = logging.getLogger(__name__)


class ConversationContextBuilder:
    """Builds a bounded LLM prompt from history + retrieved evidence."""

    def __init__(
        self,
        max_history_chars: int = CONVERSATION_MAX_HISTORY_CHARS,
        max_turns: int = CONVERSATION_MAX_TURNS,
        max_evidence_chars: int = RAG_MAX_CONTEXT,
    ) -> None:
        self._max_history_chars = max_history_chars
        self._max_turns = max_turns
        self._max_evidence_chars = max_evidence_chars

    def build_history(
        self, messages: List[ChatMessage], max_turns: Optional[int] = None
    ) -> str:
        """Serialize recent turns (user/assistant pairs) into bounded text.

        Args:
            messages: All messages (oldest first).
            max_turns: Override turn budget.

        Returns:
            Formatted history string (empty when no history).
        """
        max_turns = max_turns or self._max_turns
        recent = messages[-max_turns * 2:] if len(messages) > max_turns * 2 else messages

        parts = []
        total = 0
        for msg in reversed(recent):
            if msg.role not in ("user", "assistant"):
                continue
            line = f"{'User' if msg.role == 'user' else 'Assistant'}: {msg.content.strip()}"
            if total + len(line) > self._max_history_chars and parts:
                break
            parts.append(line)
            total += len(line)
            if total >= self._max_history_chars:
                break
        parts.reverse()
        return "\n".join(parts)

    def build_evidence(
        self,
        results,
        max_chars: Optional[int] = None,
    ) -> str:
        """Serialize retrieval results into bounded evidence context.

        Results may be RetrievalResult objects or plain dicts.
        """
        max_chars = max_chars or self._max_evidence_chars
        parts = []
        total = 0
        for r in results:
            text = (getattr(r, "text", None) or r.get("text", "")) if not isinstance(r, dict) else r.get("text", "")
            source = (getattr(r, "source_label", None) or r.get("source_label", "")) if not isinstance(r, dict) else r.get("source_label", "")
            path = (getattr(r, "file_path", None) or r.get("file_path", "")) if not isinstance(r, dict) else r.get("file_path", "")
            if not text:
                continue
            remaining = max_chars - total
            if remaining <= 0:
                break
            snippet = text[:remaining] if len(text) > remaining else text
            file_name = path.split("/")[-1] if path else "?"
            parts.append(f"[{source or 'Source'} | {file_name}]\n{snippet}")
            total += len(snippet)
        return "\n\n---\n\n".join(parts)

    def build_prompt(
        self,
        question: str,
        evidence_context: str,
        history: str = "",
        system: Optional[str] = None,
    ) -> str:
        """Assemble the final chat prompt with priority:
        system → question → evidence → history.
        """
        if system is None:
            system = (
                "You are IntelliVault, a grounded knowledge assistant. "
                "Answer the user's question using ONLY the provided evidence "
                "and conversation history. If the evidence does not contain "
                "the answer, say so explicitly. Never invent facts, page "
                "numbers, timestamps or sources."
            )
        prompt = system
        if history:
            prompt += f"\n\nCONVERSATION HISTORY:\n{history}"
        prompt += f"\n\nEVIDENCE:\n{evidence_context}" if evidence_context else "\n\nEVIDENCE:\n(no evidence retrieved)"
        prompt += f"\n\nQUESTION: {question}\n\nANSWER:"
        return prompt


class MultiDocumentContextBuilder:
    """Builds cross-document evidence context, grouping by source file.

    Enforces per-file chunk caps (evidence diversity) and produces a
    per-file index so the LLM can attribute claims to specific documents.
    """

    def __init__(self, max_chars: int = RAG_MAX_CONTEXT, max_chunks_per_file: int = 3) -> None:
        self._max_chars = max_chars
        self._max_chunks_per_file = max_chunks_per_file

    def group_by_file(self, results) -> "OrderedDict[str, list]":
        """Group results by file path, keeping best-scoring chunks first."""
        grouped: "OrderedDict[str, list]" = OrderedDict()
        for r in results:
            path = getattr(r, "file_path", None) or (r.get("file_path") if isinstance(r, dict) else None)
            if not path:
                continue
            grouped.setdefault(path, []).append(r)
        for path in grouped:
            chunks = grouped[path]
            first = chunks[0] if chunks else None
            modality = getattr(first, "modality", "") or (first.get("modality", "") if isinstance(first, dict) else "")
            max_chunks = 25 if modality in ("audio", "video") or len(grouped) == 1 else self._max_chunks_per_file

            chunks.sort(
                key=lambda r: (r.score if not isinstance(r, dict) else r.get("score", 0.0)),
                reverse=True,
            )
            grouped[path] = chunks[:max_chunks]
        return grouped


    def build(self, results, max_chars: Optional[int] = None) -> str:
        """Build a per-file-labeled evidence context string."""
        max_chars = max_chars or self._max_chars
        grouped = self.group_by_file(results)
        parts = []
        total = 0
        for path, chunks in grouped.items():
            file_name = path.split("/")[-1] or path
            block_parts = [f"--- DOCUMENT: {file_name} ---"]
            for c in chunks:
                text = getattr(c, "text", None) or (c.get("text") if isinstance(c, dict) else "")
                source = getattr(c, "source_label", None) or (c.get("source_label") if isinstance(c, dict) else "")
                if not text:
                    continue
                remaining = max_chars - total
                if remaining <= 0:
                    break
                snippet = text[:remaining] if len(text) > remaining else text
                block_parts.append(f"[{source or 'Source'}]\n{snippet}")
                total += len(snippet)
            if len(block_parts) > 1:
                block = "\n".join(block_parts)
                parts.append(block)
            if total >= max_chars:
                break
        return "\n\n".join(parts)

    def document_map(self, results) -> dict:
        """Return {file_path: count} for observability/testing."""
        grouped = self.group_by_file(results)
        return {path: len(chunks) for path, chunks in grouped.items()}
