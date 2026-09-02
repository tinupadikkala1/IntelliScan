"""Batch 4 — Agentic Workflows.

Read-only, bounded agent over retrieval + knowledge graph tools
(plan → tool → observe → synthesize). No shell, no arbitrary code,
no file modification.
"""

from .agent_engine import AgentEngine

__all__ = ["AgentEngine"]
