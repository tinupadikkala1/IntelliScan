"""Agent planner — asks the LLM to pick the next tool call.

Strict JSON-only output; no chain-of-thought is surfaced to the user.
If the LLM is unavailable or returns invalid JSON, the planner falls back
to a deterministic ``search`` step so the agent remains useful offline.
"""

from __future__ import annotations

import logging
from typing import List, Optional

from .schemas import parse_tool_call
from .tool_registry import ToolRegistry

logger = logging.getLogger(__name__)

_PLAN_PROMPT = (
    "You are a read-only research assistant over a local knowledge base. "
    "Decide the NEXT tool call to answer the user's request.\n\n"
    "TOOLS:\n{tools}\n\n"
    "TASK:\n{task}\n\n"
    "OBSERVATIONS SO FAR:\n{observations}\n\n"
    "Rules:\n"
    "- Reply ONLY with one JSON object: {{\"tool\": \"tool_name\", "
    "\"arguments\": {{...}}}}\n"
    "- Use arguments exactly as the tool schema expects.\n"
    "- Prefer the fewest tool calls needed. Use 'search' first for broad "
    "questions, 'query_knowledge_graph' for entity questions.\n"
    "- If you have enough information, reply with "
    "{{\"tool\": \"__final__\", \"arguments\": {{\"answer\": \"...\"}}}}\n"
    "- Never call a tool that mutates state.\n\n"
    "JSON:"
)


class Planner:
    """Selects the next tool call from the LLM, with fallback logic."""

    def __init__(self, rag, registry: ToolRegistry) -> None:
        self._rag = rag
        self._registry = registry

    def plan(self, task: str, observations: List[dict],
             used_tools: Optional[List[str]] = None) -> dict:
        """Return {'tool': name, 'arguments': {...}} or a final-answer dict."""
        used = used_tools or []
        tool_lines = "\n".join(
            f"- {s['name']}: {s['description']} "
            f"params={{{', '.join(s['parameters'])}}}"
            for s in self._registry.specs()
        )
        obs_text = "\n".join(
            f"{o.get('tool')}: {o.get('result', {})}" for o in observations[-5:]
        ) or "(none yet)"

        prompt = (
            _PLAN_PROMPT
            .replace("{tools}", tool_lines)
            .replace("{task}", task[:1500])
            .replace("{observations}", obs_text[:2000])
        )
        raw = self._generate(prompt)

        # Parse with fallback heuristics.
        if raw:
            try:
                call = parse_tool_call(raw)
                name = call["tool"]
                if name == "__final__":
                    return {"tool": "__final__",
                            "arguments": call.get("arguments", {})}
                if name in self._registry.names():
                    return call
                logger.debug("Planner returned unknown tool %s, falling back", name)
            except Exception as exc:
                logger.debug("Planner JSON parse failed: %s", exc)

        # Deterministic fallback: search (or final if we already searched).
        if "search" not in used:
            return {"tool": "search", "arguments": {"query": task, "limit": 5}}
        return {"tool": "__final__", "arguments": {
            "answer": "I gathered evidence but could not plan further tool "
                      "calls. Use the semantic search and Ask AI features to "
                      "explore the results."
        }}

    def synthesize(self, task: str, observations: List[dict]) -> str:
        """Generate the final grounded answer from all observations."""
        obs_text = "\n\n".join(
            f"Tool: {o.get('tool')}\n{o.get('result', {})}"
            for o in observations
        )
        prompt = (
            "You are a research assistant. Produce a concise, well-structured "
            "answer to the user's request using ONLY the tool observations "
            "below. Cite source file paths inline like [file.pdf]. If the "
            "observations lack the answer, say so.\n\n"
            f"REQUEST:\n{task}\n\n"
            f"OBSERVATIONS:\n{obs_text[:4000]}\n\n"
            "ANSWER:"
        )
        answer = self._generate(prompt)
        if answer:
            return answer.strip()
        # Fallback: plain aggregation of observations.
        lines = []
        for o in observations:
            result = o.get("result", {})
            if "answer" in result:
                lines.append(str(result["answer"]))
            elif "results" in result:
                lines.append(f"Found {result.get('total', len(result['results']))} results")
            elif "files" in result:
                lines.append(f"Related files: {', '.join(f['file_path'] for f in result['files'])}")
        return "\n".join(lines) or "No answer could be generated."

    # ------------------------------------------------------------------ #
    def _generate(self, prompt: str) -> str:
        if self._rag is None:
            return ""
        try:
            return (self._rag._generate(prompt) or "").strip()
        except Exception as exc:
            logger.debug("Planner LLM call failed: %s", exc)
            return ""
