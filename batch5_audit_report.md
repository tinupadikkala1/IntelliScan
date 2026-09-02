# INTELLIVAULT — POST-BATCH-4 CURRENT STATE & BATCH-5 READINESS AUDIT

**Audit date:** 2026-08-11
**Method:** Full source inspection (read every module in `engines/`, `extractors/`, `ai/`, `services/`, `database/`, `conversation/`, `graph/`, `agent/`, `ui/`, `widgets/`, `vision/`, `speech/`, `video/`, `text_extraction/`), live SQLite inspection, FAISS state check, full test suite run, and runtime boot/lazy-init verification. **No source code was modified.**

**Verification labels used throughout:**
- **RUNTIME VERIFIED** — exercised live (tests run, app booted, DB queried, engines instantiated).
- **STATICALLY VERIFIED** — confirmed by reading source; not exercised at runtime.
- **NOT VERIFIED** — could not be confirmed.
- **DOCUMENTED vs IMPLEMENTED** — distinguished where documentation claims more than code delivers.

---

## 1. PROJECT STRUCTURE

Root: `/home/user/Desktop/IntelliScan` (the venv was moved here from `mini_project/IntelliVault`; all absolute-path references in venv scripts were repaired).

```
IntelliScan/
├── main.py                     # Entry point — creates QApplication + MainWindow
├── requirements.txt
├── pyproject.toml              # pytest config
├── config/
│   ├── settings.json           # persisted app settings
│   └── intellivault.db         # SQLite database (1.6 MB)
├── cache/
│   ├── faiss_index.bin         # FAISS index on disk
│   └── faiss_index.bin.ids     # pickle of chunk_id list
├── app/
│   ├── container.py            # DI container, lazy service init (Batch 3+4 engines)
│   └── signal_bus.py           # global Qt signal bus
├── engines/                    # Batch 3 + 4 core engines
│   ├── config.py               # SINGLE source of truth for models/chunking/thresholds
│   ├── content_engine.py       # UniversalContentEngine + ContentBlock (multimodal extraction)
│   ├── evidence_engine.py      # EvidenceEngine + EvidenceChunk (chunking with provenance)
│   ├── embedding_engine.py     # nomic-embed-text via Ollama (/api/embed, batch + sequential)
│   ├── vector_engine.py        # FAISS IndexFlatIP + chunk_id map, save/load/remove
│   ├── retrieval_engine.py     # RetrievalEngine — unified semantic retrieval API
│   ├── rag_engine.py           # RAGEngine — grounded Q&A w/ citations, direct-ask, answer_multi
│   ├── db_store.py             # EngineDBStore — evidence/vector_map/search_history persistence
│   ├── ai_indexer.py           # AIFolderIndexer — full AI indexing pipeline
│   └── clip_engine.py          # CLIP ViT-B/32 image embeddings (512-d, optional)
├── extractors/                 # multimodal extractors (image/audio/video + base + factory)
│   ├── image_extractor.py      # OCR + moondream captioning; ocr_image_bytes/caption_image_bytes
│   ├── audio_extractor.py      # Whisper transcription, ~30s grouped blocks
│   ├── video_extractor.py      # ffmpeg audio → Whisper + keyframe captions
│   ├── document_extractor.py
│   ├── base_extractor.py       # BaseMultimodalExtractor
│   └── extractor_factory.py
├── text_extraction/            # Batch 1/2 text extractors: pdf/docx/pptx/xlsx/txt/csv/json/xml/md
├── ai/                         # Batch 2 AI analysis stack
│   ├── config.py               # MODEL_NAME=qwen-local:latest, temperature 0.3, timeout 480
│   ├── ollama_client.py        # OllamaClient (/api/generate, availability check)
│   ├── prompt_builder.py
│   ├── json_parser.py          # strict JSON parse of LLM analysis output
│   ├── ai_service.py           # AIService.analyze_text → summary/keywords/tags/category/language
│   ├── analysis_manager.py     # AnalysisManager.analyze_file (extract → hash → analyze)
│   └── cache_manager.py        # AICacheManager — ai_analysis table CRUD by SHA-256
├── services/
│   ├── folder_scanner.py       # FolderScanner (recursive walk, ignore patterns, cycles)
│   ├── metadata_extractor.py   # MetadataExtractor — size/mime/dates/owner/SHA-256 checksum
│   ├── text_extractor.py       # TextExtractor (Batch 1 pipeline)
│   ├── sqlite_indexer.py       # SQLiteIndexer — indexed_files table, status tracking
│   ├── task_manager.py         # TaskManager — QObject signals + cancel events over ThreadManager
│   ├── thread_manager.py       # ThreadManager — QThreadPool + Worker QRunnable
│   ├── file_watcher.py         # FileWatcher — watchdog Observer → Qt signal
│   ├── cache_manager.py        # disk cache (SHA-256 keyed)
│   ├── evidence_navigator.py   # EvidenceNavigator — modality-aware navigation dispatch
│   └── ai_resource_manager.py  # AIResourceManager — semaphore slots (llm/embed/vision/speech)
├── conversation/               # Batch 4 conversations
│   ├── conversation_store.py   # ConversationStore — CRUD, citations, PersistenceError
│   ├── conversation_manager.py # ConversationManager — full chat pipeline per turn
│   ├── conversation_service.py # run_chat worker entry point (TaskManager contract)
│   ├── scope_manager.py        # ChatScope + ScopeManager (file/folder/workspace filters)
│   ├── context_builder.py      # ConversationContextBuilder + MultiDocumentContextBuilder
│   ├── citation_builder.py     # CitationBuilder — results → persisted citation records
│   └── models.py               # ChatMessage/CitationRecord/ConversationInfo/ChatResult
├── graph/                      # Batch 4 knowledge graph
│   ├── graph_engine.py         # GraphEngine — orchestration, wired into AIFolderIndexer
│   ├── graph_store.py          # GraphStore — entities/relationships/evidence-links persistence
│   ├── graph_models.py         # EntityRecord/RelationshipRecord/normalize_entity_name
│   ├── entity_extractor.py     # LLM entity extraction, 10 controlled types
│   ├── relationship_extractor.py  # LLM relationship extraction, validated against entities
│   ├── graph_query_service.py  # read-side queries for UI + agent tool
│   └── graph_view.py           # QGraphicsView canvas (read-only visualization)
├── agent/                      # Batch 4 agentic workflows
│   ├── agent_engine.py         # AgentEngine — bounded loop: plan→execute→synthesize
│   ├── planner.py              # Planner — LLM tool selection w/ deterministic fallback
│   ├── tool_registry.py        # 8 read-only tools wired to engines
│   ├── tool_executor.py        # validation + execution + step recording
│   ├── policies.py             # AgentPolicy — max steps/time/evidence, read-only
│   ├── schemas.py              # ToolSpec/ToolInput validation
│   └── agent_state.py          # AgentState/AgentStep — status machine + sticky cancel
├── ui/
│   ├── main_window.py          # MainWindow (1633 lines) — all wiring lives here
│   ├── menu_bar.py             # MenuBar — File/Edit/View/Tools/Help, signal-exposed actions
│   ├── toolbar.py / status_bar.py / dock_manager.py / theme_engine.py
│   ├── indexed_files_widget.py / indexed_files_model.py
│   ├── settings_dialog.py      # SettingsDialog — tabbed; "Batch 4" tab present
│   └── dialogs/
│       ├── semantic_search_dialog.py  # SemanticSearchDialog
│       ├── ask_ai_dialog.py           # AskAIDialog
│       ├── ai_analysis_dialog.py      # AI Analysis viewer
│       ├── b1_progress_dialog.py      # Batch 1 scan progress
│       ├── chat_dialog.py             # ChatDialog (folder/workspace/file chat)
│       ├── graph_dialog.py            # GraphDialog (knowledge graph explorer)
│       ├── agent_dialog.py            # AgentDialog (Agent Mode)
│       └── conversation_history_dialog.py  # resume/delete conversations
├── widgets/
│   ├── file_explorer.py        # FileExplorer — list/grid, context menu, drag-drop
│   ├── preview_panel.py        # PreviewPanel — file preview + metadata + extracted text
│   ├── chat_view.py            # ChatView — reusable chat panel (states, stop)
│   ├── message_bubble.py       # MessageBubble — message rendering + clickable citations
│   ├── indexed_files_widget.py / indexed_files_model.py
│   └── (folder tree, drives, favorites, breadcrumb widgets)
├── vision/                     # OCR engine, vision engine, content merger
├── speech/                     # SpeechEngine (Whisper)
├── video/                      # VideoEngine, keyframe engine
├── plugins/ + core/plugin_registry.py  # plugin system (hook invocation; context-menu hook disabled)
├── tests/                      # 19 test files, 261 tests
├── docs (batch plans/audits)   # IntelliVault_Batch3.md, IMPLEMENTATION_PLAN.md, batch4_audit_report.md, etc.
└── graphify-out/               # generated AST-graph artifacts (junk, not part of the app)
```

**Entry point:** `main.py` → QApplication → `MainWindow(container=Container())`.

---

## 2. APPLICATION ARCHITECTURE

The actual data flow (reconstructed from source, runtime-verified where possible):

