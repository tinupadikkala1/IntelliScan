# IntelliVault Current-System Audit

*Audit date: 2026-08-11 · Prepared from `ask_before_batch3.md` (audit-only brief) · Source of truth: the current codebase (not the docs). No files modified, none created beyond this report.*

---

## 1. Executive Summary

IntelliVault is an offline, PySide6 desktop "Smart File Intelligence System." The **Foundation + Batch 1 (file explorer + scan/index) and Batch 2 (AI document analysis) are fully implemented and stable**. Batch 3 (semantic search / RAG) is **partially implemented**: all the engines exist and are wired into two user-facing features — **Semantic Search** and **Ask AI about this File** — and a folder-indexing pipeline. The `extractors/`, `speech/`, `video/`, `vision/` multimodal layer is implemented and tested.

**Four critical findings a Batch 3 planner must know:**

1. **Evidence persistence is not wired.** `EngineDBStore` (`engines/db_store.py`) is only exercised by tests. The FAISS index is saved to disk (`cache/faiss_index.bin` + `.ids`), but the `chunk_id → text` evidence map is **in-memory only** and never reloaded on startup. The live DB's `evidence`/`vector_map`/`search_history` tables have **0 rows**. Consequence: after an app restart, FAISS loads but evidence lookup fails → semantic search returns nothing until a full re-index.
2. **Ask AI on documents ignores embedded images.** `RAGEngine.ask_file_direct` extracts only text frames for PPTX/PDF/DOCX. Text inside embedded images/diagrams is never OCR'd — the exact failure behind "The available documents do not contain this information."
3. **Hardware is severely constrained.** Intel i3-N305 (8 threads), 6.9 GiB RAM, **no GPU** (torch 2.7.0+cpu), and **only ~4.8 GiB free disk (98% full)**. Ollama, Whisper, CLIP, and FAISS all run on CPU in-process; a 3.7 MB FAISS index already exists in `cache/`.
4. **Ollama server was not running at audit time.** Installed models (from `~/.ollama/models/manifests`): `moondream:latest`, `nomic-embed-text:latest`, `qwen3:latest`, `qwen-local:latest`. Ollama version not determinable (server down).

---

## 2. Project Structure

```
IntelliScan/
├── main.py                  # Entry point: Container → logging → QApplication → MainWindow
├── app/                     # DI container + signal bus
│   ├── container.py         # Lazy service locator (db, tasks, engines…)
│   └── signal_bus.py        # Central Qt Signal hub (path_changed, task_progress, …)
├── core/                    # config.py (JSON settings), logging_setup.py, plugin_registry.py
├── ui/                      # main_window.py, menu_bar, toolbar, status_bar, dock_manager,
│   │                        # theme_engine, settings_dialog, indexed_files_{widget,model}.py
│   └── dialogs/             # ai_analysis_dialog, ask_ai_dialog, semantic_search_dialog, b1_progress_dialog
├── widgets/                 # folder_tree, favorites, drives, breadcrumb, file_explorer, preview_panel
├── services/                # thread_manager, task_manager, file_watcher, cache_manager,
│                            # folder_scanner, metadata_extractor, text_extractor, sqlite_indexer
├── database/                # engine.py, models.py, repository.py, migrations.py (FTS5 + embeddings)
├── text_extraction/         # Per-format extractors: txt, md, pdf, docx, pptx, xlsx, csv, json, xml
├── ai/                      # Batch 2: ollama_client, prompt_builder, json_parser, ai_service,
│                            # analysis_manager, cache_manager (AIAnalysis table)
├── engines/                 # Batch 3 core: content_engine, evidence_engine, embedding_engine,
│                            # vector_engine (FAISS), retrieval_engine, rag_engine, ai_indexer,
│                            # db_store (UNWIRED), clip_engine, config.py
├── extractors/              # Multimodal: base, factory, document, image, audio, video
├── speech/                  # speech_engine.py (Whisper)
├── video/                   # video_engine.py, keyframe_engine.py
├── vision/                  # ocr_engine.py, vision_engine.py, content_merger.py
├── plugins/                 # loader.py + example_plugin.py (registry extension point)
├── tests/                   # 17 suites, 180 tests (all passing)
├── config/                  # settings.json + intellivault.db (89 indexed_files rows)
├── cache/                   # faiss_index.bin (3.7 MB) + .ids + thumbnail cache
├── resources/themes/        # dark.qss, light.qss
└── graphify-out/            # Existing dependency-graph report (stale: built from commit 34a754d1)
```

**Dependency direction:** `ui/widgets → services/database → engines → extractors/speech/video/vision → text_extraction → ai`. The `Container` is the hub: everything is lazily resolved through it. `plugins/` is a hook-based extension point but currently holds only an example plugin.

### Purpose of each major directory

| Directory | Purpose |
|---|---|
| `app/` | Bootstrap, dependency-injection container, central signal bus |
| `core/` | Config persistence, logging, plugin registry contract |
| `ui/` | Main window, chrome (menu/toolbar/status/docks), settings, indexed-files panel, dialogs |
| `widgets/` | Reusable UI components: navigation widgets, explorer, preview panel |
| `services/` | Background orchestration: threads, tasks, watcher, cache, scanner, extractors, SQLite indexer |
| `database/` | SQLAlchemy engine, ORM models, repository CRUD, versioned migrations |
| `text_extraction/` | Per-file-format text extractors (foundation layer) |
| `ai/` | Batch 2 structured document analysis (Ollama client, prompts, JSON parsing, caching) |
| `engines/` | Batch 3 AI core: content, evidence, embedding, vector (FAISS), retrieval, RAG, folder indexer, CLIP |
| `extractors/` | Multimodal extractors: document, image, audio, video (unified ContentBlock output) |
| `speech/`, `video/`, `vision/` | Whisper transcription, video/keyframe processing, OCR + vision captioning |
| `plugins/` | Plugin discovery/loader; example plugin |
| `tests/` | 17 pytest suites (180 tests) |

---

## 3. Technology Stack

**Core:** Python 3.12.7 · PySide6 6.11.1 · SQLAlchemy 2.0.51 · SQLite (Python stdlib `sqlite3`; exact lib version not captured) · Ubuntu 24.10 x86_64.

### AI (verified installed in venv, not from requirements.txt)

