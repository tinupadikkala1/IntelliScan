"""Tool schemas — validated, structured inputs and outputs (Batch 4 §35).

Every tool declares its name, description, input fields and a ``validate``
helper so the planner's JSON output can be checked before execution.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional


class SchemaValidationError(ValueError):
    """Raised when tool input does not match its schema."""


@dataclass
class ToolInput:
    query: str = ""
    limit: int = 5
    scope: str = ""
    file_path: str = ""
    entity_name: str = ""
    evidence_ids: List[str] = field(default_factory=list)

    def validate(self) -> "ToolInput":
        if self.limit < 1 or self.limit > 20:
            raise SchemaValidationError("limit must be between 1 and 20")
        if self.scope and self.scope not in ("folder", "workspace", "file"):
            raise SchemaValidationError(f"unknown scope '{self.scope}'")
        for name in (self.query, self.file_path, self.entity_name):
            if len(name) > 2000:
                raise SchemaValidationError("input field too long")
        return self


@dataclass
class ToolSpec:
    name: str
    description: str
    parameters: Dict[str, dict]
    handler: Callable[[ToolInput], Any]
    timeout_seconds: float = 30.0
    policy: str = "read_only"

    def validate(self, raw: Dict[str, Any]) -> ToolInput:
        """Build a validated ToolInput from planner JSON."""
        allowed = {k for k in self.parameters}
        unknown = set(raw) - allowed
        if unknown:
            raise SchemaValidationError(
                f"unknown parameter(s) {sorted(unknown)} for tool '{self.name}'"
            )
        inp = ToolInput(
            query=str(raw.get("query", "") or ""),
            limit=int(raw.get("limit", 5) or 5),
            scope=str(raw.get("scope", "") or ""),
            file_path=str(raw.get("file_path", "") or ""),
            entity_name=str(raw.get("entity_name", "") or ""),
        )
        return inp.validate()


def parse_tool_call(raw: str) -> dict:
    """Parse a single tool-call JSON object, tolerating surrounding text."""
    if not raw or not raw.strip():
        raise SchemaValidationError("empty tool call")
    m = re.search(r"\{.*\}", raw, re.DOTALL)
    if not m:
        raise SchemaValidationError("no JSON object in tool call")
    import json
    data = json.loads(m.group(0))
    if not isinstance(data, dict):
        raise SchemaValidationError("tool call must be a JSON object")
    name = str(data.get("tool") or data.get("name") or "").strip()
    if not name:
        raise SchemaValidationError("tool call missing 'tool' name")
    params = data.get("arguments") or data.get("params") or data.get("input") or {}
    if not isinstance(params, dict):
        raise SchemaValidationError("tool arguments must be a JSON object")
    return {"tool": name, "arguments": params}
