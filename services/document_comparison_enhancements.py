"""
Phase 2.3: Document Comparison Enhancements
Implements 3-method validation for accurate document comparison
Methods: Textual, Structural, Semantic
"""

import difflib
import re
from typing import Dict, List
from dataclasses import dataclass


@dataclass
class ComparisonMethodResult:
    """Result from one comparison method"""
    method_name: str
    similarities: List[str]
    differences: List[Dict]
    confidence: float
    details: Dict


class DocumentComparisonEnhancements:
    """3-method comparison system for documents"""
    
    @staticmethod
    def textual_diff(text1: str, text2: str) -> Dict:
        """
        METHOD 1: Line-by-line textual comparison
        
        Strategy:
        - Split into lines
        - Use SequenceMatcher to find common/different lines
        - Calculate similarity ratio
        
        Returns:
            Dict with similarities, differences, ratio
        """
        lines1 = text1.split('\n')
        lines2 = text2.split('\n')
        
        matcher = difflib.SequenceMatcher(None, lines1, lines2)
        
        similarities = []
        differences = []
        
        # Extract opcodes
        for tag, i1, i2, j1, j2 in matcher.get_opcodes():
            if tag == 'equal':
                # Lines that match
                similarities.extend(lines1[i1:i2])
            else:
                # Lines that differ
                differences.append({
                    'type': tag,  # replace, delete, insert
                    'original': lines1[i1:i2],
                    'modified': lines2[j1:j2]
                })
        
        return {
            'method': 'Textual (Line-by-Line)',
            'similarities': similarities,
            'differences': differences,
            'similarity_ratio': matcher.ratio(),
            'matching_lines': len([l for l in matcher.get_matching_blocks() if l.size > 0])
        }
    
    @staticmethod
    def structural_analysis(content1, content2) -> Dict:
        """
        METHOD 2: Structural analysis
        
        Strategy:
        - Compare length, word count
        - Extract and compare sections/headers
        - Analyze formatting differences
        
        Returns:
            Dict with structural comparisons
        """
        text1 = getattr(content1, 'text', str(content1))
        text2 = getattr(content2, 'text', str(content2))
        
        # Length metrics
        length_diff = len(text2) - len(text1)
        word_count1 = len(text1.split())
        word_count2 = len(text2.split())
        word_diff = word_count2 - word_count1
        
        # Extract sections/headers (lines starting with # or ----)
        def extract_sections(text):
            sections = []
            for line in text.split('\n'):
                if line.startswith('#') or line.startswith('===') or line.startswith('---'):
                    sections.append(line.strip())
            return sections
        
        sections1 = extract_sections(text1)
        sections2 = extract_sections(text2)
        
        # Compare sections
        missing_sections = set(sections1) - set(sections2)
        new_sections = set(sections2) - set(sections1)
        
        return {
            'method': 'Structural Analysis',
            'length_diff': length_diff,
            'word_count_diff': word_diff,
            'sections_1': len(sections1),
            'sections_2': len(sections2),
            'missing_sections': list(missing_sections),
            'new_sections': list(new_sections),
            'similarity_ratio': (len(set(sections1) & set(sections2)) / max(len(sections1), len(sections2))) if max(len(sections1), len(sections2)) > 0 else 0
        }
    
    @staticmethod
    def semantic_diff(text1: str, text2: str, embedding_engine=None) -> Dict:
        """
        METHOD 3: Semantic comparison using embeddings
        
        Strategy:
        - Chunk text into meaningful units
        - Generate embeddings for each chunk
        - Compare semantic similarity
        - Find conceptually similar vs different chunks
        
        Args:
            text1: First document text
            text2: Second document text
            embedding_engine: Optional embedding engine for semantic analysis
        
        Returns:
            Dict with semantic comparisons
        """
        if not embedding_engine:
            return {
                'method': 'Semantic Analysis',
                'status': 'Embedding engine not available',
                'similarity': 'unknown'
            }
        
        try:
            # Chunk texts
            def chunk_text(text, chunk_size=100):
                """Split text into chunks of ~chunk_size words"""
                words = text.split()
                chunks = []
                for i in range(0, len(words), chunk_size):
                    chunk = ' '.join(words[i:i+chunk_size])
                    if chunk.strip():
                        chunks.append(chunk)
                return chunks
            
            chunks1 = chunk_text(text1)
            chunks2 = chunk_text(text2)
            
            # Generate embeddings
            embeddings1 = [embedding_engine.embed_text(c) for c in chunks1]
            embeddings2 = [embedding_engine.embed_text(c) for c in chunks2]
            
            # Calculate similarities
            def cosine_similarity(v1, v2):
                import numpy as np
                try:
                    v1 = np.array(v1, dtype=np.float32)
                    v2 = np.array(v2, dtype=np.float32)
                    return float(np.dot(v1, v2) / (np.linalg.norm(v1) * np.linalg.norm(v2)))
                except:
                    return 0.0
            
            # Find similar chunks
            similar_chunks = []
            for e1, c1 in zip(embeddings1, chunks1):
                for e2, c2 in zip(embeddings2, chunks2):
                    sim = cosine_similarity(e1, e2)
                    if sim > 0.7:
                        similar_chunks.append({
                            'chunk1': c1[:50] + '...',
                            'chunk2': c2[:50] + '...',
                            'similarity': round(sim, 3)
                        })
            
            return {
                'method': 'Semantic Analysis',
                'total_chunks_1': len(chunks1),
                'total_chunks_2': len(chunks2),
                'similar_chunks': len(similar_chunks),
                'overall_semantic_similarity': sum(s['similarity'] for s in similar_chunks) / max(len(similar_chunks), 1) if similar_chunks else 0,
                'details': similar_chunks[:5]  # Top 5 similar chunks
            }
        
        except Exception as e:
            return {
                'method': 'Semantic Analysis',
                'status': f'Error: {str(e)}',
                'similarity': 'error'
            }
    
    @staticmethod
    def consolidate_results(textual_result: Dict, structural_result: Dict, 
                           semantic_result: Dict) -> Dict:
        """
        Consolidate all 3 methods into final verdict
        
        Strategy:
        - Weight each method
        - Detect agreement/disagreement
        - Generate confidence score
        - Produce final summary
        
        Returns:
            Consolidated comparison result
        """
        
        # Extract confidence scores from each method
        textual_conf = textual_result.get('similarity_ratio', 0)
        structural_conf = structural_result.get('similarity_ratio', 0) if 'similarity_ratio' in structural_result else 0.5
        semantic_conf = semantic_result.get('overall_semantic_similarity', 0.5) if 'overall_semantic_similarity' in semantic_result else 0.5
        
        # Weighted average
        overall_confidence = (
            textual_conf * 0.4 +  # 40% weight on textual
            structural_conf * 0.3 +  # 30% weight on structural
            semantic_conf * 0.3    # 30% weight on semantic
        )
        
        # Check method agreement
        methods_agree = abs(textual_conf - structural_conf) < 0.2
        
        return {
            'overall_similarity': round(overall_confidence, 3),
            'methods': {
                'textual': textual_result,
                'structural': structural_result,
                'semantic': semantic_result
            },
            'methods_agree': methods_agree,
            'verdict': 'Similar' if overall_confidence > 0.6 else 'Different',
            'confidence': 'High' if overall_confidence > 0.75 else 'Medium' if overall_confidence > 0.5 else 'Low'
        }


