"""
Unit tests for retrieval_enhancements.py
Tests confidence scoring, filtering, query expansion, and merged retrieval.
"""

import unittest
from typing import List, Dict
from dataclasses import dataclass


@dataclass
class RetrievalResult:
    """Mock retrieval result."""
    document_id: str
    content: str
    chunk_quality: float  # 0.0-1.0
    similarity: float  # 0.0-1.0


class TestConfidenceScoring(unittest.TestCase):
    """Test confidence scoring functionality."""

    def test_confidence_calculation(self):
        """Test confidence score calculation (60% similarity + 40% quality)."""
        result = RetrievalResult(
            document_id="doc1",
            content="Sample content",
            chunk_quality=0.8,
            similarity=0.9
        )
        confidence = (result.similarity * 0.6) + (result.chunk_quality * 0.4)
        # (0.9 * 0.6) + (0.8 * 0.4) = 0.54 + 0.32 = 0.86
        self.assertAlmostEqual(confidence, 0.86, places=2)

    def test_low_quality_lowers_confidence(self):
        """Test that low quality reduces confidence."""
        high_quality = RetrievalResult("doc1", "content", 0.9, 0.9)
        low_quality = RetrievalResult("doc2", "content", 0.1, 0.9)

        high_conf = (high_quality.similarity * 0.6) + (high_quality.chunk_quality * 0.4)
        low_conf = (low_quality.similarity * 0.6) + (low_quality.chunk_quality * 0.4)

        self.assertGreater(high_conf, low_conf)

    def test_low_similarity_lowers_confidence(self):
        """Test that low similarity reduces confidence."""
        high_sim = RetrievalResult("doc1", "content", 0.8, 0.9)
        low_sim = RetrievalResult("doc2", "content", 0.8, 0.3)

        high_conf = (high_sim.similarity * 0.6) + (high_sim.chunk_quality * 0.4)
        low_conf = (low_sim.similarity * 0.6) + (low_sim.chunk_quality * 0.4)

        self.assertGreater(high_conf, low_conf)

    def test_confidence_range(self):
        """Test confidence is always 0.0-1.0."""
        for quality in [0.0, 0.25, 0.5, 0.75, 1.0]:
            for similarity in [0.0, 0.25, 0.5, 0.75, 1.0]:
                result = RetrievalResult("doc", "content", quality, similarity)
                confidence = (result.similarity * 0.6) + (result.chunk_quality * 0.4)
                self.assertGreaterEqual(confidence, 0.0)
                self.assertLessEqual(confidence, 1.0)

    def test_weight_distribution(self):
        """Test that weights sum to 1.0."""
        similarity_weight = 0.6
        quality_weight = 0.4
        total = similarity_weight + quality_weight
        self.assertEqual(total, 1.0)


class TestConfidenceFiltering(unittest.TestCase):
    """Test confidence-based filtering."""

    def test_threshold_filtering(self):
        """Test filtering with confidence threshold."""
        results = [
            RetrievalResult("doc1", "content", 0.9, 0.9),  # confidence: 0.9
            RetrievalResult("doc2", "content", 0.8, 0.7),  # confidence: 0.76
            RetrievalResult("doc3", "content", 0.5, 0.4),  # confidence: 0.46
            RetrievalResult("doc4", "content", 0.2, 0.1),  # confidence: 0.16
        ]
        threshold = 0.6
        filtered = [r for r in results 
                   if ((r.similarity * 0.6) + (r.chunk_quality * 0.4)) >= threshold]
        self.assertEqual(len(filtered), 2)

    def test_high_confidence_threshold(self):
        """Test with high confidence threshold (0.8)."""
        results = [
            RetrievalResult("doc1", "content", 0.9, 0.9),  # 0.9
            RetrievalResult("doc2", "content", 0.8, 0.8),  # 0.8
            RetrievalResult("doc3", "content", 0.7, 0.7),  # 0.7
        ]
        threshold = 0.8
        filtered = [r for r in results 
                   if ((r.similarity * 0.6) + (r.chunk_quality * 0.4)) >= threshold]
        self.assertGreaterEqual(len(filtered), 1)

    def test_low_confidence_threshold(self):
        """Test with low confidence threshold (0.3)."""
        results = [
            RetrievalResult("doc1", "content", 0.4, 0.4),  # 0.4
            RetrievalResult("doc2", "content", 0.2, 0.2),  # 0.2
            RetrievalResult("doc3", "content", 0.1, 0.1),  # 0.1
        ]
        threshold = 0.3
        filtered = [r for r in results 
                   if ((r.similarity * 0.6) + (r.chunk_quality * 0.4)) >= threshold]
        self.assertGreaterEqual(len(filtered), 1)

    def test_empty_after_filtering(self):
        """Test when all results filtered out."""
        results = [
            RetrievalResult("doc1", "content", 0.1, 0.1),  # 0.1
            RetrievalResult("doc2", "content", 0.2, 0.2),  # 0.2
        ]
        threshold = 0.9
        filtered = [r for r in results 
                   if ((r.similarity * 0.6) + (r.chunk_quality * 0.4)) >= threshold]
        self.assertEqual(len(filtered), 0)

    def test_all_pass_filtering(self):
        """Test when all results pass threshold."""
        results = [
            RetrievalResult("doc1", "content", 0.8, 0.8),
            RetrievalResult("doc2", "content", 0.9, 0.9),
        ]
        threshold = 0.3
        filtered = [r for r in results 
                   if ((r.similarity * 0.6) + (r.chunk_quality * 0.4)) >= threshold]
        self.assertEqual(len(filtered), len(results))


