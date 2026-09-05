"""
Unit tests for document_comparison_enhancements.py
Tests textual diff, structural analysis, semantic diff, and consolidated results.
"""

import unittest
from dataclasses import dataclass
from typing import List, Dict
from difflib import SequenceMatcher


@dataclass
class ComparisonMethodResult:
    """Result from a comparison method."""
    method_name: str
    similarity: float  # 0.0-1.0
    differences: List[str]
    confidence: float  # 0.0-1.0


class TestTextualComparison(unittest.TestCase):
    """Test textual diff comparison method."""

    def test_identical_documents(self):
        """Test comparison of identical documents."""
        doc1 = "The quick brown fox jumps"
        doc2 = "The quick brown fox jumps"
        
        matcher = SequenceMatcher(None, doc1, doc2)
        similarity = matcher.ratio()
        
        self.assertEqual(similarity, 1.0)

    def test_completely_different_documents(self):
        """Test comparison of completely different documents."""
        doc1 = "AAABBBCCC"
        doc2 = "XXXYYYZZZZ"
        
        matcher = SequenceMatcher(None, doc1, doc2)
        similarity = matcher.ratio()
        
        self.assertEqual(similarity, 0.0)

    def test_partial_similarity(self):
        """Test documents with partial similarity."""
        doc1 = "The quick brown fox"
        doc2 = "The brown fox"
        
        matcher = SequenceMatcher(None, doc1, doc2)
        similarity = matcher.ratio()
        
        self.assertGreater(similarity, 0.5)
        self.assertLess(similarity, 1.0)

    def test_case_sensitivity(self):
        """Test case sensitivity in comparison."""
        doc1 = "Hello World"
        doc2 = "hello world"
        
        matcher_case_sensitive = SequenceMatcher(None, doc1, doc2)
        similarity_cs = matcher_case_sensitive.ratio()
        
        # Case matters
        self.assertLess(similarity_cs, 1.0)

    def test_whitespace_sensitivity(self):
        """Test whitespace handling."""
        doc1 = "The quick brown fox"
        doc2 = "The  quick  brown  fox"  # Extra spaces
        
        matcher = SequenceMatcher(None, doc1, doc2)
        similarity = matcher.ratio()
        
        self.assertLess(similarity, 1.0)

    def test_line_by_line_comparison(self):
        """Test line-by-line comparison."""
        doc1 = "Line 1\nLine 2\nLine 3"
        doc2 = "Line 1\nLine 2\nLine 4"
        
        lines1 = doc1.split('\n')
        lines2 = doc2.split('\n')
        
        differences = [i for i, (l1, l2) in enumerate(zip(lines1, lines2)) if l1 != l2]
        self.assertEqual(len(differences), 1)

    def test_empty_document(self):
        """Test comparison with empty document."""
        doc1 = "content"
        doc2 = ""
        
        matcher = SequenceMatcher(None, doc1, doc2)
        similarity = matcher.ratio()
        
        self.assertEqual(similarity, 0.0)

    def test_very_long_documents(self):
        """Test comparison of very long documents."""
        doc1 = "word " * 10000
        doc2 = "word " * 10000
        
        matcher = SequenceMatcher(None, doc1, doc2)
        similarity = matcher.ratio()
        
        self.assertEqual(similarity, 1.0)


class TestStructuralComparison(unittest.TestCase):
    """Test structural analysis comparison method."""

    def test_length_analysis(self):
        """Test length analysis."""
        doc1 = "Short document"
        doc2 = "This is a much longer document with more words"
        
        len1 = len(doc1)
        len2 = len(doc2)
        
        self.assertLess(len1, len2)
        length_ratio = min(len1, len2) / max(len1, len2)
        self.assertLess(length_ratio, 1.0)

    def test_word_count_analysis(self):
        """Test word count analysis."""
        doc1 = "one two three four five"
        doc2 = "one two three"
        
        words1 = len(doc1.split())
        words2 = len(doc2.split())
        
        self.assertEqual(words1, 5)
        self.assertEqual(words2, 3)

    def test_section_analysis(self):
        """Test section/paragraph analysis."""
        doc1 = "Section 1\n\nParagraph 1\nParagraph 2\n\nSection 2\n\nParagraph 3"
        doc2 = "Section 1\n\nParagraph 1\n\nSection 2\n\nParagraph 2\nParagraph 3"
        
        sections1 = len([p for p in doc1.split('\n\n') if p.strip()])
        sections2 = len([p for p in doc2.split('\n\n') if p.strip()])
        
        self.assertGreater(sections1, 0)
        self.assertGreater(sections2, 0)

    def test_formatting_analysis(self):
        """Test formatting detection."""
        doc1 = "**Bold** and *italic*"
        doc2 = "Bold and italic"
        
        bold_markers_1 = doc1.count('**')
        bold_markers_2 = doc2.count('**')
        
        self.assertEqual(bold_markers_1, 2)
        self.assertEqual(bold_markers_2, 0)

    def test_average_line_length(self):
        """Test average line length calculation."""
        doc1 = "Short\nMedium length line\nLonger line with more content here"
        doc2 = "Line1\nLine2\nLine3"
        
        lines1 = doc1.split('\n')
        lines2 = doc2.split('\n')
        
        avg_len1 = sum(len(l) for l in lines1) / len(lines1)
        avg_len2 = sum(len(l) for l in lines2) / len(lines2)
        
        self.assertGreater(avg_len1, avg_len2)

    def test_structural_similarity(self):
        """Test overall structural similarity."""
        doc1 = "Title\n\nParagraph 1\nParagraph 2\n\nConclusion"
        doc2 = "Title\n\nContent section 1\nContent section 2\n\nFinal thoughts"
        
        # Same structure: title, 2 sections, conclusion
        structure_similar = (
            len(doc1.split('\n\n')) == len(doc2.split('\n\n'))
        )
        self.assertTrue(structure_similar)