```
User
 ↓
UI layer (MainWindow / FileExplorer / dialogs)          [GUI thread]
 ↓ signals (send_requested, search_requested, ai_*_requested...)
TaskManager.submit(fn, type, ...)                        [GUI thread, microtask]
 ↓
ThreadManager → QThreadPool Worker (QRunnable)           [worker thread]
 ↓
┌────────────────────── ENGINE PIPELINE ──────────────────────┐
│ AIFolderIndexer.index_folder/_index_file                     │
│   → UniversalContentEngine.extract(file) → ContentBlock[]    │
│   → EvidenceEngine.build_evidence(file) → EvidenceChunk[]    │
│   → RetrievalEngine.index_chunks_detailed()                  │
│        → EmbeddingEngine.embed_batch() (nomic-embed-text)    │
│        → VectorEngine.add() (FAISS IndexFlatIP, normalized)  │
│   → EngineDBStore.store_evidence + store_vector_maps (SQLite)│
│   → GraphEngine.index_file() (entity/relationship extraction)│
└──────────────────────────────────────────────────────────────┘
 ↓ results
Worker signals (finished/error) → queued to GUI thread
 ↓
UI updates (dialogs, indexed-files list, status bar)
```

Query path (Semantic Search / Chat / Ask AI):

```
Query
 ↓
RetrievalEngine.retrieve()/smart_retrieve()
   → EmbeddingEngine.embed_text("search_query: "+q)
   → VectorEngine.search() (FAISS cosine)
   → in-memory evidence map (chunk_id → EvidenceChunk)     [hydrated from SQLite at startup]
   → per-file cap (MAX_CHUNKS_PER_FILE=3) + scope file_filter
 → RetrievalResult[] (rank, score, provenance, modality, timestamps)
 ↓
RAGEngine.ask()/answer_multi()/ask_file_direct()
   → prompt with evidence + citations
   → Ollama qwen-local:latest
 → RAGResponse(answer, citations, grounded)
 ↓
UI (citations → EvidenceNavigator → PDF page / slide / media seek)
```

Key architectural facts:
- **Dependency injection via `Container`** (`app/container.py`) with lazy singletons for every engine; heavy services instantiate only when first accessed.
- **Background work**: every heavy operation runs through `TaskManager` → `ThreadManager` (QThreadPool, max 4 threads). Workers accept `(progress_callback, cancel_event, *args)` and emit Qt signals.
- **AI concurrency bounded** by `AIResourceManager` (semaphores: 1 slot each for LLM/embedding/vision/speech + global limit 2) — designed for the 6.9 GiB RAM host.
- **Persistence layering**: `database/engine.py` (SQLAlchemy `Database`), `database/models.py` (shared `Base`), `database/migrations.py` (version 7). Batch 3/4 stores use per-call sessions.
- **Retrieval hydration**: at startup, `Container.retrieval_engine` calls `RetrieveEngine.hydrate_from_store(db_store)` — rebuilds the in-memory evidence map from SQLite, removes orphaned FAISS vectors, and persists the cleaned index.

---

## 3. BATCH 1 STATUS

All Batch 1 features verified present. Batch 1 is the file-explorer foundation.

| Feature | Status | Relevant files | Notes |
|---|---|---|---|
| Folder scanning (recursive) | COMPLETE | `services/folder_scanner.py` | `FolderScanner.scan()` — `Path.rglob`, cycle-safe, progress + cancel |
| Ignore patterns | COMPLETE | `folder_scanner.py::_should_ignore` | pattern matching; also hard-coded dir skip list in AI indexer |
| Metadata extraction | COMPLETE | `services/metadata_extractor.py` | size, MIME, ctime/mtime, owner, **SHA-256 checksum** |
| SHA-256 | COMPLETE (RUNTIME VERIFIED) | `metadata_extractor._calculate_checksum` | **89/89 indexed files have checksums in DB** |
| MIME detection | COMPLETE | `mimetypes.guess_type` | fallback `application/octet-stream` |
| Text extraction | COMPLETE | `text_extraction/` + `services/text_extractor.py` | pdf/docx/pptx/xlsx/txt/csv/json/xml/md; 16/89 files have extracted_text |
| SQLite indexing | COMPLETE | `services/sqlite_indexer.py` | `indexed_files` table, status enum, batch upsert |
| Background workers | COMPLETE | `services/task_manager.py`, `thread_manager.py` | QThreadPool pattern |
| File watcher | COMPLETE | `services/file_watcher.py` | watchdog, non-recursive, debounced in MainWindow |
| Progress UI | COMPLETE | `ui/dialogs/b1_progress_dialog.py` | scan dialog |
| Indexed Files panel | COMPLETE | `ui/indexed_files_widget.py`, `indexed_files_model.py` | list + double-click preview |
| Metadata panel | COMPLETE | `widgets/preview_panel.py` | shows metadata from indexed record |
| Extracted Text panel | COMPLETE | `preview_panel.py` | shows `extracted_text` |
| Delete/rename/move handling | PARTIAL | `ui/main_window.py::_incremental_reindex` | new/modified handled; **deleted files remain in `indexed_files` (stale rows)** |

Tests: `test_services.py` (8), `test_explorer.py` (9), `test_navigation.py` (7), `test_database.py` (9) — all pass.

**Batch-5 relevance:** `indexed_files` (89 rows, all with SHA-256) is the foundation for B5-04 exact-duplicate detection. Note the delete-handling gap (stale rows) matters for B5-03/04/10 accuracy.

---

## 4. BATCH 2 STATUS

| Feature | Status | Implementation | Notes |
|---|---|---|---|
| Ollama integration | COMPLETE (RUNTIME VERIFIED) | `ai/ollama_client.py` | `/api/generate`, `/api/tags`; Ollama was running during audit |
| Local LLM (qwen-local) | COMPLETE (RUNTIME VERIFIED) | `ai/config.py` MODEL_NAME | qwen-local:latest reachable |
| AI analysis | COMPLETE | `ai/ai_service.py`, `ai/analysis_manager.py` | analyze_file → summary/keywords/tags/category/language |
| Summary generation | COMPLETE | prompt_builder + ai_service | stored in `ai_analysis.summary` |
| Keywords | COMPLETE | same | JSON array in `ai_analysis.keywords` |
| Tags | COMPLETE | same | JSON array in `ai_analysis.tags` |
| Category | COMPLETE | same | `ai_analysis.category` (free-form LLM string, e.g. "technical") |
| Language detection | COMPLETE | same | `ai_analysis.language` |
| AI metadata storage | COMPLETE (RUNTIME VERIFIED) | `ai/cache_manager.py` → `ai_analysis` | **3 rows present in DB** |
| Analysis caching | COMPLETE | `AICacheManager` keyed by SHA-256 | identity survives rename/move |
| Regeneration | COMPLETE | MainWindow `_on_ai_regenerate` | recompute hash → overwrite analysis |
| Background AI processing | COMPLETE | TaskManager worker | `_perform_ai_analysis` |
| AI dialog | COMPLETE | `ui/dialogs/ai_analysis_dialog.py` | view + regenerate |
| Error handling | COMPLETE | `ai_service` returns `{"error": ...}` dicts | UI surfaces message |

Entry points: right-click file → **AI → Analyze File / View Analysis / Regenerate Analysis**.

**Batch-5 relevance (B5-01/02):** `category`, `tags`, `keywords` already exist per content-hash and are populated. Missing: searchability (no join to `indexed_files`), editability, versioning (prompt_version column exists but is not surfaced in UI), and any UI showing tags/category in the file list.

---

## 5. BATCH 3 STATUS

All components verified present. (Full details in `batch4_audit_report.md`; abbreviated here with the facts Batch 5 needs.)

### CONTENT
- **ContentEngine** — `engines/content_engine.py`, `UniversalContentEngine.extract()` → `ContentBlock[]` with `source_type/source_index/source_label/modality/timestamps/confidence/metadata`. Handles PDF (per-page + **embedded images OCR/caption**), PPTX (per-slide + embedded images), DOCX (sections + embedded images), XLSX (per-sheet), CSV, text/code (500-char sections), images, audio, video.
- **Image**: OCR (tesseract) + moondream caption, `source_type=ocr|caption`, `modality=image`.
- **Audio**: Whisper, ~30s grouped segments, `source_type=transcript`, `timestamp_start/end`.
- **Video**: ffmpeg audio → Whisper + up to 5 keyframes captioned, `source_type=transcript|keyframe`.

### EVIDENCE
- **EvidenceEngine** — `engines/evidence_engine.py`; `build_evidence(file)` → `EvidenceChunk[]` (400-char chunks, 50 overlap, uuid4 chunk_id, char offsets, full provenance). `file_hash` = SHA-256.
- Persisted via `EngineDBStore.store_evidence` → `evidence` table (currently **0 rows at runtime**).

### EMBEDDINGS
- **EmbeddingEngine** — `engines/embedding_engine.py`; nomic-embed-text via Ollama `/api/embed`; batch with sequential fallback; query/document prefixes; dimension 768 (auto-adjusts).

### VECTOR SEARCH
- **VectorEngine** — `engines/vector_engine.py`; FAISS `IndexFlatIP`, L2-normalized cosine; `add/add_batch/search/remove_by_chunk_ids/save/load/clear`; chunk_id list pickled to `.ids`; thread-locked; **rebuild-on-remove** (O(n) reconstruct).
- On-disk `cache/faiss_index.bin` currently **0 vectors** (was 1,213 with 0 matching evidence rows at the Batch-3 audit; startup hydration removed the orphans — by design).
- **Hydration** (`retrieval_engine.hydrate_from_store`) guarantees: every FAISS id resolves to persisted evidence (invariant enforced by removing orphans).