| Component | Version | Notes |
|---|---|---|
| Ollama | server down at audit; version not determinable | Models installed: `moondream:latest`, `nomic-embed-text:latest`, `qwen3:latest`, `qwen-local:latest` |
| LLM (configured) | `qwen-local:latest` | `engines/rag_engine.py` `RAG_MODEL`; also `ai/config.py` `MODEL_NAME` |
| Embedding model | `nomic-embed-text` | 768 dims, `engines/config.py` |
| Vision | `moondream:latest` | hardcoded in `extractors/image_extractor.py`, `extractors/video_extractor.py`, `rag_engine._ask_image_direct`; **but `vision/vision_engine.py` defaults to `qwen-local:latest` (text-only) — a bug** |
| Speech | openai-whisper 20250625 | `base` model, CPU (`fp16=False`) |

### Retrieval

- faiss-cpu **1.14.3** · numpy **2.4.4**
- FAISS **`IndexFlatIP`** (inner product on L2-normalized vectors = cosine similarity)
- Index persisted to `cache/faiss_index.bin` + pickled `.ids` mapping

### Document processing (all present)

PyMuPDF (fitz) **1.28.0** · python-docx **1.2.0** · python-pptx **1.0.2** · openpyxl **3.1.5** · CSV (stdlib + openpyxl fallback) · JSON/XML (stdlib ElementTree).

### Multimodal dependencies (verified)

| Package | Status |
|---|---|
| Tesseract / pytesseract | ✅ installed (Tesseract 5.3.4, pytesseract 0.3.13) |
| OpenCV | ✅ cv2 5.0.0 |
| Pillow | ✅ 12.2.0 |
| openai-whisper | ✅ 20250625 |
| FFmpeg | ✅ 7.0.2 (`/usr/bin/ffmpeg`) |
| torch | ✅ 2.7.0+cpu (CPU-only) |
| CLIP | ✅ importable (ViT-B/32, lazy-loaded, CPU) |
| mutagen | ✅ 1.48.1 (audio tags in preview) |
| pandas | ❌ NOT installed |
| PyPDF2 | ❌ NOT installed (PDF handled by PyMuPDF instead) |
| faster-whisper / transformers / sentence-transformers | ❌ not present |

> **Discrepancy:** none of these AI dependencies appear in `requirements.txt`, which lists only `pyside6, sqlalchemy, watchdog, mutagen, pytest, pytest-qt`.

---

## 4. Current User-Facing Features

| Feature | UI Entry Point | Current Status | Relevant Code | Notes |
|---|---|---|---|---|
| **Foundation** | | | | |
| Browse folders | FolderTree / Drives / Favorites / Breadcrumb | ✅ Works | `widgets/folder_tree.py` etc. → `ui/main_window._navigate_to` | navigation history (back/forward/up) |
| List & grid views, sorting, multi-select | Explorer | ✅ Works | `widgets/file_explorer.py` | QFileSystemModel; custom `GridDelegate` |
| Open / rename / copy / move / delete / properties | Explorer context menu | ✅ Works | `file_explorer._on_context_menu` | no re-index on these ops |
| Drag & drop (internal move + external import) | Explorer | ✅ Works | `file_explorer.handle_drop` | |
| Preview: image/text/PDF/audio/video/properties | PreviewPanel | ✅ Works | `widgets/preview_panel.py` | video thumbnail via ffmpeg |
| Filename search | Toolbar search box | ✅ Works | `toolbar.search_box` → `set_name_filter` | |
| Settings dialog + theme (dark/light) | Tools → Settings | ✅ Works | `ui/settings_dialog.py`, `theme_engine.py` | |
| Favorites / Recents persistence | Sidebar / open file | ✅ Works | `database/repository.py` | |
| Indexed Files panel | Bottom of central layout | ✅ Works | `ui/indexed_files_widget.py` | shows SQLite index for current folder |
| **Batch 1** | | | | |
| Scan Folder (+ progress dialog, cancel) | Toolbar "Scan Folder" | ✅ Works | `main_window._on_scan_requested` → `SQLiteIndexer` | writes `indexed_files` |
| Incremental re-index on filesystem change | Automatic (watchdog) | ✅ Works | `main_window._incremental_reindex` | debounced 300 ms |
| **Batch 2** | | | | |
| AI Analyze File (low/med/high) | Context menu → AI → Analyze File | ✅ Works | `main_window._on_ai_analyze_requested` | cached in `ai_analysis` by SHA-256 |
| View / Regenerate Analysis | Context menu → AI | ✅ Works | `main_window._on_ai_view_requested` | |
| **Batch 3 (implemented so far)** | | | | |
| Index for AI | Toolbar "Index for AI" | ✅ Works (session-only persistence) | `main_window._on_ai_index_requested` → `AIFolderIndexer` | evidence not persisted; see §5/§9 |
| Semantic Search | Toolbar AI box / context menu → AI → Semantic Search | ✅ Works (while indexed in-session) | `main_window._perform_semantic_search` → `RetrievalEngine.smart_retrieve` | LLM re-rank when no modality detected |
| Ask AI about this File | Context menu → AI → Ask AI | ✅ Works for text/images/audio/video | `main_window._perform_ask_ai` → `RAGEngine.ask_file_direct` | embedded images in docs not extracted |

Internal engines (ContentEngine, EvidenceEngine, EmbeddingEngine, VectorEngine, RetrievalEngine, RAGEngine, EngineDBStore, CLIPEngine, extractors) are **not** counted as user-facing features above — they only surface through the four Batch 3 features listed.

---

## 5. Current Batch 3 Implementation

### ContentEngine — `engines/content_engine.py`

- **Classes:** `ContentBlock` (dataclass), `UniversalContentEngine` (alias `ContentEngine` in `engines/__init__.py`).
- **Input:** file path. **Output:** `list[ContentBlock]` with `text, source_type, source_index, source_label, file_path, modality, timestamp_start/end, confidence, metadata` (incl. `file_hash`).
- **Handlers:** PDF (fitz, per page), PPTX (per slide), XLSX (per sheet), CSV (single), DOCX (~500-char sections), text/code files (chunked ~500 chars), image (delegates to `ImageExtractor`), audio (→ `AudioExtractor`), video (→ `VideoExtractor`). Computes SHA-256 on every call.
- **Dependencies:** `text_extraction.ExtractorFactory`, optional fitz/docx/pptx/openpyxl; runtime `extractors.*`.
- **Database interaction:** none. **UI interaction:** none.
- **Current limitations:** PPTX/PDF/DOCX embedded images are ignored; whole-file read for hashing (slow on large media).
- **Important assumptions:** extraction is best-effort — every handler swallows errors and returns `[]` rather than raising.
- **Safe to extend:** yes — it is the intended normalization point.

### EvidenceEngine — `engines/evidence_engine.py`

