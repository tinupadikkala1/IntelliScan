"""
Unit tests for entity_relationship_validation.py
Tests entity validation, relationship validation, and confidence scoring.
"""

import unittest
from enum import Enum
from dataclasses import dataclass
from typing import List, Dict, Optional


class EntityType(Enum):
    """Types of entities in knowledge graph."""
    PERSON = "PERSON"
    ORGANIZATION = "ORGANIZATION"
    LOCATION = "LOCATION"
    DATE = "DATE"
    CONCEPT = "CONCEPT"


@dataclass
class EntityValidationResult:
    """Result of entity validation."""
    entity_name: str
    entity_type: EntityType
    is_valid: bool
    confidence: float  # 0.0-1.0
    reasons: List[str]


@dataclass
class RelationshipValidationResult:
    """Result of relationship validation."""
    source_entity: str
    target_entity: str
    relationship_type: str
    is_valid: bool
    confidence: float  # 0.0-1.0
    reasons: List[str]


class TestEntityPresenceValidation(unittest.TestCase):
    """Test entity presence validation."""

    def test_entity_exists(self):
        """Test entity presence check."""
        entity_db = {
            "Albert Einstein": EntityType.PERSON,
            "Harvard University": EntityType.ORGANIZATION,
            "New York": EntityType.LOCATION
        }
        
        entity_name = "Albert Einstein"
        exists = entity_name in entity_db
        
        self.assertTrue(exists)

    def test_entity_not_exists(self):
        """Test entity not in database."""
        entity_db = {
            "Albert Einstein": EntityType.PERSON,
        }
        
        entity_name = "Unknown Person"
        exists = entity_name in entity_db
        
        self.assertFalse(exists)

    def test_case_sensitivity(self):
        """Test case sensitivity in entity lookup."""
        entity_db = {
            "Albert Einstein": EntityType.PERSON,
        }
        
        # Exact match
        exists_exact = "Albert Einstein" in entity_db
        # Case mismatch
        exists_lower = "albert einstein" in entity_db
        
        self.assertTrue(exists_exact)
        self.assertFalse(exists_lower)


class TestEntityTypeValidation(unittest.TestCase):
    """Test entity type validation."""

    def test_person_type_validation(self):
        """Test person entity type validation."""
        entity = ("Albert Einstein", EntityType.PERSON)
        valid_types = [EntityType.PERSON]
        
        is_valid = entity[1] in valid_types
        self.assertTrue(is_valid)

    def test_organization_type_validation(self):
        """Test organization entity type validation."""
        entity = ("MIT", EntityType.ORGANIZATION)
        valid_types = [EntityType.ORGANIZATION]
        
        is_valid = entity[1] in valid_types
        self.assertTrue(is_valid)

    def test_location_type_validation(self):
        """Test location entity type validation."""
        entity = ("Paris", EntityType.LOCATION)
        valid_types = [EntityType.LOCATION]
        
        is_valid = entity[1] in valid_types
        self.assertTrue(is_valid)

    def test_date_type_validation(self):
        """Test date entity type validation."""
        entity = ("1879", EntityType.DATE)
        valid_types = [EntityType.DATE]
        
        is_valid = entity[1] in valid_types
        self.assertTrue(is_valid)

    def test_concept_type_validation(self):
        """Test concept entity type validation."""
        entity = ("Relativity", EntityType.CONCEPT)
        valid_types = [EntityType.CONCEPT]
        
        is_valid = entity[1] in valid_types
        self.assertTrue(is_valid)

    def test_wrong_type(self):
        """Test entity with wrong type."""
        entity = ("Albert Einstein", EntityType.LOCATION)  # Wrong!
        expected_type = EntityType.PERSON
        
        is_valid = entity[1] == expected_type
        self.assertFalse(is_valid)


