"""Lightweight BM25 keyword retriever for hybrid search (modern backend port).

Ported from New Folder `src/ai_file_explorer/core/bm25.py`.
Stdlib only (math/log), no new deps, Linux+Windows safe.
Used to fuse with dense FAISS scores via RRF/weighted sum.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from typing import Sequence

_TOKEN = re.compile(r"[a-z0-9]+")


def _tokenize(text: str) -> list[str]:
    return _TOKEN.findall((text or "").lower())


def _idf(num_docs: int, doc_freq: int) -> float:
    return math.log(1.0 + (num_docs - doc_freq + 0.5) / (doc_freq + 0.5))


class BM25Retriever:
    """In-memory BM25 over evidence-chunk texts."""

    def __init__(self, k1: float = 1.5, b: float = 0.75) -> None:
        self._k1 = k1
        self._b = b
        self._docs: list[tuple[str, str]] = []  # (chunk_id, text)
        self._avg_dl = 0.0
        self._doc_freqs: dict[str, int] = {}
        self._term_counts: list[Counter[str]] = []

    def rebuild(self, items: Sequence[tuple[str, str]]) -> None:
        """Rebuild index from (chunk_id, text) pairs."""
        self._docs = list(items)
        self._doc_freqs = {}
        self._term_counts = []
        for _, text in self._docs:
            tokens = _tokenize(text)
            terms = set(tokens)
            self._term_counts.append(Counter(tokens))
            for t in terms:
                self._doc_freqs[t] = self._doc_freqs.get(t, 0) + 1
        total = sum(sum(c.values()) for c in self._term_counts)
        self._avg_dl = total / len(self._docs) if self._docs else 0.0

    def search(self, query: str, k: int = 10) -> list[tuple[str, float]]:
        """Return top-k (chunk_id, bm25_score) sorted descending."""
        qtok = _tokenize(query)
        if not self._docs or not qtok:
            return []
        qf = Counter(qtok)
        n = len(self._docs)
        scores = [0.0] * n
        for t, _ in qf.items():
            df = self._doc_freqs.get(t, 0)
            if df == 0:
                continue
            idf = _idf(n, df)
            for i in range(n):
                tf = self._term_counts[i].get(t, 0)
                if tf == 0:
                    continue
                dl = sum(self._term_counts[i].values())
                num = tf * (self._k1 + 1)
                den = tf + self._k1 * (1 - self._b + self._b * dl / max(self._avg_dl, 1e-9))
                scores[i] += idf * num / den
        ranked = sorted(enumerate(scores), key=lambda x: -x[1])[:k]
        out = []
        for idx, s in ranked:
            if s > 0:
                out.append((self._docs[idx][0], float(s)))
        return out
