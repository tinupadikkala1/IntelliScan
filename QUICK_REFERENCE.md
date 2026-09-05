# IntelliScan - Quick Reference Guide

## At a Glance

| Metric | Value |
|--------|-------|
| **Type** | Desktop AI Application (PySide6/Python) |
| **Status** | Production-Ready (7 batches complete) |
| **Code** | 46,355 LOC | 380+ classes | 2,114+ functions |
| **Tests** | 30+ modules | 1,000+ test cases | 70% coverage |
| **Database** | SQLite (5.6 MB) + FAISS (1.1 MB) |
| **Rating** | ⭐⭐⭐⭐ (4.5/5) |

---

## Core Features Matrix

### File Management
| Feature | Status | Performance |
|---------|--------|-------------|
| Metadata Extraction | ✅ Complete | <1 sec/file |
| Content Extraction | ✅ Complete | 1-5 sec/file |
| File Watcher | ✅ Complete | Real-time |
| Duplicate Detection | ✅ Complete | 5-30 sec/1K files |
| Auto-Organization | ✅ Complete | 10-30 sec/1K files |

### AI & Search
| Feature | Status | Performance |
|---------|--------|-------------|
| Semantic Search | ✅ Complete | 50-200 ms |
| RAG Q&A | ✅ Complete | 2-10 sec (with context) |
| Knowledge Graphs | ✅ Complete | 10-30 sec/K files |
| Agents/Tools | ✅ Complete | Tool-dependent |
| Collections | ✅ Complete | Instant |

### Content Processing
| Format | Status | Technology |
|--------|--------|-----------|
| Text (PDF, Word, Excel, etc.) | ✅ | PyMuPDF, python-docx, openpyxl |
| Images + OCR | ✅ | Pillow, Tesseract (optional) |
| Audio Transcription | ✅ | Whisper (optional) |
| Video Keyframes | ✅ | OpenCV |
| Vision Captions | ✅ | Moondream (optional) |

---

## Architecture Quick View

```
┌─────────────────────────────────────────┐
│    PRESENTATION LAYER (Qt GUI)          │
│  MainWindow | Dialogs | Widgets         │
└─────────────────────┬───────────────────┘
                      │
┌─────────────────────▼───────────────────┐
│  BUSINESS LOGIC (Services, Tasks)       │
│  Container | TaskMgr | ThreadMgr        │
└─────────────────────┬───────────────────┘
                      │
┌─────────────────────▼───────────────────┐
│  EXTRACTION (Content Processing)        │
│  Metadata | Text | Image | Audio | Video│
└─────────────────────┬───────────────────┘
                      │
┌─────────────────────▼───────────────────┐
│  AI & SEARCH (Semantic Layer)           │
│  RAG | Retrieval | Embedding | Vector   │
└──────┬──────────────────────────┬───────┘
       │                          │
┌──────▼──────┐         ┌────────▼────────┐
│ SQLite DB   │         │ FAISS Index     │
│ 25 Models   │         │ Vector Storage  │
└─────────────┘         └─────────────────┘
```

---

## Development Process

### Batch-Based Delivery
```
Batch → Specification → Implementation → Testing → Audit → Complete
  ↓
  7/7 Complete (July-September 2026)
```

### Testing Strategy
```
    E2E (20%)
  Integration (40%)
    Unit (40%)
  
  Coverage: 70%+ of critical paths
```

---

## Performance Targets vs Current

| Operation | Current | Target | Gap |
|-----------|---------|--------|-----|
| Cold Start | 2-5 sec | <2 sec | +60% |
| Index 1 file | 100-500 ms | <100 ms | +80% |
| Search (10K) | 50-200 ms | <100 ms | +50% |
| Find Dupes | 5-30 sec | <10 sec | +70% |
| FAISS Load | 100-200 ms | <50 ms | +50% |

---

## Key Classes & Responsibilities

### Core Engines (12 Total)
1. **RAGEngine** (918 LOC) - Q&A orchestration
2. **RetrievalEngine** (875 LOC) - Semantic search
3. **ContentEngine** (621 LOC) - Content extraction
4. **AIIndexer** (626 LOC) - Indexing pipeline
5. **VectorEngine** (299 LOC) - FAISS wrapper
6. **EmbeddingEngine** (243 LOC) - Vector generation
7. **EvidenceEngine** (239 LOC) - Text chunking
8. **DuplicateEngine** (239 LOC) - Duplicate finding
9. **GraphEngine** (124 LOC) - Knowledge graphs
10. **ClassificationEngine** - Category assignment
11. **RelationshipEngine** - File relationships
12. **TaggingEngine** - Intelligent tagging

### Key Services (20+)
- **FileOrganizerService** - Auto-clustering
- **SuggestionEngine** - Smart suggestions
- **DocumentComparisonService** - Semantic comparison
- **NLFilterParser** - Natural language queries
- **MetadataExtractor** - System info
- **TextExtractor** - Document parsing
- **And 14+ others**

---

## Database Schema Overview

### Core Tables
- **File** - Metadata, checksums, MIME types
- **Evidence** - Text chunks with source locations
- **VectorMap** - Embedding to chunk mapping
- **AIAnalysis** - Cached analysis results
- **FileRelationship** - File connections
- **Conversation** - Chat history
- **GraphEntity** - Knowledge graph nodes
- **Collection** - Smart folders
- **And 17+ more**