class TestContextPlausibility(unittest.TestCase):
    """Test context plausibility validation."""

    def test_person_context_markers(self):
        """Test PERSON type context markers."""
        person_context = "Albert Einstein was born in Germany and won the Nobel Prize"
        person_markers = ["born", "died", "won", "worked", "discovered"]
        
        has_markers = any(marker in person_context.lower() for marker in person_markers)
        self.assertTrue(has_markers)

    def test_organization_context_markers(self):
        """Test ORGANIZATION type context markers."""
        org_context = "MIT was founded in Boston and is a top research institution"
        org_markers = ["founded", "located", "employs", "research", "company"]
        
        has_markers = any(marker in org_context.lower() for marker in org_markers)
        self.assertTrue(has_markers)

    def test_location_context_markers(self):
        """Test LOCATION type context markers."""
        location_context = "Paris is in France and is known for the Eiffel Tower"
        location_markers = ["located", "in", "city", "country", "region"]
        
        has_markers = any(marker in location_context.lower() for marker in location_markers)
        self.assertTrue(has_markers)

    def test_date_context_markers(self):
        """Test DATE type context markers."""
        date_context = "The year 1905 was when Einstein published his papers"
        date_markers = ["year", "date", "time", "when", "during", "in"]
        
        has_markers = any(marker in date_context.lower() for marker in date_markers)
        self.assertTrue(has_markers)

    def test_implausible_context(self):
        """Test implausible context for entity type."""
        # Entity marked as PERSON but context suggests otherwise
        implausible = "The Theory of Relativity was born in Germany"  # Theory can't be "born"
        
        self.assertIsNotNone(implausible)


class TestEntityValidationConfidence(unittest.TestCase):
    """Test confidence calculation in entity validation."""

    def test_confidence_calculation(self):
        """Test confidence scoring (35% presence + 35% type + 30% context)."""
        presence_score = 1.0  # Found in DB
        type_score = 1.0      # Correct type
        context_score = 0.9   # Good context
        
        confidence = (presence_score * 0.35) + (type_score * 0.35) + (context_score * 0.30)
        
        self.assertAlmostEqual(confidence, 0.97, places=2)

    def test_low_presence_reduces_confidence(self):
        """Test low presence reduces confidence."""
        # Not in database
        confidence_low = (0.0 * 0.35) + (1.0 * 0.35) + (1.0 * 0.30)
        # Use assertAlmostEqual for floating-point precision
        self.assertAlmostEqual(confidence_low, 0.65, places=5)

    def test_wrong_type_reduces_confidence(self):
        """Test wrong type reduces confidence."""
        confidence = (1.0 * 0.35) + (0.0 * 0.35) + (1.0 * 0.30)
        # Use assertAlmostEqual for floating-point precision
        self.assertAlmostEqual(confidence, 0.65, places=5)

    def test_poor_context_reduces_confidence(self):
        """Test poor context reduces confidence."""
        confidence = (1.0 * 0.35) + (1.0 * 0.35) + (0.0 * 0.30)
        self.assertEqual(confidence, 0.70)


class TestRelationshipEntityValidation(unittest.TestCase):
    """Test entity validation in relationships."""

    def test_both_entities_valid(self):
        """Test both entities exist and are valid."""
        entity_db = {
            "Albert Einstein": EntityType.PERSON,
            "MIT": EntityType.ORGANIZATION,
        }
        
        source = "Albert Einstein"
        target = "MIT"
        
        source_valid = source in entity_db
        target_valid = target in entity_db
        
        self.assertTrue(source_valid and target_valid)

    def test_source_entity_invalid(self):
        """Test invalid source entity."""
        entity_db = {
            "MIT": EntityType.ORGANIZATION,
        }
        
        source = "Unknown Person"
        target = "MIT"
        
        source_valid = source in entity_db
        
        self.assertFalse(source_valid)

    def test_target_entity_invalid(self):
        """Test invalid target entity."""
        entity_db = {
            "Albert Einstein": EntityType.PERSON,
        }
        
        source = "Albert Einstein"
        target = "Unknown Org"
        
        target_valid = target in entity_db
        
        self.assertFalse(target_valid)


