"""
Phase 3.2: RAG Engine - Hallucination Detector Integration
Hooks hallucination detection into all RAG operations
"""

from ai.hallucination_detector import HallucinationDetector, HallucinationResult


class RAGHallucinationIntegration:
    """Integration point for hallucination detection in RAG"""
    
    @staticmethod
    def add_to_rag_engine():
        """Methods to add to RAGEngine class"""
        pass


# METHODS TO ADD TO RAGEngine CLASS:

def __init_hallucination_detector(self):
    """Initialize hallucination detector in RAGEngine.__init__"""
    self.hallucination_detector = HallucinationDetector(
        db_store=getattr(self, 'db_store', None),
        embedding_engine=getattr(self, 'embedding_engine', None)
    )


def _check_answer_safety(self, question: str, answer: str, context_blocks: list) -> dict:
    """
    Check if answer is safe (not hallucinated) before returning to user
    
    Args:
        question: Original user question
        answer: Generated answer from LLM
        context_blocks: Retrieved context chunks
    
    Returns:
        Dictionary with safety check results
    """
    try:
        hallucination_check = self.hallucination_detector.detect_hallucination(
            question=question,
            answer=answer,
            context=context_blocks,
            model_name=getattr(self, 'model_name', 'unknown')
        )
        
        return {
            'safe': not hallucination_check.is_hallucinated,
            'confidence': hallucination_check.confidence,
            'issues': hallucination_check.issues,
            'recommendation': hallucination_check.recommendation,
            'scores': hallucination_check.scores
        }
    
    except Exception as e:
        print(f"Error in hallucination check: {e}")
        return {
            'safe': True,  # Fail open
            'confidence': 0.5,
            'issues': [f'Safety check error: {str(e)}'],
            'recommendation': 'Could not verify answer safety',
            'scores': {}
        }


def _wrap_answer_with_safety_notice(self, answer: str, safety_check: dict) -> str:
    """
    Wrap answer with safety notices if needed
    
    Args:
        answer: Original answer
        safety_check: Safety check results
    
    Returns:
        Answer potentially with warnings prepended
    """
    if safety_check['safe']:
        return answer
    
    confidence = safety_check['confidence']
    
    if confidence > 0.8:
        warning = (
            "⚠️ HIGH RISK - LIKELY HALLUCINATION ⚠️\n"
            f"{safety_check['recommendation']}\n\n"
            "ORIGINAL ANSWER (DO NOT TRUST):\n"
            f"{answer}\n\n"
            "ISSUES:\n"
            + "\n".join(f"• {issue}" for issue in safety_check['issues'])
        )
    elif confidence > 0.6:
        warning = (
            "⚠️ MODERATE RISK - VERIFY BEFORE USE ⚠️\n"
            f"{safety_check['recommendation']}\n\n"
            "ANSWER:\n"
            f"{answer}\n\n"
            "POTENTIAL ISSUES:\n"
            + "\n".join(f"• {issue}" for issue in safety_check['issues'])
        )
    else:
        warning = answer
    
    return warning


# MODIFIED ask() METHOD PATTERN:

ask_method_pattern = """
def ask(self, query, file_paths=None, rag_enabled=True):
    '''Ask question with hallucination detection'''
    
    # ... existing code to build context and generate answer ...
    
    # NEW: After generating answer, add this:
    
    # Check for hallucination
    safety_check = self._check_answer_safety(
        question=query,
        answer=answer,
        context_blocks=context_blocks
    )
    
    # Wrap with safety notice if needed
    answer = self._wrap_answer_with_safety_notice(answer, safety_check)
    
    # Add safety metadata to response
    response.hallucination_risk = safety_check['confidence']
    response.safety_verified = safety_check['safe']
    response.safety_issues = safety_check['issues']
    
    return response
"""


# INTEGRATION CHECKLIST:

integration_checklist = """
PHASE 3.2 INTEGRATION - RAG HALLUCINATION DETECTION

Step 1: Import hallucination detector
  ├─ Add: from ai.hallucination_detector import HallucinationDetector
  └─ Location: Top of engines/rag_engine.py

Step 2: Initialize detector in RAGEngine.__init__
  ├─ Add: self.hallucination_detector = HallucinationDetector(...)
  └─ Location: RAGEngine.__init__ method

Step 3: Add safety check methods
  ├─ Add: _check_answer_safety() method
  ├─ Add: _wrap_answer_with_safety_notice() method
  └─ Location: RAGEngine class

Step 4: Integrate into ask() method
  ├─ Call: safety_check = self._check_answer_safety(...)
  ├─ Call: answer = self._wrap_answer_with_safety_notice(...)
  ├─ Set: response.hallucination_risk = safety_check['confidence']
  └─ Location: End of ask() method, before return

Step 5: Test integration
  ├─ Run: pytest tests/test_rag_hallucination.py
  ├─ Verify: Safety warnings appear on risky answers
  └─ Verify: Safe answers pass through unchanged

RESULT: All RAG answers now have hallucination detection!
"""
