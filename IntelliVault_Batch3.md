# IntelliVault Batch 3 – AI Knowledge & Retrieval Engine

## Master Implementation Plan

### Architecture Principle

Batch 3 is centered around a **single reusable Retrieval Engine**.
Semantic Search, Ask Selected File, Similar Documents, and Basic RAG all reuse this engine.

## Objectives

- Universal Content Extraction
- Evidence Builder
- Embedding Engine
- Vector Index (FAISS)
- Retrieval Engine
- Basic RAG
- Ask Selected File
- Semantic Search
- Similar Documents
- Evidence Navigation

## Technology Stack

### Models
- Qwen 2.5 (Reasoning)
- nomic-embed-text via Ollama (Embeddings)
- SmolVLM (Vision)
- Whisper Base (Speech)

### Libraries
- PySide6
- SQLite
- PyMuPDF
- python-docx
- python-pptx
- openpyxl
- PaddleOCR
- OpenCV
- ffmpeg-python
- faiss-cpu
- numpy

## Core Engines

1. Universal Content Extraction Engine
2. OCR Engine
3. Vision Engine
4. Speech Engine
5. Video Engine
6. Evidence Engine
7. Embedding Engine
8. Vector Engine (FAISS)
9. Retrieval Engine
10. Basic RAG Engine

## Retrieval Engine

Single API:

retrieve(query, scope, top_k)

Scopes:
- Selected File
- Folder
- Workspace
- Selected Files

Every feature consumes this API.

## Workflows

### Indexing

File
-> Universal Extraction
-> Evidence Builder
-> Embeddings
-> FAISS
-> SQLite

### Semantic Search

Query
-> Embedding
-> Retrieval Engine
-> Evidence
-> Results UI

### Ask Selected File

Question
-> Retrieval Engine (Selected File)
-> Qwen
-> Grounded Answer
-> Citations

## UI

- Universal Search Bar
- Semantic Results
- Ask AI (Selected File)
- Similar Documents
- Evidence Preview
- Confidence Score
- Open at Page / Timestamp
- Index Manager

## Database

Tables

- evidence
- embeddings
- vector_map
- ocr_results
- captions
- transcripts
- search_history

## Unit Tests

- OCR
- Vision
- Whisper
- Extraction
- Embeddings
- FAISS
- Retrieval Engine
- Prompt Builder
- Basic RAG
- SQLite
- Cache
- SHA-256

## Integration Tests

1. PDF Search
2. OCR Search
3. Image Search
4. Audio Search
5. Video Search
6. Ask Selected File
7. Similar Documents
8. Rename File
9. Move File
10. Modify File
11. Rebuild Index
12. Recovery
13. Page Navigation
14. Timestamp Navigation
15. Folder Search
16. Workspace Search

## Acceptance Criteria

- All supported file types searchable.
- Exact evidence location returned.
- Ask Selected File produces grounded answers.
- Retrieval Engine reused everywhere.
- Batch 1 & Batch 2 remain compatible.
- UI remains responsive.
- All tests pass.

## Future Batch 4

- Persistent conversations
- Folder Chat
- Workspace Chat
- Multi-document reasoning
- Knowledge Graphs
- Agentic workflows

Batch 4 builds on the Retrieval Engine without architectural changes.