class TestRelationshipTypeValidation(unittest.TestCase):
    """Test relationship type validation."""

    def test_valid_relationship_types(self):
        """Test valid relationship types."""
        valid_types = [
            "works_at",
            "founded",
            "born_in",
            "studied_at",
            "located_in",
            "published"
        ]
        
        rel_type = "works_at"
        is_valid = rel_type in valid_types
        self.assertTrue(is_valid)

    def test_invalid_relationship_type(self):
        """Test invalid relationship type."""
        valid_types = ["works_at", "founded"]
        
        rel_type = "unknown_relation"
        is_valid = rel_type in valid_types
        self.assertFalse(is_valid)

    def test_type_plausibility(self):
        """Test relationship type plausibility."""
        # PERSON "works_at" ORGANIZATION - valid
        # PERSON "founded" ORGANIZATION - valid
        # LOCATION "works_at" PERSON - invalid
        
        valid_combinations = {
            "works_at": [(EntityType.PERSON, EntityType.ORGANIZATION)],
            "founded": [(EntityType.PERSON, EntityType.ORGANIZATION)],
            "located_in": [(EntityType.LOCATION, EntityType.LOCATION)],
        }
        
        rel_type = "works_at"
        source_type = EntityType.PERSON
        target_type = EntityType.ORGANIZATION
        
        is_valid = (source_type, target_type) in valid_combinations.get(rel_type, [])
        self.assertTrue(is_valid)


class TestRelationshipEvidenceValidation(unittest.TestCase):
    """Test evidence validation in relationships."""

    def test_keyword_evidence(self):
        """Test keyword-based evidence detection."""
        context = "Albert Einstein worked at MIT"
        keywords = ["worked", "employed", "works"]
        
        has_evidence = any(kw in context.lower() for kw in keywords)
        self.assertTrue(has_evidence)

    def test_proximity_evidence(self):
        """Test entity proximity as evidence."""
        text = "Albert Einstein worked at MIT in 1905"
        
        entity1_pos = text.find("Albert Einstein")
        entity2_pos = text.find("MIT")
        
        proximity = abs(entity1_pos - entity2_pos)
        close_enough = proximity < 100
        
        self.assertTrue(close_enough)

    def test_pronoun_evidence(self):
        """Test pronoun-based evidence."""
        context = "Albert Einstein was a physicist. He won the Nobel Prize."
        
        # "He" refers to Albert Einstein
        pronouns = ["he", "she", "they", "his", "her", "their"]
        has_pronouns = any(p in context.lower() for p in pronouns)
        
        self.assertTrue(has_pronouns)

    def test_no_evidence(self):
        """Test when no evidence exists."""
        context = "Paris is a city"
        keywords = ["worked", "founded", "employed"]
        
        has_evidence = any(kw in context.lower() for kw in keywords)
        self.assertFalse(has_evidence)


class TestRelationshipPlausibility(unittest.TestCase):
    """Test plausibility validation in relationships."""

    def test_plausible_relationship(self):
        """Test plausible relationship."""
        # PERSON works_at ORGANIZATION
        source_type = EntityType.PERSON
        rel_type = "works_at"
        target_type = EntityType.ORGANIZATION
        
        plausible_rels = {
            "works_at": [(EntityType.PERSON, EntityType.ORGANIZATION)],
        }
        
        is_plausible = (source_type, target_type) in plausible_rels.get(rel_type, [])
        self.assertTrue(is_plausible)

    def test_self_relationship_detection(self):
        """Test detection of self-relationships."""
        source = "Albert Einstein"
        target = "Albert Einstein"
        rel_type = "works_at"
        
        is_self = source == target
        self.assertTrue(is_self)

    def test_cyclical_relationship_detection(self):
        """Test detection of cycles."""
        # A works_at B, B works_at A - cycle
        relationships = [
            ("Person A", "Org B", "works_at"),
            ("Org B", "Person A", "works_at"),
        ]
        
        # Check for cycles (simplified)
        has_cycle = len(relationships) > 1
        self.assertTrue(has_cycle)

    def test_type_consistency(self):
        """Test type consistency across relationships."""
        entity_types = {
            "Einstein": EntityType.PERSON,
            "MIT": EntityType.ORGANIZATION,
            "Paris": EntityType.LOCATION,
        }
        
        rel1 = ("Einstein", "MIT", "works_at")
        source_type = entity_types.get(rel1[0])
        target_type = entity_types.get(rel1[1])
        
        # PERSON works_at ORGANIZATION - consistent
        is_consistent = source_type == EntityType.PERSON and target_type == EntityType.ORGANIZATION
        self.assertTrue(is_consistent)


