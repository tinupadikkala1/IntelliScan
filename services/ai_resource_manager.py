"""AI resource manager — bounded concurrency for heavy AI workloads.

Batch 4 M0-08. The host machine (Intel i3-N305, 6.9 GiB RAM, CPU-only) cannot
safely run Whisper, CLIP, moondream and Qwen simultaneously. This manager
provides per-slot semaphores (LLM / embedding / vision / speech) plus a
global concurrency limit so a runaway task queue cannot exhaust RAM.

Usage (from worker threads only):

    with ai_resources.llm():
        ... call Ollama generation ...

Each heavy call acquires exactly ONE slot; callers never hold two slots at
once (avoids deadlock between slots and the global limit).
"""

from __future__ import annotations

import logging
import threading
from contextlib import contextmanager
from typing import Iterator, Optional

from engines.config import (
    AI_EMBEDDING_SLOTS,
    AI_GLOBAL_LIMIT,
    AI_LLM_SLOTS,
    AI_SPEECH_SLOTS,
    AI_VISION_SLOTS,
)

logger = logging.getLogger(__name__)


class AIResourceManager:
    """Semaphore-based slots for AI subsystems.

    Acquire semantics: block until a slot is free (or timeout elapses).
    ``cancelled`` is an optional threading.Event; when set, pending acquires
    abort with an AIResourceUnavailable error instead of waiting forever.
    """

    def __init__(
        self,
        llm_slots: int = AI_LLM_SLOTS,
        embedding_slots: int = AI_EMBEDDING_SLOTS,
        vision_slots: int = AI_VISION_SLOTS,
        speech_slots: int = AI_SPEECH_SLOTS,
        global_limit: int = AI_GLOBAL_LIMIT,
    ) -> None:
        self._global = threading.BoundedSemaphore(max(1, global_limit))
        self._llm = threading.BoundedSemaphore(max(1, llm_slots))
        self._embedding = threading.BoundedSemaphore(max(1, embedding_slots))
        self._vision = threading.BoundedSemaphore(max(1, vision_slots))
        self._speech = threading.BoundedSemaphore(max(1, speech_slots))
        self._cancelled: Optional[threading.Event] = None

    # ------------------------------------------------------------------ #
    def set_cancel_event(self, event: Optional[threading.Event]) -> None:
        """Bind a cancellation event; pending acquires abort when set."""
        self._cancelled = event

    def _acquire(self, semaphore: threading.BoundedSemaphore, timeout: float) -> bool:
        deadline = None if timeout is None else (threading.get_ident(), timeout)
        acquired = semaphore.acquire(timeout=timeout)
        if not acquired:
            raise AIResourceUnavailable(
                f"AI resource busy (waited {timeout}s). Another AI task is running."
            )
        return True

    def _check_cancel(self) -> None:
        if self._cancelled is not None and self._cancelled.is_set():
            raise AIResourceUnavailable("AI operation cancelled while waiting for resources")

    @contextmanager
    def llm(self, timeout: float = 600.0) -> Iterator[None]:
        self._check_cancel()
        self._acquire(self._global, timeout)
        try:
            self._check_cancel()
            self._acquire(self._llm, timeout)
        except BaseException:
            self._global.release()
            raise
        try:
            yield
        finally:
            self._llm.release()
            self._global.release()

    @contextmanager
    def embedding(self, timeout: float = 300.0) -> Iterator[None]:
        self._check_cancel()
        self._acquire(self._global, timeout)
        try:
            self._check_cancel()
            self._acquire(self._embedding, timeout)
        except BaseException:
            self._global.release()
            raise
        try:
            yield
        finally:
            self._embedding.release()
            self._global.release()

    @contextmanager
    def vision(self, timeout: float = 300.0) -> Iterator[None]:
        self._check_cancel()
        self._acquire(self._global, timeout)
        try:
            self._check_cancel()
            self._acquire(self._vision, timeout)
        except BaseException:
            self._global.release()
            raise
        try:
            yield
        finally:
            self._vision.release()
            self._global.release()

    @contextmanager
    def speech(self, timeout: float = 600.0) -> Iterator[None]:
        self._check_cancel()
        self._acquire(self._global, timeout)
        try:
            self._check_cancel()
            self._acquire(self._speech, timeout)
        except BaseException:
            self._global.release()
            raise
        try:
            yield
        finally:
            self._speech.release()
            self._global.release()

    # ------------------------------------------------------------------ #
    def snapshot(self) -> dict:
        """Return current slot availability (for status bar / observability)."""
        return {
            "global": self._global._value if hasattr(self._global, "_value") else 1,
            "llm": self._llm._value if hasattr(self._llm, "_value") else 1,
            "embedding": self._embedding._value if hasattr(self._embedding, "_value") else 1,
            "vision": self._vision._value if hasattr(self._vision, "_value") else 1,
            "speech": self._speech._value if hasattr(self._speech, "_value") else 1,
        }


class AIResourceUnavailable(Exception):
    """Raised when an AI resource slot cannot be acquired in time."""