### Key Indices
- `file(checksum_sha256)` - Duplicate detection
- `file(path)` - Path lookups
- `evidence(file_id, modality)` - Search filtering
- `graph_entity(normalized_name)` - Entity search

---

## Installation Quick Start

```bash
# Clone/navigate
cd /home/user/Desktop/IntelliScan

# Setup
python3.12 -m venv venv
source venv/bin/activate

# Install
pip install -r requirements.txt
pip install pyside6>=6.6

# Optional AI features
pip install torch sentence-transformers faiss-cpu
pip install openai-whisper pillow

# Run
python main.py

# Test
pytest tests/ -v
```

---

## Top Improvements (Priority Order)

### Week 1-2: Stability & Performance
1. ⚡ Add database indices (+50% query speed)
2. ⚡ Incremental FAISS updates (+3x indexing)
3. 📊 Performance monitoring (identify bottlenecks)
4. 🛡️ Error recovery mechanisms (rollback)

### Week 3-6: Robustness & Quality
5. 📝 Enhanced logging & debugging
6. 🧪 Test coverage to 80%+
7. 📈 Performance benchmarking
8. 🔍 Health checks & telemetry

### Week 7+: UX & Scalability
9. 🎨 Simplify settings UI
10. 📚 User documentation
11. 📦 Deployment packages
12. 🚀 100K+ file support

---

## Extension Points

### Add Custom Plugin
```python
class MyPlugin(PluginInterface):
    @property
    def name(self): return "My Plugin"
    
    def on_hook(self, hook_name, **kwargs):
        if hook_name == "file_indexed":
            self.process_file(kwargs['file_path'])

plugin_registry.register(MyPlugin())
```

### Add Custom Extractor
```python
class MyExtractor(BaseExtractor):
    def can_handle(self, path): return path.endswith('.myformat')
    
    def extract(self, path):
        return [ContentBlock(modality="text", text="...")]

extractor_factory.register(MyExtractor())
```

---

## Common Tasks

### Index a Folder
```
Main Window → Select Folder → Scan Requested
→ AI Indexer → MetadataExtractor + ContentEngine
→ EvidenceEngine (chunking) → Embedding → FAISS + SQLite
```

### Search Semantically
```
Search Dialog → Query Embedding → VectorSearch
→ Hydrate Results → Filter & Rank → Display
```

### Ask Question (RAG)
```
Ask AI Dialog → Build Context → Rank Results
→ Prompt Assembly → LLM Generation → Citations
```

### Organize Files
```
Organize Dialog → Classify Files → Generate Names
→ Preview Moves → Execute with Rollback on Error
```

### Find Duplicates
```
Scan Duplicates → Find Exact (SHA-256)
→ Find Near-Duplicates (CLIP/Semantic)
→ Score & Suggest Removal → Move to Trash
```

---

## Troubleshooting

| Issue | Cause | Solution |
|-------|-------|----------|
| Slow indexing | Large files, no GPU | Use CLIP for images, parallel processing |
| Q&A not working | Ollama not running | Start Ollama, or use search-only mode |
| Missing OCR | Tesseract not installed | Install system tesseract package |
| Memory issues | 50K+ files | Use lazy loading, pagination |
| FAISS errors | Corrupted index | Delete cache/faiss_index.bin, reindex |

---

## Performance Profiling

```
# Find slow queries
grep "SLOW" logs/intellivault.log

# Monitor memory
ps aux | grep main.py

# Profile indexing
python -m cProfile -s cumtime main.py

# Benchmark searches
pytest tests/ -k "test_retrieval" -v --durations=10
```

---

## API Summary

### RetrievalEngine
```python
retrieve(query_vec, k=50, threshold=0.3) → RetrievalResponse
retrieve_similar(query, file_id) → RetrievalResponse[]
smart_retrieve(query, scope) → RetrievalResponse[]
```

### RAGEngine
```python
ask(query, file_paths=[]) → RAGResponse
ask_file(query, file_path) → RAGResponse
answer_multi(query, file_paths) → RAGResponse
resolve_followup(query, history) → RAGResponse
```

### FileOrganizerService
```python
find_candidates(folder) → OrganizationCandidate[]
auto_cluster_folder(folder) → ProposedFolderCluster[]
execute_organization(moves, callback) → MoveResult
```

### DuplicateEngine
```python
find_exact_duplicates() → DuplicateGroup[]
find_near_duplicates(files) → DuplicateGroup[]
find_near_duplicates_for_file(path) → DuplicateGroup
```

---

## Configuration Files

| File | Purpose | Location |
|------|---------|----------|
| settings.json | App settings | ~/.config/intellivault/ |
| intellivault.db | SQLite database | config/intellivault.db |
| faiss_index.bin | Vector index | cache/faiss_index.bin |
| intellivault.log | Application log | logs/intellivault.log |

---

## Support & Resources

- **Architecture**: See `system_architecture.md`
- **Technical Deep Dive**: See `TECHNICAL_DEEP_DIVE.md`
- **Full Analysis**: See `PROJECT_ANALYSIS.md`
- **Code Repo**: `/home/user/Desktop/IntelliScan`
- **Tests**: `tests/` directory (30+ modules)

---

**Last Updated:** September 5, 2026  
**Version:** 1.0 (Post-Batch 7)
