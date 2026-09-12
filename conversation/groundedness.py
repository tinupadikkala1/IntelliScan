"""Groundedness + sanitization guards (modern backend port).

Ported from New Folder `src/ai_file_explorer/core/guards.py`.
Dependency-free lexical overlap with synonym + bigram signals.
Used to score answers and decide CRAG/escalation without extra models.
"""

from __future__ import annotations

import re

_TOKEN = re.compile(r"[a-z0-9]+")

_STOPWORDS = frozenset({
    "the", "a", "an", "and", "or", "to", "of", "in", "on", "for",
    "is", "are", "you", "your", "please", "we", "it", "this", "that",
    "with", "can", "will", "not", "be", "have", "do",
})

_INJECTION = [
    re.compile(r"ignore (all|previous|above) instructions", re.I),
    re.compile(r"disregard (the )?(system|previous) (prompt|instructions)", re.I),
    re.compile(r"you are now", re.I),
    re.compile(r"reveal (your )?(system )?prompt", re.I),
]

_SYNONYM_GROUPS: list[set[str]] = [
    {"refund", "money", "back", "reimburse", "return"},
    {"password", "login", "signin", "sign", "in", "log", "authentication"},
    {"account", "profile", "user", "username"},
    {"email", "mail", "inbox", "gmail", "outlook"},
    {"delete", "remove", "close", "cancel", "terminate"},
    {"upgrade", "downgrade", "change", "switch", "plan"},
    {"error", "bug", "crash", "freeze", "fail", "broken"},
    {"help", "support", "assist", "guide", "tutorial"},
]

_SYN_MAP: dict[str, set[str]] = {}
for _g in _SYNONYM_GROUPS:
    for _w in _g:
        _SYN_MAP.setdefault(_w, set()).update(_g - {_w})


def sanitize(text: str) -> str:
    out = text or ""
    for pat in _INJECTION:
        out = pat.sub("[filtered]", out)
    return out


def _toks(s: str) -> list[str]:
    return _TOKEN.findall((s or "").lower())


def groundedness_score(answer: str, contexts: list, use_synonyms: bool = True) -> float:
    """Return lexical groundedness in [0,1] for answer vs context texts.

    `contexts` may be RetrievalResult/EvidenceChunk/str mixed.
    """
    if (answer or "").strip() == "I don't have enough information to answer that confidently.":
        return 1.0
    ans_list = [t for t in _toks(answer) if t not in _STOPWORDS]
    ans_set = set(ans_list)
    if not ans_set:
        return 0.0

    ctx_texts: list[str] = []
    for c in contexts or []:
        if isinstance(c, str):
            ctx_texts.append(c)
        else:
            ctx_texts.append(getattr(c, "text", "") or "")

    def _expand(s: set[str]) -> set[str]:
        if not use_synonyms:
            return s
        out = set(s)
        for t in s:
            out.update(_SYN_MAP.get(t, ()))
        return out

    ctx_set: set[str] = set()
    for t in ctx_texts:
        ctx_set.update(_toks(t))
    sup = _expand(ans_set) & _expand(ctx_set)
    uni = min(1.0, len(sup) / max(len(ans_set), 1))

    # bigram signal
    ab = set(zip(ans_list, ans_list[1:])) if len(ans_list) > 1 else set()
    cb: set[tuple[str, str]] = set()
    for t in ctx_texts:
        cl = [x for x in _toks(t) if x not in _STOPWORDS]
        cb.update(zip(cl, cl[1:]))
    bi = len(ab & cb) / max(len(ab), 1) if ab else 0.0
    return max(uni, bi)


def strip_think(text: str) -> str:
    """Remove <think>...</think> chain-of-thought leakage (deepseek-1.5B)."""
    if not text:
        return text
    out = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL | re.IGNORECASE)
    out = re.sub(r"</?think>", "", out, flags=re.IGNORECASE).strip().strip('"')
    return out or text
