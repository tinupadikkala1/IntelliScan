"""Central path normalization (Windows + Linux safe).

All file identity comparisons MUST use these helpers — exact `==` and
`split('/')` caused re-index loops, orphan vectors, and broken citations
on Windows (case, junctions, 8.3) and symlinks.
"""

from __future__ import annotations

import os


def norm(p: str) -> str:
    """Normalized key: realpath + abspath + normcase."""
    try:
        return os.path.normcase(os.path.realpath(p or ""))
    except Exception:
        try:
            return os.path.normcase(os.path.abspath(p or ""))
        except Exception:
            return str(p or "")


def is_within(child: str, parent: str) -> bool:
    """True if normalized child == parent or lives under it."""
    try:
        c, b = norm(child), norm(parent)
        return c == b or c.startswith(b.rstrip(os.sep) + os.sep)
    except Exception:
        return False


def basename(p: str) -> str:
    """OS-safe basename (replaces split('/')[-1])."""
    try:
        return os.path.basename(p or "")
    except Exception:
        return str(p or "")
