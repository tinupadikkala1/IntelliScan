"""
Phase 3.1: Knowledge Graph Validation
Validates entities and relationships to ensure accuracy
"""

import re
from typing import List, Dict, Tuple


class EntityValidation:
    """Entity extraction validation"""
    
    @staticmethod
    def validate_entity(entity: Dict, original_text: str, confidence_threshold: float = 0.7) -> float:
        """
        Validate if extracted entity is truly present and meaningful
        
        Args:
            entity: Extracted entity dict {text, type, confidence}
            original_text: Original document text
            confidence_threshold: Minimum confidence to accept
        
        Returns:
            Confidence score (0.0-1.0)
        """
        confidence = 0.0
        
        # Check 1: Entity text appears in original text
        entity_text = entity.get('text', '')
        if entity_text.lower() in original_text.lower():
            confidence += 0.35
        else:
            return 0.0  # Not even in text, fail immediately
        
        # Check 2: Known entity type
        known_types = {'PERSON', 'ORGANIZATION', 'LOCATION', 'DATE', 'PRODUCT', 'CONCEPT', 'EVENT'}
        entity_type = entity.get('type', '').upper()
        if entity_type in known_types:
            confidence += 0.35
        else:
            confidence += 0.10
        
        # Check 3: Context plausibility
        if EntityValidation._is_context_plausible(entity, original_text):
            confidence += 0.30
        
        return min(1.0, confidence)
    
    @staticmethod
    def _is_context_plausible(entity: Dict, text: str) -> bool:
        """Check if entity makes sense in context"""
        entity_text = entity.get('text', '')
        entity_type = entity.get('type', '').upper()
        
        # Find entity in text
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
            person_markers = {'mr', 'ms', 'dr', 'prof', 'said', 'told', 'asked', 'named', 'called'}
            return any(marker in context_words for marker in person_markers)
        
        elif entity_type == 'ORGANIZATION':
            org_markers = {'company', 'corp', 'inc', 'said', 'announced', 'reported', 'founded', 'established'}
            return any(marker in context_words for marker in org_markers)
        
        elif entity_type == 'LOCATION':
            loc_markers = {'in', 'from', 'to', 'near', 'located', 'city', 'country', 'region'}
            return any(marker in context_words for marker in loc_markers)
        
        elif entity_type == 'DATE':
            date_patterns = [r'\d{1,2}[/-]\d{1,2}[/-]\d{2,4}', r'\d{4}', r'january|february|march|april|may|june|july|august|september|october|november|december']
            return any(re.search(pattern, context) for pattern in date_patterns)
        
        return True  # Default: probably plausible