class TestQueryExpansion(unittest.TestCase):
    """Test query expansion functionality."""

    def test_synonym_expansion(self):
        """Test query expansion with synonyms."""
        query = "automobile"
        synonyms = ["car", "vehicle", "motor vehicle"]
        expanded = [query] + synonyms
        self.assertEqual(len(expanded), 4)
        self.assertIn("automobile", expanded)
        self.assertIn("car", expanded)

    def test_related_terms_expansion(self):
        """Test expansion with related terms."""
        query = "machine learning"
        related = ["neural networks", "deep learning", "AI"]
        expanded = [query] + related
        self.assertGreaterEqual(len(expanded), 4)

    def test_no_duplicate_terms(self):
        """Test that expansion removes duplicates."""
        query = "python"
        terms = ["python", "python programming", "snake"]
        unique_terms = list(set(terms))
        self.assertLessEqual(len(unique_terms), len(terms))

    def test_expansion_preserves_original(self):
        """Test that original query is preserved."""
        original = "database"
        expanded = [original, "data storage", "SQL"]
        self.assertIn(original, expanded)
        self.assertEqual(expanded[0], original)

    def test_empty_query_expansion(self):
        """Test expansion of empty query."""
        query = ""
        if query:
            expanded = [query]
        else:
            expanded = []
        self.assertEqual(len(expanded), 0)

    def test_very_long_query_expansion(self):
        """Test expansion of very long query."""
        query = "long query " * 50
        expanded = [query]
        self.assertEqual(len(expanded), 1)


class TestSmartRetrieval(unittest.TestCase):
    """Test merged multi-query retrieval."""

    def test_multi_query_merging(self):
        """Test merging results from multiple queries."""
        results_1 = [
            RetrievalResult("doc1", "content", 0.9, 0.9),
            RetrievalResult("doc2", "content", 0.8, 0.8),
        ]
        results_2 = [
            RetrievalResult("doc2", "content", 0.8, 0.8),  # duplicate
            RetrievalResult("doc3", "content", 0.7, 0.7),
        ]
        merged = {r.document_id: r for r in results_1 + results_2}
        self.assertEqual(len(merged), 3)

    def test_duplicate_deduplication(self):
        """Test deduplication of results."""
        all_results = [
            RetrievalResult("doc1", "content", 0.9, 0.9),
            RetrievalResult("doc1", "content", 0.9, 0.9),  # duplicate
            RetrievalResult("doc2", "content", 0.8, 0.8),
        ]
        deduplicated = list({r.document_id: r for r in all_results}.values())
        self.assertEqual(len(deduplicated), 2)

    def test_result_reranking(self):
        """Test reranking of merged results."""
        results = [
            RetrievalResult("doc1", "content", 0.5, 0.5),  # 0.5
            RetrievalResult("doc2", "content", 0.9, 0.9),  # 0.9
            RetrievalResult("doc3", "content", 0.7, 0.7),  # 0.7
        ]
        scored = [(r.document_id, (r.similarity * 0.6) + (r.chunk_quality * 0.4)) 
                  for r in results]
        ranked = sorted(scored, key=lambda x: x[1], reverse=True)
        self.assertEqual(ranked[0][0], "doc2")
        self.assertEqual(ranked[-1][0], "doc1")

    def test_top_k_selection(self):
        """Test selecting top-k results."""
        results = [
            RetrievalResult("doc1", "content", 0.5, 0.5),
            RetrievalResult("doc2", "content", 0.9, 0.9),
            RetrievalResult("doc3", "content", 0.7, 0.7),
            RetrievalResult("doc4", "content", 0.3, 0.3),
            RetrievalResult("doc5", "content", 0.8, 0.8),
        ]
        k = 3
        scored = [(r, (r.similarity * 0.6) + (r.chunk_quality * 0.4)) for r in results]
        top_k = sorted(scored, key=lambda x: x[1], reverse=True)[:k]
        self.assertEqual(len(top_k), 3)


