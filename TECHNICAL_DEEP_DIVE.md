# IntelliScan - Technical Deep Dive & Code Workflow

**Focus:** Core engine workflows, data flow, and implementation details  
**Audience:** Developers and architects  
**Last Updated:** September 5, 2026

---

## Part 1: Core Data Flows & Workflows

### 1.1 File Indexing Workflow

```
USER ACTION: Select Folder to Index
         ↓
[ MAIN WINDOW ]
  └─ _on_scan_requested()
         ↓
[ TASK MANAGER ] - Spawn background worker
         ↓
[ AI_FOLDER_INDEXER ] 
  ├─ _discover_files(folder_path)          # Recursively scan files
  │   └─ Yield: (path, priority)
  │       • .py files: priority 1
  │       • Images: priority 2
  │       • Videos: priority 5 (slow)
  │
  ├─ For each file in priority order:
  │   ├─ _index_file(path)
  │   │   ├─ MetadataExtractor.extract()
  │   │   │   └─ MIME, size, mtime, SHA-256
  │   │   │
  │   │   ├─ ContentEngine.extract(path)
  │   │   │   ├─ Detect file type
  │   │   │   ├─ Route to appropriate extractor:
  │   │   │   │   • PDF → PyMuPDF
  │   │   │   │   • DOCX → python-docx
  │   │   │   │   • Image → Pillow (+ OCR if Tesseract available)
  │   │   │   │   • Audio → Whisper transcription
  │   │   │   │   • Video → Keyframe extraction
  │   │   │   └─ Return: [ContentBlock(modality, text, metadata)]
  │   │   │
  │   │   ├─ EvidenceEngine._build_chunk()
  │   │   │   └─ Create sliding-window chunks (overlap=50%)
  │   │   │       Each chunk: text + source location (page, timestamp, etc.)
  │   │   │
  │   │   ├─ EmbeddingEngine.embed_batch(chunks)
  │   │   │   ├─ Call Ollama: /api/embed (or load sentence-transformers)
  │   │   │   └─ Return: Vector[] (384-dim or 768-dim depending on model)
  │   │   │
  │   │   ├─ Store in Database:
  │   │   │   ├─ File record (metadata, SHA-256)
  │   │   │   ├─ Evidence records (chunks, modality)
  │   │   │   └─ VectorMap (embedding-to-chunk mapping)
  │   │   │
  │   │   ├─ Store in FAISS:
  │   │   │   ├─ VectorEngine.add_batch(vectors, chunk_ids)
  │   │   │   └─ Persist to disk: cache/faiss_index.bin
  │   │   │
  │   │   └─ Emit progress signal
  │   │
  │   └─ Repeat for next file
  │
  └─ IndexingResult(total, successful, failed, time_elapsed)
         ↓
[ MAIN WINDOW ] UI update: "Indexed 1,234 files in 45 seconds"
```

**Key Classes:**
- `AIFolderIndexer` - Main indexing orchestrator
- `MetadataExtractor` - System-level metadata
- `UniversalContentEngine` - Content extraction router
- `EvidenceEngine` - Text chunking
- `EmbeddingEngine` - Vector generation
- `VectorEngine` - FAISS wrapper
- `EngineDBStore` - Persistence

**Database Tables Updated:**
- `file` - File metadata
- `evidence` - Text chunks with locations
- `vector_map` - Embedding-to-chunk links
- `ai_analysis` - Analysis results cache

---

### 1.2 Semantic Search Workflow