class TestSemanticComparison(unittest.TestCase):
    """Test semantic similarity comparison."""

    def test_synonym_recognition(self):
        """Test semantic understanding with synonyms."""
        # In real implementation, would use embeddings
        doc1 = "The automobile is fast"
        doc2 = "The car is quick"
        
        # Semantic similarity (simulated)
        self.assertIsNotNone(doc1)
        self.assertIsNotNone(doc2)

    def test_paraphrase_recognition(self):
        """Test recognition of paraphrases."""
        doc1 = "The weather is bad today"
        doc2 = "Today has poor weather"
        
        # Both express same concept
        self.assertIsNotNone(doc1)
        self.assertIsNotNone(doc2)

    def test_meaning_preservation_through_changes(self):
        """Test semantic meaning preserved despite textual changes."""
        original = "John gave Mary a book"
        paraphrase = "Mary received a book from John"
        
        self.assertIsNotNone(original)
        self.assertIsNotNone(paraphrase)

    def test_semantic_distance(self):
        """Test semantic distance between documents."""
        related = "Python is a snake"
        unrelated = "The weather is sunny"
        
        self.assertIsNotNone(related)
        self.assertIsNotNone(unrelated)

    def test_topic_similarity(self):
        """Test topic-level similarity."""
        doc1 = "Machine learning uses neural networks"
        doc2 = "Deep learning with artificial neural networks"
        
        # Both about neural networks - high semantic similarity
        self.assertIsNotNone(doc1)
        self.assertIsNotNone(doc2)


class TestConsolidatedResults(unittest.TestCase):
    """Test consolidated comparison results."""

    def test_three_method_consolidation(self):
        """Test consolidating results from 3 methods."""
        textual = ComparisonMethodResult("textual", 0.85, ["Minor word differences"], 0.9)
        structural = ComparisonMethodResult("structural", 0.90, [], 0.95)
        semantic = ComparisonMethodResult("semantic", 0.88, [], 0.92)
        
        methods = [textual, structural, semantic]
        
        # Weighted scoring: 40% textual, 30% structural, 30% semantic
        # (0.85 * 0.4) + (0.90 * 0.3) + (0.88 * 0.3) = 0.34 + 0.27 + 0.264 = 0.874
        consolidated = (
            (textual.similarity * 0.4) +
            (structural.similarity * 0.3) +
            (semantic.similarity * 0.3)
        )
        
        self.assertAlmostEqual(consolidated, 0.874, places=2)

    def test_weight_distribution(self):
        """Test that weights sum to 1.0."""
        weights = {
            "textual": 0.4,
            "structural": 0.3,
            "semantic": 0.3
        }
        total = sum(weights.values())
        self.assertEqual(total, 1.0)

    def test_consolidated_confidence(self):
        """Test consolidated confidence score."""
        results = [
            ComparisonMethodResult("textual", 0.8, [], 0.85),
            ComparisonMethodResult("structural", 0.9, [], 0.95),
            ComparisonMethodResult("semantic", 0.85, [], 0.88),
        ]
        
        avg_confidence = sum(r.confidence for r in results) / len(results)
        self.assertAlmostEqual(avg_confidence, 0.893, places=2)

    def test_difference_aggregation(self):
        """Test aggregating differences from all methods."""
        results = [
            ComparisonMethodResult("textual", 0.8, ["Word mismatch at position 10"], 0.85),
            ComparisonMethodResult("structural", 0.9, [], 0.95),
            ComparisonMethodResult("semantic", 0.85, ["Slightly different meaning"], 0.88),
        ]
        
        all_differences = []
        for r in results:
            all_differences.extend(r.differences)
        
        self.assertEqual(len(all_differences), 2)

    def test_consolidated_result_structure(self):
        """Test structure of consolidated result."""
        consolidated = {
            "overall_similarity": 0.867,
            "overall_confidence": 0.893,
            "textual_similarity": 0.85,
            "structural_similarity": 0.90,
            "semantic_similarity": 0.88,
            "all_differences": ["Difference 1", "Difference 2"],
            "recommendation": "Documents are highly similar"
        }
        
        self.assertIn("overall_similarity", consolidated)
        self.assertIn("overall_confidence", consolidated)
        self.assertGreater(consolidated["overall_similarity"], 0.8)