### RETRIEVAL
- **RetrievalEngine** — `engines/retrieval_engine.py`. One API: `retrieve(query, scope, top_k, threshold, file_filter, max_chunks_per_file)`; plus `smart_retrieve` (modality detection + per-file dedup), `retrieve_similar(file_path)` (**average-of-chunks vector → FAISS search excluding source — the existing near-duplicate primitive**), `remove_file`, `hydrate_from_store`, `validate_vector_evidence_integrity`.
- Scopes: SELECTED_FILE, FOLDER, WORKSPACE, SELECTED_FILES.
- Ranking: cosine score, per-file cap (3), optional LLM `rerank_results` (in `rag_engine`).
- `record_search` writes `search_history` on every UI search (currently **0 rows** because the index is empty → searches return early).

### RAG
- **RAGEngine** — `engines/rag_engine.py`: `ask`, `ask_file`, `ask_file_direct` (Tier-1 full-file, per modality), `answer_multi`, `resolve_followup`, `rerank_results`; citations built from evidence; grounded answers; graceful empty/error answers; `AIResourceUnavailable` handling.

Tests: `test_batch3.py` (20), `test_batch3_extended.py` (32), `test_multimodal.py` (34) — all pass.

---

## 6. BATCH 4 STATUS (MOST IMPORTANT FOR BATCH 5)

### B4-01 — Persistent Conversations: **COMPLETE**
- Tables: `conversations`, `conversation_messages`, `message_citations` (migration 7). Models in `database/models.py`.
- `ConversationStore` (create/list/get/rename/delete/append_message/get_messages; citations persisted with full evidence location; cascade delete; `ConversationPersistenceError`).
- `ConversationManager.ask()` pipeline: follow-up resolution → scoped retrieval → multi-doc context → bounded history → RAG generation → citations → persistence.
- Restart persistence: RUNTIME VERIFIED — DB contains 1 conversation row; tables exist; store CRUD covered by 49 tests.
- UI: Conversation History dialog (resume/delete), Chat dialog loads persisted history.

### B4-02 — Folder Chat: **COMPLETE**
- Entry: right-click folder → **AI → Chat with this Folder** (`FileExplorer.folder_chat_requested` → `MainWindow._on_folder_chat_requested`).
- Scope: `ScopeManager.file_filter` — folder prefix match over the in-memory evidence map; post-filter `path_in_scope`.
- Nested folders: yes (prefix match `base + os.sep`).
- Citations: yes (persisted `message_citations`).

### B4-03 — Workspace Chat: **COMPLETE**
- Entry: **Tools → Workspace Chat...**.
- Scope: workspace (no file_filter), full index.
- Conversation persistence: yes (each dialog creates a conversation).

### B4-04 — Multi-Document Reasoning: **COMPLETE**
- `MultiDocumentContextBuilder` (per-file grouping, 3-chunk cap) + `RAGEngine.answer_multi` with `_MULTI_DOC_INSTRUCTIONS` (contradiction reporting, source attribution).
- Used by all chat (Folder/Workspace) and the agent's `compare_documents`.

### B4-05 — Knowledge Graph: **COMPLETE (with a structural limitation critical to B5-07)**
- Schema: `graph_entities`, `graph_relationships`, `graph_evidence_links` (migration 7).
- **Node types:** ENTITY nodes only — 10 controlled types (PERSON, ORGANIZATION, LOCATION, PROJECT, CONCEPT, TECHNOLOGY, DOCUMENT, ALGORITHM, PRODUCT, TOPIC).
- **Relationship types:** free-form lowercase LLM verb phrases (e.g. `discusses`, `uses`, `part_of`) — NOT the B5-07 controlled set.
- **FILE → FILE relationships: DO NOT EXIST.** The graph is strictly **ENTITY → ENTITY**.
- Normalization: `normalize_entity_name` (case/whitespace/punctuation folding); dedup on normalized name; aliases merged.
- Evidence linking: every relationship carries `graph_evidence_links` rows (chunk_id, file_path, source_label, source_index) — files are reachable *through* entities (`related_files()` returns distinct file paths for an entity), but files are not first-class nodes.
- Confidence: stored per relationship (`confidence` column, min 0.5 filter).
- Provenance: stored (evidence links + file_path).
- Synchronization: `GraphStore.remove_file()` cascades (evidence links → orphaned relationships → orphaned entities); wired via `AIFolderIndexer._remove_file_evidence` and `MainWindow._perform_ai_sync`.
- Queries: `search_entities`, `entity_details`, `relationships_with_evidence`, `neighbors`, `related_files`, `stats`.
- UI: Tools → Knowledge Graph; canvas + search + details + evidence double-click navigation.
- Runtime state: graph tables **empty (0 entities/relationships/links)** because the AI index is empty (graph extraction runs during AI indexing only).

### B4-06 — Agentic Workflows: **COMPLETE (read-only by design)**
- `AgentEngine.run()` loop: plan → tool → execute → observe → synthesize; guardrails: max_steps (8 default / config), wall-clock timeout (300s via config), sticky cancellation, read-only policy.
- 8 tools (all read-only): `search`, `retrieve_evidence`, `list_related_files`, `get_file_metadata`, `query_knowledge_graph`, `open_evidence`, `summarize_evidence`, `compare_documents`.
- Planner: LLM JSON tool selection with deterministic `search` fallback; synthesis with fallback aggregation.
- Persistence: **no agent-run persistence** (runs are ephemeral; answers shown in dialog only).
- Organization-related operations: **none** (read-only policy prohibits writes).
- UI: Tools → Agent Mode; live action status via Qt-signal bridge (RUNTIME VERIFIED thread-safe).

---

## 7. DATABASE AUDIT

**RUNTIME VERIFIED** — `config/intellivault.db` (1,630,208 bytes), schema_version = **7** (migration 7 applied 2026-08-11 20:29:30).

### Row counts (live)
| Table | Rows | Used at runtime? |
|---|---|---|
| `indexed_files` | **89** | Yes (Batch 1 index; all have checksums; 16 with extracted_text; 0 missing on disk) |
| `ai_analysis` | **3** | Yes (Batch 2 analysis) |
| `conversations` | **1** | Yes (chat) |
| `conversation_messages` | **0** | — |
| `message_citations` | **0** | — |
| `evidence` | **0** | — (AI index empty) |
| `vector_map` | **0** | — |
| `search_history` | **0** | — (searches return early on empty index) |
| `embeddings` | **0** | **DEAD — never populated** (migration 3; FAISS + evidence used instead) |
| `file_content_fts` (+ shadow tables) | **0** | **DEAD — never populated** (migration 2; triggers only fire on `files` inserts) |
| `graph_entities` / `graph_relationships` / `graph_evidence_links` | **0** | — |
| `files` / `folders` | 6 / 4 | **Dead — only test data** (paths under /tmp); not used by runtime flows |
| `tasks` | **5,840** | Yes — **unbounded growth** (every task append-only) |
| `recent` | 50 | Yes |
| `favorites` | 1 | Yes |
| `settings` | 9 | Yes |
| `logs` | 11 | Yes (Batch 1 logging) |
| `plugins` | 0 | — |

### Schema highlights
- **`indexed_files`**: id PK, filename, **absolute_path UNIQUE**, size, mime_type, extension, created_date, modified_date, **checksum** (SHA-256), extracted_text, metadata_json, scan_timestamp, indexing_status, processing_attempts, error_message, last_updated.
- **`ai_analysis`**: id PK, **file_hash UNIQUE (SHA-256)**, summary, keywords (JSON), tags (JSON), category, language, ai_generated, generated_time, prompt_version, model_name.
- **`evidence`**: id PK, **chunk_id UNIQUE**, file_path (idx), file_hash (idx), text, source_type, source_index, source_label, char_start, char_end, modality, timestamp_start/end, confidence, metadata_json, indexed_at.
- **`vector_map`**: id PK, chunk_id UNIQUE, file_path (idx), file_hash (idx), embedding_model, indexed_at. **Written by `_persist_indexed` but never read at runtime** (only `get_all_vector_maps` for the integrity check; hydration uses `evidence` only).
- **`search_history`**: id, query, scope, results_count, elapsed_ms, searched_at. Written by `MainWindow._perform_semantic_search` → `db_store.record_search`.
- **`conversations`**: id, title, scope_type, scope_path, created_at, updated_at, status, model_name, metadata_json.
- **`conversation_messages`**: id, conversation_id FK CASCADE, role, content, created_at, sequence_number, metadata_json.
- **`message_citations`**: id, message_id FK CASCADE, chunk_id, file_path, source_label, source_index, char_start/end, timestamp_start/end, citation_order, metadata_json.
- **`graph_entities`**: id, canonical_name, normalized_name (idx), entity_type (idx), metadata_json, created/updated.
- **`graph_relationships`**: id, source_entity_id FK CASCADE, target_entity_id FK CASCADE, relationship_type, confidence, metadata_json, created_at.
- **`graph_evidence_links`**: id, relationship_id FK CASCADE, chunk_id, file_path (idx), source_label, source_index, char_start/end, metadata_json.