```
USER ACTION: "Find all PDFs about machine learning"
         ↓
[ SEMANTIC SEARCH DIALOG ]
  └─ _on_search(query="machine learning", modality="documents")
         ↓
[ RETRIEVAL ENGINE ]
  ├─ Step 1: Query Embedding
  │   ├─ EmbeddingEngine.embed_text("machine learning")
  │   └─ Return: query_vector (768-dim)
  │
  ├─ Step 2: Vector Search
  │   ├─ VectorEngine.search(query_vector, k=50, threshold=0.3)
  │   └─ Return: [(chunk_id, similarity_score), ...] sorted by score
  │
  ├─ Step 3: Hydrate Results
  │   ├─ For each chunk_id:
  │   │   ├─ Load Evidence record from DB
  │   │   │   └─ Get: text, file_id, page_num, timestamp
  │   │   ├─ Load File record from DB
  │   │   │   └─ Get: path, size, mtime, extension
  │   │   └─ Build RetrievalResult(file, evidence, score)
  │   │
  │   └─ Return: RetrievalResponse(results=[], scope=ChatScope)
  │
  ├─ Step 4: Filter & Rank
  │   ├─ By Modality: filter_results_by_modality(results, "documents")
  │   │   └─ Keep only PDFs (.pdf), Word (.docx), etc.
  │   ├─ By File Scope: scope_manager.filter_results(results)
  │   │   └─ Keep only files in selected folder/workspace
  │   └─ Deduplicate: _deduplicate_by_file()
  │       └─ Show best result per file
  │
  ├─ Step 5: Calculate Strengths
  │   ├─ match_strength(score):
  │   │   ├─ score >= 0.7 → "High"
  │   │   ├─ score >= 0.5 → "Medium"
  │   │   └─ score <  0.5 → "Low"
  │   └─ Attach: RetrievalResult.match_strength_label
  │
  └─ Return: Final results to UI
         ↓
[ UI ] Display results:
  ├─ Result 1: "Machine Learning Basics.pdf" (High: 0.87)
  ├─ Result 2: "Deep Learning Chapter 3.pdf" (Medium: 0.62)
  └─ Result 3: "Linear Algebra Notes.pdf" (Low: 0.48)
```

**Key Classes:**
- `RetrievalEngine` - Main search orchestrator
- `VectorEngine` - FAISS queries
- `ScopeManager` - Scope filtering
- `ModalityFilter` - Content-type filtering

**Performance:**
- Vector search: O(log N) with FAISS
- Hydration: N DB queries (batched if possible)
- Total time: ~50-200ms for typical searches

---

### 1.3 RAG (Question Answering) Workflow

```
USER ACTION: "Tell me about the key points in these files"
         ↓
[ ASK AI DIALOG ]
  └─ ask(query, file_paths=[...], llm_available=True)
         ↓
[ RAG ENGINE ]
  ├─ Step 1: Determine Query Intent
  │   ├─ Is it asking about specific files?
  │   │   └─ file_paths provided → Use them
  │   ├─ Is it a followup?
  │   │   └─ resolve_followup(query, conversation_history)
  │   └─ Is it multi-file?
  │       └─ answer_multi(query, file_paths)
  │
  ├─ Step 2: Build Context
  │   ├─ For each target file:
  │   │   ├─ RetrievalEngine.retrieve_similar(query, file_id)
  │   │   │   └─ Find best chunks from that file
  │   │   ├─ Load full content if needed
  │   │   └─ Assemble: context_text
  │   │
  │   └─ Combine all contexts (with separators)
  │
  ├─ Step 3: Rank Results
  │   ├─ RetrievalEngine.rerank_results(query, candidates)
  │   │   └─ Use semantic similarity for ranking
  │   └─ Take top-k results (typically 5-10)
  │
  ├─ Step 4: Build Prompt
  │   ├─ System prompt: "You are a helpful assistant..."
  │   ├─ Context: Insert retrieved chunks
  │   ├─ History: Include previous turns
  │   ├─ Question: The user's query
  │   └─ Format: Structured template
  │
  ├─ Step 5: Call LLM
  │   ├─ If Ollama available:
  │   │   ├─ OllamaClient.generate(prompt, model="neural-chat")
  │   │   ├─ Stream response token-by-token
  │   │   └─ Build: answer_text
  │   │
  │   └─ If Ollama unavailable:
  │       └─ Fallback: Return summarized retrieval results
  │
  ├─ Step 6: Build Citations
  │   ├─ CitationBuilder.from_results(context_chunks)
  │   │   └─ Extract: file, page/timestamp, snippet
  │   └─ Return: Citation[] matching answer text
  │
  └─ Return: RAGResponse(answer, citations, modality_hints)
         ↓
[ CONVERSATION MANAGER ]
  ├─ Store message in ConversationStore
  │   └─ Save: question, answer, citations, file_scope
  ├─ Persist to DB
  │   └─ ConversationMessage + CitationRecord
  └─ Display in Chat UI
```

**Key Classes:**
- `RAGEngine` - Q&A orchestration
- `RetrievalEngine` - Context retrieval
- `PromptBuilder` - Prompt assembly
- `OllamaClient` - LLM interaction
- `ConversationManager` - Chat history
- `CitationBuilder` - Citation extraction

