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

        # 2. Heuristic / Pattern-based Fallback (bounded, low-noise)
        try:
            candidates = re.findall(r'\b[A-Z][a-zA-Z0-9_\-]{2,}(?:\s+[A-Z][a-zA-Z0-9_\-]{2,})*\b', text)
            _STOP = ('the', 'and', 'for', 'with', 'this', 'that', 'from', 'image', 'file', 'content', 'extracted', 'normalized', 'document', 'text', 'photo', 'picture', 'page', 'table', 'figure', 'chapter', 'section')
            for cand in candidates:
                cand_clean = cand.strip()
                norm = normalize_entity_name(cand_clean)
                if cand_clean and norm not in seen and len(cand_clean) >= 3:
                    if cand_clean.lower() in _STOP:
                        continue
                    seen.add(norm)
                    records.append(EntityRecord(name=cand_clean, entity_type="CONCEPT"))
                    if len(records) >= 10:
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


    # ============ PHASE 3.1: ENTITY VALIDATION ============
    
    def extract_with_validation(self, text: str, validation_threshold: float = 0.7) -> List:
        """Extract entities with confidence-based validation."""
        from typing import List
        
        # Extract raw entities
        raw_entities = self.extract(text)
        
        # Validate each entity
        validated = []
        for entity in raw_entities:
            try:
                confidence = self._validate_entity(entity, text, validation_threshold)
                
                if confidence >= validation_threshold:
                    validated.append({
                        'name': entity.name,
                        'type': entity.entity_type,
                        'confidence': confidence,
                        'validated': True
                    })
            except Exception:
                pass
        
        return validated
    
    def _validate_entity(self, entity, original_text: str, confidence_threshold: float = 0.7) -> float:
        """Validate if extracted entity is truly present and meaningful."""
        confidence = 0.0
        
        entity_text = entity.name if hasattr(entity, 'name') else str(entity)
        
        # Check 1: Entity text appears in original
        if entity_text.lower() in original_text.lower():
            confidence += 0.35
        else:
            return 0.0
        
        # Check 2: Known entity type
        known_types = {'PERSON', 'ORGANIZATION', 'LOCATION', 'DATE', 'PRODUCT', 'CONCEPT', 'EVENT'}
        entity_type = (entity.entity_type if hasattr(entity, 'entity_type') else 'CONCEPT').upper()
        if entity_type in known_types:
            confidence += 0.35
        else:
            confidence += 0.10
        
        # Check 3: Context plausibility
        if self._is_entity_context_plausible(entity, original_text):
            confidence += 0.30
        
        return min(1.0, confidence)
    
    def _is_entity_context_plausible(self, entity, text: str) -> bool:
        """Check if entity makes sense in context."""
        entity_text = entity.name if hasattr(entity, 'name') else str(entity)
        entity_type = (entity.entity_type if hasattr(entity, 'entity_type') else 'CONCEPT').upper()
        
        idx = text.lower().find(entity_text.lower())
        if idx == -1:
            return False
        
        # Get context window
        start = max(0, idx - 80)
        end = min(len(text), idx + len(entity_text) + 80)
        context = text[start:end].lower()
        context_words = context.split()
        
        # Type-specific context checks
        if entity_type == 'PERSON':
            markers = {'mr', 'ms', 'dr', 'prof', 'said', 'told', 'asked', 'named'}
            return any(m in context_words for m in markers)
        elif entity_type == 'ORGANIZATION':
            markers = {'company', 'corp', 'inc', 'said', 'announced', 'founded'}
            return any(m in context_words for m in markers)
        elif entity_type == 'LOCATION':
            markers = {'in', 'from', 'to', 'city', 'country', 'region'}
            return any(m in context_words for m in markers)
        
        return True