- **Classes:** `EvidenceChunk` (dataclass: `chunk_id` uuid4-hex, `text, file_path, file_hash, source_type, source_index, source_label, char_start, char_end`), `EvidenceEngine`.
- **Input:** file path → calls `ContentEngine.extract` → splits each block into overlapping chunks (**CHUNK_SIZE=400, CHUNK_OVERLAP=50** from `engines/config.py`).
- **Database/UI:** none.
- **Limitation:** re-computes the file hash if not in block metadata (double-hash with ContentEngine).
- **Safe to extend:** yes.

### EmbeddingEngine — `engines/embedding_engine.py`

- **Model:** `nomic-embed-text`, base URL `http://localhost:11434`, dim 768 (auto-adjusts to model output).
- **API:** `embed_text` (single POST `/api/embed`), `embed_batch` (batch POST with per-item fallback to sequential on failure), `is_available` (GET `/api/tags`).
- **No prefixes applied here** — the `search_document:` / `search_query:` prefixes are applied in `RetrievalEngine`/`AIFolderIndexer` instead.
- **Safe to extend:** yes.

### VectorEngine — `engines/vector_engine.py`

- FAISS `IndexFlatIP`, L2-normalized vectors (cosine), `RLock`-protected (`@lock_required` decorator — thread safety is already handled).
- **API:** `add`, `add_batch`, `search(query_vector, top_k, threshold=0.3)` → `list[SearchResult(chunk_id, score, rank)]`, `remove_by_chunk_ids` (rebuild), `save` (faiss.write_index + pickle ids), `_load` on init, `clear`.
- **Limitations:** index dimension fixed at construction (768) — CLIP's 512-dim vectors are **padded to 768** in `ai_indexer._index_image`; deletion rebuilds the whole index.
- **Safe to extend:** yes.

### RetrievalEngine — `engines/retrieval_engine.py`

- **Single API:** `retrieve(query, scope, top_k, threshold, file_filter)`; scopes `SELECTED_FILE / FOLDER / WORKSPACE / SELECTED_FILES`.
- `index_chunks(chunks)`: embeds with `search_document:` prefix, adds to FAISS, populates **in-memory** `self._evidence[chunk_id]`.
- `smart_retrieve`: `_detect_modality` (keyword lists) → over-fetch 6× top_k → `_filter_by_modality` (by extension) → `_deduplicate_by_file` (one result per file, best score).
- `retrieve_similar(file_path)`: average-embedding of the file's chunks (document-level similarity, exists but **no UI entry point**).
- **Database interaction:** none (evidence in-memory).
- **Limitation:** `self._evidence` never hydrated from `evidence` table at startup → post-restart search returns nothing.
- **Limitation:** dedup discards multi-chunk evidence from the same file.
- **Safe to extend:** yes.

### RAGEngine — `engines/rag_engine.py`

- **LLM:** `qwen-local:latest`, temperature 0.4, timeout 300 s, `RAG_MAX_CONTEXT = 3000` chars.
- `ask(question, scope, file_filter, top_k=5)`: retrieval → `_build_context` (bounded 3000 chars, source-ref `[label | filename]` per chunk) → `_build_rag_prompt` (strict grounded prompt; "say so clearly" fallback — this produces the *"The available documents do not contain this information."* message) → `_generate` (non-streaming POST `/api/generate`) → `RAGResponse(answer, citations)`.
- `ask_file_direct` (**the path used by the Ask AI dialog**): for docs → `extract_full_text` → `_build_direct_prompt` (permissive, "reason and infer" prompt); images → OCR first, else moondream via `_ask_image_direct`; audio → `SpeechEngine` transcription; video → `VideoEngine.extract_audio_track` + transcription. Returns a single whole-file citation.
- `rerank_results(query, results)`: LLM-as-judge re-ranker used by Semantic Search when no modality detected; falls back to top-5.
- **UI:** none (dialog drives via signals).
- **Safe to extend with care** — prompt engineering is the accuracy lever.

### AIFolderIndexer — `engines/ai_indexer.py`

- **Index Folder pipeline:** `_discover_files` (skips archives/binaries/caches) → per file: documents → `EvidenceEngine.build_evidence` → `retrieval.index_chunks`; images → OCR/caption text chunks + CLIP visual vector (padded to 768, stored with synthetic evidence `[Image: name]`); audio/video → transcription evidence.
- **Progress:** `IndexingProgress` callback; cancellation via `threading.Event`.
- **Database interaction:** none (no `EngineDBStore` calls, no vector_map writes).
- **Limitation:** duplicate indexing check scans `retrieval._evidence.values()` per file (O(n) per file).
- **Safe to extend:** yes.

### EngineDBStore — `engines/db_store.py` — **UNWIRED**

- Full CRUD for `Evidence` / `VectorMap` / `SearchHistory` exists and is unit-tested (`tests/test_batch3.py`), but **no runtime code imports or calls it**. Search history is also never recorded at runtime.

### CLIPEngine — `engines/clip_engine.py`

- Lazy global model load (`ViT-B/32`, device "cpu"), 512-dim `embed_image`/`embed_text`, `is_available` checks `import clip`. Only used inside `AIFolderIndexer._index_image`.
- **Limitation:** its vectors are padded into the 768-dim FAISS space (mathematically lossy).
- **Safe to extend:** yes.

---

## 6. Content and Evidence Model

Both structures **exist** and are the real pipeline model:

- **`ContentBlock`** (`engines/content_engine.py`): `text, source_type ("page"|"slide"|"sheet"|"section"|"file"|"ocr"|"caption"|"transcript"|"keyframe"|"filename"), source_index, source_label ("Slide 3", "0:30 - 1:00"…), file_path, modality ("document"|"image"|"audio"|"video"), timestamp_start/end, confidence, metadata{file_hash}`.
- **`EvidenceChunk`** (`engines/evidence_engine.py`): `chunk_id (uuid4 hex), text, file_path, file_hash, source_type, source_index, source_label, char_start, char_end`.

**Origin tracking:** provenance travels block → chunk → `RetrievalResult` (all fields surfaced) → `Citation(source_label, file_path, text_snippet, score)`. Page/slide/sheet numbers and audio/video timestamps **are** carried through to the RAG prompt context as `[Slide 3 | deck.pptx]` labels. There is **no image ID / frame image binary** stored in the model — video keyframes are captioned to text only.

---

## 7. Embedding Architecture

