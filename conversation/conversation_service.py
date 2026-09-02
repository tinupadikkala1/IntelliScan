"""Conversation service — worker entry point used by the UI thread pool.

Conforms to the TaskManager worker contract:
    fn(progress_callback, cancel_event, *args, **kwargs)

Keeps Qt out of the conversation package: the service returns plain
ChatResult objects that the UI marshals onto the GUI thread via signals.
"""

from __future__ import annotations

import logging
from typing import Optional

from .conversation_manager import ConversationManager
from .models import ChatResult

logger = logging.getLogger(__name__)


def run_chat(
    progress_callback,
    cancel_event,
    manager: ConversationManager,
    conversation_id: int,
    question: str,
    top_k: int = 5,
    threshold: float = 0.3,
    max_chunks_per_file: Optional[int] = None,
) -> ChatResult:
    """Run one chat turn in a worker thread.

    Args:
        progress_callback: TaskManager progress signal (current, total).
        cancel_event: threading.Event checked between pipeline stages.
        manager: Configured ConversationManager.
        conversation_id: Target conversation.
        question: The user's question.
        top_k: Retrieval candidate count.
        threshold: Similarity threshold.
        max_chunks_per_file: Per-file evidence cap (default from config).

    Returns:
        ChatResult (answer, citations, grounded, conversation_id).
    """
    if progress_callback is not None:
        progress_callback(1, 4)
    try:
        result = manager.ask(
            conversation_id=conversation_id,
            question=question,
            top_k=top_k,
            threshold=threshold,
            max_chunks_per_file=max_chunks_per_file,
            cancel_event=cancel_event,
        )
        if progress_callback is not None:
            progress_callback(4, 4)
        return result
    except Exception as exc:
        logger.error("Chat turn failed: %s", exc, exc_info=True)
        return ChatResult(
            answer="",
            citations=[],
            grounded=False,
            conversation_id=conversation_id,
            error=str(exc),
        )
