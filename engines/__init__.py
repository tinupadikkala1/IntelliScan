"""Engines module for IntelliVault Batch 3.

Provides structured content extraction, evidence chunking, embeddings,
vector search, and retrieval for semantic search capabilities.
"""

from .content_engine import ContentBlock, UniversalContentEngine
from .embedding_engine import EmbeddingEngine
from .evidence_engine import EvidenceChunk, EvidenceEngine
from .rag_engine import Citation, RAGEngine, RAGResponse
from .retrieval_engine import RetrievalEngine, RetrievalResponse, RetrievalResult, RetrievalScope
from .vector_engine import SearchResult, VectorEngine

# Public aliases
ContentEngine = UniversalContentEngine

__all__ = [
    "Citation",
    "ContentBlock",
    "ContentEngine",
    "EmbeddingEngine",
    "EvidenceChunk",
    "EvidenceEngine",
    "RAGEngine",
    "RAGResponse",
    "RetrievalEngine",
    "RetrievalResponse",
    "RetrievalResult",
    "RetrievalScope",
    "SearchResult",
    "UniversalContentEngine",
    "VectorEngine",
]