| Aspect | Value |
|---|---|
| Model / dims | `nomic-embed-text`, 768 (auto-adjusted on mismatch) |
| Prefixes | `search_document:` at index time (`retrieval.index_chunks`, `ai_indexer`), `search_query:` at query time (`retrieval.retrieve`) |
| Normalization | yes — `faiss.normalize_L2` before add/search (IndexFlatIP ⇒ cosine) |
| Chunk size / overlap | 400 / 50 chars (`engines/config.py`) |
| Batching | `embed_batch` sends array to `/api/embed`; falls back to per-item on any failure |
| Storage | FAISS in-memory + `cache/faiss_index.bin` + pickled `.ids`; `embeddings` SQLite table (migration 3) exists but is **not used** by the Batch 3 pipeline |
| Vector→evidence map | in-memory dict `chunk_id → EvidenceChunk` only |
| Persistence | FAISS ✅ (save on index complete), evidence ❌ (lost on restart) |
| Incremental / delete | `remove_file` (rebuild-based), `remove_by_chunk_ids`; not invoked by watcher/UI |
| Duplicates | chunk_ids are uuid4 — re-indexing creates new vectors without dedup against FAISS |
| Error recovery | `_load` failure → fresh empty index + empty id map (logged) |

**Complete current flow:**

```
User/File → UniversalContentEngine (ContentBlocks)
         → EvidenceEngine (EvidenceChunks, 400/50 chars)
         → EmbeddingEngine (nomic-embed-text, "search_document:" prefix, batch /api/embed)
         → VectorEngine.add (L2-normalized, IndexFlatIP, 768-dim)
         → save → cache/faiss_index.bin + faiss_index.bin.ids
```

---

## 8. Retrieval Architecture

1. Query arrives from `SemanticSearchDialog` → `main_window._perform_semantic_search` → `RetrievalEngine.smart_retrieve(query, top_k=10)` (worker thread).
2. Query embedded (with `search_query:` prefix).
3. FAISS `search(top_k=60)` (6× over-fetch), `SIMILARITY_THRESHOLD = 0.3`.
4. `chunk_id` → in-memory `_evidence` dict → `RetrievalResult` (full provenance + score).
5. Optional modality filter (extension-based), then dedup by file (best score).
6. If no modality detected → `RAGEngine.rerank_results` (LLM judge) filters/orders.
7. UI shows `[score] source_label`, 120-char snippet, file path; double-click opens file.

**Answers to the spec questions:**

1. Query received: `SemanticSearchDialog.search_requested` signal → MainWindow worker.
2. Query embedded: `EmbeddingEngine.embed_text` with `search_query:` prefix.
3. FAISS searched: `VectorEngine.search` (IndexFlatIP, threshold 0.3, over-fetch).
4. Vector→evidence: in-memory `self._evidence` dict keyed by `chunk_id`.
5. Ranking: FAISS cosine score descending; optional LLM re-rank; then per-file dedup.
6. Returned: `RetrievalResponse` with `RetrievalResult(chunk_id, text, score, rank, file_path, file_hash, source_type, source_index, source_label, char_start, char_end)`.
7. Scores/confidence: ✅ `score` (cosine); no calibrated confidence.
8. Page numbers: ✅ `source_label` ("Page 3", "Slide 5") + `source_index`.
9. Source snippets: ✅ `text` shown truncated (120 chars).
10. Multiple files: ✅ workspace scope + modality filter + dedup.
11. Multiple modalities: ✅ (extension filter + CLIP-padded vectors), though intent detection is keyword-based and brittle.

**Actual retrieval data flow:**

```
Query → EmbeddingEngine (search_query:) → VectorEngine.search (FAISS, cosine)
     → _evidence[chunk_id] → scope/file filter → modality filter → dedup by file
     → [optional] RAGEngine.rerank_results (LLM judge)
     → SemanticSearchDialog results list
```

---

## 9. RAG / Ask AI Architecture

- **LLM:** `qwen-local:latest`, temp 0.4, non-streaming, timeout 300 s.
- **Prompt construction:** `_build_direct_prompt` (full-file, permissive reasoning) for documents; `_build_audio_prompt` / `_build_video_prompt` (timestamped transcripts); `_build_rag_prompt` (retrieval-grounded, strict) for `ask()`; `_ask_image_direct` (OCR/moondream context).
- **Retrieved context format:** `[source_label | filename]:\n<text>` chunks joined by `\n\n---\n\n`; truncated to `RAG_MAX_CONTEXT = 3000` chars.
- **Number of retrieved chunks:** `top_k=5` default for `ask()`; **zero** for `ask_file_direct` (full file instead).
- **Context limits:** 3000 chars (`RAG_MAX_CONTEXT`); document full-text limited only by Ollama context window.
- **Citation handling:** `Citation(source_label, file_path, text_snippet, score)`; direct-ask returns one whole-file citation.
- **Answer generation:** non-streaming POST `/api/generate`, temperature 0.4.
- **Error handling:** empty extraction → helpful message; Ollama down → "Failed to generate… check that Ollama is running"; `grounded=False` still renders the message.
- **Conversation state:** none — stateless single Q&A.
- **UI integration:** `AskAIDialog` (pure view) ← `main_window._perform_ask_ai` ← context menu.

### "Ask AI about this File" — complete trace (UI click → final answer)

1. Context menu `Ask AI about this File` (`file_explorer.py`) → `ai_ask_requested` signal → `main_window._on_ask_ai_requested` → opens `AskAIDialog` (pure view, signals only).
2. `question_submitted(question, file_path)` → `main_window._perform_ask_ai` → `tasks.submit(_do_ask)` worker thread.
3. `RAGEngine.ask_file_direct(question, file_path)` — **no vector search at all** ("Tier 1"):
   - image extension → OCR (`pytesseract`); if >50 chars use OCR text, else base64 → `moondream:latest` `/api/generate` → combined context prompt.
   - audio extension → `SpeechEngine.transcribe` (Whisper) → timestamped transcript prompt.
   - video extension → `VideoEngine.extract_audio_track` (ffmpeg) → transcribe → transcript prompt.
   - else (docs/code) → `UniversalContentEngine.extract_full_text` → direct prompt.
4. `_generate` → answer + one whole-file `Citation`.
5. `dialog.set_answer(answer, citations)`.

---

## 10. Database Schema (live `config/intellivault.db`)

Tables present (21 + `sqlite_sequence`): `ai_analysis, embeddings, evidence, favorites, file_content_fts*` (FTS5 shadow tables), `files, folders, indexed_files, logs, plugins, recent, schema_version, search_history, settings, tasks, vector_map`.

### `indexed_files` — Batch-1 workhorse (**89 rows**)