### Observations for Batch 5
- **Exact duplicates already exist in data:** 13 indexed files share the SHA-256 of an empty file (`e3b0c44…`); one document (`b55f4f6…`) has **3 copies**; two other hashes have 2 copies each. A simple `GROUP BY checksum HAVING COUNT(*)>1` query is the whole B5-04 backend seed.
- No index on `indexed_files.checksum` (needed for efficient duplicate queries at scale).
- No link between `ai_analysis` and `indexed_files` (join by hash is possible but not indexed both ways — ai_analysis.file_hash is indexed/unique; indexed_files.checksum is not).
- `tasks` table needs pruning or TTL (5,840 rows).
- B5 needs: `collections`/`collection_items`, `saved_searches`, `file_relationships` (or FILE nodes in graph), `duplicate_groups`, `organization_suggestions` — none exist yet.

---

## 8. FILE IDENTITY AND SYNCHRONIZATION

### Identity mechanism (RUNTIME VERIFIED)
- **Primary identity = absolute path** for the Batch-1 index (`indexed_files.absolute_path` UNIQUE) and the AI index (`evidence.file_path`, `vector_map.file_path`).
- **Content identity = SHA-256** computed independently in 5 places: `MetadataExtractor._calculate_checksum` (Batch 1, stored), `ContentEngine._compute_hash`, `EvidenceEngine._compute_hash`, `AIFolderIndexer._hash_file`, `AnalysisManager._compute_file_hash`. Stored in `indexed_files.checksum`, `ai_analysis.file_hash` (UNIQUE), `evidence.file_hash`, `vector_map.file_hash`.
- No inode/file-id used. Modification time (`modified_date`) used to detect changes.

### Change propagation (STATICALLY VERIFIED)
| Event | SQLite index | AI metadata | Evidence/FAISS | Vector map | Graph | UI |
|---|---|---|---|---|---|---|
| New file | ✅ `_incremental_reindex` (mtime > stored) | ❌ not auto-analyzed | ✅ `_ai_sync_path` → `reindex_file` (only if index non-empty) | ✅ | ✅ | ✅ refresh |
| Modified file | ✅ (mtime newer) | ❌ not re-analyzed | ✅ `reindex_file` (removes stale first) | ✅ | ✅ (via remove+index) | ✅ |
| Deleted file | ❌ **stale row remains in `indexed_files`** | ❌ analysis row remains | ✅ removed by `_ai_sync_path` (only if index non-empty) | ✅ | ✅ | ✅ |
| Renamed/Moved | ❌ old path row remains; new path indexed as new | ✅ hash-keyed analysis survives | ⚠️ old-path evidence removed on delete event; new path reindexed | ⚠️ same | ⚠️ same | ⚠️ |

**Stale-data risks for Batch 5:**
1. `indexed_files` never prunes deleted paths → **B5-04/05/10 will count phantom files** unless reconciliation is added.
2. AI sync is **guarded by `indexed_count == 0`** — currently the AI index is empty, so delete events are no-ops; if Batch 5 computes duplicates/similarity from `indexed_files` (which has stale rows) vs evidence (which is reconciled), counts diverge.
3. Renames produce delete+create event pairs; AI sync handles the delete only when the index is non-empty.
4. `ai_analysis` rows are never deleted when files disappear (hash-keyed; harmless for analysis, but dashboard "analyzed files" counts must be derived from `indexed_files` join, not `ai_analysis` alone).

---

## 9. CURRENT SEARCH CAPABILITIES

| Mechanism | Input | Backend | DB | Vector | Scope | UI | Result | Ranking | Citations | Tests |
|---|---|---|---|---|---|---|---|---|---|---|
| Filename search | toolbar/name filter | `QFileSystemModel` name filters | — | — | current folder | toolbar | file list | — | — | test_explorer |
| Full-text (FTS5) | — | **dead** (FTS table empty, no code path) | ❌ | — | — | — | — | — | — | — |
| Semantic search | NL query | `RetrievalEngine.smart_retrieve` | evidence (hydrated) | FAISS | workspace + modality filter | Semantic Search dialog | ranked chunks w/ provenance | cosine + per-file dedup + optional LLM rerank | High/Med/Low label | test_batch3 |
| Related-file search | file path | `RetrievalEngine.retrieve_similar` | evidence | avg-vector FAISS | workspace (excl. source) | ⚠️ **no direct UI entry** (used by agent `list_related_files`) | chunks | cosine | — | ✅ (in test_batch4?) — STATICALLY only |
| Graph search | entity name | `GraphQueryService.search_entities` | graph tables | — | graph | Graph dialog | entities + rels + files | name match | — | test_batch4 |
| Conversational retrieval | NL in chat | `ConversationManager.ask` → RAG | conversations + evidence | FAISS | file/folder/workspace | Chat dialogs | grounded answer + citations | retrieval + per-file cap | ✅ persisted | test_batch4 |
| Agent search | NL request | AgentEngine tools | evidence + graph | FAISS | workspace | Agent Mode | synthesized answer | tool loop | inline file cites | test_batch4 |

**Relevance to B5-06 (Related Files) and B5-09 (Saved Searches):**
- B5-06 can build directly on `retrieve_similar()` + `smart_retrieve()` dedup + graph `related_files()`.
- B5-09: `search_history` exists (query, scope, results_count, elapsed_ms) and is written on UI searches — but **queries are not named, embeddings not persisted, filters not persisted, and there is no re-run capability**. `search_history` is a good base to extend or a clear precedent for a `saved_searches` table.

---

## 10. CURRENT UI

**RUNTIME VERIFIED** (app boots offscreen; all dialogs constructed in tests; structure read from source).

- **MainWindow** — central navigation (toolbar back/up/forward/refresh), path breadcrumb, sidebar docks (folder tree, drives, favorites), file explorer (list/grid), preview panel, status bar, indexed-files dock, log dock. 1,633 lines — the largest file; holds all orchestration.
- **Menus** — File (Quit), Edit (Copy/Move/Delete **placeholders, unconnected**), View (sidebar/preview/theme/refresh), **Tools (Workspace Chat…, Knowledge Graph…, Conversation History…, Agent Mode…, Settings…)**, Help (About).
- **Explorer context menu** — Open/Rename/Copy/Move/Delete/Properties; **AI submenu: Analyze File, View Analysis, Regenerate Analysis, Semantic Search, Ask AI about this File, Chat with this Folder**.
- **Dialogs**: SemanticSearch (query + modality combo + results list), AskAI (answer + citations), AIAnalysis (view/regenerate), B1Progress, Chat (scope label + ChatView), Graph (canvas + entity search + details + relationships + evidence list), Agent (ChatView + action strip), ConversationHistory (list + resume/delete), Settings (tabs: General, Appearance, File Explorer, Database, Plugins, Performance, **Batch 4**; AI/OCR/Models/Embeddings/LLM tabs are **disabled placeholders**).
- **ChatView/MessageBubble** — reusable; states ready/retrieving/generating/completed/failed/cancelled; Stop button; clickable citations.
- **Settings** — `ui/settings_dialog.py`; Batch 4 tab edits `batch4.*` keys (default scope, history chars/turns, top_k, threshold, graph_enabled, agent steps/timeout/enabled). Note: Batch 4 keys are **not mirrored to the DB `settings` table** (only the original 9 keys are).

**Safest Batch-5 UI extension points (do not redesign):**
1. **Tools menu** — add Collections, Duplicates, Related Files, Saved Searches, Dashboard entries (pattern already established by Batch 4 entries in `menu_bar.py`).
2. **Explorer AI submenu** — add per-file actions (Classify, Auto-Tag, Find Duplicates, Find Related) in `file_explorer._on_context_menu`.
3. **SettingsDialog** — add a "Batch 5" tab following the Batch 4 tab pattern.
4. **Docks** — a Collections dock or Dashboard dock can be added via `dock_manager.py`.
5. **SignalBus** — events for index/analysis refresh.

---

## 11. CURRENT AI INFRASTRUCTURE

| Component | Value | Where configured | Where used | Reachable? |
|---|---|---|---|---|
| LLM | `qwen-local:latest` | `engines/config.py LLM_MODEL`, `ai/config.py MODEL_NAME` | RAGEngine, AIService, Entity/Relationship extractors, Planner | RUNTIME VERIFIED (answered queries in earlier smoke tests) |
| Embedding | `nomic-embed-text` (768-d) | `engines/config.py EMBEDDING_MODEL` | EmbeddingEngine via `/api/embed` | RUNTIME VERIFIED (loaded in Ollama) |
| Vision | `moondream:latest` | `engines/config.py VISION_MODEL` | image captioning, embedded images, video keyframes, `_ask_image_direct` | RUNTIME VERIFIED (present in Ollama) |
| Speech | Whisper `base` | `engines/config.py WHISPER_MODEL` | AudioExtractor/VideoExtractor (cached globally) | RUNTIME VERIFIED (model cached) |
| CLIP | ViT-B/32 (512-d, CPU) | `engines/clip_engine.py` | image visual vectors in AI indexing (optional) | STATICALLY VERIFIED; `is_available()` gates |
| OCR | tesseract 5.3.4 via pytesseract | — | ImageExtractor, embedded images | RUNTIME VERIFIED (installed) |
| FFmpeg | system | — | VideoExtractor audio extraction | RUNTIME VERIFIED (installed) |

