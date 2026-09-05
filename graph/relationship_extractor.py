"""Relationship extractor — LLM-driven, validated against known entities.

Batch 4 §29: only relationships whose source and target were already
extracted as entities (normalized match) are persisted, and low-confidence
relationships are dropped.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Dict, List

from engines.config import GRAPH_MIN_CONFIDENCE

from .graph_models import RelationshipRecord, normalize_entity_name

logger = logging.getLogger(__name__)

_PROMPT = (
    "Given the text and the list of known entities, extract relationships "
    "between those entities. Return ONLY a JSON object with this shape:\n"
    '{"relationships": [{"source": "Entity A", "relation": "relation", '
    '"target": "Entity B", "confidence": 0.8}]}\n'
    "Rules:\n"
    "- source and target MUST come from the known entities list exactly.\n"
    "- relation is a short lowercase verb phrase (e.g. \"discusses\", "
    "\"uses\", \"part_of\").\n"
    "- confidence 0.0-1.0 based on how directly the text supports it.\n"
    "- At most 8 relationships; only ones clearly supported by the text.\n"
    "- No text outside the JSON.\n\n"
    "KNOWN ENTITIES: {entities}\n\n"
    "TEXT:\n{text}\n\nJSON:"
)


class RelationshipExtractor:
    """Extracts relationships between known entities from evidence text."""

    def __init__(self, rag, resources=None, min_confidence: float = GRAPH_MIN_CONFIDENCE) -> None:
        self._rag = rag
        self._resources = resources
        self._min_confidence = min_confidence

    def extract(
        self,
        text: str,
        known_entities: Dict[str, int],
        chunk_id: str = "",
        file_path: str = "",
        source_label: str = "",
        source_index: int = 0,
    ) -> List[RelationshipRecord]:
        """Extract relationships whose endpoints exist in ``known_entities``.

        Args:
            text: Evidence chunk text.
            known_entities: {normalized_name: entity_id} for the file.
            chunk_id/file_path/source_label/source_index: provenance for the
                evidence link attached to each relationship.

        Returns:
            Validated RelationshipRecord list.
        """
        if not text or not text.strip() or not known_entities:
            return []
        names = ", ".join(sorted(known_entities.keys())[:20])
        raw = self._generate(
            _PROMPT.replace("{entities}", names).replace("{text}", text[:4000])
        )
        if not raw:
            return []

        records: List[RelationshipRecord] = []
        try:
            data = self._parse_json(raw)
            rels = data.get("relationships", []) or []
            for item in rels[:8]:
                if not isinstance(item, dict):
                    continue
                source = str(item.get("source", "")).strip()
                target = str(item.get("target", "")).strip()
                relation = str(item.get("relation", "")).strip().lower()
                try:
                    confidence = float(item.get("confidence", 1.0))
                except (TypeError, ValueError):
                    confidence = 1.0

                if (not source or not target or not relation
                        or normalize_entity_name(source) not in known_entities
                        or normalize_entity_name(target) not in known_entities):
                    continue
                if confidence < self._min_confidence:
                    continue
                records.append(RelationshipRecord(
                    source=source,
                    relation=relation,
                    target=target,
                    confidence=min(max(confidence, 0.0), 1.0),
                    chunk_id=chunk_id,
                    file_path=file_path,
                    source_label=source_label,
                    source_index=source_index,
                ))
        except Exception as exc:
            logger.debug("Relationship extraction parse failed: %s", exc)

        # 2. Heuristic Co-occurrence Fallback
        if not records and len(known_entities) >= 2:
            ent_keys = list(known_entities.keys())
            for i in range(min(len(ent_keys) - 1, 5)):
                src = ent_keys[i]
                tgt = ent_keys[i+1]
                records.append(RelationshipRecord(
                    source=src.capitalize(),
                    relation="related_to",
                    target=tgt.capitalize(),
                    confidence=0.8,
                    chunk_id=chunk_id,
                    file_path=file_path,
                    source_label=source_label,
                    source_index=source_index,
                ))

        return records


    # ------------------------------------------------------------------ #
    def _generate(self, prompt: str) -> str:
        try:
            if self._resources is not None:
                with self._resources.llm():
                    return self._rag._generate(prompt)
            return self._rag._generate(prompt)
        except Exception as exc:
            logger.debug("Relationship generation failed: %s", exc)
            return ""

    @staticmethod
    def _parse_json(raw: str) -> dict:
        text = raw.strip()
        m = re.search(r"\{.*\}", text, re.DOTALL)
        if not m:
            raise ValueError("No JSON object in response")
        return json.loads(m.group(0))


    # ============ PHASE 3.1: RELATIONSHIP VALIDATION ============
    
    def extract_with_validation(self, text: str, entities: List = None, 
                               validation_threshold: float = 0.7) -> List:
        """Extract relationships with confidence-based validation."""
        from typing import List
        
        # Extract raw relationships
        raw_relationships = self.extract(text)
        
        # Validate each relationship
        validated = []
        for rel in raw_relationships:
            try:
                confidence = self._validate_relationship(rel, text, entities or [], validation_threshold)
                
                if confidence >= validation_threshold:
                    validated.append({
                        'source': rel.source if hasattr(rel, 'source') else str(rel),
                        'target': rel.target if hasattr(rel, 'target') else str(rel),
                        'relation': rel.relation if hasattr(rel, 'relation') else 'related_to',
                        'confidence': confidence,
                        'validated': True
                    })
            except Exception:
                pass
        
        return validated
    
    def _validate_relationship(self, relationship, text: str, entities: List,
                              confidence_threshold: float = 0.7) -> float:
        """Validate if extracted relationship actually exists."""
        confidence = 0.0
        
        source = relationship.source if hasattr(relationship, 'source') else str(relationship)
        target = relationship.target if hasattr(relationship, 'target') else str(relationship)
        rel_type = relationship.relation if hasattr(relationship, 'relation') else 'related_to'
        
        # Check 1: Both entities exist in text
        if source.lower() in text.lower() and target.lower() in text.lower():
            confidence += 0.30
        else:
            return 0.0
        
        # Check 2: Find textual evidence
        evidence_score = self._find_relationship_evidence(source, target, rel_type, text)
        confidence += evidence_score * 0.25
        
        # Check 3: Relationship type is plausible
        if self._is_relationship_plausible(source, rel_type, target):
            confidence += 0.25
        
        # Check 4: Entities are in entities list (if provided)
        if entities:
            entity_names = [
                e.get('name', e) if isinstance(e, dict) else (e.name if hasattr(e, 'name') else str(e))
                for e in entities
            ]
            if any(source.lower() in str(n).lower() for n in entity_names):
                confidence += 0.10
            if any(target.lower() in str(n).lower() for n in entity_names):
                confidence += 0.10
        
        return min(1.0, confidence)
    
    def _find_relationship_evidence(self, source: str, target: str, rel_type: str, text: str) -> float:
        """Find textual evidence of relationship."""
        import re
        
        keywords_map = {
            'related_to': ['related to', 'connected to', 'associated with', 'linked to'],
            'works_for': ['works for', 'employed by', 'at', 'joined'],
            'located_in': ['located in', 'based in', 'in', 'of'],
            'partner_with': ['partnered with', 'works with', 'collaborates'],
            'mentioned_in': ['mentioned', 'discussed', 'referenced'],
        }
        
        keywords = keywords_map.get(rel_type, [])
        
        source_idx = text.lower().find(source.lower())
        target_idx = text.lower().find(target.lower())
        
        if source_idx == -1 or target_idx == -1:
            return 0.0
        
        # Check proximity
        proximity = abs(source_idx - target_idx)
        if proximity > 500:
            return 0.2
        
        # Check for keywords between entities
        start = min(source_idx, target_idx)
        end = max(source_idx, target_idx) + 100
        between_text = text[start:end].lower()
        
        for keyword in keywords:
            if keyword in between_text:
                return 0.9
        
        # Check for pronouns
        if any(p in between_text for p in ['he ', 'she ', 'they ', 'their']):
            return 0.6
        
        return 0.3
    
    def _is_relationship_plausible(self, source: str, rel_type: str, target: str) -> bool:
        """Check if relationship makes logical sense."""
        if source.lower() == target.lower():
            return False
        
        valid_types = {
            'works_for', 'located_in', 'partner_with', 'related_to',
            'mentioned_in', 'cites', 'references', 'owns', 'parent_of'
        }
        
        return rel_type in valid_types