`id INTEGER PK · filename TEXT · absolute_path TEXT UNIQUE · size INTEGER · mime_type TEXT · extension TEXT · created_date DATETIME · modified_date DATETIME · checksum TEXT · extracted_text TEXT · metadata_json TEXT · scan_timestamp DATETIME · indexing_status TEXT · processing_attempts INTEGER · error_message TEXT · last_updated DATETIME`

### `evidence` — Batch 3 chunks (**0 rows**)

`id INTEGER PK · chunk_id VARCHAR(32) UNIQUE · file_path VARCHAR(64) index · file_hash VARCHAR(64) index · text TEXT · source_type VARCHAR · source_index INTEGER · source_label VARCHAR · char_start INTEGER · char_end INTEGER · indexed_at DATETIME`

### `vector_map` — chunk→vector metadata (**0 rows**)

`id INTEGER PK · chunk_id VARCHAR(32) UNIQUE · file_path VARCHAR index · file_hash VARCHAR(64) index · embedding_model VARCHAR · indexed_at DATETIME`

### `search_history` (**0 rows**)

`id INTEGER PK · query TEXT · scope VARCHAR · results_count INTEGER · elapsed_ms INTEGER · searched_at DATETIME`

### `ai_analysis` — Batch 2 cache

`id INTEGER PK · file_hash VARCHAR(64) UNIQUE · summary TEXT · keywords TEXT (JSON) · tags TEXT (JSON) · category VARCHAR · language VARCHAR · ai_generated BOOLEAN · generated_time DATETIME · prompt_version VARCHAR · model_name VARCHAR`

### `embeddings` — migration 3 (**unused by runtime**)

`id INTEGER PK · file_id INTEGER FK→files.id ON DELETE CASCADE · model TEXT · vector BLOB · created TIMESTAMP`

### `file_content_fts` — FTS5 virtual table (**unused by runtime**)

Virtual table over `files` with insert/update/delete triggers (migration 2).

### Foundation tables

- `files`: `id PK, path UNIQUE index, name, parent index, size, mime, modified, checksum`
- `folders`: `id PK, path UNIQUE index, name, parent index`
- `settings`: `key PK, value TEXT`
- `favorites`: `id PK, path UNIQUE index, name, added`
- `recent`: `id PK, path index, name, opened`
- `tasks`: `id PK, task_id UNIQUE index, type, status, progress, total, created, finished`
- `plugins`: `id PK, name UNIQUE index, version, enabled BOOLEAN`
- `logs`: `id PK, timestamp, level, logger, message`

### Schema management

- **Migration mechanism:** `database/migrations.py` — versioned dict `MIGRATIONS = {1..5}` with `schema_version` table; `init_database()` runs `Base.metadata.create_all(engine)` then `run_migrations(engine)`.
- **Schema versioning:** `schema_version(version PK, applied)`; `get_current_version` / `set_version` helpers.
- **Database initialization:** `Database(path)` in `database/engine.py` → `init_database(path)`; SQLite URL, `check_same_thread=False`, `pool_pre_ping=True`.
- **Transaction handling:** every repository method / engine store method opens `with session_factory() as session: … commit()` — no cross-method transactions.
- **Indexes:** UNIQUE on `indexed_files.absolute_path`, `evidence.chunk_id`, `vector_map.chunk_id`, `ai_analysis.file_hash`; indexes on `file_path`, `file_hash`, `parent`, `task_id`, `name`.

---

## 11. UI Architecture

| Component | File | Class | Responsibility | Signals → backend |
|---|---|---|---|---|
| Main Window | `ui/main_window.py` | `MainWindow` | Assembles all; owns ALL AI orchestration (`_on_ai_analyze_requested`, `_perform_semantic_search`, `_perform_ask_ai`, `_on_ai_index_requested`) | routes `container.tasks.submit` workers; QProgressDialog/QMessageBox |
| Explorer | `widgets/file_explorer.py` | `FileExplorer` | List/grid, DnD, context menu incl. AI submenu | `ai_analyze_requested`, `ask_ai_requested`, `semantic_search_requested`… |
| Preview | `widgets/preview_panel.py` | `PreviewPanel` | Per-type preview + "Extracted Text"/metadata from SQLite | `container.tasks` (thumbnail) |
| Indexed Files | `ui/indexed_files_{widget,model}.py` | `IndexedFilesWidget/Model` | Filterable list of `indexed_files` for current folder | `bus.file_selected` |
| Dialogs | `ui/dialogs/*` | `AskAIDialog`, `SemanticSearchDialog`, `AIAnalysisDialog`, `B1ProgressDialog` | All purely presentational; signals only | `question_submitted`, `search_requested`… |
| Navigation | `widgets/` | `FolderTree`, `DrivesWidget`, `FavoritesWidget`, `Breadcrumb` | Path navigation | `folder_selected`/`path_changed` |
| Toolbar | `ui/toolbar.py` | `ToolBar` | back/forward/up/refresh, view, filename search, **Scan Folder**, **Index for AI**, **Semantic search box** | signals incl. `ai_index_requested`, `semantic_search_requested` |
| Theme | `ui/theme_engine.py` | `ThemeEngine` | dark/light QSS | `theme_changed` |
| Settings | `ui/settings_dialog.py` | `SettingsDialog` | Tabbed settings; reserved AI tabs disabled | writes config + repository |
| Sidebar | `ui/dock_manager.py` | `DockManager` | Navigation + Preview docks; hosts indexed-files widget in central layout | — |
| Menus | `ui/menu_bar.py` | `MenuBar` | File/Edit/View/Tools/Help | signals: toggle sidebar/preview/theme, refresh, settings |

**Architecture pattern:** widgets are dumb; `MainWindow` is the orchestrator; workers never touch widgets (signal-only). Note `PreviewPanel._get_metadata_from_index` / `_get_extracted_text_from_index` load **all** `IndexedFile` rows and loop (known inefficiency).

---

## 12. Context Menu Architecture

```
Right-click file
  ├─ Open / Rename / Copy to… / Move to… / Delete / Properties
  └─ AI
      ├─ Analyze File          (enabled for single files)
      ├─ View Analysis         (enabled only if ai_analysis cached for hash)
      ├─ Regenerate Analysis   (enabled only if cached)
      ├─ ─────────────────
      ├─ Semantic Search       (always enabled)
      └─ Ask AI about this File (enabled for single files)
```

Built in `FileExplorer._on_context_menu`; actions emit `file_explorer` signals → `MainWindow`.

**Existing actions:** Analyze File ✅ · Ask AI ✅ · Semantic Search ✅ · View/Regenerate Analysis ✅. (Open/Rename/Copy/Move/Delete/Properties from the base menu.)