# INTEGRATION CODE FOR document_comparison_service.py:

integration_code = """
# Add these methods to DocumentComparisonService class:

def _textual_diff(self, text1, text2):
    from services.document_comparison_enhancements import DocumentComparisonEnhancements
    return DocumentComparisonEnhancements.textual_diff(text1, text2)

def _structural_analysis(self, content1, content2):
    from services.document_comparison_enhancements import DocumentComparisonEnhancements
    return DocumentComparisonEnhancements.structural_analysis(content1, content2)

def _semantic_diff(self, text1, text2):
    from services.document_comparison_enhancements import DocumentComparisonEnhancements
    return DocumentComparisonEnhancements.semantic_diff(text1, text2, self.embedding_engine)

def compare(self, file1_path, file2_path):
    '''Compare using 3 methods'''
    
    # Extract content
    content1 = self._extract_content(file1_path)
    content2 = self._extract_content(file2_path)
    
    # Method 1: Textual
    textual = self._textual_diff(content1.text, content2.text)
    
    # Method 2: Structural
    structural = self._structural_analysis(content1, content2)
    
    # Method 3: Semantic
    semantic = self._semantic_diff(content1.text, content2.text)
    
    # Consolidate
    from services.document_comparison_enhancements import DocumentComparisonEnhancements
    result = DocumentComparisonEnhancements.consolidate_results(textual, structural, semantic)
    
    return ComparisonResult(
        file1=file1_path,
        file2=file2_path,
        similarities=textual.get('similarities', [])[:5],
        differences=textual.get('differences', [])[:5],
        detailed_analysis=result
    )
"""
