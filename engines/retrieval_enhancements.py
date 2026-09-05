"""
Phase 2.1: Retrieval Engine Enhancements
Adds confidence scoring, filtering, and query expansion to improve search results quality
"""

from typing import List, Dict
import numpy as np


class RetrievalEnhancementsMixin:
    """Mixin for RetrievalEngine to add Phase 2 features"""
    
    def score_result_relevance(self, query: str, result) -> float:
        """
        Score how relevant a result is to the query (0.0-1.0)
        Higher score = more confident in the result
        
        Factors:
        - Base similarity score (60%)
        - Chunk quality (40%)
        """
        try:
            similarity_score = getattr(result, 'similarity_score', 0.0)
            
            # Check chunk quality (50 words is optimal)
            text_length = len(result.text.split())
            optimal_length = 50
            
            if text_length == 0:
                chunk_quality = 0.0
            elif text_length < 20:
                chunk_quality = 0.3  # Too short
            elif text_length < optimal_length:
                chunk_quality = 0.5 + (text_length / optimal_length) * 0.5
            elif text_length < optimal_length * 2:
                chunk_quality = 1.0 - ((text_length - optimal_length) / optimal_length) * 0.4
            else:
                chunk_quality = 0.5  # Too long
            
            chunk_quality = max(0.0, min(1.0, chunk_quality))
            
            # Weighted combination
            confidence = (
                similarity_score * 0.6 +  # 60% weight on similarity
                chunk_quality * 0.4        # 40% weight on chunk quality
            )
            
            return max(0.0, min(1.0, confidence))
        
        except Exception as e:
            print(f"Error scoring result: {e}")
            return 0.5
    
    def filter_results_by_confidence(self, results: List, 
                                     min_confidence: float = 0.5) -> List:
        """
        Filter results to only include high-confidence matches
        
        Args:
            results: List of RetrievalResult objects
            min_confidence: Minimum confidence threshold (0.0-1.0)
        
        Returns:
            Filtered list of results above threshold
        """
        filtered = []
        for result in results:
            score = self.score_result_relevance("", result)
            if score >= min_confidence:
                filtered.append(result)
        
        return filtered
    
    def expand_query(self, query: str) -> List[str]:
        """
        Expand query with related terms and synonyms for better retrieval
        
        Example:
            "machine learning" → ["machine learning", "deep learning", "AI", "neural networks"]
        
        Args:
            query: Original user query
        
        Returns:
            List of expanded queries (original + synonyms)
        """
        # Synonym mappings
        synonym_map = {
            "machine learning": ["deep learning", "AI", "neural networks", "algorithms"],
            "neural network": ["deep learning", "neural", "network architecture"],
            "pdf": ["document", "file", "text"],
            "image": ["picture", "photo", "visual", "graphic"],
            "error": ["bug", "issue", "problem", "failure", "exception"],
            "fast": ["quick", "speedy", "rapid", "efficient"],
            "slow": ["sluggish", "lagging", "delay"],
            "large": ["big", "huge", "massive"],
            "small": ["tiny", "little", "compact"],
            "similar": ["same", "alike", "comparable"],
            "different": ["distinct", "different", "varied"],
        }
        
        expanded_queries = [query]  # Always include original
        query_lower = query.lower()
        
        # Check for keyword matches
        for keyword, synonyms in synonym_map.items():
            if keyword in query_lower:
                # Add all synonyms
                expanded_queries.extend(synonyms)
                break  # Only expand first match to avoid explosion
        
        # Remove duplicates while preserving order
        seen = set()
        unique_queries = []
        for q in expanded_queries:
            if q.lower() not in seen:
                seen.add(q.lower())
                unique_queries.append(q)
        
        return unique_queries
    
    def smart_retrieve_with_expansion(self, query: str, scope=None, top_k: int = 50) -> object:
        """
        Retrieve using query expansion for better coverage
        
        Strategy:
        1. Expand query with synonyms
        2. Search with all queries
        3. Deduplicate and merge results
        4. Filter by confidence
        5. Rank by combined score
        
        Args:
            query: User query
            scope: Search scope (ChatScope)
            top_k: Maximum results to return
        
        Returns:
            RetrievalResponse with high-confidence results
        """
        try:
            all_results = []
            seen_files = set()
            
            # Expand query
            expanded_queries = self.expand_query(query)
            
            # Search with each query
            for expanded_query in expanded_queries:
                try:
                    # Embed expanded query
                    query_vec = self.embedding_engine.embed_text(expanded_query)
                    
                    # Retrieve results
                    results = self.retrieve(query_vec, scope=scope, top_k=top_k * 2)
                    
                    # Add to pool, avoiding duplicates
                    for result in results.results:
                        file_key = result.file_id
                        if file_key not in seen_files:
                            all_results.append(result)
                            seen_files.add(file_key)
                
                except Exception as e:
                    print(f"Error with expanded query '{expanded_query}': {e}")
                    continue
            
            # Deduplicate by file (keep best per file)
            best_per_file = {}
            for result in all_results:
                file_id = result.file_id
                if file_id not in best_per_file:
                    best_per_file[file_id] = result
                elif result.similarity_score > best_per_file[file_id].similarity_score:
                    best_per_file[file_id] = result
            
            dedup_results = list(best_per_file.values())
            
            # Filter by confidence
            confident_results = self.filter_results_by_confidence(
                dedup_results,
                min_confidence=0.5
            )
            
            # Sort by score (descending)
            confident_results.sort(
                key=lambda r: self.score_result_relevance(query, r),
                reverse=True
            )
            
            # Limit to top_k
            final_results = confident_results[:top_k]
            
            # Build response
            from engines.retrieval_engine import RetrievalResponse
            return RetrievalResponse(
                results=final_results,
                scope=scope
            )
        
        except Exception as e:
            print(f"Error in smart_retrieve_with_expansion: {e}")
            # Fallback to regular retrieve
            query_vec = self.embedding_engine.embed_text(query)
            return self.retrieve(query_vec, scope=scope, top_k=top_k)


# Instructions for integration:
# 
# In retrieval_engine.py, add this to RetrievalEngine class:
#
#     def score_result_relevance(self, query, result):
#         # Copy from RetrievalEnhancementsMixin.score_result_relevance above
#         pass
#
#     def filter_results_by_confidence(self, results, min_confidence=0.5):
#         # Copy from RetrievalEnhancementsMixin.filter_results_by_confidence above
#         pass
#
#     def expand_query(self, query):
#         # Copy from RetrievalEnhancementsMixin.expand_query above
#         pass
#
#     def smart_retrieve_with_expansion(self, query, scope=None, top_k=50):
#         # Copy from RetrievalEnhancementsMixin.smart_retrieve_with_expansion above
#         pass
