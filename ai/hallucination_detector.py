"""
Hallucination Detector Module

Detects and flags potentially hallucinated or unreliable AI-generated content.
Multi-layer validation system to ensure answers are grounded in provided context.
"""

import re
import numpy as np
from typing import Dict, List, Tuple
from dataclasses import dataclass


@dataclass
class HallucinationResult:
    """Result of hallucination detection"""
    is_hallucinated: bool
    confidence: float  # 0.0-1.0, higher = more likely hallucinated
    issues: List[str]
    recommendation: str
    scores: Dict[str, float]


class HallucinationDetector:
    """
    Multi-layer hallucination detection system
    
    Checks:
    1. Factual consistency (facts from context?)
    2. Semantic alignment (does answer address question?)
    3. Length plausibility (reasonable length?)
    4. Citation presence (proper citations?)
    5. Confidence markers (uncertain language?)
    """
    
    def __init__(self, db_store=None, embedding_engine=None):
        """
        Initialize detector
        
        Args:
            db_store: Database store for file access counts
            embedding_engine: Embedding engine for semantic checks
        """
        self.db_store = db_store
        self.embedding_engine = embedding_engine
    
    def detect_hallucination(self, 
                            question: str, 
                            answer: str, 
                            context: List[str],
                            model_name: str = "unknown") -> HallucinationResult:
        """
        Check if answer is hallucinated (not grounded in context)
        
        Args:
            question: Original user question
            answer: LLM-generated answer
            context: List of retrieved context chunks
            model_name: Name of LLM model (for logging)
        
        Returns:
            HallucinationResult with detailed analysis
        """
        
        issues = []
        scores = {}
        
        # Check 1: Factual consistency
        factual_score = self._check_factual_consistency(answer, context)
        scores['factual'] = factual_score
        if factual_score < 0.5:
            issues.append("Answer contains facts not found in provided context")
        
        # Check 2: Semantic alignment
        if self.embedding_engine:
            semantic_score = self._check_semantic_alignment(question, answer, context)
            scores['semantic'] = semantic_score
            if semantic_score < 0.5:
                issues.append("Answer doesn't semantically align with question")
        else:
            semantic_score = 0.5
            scores['semantic'] = semantic_score
        
        # Check 3: Length plausibility
        length_score = self._check_length_plausibility(answer, context)
        scores['length'] = length_score
        if length_score < 0.5:
            issues.append("Answer length implausible given context size")
        
        # Check 4: Citation presence
        citation_score = self._check_citation_score(answer, context)
        scores['citation'] = citation_score
        if citation_score < 0.3:
            issues.append("Answer lacks proper citations to source material")
        
        # Check 5: Confidence markers
        confidence_markers = self._detect_confidence_markers(answer)
        if confidence_markers['uncertain_ratio'] > 0.3:
            issues.append("Answer contains many uncertain phrases (might, possibly, etc.)")
        
        # Calculate overall hallucination probability
        avg_score = np.mean([factual_score, semantic_score, length_score, citation_score])
        hallucination_confidence = 1.0 - avg_score
        
        # Generate recommendation
        recommendation = self._recommend_action(
            hallucination_confidence, 
            issues,
            model_name
        )
        
        return HallucinationResult(
            is_hallucinated=hallucination_confidence > 0.6,
            confidence=hallucination_confidence,
            issues=issues,
            recommendation=recommendation,
            scores=scores
        )
    
    def _check_factual_consistency(self, answer: str, context: List[str]) -> float:
        """
        Check if answer facts are actually in context
        Returns: 0.0-1.0 (higher = more consistent)
        """
        # Extract key facts/entities from answer
        answer_facts = self._extract_facts(answer)
        
        # Extract facts from context
        context_facts = set()
        for chunk in context:
            context_facts.update(self._extract_facts(chunk))
        
        # Calculate overlap
        if not answer_facts:
            return 0.5  # No facts extracted, neutral score
        
        overlap = len(answer_facts & context_facts) / len(answer_facts)
        
        # Boost score if we find strong factual grounding
        if overlap >= 0.8:
            return 0.95
        elif overlap >= 0.6:
            return 0.75
        elif overlap >= 0.4:
            return 0.55
        else:
            return 0.30
    
    def _check_semantic_alignment(self, question: str, answer: str, 
                                  context: List[str]) -> float:
        """
        Check if answer is semantically related to question and context
        Returns: 0.0-1.0 (higher = better alignment)
        """
        try:
            # Embed question, answer, and contexts
            q_embedding = self.embedding_engine.embed_text(question)
            a_embedding = self.embedding_engine.embed_text(answer)
            c_embeddings = [self.embedding_engine.embed_text(c) for c in context]
            
            # Calculate similarities
            q_a_similarity = self._cosine_similarity(q_embedding, a_embedding)
            
            # Calculate context relevance
            c_q_similarities = [self._cosine_similarity(c_emb, q_embedding) 
                              for c_emb in c_embeddings]
            avg_context_relevance = np.mean(c_q_similarities) if c_q_similarities else 0.0
            
            # Combined score: both question-answer similarity and context relevance matter
            combined = (q_a_similarity * 0.6 + avg_context_relevance * 0.4)
            
            return max(0.0, min(1.0, combined))
        
        except Exception as e:
            print(f"Error in semantic alignment check: {e}")
            return 0.5  # Neutral if embedding fails
    
    def _check_length_plausibility(self, answer: str, context: List[str]) -> float:
        """
        Check if answer length is reasonable given context
        Returns: 0.0-1.0 (higher = more plausible)
        """
        answer_words = len(answer.split())
        context_words = sum(len(c.split()) for c in context)
        
        # Protect against division by zero
        if context_words == 0:
            return 0.5
        
        # Calculate ratio
        ratio = answer_words / context_words
        
        # Ideal range: 5-30% of context size
        if 0.05 <= ratio <= 0.30:
            return 1.0
        elif 0.02 <= ratio <= 0.50:
            return 0.7
        elif 0.01 <= ratio <= 1.0:
            return 0.4
        else:
            return 0.1  # Way too short or too long
    
    def _check_citation_score(self, answer: str, context: List[str]) -> float:
        """
        Check if answer properly cites sources
        Returns: 0.0-1.0 (higher = better cited)
        """
        # Look for citation patterns
        citation_patterns = [
            r'\[.*?\]',           # [Source]
            r'\(.*?\..*?\)',       # (Source, etc.)
            r'".*?"',              # "quote"
            r'According to',
            r'As stated in',
            r'From',
        ]
        
        citations_found = 0
        for pattern in citation_patterns:
            citations_found += len(re.findall(pattern, answer))
        
        # Should have ~1 citation per 100 words
        answer_words = len(answer.split())
        expected_citations = max(1, answer_words / 100)
        
        citation_ratio = min(1.0, citations_found / expected_citations)
        return citation_ratio
    
    def _detect_confidence_markers(self, answer: str) -> Dict[str, float]:
        """
        Detect words indicating uncertainty
        Returns: dict with uncertainty metrics
        """
        uncertain_words = {
            'might': 0.2, 'possibly': 0.2, 'maybe': 0.3,
            'could': 0.15, 'may': 0.15, 'approximately': 0.1,
            'likely': 0.15, 'seems': 0.2, 'appears': 0.15,
            'apparently': 0.2, 'supposedly': 0.25
        }
        
        answer_lower = answer.lower()
        total_uncertainty = 0
        
        for word, weight in uncertain_words.items():
            count = answer_lower.count(' ' + word + ' ')  # Word boundaries
            total_uncertainty += count * weight
        
        answer_words = len(answer.split())
        uncertain_ratio = total_uncertainty / max(answer_words, 1)
        
        # Count certain markers
        certain_patterns = ['confirmed', 'verified', 'proven', 'clearly', 'definitely']
        certain_count = sum(len(re.findall(r'\b' + p + r'\b', answer_lower)) 
                           for p in certain_patterns)
        
        return {
            'uncertain_ratio': uncertain_ratio,
            'certain_markers': certain_count
        }
    
    def _extract_facts(self, text: str) -> set:
        """
        Extract key facts/entities from text
        Returns: set of fact strings
        """
        facts = set()
        
        # Extract numbers
        numbers = re.findall(r'\b\d+(?:\.\d+)?\b', text)
        facts.update(numbers)
        
        # Extract dates (YYYY-MM-DD or DD/MM/YYYY)
        dates = re.findall(r'\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b', text)
        facts.update(dates)
        
        # Extract proper nouns (capitalized words)
        proper_nouns = re.findall(r'\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*\b', text)
        facts.update(proper_nouns)
        
        # Extract quoted phrases
        quotes = re.findall(r'"([^"]*)"', text)
        facts.update(quotes)
        
        return facts
    
    @staticmethod
    def _cosine_similarity(vec1: np.ndarray, vec2: np.ndarray) -> float:
        """Calculate cosine similarity between two vectors"""
        try:
            vec1 = np.array(vec1, dtype=np.float32)
            vec2 = np.array(vec2, dtype=np.float32)
            
            norm1 = np.linalg.norm(vec1)
            norm2 = np.linalg.norm(vec2)
            
            if norm1 == 0 or norm2 == 0:
                return 0.0
            
            return float(np.dot(vec1, vec2) / (norm1 * norm2))
        except Exception:
            return 0.0
    
    def _recommend_action(self, confidence: float, issues: List[str], 
                         model_name: str) -> str:
        """Generate user-facing recommendation based on analysis"""
        
        if confidence > 0.8:
            return (
                f"⚠️ HIGH RISK HALLUCINATION\n"
                f"Do NOT trust this answer. The model ({model_name}) likely made up information.\n"
                f"Issues detected: {len(issues)}\n"
                f"Recommendation: Rephrase question and search again."
            )
        elif confidence > 0.6:
            return (
                f"⚠️ MODERATE RISK\n"
                f"Use with caution. Verify key facts independently.\n"
                f"Issues found: {len(issues)}"
            )
        elif confidence > 0.4:
            return (
                f"✓ PARTIAL CONFIDENCE\n"
                f"Probably accurate but has some uncertainties.\n"
                f"Verify important claims."
            )
        else:
            return (
                f"✓ HIGH CONFIDENCE\n"
                f"Answer appears well-grounded in provided context."
            )


# Convenience function for easy integration
def check_answer_reliability(question: str, answer: str, context: List[str]) -> Dict:
    """
    Quick check function for answer reliability
    
    Usage:
        result = check_answer_reliability(
            "What is machine learning?",
            "Machine learning is...",
            ["ML is an AI technique...", "Deep learning is a subset..."]
        )
        if result['is_hallucinated']:
            print(result['recommendation'])
    """
    detector = HallucinationDetector()
    result = detector.detect_hallucination(question, answer, context)
    
    return {
        'is_hallucinated': result.is_hallucinated,
        'confidence': result.confidence,
        'issues': result.issues,
        'recommendation': result.recommendation,
        'scores': result.scores
    }
