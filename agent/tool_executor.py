"""Tool executor — runs a validated tool call with timeout + cancellation.

Execution runs synchronously inside the caller's worker thread; the timeout
is enforced by an interrupt-less deadline check the engine performs, plus a
documented per-tool timeout used for scheduling. Cancellation is cooperative:
the engine checks ``state.cancelled`` before and after each tool.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict

from .agent_state import AgentState, AgentStep
from .schemas import SchemaValidationError, ToolInput
from .tool_registry import ToolRegistry

logger = logging.getLogger(__name__)


class ToolExecutor:
    """Validates + invokes tools and records steps/observations."""

    def __init__(self, registry: ToolRegistry) -> None:
        self._registry = registry

    def execute(self, tool_name: str, arguments: Dict[str, Any],
                state: AgentState) -> AgentStep:
        """Validate, run and record one tool call.

        Returns an AgentStep; observations are appended to ``state``.
        """
        start = time.time()
        try:
            spec = self._registry.get(tool_name)
        except KeyError:
            step = AgentStep(tool=tool_name, arguments=arguments,
                             summary=f"Unknown tool '{tool_name}'", ok=False,
                             error=f"Unknown tool '{tool_name}'")
            state.add_step(step)
            return step

        # Validate the structured input.
        try:
            inp: ToolInput = spec.validate(arguments)
        except SchemaValidationError as exc:
            step = AgentStep(tool=tool_name, arguments=arguments,
                             summary=f"Invalid input: {exc}", ok=False,
                             error=str(exc))
            state.add_step(step)
            return step

        if state.cancelled:
            step = AgentStep(tool=tool_name, arguments=arguments,
                             summary="Cancelled before execution", ok=False,
                             error="cancelled")
            state.add_step(step)
            return step

        # Execute.
        try:
            result = spec.handler(inp)
        except Exception as exc:  # noqa: BLE001 - surface tool failures to the planner
            logger.debug("Tool %s failed: %s", tool_name, exc)
            step = AgentStep(tool=tool_name, arguments=arguments,
                             summary=f"Tool failed: {exc}", ok=False,
                             error=str(exc))
            state.add_step(step)
            return step

        elapsed = time.time() - start
        summary = self._summarize(tool_name, result)
        step = AgentStep(tool=tool_name, arguments=arguments,
                         summary=summary, ok=True)
        state.add_step(step)
        state.add_observation({"tool": tool_name, "result": result,
                               "elapsed_ms": round(elapsed * 1000, 1)})
        return step

    # ------------------------------------------------------------------ #
    @staticmethod
    def _summarize(tool_name: str, result: dict) -> str:
        if tool_name == "search":
            return f"Found {result.get('total', 0)} relevant results"
        if tool_name == "retrieve_evidence":
            return f"Loaded {result.get('total', 0)} evidence chunks"
        if tool_name == "list_related_files":
            return f"Found {len(result.get('files', []))} related files"
        if tool_name == "query_knowledge_graph":
            if result.get("entity"):
                return f"Queried entity '{result['entity']}' ({result.get('type')})"
            return "No graph entities matched"
        if tool_name == "open_evidence":
            return "Resolved evidence location"
        if tool_name == "summarize_evidence":
            return "Generated evidence summary"
        if tool_name == "compare_documents":
            return "Compared documents"
        if tool_name == "get_file_metadata":
            return "Loaded file metadata"
        return f"Executed {tool_name}"