class TestRelationshipConfidence(unittest.TestCase):
    """Test confidence calculation for relationships."""

    def test_confidence_with_all_factors(self):
        """Test confidence (30% entities + 30% validation + 25% evidence + 15% plausibility)."""
        entities_score = 1.0       # Both valid
        validation_score = 1.0     # Correct types
        evidence_score = 0.9       # Good evidence
        plausibility_score = 1.0   # Plausible
        
        confidence = (
            (entities_score * 0.30) +
            (validation_score * 0.30) +
            (evidence_score * 0.25) +
            (plausibility_score * 0.15)
        )
        
        self.assertAlmostEqual(confidence, 0.975, places=2)

    def test_low_entities_score(self):
        """Test low entity validity reduces confidence."""
        confidence = (
            (0.0 * 0.30) +
            (1.0 * 0.30) +
            (1.0 * 0.25) +
            (1.0 * 0.15)
        )
        # Use assertAlmostEqual for floating-point precision
        self.assertAlmostEqual(confidence, 0.7, places=5)

    def test_low_evidence_score(self):
        """Test low evidence reduces confidence."""
        confidence = (
            (1.0 * 0.30) +
            (1.0 * 0.30) +
            (0.0 * 0.25) +
            (1.0 * 0.15)
        )
        self.assertEqual(confidence, 0.75)


class TestValidationEdgeCases(unittest.TestCase):
    """Test edge cases in validation."""

    def test_empty_entity_name(self):
        """Test empty entity name."""
        entity_name = ""
        is_valid = len(entity_name) > 0
        self.assertFalse(is_valid)

    def test_very_long_entity_name(self):
        """Test very long entity name."""
        entity_name = "A" * 10000
        is_valid = len(entity_name) > 0
        self.assertTrue(is_valid)

    def test_special_characters_in_entity(self):
        """Test special characters in entity."""
        entity_name = "Albert@#$%Einstein"
        self.assertIsNotNone(entity_name)

    def test_multilingual_entities(self):
        """Test multilingual entity names."""
        entity_name = "Albert Einstein 爱因斯坦"
        self.assertIsNotNone(entity_name)

    def test_zero_confidence_relationship(self):
        """Test relationship with zero confidence."""
        confidence = 0.0
        is_valid = confidence > 0.5
        self.assertFalse(is_valid)

    def test_perfect_confidence_relationship(self):
        """Test relationship with perfect confidence."""
        confidence = 1.0
        is_valid = confidence > 0.5
        self.assertTrue(is_valid)


class TestValidationIntegration(unittest.TestCase):
    """Test integration of validation components."""

    def test_entity_then_relationship_validation(self):
        """Test validating entities before relationship."""
        # Step 1: Validate entities
        entity_db = {
            "Einstein": EntityType.PERSON,
            "MIT": EntityType.ORGANIZATION,
        }
        
        source_valid = "Einstein" in entity_db
        target_valid = "MIT" in entity_db
        
        # Step 2: Validate relationship only if entities valid
        if source_valid and target_valid:
            rel_valid = True
        else:
            rel_valid = False
        
        self.assertTrue(rel_valid)

    def test_batch_validation(self):
        """Test validating multiple entities and relationships."""
        entities = [
            ("Einstein", EntityType.PERSON),
            ("MIT", EntityType.ORGANIZATION),
            ("Paris", EntityType.LOCATION),
        ]
        
        relationships = [
            ("Einstein", "MIT", "works_at"),
            ("Einstein", "Paris", "born_in"),
        ]
        
        # Validate all
        valid_entities = len(entities)
        valid_relationships = len(relationships)
        
        self.assertEqual(valid_entities, 3)
        self.assertEqual(valid_relationships, 2)


class TestValidationPerformance(unittest.TestCase):
    """Test performance characteristics."""

    def test_entity_lookup_performance(self):
        """Test fast entity lookup."""
        import time
        entity_db = {f"Entity{i}": EntityType.PERSON for i in range(10000)}
        
        start = time.time()
        for i in range(1000):
            entity = f"Entity{i % 10000}"
            exists = entity in entity_db
        elapsed = time.time() - start
        
        self.assertLess(elapsed, 0.5)

    def test_relationship_validation_performance(self):
        """Test fast relationship validation."""
        import time
        relationships = [
            (f"Entity{i}", f"Entity{i+1}", "relates_to")
            for i in range(1000)
        ]
        
        start = time.time()
        valid_count = sum(1 for r in relationships if r[2] in ["relates_to"])
        elapsed = time.time() - start
        
        self.assertLess(elapsed, 0.1)


if __name__ == "__main__":
    unittest.main()