- **Model loading**: lazy + cached — CLIP and Whisper load once (global caches); Ollama models load on first request (server-side).
- **AIResourceManager** bounds concurrency: 1 slot each for LLM/embedding/vision/speech + global limit 2; callers acquire exactly one slot; cancellation event checked before acquisition.
- **Timeouts**: RAG 300s, direct ask 90s (vision), embed 60/120s, OllamaClient 480s, agent 300s (config).
- **Prompts**: `ai/prompt_builder.py` (analysis), `rag_engine` (RAG/direct/multi-doc/rerank/follow-up), `graph/entity_extractor` + `relationship_extractor` (JSON-only), `agent/planner.py` (tool selection).
- **Batch-5 reuse**: LLM + embedding + vision all directly reusable for classification, tagging, and suggestion generation; AIResourceManager prevents Batch-5 AI workloads from flooding the 6.9 GiB machine.

---

## 12. CURRENT KNOWLEDGE GRAPH (DETAILED)

1. **Node types:** ENTITY only (10 controlled types; everything else coerced to CONCEPT). **No file nodes.**
2. **Relationship types:** free-form LLM verb phrases; validated endpoints; dedup on (source, relation, target); min confidence 0.5.
3. **Normalization:** `normalize_entity_name` — lowercase, strip non `[a-z0-9 '&-]`, collapse whitespace; aliases merged into `metadata_json.aliases`; deliberate NO fuzzy merging.
4. **Evidence linking:** `graph_evidence_links` rows per relationship → chunk_id/file_path/source_label/source_index.
5. **Update on file change:** `GraphStore.remove_file` (cascade delete) called from `AIFolderIndexer._remove_file_evidence` and `MainWindow._perform_ai_sync`; new files get graph extraction during AI indexing (`GraphEngine.index_file`, bounded to 20 chunks/file).
6. **Can graph queries return files?** YES indirectly — `related_files(entity_id)` returns distinct file paths linked to an entity's relationships.
7. **Can graph queries return related files?** Only "files related to an entity". NOT "files related to a file".
8. **File-to-file relationships:** NO — structurally impossible today (relationships require `source_entity_id`/`target_entity_id`; files are not entities).
9. **Confidence stored:** YES (`graph_relationships.confidence`).
10. **Provenance stored:** YES (evidence links).

**Can the current Knowledge Graph support B5-07 directly? NO.** B5-07 needs `related_to | duplicate_of | similar_to | references | derived_from | belongs_to_project` between **files**. Options for the plan: (a) add FILE as a node type and synthesize file→file edges from shared entities/evidence + duplicate/similarity computation, or (b) a separate `file_relationships` table. The graph's existing evidence-linking and cascade-delete machinery would be reused either way.

---

## 13. DUPLICATE DETECTION READINESS

### Exact duplicates (B5-04) — **READY at data level**
- SHA-256 already computed and stored for **all 89 indexed files** (`indexed_files.checksum`).
- **Real duplicates already exist in the live DB** (RUNTIME VERIFIED):
  - `e3b0c44…` (SHA-256 of empty content): **13 files**
  - `b55f4f6…`: **3 files** (matches a row in `ai_analysis`)
  - `e01ef40…`, `fa101a7…`: **2 files each**
- Query pattern exists in code (`ai_analysis.file_hash` UNIQUE, `evidence.file_hash` indexed); the GROUP BY query itself is not yet implemented anywhere.
- Missing: index on `indexed_files.checksum`, a DuplicateEngine, a results UI, and handling for empty-content files (13 empties — should be grouped or excluded).

### Near duplicates (B5-05) — **PRIMITIVES EXIST, FEATURE DOES NOT**
- Existing primitives:
  - nomic-embed-text 768-d vectors in FAISS (cosine-normalized) — the core similarity substrate.
  - `RetrievalEngine.retrieve_similar(file_path, top_k)` — average of a file's chunk vectors → FAISS search excluding source. **This is exactly the B5-05 query primitive for one file.**
  - `smart_retrieve` per-file dedup; per-file chunk caps.
- Missing: workspace-wide pairwise/centroid clustering, configurable similarity threshold calibrated for "near" (only High/Medium/Low labels at 0.80/0.60 exist), chunk→file aggregation, and any UI.
- No perceptual/image hashes exist (CLIP vectors are the image similarity substrate, but no image-duplicate detector).

---

## 14. CLASSIFICATION AND TAGGING READINESS

Existing (RUNTIME VERIFIED in DB):
- `ai_analysis.category` — 3 rows populated (e.g. "technical", "Technical").
- `ai_analysis.tags` — JSON arrays populated (e.g. `["development","desktop app","AI integration","Python","Qt6"]`).
- `ai_analysis.keywords` — JSON arrays.
- `ai_analysis.summary`, `language`, `model_name`, `prompt_version`, `generated_time`.

Properties:
| Property | Status |
|---|---|
| Persisted | ✅ (`ai_analysis`, keyed by SHA-256) |
| Searchable | ❌ — no join path to `indexed_files` used; no tag/category filter in any UI |
| Editable | ❌ — LLM-only; no user editing |
| Versioned | ⚠️ — `prompt_version` column exists ("1.0" from `ai/config.py`), not surfaced |
| Regenerated | ✅ — right-click → AI → Regenerate |
| Associated with file identity | ✅ — content hash (survives rename/move) but **not** with `indexed_files` rows directly |
| Coverage | ⚠️ — only 3/89 files analyzed (analysis is per-file manual action; no batch analysis) |

Missing for B5-01/02: batch classification/tagging pipeline (can reuse `AnalysisManager`/`AIService`/`prompt_builder`), controlled category taxonomy (currently free-form LLM strings — note "technical" vs "Technical" inconsistency already in data), tag vocabulary/consolidation (duplicate tags from free text), join/UI for browsing by category/tag, and propagation into the file list.

---

## 15. COLLECTION READINESS

Existing:
- `favorites` table (path-based user favorites, 1 row) — a simple hard-coded list, not a collection system.
- Folder tree / virtual folders: **none** (collections are not folders).
- Saved searches: **none** (`search_history` is a passive log only).
- Filters: only the Semantic Search modality combo (All/Documents/Images/Audio/Video).
- Smart filters / labels / user groups: **none**.

**B5-03 Smart Collections: NOT READY** — requires new `collections` + `collection_items` tables (or equivalent), a collections engine (query/member model — static lists, saved searches, or semantic criteria), and a Collections UI (dock or dialog). The only reusable piece is the `favorites` precedent and `RetrievalEngine` for semantic-criteria collections.

---

## 16. ORGANIZATION SUGGESTION READINESS

Existing APIs Batch 5 can reuse for B5-08:
- **Category:** `ai_analysis.category` (3 rows).
- **Related files:** `RetrievalEngine.retrieve_similar(file)`; `smart_retrieve(q)`; agent `list_related_files`.
- **Topics:** `ai_analysis.keywords`/`tags`; graph CONCEPT/TOPIC entities.
- **Semantic similarity:** FAISS cosine + `retrieve_similar`.
- **Graph relationships:** `GraphQueryService` (`related_files(entity)`; entity→entity relations that can imply co-occurrence).
- **Metadata:** `indexed_files` (size/type/dates); `services/metadata_extractor.py`.

Missing: a suggestion engine that combines these into "recommended folder/collection" outputs, a non-destructive suggestions UI (the frozen scope requires recommendations only — no auto-move), and grounding/safety around hallucinated suggestions (mitigation: only suggest based on existing indexed evidence, e.g. "files already in this folder are topically similar").

---

## 17. SAVED SEARCH READINESS

- `search_history` table: id, query, scope, results_count, elapsed_ms, searched_at — written on each UI semantic search (`MainWindow._perform_semantic_search` → `db_store.record_search`). **0 rows** currently (empty index short-circuits).
- `EngineDBStore.get_recent_searches(limit)` reads it (used nowhere in UI yet — no recent-searches panel).
- Query embeddings: **not persisted** (recomputed on each search — fine for rerun, since nomic is deterministic per text).
- Scopes: only the modality string stored; folder scope not recorded.

Minimum infrastructure for B5-09: a `saved_searches` table (name, query, scope/modality, created, last_run) — or extend `search_history`; a SavedSearchManager (CRUD + run); a UI (dialog + entries in the Semantic Search dialog); a re-run path reusing `smart_retrieve`. "Reflect newly indexed content" works for free because re-running re-embeds the query against the current FAISS index.

---

## 18. DASHBOARD READINESS

Data already obtainable with existing queries:
- Total files: `SQLiteIndexer.get_indexing_stats()` → total (89).
- Files by type: `indexed_files.extension` GROUP BY (RUNTIME VERIFIED: .tmp 15, '' 13, .zip 11, .png 11, .txt 8, .pdf 7, .pptx 6, …).
- Files by category/tag: `ai_analysis` (3 rows) — needs join by hash.
- AI analyzed count: `ai_analysis` count (3).
- Semantic index count: `RetrievalEngine.indexed_count` (0) + `validate_vector_evidence_integrity`.
- Graph counts: `GraphStore.stats()` → entities/relationships/evidence_links (0/0/0).
- Duplicate count: GROUP BY checksum (data present, no API).
- Recent files: `recent` table (50) and `indexed_files.last_updated`.
- Most common topics: keywords/tags aggregation (parse JSON) — no API yet.
- Indexing status: `get_indexing_stats` (completed/pending/failed + rate).