**Fallback Behavior:**
- No Ollama → Use retrieval-only mode (show top chunks)
- No context found → LLM generates from knowledge
- Timeout → Return "Answer not found" with search results

---

### 1.4 File Organization Workflow

```
USER ACTION: "Auto-organize my files"
         ↓
[ ORGANIZE DIALOG ]
  └─ execute_organization(target_folder)
         ↓
[ FILE_ORGANIZER_SERVICE ]
  ├─ Step 1: Discover Candidates
  │   ├─ Get all files in target_folder
  │   ├─ For each file:
  │   │   ├─ ClassificationEngine.category_for_path(file_path)
  │   │   │   ├─ Check AI classification (if analyzed)
  │   │   │   ├─ Check filename patterns
  │   │   │   └─ Check extension mapping
  │   │   │
  │   │   └─ Return: category (e.g., "Documents", "Images")
  │   │
  │   └─ Group by category: {category: [file1, file2, ...]}
  │
  ├─ Step 2: Generate Folder Names
  │   ├─ For each category:
  │   │   ├─ If files < 100:
  │   │   │   └─ Generate name: "Documents" or "Documents_2024"
  │   │   ├─ If files > 100:
  │   │   │   └─ Generate: "Documents", "Images_Work", "Images_Personal"
  │   │   │
  │   │   └─ Validate: No collisions, reserved names
  │   │
  │   └─ Return: {category: "folder_name"}
  │
  ├─ Step 3: Suggest Organization
  │   ├─ Build ProposedFolderCluster[] with:
  │   │   ├─ folder_name
  │   │   ├─ files_count
  │   │   ├─ sample_files
  │   │   └─ estimated_size
  │   │
  │   └─ Show preview: "Move 45 files to /target/Documents?"
  │
  ├─ Step 4: Execute Moves (if approved)
  │   ├─ For each file:
  │   │   ├─ Create target folder if needed
  │   │   ├─ FileMover.move_file(src, dest)
  │   │   │   ├─ Update DB records (file path)
  │   │   │   ├─ Sync VectorMap paths
  │   │   │   ├─ Move file on disk
  │   │   │   └─ Preserve metadata/AI analysis
  │   │   │
  │   │   ├─ Handle collisions:
  │   │   │   └─ If exists: Add suffix (_1, _2, ...)
  │   │   │
  │   │   └─ Emit progress signal
  │   │
  │   └─ Rollback on error: Keep original location
  │
  └─ Return: MoveResult(total=45, successful=44, failed=1)
         ↓
[ MAIN WINDOW ] Update: "Organized 44 files successfully"
```

**Key Classes:**
- `FileOrganizerService` - Clustering & generation
- `ClassificationEngine` - Category assignment
- `FileMover` - Safe file movement with sync
- `SuggestionEngine` - Smart suggestions

**Safety Mechanisms:**
- Atomic operations (all-or-nothing)
- Path collision detection
- Metadata preservation
- Database sync on move
- Undo support (via versioning)

---

### 1.5 Duplicate Detection Workflow

