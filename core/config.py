"""Application-wide configuration with typed accessors and persistence.

Settings are stored as JSON under ``config/settings.json``. Defaults are
deep-merged with anything loaded from disk so new keys are always present.
Changing a value emits ``changed`` so other subsystems can react.
"""

from __future__ import annotations

import json
import os
from typing import Any

from PySide6.QtCore import QObject, Signal

DEFAULTS: dict[str, Any] = {
    "general": {
        "startup_path": "~/Desktop",
        "single_click_open": False,
        "confirm_delete": True,
        "inactivity_reminder_enabled": True,
        "inactivity_threshold_days": 14,
    },

    "appearance": {
        "theme": "dark",
        "accent": "#3daee9",
    },
    "explorer": {
        "default_view": "list",
        "show_hidden": False,
        "thumbnails": True,
    },
    "database": {
        "path": "config/intellivault.db",
    },
    "performance": {
        "max_threads": min(2, os.cpu_count() or 2),
        "cache_size_mb": 128,
    },

    "plugins": {
        "enabled": [],
    },
    # Reserved for future AI batches (Batch 1-10). Inert in Foundation v1.0.
    "ai": {"enabled": False},
    "ocr": {"enabled": False},
    "models": {"enabled": False},
    "embeddings": {"enabled": False},
    "llm": {"enabled": False},

    # Batch 4: conversations, retrieval, graph, agent.
    "batch4": {
        "default_scope": "folder",
        "history_chars": 6000,
        "history_turns": 12,
        "top_k": 5,
        "threshold": 0.3,
        "graph_enabled": True,
        "agent_max_steps": 8,
        "agent_timeout_s": 300,
        "agent_enabled": True,
    },
    # Batch 5: intelligent organization & knowledge management.
    "batch5": {
        "empty_duplicates_visible": True,
        "near_duplicate_threshold": 0.90,
        "similar_file_threshold": 0.75,
        "max_related_results": 10,
        "classification_batch_size": 10,
        "suggestion_min_confidence": 0.5,
        "dashboard_refresh_auto": True,
    },
    # Batch 6: completing the five partial features.
    "batch6": {
        "caption_model": "moondream:latest",
        "caption_enabled": True,
        "duplicate_removal_min_confidence": 0.70,
        "folder_classification_recursive": True,
        "folder_organization_enabled": True,
        "trash_dir": "config/trash",
    },
    # Batch 7: image intelligence, metadata tools, timeline, folder
    # intelligence, comparison, safe renaming, image filtering.
    "batch7": {
        "image_quality_enabled": True,
        "object_detection_enabled": True,
        "object_detection_model": "moondream:latest",
        "object_detection_threshold": 0.40,
        "reverse_image_min_similarity": 0.55,
        "image_filter_threshold": 0.45,
        "folder_summary_enabled": True,
        "folder_summary_model": "qwen-local:latest",
        "rename_pattern": "{category}_{title}",
        "timeline_max_events": 2000,
    },
}


class Config(QObject):
    """Holds settings and persists them to disk."""

    changed = Signal(str)

    def __init__(self, path: str | None = None) -> None:
        super().__init__()
        if path is None:
            path = os.path.join(os.path.dirname(__file__), "..", "config", "settings.json")
        self._path = os.path.abspath(path)
        self._data: dict[str, Any] = {}
        self.load()

    # ------------------------------------------------------------------ #
    # Persistence
    # ------------------------------------------------------------------ #
    def load(self) -> None:
        self._data = json.loads(json.dumps(DEFAULTS))  # deep copy of defaults
        if os.path.exists(self._path):
            try:
                with open(self._path, "r", encoding="utf-8") as fh:
                    loaded = json.load(fh)
                self._deep_update(self._data, loaded)
            except Exception:
                # Corrupt config: fall back to defaults (kept above).
                pass
        self._ensure_file()

    def save(self) -> None:
        self._ensure_file()
        with open(self._path, "w", encoding="utf-8") as fh:
            json.dump(self._data, fh, indent=2)

    def _ensure_file(self) -> None:
        os.makedirs(os.path.dirname(self._path), exist_ok=True)
        if not os.path.exists(self._path):
            with open(self._path, "w", encoding="utf-8") as fh:
                json.dump(self._data, fh, indent=2)

    @staticmethod
    def _deep_update(base: dict, update: dict) -> None:
        for key, value in update.items():
            if isinstance(value, dict) and isinstance(base.get(key), dict):
                Config._deep_update(base[key], value)
            else:
                base[key] = value

    # ------------------------------------------------------------------ #
    # Accessors
    # ------------------------------------------------------------------ #
    def get(self, key: str, default: Any = None) -> Any:
        node: Any = self._data
        for part in key.split("."):
            if isinstance(node, dict) and part in node:
                node = node[part]
            else:
                return default
        return node

    def set(self, key: str, value: Any, save: bool = True) -> None:
        parts = key.split(".")
        node = self._data
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        node[parts[-1]] = value
        if save:
            self.save()
        self.changed.emit(key)

    @property
    def path(self) -> str:
        return self._path