**Safest extension point for Batch 3 additions (Image AI / Audio AI / Video AI / Similar Files / multimodal search):** add `QAction`s to the `ai_menu` and new signals on `FileExplorer` (mirroring `ask_ai_requested`), then handle them in `MainWindow` — zero changes to engine code required. (The plugin `context_menu` hook exists but is disabled: `if False and self.plugin_registry…`.)

---

## 13. Worker / Background Processing Architecture

- **`ThreadManager`** (`services/thread_manager.py`): wraps `QThreadPool`; `Worker(QRunnable)` runs `fn(progress.emit, cancel_event, *args)`; `WorkerSignals(progress, finished, error)`; worker cleaned up via `deleteLater` on GUI thread.
- **`TaskManager`** (`services/task_manager.py`): `submit(fn, type_, task_id=None, *args, on_*…)` → uuid `task_id`, `threading.Event` cancellation, persists to `tasks` table, fans `task_progress`/`task_finished` to signal bus, tracks `_active` dict.
- **Cancellation:** cooperative via `cancel_event.is_set()` — every long pipeline checks it (scanner, indexer, AI analysis, incremental reindex).
- **Errors:** caught in `Worker.run`, emitted via `error` signal, surfaced to dialogs/status bar; workers never crash the pool.
- **Progress:** `progress(current, total)` callback threaded through `TaskManager._progress` → bus + status bar + dialogs.
- **Cleanup:** finished/error handlers pop `_active`, `deleteLater` signals, `waitForDone(timeout_ms=5000)` on shutdown.
- **Concurrency:** `max_threads` from config (`performance.max_threads`, currently 6). `VectorEngine` is lock-protected, but **FAISS saves and searches can still race across threads** (lock only guards within one engine instance; concurrent index + search is not serialized across calls).
- **This architecture is adequate** for OCR/Whisper/Vision/FFmpeg/embedding — all existing heavy ops already run here.

---

## 14. File Identity and Change Detection

- **Identity:** SHA-256 content hash (`MetadataExtractor._calculate_checksum`, `ContentEngine._compute_hash`, `AICacheManager` keying) **plus** `absolute_path` as the DB/FAISS identity (`indexed_files.absolute_path` UNIQUE; evidence `file_path`; AIAnalysis keyed by `file_hash`).
- **File Created:** watchdog → debounced (300 ms) → `_incremental_reindex` compares mtime vs `indexed_files.modified_date` → indexes **only new/modified files into `indexed_files` (SQLite)**. FAISS evidence is **not** updated.
- **File Renamed:** nothing re-indexes. Old path record stays; new path creates a new record. `ai_analysis` (hash-keyed) survives; `indexed_files` and FAISS evidence do not.
- **File Moved:** same as rename (no handler).
- **File Modified:** incremental reindex refreshes `indexed_files` text/metadata; **Batch 3 FAISS evidence goes stale** (no re-embed).
- **File Deleted:** no handler removes `indexed_files` / FAISS evidence / `ai_analysis` / `evidence` rows.
- **Re-indexing:** manual "Index for AI" only; duplicate check scans in-memory evidence.
- **Stale vector/evidence removal:** `RetrievalEngine.remove_file` exists but is not invoked by watcher/UI.
- **Metadata preservation:** `indexed_files` row updated in place on modification (same path).

---

## 15. Test Suite

- **Location:** `tests/` — 17 files. Run with `venv/bin/python3 -m pytest tests/ -q`.
- **Result:**

```
Total tests:  180
Passed:       180
Failed:       0
Skipped:      0
Errors:       0
```

- **Coverage:** config, logging, database, services (threads/tasks/watcher/cache), navigation, explorer, preview (+metadata, +extracted-text variants), settings, plugin registry, main window, Batch 2 unit + integration, **Batch 3** (engines incl. EngineDBStore, VectorEngine, RetrievalEngine, RAG), multimodal (image/audio/video extractors, OCR, vision, keyframes).
- **Mocks/fixtures:** Ollama and Whisper are mocked (tests need no live server); temp SQLite DBs via fixtures; FAISS used in-memory with temp paths.
- **No existing failures** — every suite passes.

---

## 16. Performance Baseline

**No formal baseline exists** in the repo — no benchmark scripts, no recorded timings. Only observed data point: full test suite = 3:40 (220 s). A stale FAISS index (3.7 MB, `cache/faiss_index.bin`) exists from a real indexing run (Jul 20), but no timing was recorded.

**Statement: no performance baseline is determinable from the current codebase.** No destructive or long-running benchmarks were performed for this audit.

---

## 17. Hardware and Resource Constraints

| Resource | Value |
|---|---|
| CPU | Intel Core i3-N305, 8 threads (x86_64) |
| RAM | 6.9 GiB total; **3.3 GiB available** at audit time |
| GPU / VRAM | **None** (nvidia-smi absent; torch `2.7.0+cpu`) |
| Disk | `/` 225 GiB, **98% full — 4.8 GiB free** (`/dev/nvme0n1p7`) |
| OS | Ubuntu 24.10 |

**Resource-sensitive components running locally:** Ollama (qwen-local, nomic-embed-text, moondream), Whisper `base`, CLIP ViT-B/32 (CPU), FAISS, OpenCV/Tesseract, FFmpeg.

**Constraint note:** Whisper + CLIP + Ollama cannot run concurrently without heavy memory pressure on 6.9 GiB total RAM; the 98%-full disk is a hard constraint on any model or blob growth.

---

## 18. Current Media Support

| Modality | Format | Can Read? | Can Extract Content? | Can Index? | Can Search? | Can Ask AI? |
|---|---|---|---|---|---|---|
| PDF | .pdf | ✅ | ✅ per-page (fitz) | ✅ | ✅ | ✅ (text only) |
| DOCX | .docx | ✅ | ✅ sections | ✅ | ✅ | ✅ |
| PPTX | .pptx | ✅ | ✅ per-slide text | ✅ | ✅ | ✅ (embedded images ❌) |
| XLSX/XLS | .xlsx | ✅ | ✅ per-sheet | ✅ | ✅ | ✅ |
| CSV/TSV | .csv | ✅ | ✅ | ✅ | ✅ | ✅ |
| TXT/MD | .txt/.md | ✅ | ✅ chunked | ✅ | ✅ | ✅ |
| JSON/XML | .json/.xml | ✅ | ✅ | ✅ | ✅ | ✅ |
| Code files | .py/.js/.ts/.java/.cpp/.c/.h/.rs/.go/.html/.css/.yaml/.toml/.ini/.sh/.rb/.php/.sql | ✅ | ✅ chunked | ✅ | ✅ | ✅ |
| PNG/JPG/JPEG | images | ✅ | ✅ OCR+caption (moondream) | ✅ text+CLIP | ✅ | ✅ (OCR→moondream) |
| WEBP/BMP/TIFF/GIF | images | ✅ | ✅ (GIF first frame) | ✅ | ✅ | ✅ |
| MP3/WAV/M4A/FLAC/OGG/AAC/WMA/OPUS | audio | ✅ | ✅ Whisper transcript | ✅ | ✅ | ✅ |
| MP4/MKV/MOV/AVI/WEBM/M4V/FLV/WMV | video | ✅ | ✅ transcript + keyframe captions | ✅ | ✅ | ✅ |
| ZIP/TAR/GZ/7Z/RAR/EXE/DLL/DB/BIN | archives/binary | ❌ skipped | ❌ | ❌ | ❌ | ❌ |

