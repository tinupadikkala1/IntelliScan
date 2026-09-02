"""Agent run state — tracks steps, observations and termination (Batch 4 §39).

States: idle → planning → running → finished | cancelled | error | timeout |
max_steps. ``cancelled`` is sticky: the engine checks it between every tool.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class AgentStep:
    tool: str
    arguments: dict
    summary: str
    ok: bool = True
    error: Optional[str] = None


@dataclass
class AgentState:
    request: str = ""
    status: str = "idle"  # idle|planning|running|finished|cancelled|error|timeout|max_steps
    steps: List[AgentStep] = field(default_factory=list)
    observations: List[dict] = field(default_factory=list)
    started_at: float = 0.0
    _cancelled: bool = False
    _cancel_lock: object = None

    def __post_init__(self):
        self._cancel_lock = __import__("threading").Lock()

    @property
    def cancelled(self) -> bool:
        return self._cancelled

    def cancel(self) -> None:
        with self._cancel_lock:
            self._cancelled = True
            if self.status in ("idle", "planning", "running"):
                self.status = "cancelled"

    def elapsed(self) -> float:
        if not self.started_at:
            return 0.0
        return time.time() - self.started_at

    def add_step(self, step: AgentStep) -> None:
        self.steps.append(step)

    def add_observation(self, obs: dict) -> None:
        self.observations.append(obs)