**B5-10 readiness: PARTIALLY READY** — most aggregates exist as raw queries; what's missing is a DashboardService that composes them, and a Dashboard UI (dock or dialog). Data caveat: with the AI index empty, "semantic index" and "graph" metrics will read 0 until a user runs Index for AI.

---

## 19. TEST AUDIT

**RUNTIME VERIFIED — full suite run on the audit machine:**

```
261 passed in 346.88s (0:05:46)
0 failed · 0 errors · 0 skipped
```

| File | Tests | Category |
|---|---|---|
| test_batch2_integration.py | 6 | Integration (Batch 2) |
| test_batch2_unit.py | 30 | Unit (Batch 2) |
| test_batch3_extended.py | 32 | Batch 3 / retrieval / multimodal |
| test_batch3.py | 20 | Batch 3 |
| test_batch4.py | **49** | **Batch 4: conversations, scopes, citations, graph, agent, UI smoke** |
| test_config.py | 5 | Unit |
| test_database.py | 9 | Database |
| test_explorer.py | 9 | UI |
| test_indexed_files.py | 6 | UI |
| test_logging.py | 3 | Unit |
| test_main_window.py | 7 | UI/integration |
| test_multimodal.py | 34 | Multimodal (image/audio/video) |
| test_navigation.py | 7 | UI |
| test_plugin_registry.py | 7 | Unit |
| test_preview_panel_extracted_text.py | 8 | UI |
| test_preview_panel_metadata.py | 6 | UI |
| test_preview.py | 9 | UI |
| test_services.py | 8 | Unit |
| test_settings.py | 6 | UI |

Categorization: ~90 unit, ~80 UI, ~90 integration/multimodal/Batch-4. Tests avoid external services (Ollama/CLIP/Whisper are mocked or gated); no tests require Ollama or large models; no skips.

**Missing tests relevant to Batch 5:**
- No tests for `retrieve_similar` (near-duplicate primitive) as a first-class feature.
- No tests for duplicate detection (no feature exists).
- No tests for `record_search`/`search_history` persistence round-trip (the method exists but has no direct test).
- No tests for classification/tagging taxonomy or category consistency.
- No dashboard/aggregation tests.
- Known flake/robustness quirks (documented, not failing): three legacy preview test files rely on the session-scoped `qapp` fixture and abort when run standalone (they only pass inside the full suite); the full suite takes ~6 minutes and is sensitive to machine load/disk contention.

---

## 20. RUNTIME VERIFICATION

Performed on this machine (Ollama running; offscreen Qt):

| Check | Result |
|---|---|
| 1. Application startup (offscreen) | ✅ RUNTIME VERIFIED — MainWindow constructs; container boots |
| 2. Lazy engine init | ✅ RUNTIME VERIFIED — rag/conversation/graph/agent/retrieval all construct; agent exposes 8 tools |
| 3. FAISS integrity | ✅ RUNTIME VERIFIED — `{active_vectors:0, evidence_in_memory:0, ..., valid:True}` (empty index is consistent) |
| 4. Graph stats | ✅ RUNTIME VERIFIED — 0 entities/relationships/links |
| 5. Full test suite | ✅ RUNTIME VERIFIED — 261/261 pass |
| 6. DB inspection | ✅ RUNTIME VERIFIED — 24 tables; schema v7; row counts above |
| 7. Semantic search / Ask AI / Chat / Graph / Agent with live data | ⚠️ **NOT VERIFIED end-to-end in this audit** — the AI index is empty (0 evidence), so retrieval-based flows return "no files indexed". Earlier Batch-3/4 smoke tests (temp DB + temp FAISS + live Ollama) verified index→search→hydration→Ask AI end-to-end (documented in `batch4_audit_report.md`). |
| 8. Conversation persistence | ✅ RUNTIME VERIFIED at the storage layer (1 conversation row; CRUD covered by 49 passing tests) |
| 9. Restart persistence | ✅ Storage-layer verified (schema v7, hydration path exercised by tests); full GUI restart loop not re-run |

---

## 21. PERFORMANCE AUDIT

Target environment: Intel i3-N305, **6.9 GiB RAM**, CPU-only, disk ~98% full.

| Area | Current state | Batch-5 concern |
|---|---|---|
| FAISS | Flat index (exact search), in-memory; rebuild-on-remove O(n); 0 vectors now, ~1,213 max observed | B5-05 workspace-wide near-duplicate = O(n²) embedding comparisons if naive; must reuse chunk vectors, not re-embed |
| Embedding workload | Batch + sequential fallback; 1 slot | Classification/tagging across 89+ files = N LLM calls; needs batch + resource slots + progress/cancel |
| Graph extraction | LLM per chunk (≤20 chunks/file) | Reuse for suggestion features; bounded already |
| Task queue | `tasks` table unbounded (5,840 rows); ThreadPool max 4 | Dashboard reads must avoid scanning all tasks |
| Duplicate model loading | CLIP/Whisper global-cached; Ollama server-side cache | No known duplicate loading |
| DB queries | Session-per-call; some N+1 patterns in graph dialog | `GROUP BY checksum` fine; tag joins need indexes |
| UI thread | Heavy work always off-thread; AI sync guarded by indexed_count==0 | Keep Batch-5 AI work in TaskManager workers |
| Memory | 2-slot global AI limit designed for this box | B5 AI features must acquire AIResourceManager slots |

No benchmark numbers were measured (no perf harness exists); these are structural observations.

---

## 22. ERROR HANDLING

| Scenario | Current behavior |
|---|---|
| Ollama unavailable | Embedding/RAG return empty → dialogs show "Ensure Ollama is running"; graceful |
| Model unavailable | `is_available()` checks; errors surfaced |
| Invalid LLM output | `ai/json_parser.py` + entity/relationship extractors regex-extract JSON, else empty; planner falls back to deterministic search |
| Corrupt/unsupported file | Extractors catch exceptions → `[]` → file skipped with error recorded |
| DB failure | `PersistenceError` (evidence/conversations) and `GraphPersistenceError` propagate to callers/UI; some reads silently return `[]` |
| FAISS failure | logged; `add` returns False; index not corrupted |
| Worker cancellation | Cooperative via `cancel_event` checked between stages; AgentState sticky cancel |
| Task timeout | Agent: wall-clock timeout (status=timeout); tools: per-tool timeout documented but **not hard-enforced** (interrupt-less) — noted limitation |
| Silent failures | ⚠️ Several: `metadata_extractor._calculate_checksum` returns "" on IO error (files silently get empty checksums); deleted-file handling is silent; `_ai_sync_path` silently no-ops when index empty; `record_search` failures logged at debug |

Batch-5 must add: explicit handling for duplicate/similarity computation failures and, per frozen scope, a prominent "suggestion confidence" caveat to counter model hallucination.

---

## 23. TECHNICAL DEBT

| ID | Description | Severity | Module | Batch-5 impact |
|---|---|---|---|---|
| TD-1 | `embeddings` + FTS5 tables dead (never populated) | MEDIUM | database/migrations | Don't build B5-09 on them; avoid confusion in schema docs |
| TD-2 | `vector_map` written but never read at runtime | MEDIUM | engines/ai_indexer + db_store | Integrity tooling exists but is unused in product flows |
| TD-3 | `tasks` unbounded (5,840 rows) | LOW | repository/task_manager | Dashboard must exclude tasks |
| TD-4 | Deleted files leave stale `indexed_files` rows | HIGH | main_window._incremental_reindex | **B5-04/05/10 counts will be wrong** unless fixed |
| TD-5 | `files`/`folders` tables dead (test data only) | LOW | database/models | Ignore for B5 |
| TD-6 | Duplicated SHA-256 computation (5 sites) | MEDIUM | multiple | Consolidate for B5-04 identity |
| TD-7 | `FileExplorer._check_ai_analysis_exists` opens a fresh Database per context menu | LOW | widgets/file_explorer | Minor perf |
| TD-8 | Edit menu placeholders (Copy/Move/Delete unconnected) | LOW | ui/menu_bar | — |
| TD-9 | Plugin context-menu hook disabled (`if False`) | LOW | widgets/file_explorer | Could host B5 extensions later |
| TD-10 | Batch-4 settings not mirrored to DB `settings` table | LOW | ui/settings_dialog | B5 settings tab should mirror consistently |
| TD-11 | `ai_analysis` free-form category (inconsistent case already: "technical"/"Technical") | MEDIUM | ai | B5-01 needs a controlled taxonomy |
| TD-12 | Graph full-view bounded at 120 entities with O(n²) name lookups | LOW | ui/dialogs/graph_dialog | File-to-file graph UI must avoid this pattern |
| TD-13 | `graphify-out/` + old-path docs (`system_architecture.md` points at `mini_project/IntelliScan`) | LOW | repo | Documentation drift; source is authority |

---

## 24. BATCH 5 FEATURE READINESS MATRIX