*(Verified against `content_engine.py` and `ai_indexer.py` extension sets and `rag_engine.ask_file_direct` modality dispatch. Archives/executables/databases are excluded via `ai_indexer._SKIP_EXT`.)*

---

## 19. Existing Error Handling

| Scenario | Behavior | Logged? | Shown to user? | Retried? |
|---|---|---|---|---|
| Unsupported format | logged; `ContentEngine` returns `[]`; extractors return filename fallback block | ✅ | via status/dialog | ❌ |
| Corrupted document | logged, empty result; Ask AI shows helpful message | ✅ | ✅ | ❌ |
| Empty file | logged; text extractor skips | ✅ | — | ❌ |
| Permission errors | logged by scanner, item skipped | ✅ | ❌ (silently skipped) | ❌ |
| Missing file | logged, `[]` / None | ✅ | ✅ (Ask AI "cannot ask: invalid file") | ❌ |
| Ollama unavailable | `EmbeddingEngine`/`RAGEngine`/`OllamaClient` return None/"" with logged error | ✅ | ✅ "check that Ollama is running" | ❌ |
| Model unavailable | `is_available()` checks; warning logged | ✅ | ✅ | ❌ |
| Invalid LLM output | `JsonParser` raises → `AIService` returns `{"error": …}` → shown | ✅ | ✅ | ❌ |
| Database errors | caught, logged, `[]`/None returned | ✅ | ❌ | ❌ |
| FAISS errors | caught, logged, empty results; fresh index on load failure | ✅ | ❌ | ❌ |
| Extraction errors | caught per-handler, logged, `[]` | ✅ | ❌ | ❌ |
| Worker failures | caught in `Worker.run` → `error` signal → dialog/status | ✅ | ✅ | ❌ |

**Missing:** no stale-evidence cleanup on file delete/modify; no FAISS save triggered by search-time modifications; no retry logic anywhere.

---

## 20. Configuration

### Runtime config — `core/config.py` (JSON `config/settings.json`)

Theme, explorer view, `database.path`, `performance.max_threads` (6 currently), `cache_size_mb`. Feature flags `ai/ocr/models/embeddings/llm.enabled` exist but are **inert** (Batch 1–10 reserved).

### Engine constants — `engines/config.py`

| Constant | Value |
|---|---|
| `CHUNK_SIZE` | 400 chars |
| `CHUNK_OVERLAP` | 50 chars |
| `EMBEDDING_MODEL` | `nomic-embed-text` |
| `EMBEDDING_DIM` | 768 |
| `OLLAMA_BASE_URL` | `http://localhost:11434` |
| `TOP_K_DEFAULT` | 5 |
| `SIMILARITY_THRESHOLD` | 0.3 |

### AI constants — `ai/config.py`

`MODEL_NAME = qwen-local:latest` · `TEMPERATURE = 0.3` · `TIMEOUT = 480` · `MAX_TEXT_CHUNK = 6000` · `PROMPT_VERSION = 1.0`.

### RAG constants — `engines/rag_engine.py`

`RAG_MODEL = qwen-local:latest` · `RAG_TEMPERATURE = 0.4` · `RAG_TIMEOUT = 300` · `RAG_MAX_CONTEXT = 3000`.

### Hardcoded values Batch 3 must be aware of

- `moondream:latest` and `OLLAMA_BASE_URL` **hardcoded inside** `extractors/image_extractor.py`, `extractors/video_extractor.py`, `vision/vision_engine.py` (default), `rag_engine._ask_image_direct` — the central `OLLAMA_BASE_URL` config is ignored in these paths.
- FAISS path hardcoded in `app/container.py` (`cache/faiss_index.bin`).
- Extension sets **duplicated** across `content_engine.py`, `ai_indexer.py`, `retrieval_engine.py`, `preview_panel.py`.
- Whisper model size `"base"` repeated in `audio_extractor.py`, `speech_engine.py`, `video_extractor.py`, `rag_engine.py`.
- `performance.max_threads` default 4 in code, 6 in live settings.

---

## 21. Documentation vs Code Discrepancies

| Planned / Documented | Actually Implemented | Difference | Impact |
|---|---|---|---|
| `requirements.txt` lists 6 packages | Runtime uses faiss, numpy, requests, PyMuPDF, docx, pptx, openpyxl, pytesseract, Pillow, whisper, opencv, torch, clip | Manifest is stale | Fresh installs break; venv carries the real deps |
| `pyproject.toml` packages list | Missing `engines, extractors, speech, video, vision, text_extraction` | `pip install -e .` won't package them | Packaging/editable install incomplete |
| `analysis_results.md`: "video keyframes captioned with qwen-local (text-only)" | `video_extractor._caption_frame` uses **moondream:latest** | Already fixed in code | Doc is stale; no action |
| `analysis_results.md`: "missing nomic prefixes" | Prefixes applied in `RetrievalEngine`/indexer | Already fixed | Doc is stale |
| `system_architecture.md`: `EngineDBStore` as part of "Relational Storage" | `EngineDBStore` is **not wired** anywhere | Doc overstates | Critical finding — persistence gap |
| Blueprint "8 tables" | 12+ tables incl. `indexed_files`, `ai_analysis`, `evidence`, `vector_map`, `search_history`, FTS5, `embeddings` | Schema grew (migrations 2–5) | Compatible; migrations handle it |
| `vision_engine.py` claims "vision models" | Default model `qwen-local:latest` is **text-only** | Config bug | Image captioning silently fails unless moondream used elsewhere |
| `IntelliVault_Batch3.md` lists PaddleOCR | Not used — Tesseract used instead | Doc mismatch | Cosmetic |
| `IntelliVault_Batch3.md` lists ffmpeg-python | Not used — raw `subprocess` ffmpeg calls | Doc mismatch | Cosmetic |

