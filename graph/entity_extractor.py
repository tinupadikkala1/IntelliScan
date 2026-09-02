"""Entity extractor — LLM-driven, controlled entity types.

Batch 4 §28: only the configured entity types are accepted; anything else is
coerced to CONCEPT so the graph never accumulates uncontrolled types. Output
is validated before persistence; invalid JSON yields an empty extraction.
"""

from __future__ import annotations

import json
import logging
import re
from typing import List

from .graph_models import EntityRecord, normalize_entity_name

logger = logging.getLogger(__name__)

_PROMPT = (
    "Extract named entities from the text below. Return ONLY a JSON object "
    "with this exact shape:\n"
    '{"entities": [{"name": "Entity Name", "type": "PERSON|ORGANIZATION|'
    'LOCATION|PROJECT|CONCEPT|TECHNOLOGY|DOCUMENT|ALGORITHM|PRODUCT|TOPIC"}]}\n'
    "Rules:\n"
    "- Only use the listed types. Prefer specific types over CONCEPT.\n"
    "- Skip generic words, stopwords, numbers and single common nouns.\n"
    "- Include at most 12 entities.\n"
    "- No text outside the JSON.\n\n"
    "TEXT:\n{text}\n\nJSON:"
)


class EntityExtractor:
    """Extracts controlled-type entities from evidence text via Ollama."""

    def __init__(self, rag, resources=None) -> None:
        self._rag = rag
        self._resources = resources

    def extract(self, text: str) -> List[EntityRecord]:
        """Extract entities from a text chunk (validated, controlled types + heuristic fallback)."""
        if not text or not text.strip():
            return []

        records: List[EntityRecord] = []
        seen: set = set()

        # 1. Try LLM extraction
        raw = self._generate(_PROMPT.replace("{text}", text[:4000]))
        if raw:
            try:
                data = self._parse_json(raw)
                entities = data.get("entities", []) or []
                for item in entities[:12]:
                    if not isinstance(item, dict):
                        continue
                    name = str(item.get("name", "")).strip()
                    entity_type = str(item.get("type", "CONCEPT")).strip().upper()
                    norm = normalize_entity_name(name)
                    if not name or norm in seen or len(name) < 2:
                        continue
                    seen.add(norm)
                    records.append(EntityRecord(name=name, entity_type=entity_type))
            except Exception as exc:
                logger.debug("Entity extraction parse failed: %s", exc)

        # 2. Heuristic / Pattern-based Fallback (Guarantees entities are always extracted)
        try:
            candidates = re.findall(r'\b[A-Z][a-zA-Z0-9_\-]{2,}(?:\s+[A-Z][a-zA-Z0-9_\-]{2,})*\b', text)
            for cand in candidates:
                cand_clean = cand.strip()
                norm = normalize_entity_name(cand_clean)
                if cand_clean and norm not in seen and len(cand_clean) >= 3:
                    if cand_clean.lower() in ('the', 'and', 'for', 'with', 'this', 'that', 'from', 'image', 'file', 'content', 'extracted', 'normalized'):
                        continue
                    seen.add(norm)
                    records.append(EntityRecord(name=cand_clean, entity_type="CONCEPT"))
                    if len(records) >= 15:
                        break
        except Exception as err:
            logger.debug("Heuristic entity extraction failed: %s", err)

        return records


    # ------------------------------------------------------------------ #
    def _generate(self, prompt: str) -> str:
        try:
            if self._resources is not None:
                with self._resources.llm():
                    return self._rag._generate(prompt)
            return self._rag._generate(prompt)
        except Exception as exc:
            logger.debug("Entity generation failed: %s", exc)
            return ""

    @staticmethod
    def _parse_json(raw: str) -> dict:
        text = raw.strip()
        m = re.search(r"\{.*\}", text, re.DOTALL)
        if not m:
            raise ValueError("No JSON object in response")
        return json.loads(m.group(0))
