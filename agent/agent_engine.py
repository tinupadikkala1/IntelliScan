"""Agent engine — bounded read-only agent loop (Batch 4 M10, §36-§39).

Pipeline: user request → planner → tool selection → tool execution →
observation → state update → next tool → final synthesis.

Guardrails enforced here:
- max step count (AgentPolicy.max_steps)
- wall-clock timeout (AgentPolicy.max_time_seconds)
- sticky cancellation checked between every tool
- read-only tools only
"""

from __future__ import annotations

import logging
import time
from typing import Callable, Optional

from .agent_state import AgentState, AgentStep
from .policies import AgentPolicy
from .planner import Planner
from .schemas import ToolInput
from .tool_executor import ToolExecutor
from .tool_registry import ToolRegistry

logger = logging.getLogger(__name__)

MAX_EVIDENCE_BUDGET = 20000  # chars of observations kept for synthesis


class AgentEngine:
    """Runs a bounded agent turn. All work happens in the caller's thread."""

    def __init__(self, retrieval=None, rag=None, graph_engine=None,
                 resources=None, registry: Optional[ToolRegistry] = None,
                 policy: Optional[AgentPolicy] = None,
                 on_step: Optional[Callable[[AgentStep], None]] = None) -> None:
        self._retrieval = retrieval
        self._rag = rag
        self._graph_engine = graph_engine
        self._resources = resources
        graph_query = None
        if graph_engine is not None:
            from graph.graph_query_service import GraphQueryService
            graph_query = GraphQueryService(graph_engine.store)
        db_store = getattr(retrieval, "_db_store", None) if retrieval is not None else None
        indexer = getattr(retrieval, "_indexer", None) if retrieval is not None else None
        self._registry = registry or ToolRegistry(
            retrieval=retrieval, rag=rag, db_store=db_store,
            graph_query=graph_query, indexer=indexer,
        )
        self._executor = ToolExecutor(self._registry)
        self._planner = Planner(rag, self._registry)
        self._policy = policy or AgentPolicy()
        self._on_step = on_step

    # ------------------------------------------------------------------ #
    @property
    def registry(self) -> ToolRegistry:
        return self._registry

    def run(self, request: str, cancel_event=None,
            on_status: Optional[Callable[[str], None]] = None) -> AgentState:
        """Execute one agent turn. Returns the final AgentState."""
        state = AgentState(request=request)
        state.status = "planning"
        state.started_at = time.time()
        if on_status:
            on_status("planning")

        try:
            used_tools: list = []
            step_count = 0
            final_answer = ""

            while True:
                if cancel_event is not None and cancel_event.is_set():
                    state.cancel()
                    return state
                if state.cancelled:
                    return state
                if state.elapsed() > self._policy.max_time_seconds:
                    state.status = "timeout"
                    return state
                if step_count >= self._policy.max_steps:
                    state.status = "max_steps"
                    break

                plan = self._planner.plan(request, state.observations, used_tools)
                tool = plan.get("tool", "")
                arguments = plan.get("arguments", {})

                if tool == "__final__":
                    final_answer = arguments.get("answer", "") if isinstance(arguments, dict) else ""
                    break

                if not self._policy.allows(tool):
                    state.add_step(AgentStep(
                        tool=tool, arguments=arguments,
                        summary=f"Tool '{tool}' blocked by policy", ok=False,
                        error="policy_blocked",
                    ))
                    step_count += 1
                    continue

                state.status = "running"
                if on_status:
                    on_status(f"tool:{tool}")

                step = self._executor.execute(tool, arguments, state)
                used_tools.append(tool)
                step_count += 1
                if self._on_step is not None:
                    self._on_step(step)

                if not step.ok and step.error == "cancelled":
                    return state
                if not step.ok:
                    # A failed tool should not loop forever: treat as an
                    # observation and let the planner decide (max_steps caps).
                    continue

                # Budget guard: cap observation bytes kept for synthesis.
                if len(state.observations) > 8:
                    state.observations = state.observations[-8:]

            if state.status in ("finished", "max_steps"):
                state.status = "finished"
                answer = self._planner.synthesize(request, state.observations)
                if final_answer and not answer.strip():
                    answer = final_answer
                state.add_step(AgentStep(
                    tool="__synthesis__", arguments={},
                    summary=answer or "Generated answer", ok=bool(answer),
                    error=None if answer else "empty_synthesis",
                ))
            return state
        except Exception as exc:  # noqa: BLE001 - keep the UI responsive
            logger.error("Agent run failed: %s", exc)
            state.status = "error"
            state.add_step(AgentStep(
                tool="__error__", arguments={}, summary=str(exc), ok=False,
                error=str(exc),
            ))
            return state

    def cancel(self, state: AgentState) -> None:
        """Request cancellation of a running agent turn (cooperative)."""
        state.cancel()