```
USER ACTION: "Find duplicate files"
         ↓
[ MAIN WINDOW ] → _on_duplicates_requested()
         ↓
[ DUPLICATE_ENGINE ]
  ├─ Step 1: Find Exact Duplicates
  │   ├─ For each file in workspace:
  │   │   ├─ Calculate SHA-256: file_checksum
  │   │   ├─ Query DB: files with same checksum
  │   │   │
  │   │   └─ If matches > 1:
  │   │       └─ Add to: exact_duplicate_group
  │   │
  │   └─ Return: duplicate_groups
  │       Example: {
  │         "abc123": [file1.pdf, file1_copy.pdf, Document.pdf],
  │         "def456": [image1.jpg, image1_backup.jpg]
  │       }
  │
  ├─ Step 2: Find Near-Duplicates (if enabled)
  │   ├─ For each file:
  │   │   ├─ If IMAGE:
  │   │   │   └─ Use CLIP embedding distance
  │   │   │       └─ threshold: 0.15 (tunable)
  │   │   │
  │   │   ├─ If TEXT/DOC:
  │   │   │   └─ Retrieve similar via RetrievalEngine
  │   │   │       └─ threshold: 0.5 (tunable)
  │   │   │
  │   │   └─ If AUDIO/VIDEO:
  │   │       └─ Compare transcripts similarity
  │   │           └─ threshold: 0.6 (tunable)
  │   │
  │   └─ Build near_duplicate_groups
  │
  ├─ Step 3: Score & Rank Within Group
  │   ├─ For each group:
  │   │   ├─ Calculate per-file score:
  │   │   │   ├─ file_size (larger = better)
  │   │   │   ├─ modification_time (newer = better)
  │   │   │   ├─ filename_quality (more descriptive = better)
  │   │   │   └─ total_score
  │   │   │
  │   │   ├─ Identify: best_copy (highest score)
  │   │   └─ Mark others: candidates_for_removal
  │   │
  │   └─ Return: ranking_by_group
  │
  ├─ Step 4: Generate Suggestions
  │   ├─ SuggestionEngine.suggest_duplicate_removals()
  │   │   ├─ For each non-best file:
  │   │   │   ├─ Create DuplicateSuggestion:
  │   │   │   │   ├─ path_to_remove
  │   │   │   │   ├─ keep_file (the best one)
  │   │   │   │   ├─ reason: "Older version, keep primary"
  │   │   │   │   ├─ confidence: 0.95
  │   │   │   │   └─ status: "pending"
  │   │   │   │
  │   │   │   └─ Store in DB: duplicate_suggestions
  │   │   │
  │   │   └─ Return: suggestion[]
  │   │
  │   └─ Group by: keep_file (to show together)
  │
  └─ Return: DuplicateDialog with suggestions
         ↓
[ DUPLICATE_DIALOG ]
  ├─ Show groups with file sizes, dates, names
  ├─ Highlight: "KEEP" (green) vs "REMOVE" (red)
  └─ Allow user to:
     ├─ Accept suggestion → Move to trash
     ├─ Dismiss → Mark "reviewed, keep both"
     ├─ Modify → Choose different keep file
     └─ Compare → Show side-by-side details
         ↓
[ SUGGESTION_ENGINE ]
  └─ accept_duplicate_removal(suggestion_id)
     ├─ Verify file still exists
     ├─ Move to trash: SafeFileOps.move_to_trash(path)
     ├─ Cleanup DB:
     │   ├─ Delete evidence records
     │   ├─ Delete vector maps
     │   ├─ Delete file record
     │   └─ Clean orphaned vectors from FAISS
     ├─ Update suggestion: status = "accepted"
     └─ Emit signal: "duplicate removed"
```

**Key Classes:**
- `DuplicateEngine` - Exact & near-duplicate finding
- `SuggestionEngine` - Smart suggestion generation
- `FileSimilarityService` - Similarity calculation
- `SafeFileOps` - Safe file operations

**Thresholds (Configurable):**
- Exact: SHA-256 match (100%)
- CLIP images: distance < 0.15
- Semantic text: similarity > 0.5
- Audio/video: transcript similarity > 0.6

---

## Part 2: Database Schema & Data Structures

### 2.1 Core Tables