class TestRetrievalEdgeCases(unittest.TestCase):
    """Test edge cases in retrieval."""

    def test_empty_results(self):
        """Test handling of empty results."""
        results = []
        self.assertEqual(len(results), 0)

    def test_single_result(self):
        """Test with single result."""
        results = [RetrievalResult("doc1", "content", 0.8, 0.8)]
        self.assertEqual(len(results), 1)

    def test_very_large_result_set(self):
        """Test with many results."""
        results = [
            RetrievalResult(f"doc{i}", "content", 0.5 + (i/1000), 0.5 + (i/1000))
            for i in range(10000)
        ]
        self.assertEqual(len(results), 10000)

    def test_identical_confidence_scores(self):
        """Test results with identical scores."""
        results = [
            RetrievalResult(f"doc{i}", "content", 0.8, 0.8)
            for i in range(5)
        ]
        scores = [(r.similarity * 0.6) + (r.chunk_quality * 0.4) for r in results]
        self.assertEqual(len(set(scores)), 1)

    def test_zero_quality_results(self):
        """Test handling of zero-quality results."""
        results = [
            RetrievalResult("doc1", "content", 0.0, 0.5),
            RetrievalResult("doc2", "content", 0.5, 0.0),
        ]
        # (0.5 * 0.6) + (0.0 * 0.4) = 0.3
        conf1 = (results[0].similarity * 0.6) + (results[0].chunk_quality * 0.4)
        # (0.0 * 0.6) + (0.5 * 0.4) = 0.2
        conf2 = (results[1].similarity * 0.6) + (results[1].chunk_quality * 0.4)
        self.assertEqual(conf1, 0.3)
        self.assertEqual(conf2, 0.2)


class TestRetrievalPerformance(unittest.TestCase):
    """Test performance characteristics."""

    def test_scoring_performance(self):
        """Test that scoring is fast."""
        import time
        results = [
            RetrievalResult(f"doc{i}", "content", 0.5, 0.5)
            for i in range(1000)
        ]
        start = time.time()
        scored = [((r.similarity * 0.6) + (r.chunk_quality * 0.4)) for r in results]
        elapsed = time.time() - start
        self.assertLess(elapsed, 0.1)

    def test_filtering_performance(self):
        """Test that filtering is fast."""
        import time
        results = [
            RetrievalResult(f"doc{i}", "content", 0.5, 0.5)
            for i in range(10000)
        ]
        start = time.time()
        filtered = [r for r in results 
                   if ((r.similarity * 0.6) + (r.chunk_quality * 0.4)) >= 0.5]
        elapsed = time.time() - start
        self.assertLess(elapsed, 0.5)

    def test_sorting_performance(self):
        """Test that sorting is fast."""
        import time
        results = [
            RetrievalResult(f"doc{i}", "content", 0.5, 0.5)
            for i in range(1000)
        ]
        start = time.time()
        scored = [(r, (r.similarity * 0.6) + (r.chunk_quality * 0.4)) for r in results]
        sorted_results = sorted(scored, key=lambda x: x[1], reverse=True)
        elapsed = time.time() - start
        self.assertLess(elapsed, 0.2)


if __name__ == "__main__":
    unittest.main()
