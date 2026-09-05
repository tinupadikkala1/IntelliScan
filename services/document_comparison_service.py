"""Document & File comparison service — B7-5 (#21).

Content-first binary comparison engine for ANY two files:
  - Documents (PDF, DOCX, TXT, MD, CSV, JSON, PPTX, etc.)
  - Images (JPG, PNG, WEBP, etc.)
  - Audio (MP3, WAV, FLAC, etc.)
  - Video (MP4, MKV, MOV, etc.)

Comparison pipeline:
  1. Content Extraction — uses indexed DB text first (from project startup
     indexing), falls back to live extraction via UniversalContentEngine.
  2. Structural Stats  — deterministic format/word/char/section analysis.
  3. Textual Diff      — difflib-based line/char diff on extracted content.
  4. Semantic Analysis  — LLM-powered content-vs-content comparison
                          (strictly File A vs File B, zero external files,
                          zero metadata/dates/sizes).

Key design constraints (per user requirements):
  - BINARY comparison: strictly File A vs File B. Never reference other files.
  - CONTENT-FIRST: compare meaning, text, objects, signage, dialogue, data.
  - NO metadata noise: no creation dates, modification times, file sizes.
  - CROSS-FORMAT: same content in different formats must be detected as similar.
  - ALL FILE TYPES: images, audio, video, documents, code, data files.
  - USE INDEXED DATA: leverage pre-indexed content from project startup.
"""

from __future__ import annotations

import difflib
import logging
import os
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from engines.config import COMPARE_EVIDENCE_TOP_K, COMPARE_MAX_TEXT_CHARS

logger = logging.getLogger(__name__)

_DOC_EXTS = {".pdf", ".docx", ".doc", ".txt", ".md", ".text", ".markdown", ".pptx", ".xlsx", ".csv", ".json", ".py", ".html", ".xml", ".log", ".cpp", ".java", ".c", ".h", ".rs", ".go", ".js", ".ts"}
_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif", ".tiff", ".svg"}
_AUDIO_EXTS = {".mp3", ".wav", ".flac", ".m4a", ".ogg", ".aac", ".wma"}
_VIDEO_EXTS = {".mp4", ".mkv", ".mov", ".avi", ".webm", ".flv"}

_SUPPORTED = _DOC_EXTS | _IMAGE_EXTS | _AUDIO_EXTS | _VIDEO_EXTS


def get_file_type_info(file_path: str) -> tuple[str, str]:
    """Return (media_category, friendly_type_name) for a given file path.

    Categories: 'Document', 'Image', 'Audio', 'Video', 'Dataset', 'Code'
    """
    ext = os.path.splitext(file_path)[1].lower()
    if ext == ".pdf":
        return ("Document", "PDF Document")
    elif ext in (".docx", ".doc", ".odt", ".rtf", ".pptx", ".ppt"):
        return ("Document", f"Office Document ({ext.upper().lstrip('.')})")
    elif ext in (".txt", ".md", ".text", ".markdown", ".log"):
        return ("Document", f"Text Document ({ext.upper().lstrip('.')})")
    elif ext in _IMAGE_EXTS:
        return ("Image", f"Image ({ext.upper().lstrip('.')})")
    elif ext in _AUDIO_EXTS:
        return ("Audio", f"Audio ({ext.upper().lstrip('.')})")
    elif ext in _VIDEO_EXTS:
        return ("Video", f"Video ({ext.upper().lstrip('.')})")
    elif ext in (".csv", ".tsv", ".json", ".xml", ".yaml", ".yml", ".xlsx", ".xls"):
        return ("Dataset", f"Structured Dataset ({ext.upper().lstrip('.')})")
    elif ext in (".py", ".js", ".ts", ".html", ".css", ".cpp", ".c", ".java", ".go", ".rs", ".h"):
        return ("Code", f"Source Code ({ext.upper().lstrip('.')})")
    return ("Document", f"File ({ext.upper().lstrip('.')})")


@dataclass
class StructuralStats:
    """Deterministic structural stats for one document or media file."""

    format: str = ""
    media_type: str = ""
    word_count: int = 0
    char_count: int = 0
    page_or_section_count: int = 0
    headings: List[str] = field(default_factory=list)
    table_count: int = 0
    file_size_bytes: int = 0

    def to_dict(self) -> dict:
        return {
            "format": self.format,
            "media_type": self.media_type,
            "word_count": self.word_count,
            "char_count": self.char_count,
            "page_or_section_count": self.page_or_section_count,
            "headings": self.headings[:10],
            "table_count": self.table_count,
            "file_size_bytes": self.file_size_bytes,
        }


@dataclass
class TextualDiff:
    """Deterministic diff summary between two documents."""

    added_chars: int = 0
    removed_chars: int = 0
    unchanged_ratio: float = 0.0
    added_lines: List[str] = field(default_factory=list)
    removed_lines: List[str] = field(default_factory=list)
    common_snippets: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "added_chars": self.added_chars,
            "removed_chars": self.removed_chars,
            "unchanged_ratio": round(self.unchanged_ratio, 4),
            "added_lines": self.added_lines[:20],
            "removed_lines": self.removed_lines[:20],
            "common_snippets": self.common_snippets[:10],
        }


@dataclass
class ComparisonResult:
    """Complete comparison of two documents."""

    file_a: str
    file_b: str
    structural_a: Optional[StructuralStats] = None
    structural_b: Optional[StructuralStats] = None
    textual: Optional[TextualDiff] = None
    semantic_summary: str = ""
    error: str = ""
    numerical_audit: List[dict] = field(default_factory=list)
    clean_text_a: str = ""
    clean_text_b: str = ""
    side_by_side_html: str = ""

    def to_dict(self) -> dict:
        return {
            "file_a": self.file_a,
            "file_b": self.file_b,
            "structural_a": self.structural_a.to_dict() if self.structural_a else None,
            "structural_b": self.structural_b.to_dict() if self.structural_b else None,
            "textual": self.textual.to_dict() if self.textual else None,
            "semantic_summary": self.semantic_summary,
            "error": self.error,
            "numerical_audit": self.numerical_audit,
            "side_by_side_html": self.side_by_side_html,
        }


