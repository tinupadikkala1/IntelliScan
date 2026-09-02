"""Automatic file renaming suggestions — B7-9 (#28).

Generates a meaningful proposed filename from existing metadata
(category, tags, caption, title, date, file type) and lets the user approve
it. Nothing is renamed automatically: execution goes through the same
approval → preview → move_file pipeline used by folder organization, so
every derived layer stays in sync and SHA-256 identity is preserved.

Validation rejects empty names, invalid filesystem characters, path
traversal, collisions, unintended extension changes, dangerous names and
excessive lengths.
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field
from typing import List, Optional

from engines.config import RENAME_FORBIDDEN_CHARS, RENAME_MAX_LENGTH

logger = logging.getLogger(__name__)


@dataclass
class RenameSuggestion:
    """A proposed rename for one file (advisory)."""

    file_path: str
    proposed_name: str
    current_name: str
    reason: str = ""
    errors: List[str] = field(default_factory=list)

    def is_valid(self) -> bool:
        return not self.errors and self.proposed_name != self.current_name

    def to_dict(self) -> dict:
        return {
            "file_path": self.file_path,
            "current_name": self.current_name,
            "proposed_name": self.proposed_name,
            "reason": self.reason,
            "errors": self.errors,
        }


class RenameSuggestionService:
    """Proposes and validates file renames from existing metadata or direct LLM content analysis."""

    def __init__(self, session_factory, pattern: str = "{category}_{title}", rag_engine=None) -> None:
        self._session_factory = session_factory
        self._pattern = pattern or "{category}_{title}"
        self._rag = rag_engine

    def suggest_from_content(self, file_path: str) -> RenameSuggestion:
        """Analyze file content directly using LLM to generate a concise, descriptive filename."""
        file_path = os.path.abspath(file_path)
        current = os.path.basename(file_path)
        ext = os.path.splitext(current)[1]
        stem = os.path.splitext(current)[0]

        meta = self._load_meta(file_path)
        extracted_text = meta.get("extracted_text") or meta.get("caption") or meta.get("summary") or ""

        # 1. Fallback to extracting document/audio/video content from scratch if not cached
        if not extracted_text:
            try:
                from engines.content_engine import UniversalContentEngine
                engine = UniversalContentEngine()
                extracted_text = engine.extract_full_text(file_path)
            except Exception as exc:
                logger.debug("Content extraction for rename failed: %s", exc)

        title_candidate = ""
        # 2. Ask LLM to generate a short, descriptive title if rag_engine & content are available
        if extracted_text and len(extracted_text.strip()) > 15 and self._rag is not None:
            try:
                snippet = extracted_text[:3000].replace("\n", " ")
                prompt = (
                    "You are an assistant that renames files based on their content.\n"
                    "Analyze the text snippet below and suggest a short, highly descriptive, "
                    "3 to 5 word file title that accurately summarizes what the file is about.\n\n"
                    "INSTRUCTIONS:\n"
                    "- Return ONLY the short title (e.g. '2026_Q2_Financial_Report' or 'DSA_Cheatsheet_Notes').\n"
                    "- Use clean TitleCase or Snake_Case with words separated by underscores or spaces.\n"
                    "- Do NOT include any explanations, quotes, punctuation, or file extension.\n\n"
                    f"FILE NAME: {current}\n"
                    f"CONTENT SNIPPET:\n{snippet}\n\n"
                    "SUGGESTED SHORT TITLE:"
                )
                response = self._rag._generate(prompt)
                if response and response.strip():
                    raw_title = response.strip().split("\n")[0].strip('"\'` ')
                    title_candidate = self._safe_token(raw_title)
            except Exception as exc:
                logger.debug("LLM title generation for rename failed: %s", exc)

        if not title_candidate:
            # Fallback to standard metadata-based suggestion if LLM is unavailable
            return self.suggest(file_path)

        proposed = title_candidate.replace(" ", "_")
        if ext and not proposed.lower().endswith(ext.lower()):
            proposed = f"{proposed}{ext}"

        suggestion = RenameSuggestion(
            file_path=file_path,
            current_name=current,
            proposed_name=proposed,
            reason="AI LLM Content Summarization",
        )
        suggestion.errors = self.validate(file_path, suggestion.proposed_name)
        return suggestion


    # ------------------------------------------------------------------ #
    def suggest(self, file_path: str) -> RenameSuggestion:
        """Build a rename suggestion for a single file."""
        current = os.path.basename(file_path)
        ext = os.path.splitext(current)[1]
        stem = os.path.splitext(current)[0]

        meta = self._load_meta(file_path)
        category = self._safe_token(meta.get("category") or "")
        tags = meta.get("tags") or []
        caption = (meta.get("caption") or "").strip()
        title = self._safe_token(meta.get("title") or stem)

        # Choose the best title-ish token: user title > caption > filename stem.
        title = self._safe_token(
            meta.get("title") or caption or stem
        ) or self._safe_token(stem)

        parts = {
            "category": category,
            "title": title,
            "type": ext.lstrip(".").lower() if ext else "file",
        }
        if tags:
            parts["tag"] = self._safe_token(tags[0])

        name = self._pattern
        for key, value in parts.items():
            name = name.replace("{" + key + "}", value or "")
        # Strip leftover placeholders and normalize whitespace/separators.
        name = re.sub(r"\{[a-z_]+\}", "", name)
        name = re.sub(r"\s+", " ", name).strip(" _-")

        if not name:
            name = title or stem
        if ext and not name.lower().endswith(ext.lower()):
            name = f"{name}{ext}"
        elif not ext:
            pass

        reason_parts = []
        if category:
            reason_parts.append(f"category '{category}'")
        if tags:
            reason_parts.append(f"tags: {', '.join(tags[:3])}")
        if caption:
            reason_parts.append("image caption")
        reason = "Derived from " + (" + ".join(reason_parts) if reason_parts else "filename")

        suggestion = RenameSuggestion(
            file_path=os.path.abspath(file_path),
            current_name=current,
            proposed_name=name,
            reason=reason,
        )
        suggestion.errors = self.validate(
            file_path, suggestion.proposed_name
        )
        return suggestion

    def suggest_many(self, paths: List[str]) -> List[RenameSuggestion]:
        return [self.suggest(p) for p in paths]

    # ------------------------------------------------------------------ #
    def validate(self, file_path: str, new_name: str) -> List[str]:
        """Validate a proposed name; returns a list of error strings."""
        errors: List[str] = []
        if not new_name or not new_name.strip():
            errors.append("Empty name")
            return errors
        if len(new_name) > RENAME_MAX_LENGTH:
            errors.append(f"Name too long ({len(new_name)} > {RENAME_MAX_LENGTH})")
        if any(c in new_name for c in RENAME_FORBIDDEN_CHARS):
            errors.append("Contains invalid filesystem characters")
        if new_name in (".", ".."):
            errors.append("Reserved name")
        if "/" in new_name or "\\" in new_name or new_name.startswith("~"):
            errors.append("Path traversal is not allowed")

        current = os.path.basename(file_path)
        if new_name == current:
            errors.append("Name is unchanged")

        # Extension must stay the same (never silently change file type).
        ext_new = os.path.splitext(new_name)[1].lower()
        ext_cur = os.path.splitext(current)[1].lower()
        if ext_cur and ext_new != ext_cur:
            errors.append(
                f"Extension change is not allowed ({ext_cur} → {ext_new})"
            )
        if not ext_cur and ext_new:
            errors.append("Extension change is not allowed")

        # Collision: target exists and is not this same file.
        target = os.path.join(os.path.dirname(os.path.abspath(file_path)), new_name)
        if os.path.exists(target) and os.path.abspath(target) != os.path.abspath(file_path):
            errors.append("A file with that name already exists")

        return errors

    # ------------------------------------------------------------------ #
    def _load_meta(self, file_path: str) -> dict:
        meta: dict = {"tags": []}
        try:
            import json
            from database.models import AIAnalysis
            from services.sqlite_indexer import IndexedFile
            from services.file_identity import calculate_sha256_safe

            abs_path = os.path.abspath(file_path)
            with self._session_factory() as session:
                row = session.query(IndexedFile).filter_by(
                    absolute_path=abs_path
                ).first()
                if row is not None:
                    if row.extracted_text:
                        meta["extracted_text"] = row.extracted_text
                    if row.user_metadata_json:
                        try:
                            um = json.loads(row.user_metadata_json) or {}
                            if isinstance(um, dict) and um.get("title"):
                                meta["title"] = um["title"]
                        except (json.JSONDecodeError, TypeError):
                            pass

                # Prefer the indexed checksum (no disk read); fall back to
                # hashing the file when it is not (yet) indexed.
                file_hash = row.checksum if (row and row.checksum) else None
                if not file_hash:
                    file_hash = calculate_sha256_safe(file_path)
                if file_hash:
                    ai = (
                        session.query(AIAnalysis)
                        .filter_by(file_hash=file_hash)
                        .first()
                    )
                    if ai is not None:
                        meta["category"] = ai.normalized_category or ai.category or ""
                        if ai.normalized_tags:
                            try:
                                meta["tags"] = json.loads(ai.normalized_tags) or []
                            except (json.JSONDecodeError, TypeError):
                                meta["tags"] = []
                        meta["caption"] = ai.caption or ""
        except Exception as exc:
            logger.debug("Rename metadata lookup failed for %s: %s", file_path, exc)
        return meta

    @staticmethod
    def _safe_token(text: str) -> str:
        """Normalize a token to filesystem-safe form."""
        text = re.sub(r"[" + re.escape(RENAME_FORBIDDEN_CHARS) + r"]", " ", text)
        text = re.sub(r"\s+", " ", text).strip(" ._-")
        text = text[:80]
        return text