```sql
-- File metadata
File(
  id INT PRIMARY KEY,
  path VARCHAR UNIQUE NOT NULL,
  filename VARCHAR,
  extension VARCHAR,
  size_bytes INT,
  checksum_sha256 VARCHAR UNIQUE,
  mime_type VARCHAR,
  mtime DATETIME,
  analysis_version INT,
  is_indexed BOOL,
  created_at DATETIME
)

-- Content chunks (evidence)
Evidence(
  id INT PRIMARY KEY,
  file_id INT FOREIGN KEY,
  chunk_index INT,
  modality VARCHAR,  -- "text", "image", "audio", "video"
  text TEXT,
  source_page INT,   -- For PDFs
  source_timestamp FLOAT,  -- For video/audio
  created_at DATETIME
)

-- Vector embeddings mapping
VectorMap(
  id INT PRIMARY KEY,
  evidence_id INT FOREIGN KEY,
  embedding_model VARCHAR,
  vector_id INT,  -- FAISS index ID
  created_at DATETIME
)

-- AI analysis results (cached)
AIAnalysis(
  id INT PRIMARY KEY,
  file_id INT FOREIGN KEY,
  analysis_type VARCHAR,  -- "caption", "tags", "category", "entities"
  result JSON,
  confidence FLOAT,
  model_used VARCHAR,
  created_at DATETIME
)

-- File relationships
FileRelationship(
  id INT PRIMARY KEY,
  source_file_id INT FOREIGN KEY,
  target_file_id INT FOREIGN KEY,
  relationship_type VARCHAR,  -- "duplicate", "related", "cited_by"
  similarity_score FLOAT,
  reason TEXT,
  created_at DATETIME
)

-- Suggestions for users
OrganizationSuggestion(
  id INT PRIMARY KEY,
  file_id INT FOREIGN KEY,
  target_folder VARCHAR,
  category VARCHAR,
  confidence FLOAT,
  reason TEXT,
  status VARCHAR,  -- "pending", "accepted", "dismissed"
  created_at DATETIME
)

-- Search history
SearchHistory(
  id INT PRIMARY KEY,
  query_text VARCHAR,
  query_embedding BLOB,  -- Vector for semantic search
  results_count INT,
  execution_time_ms INT,
  created_at DATETIME
)

-- Collections (smart folders)
Collection(
  id INT PRIMARY KEY,
  name VARCHAR UNIQUE,
  criteria JSON,  -- {extension: ".pdf", min_size: 1000000}
  is_dynamic BOOL,
  created_at DATETIME
)

-- Conversations & chat
Conversation(
  id INT PRIMARY KEY,
  name VARCHAR,
  created_at DATETIME,
  updated_at DATETIME
)

ConversationMessage(
  id INT PRIMARY KEY,
  conversation_id INT FOREIGN KEY,
  role VARCHAR,  -- "user", "assistant"
  content TEXT,
  citations JSON,  -- [{file_id, page, snippet}]
  created_at DATETIME
)

-- Graph nodes & relationships
GraphEntity(
  id INT PRIMARY KEY,
  file_id INT FOREIGN KEY,
  entity_name VARCHAR,
  entity_type VARCHAR,  -- "Person", "Organization", "Location"
  normalized_name VARCHAR,  -- Lowercase, no punctuation
  mentions INT,
  created_at DATETIME
)

GraphRelationship(
  id INT PRIMARY KEY,
  source_entity_id INT FOREIGN KEY,
  target_entity_id INT FOREIGN KEY,
  relationship_type VARCHAR,
  evidence_id INT FOREIGN KEY,  -- Which chunk showed this relationship
  created_at DATETIME
)
```

### 2.2 Key Indices for Performance

```sql
-- Frequently searched columns
CREATE INDEX idx_file_checksum ON File(checksum_sha256);
CREATE INDEX idx_file_path ON File(path);
CREATE INDEX idx_evidence_file ON Evidence(file_id);
CREATE INDEX idx_evidence_modality ON Evidence(modality);
CREATE INDEX idx_vector_map_evidence ON VectorMap(evidence_id);
CREATE INDEX idx_relationship_type ON FileRelationship(relationship_type);
CREATE INDEX idx_search_history_query ON SearchHistory(query_text);
CREATE INDEX idx_conversation_timestamp ON Conversation(updated_at);
CREATE INDEX idx_graph_entity_name ON GraphEntity(normalized_name);

-- Composite indices for common queries
CREATE INDEX idx_file_extension_size ON File(extension, size_bytes);
CREATE INDEX idx_evidence_file_modality ON Evidence(file_id, modality);
CREATE INDEX idx_relationship_file_pair ON FileRelationship(source_file_id, target_file_id);
```

### 2.3 Data Types & Serialization

```python
# Evidence modalities
Modality = {
    "text": "Plain text or extracted document text",
    "ocr": "Text extracted via OCR from images",
    "transcript": "Speech-to-text from audio/video",
    "caption": "AI-generated image caption",
    "keyframe": "Video keyframe descriptor"
}

# Chunk structure (in memory)
@dataclass
class ContentBlock:
    modality: str           # From Modality enum
    text: str               # Extracted content
    source_page: int = None # For PDFs
    source_timestamp: float = None  # For audio/video
    metadata: dict = None   # Custom fields

# Evidence chunk (database)
@dataclass
class EvidenceChunk:
    text: str
    modality: str
    source_file_id: int
    source_page: int = None
    source_timestamp: float = None
    chunk_id: int = None

# Vector embedding
Vector = ndarray(shape=(768,), dtype=float32)  # Or 384, 1536 depending on model

# Retrieval result
@dataclass
class RetrievalResult:
    file_id: int
    file_path: str
    evidence_id: int
    text: str
    modality: str
    similarity_score: float
    match_strength_label: str  # "High", "Medium", "Low"
    source_location: dict  # {page: 5} or {timestamp: 45.3}
```

