"""Scope manager — resolves a chat scope into concrete retrieval constraints.

Scopes:
    file       — exactly one file
    folder     — a folder and all of its descendants (prefix match)
    workspace  — everything indexed

Used by ConversationManager to build the ``file_filter`` passed to
RetrievalEngine.retrieve() and to label the chat header.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class ChatScope:
    scope_type: str  # file | folder | workspace
    scope_path: str = ""

    @property
    def label(self) -> str:
        if self.scope_type == "file":
            return f"📄 {os.path.basename(self.scope_path) if self.scope_path else 'File'}"
        if self.scope_type == "folder":
            return f"📁 {self.scope_path}"
        return "🌐 Workspace"

    def to_dict(self) -> dict:
        return {"scope_type": self.scope_type, "scope_path": self.scope_path}


class ScopeManager:
    """Builds file filters and validates paths against a chat scope."""

    @staticmethod
    def path_in_scope(path: str, scope: ChatScope) -> bool:
        if scope.scope_type == "workspace":
            return True
        if scope.scope_type == "file":
            return os.path.abspath(path) == os.path.abspath(scope.scope_path)
        if scope.scope_type == "folder":
            base = os.path.abspath(scope.scope_path)
            return os.path.abspath(path).startswith(base + os.sep) or os.path.abspath(path) == base
        return True

    def file_filter(self, scope: ChatScope, evidence_map: Optional[Dict[str, object]] = None) -> Optional[List[str]]:
        """Return the file_path list for retrieval filtering, or None (all)."""
        if scope.scope_type == "workspace" or not scope.scope_path:
            return None
        if scope.scope_type == "file":
            return [os.path.abspath(scope.scope_path)]
        if scope.scope_type == "folder":
            if evidence_map is None:
                return None  # cannot enumerate without evidence map; caller must supply
            base = os.path.abspath(scope.scope_path)
            paths = {
                os.path.abspath(chunk.file_path)
                for chunk in evidence_map.values()
                if os.path.abspath(chunk.file_path).startswith(base + os.sep) or os.path.abspath(chunk.file_path) == base
            }

            if not paths and base in {os.path.abspath(c.file_path) for c in evidence_map.values()}:
                paths = {base}
            return sorted(paths)
        return None

    @staticmethod
    def filter_results(results, scope: ChatScope) -> list:
        """Post-filter retrieval results against a scope (defensive layer)."""
        if scope.scope_type == "workspace":
            return results
        return [r for r in results if ScopeManager.path_in_scope(r.file_path, scope)]