| Feature | Existing Support | Reusable Components | Missing Components | Risk | Readiness |
|---|---|---|---|---|---|
| B5-01 Intelligent Classification | `ai_analysis.category` (3 rows), LLM pipeline | `AIService`, `AnalysisManager`, `prompt_builder`, `ai_analysis` table | Batch classification engine, controlled taxonomy, file-list category display, join by hash | Free-form categories inconsistent | **PARTIALLY READY** |
| B5-02 Auto-Tagging | `ai_analysis.tags`/`keywords` persisted | same + `AICacheManager` | Tag vocabulary/consolidation, maintenance (add/remove/merge), UI | Tag drift, LLM hallucination | **PARTIALLY READY** |
| B5-03 Smart Collections | `favorites` precedent only | SignalBus, dock pattern, retrieval for criteria | `collections`/`collection_items` tables, engine, UI | Sync with file changes | **NOT READY** |
| B5-04 Exact Duplicate Detection | SHA-256 for **all 89 files**; real duplicates already in DB | `indexed_files.checksum`, hash code sites, `ai_analysis.file_hash` | Group query, index on checksum, DuplicateEngine, results UI | Empty-file dupes (13) need policy | **READY** |
| B5-05 Near-Duplicate Detection | `retrieve_similar`, FAISS cosine, chunk vectors | `RetrievalEngine.retrieve_similar`, `VectorEngine`, evidence store | Workspace-wide clustering, calibrated threshold, file-level aggregation, UI | O(n²) if naive | **PARTIALLY READY** |
| B5-06 Related File Discovery | `retrieve_similar`, `smart_retrieve` dedup, graph `related_files`, agent `list_related_files` | same | UI entry (per-file "Find Related"), explanation of relation | Score quality | **PARTIALLY READY** |
| B5-07 File-to-File Relationships | Entity graph + evidence links; **no FILE→FILE** | graph tables, cascade deletion, evidence linking | FILE nodes or `file_relationships` table; relation taxonomy | Graph redesign | **NOT READY** |
| B5-08 AI Organization Suggestions | category + related files + graph + metadata APIs | retrieval, graph, `ai_analysis` | Suggestion engine (evidence-grounded), non-destructive UI | Hallucinated suggestions | **PARTIALLY READY** |
| B5-09 Saved Semantic Searches | `search_history` table + `record_search` | `smart_retrieve`, `EngineDBStore` | `saved_searches` storage, manager, UI, re-run | Stale query semantics | **PARTIALLY READY** |
| B5-10 Workspace Knowledge Dashboard | indexing stats, graph stats, extension counts, recent | `SQLiteIndexer.get_indexing_stats`, `GraphStore.stats`, `recent` | DashboardService aggregation, dashboard UI | Empty AI index → 0s; stale rows | **PARTIALLY READY** |

---

## 25. BATCH 5 DEPENDENCY MAP