class RelationshipValidation:
    """Relationship extraction validation"""
    
    @staticmethod
    def validate_relationship(relationship: Dict, text: str, entities: List[Dict],
                             confidence_threshold: float = 0.7) -> float:
        """
        Validate if extracted relationship actually exists
        
        Args:
            relationship: Extracted relationship {source, target, type}
            text: Original document text
            entities: List of validated entities
            confidence_threshold: Minimum confidence to accept
        
        Returns:
            Confidence score (0.0-1.0)
        """
        confidence = 0.0
        
        source = relationship.get('source', '')
        target = relationship.get('target', '')
        rel_type = relationship.get('type', '')
        
        # Check 1: Both entities exist in text
        if source.lower() in text.lower() and target.lower() in text.lower():
            confidence += 0.30
        else:
            return 0.0  # Entities not in text, fail
        
        # Check 2: Entities are validated
        source_validated = any(e.get('text', '').lower() == source.lower() for e in entities)
        target_validated = any(e.get('text', '').lower() == target.lower() for e in entities)
        
        if source_validated and target_validated:
            confidence += 0.30
        else:
            confidence += 0.15
        
        # Check 3: Find textual evidence
        evidence_score = RelationshipValidation._find_relationship_evidence(
            source, target, rel_type, text
        )
        confidence += evidence_score * 0.25
        
        # Check 4: Relationship type is plausible
        if RelationshipValidation._is_relationship_plausible(source, rel_type, target):
            confidence += 0.15
        
        return min(1.0, confidence)
    
    @staticmethod
    def _find_relationship_evidence(source: str, target: str, rel_type: str, text: str) -> float:
        """Find textual evidence of relationship"""
        
        # Relationship keywords
        keywords_map = {
            'works_for': ['works for', 'employed by', 'at company', 'joined', 'works at'],
            'located_in': ['located in', 'based in', 'in city', 'of country', 'headquarters'],
            'partner_with': ['partnered with', 'works with', 'allied with', 'collaborates'],
            'owns': ['owns', 'founded', 'created', 'started', 'established'],
            'parent_of': ['parent of', 'father of', 'mother of', 'child of'],
            'friend_of': ['friend of', 'friends with', 'colleague'],
            'similar_to': ['similar to', 'like', 'compared to'],
        }
        
        keywords = keywords_map.get(rel_type, [])
        
        # Find entities in text
        source_idx = text.lower().find(source.lower())
        target_idx = text.lower().find(target.lower())
        
        if source_idx == -1 or target_idx == -1:
            return 0.0
        
        # Check proximity (entities should be close, within 500 chars)
        proximity = abs(source_idx - target_idx)
        if proximity > 500:
            return 0.2  # Too far apart but possible
        
        # Check for keywords between entities
        start = min(source_idx, target_idx)
        end = max(source_idx, target_idx) + 100
        between_text = text[start:end].lower()
        
        for keyword in keywords:
            if keyword in between_text:
                return 0.9  # Strong evidence
        
        # Check for pronouns linking entities
        if any(p in between_text for p in ['he ', 'she ', 'they ', 'their', 'him', 'her']):
            return 0.6  # Weak evidence
        
        return 0.3  # Proximity alone
    
    @staticmethod
    def _is_relationship_plausible(source: str, rel_type: str, target: str) -> bool:
        """Check if relationship makes logical sense"""
        
        # Self-relationships don't make sense
        if source.lower() == target.lower():
            return False
        
        # Validate relationship type exists
        valid_types = {
            'works_for', 'located_in', 'partner_with', 'owns',
            'parent_of', 'friend_of', 'similar_to', 'related_to',
            'mentions', 'cites', 'references'
        }
        
        if rel_type not in valid_types:
            return False  # Unknown relationship type
        
        return True


# INTEGRATION CODE FOR graph modules:

entity_integration = """
# Add to graph/entity_extractor.py - EntityExtractor class:

def extract_with_validation(self, text, validation_threshold=0.7):
    '''Extract entities with confidence filtering'''
    from graph.entity_validation import EntityValidation
    
    # Extract raw entities
    raw_entities = self._extract_entities_internal(text)
    
    # Validate each entity
    validated = []
    for entity in raw_entities:
        confidence = EntityValidation.validate_entity(entity, text, validation_threshold)
        
        if confidence >= validation_threshold:
            entity['confidence'] = confidence
            entity['validated'] = True
            validated.append(entity)
    
    return validated
"""

relationship_integration = """
# Add to graph/relationship_extractor.py - RelationshipExtractor class:

def extract_with_validation(self, text, entities, validation_threshold=0.7):
    '''Extract relationships with confidence filtering'''
    from graph.relationship_validation import RelationshipValidation
    
    # Extract raw relationships
    raw_relationships = self._extract_relationships_internal(text, entities)
    
    # Validate each relationship
    validated = []
    for rel in raw_relationships:
        confidence = RelationshipValidation.validate_relationship(
            rel, text, entities, validation_threshold
        )
        
        if confidence >= validation_threshold:
            rel['confidence'] = confidence
            rel['validated'] = True
            validated.append(rel)
    
    return validated
"""
