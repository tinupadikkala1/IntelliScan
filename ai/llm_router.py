"""LLM router — task-aware model selection (modern backend port).

Ported from New Folder `src/ai_file_explorer/llm/llm_router.py`.
UI/UX unchanged: callers keep using `OllamaClient.generate()`, but now
pass `task_type` to pick the right lane without hardcoding model names.

Lanes (all non-8B, all already downloaded):
- qwen fast  (qwen-local:latest, 1.8B) — simple_qa, tagging, rewrite/hyde
- qwen main  (qwen3:latest, 4B)         — qa, summarization, classification
- deepseek   (deepseek-r1-1.5b:latest)  — reasoning, complex_qa, comparison
- vision     (moondream:latest)         — caption/VQA (routed by callers)
"""

from __future__ import annotations

from .config import (
    DEEPSEEK_MODEL_NAME,
    LIGHT_MODEL_NAME,
    LLM_MAIN_MODEL,
    MODEL_NAME,
)

TASK_MODEL_MAP: dict[str, str] = {
    # fast lane
    "simple_qa": "qwen_fast",
    "tagging": "qwen_fast",
    "metadata": "qwen_fast",
    "naming": "qwen_fast",
    "rewrite": "qwen_fast",
    "hyde": "qwen_fast",
    # main QA lane
    "qa": "qwen_main",
    "summarization": "qwen_main",
    "classification": "qwen_main",
    # reasoning lane (1.5B, replaces 8B)
    "reasoning": "deepseek",
    "complex_qa": "deepseek",
    "comparison": "deepseek",
    "analysis": "deepseek",
    "relationship": "deepseek",
    "workspace": "deepseek",
}

LANE_MODEL: dict[str, str] = {
    "qwen_fast": MODEL_NAME,
    "qwen_main": LLM_MAIN_MODEL,
    "deepseek": DEEPSEEK_MODEL_NAME,
    "light": LIGHT_MODEL_NAME or MODEL_NAME,
}


def route(task_type: str, default_lane: str = "qwen_main") -> str:
    """Return the model name for a task type.

    Args:
        task_type: e.g. "qa", "reasoning", "rewrite".
        default_lane: lane key used when task_type is unknown.

    Returns:
        Ollama model tag string.
    """
    lane = TASK_MODEL_MAP.get(task_type, default_lane)
    return LANE_MODEL.get(lane, LLM_MAIN_MODEL)


def lane_for(task_type: str) -> str:
    """Return the lane key (qwen_fast/qwen_main/deepseek) for a task."""
    return TASK_MODEL_MAP.get(task_type, "qwen_main")