Derived from the actual codebase (not the audit prompt's example):

```
B5-04 Exact Duplicates (indexed_files.checksum — data ready)
      ↓
B5-05 Near Duplicates (retrieve_similar / FAISS chunk vectors)
      ↓
B5-06 Related Files (retrieve_similar + smart_retrieve + graph related_files)

B5-01 Classification (ai_analysis pipeline + controlled taxonomy)
      ↓
B5-02 Auto-Tagging (tags/keywords + vocabulary + maintenance)

B5-01 + B5-06 (+ B5-07 partial)
      ↓
B5-08 Organization Suggestions (evidence-grounded recommendations)

B5-04 + B5-05 + B5-06 + B5-07(if file relationships built)
      ↓
B5-07 File-to-File Relationships (files as graph nodes OR file_relationships table)

B5-01 + B5-02 + B5-06 + B5-07
      ↓
B5-03 Smart Collections (semantic/topic/category criteria)

B4 semantic search (RetrievalEngine) + search_history precedent
      ↓
B5-09 Saved Semantic Searches

All of the above
      ↓
B5-10 Knowledge Dashboard
```

The plan's example order is close to correct; one correction: **B5-07 (file relationships) depends on B5-04/05/06 outputs** (duplicates/similarity/relatedness are exactly the file→file edges), so it should be implemented after those, not as a sibling.

---

## 26. REQUIRED NEW DATABASE OBJECTS

Only what the frozen scope actually needs:

| Object | Why required |
|---|---|
| `collections` (id, name, description, criteria_json, created/updated, is_smart) | B5-03 storage |
| `collection_items` (collection_id FK, file_path, added_at, source) | B5-03 membership (path-based, matching `indexed_files.absolute_path` identity) |
| `saved_searches` (id, name, query, scope, modality, created/updated, last_run) | B5-09 (extend or parallel to `search_history`; `search_history` stays as the activity log) |
| `duplicate_groups` (id, hash, created, member_count) or reuse `GROUP BY checksum` view | B5-04/05 grouping (can be a query; table only if persistent UI state needed) |
| `file_relationships` (id, source_path, relation, target_path, confidence, evidence_json, created) | B5-07 — **unless** file nodes are added to the graph; separate table is simpler and avoids touching graph internals |
| `organization_suggestions` (id, file_path, suggested_target, reason, confidence, status[accepted/dismissed], created) | B5-08 (persist recommendations so user decisions survive restart) |
| Index: `indexed_files(checksum)` | B5-04 efficient grouping |
| Join index consideration: `ai_analysis(file_hash)` already unique/indexed; `indexed_files.checksum` needs the same treatment for hash joins |

Optional (not required): dashboard materialization — live queries are cheap at 89 files; materialize only if the workspace grows.

---

## 27. REQUIRED NEW BACKEND COMPONENTS

Recommended architecture (extend existing engines, avoid new parallel stacks):

| Component | Recommendation | Built on |
|---|---|---|
| Classification + tagging | **Extend** `ai/` — add `ClassificationEngine`/`TaggingEngine` (or one `OrganizationEngine`) that reuses `AIService`/`AnalysisManager`/`prompt_builder`, adds batch + controlled taxonomy + tag consolidation | `ai_service`, `analysis_manager`, `ai_analysis` |
| Duplicate detection | **New** `DuplicateEngine` (exact: `GROUP BY checksum`; near: reuse `retrieve_similar` per file with aggregation + configurable threshold) | `indexed_files.checksum`, `RetrievalEngine`, `VectorEngine` |
| Related files | **Extend** `RetrievalEngine` (expose per-file similarity as a first-class result) or thin `RelatedFileService` | `retrieve_similar`, `smart_retrieve`, graph `related_files` |
| File relationships | **New** `RelationshipEngine` persisting `file_relationships` (computed from duplicates + similarity + shared entities) | `DuplicateEngine`, `RetrievalEngine`, `GraphStore` |
| Collections | **New** `CollectionEngine` (CRUD + membership evaluation: static list, saved-search criteria, semantic criteria) | `RetrievalEngine`, `saved_searches` |
| Saved searches | **New** `SavedSearchManager` (CRUD + re-run) or extend `EngineDBStore` | `smart_retrieve`, `search_history` precedent |
| Organization suggestions | **New** `SuggestionEngine` — evidence-grounded recommendation (no moves/deletes; frozen scope) | classification, related files, relationships, metadata |
| Dashboard | **New** `DashboardService` composing existing stats + new aggregates | `SQLiteIndexer.get_indexing_stats`, `GraphStore.stats`, `RetrievalEngine`, new queries |
| Identity | **Refactor** duplicated SHA-256 into one `file_identity.py` helper | 5 existing hash sites |

All new engines should: run in TaskManager workers, acquire `AIResourceManager` slots for LLM work, raise/`PersistenceError`-style failures, and expose plain-dict results for UI.

---

## 28. REQUIRED NEW UI COMPONENTS

| Component | Extend vs New | Data source | User action → result |
|---|---|---|---|
| Category/tag display in file list + preview | Extend `indexed_files_model.py` / `preview_panel.py` | `ai_analysis` joined by hash | See category/tags on selection; browse by tag |
| Batch classification/tagging action | Extend explorer AI submenu + `ai_analysis_dialog` | `AnalysisManager` batch path | Right-click file/folder → AI → Classify / Auto-Tag → progress → persisted metadata |
| Collections panel | **New** dock or dialog (follows `dock_manager.py` pattern) | `CollectionEngine` | Create/edit collection; add files; view members |
| Duplicates results | **New** dialog ("Find Duplicates…" in Tools + context menu) | `DuplicateEngine` | Grouped list with sizes/paths; open members; merge policy UI |
| Related files panel | **New** dialog or dock ("Find Related…" per file) | `RelatedFileService` | Ranked list with scores + reason; click to open |
| File relationship view | Extend `graph_dialog.py` or **new** relationship list | `RelationshipEngine` | See related_to/duplicate_of/similar_to/etc. per file |
| Organization suggestions | **New** dialog with accept/dismiss (non-destructive) | `SuggestionEngine` | Suggested folder/collection + reason + confidence; user decides |
| Saved searches | **New** dialog + button in SemanticSearchDialog ("Save"/"Saved…") | `SavedSearchManager` | Save query+scope; re-run later; results reflect current index |
| Knowledge Dashboard | **New** dock or dialog (Tools → Dashboard) | `DashboardService` | Stats grid (files by type/category/tag, duplicates, graph, recent, index status) |

All new dialogs should follow the existing pure-presentation pattern: emit signals, MainWindow owns orchestration, work runs in TaskManager workers.

---

## 29. REUSE VS NEW IMPLEMENTATION

| Existing Component | Batch-5 Feature | Reuse As-Is | Extend | Replace | Reason |
|---|---|---|---|---|---|
| `indexed_files` + SHA-256 | B5-04 | ✅ | ⚠️ add checksum index | — | Data ready; only query + index needed |
| `RetrievalEngine.retrieve_similar` | B5-05, B5-06 | ✅ | ⚠️ expose + aggregate | — | Exact primitive exists |
| `VectorEngine`/FAISS | B5-05 | ✅ | — | — | Similarity substrate |
| `AIService`/`AnalysisManager`/prompts | B5-01, B5-02 | ✅ | ⚠️ batch + taxonomy | — | Full pipeline exists; 3 rows prove it works |
| `ai_analysis` | B5-01, B5-02, B5-10 | ✅ | ⚠️ searchable join | — | Persisted metadata |
| Graph store + evidence links | B5-07, B5-08 | ✅ (entity graph) | ⚠️ file relationships | — | No FILE→FILE today; extend, don't replace |
| `search_history` + `record_search` | B5-09 | ✅ precedent | ⚠️ saved-searches layer | — | Extend the pattern |
| `get_indexing_stats` / `GraphStore.stats` | B5-10 | ✅ | ⚠️ compose | — | Aggregates exist |
| `TaskManager`/`AIResourceManager` | all AI-heavy B5 | ✅ | — | — | Concurrency + bounds |
| `embeddings`/FTS5 tables | — | — | — | **ignore** | Dead infrastructure; don't build on it |

No working Batch 1–4 infrastructure should be replaced.

---

## 30. RISKS

| Risk | Probability | Impact | Mitigation |
|---|---|---|---|
| Near-duplicate O(n²) scaling (89 files now, more later) | MEDIUM | HIGH | Reuse stored chunk vectors; per-file centroid compares only; batch in workers; configurable top-n |
| Graph consistency when files change | MEDIUM | MEDIUM | Reuse `GraphStore.remove_file` cascade + `_ai_sync_path`; extend the same pattern to file relationships |
| Stale `indexed_files` rows (deleted files) | **HIGH** | **HIGH** | Pre-Batch-5 fix: reconcile `indexed_files` on delete (extend `_incremental_reindex`) |
| Stale classifications/tags after edits | HIGH | MEDIUM | Recompute on modified-file detection (mtime/hash change) |
| Collection sync (file deleted/moved) | MEDIUM | MEDIUM | Collection engine validates members against `indexed_files`/disk; re-check on open |
| Model hallucination in suggestions/tags | HIGH | MEDIUM | Evidence-grounded prompts; confidence thresholds; "recommendation only" UX; user accept/dismiss |
| Excessive AI workload (classification/tagging of all files) | HIGH | HIGH | Batch queue + AIResourceManager slots + cancel; incremental (analyze only files without analysis) |
| Database growth (suggestions/collections/searches) | LOW | LOW | Small tables; prune dismissed suggestions |
| UI complexity (10 features) | MEDIUM | MEDIUM | Pure-presentation dialogs; Tools menu + docks; no main-window redesign |
| Dashboard performance on empty AI index | MEDIUM | LOW | Show "not indexed yet" states; derive from `indexed_files` not just evidence |
| Empty-content duplicate policy (13 empty files) | MEDIUM | LOW | Decide: exclude empty files from duplicate groups or group them explicitly |

---

## 31. FINAL BATCH-5 READINESS REPORT

### A. CURRENT SYSTEM SUMMARY
1. A working PySide6 file explorer with Batch-1 indexing (89 files, all SHA-256 checksummed), Batch-2 AI analysis (3 analyzed files), Batch-3 multimodal semantic indexing (pipeline complete, index currently empty), and Batch-4 conversations/graph/agent (all built, storage empty).
2. Semantic retrieval is a single unified API (`RetrievalEngine`) over FAISS (nomic-embed-text 768-d) + SQLite evidence with restart-safe hydration and integrity enforcement.
3. RAG answers every question with grounded evidence + persisted citations; chat (file/folder/workspace) and multi-document reasoning run over the same pipeline.
4. The knowledge graph stores ENTITY→ENTITY relationships with confidence and evidence provenance; files are reachable through entities but are not nodes.
5. An 8-tool, bounded, read-only agent performs research over search/evidence/graph; no agent persistence and no write tools.
6. All heavy work runs off the GUI thread (QThreadPool) with bounded AI concurrency (AIResourceManager) — appropriate for the 6.9 GiB host.
7. The AI index and all Batch-4 derived tables are **empty at runtime** (evidence 0, vector_map 0, graph 0, search_history 0); everything seeds when the user runs **Index for AI**.
8. The test suite is green: **261/261 tests pass** (5m46s), including 49 Batch-4 tests.
9. `search_history` is written on every UI search; `record_search`/`get_recent_searches` exist but have no UI consumer yet.
10. Known gaps: deleted files stay in `indexed_files`; `embeddings`/FTS5 tables are dead; `tasks` grows unboundedly; duplicate SHA-256 is computed in 5 places.

### B. BATCH 4 COMPLETION STATUS
| Feature | Status |
|---|---|
| B4-01 Persistent Conversations | **COMPLETE** (storage layer RUNTIME VERIFIED; UI flow covered by tests) |
| B4-02 Folder Chat | **COMPLETE** (STATICALLY VERIFIED + tests) |
| B4-03 Workspace Chat | **COMPLETE** (STATICALLY VERIFIED + tests) |
| B4-04 Multi-Document Reasoning | **COMPLETE** (STATICALLY VERIFIED + tests) |
| B4-05 Knowledge Graph | **COMPLETE** as entity graph; **FILE→FILE relationships NOT implemented** |
| B4-06 Agentic Workflows | **COMPLETE** (read-only; no persistence, by design) |

### C. BATCH-5 READINESS
**Overall Readiness: PARTIALLY READY**

B5-04 is effectively ready (data + primitive exist). B5-01/02/05/06/08/09/10 are partially ready (solid building blocks, missing engines/UI). B5-03 and B5-07 require genuinely new subsystems.

### D. BLOCKERS
1. **Stale `indexed_files` rows on delete** (TD-4) — will corrupt B5-04/05/10 counts. (HIGH)
2. **No FILE→FILE relationship capability** — B5-07 requires either file nodes in the graph or a new `file_relationships` table. Not a blocker for the other 9 features.
3. **AI index empty** — not a code blocker (user action), but Batch-5 QA must either seed a test workspace or accept empty-state verification.

### E. PRE-BATCH-5 FIXES
**MANDATORY**
- Reconcile `indexed_files` on file deletion (extend `_incremental_reindex` to remove stale rows; keep AI-sync parity).
- Add index on `indexed_files.checksum` (trivial, enables B5-04).
- Consolidate SHA-256 computation into one identity helper (reduces drift across 5 sites).

**RECOMMENDED**
- Decide empty-file duplicate policy (13 existing empty hashes) before B5-04.
- Make Batch-4 settings mirror into the DB `settings` table (consistency for the Batch-5 settings tab).
- Add a `SearchHistory` read consumer (recent searches) or explicitly extend it for B5-09.
- Exclude `embeddings`/FTS5 from any new schema work (dead tables).

**OPTIONAL**
- Prune `tasks` (TTL); fix `FileExplorer` per-context-menu Database open; wire the disabled plugin context-menu hook.

### F. BATCH-5 IMPLEMENTATION STARTING POINT
Start in the **engines layer**, not the UI: build `DuplicateEngine` (exact via `indexed_files.checksum`, near via `RetrievalEngine.retrieve_similar`) and a `SavedSearchManager` first — they are small, depend only on existing stable APIs (`SQLiteIndexer`, `RetrievalEngine`, `EngineDBStore`), and everything else (collections, suggestions, relationships, dashboard) consumes their outputs. Follow the Batch-4 pattern exactly: `database/migrations.py` migration 8 → models → store/manager in new packages → engine → TaskManager worker service → pure-presentation dialog → Tools-menu entry → tests.

### G. RECOMMENDED IMPLEMENTATION ORDER
1. **B5-04** Exact Duplicates (data ready; unlocks B5-05/06/07)
2. **B5-05** Near-Duplicates (retrieve_similar aggregation; unlocks B5-06/07)
3. **B5-06** Related Files (UI + API over retrieve_similar/graph)
4. **B5-07** File Relationships (consumes 1–3 + graph evidence linking)
5. **B5-01** Classification → **B5-02** Auto-Tagging (extend AI pipeline; batch)
6. **B5-09** Saved Searches (small; enables B5-03 smart criteria)
7. **B5-03** Smart Collections (criteria from 1–6)
8. **B5-08** Organization Suggestions (composes 1–7)
9. **B5-10** Knowledge Dashboard (composes everything)

### H. FINAL VERIFICATION
- **Inspected the source code?** YES — every module in engines, extractors, ai, services, database, conversation, graph, agent, ui, widgets, text_extraction, speech, vision, video.
- **Inspected the database?** YES — live `config/intellivault.db`, all 24 tables, row counts, samples, schema v7.
- **Inspected the UI?** YES — MainWindow, menus, explorer context menu, all 9 dialogs, settings, chat/graph/agent views.
- **Inspected tests?** YES — all 19 test files reviewed; categorized.
- **Ran tests?** YES — **261 passed, 0 failed, 0 skipped, 0 errors, 346.88s**.
- **Ran the application?** YES — offscreen boot + container + all Batch-4 engines constructed (RUNTIME VERIFIED).
- **Runtime verified:** DB state, engine construction, integrity check, graph stats, checksum population, duplicate hash data, test suite, app boot.
- **Statically inspected only (NOT runtime-verified in this audit):** end-to-end semantic search/chat/graph/agent with live indexed data (empty AI index prevents this; verified end-to-end in the earlier Batch-3/4 smoke tests), full GUI restart loop, file-watcher-driven flows.