---

## Part 3: Performance Characteristics & Optimization

### 3.1 Big-O Complexity Analysis

| Operation | Current | FAISS | DB | Total |
|-----------|---------|-------|-----|--------|
| Index file | O(N) | O(N log M) | O(N log M) | O(N log M) |
| Search | O(1) | O(log M) | O(N) | O(N) |
| Find duplicates | O(N log N) | O(1) | O(N log N) | O(N log N) |
| Organize files | O(N) | O(1) | O(N) | O(N) |
| Build graph | O(E) | O(1) | O(E) | O(E) |

Where: N = files, M = vectors, E = entities

### 3.2 Memory Usage Estimates

```
Per 1,000 files (typical):
├─ SQLite DB: 5-10 MB
├─ FAISS index: 1-2 MB (384-dim) to 4-6 MB (1536-dim)
├─ Python objects: 2-3 MB
├─ Cache (thumbnails): 1-2 MB
└─ Total: ~10-25 MB

Per 10,000 files (large workspace):
├─ SQLite DB: 50-100 MB
├─ FAISS index: 10-20 MB
├─ Python objects: 20-30 MB
├─ Cache: 10-20 MB
└─ Total: ~100-200 MB (acceptable)

Per 100,000 files (enterprise):
├─ SQLite DB: 500 MB - 1 GB
├─ FAISS index: 100-200 MB
├─ Python objects: 200-300 MB
└─ Total: ~1-2 GB (manageable with streaming)
```

### 3.3 Query Performance Profile

```
Operation          | Current Time | Target | Optimization
-------------------|--------------|--------|---------------
Index 1 file       | 100-500 ms   | <100 ms | Parallel extraction
Index 1000 files   | 30-60 sec    | <30 sec | Better scheduling
Search (10K DB)    | 50-150 ms    | <100 ms | Index on modality
Find duplicates    | 5-30 sec     | <10 sec | Batch hashing
Build graph        | 10-30 sec    | <10 sec | Parallel entity extraction
Load FAISS (1K vecs)| 100-200 ms  | <50 ms  | Memory mapping
Cold start app     | 2-5 sec      | <2 sec  | Lazy loading (done)
```

### 3.4 Bottleneck Analysis

**Current Bottlenecks:**
1. **FAISS Index Loading** (100-200 ms)
   - Solution: Memory mapping or incremental loading
   
2. **LLM Inference** (1-5 sec per call)
   - Solution: Caching, smaller models, batching
   
3. **Video/Audio Processing** (5-30 sec per file)
   - Solution: Hardware acceleration, queue optimization
   
4. **Large Workspace Navigation** (lag with 50K+ files)
   - Solution: Pagination, lazy loading, filtering
   
5. **Duplicate Detection on Large Sets** (N² comparisons)
   - Solution: Bloom filters, locality-sensitive hashing

---

## Part 4: Testing Strategy & Coverage

### 4.1 Test Pyramid

```
        ▲
        │
    E2E Tests (20%)
       ▄▄▄▄▄▄
      │       │
Integration Tests (40%)
   ▄▄▄▄▄▄▄▄▄▄▄▄
  │             │
Unit Tests (40%)
▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄
└───────────────┘
   Coverage: 70%
```

### 4.2 Test Organization

```
tests/
├── Unit Tests (by module)
│   ├── test_batch2_unit.py           # Extractors, AI service
│   ├── test_batch3.py                # RAG, retrieval, evidence
│   ├── test_batch5.py                # Services (tagging, etc.)
│   └── [others]
│
├── Integration Tests
│   ├── test_batch2_integration.py    # Content extraction → storage
│   ├── test_batch5_e2e.py            # Full workflows
│   └── [others]
│
├── UI Tests
│   ├── test_main_window.py           # Main window widget
│   ├── test_preview_panel_*.py       # Preview functionality
│   ├── test_batch7_rename.py         # Rename dialogs
│   └── [others]
│
├── Fixtures
│   ├── conftest.py                   # pytest fixtures
│   └── session_factory               # DB setup/teardown
│
└── Coverage: ~70% of critical paths
```