---

## 22. Batch 3 Readiness Assessment

### Image

| Capability | Status | Why |
|---|---|---|
| OCR | 🟢 Ready | `vision/ocr_engine.py`, `image_extractor.py` implemented + tested; tesseract installed |
| Vision | 🟢 Ready | `vision/vision_engine.py`, moondream installed (but fix default model bug) |
| Image embeddings | 🟡 Requires modification | CLIP present but 512→768 padding is lossy; evidence not persisted |
| Image evidence | 🟡 Requires modification | Evidence model supports it; persistence missing |
| Ask AI about Image | 🟡 Requires modification | Works via OCR/moondream path in `ask_file_direct`; needs persistence + UI polish |
| Image semantic search | 🟡 Requires modification | CLIP path exists in indexer; needs persistence + intent handling |

### Audio

| Capability | Status | Why |
|---|---|---|
| Transcription | 🟢 Ready | `speech_engine.py` + `audio_extractor.py` implemented + tested |
| Timestamped evidence | 🟢 Ready | ContentBlocks carry `timestamp_start/end` + labels |
| Audio embeddings | 🟢 Ready | Text embeddings of transcripts via nomic |
| Ask AI about Audio | 🟡 Requires modification | Direct-ask path exists; persistence + UI entry missing |
| Audio semantic search | 🟡 Requires modification | Pipeline exists; persistence missing |

### Video

| Capability | Status | Why |
|---|---|---|
| Transcription | 🟢 Ready | `video_engine.py` + ffmpeg audio extraction, tested |
| Keyframe extraction | 🟢 Ready | `keyframe_engine.py` (OpenCV interval sampling), tested |
| OCR / vision analysis | 🟢 Ready | Keyframe captions via moondream (`video_extractor._caption_frame`) |
| Timestamped evidence | 🟢 Ready | Transcript + keyframe blocks carry timestamps |
| Ask AI about Video | 🟡 Requires modification | Direct-ask path exists; persistence + UI entry missing |
| Video semantic search | 🟡 Requires modification | Pipeline exists; persistence missing |

### Unified Retrieval

| Capability | Status | Why |
|---|---|---|
| Multimodal ContentBlocks | 🟢 Ready | Single `ContentBlock`/`EvidenceChunk` model already carries modality + timestamps |
| Common Evidence model | 🟢 Ready | One `EvidenceChunk` for all modalities |
| Common embeddings | 🟢 Ready | One `EmbeddingEngine` (nomic); CLIP padded into same FAISS space |
| Common FAISS index | 🟢 Ready | Single `VectorEngine` (IndexFlatIP, 768) |
| Modality-aware retrieval | 🟡 Requires modification | Keyword `_detect_modality` + extension filter works but is brittle (misses "which image has code" intent) |
| Evidence navigation | 🔴 Requires new architecture | No UI, no persisted mapping at runtime, no `vector_map` hydration |
| Persistence across restarts | 🔴 Requires modification | Wire `EngineDBStore` + hydrate `_evidence` at startup (currently in-memory only) |

---

## 23. Critical Findings

1. **Evidence/vector_map/search_history persistence is completely unwired** — restart breaks semantic search until re-index (`EngineDBStore` referenced only in tests; live DB tables at 0 rows).
2. **Embedded images in documents are invisible to Ask AI** (pptx/pdf/docx) — the source of "The available documents do not contain this information."
3. **Hardware ceiling:** 6.9 GiB RAM, no GPU, **4.8 GiB free disk** — multi-model concurrency (Whisper + CLIP + Ollama) is risky; disk growth is hard-limited.
4. **`vision_engine.py` defaults to a text-only model** (`qwen-local:latest`) — image captioning silently degrades.
5. **Duplicate/inconsistent extension sets and hardcoded Ollama URLs** across 5+ modules — a config refactor is a prerequisite for maintainable Batch 3 work.
6. **Stale manifests** (`requirements.txt`, `pyproject.toml`) vs actual deps; stale docs (`analysis_results.md` items already fixed in code).
7. **Ollama server not running at audit time** — model behavior unverified live.
8. **Preview panel loads the entire `indexed_files` table** in `_get_metadata_from_index` / `_get_extracted_text_from_index` (known N+1-style inefficiency).
9. **FAISS save/search race across concurrent tasks** is not fully serialized despite per-instance locking.
10. **No stale-vector cleanup** on file delete/modify; renames leave orphaned index entries.

---

## 24. Files That Must Be Modified for Batch 3

- `engines/db_store.py` (wire it) + `app/container.py` (expose store; hydrate evidence/vector_map on startup)
- `engines/ai_indexer.py` (persist evidence + vector maps; O(n) duplicate check; CLIP dim handling)
- `engines/retrieval_engine.py` (evidence hydration from DB; group multiple chunks per file instead of hard dedup)
- `ui/main_window.py` (Similar Documents entry, evidence navigation, restart-hydration call)
- `widgets/file_explorer.py` (context-menu actions: Image/Audio/Video AI, Similar Files, multimodal search)
- `ui/toolbar.py` / new dialog(s) (universal search bar; evidence navigation dialog)
- `engines/config.py` + `extractors/*.py` + `vision/vision_engine.py` + `rag_engine.py` (centralize model/URL config; fix vision default to moondream)
- `engines/content_engine.py` (OCR embedded images in pptx/pdf/docx)
- `tests/` (integration tests for the above)

---

## 25. Files That Must NOT Be Modified Without Care

- `database/models.py`, `database/migrations.py` — schema stability promised by docs; `indexed_files` is read by preview panel, indexer, watcher reindex
- `engines/rag_engine.py` — the direct-ask prompt is the accuracy lever for Ask AI
- `services/thread_manager.py`, `services/task_manager.py` — concurrency core; every worker depends on their contract
- `widgets/preview_panel.py` — 3 dedicated test suites depend on its current structure
- `services/sqlite_indexer.py` — dual-writer (scan + incremental reindex) with the `IndexedFile` table
- `main.py`, `app/container.py` (container semantics change ripples everywhere)
- `plugins/loader.py` / `core/plugin_registry.py` — plugin contract is the Batch 4+ extension point

---

*Report produced from a live codebase audit. The two most actionable next steps: (1) wire `EngineDBStore` + hydrate the evidence map on startup so indexed data survives restarts; (2) add embedded-image OCR to `ContentEngine` so Ask AI can answer questions about pptx diagrams. Both have test coverage already in place (`tests/test_batch3.py` covers the store; `tests/test_multimodal.py` covers OCR).*
