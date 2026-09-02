"""Natural-language search filter parser — B6-03 (#18).

Deterministic parsing of a controlled filter vocabulary out of a free-text
semantic search query. The remaining text is preserved as the *semantic*
query and passed to the existing RetrievalEngine unchanged — this module only
strips and structures explicit constraints.

    "PDF files about machine learning modified this month larger than 5 MB"
      → semantic_query="machine learning"
        filters: {"extensions": ["pdf"], "modified_after": <start of month>,
                  "size_min": 5 * 1024 * 1024}

Vocabulary (B6 §8.3): file type, extension, relative/absolute dates, size
ranges and scope. Anything not confidently parsed stays in the semantic
query (ambiguity rule B6 §8.7: never silently apply a wrong filter).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import List, Optional

# ---------------------------------------------------------------------- #
# Vocabulary tables
# ---------------------------------------------------------------------- #
# Modality / type words -> canonical type token.
_TYPE_WORDS = {
    "pdf": "pdf", "docx": "docx", "word": "docx", "pptx": "pptx",
    "powerpoint": "pptx", "presentation": "presentation", "slides": "presentation",
    "slide": "presentation", "xlsx": "xlsx", "xls": "xlsx",
    "spreadsheet": "spreadsheet", "sheet": "spreadsheet", "csv": "csv",
    "image": "image", "images": "image", "photo": "image", "photos": "image",
    "picture": "image", "pictures": "image", "screenshot": "image", "png": "image",
    "jpg": "image", "jpeg": "image",
    "audio": "audio", "recording": "audio", "recordings": "audio",
    "music": "audio", "podcast": "audio", "song": "audio", "mp3": "audio",
    "video": "video", "videos": "video", "clip": "video", "clips": "video",
    "footage": "video", "mp4": "video",
    "document": "document", "documents": "document", "text": "document", "text file": "document",
    "text files": "document", "txt": "document", "markdown": "document",
    "md": "document", "json": "json", "xml": "xml", "code": "code",
    "source": "code", "script": "code",
}

# Type token -> canonical extension(s) used for metadata filtering.
_TYPE_EXTENSIONS = {
    "pdf": [".pdf"],
    "docx": [".docx", ".doc"],
    "pptx": [".pptx", ".ppt"],
    "presentation": [".pptx", ".ppt", ".key"],
    "xlsx": [".xlsx", ".xls"],
    "spreadsheet": [".xlsx", ".xls", ".csv", ".tsv"],
    "csv": [".csv", ".tsv"],
    "image": [".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tiff", ".tif", ".gif", ".svg"],
    "audio": [".mp3", ".wav", ".flac", ".ogg", ".aac", ".m4a", ".wma", ".opus"],
    "video": [".mp4", ".mkv", ".mov", ".avi", ".webm", ".m4v", ".flv", ".wmv"],
    "document": [".pdf", ".docx", ".doc", ".txt", ".md", ".log", ".rtf", ".odt"],
    "json": [".json"],
    "xml": [".xml", ".xhtml"],
    "code": [".py", ".js", ".ts", ".java", ".cpp", ".c", ".h", ".rs", ".go",
             ".rb", ".php", ".sh", ".sql", ".html", ".css", ".yaml", ".yml",
             ".toml", ".ini", ".cfg"],
}

_SIZE_UNITS = {
    "b": 1, "byte": 1, "bytes": 1,
    "kb": 1024, "k": 1024, "kilobyte": 1024, "kilobytes": 1024,
    "mb": 1024 ** 2, "m": 1024 ** 2, "megabyte": 1024 ** 2, "megabytes": 1024 ** 2,
    "gb": 1024 ** 3, "g": 1024 ** 3, "gigabyte": 1024 ** 3, "gigabytes": 1024 ** 3,
}

_SCOPE_WORDS = {
    "folder": "folder", "this folder": "folder", "this directory": "folder",
    "workspace": "workspace", "this workspace": "workspace", "all files": "workspace",
}

# Phrases that separate the filter prefix from the semantic core. When a known
# filter phrase appears after a non-filter segment, the words before it are the
# semantic query. We keep this simple: filters are removed by regex, everything
# else survives as the semantic query.
_COPY_PATTERNS = [
    r"copy", r"copies", r"duplicate", r"duplicates", r"same content",
    r"identical", r"exact same",
]

# Generic instruction / filler words removed from the semantic query only after
# every structured filter has been extracted (B6 §8.7 — conservative).
_FILLER_WORDS = {
    "find", "search", "search for", "show", "get", "list", "give", "me",
    "any", "all", "the", "a", "an", "about", "for", "with", "in", "from",
    "that", "this", "these", "those", "which", "what", "please", "looking",
    "want", "need", "files", "file", "find all", "show me", "find me",
    "searching", "looking for", "that are", "that is", "which are",
}

# Generic type tokens subsumed by more specific ones (skip their extension map).
_GENERIC_TYPES = {
    "document": {"pdf", "docx", "pptx", "xlsx", "csv", "image", "audio",
                  "video", "json", "xml", "code", "presentation", "spreadsheet"},
    "presentation": {"pptx"},
    "spreadsheet": {"xlsx", "csv"},
}


@dataclass
class ParsedSearch:
    """Structured result of parsing a natural-language query (B6-03)."""

    original: str
    semantic_query: str = ""
    extensions: List[str] = field(default_factory=list)   # canonical .ext tokens
    types: List[str] = field(default_factory=list)        # canonical type tokens
    modified_after: Optional[datetime] = None             # inclusive start
    modified_before: Optional[datetime] = None            # inclusive end
    size_min: Optional[int] = None                        # bytes
    size_max: Optional[int] = None                        # bytes
    scope: str = "workspace"                              # workspace | folder
    near_duplicate: bool = False                          # user asked for copies/duplicates

    @property
    def has_filters(self) -> bool:
        return bool(
            self.extensions or self.types
            or self.modified_after or self.modified_before
            or self.size_min is not None or self.size_max is not None
        )

    def to_dict(self) -> dict:
        return {
            "extensions": self.extensions,
            "types": self.types,
            "modified_after": self.modified_after.isoformat() if self.modified_after else None,
            "modified_before": self.modified_before.isoformat() if self.modified_before else None,
            "size_min": self.size_min,
            "size_max": self.size_max,
            "scope": self.scope,
            "near_duplicate": self.near_duplicate,
        }


def describe_filters(parsed: ParsedSearch) -> List[str]:
    """Human-readable filter list for UI display (B6 §8.6)."""
    parts: List[str] = []
    if parsed.types:
        parts.append("Type: " + ", ".join(sorted(set(parsed.types))))
    if parsed.extensions:
        parts.append("Extension: " + ", ".join(sorted(set(parsed.extensions))))
    if parsed.modified_after and parsed.modified_before:
        parts.append(f"Modified: {parsed.modified_after:%Y-%m-%d} – {parsed.modified_before:%Y-%m-%d}")
    elif parsed.modified_after:
        parts.append(f"Modified after: {parsed.modified_after:%Y-%m-%d}")
    elif parsed.modified_before:
        parts.append(f"Modified before: {parsed.modified_before:%Y-%m-%d}")
    if parsed.size_min is not None and parsed.size_max is not None:
        parts.append(f"Size: {_human_size(parsed.size_min)} – {_human_size(parsed.size_max)}")
    elif parsed.size_min is not None:
        parts.append(f"Size: > {_human_size(parsed.size_min)}")
    elif parsed.size_max is not None:
        parts.append(f"Size: < {_human_size(parsed.size_max)}")
    if parsed.scope != "workspace":
        parts.append("Scope: this folder")
    if parsed.near_duplicate:
        parts.append("Intent: find duplicates/copies")
    return parts


def _human_size(num_bytes: int) -> str:
    if num_bytes >= 1024 ** 3:
        return f"{num_bytes / 1024 ** 3:.1f} GB"
    if num_bytes >= 1024 ** 2:
        return f"{num_bytes / 1024 ** 2:.1f} MB"
    if num_bytes >= 1024:
        return f"{num_bytes / 1024:.0f} KB"
    return f"{num_bytes} B"


# ---------------------------------------------------------------------- #
# Parsing helpers
# ---------------------------------------------------------------------- #
def _strip_fillers(text: str) -> str:
    """Remove filler/instruction words left over after filter extraction."""
    result = text
    for word in sorted(_FILLER_WORDS, key=len, reverse=True):
        if re.search(rf"\b{re.escape(word)}\b", result, flags=re.IGNORECASE):
            result = re.sub(rf"\b{re.escape(word)}\b", " ", result, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", result).strip()


def _strip_phrase(text: str, phrases: List[str]) -> str:
    """Remove filter phrases (case-insensitive, whole-word-ish) from text."""
    lowered = text
    result = text
    for phrase in phrases:
        # Escape regex chars in the phrase.
        pat = re.escape(phrase)
        result = re.sub(rf"\b{pat}\b", " ", result, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", result).strip()


def _parse_type_and_extension(query: str) -> tuple:
    """Extract type/ext filters; returns (remaining_text, extensions, types)."""
    words = query.lower()
    extensions: List[str] = []
    types: List[str] = []

    # Explicit extensions: ".pdf" or "pdf files" / "PDFs".
    for m in re.finditer(r"\.([a-z0-9]{1,5})\b", words):
        ext = "." + m.group(1)
        if ext in {".pdf", ".docx", ".doc", ".pptx", ".ppt", ".xlsx", ".xls",
                   ".csv", ".png", ".jpg", ".jpeg", ".webp", ".gif", ".mp3",
                   ".wav", ".mp4", ".mkv", ".txt", ".md", ".json", ".xml",
                   ".py", ".html", ".css"}:
            extensions.append(ext)

    remaining = query
    for token, type_token in _TYPE_WORDS.items():
        # Match singular and plural ("podcast" / "podcasts", "image" / "images").
        if re.search(rf"\b{re.escape(token)}s?\b", words):
            types.append(type_token)
            remaining = _strip_phrase(remaining, [token, token + "s"])

    if extensions:
        for ext in extensions:
            remaining = _strip_phrase(remaining, [ext.lstrip(".")])
            remaining = _strip_phrase(remaining, [ext])

    # "PDFs" → plural without space.
    for plural in ("pdfs", "docxs", "pptxs", "pngs", "jpgs", "mp3s", "mp4s"):
        if re.search(rf"\b{plural}\b", words):
            remaining = _strip_phrase(remaining, [plural])

    remaining = re.sub(r"\s+", " ", remaining).strip()
    remaining = remaining.strip(".,;:").strip()
    return remaining, extensions, list(dict.fromkeys(types))


def _parse_dates(query: str, today: Optional[date] = None) -> tuple:
    """Extract date constraints; returns (remaining, after, before)."""
    today = today or date.today()
    words = query.lower()
    remaining = query
    after = None
    before = None

    def _set_after(d: date) -> None:
        nonlocal after
        after = datetime(d.year, d.month, d.day) if after is None else max(after, datetime(d.year, d.month, d.day))

    def _set_before(d: date) -> None:
        nonlocal before
        before = datetime(d.year, d.month, d.day) if before is None else min(before, datetime(d.year, d.month, d.day))

    # Relative ranges.
    if re.search(r"\bthis week\b", words):
        _set_after(today - timedelta(days=today.weekday()))
        remaining = _strip_phrase(remaining, ["this week"])
    if re.search(r"\bthis month\b", words):
        _set_after(today.replace(day=1))
        remaining = _strip_phrase(remaining, ["this month"])
    if re.search(r"\bthis year\b", words):
        _set_after(today.replace(month=1, day=1))
        remaining = _strip_phrase(remaining, ["this year"])
    if re.search(r"\byesterday\b", words):
        _set_after(today - timedelta(days=1))
        _set_before(today - timedelta(days=1))
        remaining = _strip_phrase(remaining, ["yesterday"])
    if re.search(r"\btoday\b", words):
        _set_after(today)
        remaining = _strip_phrase(remaining, ["today"])
    if re.search(r"\blast week\b", words):
        start = today - timedelta(days=today.weekday() + 7)
        _set_after(start)
        _set_before(start + timedelta(days=6))
        remaining = _strip_phrase(remaining, ["last week"])
    if re.search(r"\blast month\b", words):
        first = today.replace(day=1)
        prev_last = first - timedelta(days=1)
        _set_after(prev_last.replace(day=1))
        _set_before(prev_last)
        remaining = _strip_phrase(remaining, ["last month"])

    # "modified"/"created" markers can stay — harmless. Remove the word
    # "modified"/"created"/"changed" so it doesn't pollute the semantic query.
    remaining = _strip_phrase(remaining, ["modified", "created", "changed", "updated"])

    # Absolute "after DATE" / "before DATE" (YYYY-MM-DD or Month DD, YYYY).
    for keyword, is_after in (("after", True), ("before", False), ("since", True), ("prior to", False)):
        pattern = (
            rf"\b{re.escape(keyword)}\s+"
            r"(\d{4}-\d{1,2}-\d{1,2}|"
            r"(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|"
            r"sep(?:tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\s+\d{1,2},?\s+\d{4})"
        )
        m = re.search(pattern, words)
        if m:
            try:
                d = _parse_absolute_date(m.group(1))
                if is_after:
                    _set_after(d)
                else:
                    _set_before(d)
                remaining = _strip_phrase(remaining, [keyword + " " + m.group(1)])
            except ValueError:
                pass  # unparsable → keep in semantic text

    remaining = re.sub(r"\s+", " ", remaining).strip()
    remaining = remaining.strip(".,;:").strip()
    return remaining, after, before


def _parse_absolute_date(text: str) -> date:
    text = text.strip()
    for fmt in ("%Y-%m-%d", "%Y-%m", "%B %d, %Y", "%b %d, %Y", "%B %d %Y", "%b %d %Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"Unparsable date: {text}")


def _parse_size(query: str) -> tuple:
    """Extract size constraints; returns (remaining, size_min, size_max)."""
    remaining = query
    size_min = None
    size_max = None

    def _to_bytes(value: float, unit: str) -> int:
        return int(value * _SIZE_UNITS.get(unit, 1024 ** 2))

    # between A unit and B unit
    m = re.search(
        r"\bbetween\s+(\d+(?:\.\d+)?)\s*([a-zA-Z]+)\s+and\s+(\d+(?:\.\d+)?)\s*([a-zA-Z]+)\b",
        query, flags=re.IGNORECASE,
    )
    if m:
        try:
            size_min = _to_bytes(float(m.group(1)), m.group(2).lower())
            size_max = _to_bytes(float(m.group(3)), m.group(4).lower())
            remaining = _strip_phrase(remaining, [f"between {m.group(1)} {m.group(2)} and {m.group(3)} {m.group(4)}"])
        except (ValueError, KeyError):
            pass

    # larger/greater/bigger/over than X unit
    m = re.search(
        r"\b(?:larger|bigger|greater|over|more than)\s+than\s+(\d+(?:\.\d+)?)\s*([a-zA-Z]+)\b",
        query, flags=re.IGNORECASE,
    )
    if m:
        try:
            size_min = _to_bytes(float(m.group(1)), m.group(2).lower())
            remaining = _strip_phrase(remaining, [f"{m.group(0)}"])
        except (ValueError, KeyError):
            pass

    # smaller/less/under/at most than X unit
    m = re.search(
        r"\b(?:smaller|less|under|at most)\s+than\s+(\d+(?:\.\d+)?)\s*([a-zA-Z]+)\b",
        query, flags=re.IGNORECASE,
    )
    if m:
        try:
            size_max = _to_bytes(float(m.group(1)), m.group(2).lower())
            remaining = _strip_phrase(remaining, [m.group(0)])
        except (ValueError, KeyError):
            pass

    remaining = re.sub(r"\s+", " ", remaining).strip()
    remaining = remaining.strip(".,;:").strip()
    return remaining, size_min, size_max


def _parse_scope(query: str) -> tuple:
    remaining = query
    scope = "workspace"
    for phrase, value in _SCOPE_WORDS.items():
        if re.search(rf"\b{re.escape(phrase)}\b", query.lower()):
            scope = value
            remaining = _strip_phrase(remaining, [phrase])
            break
    remaining = re.sub(r"\s+", " ", remaining).strip()
    remaining = remaining.strip(".,;:").strip()
    return remaining, scope


def _parse_near_duplicate(query: str) -> tuple:
    remaining = query
    found = False
    for phrase in _COPY_PATTERNS:
        if re.search(rf"\b{re.escape(phrase)}\b", query.lower()):
            found = True
            remaining = _strip_phrase(remaining, [phrase])
    remaining = re.sub(r"\s+", " ", remaining).strip()
    remaining = remaining.strip(".,;:").strip()
    return remaining, found


def parse_query(query: str) -> ParsedSearch:
    """Parse a free-text search query into a structured :class:`ParsedSearch`.

    Deterministic and conservative (B6 §8.7): unknown text stays in the
    semantic query; an unparsable constraint is never applied silently.
    """
    original = (query or "").strip()
    remaining = original

    remaining, extensions, types = _parse_type_and_extension(remaining)
    remaining, after, before = _parse_dates(remaining)
    remaining, size_min, size_max = _parse_size(remaining)
    remaining, scope = _parse_scope(remaining)
    remaining, near_dup = _parse_near_duplicate(remaining)

    # If the type token implies a modality with no explicit extension, keep
    # the canonical extensions for filtering (e.g. "images" → image exts).
    # Generic types subsumed by a more specific token are skipped so the
    # filter list stays tight ("PDF files" → .pdf, not every doc extension).
    for t in types:
        subsumed = _GENERIC_TYPES.get(t, set())
        if subsumed and any(s in types for s in subsumed):
            continue
        exts = _TYPE_EXTENSIONS.get(t)
        if exts:
            for e in exts:
                if e not in extensions:
                    extensions.append(e)

    semantic = _strip_fillers(remaining).strip()
    if not semantic:
        # Nothing confidently left — keep the trimmed original so the query
        # still embeds and the filter layer does the narrowing (B6 §8.7).
        semantic = original

    return ParsedSearch(
        original=original,
        semantic_query=semantic,
        extensions=extensions,
        types=types,
        modified_after=after,
        modified_before=before,
        size_min=size_min,
        size_max=size_max,
        scope=scope,
        near_duplicate=near_dup,
    )
