"""Hybrid reranker: Ollama cross-encoder when configured, local overlap fallback.

Ported from New Folder `src/ai_file_explorer/retrieval/reranker.py`.
- When `rag.rerank.model` names an installed Ollama chat model (default
  qwen3-reranker 0.6B), score top candidates 0-10 and blend with local signal.
- Any failure falls back to local token-overlap — rerank never raises.
- CPU-safe: caps LLM-scored candidates at 8, ThreadPool max 3.
- Works with IntelliScan `RetrievalResult` (text/score) — UI unchanged.
"""

from __future__ import annotations

import logging
import re
from concurrent.futures import ThreadPoolExecutor
from typing import Any, List

logger = logging.getLogger(__name__)

_TOKEN = re.compile(r"[a-z0-9]+")


def _tokens(s: str) -> set[str]:
    return set(_TOKEN.findall((s or "").lower()))


def _local_score(query: str, text: str) -> float:
    qt, dt = _tokens(query), _tokens(text)
    if not qt or not dt:
        return 0.0
    inter = len(qt & dt)
    return inter / max(len(qt), 1)


def rerank_results(
    query: str,
    results: List[Any],
    top_n: int = 5,
    model: str = "ExpedientFalcon/qwen3-reranker:0.6b-q4_k_m",
    base_url: str = "http://localhost:11434",
    timeout: int = 60,
) -> List[Any]:
    """Rerank RetrievalResults in place (blended score), return top_n.

    Never raises — falls back to local overlap scoring.
    """
    if not results:
        return results
    # local baseline
    scored = []
    for r in results:
        txt = getattr(r, "text", "") or ""
        scored.append((r, _local_score(query, txt)))
    # try LLM boost for top candidates only
    try:
        import requests

        # quick availability check (model installed?)
        try:
            tags = requests.get(f"{base_url.rstrip('/')}/api/tags", timeout=5).json().get("models", [])
            names = [m.get("name", "") for m in tags]
            base = (model or "").split(":")[0]
            ready = any(n == model or n.startswith(base + ":") for n in names)
        except Exception:
            ready = False
        if ready and model and model != "local-token-overlap":
            cands = sorted(scored, key=lambda x: -getattr(x[0], "score", 0.0))[:8]

            def _score_one(item) -> float:
                r, _ = item
                txt = (getattr(r, "text", "") or "")[:800].replace("\n", " ")
                try:
                    resp = requests.post(
                        f"{base_url.rstrip('/')}/api/chat",
                        json={
                            "model": model,
                            "messages": [
                                {"role": "system", "content": "Score relevance 0-10. Reply with ONLY a number."},
                                {"role": "user", "content": f"QUERY: {query}\nPASSAGE: {txt}\nSCORE:"},
                            ],
                            "stream": False,
                            "options": {"temperature": 0.0},
                        },
                        timeout=timeout,
                    )
                    out = resp.json().get("message", {}).get("content", "0")
                    m = re.search(r"(\d+(?:\.\d+)?)", out or "0")
                    v = float(m.group(1)) if m else 0.0
                    return max(0.0, min(10.0, v)) / 10.0
                except Exception:
                    return 0.0

            with ThreadPoolExecutor(max_workers=3, thread_name_prefix="aife-rerank") as pool:
                llm_scores = list(pool.map(_score_one, cands))
            llm_map = {id(c[0]): s for c, s in zip(cands, llm_scores)}
            blended = []
            for r, local in scored:
                if id(r) in llm_map:
                    b = 0.5 * local + 0.5 * llm_map[id(r)]
                else:
                    b = local
                blended.append((r, b))
            # blend into vector score: keep original ranking signal too
            for r, b in blended:
                try:
                    orig = float(getattr(r, "score", 0.0) or 0.0)
                    r.score = float(0.6 * orig + 0.4 * b)
                except Exception:
                    pass
            scored = blended
    except Exception as exc:
        logger.debug("Rerank LLM failed, using local: %s", exc)
    # sort by (possibly blended) score
    try:
        results_sorted = sorted(results, key=lambda r: -float(getattr(r, "score", 0.0) or 0.0))
    except Exception:
        results_sorted = list(results)
    return results_sorted[:top_n] if top_n else results_sorted