### 4.3 Key Test Cases

```python
# Example: Semantic search test
def test_retrieval_engine_retrieve():
    """Full retrieval pipeline"""
    # Setup
    db = TestDatabase()
    retrieval = RetrievalEngine(db_store, vector_engine, embedding)
    
    # Index test content
    evidence = [EvidenceChunk(...), ...]
    vectors = embedding_engine.embed_batch(...)
    vector_engine.add_batch(vectors)
    
    # Search
    query_vec = embedding_engine.embed_text("machine learning")
    results = retrieval.retrieve(query_vec, k=10)
    
    # Assertions
    assert len(results) <= 10
    assert all(r.similarity_score >= 0.0 for r in results)
    assert results[0].similarity_score >= results[-1].similarity_score
    
# Example: Duplicate detection test
def test_duplicate_engine_find_near_duplicates():
    """Find near-duplicates"""
    engine = DuplicateEngine(file_identity, file_similarity)
    
    # Create test files
    file1 = create_temp_file("content", size=1000)
    file2 = create_temp_file("content", size=1001)  # Same but 1 byte diff
    
    # Find near-duplicates
    groups = engine.find_near_duplicates([file1.path, file2.path])
    
    # Should group together
    assert len(groups) == 1
    assert len(groups[0]) == 2
    
# Example: File organization test
def test_file_organizer_auto_cluster():
    """Auto-organize files"""
    organizer = FileOrganizerService(classifier, db_store)
    
    # Create test workspace
    workspace = create_temp_folder()
    create_test_files(workspace, count=100)
    
    # Auto-organize
    clusters = organizer.auto_cluster_folder(workspace)
    
    # Should create categories
    assert len(clusters) > 0
    assert sum(c.files_count for c in clusters) == 100
    assert all(c.folder_name for c in clusters)
```

---

## Part 5: Extension Points & Plugin Architecture

### 5.1 Plugin System

```python
# Plugin base class
class PluginInterface:
    """All plugins inherit from this"""
    
    @property
    def name(self) -> str:
        return "My Plugin"
    
    @property
    def version(self) -> str:
        return "1.0.0"
    
    @property
    def subscribed_events(self) -> list[str]:
        return ["file_indexed", "file_moved", "search_completed"]
    
    def on_hook(self, hook_name: str, **kwargs):
        """Called when subscribed event fires"""
        if hook_name == "file_indexed":
            self.on_file_indexed(kwargs['file_path'])
    
    def on_file_indexed(self, file_path: str):
        print(f"Plugin noticed: {file_path} indexed")

# Register plugin
plugin_registry.register(MyPlugin())

# Hook into events
signal_bus.emit("file_indexed", file_path="/path/to/file.pdf")
```

### 5.2 Custom Extraction Module

```python
# Create custom extractor
class MyCustomExtractor(BaseExtractor):
    def can_handle(self, path: str) -> bool:
        return path.endswith('.myformat')
    
    def extract(self, path: str) -> list[ContentBlock]:
        # Custom extraction logic
        text = self.parse_myformat(path)
        return [ContentBlock(modality="text", text=text)]

# Register with factory
extractor_factory.register(MyCustomExtractor())
```

### 5.3 Custom Search Filter

```python
# Add custom filter to semantic search
class MyCustomFilter:
    def filter_results(self, results: list[RetrievalResult]) -> list[RetrievalResult]:
        # Custom filtering logic
        return [r for r in results if self.meets_criteria(r)]

# Hook into retrieval
retrieval_engine.add_filter(MyCustomFilter())
```

---

## Summary: Architecture Strengths for Extension

✅ **Easy to extend:**
- Plugin system for custom logic
- Factory patterns for new extractors
- Event bus for integrations
- Service container for dependency injection

✅ **Maintainable codebase:**
- Clear layer separation
- Minimal coupling between modules
- Consistent patterns throughout
- Comprehensive tests

✅ **Performance-aware:**
- Async operations throughout
- Lazy loading of resources
- Batching for efficiency
- Vector indexing for scale

---

**Document Version:** 1.0  
**Last Updated:** September 5, 2026  
**Prepared By:** Kiro AI Assistant