class DocumentComparisonService:
    """Structural + textual + semantic multi-media file comparison.

    Supports cross-format content comparison for all file types.
    Uses indexed DB content when available, falls back to live extraction.
    """

    def __init__(self, rag_engine=None, retrieval_engine=None,
                 session_factory=None) -> None:
        self._rag = rag_engine
        self._retrieval = retrieval_engine
        self._session_factory = session_factory

    # ------------------------------------------------------------------ #
    def is_supported(self, file_path: str) -> bool:
        return os.path.splitext(file_path)[1].lower() in _SUPPORTED

    def compare(self, file_a: str, file_b: str) -> ComparisonResult:
        """Compare two files; returns a ComparisonResult (never raises)."""
        result = ComparisonResult(file_a=os.path.abspath(file_a),
                                  file_b=os.path.abspath(file_b))

        if not self.is_supported(file_a) or not self.is_supported(file_b):
            result.error = (
                f"Unsupported format for comparison. Supported extensions:\n"
                f"Documents: {', '.join(sorted(_DOC_EXTS))}\n"
                f"Images: {', '.join(sorted(_IMAGE_EXTS))}\n"
                f"Audio/Video: {', '.join(sorted(_AUDIO_EXTS | _VIDEO_EXTS))}"
            )
            return result
        if not os.path.isfile(file_a) or not os.path.isfile(file_b):
            result.error = "One or both files no longer exist on disk."
            return result

        # Step 1: Extract content (indexed DB first, then live fallback)
        text_a = self._extract_content(file_a)
        text_b = self._extract_content(file_b)
        if not text_a or not text_a.strip() or not text_b or not text_b.strip():
            result.error = "Could not extract content from one or both files."
            return result

        # Step 2: Clean content for comparison (remove noise/generic captions)
        clean_a = self._clean_content_text(text_a)
        clean_b = self._clean_content_text(text_b)

        # Summarize structured data datasets (CSV/JSON catalogs) to prevent LLM confusion
        clean_a = self._summarize_structured_data(file_a, clean_a)
        clean_b = self._summarize_structured_data(file_b, clean_b)

        result.clean_text_a = clean_a
        result.clean_text_b = clean_b

        # Step 3: Structural analysis
        result.structural_a = self._structural(file_a, clean_a)
        result.structural_b = self._structural(file_b, clean_b)

        # Step 4: Textual diff
        result.textual = self._textual_diff(clean_a, clean_b)

        # Step 5: Numerical & Entity Audit Table (deterministic ground truth)
        result.numerical_audit = self._extract_numerical_and_entity_audit(clean_a, clean_b)

        # Step 6: Side-by-side HTML diff table
        result.side_by_side_html = self._generate_html_diff(
            clean_a, clean_b, os.path.basename(file_a), os.path.basename(file_b)
        )

        # Step 7: Semantic content comparison (File A vs File B ONLY)
        raw_summary = self._semantic(file_a, file_b, clean_a,
                                     clean_b, result.textual)

        # Prepend a clear content similarity verdict at the very top
        verdict = self._generate_verdict_line(result.textual, clean_a, clean_b, file_a, file_b)
        result.semantic_summary = f"{verdict}\n\n{raw_summary}"
        return result

    # ------------------------------------------------------------------ #
    # CONTENT EXTRACTION — indexed DB first, live extraction fallback
    # ------------------------------------------------------------------ #
    def _extract_content(self, file_path: str) -> Optional[str]:
        """Extract content for a file.

        Priority:
          1. Indexed content from DB (already extracted at project startup).
          2. Live extraction via UniversalContentEngine.
          3. Minimal metadata fallback (last resort).
        """
        abs_path = os.path.abspath(file_path)

        # Try indexed content from DB first
        indexed_text = self._get_indexed_content(abs_path)
        if indexed_text and indexed_text.strip():
            logger.debug("Using indexed content for %s (%d chars)",
                         os.path.basename(file_path), len(indexed_text))
            return indexed_text[:COMPARE_MAX_TEXT_CHARS]

        # Fallback: live extraction
        return self._extract_text_live(file_path)

    def _get_indexed_content(self, abs_path: str) -> Optional[str]:
        """Fetch pre-indexed extracted content from the SQLite database."""
        if self._session_factory is None:
            return None
        try:
            # 1. Try indexed_files table (standard documents)
            from services.sqlite_indexer import IndexedFile
            with self._session_factory() as session:
                record = session.query(IndexedFile).filter_by(
                    absolute_path=abs_path
                ).first()
                if record and record.extracted_text and record.extracted_text.strip():
                    return record.extracted_text

            # 2. Try evidence table (images, audio, video, chunked documents)
            from database.models import Evidence
            with self._session_factory() as session:
                chunks = (
                    session.query(Evidence)
                    .filter_by(file_path=abs_path)
                    .order_by(Evidence.source_index)
                    .all()
                )
                if chunks:
                    text_parts = [c.text for c in chunks if c.text and c.text.strip()]
                    if text_parts:
                        return "\n\n".join(text_parts)
        except Exception as exc:
            logger.debug("DB content fetch failed for %s: %s", abs_path, exc)
        return None

    def _extract_text_live(self, file_path: str) -> Optional[str]:
        """Live content extraction via UniversalContentEngine."""
        try:
            from engines.content_engine import UniversalContentEngine
            engine = UniversalContentEngine()
            text = engine.extract_full_text(file_path)
            if text and text.strip():
                return text[:COMPARE_MAX_TEXT_CHARS]
            # Last resort: minimal content-type indicator
            ext = os.path.splitext(file_path)[1].lower()
            return f"[Empty content — format: {ext}]"
        except Exception as exc:
            logger.debug("Live extraction failed for %s: %s", file_path, exc)
            return None

    # ------------------------------------------------------------------ #
    # CONTENT CLEANING — remove noise, generic captions, metadata labels
    # ------------------------------------------------------------------ #
    def _clean_content_text(self, text: str) -> str:
        """Clean extracted content for comparison.

        Strips:
          - Generic hallucinated vision model captions
          - Metadata-only labels (file sizes, dates, filenames)
          - Source annotation brackets that add noise to diff
        """
        if not text:
            return ""

        lines = []
        for line in text.splitlines():
            stripped = line.strip()

            # Skip generic vision model filler captions
            lower = stripped.lower()
            if any(phrase in lower for phrase in (
                "vibrant street scene",
                "trees or grassy areas",
                "building with a red roof",
                "building with a blue roof",
                "two individuals walking on the sidewalk",
                "natural ambiance of the scene",
                "the dominant color is green",
            )):
                continue

            # Skip pure metadata lines (filename, size, date references)
            if stripped.startswith("[File Metadata]"):
                continue

            lines.append(line)

        cleaned = "\n".join(lines).strip()
        # Strip all source annotations in brackets like [OCR Text], [Image Caption], [Section 1], etc.
        cleaned = re.sub(
            r"\[(Section \d+|Page \d+|Slide \d+|Sheet \d+|OCR Text|Image Caption|Transcript|Keyframe \d+|File Metadata)\]\s*",
            "",
            cleaned,
            flags=re.IGNORECASE
        )
        return cleaned.strip() if cleaned.strip() else text

    # ------------------------------------------------------------------ #
    # STRUCTURAL ANALYSIS
    # ------------------------------------------------------------------ #
    def _structural(self, file_path: str, text: str) -> StructuralStats:
        ext = os.path.splitext(file_path)[1].lower()
        cat, type_name = get_file_type_info(file_path)
        stats = StructuralStats(format=ext.lstrip("."), media_type=type_name)
        stats.word_count = len(re.findall(r"\S+", text))
        stats.char_count = len(text)
        try:
            stats.file_size_bytes = os.path.getsize(file_path)
        except Exception:
            stats.file_size_bytes = 0

        if ext == ".pdf":
            stats.page_or_section_count = len(re.findall(r"\f", text)) + 1
        elif ext in _IMAGE_EXTS:
            stats.page_or_section_count = 1  # An image is a single visual asset
            stats.headings = []              # Images do not contain document headings
            return stats
        elif ext in _AUDIO_EXTS or ext in _VIDEO_EXTS:
            stats.page_or_section_count = 1  # Single media stream
            stats.headings = []
            return stats
        elif ext in (".csv", ".tsv", ".json"):
            stats.page_or_section_count = max(1, text.count("\n"))
            stats.headings = []
            return stats
        elif ext in _DOC_EXTS:
            stats.page_or_section_count = text.count("\n\n") + 1
        else:
            stats.page_or_section_count = max(1, text.count("\n") + 1)

        # Headings: markdown-style or short uppercase lines for documents/text
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            if re.match(r"^#{1,6}\s", line):
                stats.headings.append(re.sub(r"^#{1,6}\s*", "", line))
            elif len(line) <= 60 and line.isupper() and re.search(r"[A-Za-z]{3,}", line):
                stats.headings.append(line)
            if len(stats.headings) >= 10:
                break
        return stats

    # ------------------------------------------------------------------ #
    # TEXTUAL DIFF
    # ------------------------------------------------------------------ #
    def _textual_diff(self, text_a: str, text_b: str) -> TextualDiff:
        diff = TextualDiff()
        lines_a = text_a.splitlines()
        lines_b = text_b.splitlines()

        sm = difflib.SequenceMatcher(None, text_a, text_b)
        diff.unchanged_ratio = sm.ratio()
        diff.added_chars = max(0, len(text_b) - len(text_a))
        diff.removed_chars = max(0, len(text_a) - len(text_b))

        matcher = difflib.SequenceMatcher(None, lines_a, lines_b)
        for tag, i1, i2, j1, j2 in matcher.get_opcodes():
            if tag == "insert":
                diff.added_lines.extend(lines_b[j1:j2][:10])
            elif tag == "delete":
                diff.removed_lines.extend(lines_a[i1:i2][:10])
        diff.added_lines = [l[:200] for l in diff.added_lines[:20]]
        diff.removed_lines = [l[:200] for l in diff.removed_lines[:20]]

        # Common snippets (longest matching blocks)
        for m in matcher.get_matching_blocks():
            if m.size >= 2:
                snippet = "\n".join(lines_a[m.a:m.a + m.size]).strip()
                if snippet and len(snippet) >= 15:
                    diff.common_snippets.append(snippet[:300])
        diff.common_snippets = diff.common_snippets[:10]
        return diff

    # ------------------------------------------------------------------ #
    # SEMANTIC COMPARISON — LLM-powered, File A vs File B ONLY
    # ------------------------------------------------------------------ #
    def _semantic(
        self,
        file_a: str,
        file_b: str,
        text_a: str,
        text_b: str,
        diff: TextualDiff,
    ) -> str:
        """Content-first comparison between File A and File B ONLY.

        Rules enforced:
          - Strictly binary (File A vs File B), no external files.
          - Content and meaning only, no dates/sizes/metadata.
          - Accurately identifies each file's media type (e.g. Document vs Image).
        """
        fn_a = os.path.basename(file_a)
        fn_b = os.path.basename(file_b)
        cat_a, type_a = get_file_type_info(file_a)
        cat_b, type_b = get_file_type_info(file_b)

        # Determine content type context for better prompting
        type_hint = self._get_media_type_hint(file_a, file_b)

        prompt = (
            f"FILE A: {fn_a}\n"
            f"FILE A TYPE: {type_a}\n"
            f"--- FILE A CONTENT START ---\n{text_a[:4000]}\n--- FILE A CONTENT END ---\n\n"
            f"FILE B: {fn_b}\n"
            f"FILE B TYPE: {type_b}\n"
            f"--- FILE B CONTENT START ---\n{text_b[:4000]}\n--- FILE B CONTENT END ---\n\n"
            "You are a strict, objective content comparison engine. Your ONLY job is to compare "
            "the inner CONTENT and MEANING of File A vs File B.\n\n"
            "ABSOLUTE RULES (violations are errors):\n"
            "1. COMPARE ONLY FILE A AND FILE B. Never mention, list, or reference any other file.\n"
            f"2. RESPECT EACH FILE'S MEDIA TYPE: File A is a {type_a}, and File B is a {type_b}. "
            "NEVER call an image a PDF or document! Never call an audio file a document. "
            "Accurately acknowledge their actual media types (e.g. document vs image/graphic).\n"
            "3. DO NOT discuss filesystem metadata (creation dates, timestamps, disk byte sizes, or file system paths). "
            "Focus entirely on the information, text, visual OCR, and content payload.\n"
            "4. DO NOT confuse lists of other files, dates, sizes, or details mentioned *inside* the "
            "text content of the files with the properties of File A or File B themselves. For example, "
            "if File A contains a list of filenames or a table of file sizes, treat those purely as "
            "literal text entries in the file content, not as properties of File A.\n"
            "5. FOCUS 100% ON ACTUAL CONTENT: text passages, visible text/signage (OCR), "
            "spoken dialogue, objects depicted, data values, code logic, document clauses.\n"
            "6. NEVER use vague phrases like 'minor differences', 'slight variations', "
            "'similar structure'. Always quote or describe SPECIFIC content.\n"
            "7. For images: describe and compare the actual objects, diagrams, visible text/signage, "
            "people, colors, actions visible. Do NOT describe generic scenery filler.\n"
            "8. For audio/video: compare spoken words, topics discussed, sounds, "
            "visual scenes depicted.\n"
            "9. For documents/code: compare actual paragraphs, clauses, functions, "
            "data values, arguments made.\n"
            "10. DATA CATALOGS & SAME DATASET DIFFERENT FORMATS: If File A and File B contain the same list of files/records but stored in different formats (such as one CSV file and one JSON file), they represent the exact same content payload and meaning. Under Common Content, state that they contain the same set of database records/files. Under Differences, state that the only difference is the serialization structure (CSV vs JSON structure). Do NOT compare different records/rows against each other and report them as content differences.\n"
            f"11. {type_hint}\n\n"
            "FORMAT YOUR RESPONSE EXACTLY AS:\n\n"
            "### 🤝 Common Content & Shared Elements\n"
            "• [4-8 bullet points with SPECIFIC shared content: identical text, "
            "matching objects, same data values, common topics with exact quotes]\n\n"
            "### ⚡ Content Differences & Variances\n"
            "• [4-8 bullet points with SPECIFIC differences: exact text that differs, "
            "objects present in one but not the other, different data values, "
            "contrasting arguments with exact quotes]\n"
        )

        if self._rag is not None:
            try:
                res = (self._rag._generate(prompt) or "").strip()
                if res:
                    return res
            except Exception as exc:
                logger.debug("Semantic comparison prompt failed: %s", exc)

        # Fallback: deterministic content-based bullet points
        return self._generate_fallback_summary(file_a, file_b, text_a,
                                                text_b, diff)

    def _get_media_type_hint(self, file_a: str, file_b: str) -> str:
        """Generate a type-aware hint for the LLM prompt."""
        fn_a = os.path.basename(file_a)
        fn_b = os.path.basename(file_b)
        cat_a, type_a = get_file_type_info(file_a)
        cat_b, type_b = get_file_type_info(file_b)

        # Structured data catalogs
        if cat_a == "Dataset" or cat_b == "Dataset":
            return (
                "One or both files contain structured data (CSV, JSON, XML, YAML, etc.) representing a dataset, database dump, or log catalog. "
                "Check if they contain the same set of records/files. If they represent the same dataset stored in different formats (e.g., File A is a CSV and File B is a JSON of the same metadata), "
                "they are identical in content meaning. Highlight this matching data content under Common Content, and explain that the only variance is the structural layout (CSV columns vs JSON keys)."
            )

        # Cross-modal: Document vs Image (e.g. PDF vs PNG/JPG)
        if (cat_a == "Document" and cat_b == "Image") or (cat_a == "Image" and cat_b == "Document"):
            doc_file = fn_a if cat_a == "Document" else fn_b
            doc_type = type_a if cat_a == "Document" else type_b
            img_file = fn_b if cat_b == "Image" else fn_a
            img_type = type_b if cat_b == "Image" else type_a
            return (
                f"CRITICAL CROSS-FORMAT COMPARISON (Document vs Image):\n"
                f"• One file ('{doc_file}') is a {doc_type}.\n"
                f"• The other file ('{img_file}') is an {img_type} (graphic / photo / scan / diagram) whose content was extracted from visual elements and OCR text. It is NOT a PDF or text document!\n"
                f"• DO NOT refer to '{img_file}' as a PDF, document, or written article. Refer to it as an image, graphic, or diagram.\n"
                f"• Compare whether the image visually illustrates, diagrams, quotes, or shares data with the document, or if they represent different subjects."
            )

        # Cross-modal: Document vs Audio/Video
        if (cat_a == "Document" and cat_b in ("Audio", "Video")) or (cat_b == "Document" and cat_a in ("Audio", "Video")):
            doc_file = fn_a if cat_a == "Document" else fn_b
            med_file = fn_b if cat_b in ("Audio", "Video") else fn_a
            med_type = type_b if cat_b in ("Audio", "Video") else type_a
            return (
                f"CRITICAL CROSS-FORMAT COMPARISON (Document vs {med_type}):\n"
                f"• One file ('{doc_file}') is a written document.\n"
                f"• The other file ('{med_file}') is a {med_type} whose content comes from spoken audio / video frames. It is NOT a written document or PDF.\n"
                f"• Compare whether the spoken or visual media covers the same topics, agreements, or claims as the document."
            )

        if cat_a == cat_b:
            if cat_a == "Image":
                return ("Both files are images. Compare: visible objects, text on signs/labels, "
                        "people, colors, diagrams, background elements, and any readable text (OCR).")
            elif cat_a == "Audio":
                return ("Both files are audio. Compare: spoken words/dialogue, topics, "
                        "speakers, music elements, and sound characteristics.")
            elif cat_a == "Video":
                return ("Both files are videos. Compare: visual scenes, spoken dialogue, "
                        "on-screen text, objects, people, and actions depicted.")
            else:
                return ("Both files are documents. Compare: paragraphs, headings, data, "
                        "code logic, arguments, and factual claims.")
        else:
            return (f"File A is a {type_a} and File B is a {type_b} (different media formats). "
                    "Compare their content across these distinct media types without confusing their formats.")

    # ------------------------------------------------------------------ #
    # FALLBACK SUMMARY — deterministic, no LLM needed
    # ------------------------------------------------------------------ #
    def _generate_fallback_summary(
        self,
        file_a: str,
        file_b: str,
        text_a: str,
        text_b: str,
        diff: TextualDiff,
    ) -> str:
        """Generate content-focused bullet points comparing ONLY File A and File B."""
        fn_a = os.path.basename(file_a)
        fn_b = os.path.basename(file_b)
        cat_a, type_a = get_file_type_info(file_a)
        cat_b, type_b = get_file_type_info(file_b)
        sim_pct = round(diff.unchanged_ratio * 100, 1)

        common_bullets = []
        if cat_a != cat_b:
            common_bullets.append(
                f"• **Format Distinction:** File A is a **{type_a}**, while File B is an **{type_b}**. "
                "Content is evaluated across media representations."
            )

        # Real shared content snippets from difflib
        if diff.common_snippets:
            for i, snip in enumerate(diff.common_snippets[:5], 1):
                clean = snip.replace("\n", " ").strip()
                if len(clean) > 150:
                    clean = clean[:150] + "…"
                common_bullets.append(
                    f"• **Shared Content #{i}:** \"{clean}\"")

        # Exact matching lines between the two files
        content_lines_a = [l.strip() for l in text_a.splitlines()
                           if l.strip() and not l.strip().startswith("[")]
        content_lines_b = [l.strip() for l in text_b.splitlines()
                           if l.strip() and not l.strip().startswith("[")]
        matching_lines = [l for l in content_lines_a if l in content_lines_b]
        for line in matching_lines[:3]:
            if len(line) > 150:
                line = line[:150] + "…"
            common_bullets.append(f"• **Identical Content Line:** \"{line}\"")

        if not common_bullets:
            if sim_pct > 80:
                common_bullets.append(
                    f"• **High Content Overlap:** `{fn_a}` and `{fn_b}` share "
                    f"approximately {sim_pct}% content similarity, indicating "
                    "substantially matching content payload.")
            elif sim_pct > 40:
                common_bullets.append(
                    f"• **Partial Content Overlap:** `{fn_a}` and `{fn_b}` share "
                    f"approximately {sim_pct}% content similarity.")
            else:
                common_bullets.append(
                    f"• **Low Content Overlap:** `{fn_a}` and `{fn_b}` share only "
                    f"{sim_pct}% content similarity, indicating largely different content.")

        # Differences
        diff_bullets = []
        if diff.added_lines:
            for line in diff.added_lines[:4]:
                clean = line.replace("\n", " ").strip()
                if len(clean) > 150:
                    clean = clean[:150] + "…"
                diff_bullets.append(
                    f"• **In `{fn_b}` only:** \"{clean}\"")
        if diff.removed_lines:
            for line in diff.removed_lines[:4]:
                clean = line.replace("\n", " ").strip()
                if len(clean) > 150:
                    clean = clean[:150] + "…"
                diff_bullets.append(
                    f"• **In `{fn_a}` only:** \"{clean}\"")

        if not diff_bullets:
            if sim_pct >= 99.0:
                diff_bullets.append(
                    f"• **Identical Content:** `{fn_a}` and `{fn_b}` contain "
                    "matching content with no detected differences.")
            else:
                diff_bullets.append(
                    f"• **Content Variance:** The extracted content of `{fn_a}` "
                    f"and `{fn_b}` differs in wording and structure.")

        common_section = "\n".join(common_bullets)
        diff_section = "\n".join(diff_bullets)

        return (
            f"### 🤝 Common Content & Shared Elements\n{common_section}\n\n"
            f"### ⚡ Content Differences & Variances\n{diff_section}"
        )

    def _summarize_structured_data(self, file_path: str, text: str) -> str:
        """Parse structured data catalogs and return a clean, descriptive summary.

        This prevents local LLMs from confusing raw database rows/records with the
        properties of the files themselves, or mismatching records.
        """
        ext = os.path.splitext(file_path)[1].lower()
        if not text:
            return text

        # Clean annotations (e.g. [Section 1], [Page 1]) added by content extractor
        clean_text = re.sub(r"\[Section \d+\]\s*", "", text).strip()
        clean_text = re.sub(r"\[Page \d+\]\s*", "", clean_text).strip()

        if ext in (".csv", ".tsv"):
            try:
                import csv
                import io
                f = io.StringIO(clean_text)
                reader = csv.reader(f, delimiter=',' if ext == '.csv' else '\t')
                rows = list(reader)
                if rows:
                    headers = rows[0]
                    record_count = len(rows) - 1
                    summary = (
                        f"[Structured CSV Dataset]\n"
                        f"Format: {ext.upper()} file representing tabular records.\n"
                        f"Schema/Columns ({len(headers)} fields): {', '.join(headers)}\n"
                        f"Total Records: {record_count} rows\n"
                    )
                    if record_count > 0:
                        summary += "Sample Records:\n"
                        for idx, row in enumerate(rows[1:3], 1):
                            summary += f"  - Record #{idx}: " + ", ".join(f"{h}: {val}" for h, val in zip(headers, row) if val.strip())[:400] + "\n"
                    return summary
            except Exception:
                pass

        elif ext == ".json":
            try:
                import json
                data = json.loads(clean_text)
                items = []
                if isinstance(data, list):
                    items = data
                elif isinstance(data, dict):
                    for key, val in data.items():
                        if isinstance(val, list):
                            items = val
                            break
                    if not items:
                        keys = list(data.keys())
                        summary = (
                            f"[Structured JSON Object]\n"
                            f"Format: JSON document.\n"
                            f"Top-Level Keys ({len(keys)}): {', '.join(keys)}\n"
                        )
                        return summary

                if items:
                    record_count = len(items)
                    common_keys = []
                    if isinstance(items[0], dict):
                        common_keys = list(items[0].keys())

                    summary = (
                        f"[Structured JSON Array]\n"
                        f"Format: JSON representation of a database/list catalog.\n"
                        f"Total Records: {record_count} items\n"
                    )
                    if common_keys:
                        summary += f"Attributes per Record ({len(common_keys)} fields): {', '.join(common_keys)}\n"
                    summary += "Sample Records:\n"
                    for idx, item in enumerate(items[:2], 1):
                        if isinstance(item, dict):
                            summary += f"  - Record #{idx}: " + ", ".join(f"{k}: {val}" for k, val in item.items() if str(val).strip())[:400] + "\n"
                    return summary
            except Exception:
                # Regex fallback for broken JSON text chunk sections
                paths_count = len(re.findall(r'"path"\s*:\s*"', clean_text))
                if paths_count > 0:
                    summary = (
                        f"[Structured JSON Array]\n"
                        f"Format: JSON representation of a database/list catalog.\n"
                        f"Total Records: {paths_count} items\n"
                    )
                    return summary
                pass

        return text

    def _generate_verdict_line(self, diff: TextualDiff, clean_a: str, clean_b: str, file_a: str, file_b: str) -> str:
        """Deterministically determine and format a high-level content similarity verdict."""
        ext_a = os.path.splitext(file_a)[1].lower()
        ext_b = os.path.splitext(file_b)[1].lower()

        # Check if both are structured data catalogs representing same dataset
        is_data_a = ext_a in (".csv", ".tsv", ".json")
        is_data_b = ext_b in (".csv", ".tsv", ".json")

        if is_data_a and is_data_b:
            match_a = re.search(r"Total Records:\s+(\d+)", clean_a)
            match_b = re.search(r"Total Records:\s+(\d+)", clean_b)
            if match_a and match_b:
                count_a = int(match_a.group(1))
                count_b = int(match_b.group(1))
                if abs(count_a - count_b) <= max(1, int(count_a * 0.05)):
                    return "**Content Verdict: The two compared files are almost similar in content (same database catalog stored in different structures).**"

        ratio = diff.unchanged_ratio
        cat_a, type_a = get_file_type_info(file_a)
        cat_b, type_b = get_file_type_info(file_b)
        is_media_a = ext_a in _IMAGE_EXTS | _AUDIO_EXTS | _VIDEO_EXTS
        is_media_b = ext_b in _IMAGE_EXTS | _AUDIO_EXTS | _VIDEO_EXTS
        is_media = is_media_a or is_media_b

        if cat_a != cat_b:
            if ratio >= 0.70:
                sim_text = "almost similar in content"
            elif ratio >= 0.25:
                sim_text = "partially similar in content"
            else:
                sim_text = "contain entirely different contents"
            return f"**Content Verdict: Cross-format comparison between {type_a} and {type_b}. The two files are {sim_text}.**"

        if is_media:
            # Media files have higher baseline vocabulary overlap due to AI descriptions
            if ratio >= 0.85:
                return "**Content Verdict: The two compared files are almost similar in content.**"
            elif ratio >= 0.40:
                return "**Content Verdict: The two compared files are partially similar in content.**"
            else:
                return "**Content Verdict: The two compared files contain entirely different contents.**"
        else:
            # Documents / code
            if ratio >= 0.99:
                return "**Content Verdict: The two compared files have identical contents.**"
            elif ratio >= 0.70:
                return "**Content Verdict: The two compared files are almost similar in content.**"
            elif ratio >= 0.25:
                return "**Content Verdict: The two compared files are partially similar in content.**"
            else:
                return "**Content Verdict: The two compared files contain entirely different contents.**"

    # ============ PHASE 2.3: DOCUMENT COMPARISON ENHANCEMENTS ============
    
    def textual_diff(self, text1: str, text2: str) -> Dict:
        """METHOD 1: Line-by-line textual comparison using difflib."""
        lines1 = text1.split('\n')
        lines2 = text2.split('\n')
        
        matcher = difflib.SequenceMatcher(None, lines1, lines2)
        
        similarities = []
        differences = []
        
        for tag, i1, i2, j1, j2 in matcher.get_opcodes():
            if tag == 'equal':
                similarities.extend(lines1[i1:i2])
            else:
                differences.append({
                    'type': tag,
                    'original': lines1[i1:i2],
                    'modified': lines2[j1:j2]
                })
        
        return {
            'method': 'Textual (Line-by-Line)',
            'similarities': similarities,
            'differences': differences,
            'similarity_ratio': matcher.ratio(),
            'matching_lines': len([l for l in matcher.get_matching_blocks() if l.size > 0])
        }
    
    def structural_analysis(self, content1, content2) -> Dict:
        """METHOD 2: Structural analysis comparing length, sections, formatting."""
        text1 = getattr(content1, 'text', str(content1))
        text2 = getattr(content2, 'text', str(content2))
        
        length_diff = len(text2) - len(text1)
        word_count1 = len(text1.split())
        word_count2 = len(text2.split())
        word_diff = word_count2 - word_count1
        
        def extract_sections(text):
            sections = []
            for line in text.split('\n'):
                if line.startswith('#') or line.startswith('===') or line.startswith('---'):
                    sections.append(line.strip())
            return sections
        
        sections1 = extract_sections(text1)
        sections2 = extract_sections(text2)
        
        missing_sections = set(sections1) - set(sections2)
        new_sections = set(sections2) - set(sections1)
        
        return {
            'method': 'Structural Analysis',
            'length_diff': length_diff,
            'word_count_diff': word_diff,
            'sections_1': len(sections1),
            'sections_2': len(sections2),
            'missing_sections': list(missing_sections),
            'new_sections': list(new_sections),
            'similarity_ratio': (len(set(sections1) & set(sections2)) / max(len(sections1), len(sections2))) if max(len(sections1), len(sections2)) > 0 else 0
        }
    
    def semantic_diff(self, text1: str, text2: str) -> Dict:
        """METHOD 3: Semantic comparison using embeddings."""
        try:
            if not hasattr(self, 'embedding_engine') or self.embedding_engine is None:
                return {
                    'method': 'Semantic Analysis',
                    'status': 'Embedding engine not available',
                    'similarity': 'unknown'
                }
            
            def chunk_text(text, chunk_size=100):
                words = text.split()
                chunks = []
                for i in range(0, len(words), chunk_size):
                    chunk = ' '.join(words[i:i+chunk_size])
                    if chunk.strip():
                        chunks.append(chunk)
                return chunks
            
            chunks1 = chunk_text(text1)
            chunks2 = chunk_text(text2)
            
            embeddings1 = [self.embedding_engine.embed_text(c) for c in chunks1]
            embeddings2 = [self.embedding_engine.embed_text(c) for c in chunks2]
            
            def cosine_similarity(v1, v2):
                try:
                    import numpy as np
                    v1 = np.array(v1, dtype=np.float32)
                    v2 = np.array(v2, dtype=np.float32)
                    norm1 = np.linalg.norm(v1)
                    norm2 = np.linalg.norm(v2)
                    if norm1 == 0 or norm2 == 0:
                        return 0.0
                    return float(np.dot(v1, v2) / (norm1 * norm2))
                except:
                    return 0.0
            
            similar_chunks = []
            for e1, c1 in zip(embeddings1, chunks1):
                for e2, c2 in zip(embeddings2, chunks2):
                    sim = cosine_similarity(e1, e2)
                    if sim > 0.7:
                        similar_chunks.append({
                            'chunk1': c1[:50] + '...',
                            'chunk2': c2[:50] + '...',
                            'similarity': round(sim, 3)
                        })
            
            return {
                'method': 'Semantic Analysis',
                'total_chunks_1': len(chunks1),
                'total_chunks_2': len(chunks2),
                'similar_chunks': len(similar_chunks),
                'overall_semantic_similarity': sum(s['similarity'] for s in similar_chunks) / max(len(similar_chunks), 1) if similar_chunks else 0,
                'details': similar_chunks[:5]
            }
        
        except Exception as e:
            return {
                'method': 'Semantic Analysis',
                'status': f'Error: {str(e)}',
                'similarity': 'error'
            }
    
    def consolidate_results(self, textual_result: Dict, structural_result: Dict, 
                           semantic_result: Dict) -> Dict:
        """Consolidate all 3 methods with weighted scoring."""
        textual_conf = textual_result.get('similarity_ratio', 0)
        structural_conf = structural_result.get('similarity_ratio', 0) if 'similarity_ratio' in structural_result else 0.5
        semantic_conf = semantic_result.get('overall_semantic_similarity', 0.5) if 'overall_semantic_similarity' in semantic_result else 0.5
        
        overall_confidence = (
            textual_conf * 0.4 +
            structural_conf * 0.3 +
            semantic_conf * 0.3
        )
        
        methods_agree = abs(textual_conf - structural_conf) < 0.2
        
        return {
            'overall_similarity': round(overall_confidence, 3),
            'methods': {
                'textual': textual_result,
                'structural': structural_result,
                'semantic': semantic_result
            },
            'methods_agree': methods_agree,
            'verdict': 'Similar' if overall_confidence > 0.6 else 'Different',
            'confidence': 'High' if overall_confidence > 0.75 else 'Medium' if overall_confidence > 0.5 else 'Low'
        }

    # ------------------------------------------------------------------ #
    # DETERMINISTIC NUMERICAL & ENTITY AUDIT
    # ------------------------------------------------------------------ #
    def _extract_numerical_and_entity_audit(self, text_a: str, text_b: str) -> List[dict]:
        """Extract deterministic numerical, currency, date, and ID audit comparisons."""
        import re

        def _find_items(text):
            items = []
            # Currency / Monetary amounts
            for m in re.finditer(r"[$€£₹]\s*\d+(?:,\d{3})*(?:\.\d{1,2})?|\b\d+(?:,\d{3})*(?:\.\d{1,2})?\s*(?:USD|EUR|INR|GBP|dollars)\b", text, re.I):
                items.append(("Currency / Amount", m.group(0).strip()))
            # Dates
            for m in re.finditer(r"\b(?:\d{4}[-/]\d{1,2}[-/]\d{1,2}|\d{1,2}[-/]\d{1,2}[-/]\d{2,4}|(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{1,2}(?:,\s*\d{4})?)\b", text, re.I):
                items.append(("Date", m.group(0).strip()))
            # Percentages
            for m in re.finditer(r"\b\d+(?:\.\d+)?%", text):
                items.append(("Percentage", m.group(0).strip()))
            # Identifiers / Invoices
            for m in re.finditer(r"\b(?:Invoice|INV|ID|Order|PO|Account|Ref)[#:\s]+[A-Za-z0-9_-]+", text, re.I):
                items.append(("Identifier", m.group(0).strip()))
            return items

        items_a = _find_items(text_a)
        items_b = _find_items(text_b)

        val_map_a = {}
        for cat, val in items_a:
            val_map_a.setdefault(cat, []).append(val)

        val_map_b = {}
        for cat, val in items_b:
            val_map_b.setdefault(cat, []).append(val)

        all_cats = set(val_map_a.keys()) | set(val_map_b.keys())
        audit = []
        for cat in sorted(all_cats):
            list_a = val_map_a.get(cat, [])
            list_b = val_map_b.get(cat, [])

            # Common identical values
            common = set(list_a) & set(list_b)
            for val in sorted(common):
                audit.append({"category": cat, "file_a": val, "file_b": val, "status": "Identical"})

            # Differences
            only_a = [v for v in list_a if v not in common]
            only_b = [v for v in list_b if v not in common]

            pair_count = min(len(only_a), len(only_b))
            for i in range(pair_count):
                audit.append({"category": cat, "file_a": only_a[i], "file_b": only_b[i], "status": "Changed"})

            for v in only_a[pair_count:]:
                audit.append({"category": cat, "file_a": v, "file_b": "—", "status": "Only in A"})

            for v in only_b[pair_count:]:
                audit.append({"category": cat, "file_a": "—", "file_b": v, "status": "Only in B"})

        return audit

    # ------------------------------------------------------------------ #
    # SIDE-BY-SIDE HTML DIFF TABLE
    # ------------------------------------------------------------------ #
    def _generate_html_diff(self, text_a: str, text_b: str, name_a: str, name_b: str) -> str:
        """Generate a styled side-by-side HTML diff table."""
        import difflib
        lines_a = text_a.splitlines()
        lines_b = text_b.splitlines()
        hd = difflib.HtmlDiff(tabsize=4, wrapcolumn=60)
        table = hd.make_table(
            lines_a, lines_b,
            fromdesc=f"File A: {name_a}",
            todesc=f"File B: {name_b}",
            context=True,
            numlines=3
        )
        custom_css = """
        <style>
            body { font-family: monospace, sans-serif; background-color: #1e1e1e; color: #d4d4d4; font-size: 11px; }
            table.diff { border-collapse: collapse; width: 100%; border: 1px solid #333; }
            table.diff th { background-color: #252526; color: #9cdcfe; padding: 6px; border: 1px solid #333; text-align: left; }
            table.diff td { padding: 3px 6px; border: 1px solid #2a2a2a; }
            .diff_header { background-color: #2d2d30; color: #858585; text-align: right; width: 30px; user-select: none; }
            .diff_next { background-color: #252526; }
            .diff_add { background-color: #1b4d24; color: #85e89d; }
            .diff_chg { background-color: #4a3e1b; color: #ffdf5d; }
            .diff_sub { background-color: #541d20; color: #f97583; }
        </style>
        """
        return custom_css + table

    # ------------------------------------------------------------------ #
    # EXPORT REPORT
    # ------------------------------------------------------------------ #
    def export_report(self, result: ComparisonResult, file_path: str) -> bool:
        """Export the comparison result to HTML or Markdown."""
        if not file_path or not result:
            return False

        ext = os.path.splitext(file_path)[1].lower()
        if not ext:
            ext = ".html"
            file_path += ext

        try:
            folder = os.path.dirname(os.path.abspath(file_path))
            if folder:
                os.makedirs(folder, exist_ok=True)

            fn_a = os.path.basename(result.file_a)
            fn_b = os.path.basename(result.file_b)

            if ext == ".html":
                audit_rows = ""
                for row in result.numerical_audit:
                    color = "#85e89d" if "Only in B" in row["status"] else ("#f97583" if "Only in A" in row["status"] else "#ffdf5d")
                    if row["status"] == "Identical":
                        color = "#858585"
                    audit_rows += f"<tr><td>{row['category']}</td><td>{row['file_a']}</td><td>{row['file_b']}</td><td style='color:{color}; font-weight:bold;'>{row['status']}</td></tr>\n"

                sa = result.structural_a or StructuralStats()
                sb = result.structural_b or StructuralStats()
                cat_a, type_a = get_file_type_info(result.file_a)
                cat_b, type_b = get_file_type_info(result.file_b)
                sim_pct = round((result.textual.unchanged_ratio if result.textual else 0) * 100, 1)

                html_content = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>Document Comparison: {fn_a} vs {fn_b}</title>