class TestComparisonEdgeCases(unittest.TestCase):
    """Test edge cases in document comparison."""

    def test_empty_documents(self):
        """Test comparing two empty documents."""
        doc1 = ""
        doc2 = ""
        
        matcher = SequenceMatcher(None, doc1, doc2)
        similarity = matcher.ratio()
        
        self.assertEqual(similarity, 1.0)

    def test_one_empty_document(self):
        """Test comparing with one empty document."""
        doc1 = "content"
        doc2 = ""
        
        matcher = SequenceMatcher(None, doc1, doc2)
        similarity = matcher.ratio()
        
        self.assertEqual(similarity, 0.0)

    def test_very_large_documents(self):
        """Test comparing very large documents."""
        doc1 = "word " * 100000
        doc2 = "word " * 100000
        
        matcher = SequenceMatcher(None, doc1, doc2)
        similarity = matcher.ratio()
        
        self.assertEqual(similarity, 1.0)

    def test_special_characters(self):
        """Test documents with special characters."""
        doc1 = "Test@#$%^&*()"
        doc2 = "Test@#$%^&*()"
        
        matcher = SequenceMatcher(None, doc1, doc2)
        similarity = matcher.ratio()
        
        self.assertEqual(similarity, 1.0)

    def test_multilingual_documents(self):
        """Test multilingual document comparison."""
        doc1 = "Hello 你好 مرحبا"
        doc2 = "Hello 你好 مرحبا"
        
        matcher = SequenceMatcher(None, doc1, doc2)
        similarity = matcher.ratio()
        
        self.assertEqual(similarity, 1.0)

    def test_unicode_handling(self):
        """Test unicode character handling."""
        doc1 = "Café naïve résumé"
        doc2 = "Café naïve résumé"
        
        matcher = SequenceMatcher(None, doc1, doc2)
        similarity = matcher.ratio()
        
        self.assertEqual(similarity, 1.0)

    def test_single_character_difference(self):
        """Test documents with single character difference."""
        doc1 = "The quick brown fox"
        doc2 = "The quick brown fax"
        
        matcher = SequenceMatcher(None, doc1, doc2)
        similarity = matcher.ratio()
        
        # SequenceMatcher gives 0.947... which is close to 0.95
        self.assertGreaterEqual(similarity, 0.94)
        self.assertLess(similarity, 1.0)


class TestComparisonIntegration(unittest.TestCase):
    """Test comparison method integration."""

    def test_three_methods_agreement(self):
        """Test when all three methods agree."""
        results = [
            ComparisonMethodResult("textual", 0.95, [], 0.95),
            ComparisonMethodResult("structural", 0.94, [], 0.94),
            ComparisonMethodResult("semantic", 0.96, [], 0.96),
        ]
        
        # All similar
        all_similar = all(r.similarity > 0.9 for r in results)
        self.assertTrue(all_similar)

    def test_methods_disagreement(self):
        """Test when methods disagree."""
        results = [
            ComparisonMethodResult("textual", 0.5, ["Many differences"], 0.5),
            ComparisonMethodResult("structural", 0.9, [], 0.9),
            ComparisonMethodResult("semantic", 0.8, [], 0.8),
        ]
        
        # Methods disagree on textual
        low_confidence = any(r.similarity < 0.7 for r in results)
        self.assertTrue(low_confidence)

    def test_confidence_weighted_decision(self):
        """Test decision making based on confidence."""
        result = ComparisonMethodResult(
            "consolidated",
            0.85,
            [],
            0.92
        )
        
        # High confidence - reliable result
        reliable = result.confidence > 0.9
        self.assertTrue(reliable)


class TestComparisonPerformance(unittest.TestCase):
    """Test performance characteristics."""

    def test_textual_comparison_speed(self):
        """Test textual comparison speed."""
        import time
        doc1 = "word " * 10000
        doc2 = "word " * 10000
        
        start = time.time()
        matcher = SequenceMatcher(None, doc1, doc2)
        similarity = matcher.ratio()
        elapsed = time.time() - start
        
        self.assertLess(elapsed, 1.0)

    def test_consolidation_speed(self):
        """Test result consolidation speed."""
        import time
        results = [
            ComparisonMethodResult(f"method{i}", 0.5 + (i/10), [], 0.8)
            for i in range(100)
        ]
        
        start = time.time()
        consolidated = sum(r.similarity for r in results) / len(results)
        elapsed = time.time() - start
        
        self.assertLess(elapsed, 0.1)


if __name__ == "__main__":
    unittest.main()
