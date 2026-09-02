"""Agent guardrails — bounded execution policy (Batch 4 §37).

Defaults: 8 steps, 90s wall-clock, 20 evidence items max, read-only tools.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List


@dataclass
class AgentPolicy:
    max_steps: int = 8
    max_time_seconds: float = 90.0
    max_evidence: int = 20
    read_only: bool = True
    allowed_tools: List[str] = field(default_factory=list)  # empty = all registered

    def allows(self, tool_name: str) -> bool:
        if self.read_only and not self.allowed_tools:
            return True
        return tool_name in self.allowed_tools