<style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; background: #181818; color: #e0e0e0; margin: 24px; }}
    h1, h2, h3 {{ color: #ffffff; }}
    .card {{ background: #222222; border-radius: 8px; padding: 18px; margin-bottom: 24px; border: 1px solid #333; }}
    table {{ width: 100%; border-collapse: collapse; margin-top: 10px; }}
    th, td {{ padding: 8px 12px; border: 1px solid #383838; text-align: left; }}
    th {{ background: #2c2c2c; color: #58a6ff; }}
    .badge {{ display: inline-block; padding: 4px 10px; border-radius: 4px; font-weight: bold; background: #238636; color: #fff; }}
</style>
</head>
<body>
    <h1>📄 Document Comparison Report</h1>
    <div class="card">
        <h3>Files Compared</h3>
        <p><b>File A:</b> <code>{result.file_a}</code> <span style="color:#8b949e">({type_a})</span><br><b>File B:</b> <code>{result.file_b}</code> <span style="color:#8b949e">({type_b})</span></p>
        <p><b>Overall Similarity:</b> <span class="badge">{sim_pct}% Match</span></p>
    </div>

    <div class="card">
        <h2>📊 Structural Comparison</h2>
        <table>
            <tr><th>Metric</th><th>File A ({fn_a})</th><th>File B ({fn_b})</th></tr>
            <tr><td>Format</td><td>{sa.format} ({type_a})</td><td>{sb.format} ({type_b})</td></tr>
            <tr><td>Word Count</td><td>{sa.word_count}</td><td>{sb.word_count}</td></tr>
            <tr><td>Character Count</td><td>{sa.char_count}</td><td>{sb.char_count}</td></tr>
            <tr><td>Pages / Sections</td><td>{sa.page_or_section_count}</td><td>{sb.page_or_section_count}</td></tr>
        </table>
    </div>

    <div class="card">
        <h2>🔢 Numerical & Entity Audit Table (Ground Truth)</h2>
        <table>
            <tr><th>Category</th><th>File A Value</th><th>File B Value</th><th>Status</th></tr>
            {audit_rows or "<tr><td colspan='4'>No distinct numbers/entities detected.</td></tr>"}
        </table>
    </div>

    <div class="card">
        <h2>🧠 Content Analysis & Semantic Findings</h2>
        <div style="white-space: pre-wrap; line-height: 1.5;">{result.semantic_summary}</div>
    </div>

    <div class="card">
        <h2>⚖️ Side-by-Side Diff Table</h2>
        {result.side_by_side_html or "<p>No textual diff available.</p>"}
    </div>
</body>
</html>"""
                with open(file_path, "w", encoding="utf-8") as f:
                    f.write(html_content)
                return True

            else:
                sim_pct = round((result.textual.unchanged_ratio if result.textual else 0) * 100, 1)
                cat_a, type_a = get_file_type_info(result.file_a)
                cat_b, type_b = get_file_type_info(result.file_b)
                md_content = f"""# Document Comparison Report

**File A:** `{result.file_a}` ({type_a})  
**File B:** `{result.file_b}` ({type_b})  
**Similarity:** {sim_pct}% Match

---

## 📊 Structural Comparison
| Metric | File A (`{fn_a}`) | File B (`{fn_b}`) |
| :--- | :--- | :--- |
| Format | {result.structural_a.format if result.structural_a else ''} ({type_a}) | {result.structural_b.format if result.structural_b else ''} ({type_b}) |
| Word Count | {result.structural_a.word_count if result.structural_a else 0} | {result.structural_b.word_count if result.structural_b else 0} |
| Characters | {result.structural_a.char_count if result.structural_a else 0} | {result.structural_b.char_count if result.structural_b else 0} |

---

## 🔢 Numerical & Entity Audit Table (Ground Truth)
| Category | File A | File B | Status |
| :--- | :--- | :--- | :--- |
"""
                for row in result.numerical_audit:
                    md_content += f"| {row['category']} | {row['file_a']} | {row['file_b']} | {row['status']} |\n"

                md_content += f"""
---

## 🧠 Semantic Findings
{result.semantic_summary}
"""
                with open(file_path, "w", encoding="utf-8") as f:
                    f.write(md_content)
                return True

        except Exception as exc:
            logger.error("Failed to export comparison report: %s", exc)
            return False
