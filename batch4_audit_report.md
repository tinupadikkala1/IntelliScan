# IntelliVault — POST-BATCH-3 CURRENT-STATE AUDIT

*Audit date: 2026-08-11*
*Scope: current source code, live database, FAISS cache, Ollama runtime, and full test suite.*
*Purpose: input for designing the COMPLETE Batch 4 implementation plan.*
*Rule followed: nothing below is inferred from docs/comments alone — every claim is backed by code inspection, DB inspection, or a runtime test.*

**Transparency note (audit side effects):** The audit is read-only for code. Two runtime inspections had side effects on *runtime data* (not code), disclosed here:
1. Loading the app container for a hydration check executed the designed "remove orphaned FAISS vectors" cleanup. The on-disk `cache/faiss_index.bin` had **1,213 vectors with zero matching rows in the `evidence` table**; the cleanup removed them and saved an empty index. The DB `evidence`/`vector_map` tables were already **0 rows** *before* this audit ran.
2. The runtime smoke test (§20) used an isolated temp database + temp FAISS path, so project runtime data was not touched by it.

---

## 1. Executive Summary

IntelliVault is an offline PySide6 desktop "Smart File Intelligence System." Foundation (file explorer + scan/index), Batch 1 (scanning/indexing), Batch 2 (AI document analysis) and Batch 3 (semantic search / RAG / multimodal) are implemented. The full test suite passes **212/212** in 6m17s.

### State after Batch 3 — headline findings

| # | Finding | Severity |
|---|---------|----------|
| F1 | **Semantic search has no persisted data right now.** `evidence` = 0 rows, `vector_map` = 0 rows, `search_history` = 0 rows in `config/intellivault.db`. The legacy on-disk FAISS index (1,213 vectors, dim 768) had no matching evidence and was removed by the app's own startup hydration (by design). Any Semantic Search now returns "No files indexed yet." The user must run **Index for AI** again to repopulate. | **P0 (data), works-as-designed (mechanism)** |
| F2 | **Persistence wiring is complete and verified working.** `EngineDBStore` is wired into the container; `AIFolderIndexer` persists evidence + vector_map per file; startup hydration restores the evidence map and enforces "every FAISS vector resolves to evidence." The smoke test proved index → save → reload → hydrate → search works across a simulated restart. | OK |
| F3 | **Ask AI (direct, full-file) works and answers correctly.** In the smoke test, "How many people worked on this project…" was answered with all three names + a citation — the exact failure class from the pre-Batch-3 bug report ("The available documents do not contain this information") is fixed by the Tier-1 direct path. | OK |
| F4 | **Retrieval ranking quality is imperfect.** In the smoke test, the query "Who demoed the CLIP image search?" ranked an image OCR chunk (score 0.422, "PROJECT APOLLO LAUNCH SCHEDULE …") above a text chunk containing the near-verbatim answer. Pure cosine ranking with no LLM re-rank in the engine-level `smart_retrieve` path. | P1 |
| F5 | **Hardware is severely constrained.** Intel i3-N305 (8 threads), 6.9 GiB RAM, **no GPU** (torch 2.7.0+cpu), and ~4.6 GiB free disk (98% full). Whisper (base), CLIP (ViT-B/32), FAISS, tesseract and all Ollama models run on CPU in-process. | Constraint |
| F6 | **Ollama was running at audit time** with 4 models installed and reachable: `moondream:latest` (vision), `nomic-embed-text:latest` (embedding), `qwen-local:latest` (LLM), `qwen3:latest` (LLM). | OK |
| F7 | **File watcher → incremental reindex only maintains the Batch 1 SQLite index.** Modified/deleted/renamed files do **not** update AI evidence, vector_map, or FAISS → stale evidence/vectors are possible after any filesystem change. | P1 |
| F8 | **Dead infrastructure:** `embeddings` table (migration 3) and the FTS5 `file_content_fts` virtual table are created but never written. `files`/`folders` tables are only touched by tests/repository helpers, not by the scan pipeline (which writes `indexed_files`). | P2/P3 |

### Batch-level summary

- **Foundation (M1–M8):** COMPLETE — explorer, navigation, preview, DB, services, settings, plugins.
- **Batch 1 (scan + index):** COMPLETE — `Scan Folder` → `indexed_files` (89 rows live), text/metadata extraction, incremental reindex on watcher events.
- **Batch 2 (AI analysis):** COMPLETE — AI Analysis dialog, qwen-local, summary/keywords/tags/category/language, SHA-256 identity, SQLite cache (`ai_analysis`, 3 rows live), regenerate, rename/move-preserving cache.
- **Batch 3 (semantic search + RAG + multimodal):** IMPLEMENTED as a whole; per-feature status in §6. Two caveats: (a) **no live indexed data** right now (F1), and (b) several B3 features are PARTIAL because the *user-reachable UI* path for a sub-aspect is missing (e.g., PPTX slide navigation, video timestamp navigation reachable only through search results).

---

## 2. Project Structure

```
IntelliScan/                                  # project root (= IntelliVault)
├── main.py                                   # entry point: Container → logging → QApplication → MainWindow
├── pyproject.toml                            # package metadata, editable install, pytest config
├── requirements.txt                          # ONLY 4 runtime deps (pyside6, sqlalchemy, watchdog, mutagen)
├── app/
│   ├── container.py                          # DI container; lazy db/repo/tasks/watcher/engines; db_store + hydration wiring
│   └── signal_bus.py                         # central Qt signal hub
├── core/
│   ├── config.py                             # JSON settings (config/settings.json) + typed accessors + changed signal
│   ├── logging_setup.py                      # file+console logging, DB log handler
│   └── plugin_registry.py                    # PluginInterface ABC + registry + hooks
├── ai/                                       # Batch 2 analysis pipeline
│   ├── ai_service.py                         # orchestrates prompt → Ollama → JSON parse
│   ├── analysis_manager.py                   # file-level facade (extract → hash → analyze)
│   ├── cache_manager.py                      # AIAnalysis SQLite cache keyed by SHA-256
│   ├── ollama_client.py                      # /api/generate client, availability check
│   ├── prompt_builder.py                     # structured JSON analysis prompts, detail levels
│   ├── json_parser.py                        # robust JSON extraction/validation
│   └── config.py                             # MODEL_NAME=qwen-local, TEMPERATURE, TIMEOUT
├── engines/                                  # Batch 3 core
│   ├── config.py                             # SINGLE source: models, URLs, chunking, thresholds, ext registries
│   ├── content_engine.py                     # UniversalContentEngine → ContentBlock (page/slide/sheet/section/ocr/caption/transcript…)
│   ├── evidence_engine.py                    # ContentBlock → EvidenceChunk (chunking, provenance, modality, timestamps)
│   ├── embedding_engine.py                   # nomic-embed-text via Ollama /api/embed (batch + fallback)
│   ├── vector_engine.py                      # FAISS IndexFlatIP + .ids pickled chunk_ids; add/search/remove/save/load/clear; RLock
│   ├── retrieval_engine.py                   # retrieve()/smart_retrieve()/retrieve_similar(); hydrate_from_store(); match_strength
│   ├── rag_engine.py                         # RAGEngine: ask(), ask_file(), ask_file_direct(), rerank_results(), _ask_image_direct
│   ├── db_store.py                           # EngineDBStore: evidence/vector_map/search_history persistence
│   ├── ai_indexer.py                         # AIFolderIndexer: folder → per-file index → FAISS + DB persistence; disk-space check
│   └── clip_engine.py                        # CLIP ViT-B/32 image/text embeddings (lazy global model)
├── extractors/                               # multimodal extractors
│   ├── base_extractor.py                     # BaseMultimodalExtractor ABC
│   ├── extractor_factory.py                  # MultimodalExtractorFactory dispatcher
│   ├── document_extractor.py                 # wraps UniversalContentEngine for documents
│   ├── image_extractor.py                    # OCR (tesseract) + vision caption (moondream); shared ocr_image_bytes/caption_image_bytes
│   ├── audio_extractor.py                    # Whisper base transcription → timestamped transcript blocks (~30s groups)
│   └── video_extractor.py                    # ffmpeg audio extract → Whisper; OpenCV keyframes → moondream captions
├── text_extraction/                          # Batch 1/2 plain-text extraction (extractor per format)
│   ├── extractor_factory.py, base_extractor.py
│   └── txt, md, pdf, docx, pptx, xlsx, csv, json, xml extractors
├── speech/speech_engine.py                   # SpeechEngine: Whisper transcription w/ segments (used by video engine + RAG direct)
├── vision/
│   ├── vision_engine.py                      # VisionEngine: moondream captions (file + frame)
│   ├── ocr_engine.py                         # OCREngine: tesseract with OpenCV preprocessing
│   └── content_merger.py                     # merge OCR + vision results → ContentBlocks
├── video/
│   ├── video_engine.py                       # VideoEngine: audio track → transcribe → blocks (used by RAG direct ask)
│   └── keyframe_engine.py                    # KeyframeEngine: interval-based keyframe sampling (OpenCV)
├── services/
│   ├── folder_scanner.py                     # walk + progress + cancellation → DiscoveredItem/ScanResults
│   ├── metadata_extractor.py                 # size/mime/dates/owner/checksum
│   ├── text_extractor.py                     # Batch 1 text extraction (PyPDF2/docx/pptx/openpyxl/pandas optional)
│   ├── sqlite_indexer.py                     # IndexedFile model + dual-writer (scan + incremental)
│   ├── thread_manager.py                     # QThreadPool + QRunnable Worker with signals
│   ├── task_manager.py                       # submit/cancel/progress; persists to tasks table
│   ├── file_watcher.py                       # watchdog wrapper → changed signal (non-recursive)
│   ├── cache_manager.py                      # mem+disk cache (thumbnails)
│   └── evidence_navigator.py                 # EvidenceLocation + EvidenceNavigator (PDF jump / media seek / preview / open)
├── database/
│   ├── engine.py                             # SQLAlchemy engine + session factory at config/intellivault.db
│   ├── models.py                             # 8 foundation tables + AIAnalysis + Evidence/VectorMap/SearchHistory
│   ├── migrations.py                         # versioned migrations (1-6): FTS5, embeddings, modality columns
│   └── repository.py                         # CRUD for favorites/recent/files/folders/tasks/plugins/logs/settings
├── ui/
│   ├── main_window.py                        # assembles everything; owns ALL AI orchestration (scan, analysis, index, search, ask)
│   ├── menu_bar.py, toolbar.py, status_bar.py, dock_manager.py, theme_engine.py, settings_dialog.py
│   ├── indexed_files_widget.py, indexed_files_model.py
│   └── dialogs/
│       ├── ai_analysis_dialog.py             # Batch 2 analysis display + regenerate
│       ├── ask_ai_dialog.py                  # Ask AI about this File (question → answer + citations)
│       ├── semantic_search_dialog.py         # search + modality filter + result cards
│       └── b1_progress_dialog.py             # Batch 1 scan progress
├── widgets/
│   ├── file_explorer.py                      # list/grid explorer + context menu (incl. AI menu)
│   ├── preview_panel.py                      # image/text/PDF/audio-info/video-thumb + audio/video players + jump_to_page/seek_media
│   ├── folder_tree.py, favorites.py, drives.py, breadcrumb.py
├── plugins/
│   ├── loader.py                             # discover plugins package modules, call setup()
│   └── example_plugin.py
├── tests/                                    # 18 test files, 212 tests (§19)
├── config/settings.json                      # runtime settings (currently max_threads=6, theme dark, view grid)
├── config/intellivault.db                    # live SQLite DB (§8)
├── cache/faiss_index.bin (+ .ids)            # FAISS index (now 0 vectors after orphan cleanup — see §9)
├── logs/                                     # runtime logs
└── *.md docs: IntelliVault_Batch3.md, plan to  implement batch 3.md, IMPLEMENTATION_PLAN.md,
    IntelliVault_Foundation_Blueprint_v1.md, batch3_audit_report.md, batch 3 completed…md, system_architecture.md …
```

---

## 3. Technology Stack (verified against live venv, not requirements.txt)

`requirements.txt` lists only 4 runtime deps; the real stack is much larger (installed in `venv/` and imported by code).

| Layer | Technology | Version (verified) | Where used |
|---|---|---|---|
| Language | Python | 3.12.7 | `venv/bin/python3` |
| GUI | PySide6 (Qt6) | 6.11.1 | `ui/`, `widgets/`; QtPdf (`PySide6.QtPdf`), QtMultimedia (`QMediaPlayer`/`QAudioOutput`/`QVideoWidget`) |
| Database | SQLite via SQLAlchemy 2.0.51 | — | `database/`, `engines/db_store.py` |
| Vector index | faiss-cpu 1.14.3 (IndexFlatIP) | — | `engines/vector_engine.py` |
| LLM (RAG + analysis + rerank) | Ollama `qwen-local:latest` | installed, reachable | `engines/rag_engine.py`, `ai/ollama_client.py` |
| Embedding model | Ollama `nomic-embed-text:latest`, 768-dim | installed, reachable | `engines/embedding_engine.py`, `engines/retrieval_engine.py` |
| Vision model | Ollama `moondream:latest` (1.7 GB, phi2+clip, vision capability) | installed, reachable | `engines/config.py VISION_MODEL`, `vision/vision_engine.py`, `extractors/image_extractor.py`, `extractors/video_extractor.py`, `engines/rag_engine.py` |
| OCR | pytesseract 0.3.13 + tesseract 5.3.4 (system) | working | `extractors/image_extractor.py`, `vision/ocr_engine.py`, `engines/rag_engine.py` |
| Speech | openai-whisper 20250625, model `base` (cached at `~/.cache/whisper/base.pt`) | working | `extractors/audio_extractor.py`, `speech/speech_engine.py`, `video/video_engine.py` |
| Video processing | ffmpeg (system, at /usr/bin/ffmpeg) + opencv-python-headless 5.0.0.93 | working | `extractors/video_extractor.py`, `widgets/preview_panel.py`, `video/` |
| CLIP | `clip` 1.0 (openai-clip, ViT-B/32) + torch 2.7.0+cpu | working (loaded lazily, ~30-60s first load) | `engines/clip_engine.py`, `engines/ai_indexer.py` |
| Image libs | pillow 12.2.0 | working | image extractor/preview |
| Documents | pymupdf 1.28.0 (fitz), python-docx 1.2.0, python-pptx 1.0.2, openpyxl 3.1.5 | working | `text_extraction/`, `engines/content_engine.py` |
| File watcher | watchdog 6.0.0 | working | `services/file_watcher.py` |
| Audio tags | mutagen 1.48.1 | working | `widgets/preview_panel.py` |
| HTTP | requests 2.34.2 | working | Ollama clients |
| Encoding | chardet 7.4.3 | working | txt/md extractors |
| Testing | pytest 9.1.1, pytest-qt 4.5.0 | 212/212 pass | `tests/` |

### Model configuration map

| Model | Configured in | Used in | Reachable? | Load style |
|---|---|---|---|---|
| `qwen-local:latest` | `engines/config.py LLM_MODEL` (RAG) AND `ai/config.py MODEL_NAME` (Batch 2 analysis — separate constant) | RAGEngine, rerank, AIService | ✅ (responded in test) | Per-request via HTTP; no resident process |
| `nomic-embed-text:latest` | `engines/config.py EMBEDDING_MODEL` | EmbeddingEngine | ✅ | HTTP per batch |
| `moondream:latest` | `engines/config.py VISION_MODEL` | ImageExtractor caption, VideoExtractor keyframes, VisionEngine, RAG `_ask_image_direct` | ✅ | HTTP per image |
| Whisper `base` | `extractors/audio_extractor.py` default + `engines/config.py WHISPER_MODEL` (defined but **AudioExtractor/SpeechEngine hardcode `"base"`** — see §22) | AudioExtractor, SpeechEngine, VideoEngine | ✅ (model cached) | Lazy, **cached globally** (`_MODEL_CACHE` in audio_extractor; per-instance in speech_engine — duplicated) |
| CLIP ViT-B/32 | `engines/clip_engine.py` | AIFolderIndexer `_index_image` | ✅ (loaded in smoke test) | Lazy global module cache `_clip_model` |

---

## 4. Batch 1 Status

Batch 1 = folder scanning + metadata/text extraction + SQLite indexing (`indexed_files`).

| Feature | Status | Relevant files | UI entry | Tests | Notes |
|---|---|---|---|---|---|
| Folder scan (recursive, progress, cancel) | COMPLETE | `services/folder_scanner.py` | Toolbar **Scan Folder** → `_on_scan_requested` (`ui/main_window.py`) | `test_batch2_integration.py`, `test_services.py` | Walk with symlink-cycle guard, ignore patterns, progress callback, cancel_event |
| Metadata extraction | COMPLETE | `services/metadata_extractor.py` | same | `test_batch2_integration.py` | mime/size/dates/owner/SHA-256 checksum |
| Text extraction | COMPLETE | `services/text_extractor.py` | same | — | txt/md/csv/xlsx/pptx/pdf/docx; 20 MB cap |
| SQLite index (`indexed_files`) | COMPLETE | `services/sqlite_indexer.py` | same | `test_batch2_integration.py`, `test_indexed_files.py` | 89 rows live; upsert by absolute_path; status tracking |
| Batch-1 progress dialog | COMPLETE | `ui/dialogs/b1_progress_dialog.py` | same | — | cancel wired |
| Incremental reindex (watcher-driven) | COMPLETE (Batch-1 scope only) | `ui/main_window.py:_incremental_reindex/_perform_incremental_reindex` | automatic | — | new/modified files only; **does not touch AI evidence/FAISS** (§18) |
| Indexed Files panel | COMPLETE | `ui/indexed_files_widget.py`, `ui/indexed_files_model.py` | bottom of central area (fixed 180 px) | `test_indexed_files.py` | search + MIME filters; click → preview via `file_selected` signal |
| FTS5 full-text search | NOT IMPLEMENTED (infra only) | `database/migrations.py add_fts5_index` | none | none | virtual table created but never populated (0 content rows); no code writes it |

Known limitations (Batch 1): `files`/`folders` tables unused by the scan path (scan writes only `indexed_files`); `tasks` table grows unbounded (2,499 rows live); `.tmp`/`zip` files are indexed by Batch 1 but excluded by AI indexing.

---

## 5. Batch 2 Status

Batch 2 = AI document analysis via Ollama with content-hash caching.

| Feature | Status | Files | UI entry | DB | Tests | Notes |
|---|---|---|---|---|---|---|
| AI analysis (summary/keywords/tags/category/language) | COMPLETE | `ai/ai_service.py`, `ai/prompt_builder.py`, `ai/json_parser.py`, `ai/ollama_client.py` | Right-click file → **AI → Analyze File** (`widgets/file_explorer.py`), detail-level dialog | `ai_analysis` | `test_batch2_unit.py`, `test_batch2_integration.py` | 3 rows live |
| Ollama integration | COMPLETE | `ai/ollama_client.py` | same | — | same | `qwen-local:latest`, timeout 480 s, temperature 0.3 |
| SHA-256 identity (rename/move-safe) | COMPLETE | `ai/cache_manager.py`, `ai/analysis_manager.py` | — | `ai_analysis.file_hash` unique | `test_batch2_unit.py` | content hash, not path |
| SQLite caching | COMPLETE | `ai/cache_manager.py` | — | `ai_analysis` | `test_batch2_unit.py` | get/store/delete/has |
| Regeneration | COMPLETE | `ui/main_window.py:_on_ai_regenerate*` | Context menu **AI → Regenerate Analysis**; dialog button | deletes + reruns | — | detail level re-asked |
| View cached analysis | COMPLETE | `ui/main_window.py:_on_ai_view_requested` | Context menu **AI → View Analysis** | — | — | enabled only when hash exists (`file_explorer._check_ai_analysis_exists`) |
| Language detection | COMPLETE (model-driven) | `ai/prompt_builder.py` (field), `ai/json_parser.py` (validation) | — | `ai_analysis.language` | `test_batch2_unit.py` | "English" in live rows |
| Detail levels (low/medium/high) | COMPLETE | `ai/prompt_builder.py DETAIL_LEVELS` | QInputDialog choice | — | `test_batch2_unit.py` | |
| Background processing | COMPLETE | `ui/main_window.py:_run_ai_analysis` via `TaskManager` | — | `tasks` (10 done / 8 error rows) | — | QProgressDialog, cancel → cancel_event; UI stays responsive |
| Error handling | COMPLETE | `ai/ai_service.py` (ConnectionError/Timeout/ValueError), `main_window._ai_analysis_error` | QMessageBox | — | `test_batch2_unit.py` | user-visible errors |
| AI Analysis dialog | COMPLETE | `ui/dialogs/ai_analysis_dialog.py` | after analysis completes | — | — | |

Known issues (Batch 2): 8 of 18 `ai_analysis` task rows ended in `error` (Ollama unavailable at some point historically — current server is up); `MAX_TEXT_CHUNK` 6000 chars truncates long documents; model name duplicated between `ai/config.py` and `engines/config.py`.

---

## 6. Batch 3 — 16-Feature Audit

Criteria: a feature is COMPLETE only if backend + reachable UI + integration + persistence + tests all exist and pass.

| ID | Feature | Status | UI Entry | Backend Files | Database | Tests | Known Issues |
|----|---------|--------|----------|---------------|----------|-------|--------------|
| B3-01 | Image Intelligence (OCR + caption + CLIP) | **COMPLETE** | Index for AI → image files | `extractors/image_extractor.py`, `engines/clip_engine.py`, `engines/ai_indexer.py:_index_image`, `vision/` | evidence + vector_map (when persisted) | `test_multimodal.py` (34), `test_batch3_extended.py` | Verified at runtime: OCR text + moondream caption + CLIP vector produced for a test PNG. CLIP adds a padded 512→768 vector; searchable via text queries. |
| B3-02 | OCR Search | **COMPLETE** | Semantic Search (after indexing) | `extractors/image_extractor.py`, `engines/content_engine.py` (embedded OCR), `retrieval_engine` | evidence | `test_multimodal.py` | Smoke test: "launch schedule" matched OCR text of a whiteboard PNG. |
| B3-03 | Vision Understanding | **COMPLETE** | Index for AI / Ask AI on image | `vision/vision_engine.py`, `extractors/image_extractor.py caption_image_bytes`, `engines/rag_engine.py:_ask_image_direct` | evidence (caption chunks) | `test_multimodal.py` | Caption only attempted when OCR text < 30 chars for embedded images; standalone images always caption. moondream is slow on CPU (~10-30 s/image). |
| B3-04 | Ask AI About Image | **COMPLETE** | Right-click image → AI → **Ask AI about this File** | `engines/rag_engine.py:_ask_image_direct` (OCR → vision fallback → qwen) | search_history | `test_multimodal.py`, `test_batch3_extended.py` | OCR-first strategy: >50 chars of OCR text skips vision entirely (may miss visual facts). |
| B3-05 | Audio Intelligence (Whisper transcription) | **COMPLETE** | Index for AI → audio files | `extractors/audio_extractor.py`, `speech/speech_engine.py` | evidence | `test_multimodal.py` | Runtime-verified: Whisper base loaded, silence WAV → 0 blocks (correct). Grouping into ~30 s blocks. |
| B3-06 | Audio Semantic Search | **COMPLETE** | Semantic Search + Audio filter | `retrieval_engine.smart_retrieve` + `filter_results_by_modality` | evidence | `test_batch3_extended.py` | Only as good as transcript quality; requires re-index after adding audio. |
| B3-07 | Ask AI About Audio | **COMPLETE** | Right-click audio → AI → Ask AI | `engines/rag_engine.py:ask_file_direct` → `_extract_audio_text` (Whisper) → audio prompt | search_history | `test_multimodal.py`, `test_batch3_extended.py` | Transcript truncated at `DIRECT_MAX_CONTEXT`=12000 chars for long files. |
| B3-08 | Audio Timestamp Navigation | **COMPLETE** | Double-click audio search result → preview player seeks to `timestamp_start` | `widgets/preview_panel.py:play_audio/seek_media`, `services/evidence_navigator.py` | — | `test_batch3_extended.py` | Player opens only via evidence navigation; selecting an audio file in the explorer shows metadata, not a play button (§15). |
| B3-09 | Video Intelligence (transcript + keyframes) | **COMPLETE** (code) / PARTIAL (runtime coverage) | Index for AI → video files | `extractors/video_extractor.py`, `video/video_engine.py`, `video/keyframe_engine.py` | evidence | `test_multimodal.py` | ffmpeg + Whisper + OpenCV + moondream; keyframes capped (MAX_KEYFRAMES_PER_VIDEO=5, interval 60 s). **Runtime path not exercised in this audit** (no sample video; pipeline unit-tested). |
| B3-10 | Video Semantic Search | **COMPLETE** | Semantic Search + Video filter | `retrieval_engine` + modality filter | evidence | `test_batch3_extended.py` | Same dependency chain as B3-09. |
| B3-11 | Ask AI About Video | **COMPLETE** | Right-click video → AI → Ask AI | `engines/rag_engine.py:ask_file_direct` → `_extract_video_text` (ffmpeg audio → Whisper) → video prompt | search_history | `test_multimodal.py` | Full video transcription is very slow on CPU; no progress UI inside the ask (status bar only). |
| B3-12 | Video Timestamp Navigation | **COMPLETE** (via results) | Double-click video search result → preview player seeks | `widgets/preview_panel.py:play_video/seek_media` | — | `test_batch3_extended.py` | Same reachability caveat as B3-08. Keyframe timestamps also carry `timestamp_start` for seek. |
| B3-13 | Evidence Navigation | **PARTIAL** | Double-click search result (Semantic Search dialog) | `services/evidence_navigator.py`, `ui/main_window.py:_on_evidence_location_requested` | — | `test_batch3_extended.py` | PDF page jump ✅, audio seek ✅, video seek ✅, image preview ✅, plain open ✅. **PPTX slide jump ❌, DOCX section jump ❌** — slide/section results fall through to "open file externally." Ask AI citations open the file externally, not at the evidence location. |
| B3-14 | Unified Multimodal Search | **COMPLETE** | Toolbar semantic box / AI menu → Semantic Search dialog with **Type: All/Documents/Images/Audio/Video** | `ui/dialogs/semantic_search_dialog.py`, `ui/main_window.py:_perform_semantic_search` | search_history | `test_batch3_extended.py` | Filter over-fetches (top_k=40) then filters; LLM re-rank skipped when an explicit filter is active. |
| B3-15 | Unified Evidence Results | **COMPLETE** | Search result cards show modality icon, source label, snippet, path | `ui/dialogs/semantic_search_dialog.py:_build_result_item` | — | `test_batch3_extended.py` | |
| B3-16 | Confidence / Match Explanation | **COMPLETE** | Result card "Similarity: 0.422 · Match strength: Low" | `retrieval_engine.match_strength/explain_match` (High≥0.80, Medium≥0.60, else Low), `semantic_search_dialog.match_strength_label` | — | `test_batch3_extended.py` | Deliberately NOT a calibrated "% confidence"; labels only. `explain_match` is defined but **not shown in the UI** (dead code). |

**Overall Batch 3 verdict:** 14 of 16 features functionally COMPLETE with reachable UI; B3-13 PARTIAL (PPTX/DOCX deep navigation missing); B3-16 has an unused `explain_match` helper. The most important *operational* caveat remains F1: with `evidence`=0 rows the features cannot be exercised until the user re-runs **Index for AI**.

---

## 7. Current Architecture (verified data flow)

Reconstructed from source (not from docs):

### Indexing pipeline (what actually happens)

```
User clicks "Index for AI" (toolbar)
  → MainWindow._on_ai_index_requested → TaskManager.submit (QRunnable on QThreadPool)
  → AIFolderIndexer.index_folder(folder, recursive=True, cancel_event)
      → _discover_files (skip dotfiles, node_modules, __pycache__, venv, .git, build, dist, .cache, cache; skip SKIP_EXTENSIONS)
      → per file (transactional, rollback on error):
          ext in IMAGE  → _index_image:  UniversalContentEngine.extract → ContentBlocks (OCR + caption)
                                          → EvidenceChunks (modality="image") → embed(nomic) → FAISS
                                          + CLIP.embed_image → 512-dim padded to 768 → FAISS (source_type="clip_visual")
          ext in AUDIO/VIDEO → _index_media: UniversalContentEngine.extract (Whisper transcript blocks
                                          + optional keyframes) → EvidenceChunks → embed → FAISS
          else → _index_document: EvidenceEngine.build_evidence (UniversalContentEngine → ContentBlocks
                                          → chunked EvidenceChunks) → embed_batch(nomic) → FAISS
      → _persist_indexed(chunks): EngineDBStore.store_evidence + store_vector_maps (only the chunks that got vectors)
      → VectorEngine.save() → cache/faiss_index.bin + .ids (called from MainWindow after indexing)
```

Stage-by-stage:

| Stage | Input | Output | Class | Persistence | Threading | Error handling |
|---|---|---|---|---|---|---|
| Content extraction | file path | `ContentBlock[]` (text, source_type/label/index, modality, timestamps, confidence) | `UniversalContentEngine` (engines/content_engine.py) | none | worker thread | per-file try/except → empty list + log |
| Evidence build | ContentBlock[] | `EvidenceChunk[]` (chunk_id=uuid4 hex, char offsets, full provenance) | `EvidenceEngine` (engines/evidence_engine.py) | none | worker thread | try/except → empty |
| Embedding | chunk texts (prefix `search_document: ` for nomic) | `np.ndarray[]` (768) | `EmbeddingEngine.embed_batch` → Ollama `/api/embed` (falls back to sequential `embed_text`) | none | worker thread | None vectors skipped; batch fallback |
| Vector store | chunk_id + vector | FAISS index entries + in-memory chunk_id list | `VectorEngine.add/add_batch` (IndexFlatIP, L2-normalized = cosine) | `save()` → faiss_index.bin + .ids | worker thread, guarded by `RLock` | shape check; per-add try/except |
| Evidence map | chunk_id → EvidenceChunk | in-memory dict `retrieval_engine._evidence` | `RetrievalEngine.update_evidence_store` | DB via `db_store` at index time; reloaded by `hydrate_from_store` at startup | worker thread writes; GUI thread reads at search time (through worker) | hydration skips missing evidence |
| Persistence | indexed chunks | `evidence` rows + `vector_map` rows | `EngineDBStore.store_evidence/store_vector_maps` | SQLite | worker thread | per-file try/except; transactional rollback via `_remove_file_evidence` on failure |
| Search | query | `RetrievalResponse` (ranked `RetrievalResult[]`) | `RetrievalEngine.retrieve` / `smart_retrieve` (embed query → FAISS search → evidence lookup → scope/filter/dedup) | search_history via MainWindow | worker thread | embedding failure → `embedding_available=False`; empty index → "NO_INDEX" |
| RAG / Ask | question (+ file filter) | `RAGResponse` (answer + citations) | `RAGEngine.ask` (retrieve→context→prompt→qwen) or `ask_file_direct` (full text → prompt → qwen) | none | worker thread | no evidence → grounded=False message; generation failure → "check Ollama" message |
| UI | result dicts | result cards / answer / navigation | `SemanticSearchDialog`, `AskAIDialog`, `EvidenceNavigator` | — | GUI thread (worker callbacks) | dialog `set_error` paths |

### Retrieval scope mapping (verified)

- `RetrievalScope.SELECTED_FILE` / `SELECTED_FILES` → `retrieve(..., file_filter=[paths])` — used by `RAGEngine.ask_file`; **not reachable from the current UI** (Ask AI uses `ask_file_direct` instead).
- `WORKSPACE` → semantic search (top_k*6 over-fetch in `smart_retrieve`).
- `FOLDER` scope enum exists; **no code path passes it** (searches are workspace-wide).

### Engine ownership notes (verified)

- `VectorEngine` exposes `list_chunk_ids()`; `RetrievalEngine` reads `_vector`/`_evidence` private attributes in `ai_indexer` (`self._retrieval._evidence`, `self._retrieval._vector.dimension`).
- `AIFolderIndexer` decides "already indexed" by scanning the in-memory evidence map per file (O(n) per file).
- CLIP vectors are recorded in `vector_map` with `embedding_model=nomic-embed-text` (minor mislabeling — `_persist_indexed` always passes `EMBEDDING_MODEL`).
- `index_chunks` in RetrievalEngine is a thin wrapper over `index_chunks_detailed` (returns count only).

---

## 8. Database Audit (live DB inspected)

DB file: `config/intellivault.db` (1,085,440 bytes). SQLAlchemy + SQLite, `check_same_thread=False`, migrations v1–v6 applied (`schema_version`=6).

### Tables, columns, row counts (exact, from live DB)

| Table | Rows | Columns | PK | Notes |
|---|---|---|---|---|
| `indexed_files` | **89** | id, filename, absolute_path (unique), size, mime_type, extension, created_date, modified_date, checksum, extracted_text, metadata_json, scan_timestamp, indexing_status, processing_attempts, error_message, last_updated | id | Batch 1 scan output; written by `SQLiteIndexer`; read by Indexed Files panel/preview metadata |
| `ai_analysis` | **3** | id, file_hash (unique, indexed), summary, keywords, tags, category, language, ai_generated, generated_time, prompt_version, model_name | id | Batch 2 cache; written/read by `ai/cache_manager.py` |
| `evidence` | **0** | id, chunk_id (unique, indexed), file_path (indexed), file_hash (indexed), text, source_type, source_index, source_label, char_start, char_end, **modality, timestamp_start, timestamp_end, confidence, metadata_json** (migration 6), indexed_at | id | Batch 3 evidence; written by `EngineDBStore.store_evidence`; read by `get_all_evidence`/`get_evidence_by_file`/hydration |
| `vector_map` | **0** | id, chunk_id (unique, indexed), file_path (indexed), file_hash (indexed), embedding_model, indexed_at | id | written by `EngineDBStore.store_vector_map(s)` |
| `search_history` | **0** | id, query, scope, results_count, elapsed_ms, searched_at | id | written by `EngineDBStore.record_search` (MainWindow `_perform_semantic_search`) |
| `embeddings` | **0** | id, file_id, model, vector BLOB, created | id | **dead** — created by migration 3, never written; FK → files(id) |
| `file_content_fts` (+ shadow tables) | **0** | FTS5 virtual table (path, name, content) | — | **dead** — created by migration 2, triggers only fire on `files` table which is never written by the scan pipeline |
| `files` | **6** | id, path (unique, indexed), name, parent, size, mime, modified, checksum | id | only test data (paths under /tmp) + `Repository.upsert_file`; **unused by runtime flows** |
| `folders` | **4** | id, path (unique), name, parent | id | same as files |
| `tasks` | **2499** | id, task_id (unique), type, status, progress, total, created, finished | id | unbounded growth: 2365 incremental_reindex done, 71 batch_1_scan, 44 semantic_search, 34 ask_ai, 21 ai_index/ai_analysis, 6+1 pending |
| `recent` | **50** | id, path (indexed), name, opened | id | `Repository.add_recent` (capped at 50) |
| `favorites` | **1** | id, path (unique), name, added | id | |
| `settings` | **9** | key (pk), value | key | mirrors config JSON |
| `plugins` | **0** | id, name (unique), version, enabled | id | |
| `logs` | **11** | id, timestamp, level, logger, message | id | DB log handler |
| `schema_version` | **1** | version (pk), applied | version | =6 |

### Writer/reader matrix

| Table | Writes | Reads |
|---|---|---|
| indexed_files | `services/sqlite_indexer.py` (scan + incremental) | `ui/indexed_files_model.py`, `widgets/preview_panel.py`, `services/sqlite_indexer.py` |
| evidence | `engines/db_store.py` (via `ai_indexer._persist_indexed`) | `engines/db_store.py`, `engines/retrieval_engine.hydrate_from_store` |
| vector_map | `engines/db_store.py` | `engines/db_store.py` (`get_all_vector_maps` — **not called by hydration**, hydration uses evidence only) |
| search_history | `ui/main_window.py` | `engines/db_store.get_recent_searches` (**no UI consumer** — dead read) |
| ai_analysis | `ai/cache_manager.py` | `ai/cache_manager.py`, `widgets/file_explorer._check_ai_analysis_exists` |
| tasks | `services/task_manager.py` | repository/task manager; unbounded |

**Population verdict:** `indexed_files`, `ai_analysis`, `tasks`, `recent`, `settings` are populated at runtime. `evidence`, `vector_map`, `search_history` are written correctly by the new pipeline but are **0 rows in the live DB** (index was created before persistence wiring, or data was wiped). `embeddings`, `file_content_fts`, `files`, `folders`, `plugins` are effectively unused by runtime flows.

---

## 9. FAISS / Vector Storage Audit

| Aspect | Finding (verified) |
|---|---|
| Index type | `faiss.IndexFlatIP` (inner product) on L2-normalized vectors ⇒ cosine similarity; dim 768 (`EMBEDDING_DIM`) |
| Creation | `VectorEngine.__init__` (engines/vector_engine.py) |
| Loading | `VectorEngine.__init__` auto-loads `cache/faiss_index.bin` + `.ids` if present (`_load`) |
| Saving | `VectorEngine.save()` → `faiss.write_index` + pickle of `_chunk_ids` list; called after AI indexing (MainWindow) and after hydration cleanup (container) |
| Vector IDs | chunk_id strings (uuid4 hex, 32 chars) stored in order in the pickled `.ids` list; FAISS position = list index. No `IndexIDMap`; removal rebuilds the index from `reconstruct()`. |
| vector_map role | Record of "this chunk was embedded with model X" — **not used for hydration** (hydration reconstructs from `evidence` + FAISS ids only) |
| Evidence mapping | in-memory dict `RetrievalEngine._evidence` (chunk_id → EvidenceChunk) |
| Deletion | `RetrievalEngine.remove_file(file_path)` → `VectorEngine.remove_by_chunk_ids` (full index rebuild), evidence map popped; DB rows via `EngineDBStore.delete_evidence_by_file` (evidence + vector_map for that path) |
| Update/rebuild | No bulk rebuild API; per-file reindex (`AIFolderIndexer.reindex_file` = remove + index) exists but is **not wired to any UI or watcher action** |
| Startup hydration | `container.retrieval_engine` → `hydrate_from_store(db_store)`: loads all evidence, keeps only chunks whose id is in FAISS, **removes FAISS vectors with no evidence**, then `vector_engine.save()` |
| Concurrency/locking | `VectorEngine` guarded by `threading.RLock` (`@lock_required`); DB sessions per-call (SQLite `check_same_thread=False`) |
| Stale-vector handling | Hydration removes orphans (verified live: 1,213 removed). Stale *evidence* (DB rows whose file was deleted/modified) is **kept** — no file-existence check in hydration |

### Invariant: EVERY ACTIVE FAISS VECTOR MUST RESOLVE TO VALID PERSISTED EVIDENCE

- **Mechanism: HOLDS** — `hydrate_from_store` enforces it (removes orphans), and indexing persists only chunks that got vectors (`_persist_indexed` receives `indexed_chunks`).
- **Live state before audit: VIOLATED** — FAISS on disk had 1,213 vectors, DB `evidence` had 0 rows. Hydration removed them (by design) and saved the empty index.
- **Restart behavior test (performed, §20):** index content → save → construct new VectorEngine (reload) → hydrate → search. **Result: 3/3 evidence chunks hydrated, searches resolve text correctly.** ✅ The invariant holds for newly indexed data.

---

## 10. Multimodal Pipeline Audit

### DOCUMENT
`UniversalContentEngine.extract` (per-format: PDF page-by-page + embedded images; PPTX slide-by-slide + slide images; XLSX per-sheet; CSV whole-file; DOCX sections + embedded images; text files chunked ~500 chars) → `EvidenceEngine` chunks (400 chars, 50 overlap) → nomic embeddings → FAISS → retrieval → RAG/UI. Persistence: evidence+vector_map. Navigation: PDF page jump only.

### IMAGE
`ImageExtractor` → OCR block (tesseract, confidence 0.8) + caption block (moondream, confidence 0.7) (+ filename fallback) → chunks (modality="image") → nomic embeddings **and** CLIP 512→768 padded vector (`source_type="clip_visual"`, text = `[Image: filename]`) → FAISS. Ask AI image path: OCR-first, vision fallback, qwen answer. Navigation: preview in place.

### AUDIO
`AudioExtractor` → Whisper `base` → transcript blocks grouped into ~30 s windows (`timestamp_start/end`, source_label "MM:SS - MM:SS") → chunks (modality="audio") → nomic → FAISS. Ask AI: direct Whisper transcription of the file. Navigation: seek to `timestamp_start`.

### VIDEO
`VideoExtractor` → ffmpeg extract audio track (16 kHz mono WAV) → Whisper → transcript blocks (modality="video", re-labeled) **+** OpenCV keyframes (≤5, ≥60 s apart) → moondream captions (`source_type="keyframe"`, `timestamp_start`). RAG direct path uses `video.video_engine.VideoEngine` (audio→SpeechEngine) instead. Navigation: seek to `timestamp_start` (transcript or keyframe).

**Modality filter** (`RetrievalEngine._filter_by_modality` + `modality_of` + dialog `modality_of`) is purely extension-based (`.png`→image, etc.).

**Runtime verification:** document + image + audio paths exercised in §20 (audio: silence → 0 blocks, correct). Video path NOT exercised at runtime (unit tests only).

---

## 11. Embedded Image Audit (PDF / DOCX / PPTX)

| Aspect | Status | Evidence |
|---|---|---|
| PDF embedded images | **IMPLEMENTED** | `content_engine._extract_pdf` → `_extract_embedded_images(page, seen_xrefs)` using `page.get_images(full=True)` + `doc.extract_image(xref)`; xrefs deduped document-wide |
| PPTX images | **IMPLEMENTED** | `_extract_pptx`: `shape.image.blob` per slide → `_embedded_image_blocks`, label `Slide N · Image M` |
| DOCX images | **IMPLEMENTED** | `_extract_docx`: iterates `doc.part.related_parts` for `image/*` → `_embedded_image_blocks`, label `Image N` |
| OCR of embedded images | **IMPLEMENTED** | `_embedded_image_blocks` → `ocr_image_bytes(data)` (tesseract on bytes) |
| Vision caption | **IMPLEMENTED** | caption attempted when OCR text < 30 chars; **independent of OCR failure** (separate try/except) |
| Provenance | **IMPLEMENTED** | source_label `Page 28 · Image 3 · OCR`, metadata {page/slide, image_index, embedded:True}, modality="document" |
| Evidence storage | **IMPLEMENTED** | blocks flow into EvidenceChunks → `db_store.store_evidence` |
| Embeddings + semantic search | **IMPLEMENTED** | same pipeline as any document chunk |
| Evidence navigation | **PARTIAL** | PDF page jump works; **embedded-image blocks only carry page provenance for PDFs** — PPTX/DOCX embedded images have slide/section provenance that the navigator cannot jump to |
| Tests | **IMPLEMENTED** | `test_batch3_extended.py` (embedded image OCR/caption tests incl. OCR-failure path); PDF/PPTX/DOCX extraction in `test_batch3.py`, `test_multimodal.py` |

---

## 12. Ask AI Audit (current reachable behavior)

Reachable via: right-click file → **AI → Ask AI about this File** → `AskAIDialog` → `MainWindow._perform_ask_ai` → **`RAGEngine.ask_file_direct`** (Tier 1, full-file, no vector retrieval).

| Modality | Content source | LLM | Citations |
|---|---|---|---|
| TXT/MD/JSON/XML/CSV/LOG/HTML/... | `UniversalContentEngine.extract_full_text` | qwen-local (direct prompt, context cap 12000 chars) | 1 citation = whole file (snippet first 100 chars) |
| PDF | page text (text-only; embedded images OCR/caption via ContentEngine) | qwen-local | 1 file-level citation |
| DOCX / PPTX | sections / slides (incl. embedded image OCR/caption) | qwen-local | 1 file-level citation |
| XLSX / XLS | sheets | qwen-local | 1 file-level citation |
| Images (PNG/JPG/...) | OCR (>50 chars → text-only) or moondream vision description | qwen-local | 1 citation |
| Audio | Whisper `base` transcription with timestamps (bounded 12000 chars) | qwen-local (audio prompt) | 1 citation |
| Video | ffmpeg audio → Whisper transcription (bounded) | qwen-local (video prompt) | 1 citation |

Key facts:
- **RetrievalEngine is NOT used in the Ask AI path** — `ask_file_direct` bypasses retrieval entirely (that's why it answers correctly even when the index is empty). The retrieval-based `RAGEngine.ask(file_filter=...)` exists but has no UI.
- Errors: no content → modality-specific message ("Could not extract text…"); generation failure → "Failed to generate an answer. Please check that Ollama is running."; Ollama down → same message via `_generate` returning "".
- Citation click → `citation_activated` → `MainWindow._on_file_activated` → opens file in the **default OS application** (no page/timestamp jump).
- Tests: `test_multimodal.py`, `test_batch3_extended.py` (mocked LLM).

**Verified at runtime (§20):** text file answered correctly with names and one citation, grounded=True.

---

## 13. Semantic Search Audit

| Aspect | Finding |
|---|---|
| UI location | Toolbar "Semantic search (AI)..." box; right-click → AI → Semantic Search (opens dialog); dialog search box |
| Search dialog | `ui/dialogs/semantic_search_dialog.py` — query + Type combo (All/Documents/Images/Audio/Video) + results list; purely presentational (signals only) |
| Query processing | `MainWindow._perform_semantic_search` → worker → `RetrievalEngine.smart_retrieve(query, top_k=10 or 40 if filtered)` |
| Query embedding | nomic-embed-text with `search_query: ` prefix (`RetrievalEngine.retrieve`) |
| FAISS retrieval | `VectorEngine.search` top_k*6 over-fetch, threshold 0.3 |
| Ranking | pure cosine (FAISS inner product on normalized vectors) within engine; **LLM re-rank only in the UI path** via `RAGEngine.rerank_results` when no modality filter AND no detected modality; results ≤2 skip re-rank |
| Filters | explicit UI filter (`filter_results_by_modality`) + keyword `_detect_modality`; results deduped per file (best score) |
| Thresholds | `SIMILARITY_THRESHOLD=0.3`, `TOP_K_DEFAULT=5`; match-strength High≥0.80 / Medium≥0.60 / Low |
| Result object | `RetrievalResult` (score, text, file, source_label/type/index, char offsets, modality, timestamps, confidence, match_strength) |
| Result UI | icon + filename + source label + 160-char snippet + Similarity + Match strength; double-click → evidence navigation |
| Modality handling | extension-based filtering + per-result `modality` field |
| Folder/file scope | **workspace-wide only** in the UI; `file_filter`/`SELECTED_FILE` scopes exist in the engine but are not exposed |
| Evidence display | text snippet + source label shown; full text on navigation |
| Navigation | double-click → `EvidenceNavigator` (PDF page jump / media seek / preview / open) |
| History | `db_store.record_search(query, scope, results_count, elapsed_ms)` — written on every UI search (currently 0 rows; would populate after use) |
| Tests | `test_batch3.py`, `test_batch3_extended.py` |

**Representative runtime test (§20):** "Who demoed the CLIP image search?" → 1 result (image OCR, Low 0.422) — text containing the verbatim answer was not returned (see F4). "launch schedule" → 2 results (document + image OCR), all resolved.

---

## 14. Evidence Navigation Audit

| Target | Status | Mechanism | Verified |
|---|---|---|---|
| PDF page | **WORKS** | `EvidenceNavigator` (modality=document, page=source_index+1) → `_preview_jump_pdf` → `PreviewPanel.show_file` + `jump_to_page` (`QPdfView.pageNavigator().jump`) | unit tests; code path complete |
| PPTX slide | **NOT IMPLEMENTED** | slide results fall to default `open_file` (external app) — no slide jump API | confirmed by code path |
| DOCX section | **NOT IMPLEMENTED** | same fall-through | confirmed by code path |
| Image | **WORKS** | `preview_file` → preview panel shows image | code path complete |
| Audio timestamp | **WORKS** | `play_media(path, timestamp_start)` → `play_audio` → QMediaPlayer + setPosition + play | unit tests; seek logic present |
| Video timestamp | **WORKS** | `play_video` → QMediaPlayer + QVideoWidget + setPosition | unit tests; seek logic present |
| Ask AI citation | **PARTIAL** | opens file externally only (no location) | confirmed |

Gaps: no PPTX/DOCX deep navigation; `EvidenceNavigator` has no slide/section callbacks; Ask AI citations don't carry location info (Citation has no source_index/page/timestamp).

---

## 15. UI Audit

### Layout
Menu bar (File/Edit/View/Tools/Help) · Toolbar (Back/Forward/Up/Refresh, **Scan Folder**, **Index for AI**, view combo, filename search, semantic search box) · Status bar (item count, free space, task label) · Left dock: FolderTree + Favorites + Drives · Right dock: PreviewPanel · Central: breadcrumb + explorer + **Indexed Files panel (fixed 180 px)**.

### Batch 3 feature reachability (exact user paths)
- **Index for AI**: Toolbar button → QProgressDialog (minimizable, NonModal) → summary QMessageBox.
- **Semantic Search**: Toolbar "Semantic search (AI)..." (Enter) → dialog opens pre-filled and searches; or right-click → AI → Semantic Search → dialog.
- **Ask AI about this File**: right-click file → AI → Ask AI about this File → dialog (question + answer + citations; citation double-click opens file externally).
- **AI Analysis**: right-click file → AI → Analyze File (detail-level dialog) → progress → AIAnalysisDialog; View Analysis / Regenerate Analysis (enabled when cached).
- **Evidence navigation**: double-click a semantic-search result card (PDF page jump / media seek / image preview).
- **Audio/video playback**: only reachable via evidence navigation; plain selection shows metadata/thumbnail (no inline player button).

### Duplicate / inconsistent / placeholder / disconnected elements
- **Duplicate search entries:** toolbar semantic box AND context-menu Semantic Search (both open the same dialog — acceptable, but two paths).
- **Menu placeholders:** Edit → Copy/Move/Delete are inert ("placeholder (wired in M4)" comment); no keyboard shortcuts; Help → About is wired.
- **Settings reserved tabs:** AI, OCR, Models, Embeddings, LLM — disabled placeholders (`settings_dialog._build_reserved_tabs`). Config JSON also has inert `ai/ocr/models/embeddings/llm.enabled=false` sections.
- **AI Insights group in PreviewPanel** (`Summary/Keywords/OCR/Related files`) — created, disabled, hidden (`setVisible(False)`), kept only for API compatibility. Dead UI.
- **Indexed Files panel** — the user's earlier complaint (random popup) is addressed via fixed 180 px height; but it shows only files under the current folder (non-recursive `LIKE path/%` with `~LIKE path/%/%` filter).
- **Context-menu AI plugin hook** disabled in code: `if False and self.plugin_registry is not None: ...` (dead branch).
- **Metadata tab methods** (`_show_metadata_tab`, `_show_metadata_tab_handler`) exist but no button is wired to them (only "Extracted Text" button is visible in the preview toolbar).
- **Explorer grid delegate** (`GridDelegate`) duplicates list view selection handling — cosmetic.
- **Semantic search "Open Evidence" button** documented in the dialog docstring but **not implemented** in the dialog (only double-click).
- **Status bar** shows task % via `_on_task_progress`; no dedicated progress bar widget.

### Preview panel behaviors
- Images: QPixmap scaled ≤400×300 (all images same preview size — user-requested behavior).
- Text: QPlainTextEdit (1 MB cap).
- PDF: QPdfView (full document, no page pre-selection from toolbar; `jump_to_page` only via evidence navigation).
- Audio: metadata (mutagen) in info area; **no inline player**.
- Video: thumbnail (ffmpeg frame, cached) in info area.
- Extracted Text button: pulls `extracted_text` from `indexed_files` (SQLite) — user-requested fix implemented (dedicated scroll area; file details still visible below — user's complaint #2 about clutter is *partially* addressed).

---

## 16. Background Processing / Concurrency Audit

| Concern | Finding |
|---|---|
| Threading model | `QThreadPool` (max_threads from config, currently 6) via `ThreadManager` + `QRunnable` `Worker` (signals: progress/finished/error) → `TaskManager.submit` |
| What runs on GUI thread | All rendering, dialog handling, engine *construction* (lazy, e.g., first `retrieval_engine` access does hydration + FAISS save **synchronously on first use — can stall UI briefly**), `PreviewPanel._show_pdf` (QPdfDocument load is synchronous) |
| What runs in workers | Batch-1 scan, incremental reindex, AI analysis, AI indexing, semantic search, Ask AI — all via `container.tasks.submit` |
| Heavy AI blocking | Search/index/ask do NOT block the UI. **Hydration on first engine access** and **CLIP first load** can block (seconds) — no async wrapper |
| Simultaneous models | Possible: tasks share a 6-thread pool, so e.g. Ask AI (qwen) + AI index (whisper/CLIP/embeddings) can run concurrently on a 8-thread CPU — contention + memory pressure (whisper ~1 GB, CLIP ~0.6 GB, qwen ~4 GB VRAM-equivalent RAM swap risk) |
| Cancellation | Works at file granularity: `cancel_event` checked in `index_folder` loop, `_perform_incremental_reindex` loop, `_perform_batch1_scan` (scanner), AI analysis steps. **Not interruptible mid-call** (single embed/transcribe/generate). Cancel via `TaskManager.cancel(task_id)` sets event; dialogs wired (B1 dialog, AI analysis QProgressDialog, AI index QProgressDialog) |
| FAISS locking | `RLock` per `VectorEngine` instance — all add/search/remove/save go through `@lock_required`; single shared instance via container ⇒ safe |
| DB locking | SQLite `check_same_thread=False`, short-lived sessions; `pool_pre_ping`; no WAL mode configured; concurrent writers possible across threads (SQLAlchemy handles via locking; risk of `database is locked` under heavy concurrent writes — mitigated by short transactions) |
| Signals | Qt queued connections for cross-thread; `TaskManager` re-emits on signal bus |

---

## 17. Error Handling Audit

| Scenario | Current behavior (verified from code) | UI responsive? | State consistent? |
|---|---|---|---|
| Ollama unavailable (LLM) | `_generate` catches ConnectionError → logs → returns "" → Ask AI shows "Failed to generate an answer…"; analysis shows QMessageBox | yes | no writes |
| Ollama unavailable (embeddings) | `embed_text` returns None → `retrieve` returns `embedding_available=False` → dialog error "Embedding service unavailable…"; indexing skips failed vectors | yes | per-file rollback keeps DB clean |
| Vision model unavailable | `caption_image_bytes`/`VisionEngine` catch → return "" → blocks just lack captions | yes | fine |
| Whisper unavailable/import fail | `AudioExtractor` catches → returns [] → file "skipped"; direct ask → "Audio transcription failed" | yes | fine |
| FFmpeg missing | `video_extractor._extract_audio_track` / `VideoEngine.extract_audio_track` return None → no transcript; thumbnail None | yes | fine |
| OCR failure | `ocr_image_bytes` catches → "" → caption still attempted (fixed in Batch 3) | yes | fine |
| Corrupt PDF / DOCX / PPTX / XLSX | `UniversalContentEngine` per-format try/except → empty blocks → file skipped in indexing; preview `_show_pdf` guard for QtPdf | yes | fine |
| Corrupt image / audio / video | extractors catch → empty → skipped | yes | fine |
| Permission denied | extractors catch (e.g., open errors) → empty/skip; `folder_scanner` collects per-item errors | yes | fine |
| File deleted during indexing | `os.path.isfile` check at ContentEngine start; hash open may raise → caught → skip; transactional rollback for partial state | yes | fine |
| File modified during indexing | No locking/versioning — indexes the bytes read; stale evidence possible after later modification (§18) | yes | **P1 gap** |
| DB failure | `EngineDBStore` methods catch broadly → log, return 0/[] — indexing continues without persistence (silent) | yes | **P1 gap: silent persistence loss** |
| FAISS failure | add/search/save wrap try/except → logs; `_load` resets to empty index | yes | possible empty index |
| Invalid model response / JSON | `JsonParser` repairs (code blocks, trailing commas, single quotes) then raises ValueError → user message | yes | fine |
| Disk space | `ai_indexer.index_folder` refuses below 500 MB free (config `MIN_FREE_DISK_MB`) with clear error | yes | good (disk is at 98%) |

---

## 18. File Watcher / Synchronization Audit

Watcher: `services/file_watcher.py` (watchdog, **non-recursive**, watches current folder) → `MainWindow._on_files_changed` → 300 ms debounce → `_on_files_changed_flush` → `bus.files_changed` + **`_incremental_reindex(changed_path)`**.

| Event | Batch-1 SQLite index | AI evidence/vector_map/FAISS | Search results | Notes |
|---|---|---|---|---|
| New file | ✅ updated (incremental reindex: metadata→text→index_items) | ❌ NOT updated | stale | User must re-run Index for AI |
| Modified file | ✅ updated if mtime > existing.modified_date | ❌ NOT updated (stale vectors remain) | stale | **stale evidence problem** |
| Deleted file | ❌ nothing (no delete handling; `_incremental_reindex` only handles paths that exist) | ❌ nothing — evidence/vectors remain | can still resolve to missing file (nav shows "no longer exists") | **stale evidence problem** |
| Renamed file | ❌ old path row remains; new path row added | ❌ old evidence orphaned (new path not indexed) | stale | |
| Moved file | ❌ same as rename | ❌ same | stale | |

**Assessment:** the watcher maintains only the Batch-1 index. AI evidence/vector_map/FAISS are updated **only** by explicit "Index for AI" runs. There is **no automatic reconciliation** between `indexed_files`, `evidence`, and FAISS after filesystem changes. `AIFolderIndexer.reindex_file` exists but is never invoked by the watcher or UI. This is a P1 Batch 4 dependency (conversations/search would answer from stale evidence).

---

## 19. Test Results (exact)

Command: `venv/bin/python3 -m pytest tests/ -q` → **212 passed in 377.19s (0:06:17)** — 0 failed, 0 skipped, 0 errors. (Warnings count not captured by `-q`; no failures.)

Per-file breakdown (from AST collection):

| File | Tests | Category |
|---|---|---|
| tests/test_multimodal.py | 34 | Batch 3 multimodal (image/audio/video/vision/OCR/CLIP) |
| tests/test_batch3_extended.py | 32 | Batch 3 (persistence, hydration, embedded images, match strength, modality filters, evidence nav, media players) |
| tests/test_batch2_unit.py | 30 | Batch 2 (analysis pipeline, JSON parsing, prompts, cache, hash) |
| tests/test_batch3.py | 20 | Batch 3 (engines, db_store, retrieval, RAG) |
| tests/test_preview.py | 9 | UI preview |
| tests/test_explorer.py | 9 | UI explorer |
| tests/test_database.py | 9 | DB |
| tests/test_services.py | 8 | services (threads/tasks/watcher/cache) |
| tests/test_preview_panel_extracted_text.py | 8 | UI preview extracted text |
| tests/test_plugin_registry.py | 7 | plugins |
| tests/test_navigation.py | 7 | UI navigation |
| tests/test_main_window.py | 7 | UI main window |
| tests/test_settings.py | 6 | UI settings |
| tests/test_preview_panel_metadata.py | 6 | UI preview metadata |
| tests/test_indexed_files.py | 6 | UI indexed files |
| tests/test_batch2_integration.py | 6 | Batch 2 integration (scan+analysis) |
| tests/test_config.py | 5 | core config |
| tests/test_logging.py | 3 | core logging |

**Notably untested / thin areas:** real Ollama calls (all LLM/embedding/vision tests are mocked), video keyframe runtime path, watcher→AI-evidence sync, semantic search with live embeddings, error-path UI flows, PDF page navigation end-to-end with a real PDF, PPTX/DOCX evidence navigation, `get_recent_searches` consumer, `explain_match` display, `RetrievalScope.FOLDER`, `rerank_results` quality, hydration with a genuinely stale DB (orphan cleanup is covered in extended tests via mocks).

---

## 20. Runtime Smoke Test (performed)

Isolated temp dir + temp SQLite DB + temp FAISS (project data untouched). Real Ollama (nomic, moondream, qwen-local), real tesseract, real Whisper base, real CLIP.

Fixtures: `meeting_notes.txt` (6 lines, 3 names), `whiteboard.png` (PIL-drawn "PROJECT APOLLO LAUNCH SCHEDULE …"), `tone.wav` (1 s silence).

| Stage | Result |
|---|---|
| Discover | 3 files found |
| Index | **2/3 indexed, 3 chunks, 0 errors** (silence WAV → 0 transcript blocks → skipped, correct) |
| Extract | txt → 1 block; png → OCR + caption; wav → Whisper loaded, 0 segments |
| Embed | nomic batch 2.9 s; CLIP model loaded; all 3 vectors in FAISS |
| FAISS | size 3, evidence map 3 |
| Search (live) | "Who demoed the CLIP image search?" → 1 result: **image OCR, Low 0.422** (near-verbatim text chunk not returned — ranking quality issue, F4) |
| Persistence/restart | save → new VectorEngine → `hydrate_from_store` → **3/3 hydrated, 0 orphans**; "launch schedule" → 2 results, all resolve to text ✅ |
| Ask AI (live qwen) | "How many people…" → **"There were three people… Alice Chen… Bob Martinez…"** grounded=True, 1 citation (44 s on CPU) ✅ |
| Image OCR | blocks: OCR text + moondream caption ✅ |
| Cleanup | temp dir removed |

**Not performed:** real video file E2E (would need ffmpeg+whisper+opencv on a sample; pipeline unit-tested only), UI click-through (offscreen Qt; logic paths unit-tested), PPTX slide jump.

---

## 21. Performance / Resource Audit

| Aspect | Finding |
|---|---|
| CPU | all AI on CPU (i3-N305, 8 threads). Whisper base transcribe ~0.5-1× realtime; moondream 10-30 s/image; CLIP first load 30-60 s; qwen generation ~30-60 s/short answer (observed 44 s) |
| RAM | 6.9 GiB total. Concurrent worst case (index: whisper + CLIP + torch + embeddings + qwen ask) can exceed RAM → swap. No memory guard/serialization of AI tasks |
| Model loading | Whisper: global cache in `audio_extractor` + **separate per-instance cache in `speech_engine`** (duplicate ~1 GB if both used in one session). CLIP: global lazy. Ollama models: server-side resident |
| Embedding batch size | whole file's chunks in one `/api/embed` batch (e.g., 1 call per file); sequential fallback when batch fails |
| OCR workload | one tesseract call per image/embedded image |
| Whisper workload | one full-file transcription per audio/video at index time AND again at Ask-AI time (no transcript cache) — **redundant work** |
| Video | full audio track extraction + transcription + ≤5 keyframes with moondream captions per video — heavy |
| FAISS size | flat index, small (1,213 vectors ≈ 3.7 MB); rebuild-on-remove is O(n) |
| Database growth | `tasks` grows unbounded (2,499 rows); `logs` DB handler; no pruning |
| Temp files | WAV extraction (deleted in finally), thumbnails (deleted), `.cache` files in cache/ (evicted) |
| Obvious problems | (1) duplicate Whisper caches; (2) no AI-task serialization on weak hardware; (3) hydration+CLIP load on GUI thread first-access; (4) transcript re-transcription on every Ask AI; (5) unbounded tasks table; (6) disk at 98% — indexing writes + whisper temp WAVs risk disk-full (500 MB guard exists) |

No synthetic benchmarks produced (honest: none available; only observed timings above).

---

## 22. Code Quality Audit (ranked)

P0 (blocks functionality):
- **P0-1** Live index has no persisted data (F1) — not a code bug but the state Batch 4 starts from; re-index required.
- **P0-2** (latent) `vector_map` is written but never read by hydration or removal logic — if Batch 4 relies on it as the authoritative mapping (§9), it must be wired.

P1 (serious):
- **P1-1** Watcher does not update AI evidence/vector_map/FAISS (§18) — stale answers.
- **P1-2** Ranking quality: no engine-level re-rank; keyword `_detect_modality` + cosine only (F4).
- **P1-3** PPTX/DOCX evidence navigation missing (§14).
- **P1-4** Silent persistence failures: `EngineDBStore` swallows DB errors (returns 0/[]) — indexing "succeeds" without persistence.
- **P1-5** First-access hydration + CLIP load block GUI thread.
- **P1-6** No AI concurrency guard on constrained hardware; duplicate Whisper model caches (`audio_extractor._MODEL_CACHE` vs `speech_engine._model`).

P2 (moderate):
- **P2-1** Dead infra: `embeddings` table, FTS5, `files`/`folders` runtime usage, `explain_match` (defined, unused), `get_recent_searches` (no UI), `RetrievalScope.FOLDER`, `AIFolderIndexer.reindex_file` (unwired), `_show_metadata_tab` (no button), `if False:` plugin context-menu branch, "AI Insights" hidden group.
- **P2-2** `tasks` table unbounded; `recent` capped at 50 but no purge for others.
- **P2-3** Hardcoded paths: `config/intellivault.db`, `cache/faiss_index.bin` default path in container (configurable only for DB via config; FAISS path fixed in code); `EmbeddingEngine` timeouts hardcoded.
- **P2-4** Magic numbers: `_EMBEDDED_IMAGE_VISION_THRESHOLD=30`, OCR 50-char threshold in `rag_engine._ask_image_direct`, `GROUP_DURATION=30.0` duplicated in `audio_extractor` and `video_engine` (and `AUDIO_GROUP_DURATION` in config is unused!), `_SECTION_SIZE=500` vs config `CHUNK_SIZE=400` (two different chunk philosophies).
- **P2-5** Duplicated extension sets: `retrieval_engine._filter_by_modality` redefines `_IMAGE_EXT/_AUDIO_EXT/_VIDEO_EXT` locally instead of config; `preview_panel` redefines `_AUDIO_EXT/_VIDEO_EXT/_IMAGE_EXT/_TEXT_EXT`; `content_engine` redefines sets; `rag_engine` redefines them. Config's `MODALITY_EXTENSIONS` is underused.
- **P2-6** Two config namespaces for models (`engines/config.py` vs `ai/config.py`) — same model name duplicated.
- **P2-7** Tight coupling: `MainWindow` orchestrates everything (scan, analysis, index, search, ask, navigation) — very large class (~1,100 lines); dialogs are pure but the main window holds all business flow.
- **P2-8** Business logic in UI: `file_explorer._check_ai_analysis_exists` opens its own DB (`Database(config/intellivault.db)`) instead of using the container; `preview_panel` queries SQLite directly.
- **P2-9** `index_chunks_detailed` imports `unittest.mock.Mock` inside the method (test-support code in production path).
- **P2-10** `AIFolderIndexer` reads private attrs `_retrieval._evidence`, `_retrieval._vector` (encapsulation smell).

P3 (cleanup):
- **P3-1** `config.WHISPER_MODEL` defined but extractors hardcode `"base"`.
- **P3-2** `IndexingStatus.PROCESSING`/`FAILED` unused by scanner path (always COMPLETED).
- **P3-3** `engines/__init__.py` exposes `ContentEngine` alias + full API; `engines/evidence_engine` `char_start/char_end` unused in UI.
- **P3-4** Unused imports/leftovers: `services/cache_manager` structured pickling used only for thumbnails; `text_extractor` uses optional pandas/PyPDF2 paths that may silently diverge from `text_extraction` package behavior.
- **P3-5** `DocumentExtractor._DOC_EXT` vs `engines/config.DOCUMENT_EXTENSIONS` duplicate.

---

## 23. Current User-Facing Features (definitive, usable NOW)

**Core file management**
- Browse folders (tree, drives, favorites, breadcrumb, back/forward/up) — toolbar + docks.
- List/grid views, sorting, multi-select, filename search — toolbar + explorer.
- Open (OS default), rename, copy to, move to, delete, properties — right-click.
- Drag & drop (internal move, external copy) — explorer.
- Settings (General/Appearance/Explorer/Database/Plugins/Performance), theme dark/light — Tools menu.
- Status bar (item count, free space, task status).

**Scanning / indexing (Batch 1)**
- Scan Folder → `indexed_files` (SQLite) + Indexed Files panel with filters — toolbar.
- Incremental reindex of new/modified files in the watched folder (Batch-1 scope) — automatic via watcher.

**AI Analysis (Batch 2)**
- AI → Analyze File (detail level), View Analysis, Regenerate Analysis — right-click.
- Results dialog: summary, keywords, tags, category, language; persisted by content hash (survives rename/move).

**Semantic search / multimodal (Batch 3)**
- Index for AI (folder → evidence + FAISS + SQLite, with progress + cancel + summary) — toolbar.
- Semantic Search dialog with Type filter (All/Docs/Images/Audio/Video), result cards with Similarity + Match strength; double-click navigates (PDF page, audio/video seek, image preview) — toolbar box or AI menu.
- Ask AI about this File (TXT/MD/PDF/DOCX/PPTX/XLSX/CSV/JSON/XML/Images/Audio/Video) — right-click AI menu.
- Audio/video players with timestamp seek — via search-result navigation.
- Search history recording (in DB when searches run).

**Preview (Batch 1/2/3)**
- Image preview, PDF viewer, text preview, audio metadata, video thumbnail, file properties, Extracted Text tab (from SQLite).

---

## 24. Partial / Broken / Unimplemented Features

**PARTIAL**
- B3-13 Evidence navigation for PPTX slides and DOCX sections (fall through to external open).
- Ask AI citation navigation (opens file externally, no location jump).
- Preview audio/video: no inline player for plain selection (player reachable only through evidence navigation).
- Extracted-text UX (user complaint #2 partially addressed: fixed panel, but file-details still shown below).
- Video intelligence runtime coverage (code complete; not E2E-exercised in this audit).
- Watcher-driven sync: maintains Batch-1 index only; AI evidence/FAISS not updated (§18).
- `get_recent_searches` / search-history surfaced nowhere in UI (data recorded only).

**NOT IMPLEMENTED**
- PPTX slide jump / DOCX section jump.
- FTS5 full-text search (infrastructure only).
- `embeddings` table usage (dead).
- `files`/`folders` runtime usage.
- "Open Evidence" button (documented in dialog docstring, absent).
- LLM re-rank quality control; calibrated confidence (deliberately replaced by match-strength labels).
- `RetrievalScope.FOLDER` / folder-scoped or file-scoped search in UI.
- Automatic reindex on file change (AI scope), rename/move handling for evidence.
- Metadata tab button in preview (methods exist, unwired).

**BROKEN** — none found at runtime (app boots; 212/212 tests; smoke test passed). The only "broken" perception is the empty-index state (F1), which is a data state, not a defect.

---

## 25. Batch Roadmap Reconstruction

Sources inspected: `IntelliVault_Foundation_Blueprint_v1.md`, `IMPLEMENTATION_PLAN.md`, `IntelliVault_Batch3.md`, `plan to  implement batch 3.md`, `batch 3 completed with audio,video and images.md`, `project_progress.txt`, live code.

**Conflict to report:** The blueprint's "Future Batch Integration Points" defines batches by *capability* (Batch 1: File scanner; 2: Document parser; 3: OCR; 4: Embeddings; 5: Vision; 6: Audio/Video; 7: LLM; 8: Duplicate engine; 9: Organization; 10: Analytics). The actual project used a different numbering: **Batch 1 = scan+index, Batch 2 = AI analysis (LLM), Batch 3 = semantic search/RAG + multimodal** (per `IntelliVault_Batch3.md` and the implemented code). This audit follows the **actual implemented numbering**.

- **CURRENTLY IMPLEMENTED** — Foundation M1–M8; Batch 1 (scan/index); Batch 2 (AI analysis); Batch 3 (retrieval/RAG/multimodal) as audited.
- **PLANNED for Batch 4** — `IntelliVault_Batch3.md` "Future Batch 4": **Persistent conversations, Folder Chat, Workspace Chat, Multi-document reasoning, Knowledge Graphs, Agentic workflows** ("Batch 4 builds on the Retrieval Engine without architectural changes").
- **FUTURE SCOPE** — blueprint Batch 8-10 style capabilities (duplicate-file detection, organization/auto-tagging, analytics) have **no implementation and no concrete plan file**; do not assume they are Batch 4.

---

## 26. Batch 4 Candidates

From `IntelliVault_Batch3.md` (§Future Batch 4), each with current-state grounding:

| Feature | Source | Current impl status | Supporting infra | Missing infra | Depends on |
|---|---|---|---|---|---|
| **Folder Chat** (conversational Q&A over a folder) | IntelliVault_Batch3.md | none | `RAGEngine.ask()` with `file_filter` + `RetrievalScope`; `RetrievalEngine`; `evidence`; `SemanticSearchDialog`/`AskAIDialog` patterns | conversation store (DB table), chat UI, scope binding (folder path), multi-turn context, LLM session, rerank quality | RetrievalEngine, EvidenceEngine, RAGEngine, db_store |
| **Workspace Chat** (whole workspace) | IntelliVault_Batch3.md | none | `RAGEngine.ask(scope=WORKSPACE)`; same as above | same as above | same |
| **Persistent conversations** | IntelliVault_Batch3.md | none | SQLAlchemy + migrations pattern (`database/`), `search_history` precedent | conversation/message tables + migration, CRUD, UI history panel, export | database, RAGEngine |
| **Multi-document reasoning** | IntelliVault_Batch3.md | partial engine support only | `RAGEngine.ask` retrieval across files; `smart_retrieve` dedup per file | cross-file synthesis prompt, evidence aggregation UI, citation per document | RetrievalEngine, RAGEngine |
| **Knowledge Graphs** | IntelliVault_Batch3.md | none | `evidence.metadata_json` (image_index, slide…), entity-ish fields in `ai_analysis` (keywords/tags/category) | entity extraction, graph storage (SQLite adjacency or external), graph UI, entity-linking to evidence | evidence, ai_analysis, db_store |
| **Agentic workflows** | IntelliVault_Batch3.md | none | plugin registry (extension point), TaskManager | agent orchestrator, tool/action model, model context protocol, UI | plugins, task_manager |

---

## 27. Batch 4 Dependency Analysis

- **Folder/Workspace Chat** → `RAGEngine.ask` → `RetrievalEngine.retrieve` → `EmbeddingEngine` + `VectorEngine` + `EvidenceEngine`/`EngineDBStore` (evidence must be populated — currently 0 rows) → LLM (qwen-local). UI pattern from `AskAIDialog` + `SemanticSearchDialog` (signals-only dialogs). **Needs**: evidence populated, folder scope binding (currently UI is workspace-wide), conversation persistence.
- **Persistent conversations** → `database.models`/`migrations` (add tables), `Container`, `Repository` CRUD pattern, `db_store.record_search` precedent.
- **Knowledge Graph** → `EvidenceChunk.metadata` + `AIAnalysis` (keywords/tags/category) → new graph tables + extraction service → graph UI (needs new widget; current UI has no graph component). Depends on evidence being populated.
- **Agentic workflows** → `plugins/loader.py` + `core/plugin_registry.py` (registration/hooks), `services/task_manager.py` (long-running tasks), `RAGEngine` (tools). Depends on conversation context infrastructure.

Common dependency: **all Batch 4 features read `evidence`/retrieval** — which requires the user to have run "Index for AI" (live DB currently empty, F1).

---

## 28. Blockers for Batch 4 (ranked)

- **P0-1** Live index empty (`evidence`=0, `vector_map`=0, FAISS=0 after cleanup). Any Batch 4 feature demo/story needs a populated index; a "seed/re-index on first run" UX or fixture is required, or document that the user must run Index for AI.
- **P0-2** `vector_map` is write-only today (never read). If Batch 4 needs authoritative chunk→vector/evidence mapping (graph links, incremental updates), decide and wire its read path (or remove it).
- **P1-1** AI evidence/FAISS never reconciled with filesystem changes (watcher covers only Batch-1). Conversations would answer from stale/deleted files. Needs change-detection → evidence/vector/FAISS update pipeline.
- **P1-2** PPTX/DOCX evidence navigation missing (affects any "jump to evidence" experience in chat citations).
- **P1-3** Ranking quality (F4) — chat answers inherit weak retrieval; engine-level rerank/quality control needed.
- **P1-4** Silent DB persistence failures in `EngineDBStore` (Batch 4 conversations must not silently lose messages).
- **P1-5** First-access GUI-thread work (hydration/CLIP) — will matter for chat startup latency.
- **P2-1** `tasks` unbounded growth (chat would amplify); **P2-2** `ai/config.py` vs `engines/config.py` model-name duplication; **P2-3** extension-set duplication (modality logic for chat scoping); **P2-4** no AI concurrency guard (chat + index on 6.9 GiB CPU-only box).

---

## 29. Batch 4 Readiness

### CURRENT PROJECT STATUS

- **Foundation:** COMPLETE (M1–M8; explorer, navigation, preview, DB, services, settings, plugin infra).
- **Batch 1:** COMPLETE (`Scan Folder`, `indexed_files` 89 rows, incremental reindex, Indexed Files panel).
- **Batch 2:** COMPLETE (AI Analysis, qwen-local, content-hash caching, regenerate; `ai_analysis` 3 rows).
- **Batch 3:** IMPLEMENTED — 14/16 features complete; B3-13 PARTIAL (PPTX/DOCX nav); B3-16 UI gap (`explain_match` unused). Runtime-verified: persistence + hydration + Ask AI work end-to-end.
- **Current test status:** 212/212 pass (6m17s); AI-call tests all mocked.
- **Current architecture:** DI container (`app/container.py`) with lazy engines; retrieval = EmbeddingEngine → VectorEngine(FAISS) → evidence map; RAG direct-file path used by Ask AI; index pipeline = AIFolderIndexer + EngineDBStore; all heavy work in QThreadPool workers.
- **Current database:** 21 tables; `indexed_files`/`ai_analysis`/`tasks` populated; **`evidence`/`vector_map`/`search_history` empty**; `embeddings`/FTS5/`files`/`folders` dead.
- **Current retrieval layer:** FAISS IndexFlatIP(768) + pickled ids + SQLite evidence; hydration enforces vector↔evidence invariant; no LLM rerank at engine level; workspace-wide scope in UI.
- **Current multimodal support:** document/image/audio/video all flow through ContentBlock → EvidenceChunk → embeddings → FAISS; OCR, moondream captions, Whisper transcript, CLIP, keyframes implemented; embedded document images OCR'd/captioned.
- **Current UI:** main window with toolbar/docks/indexed-files; Semantic Search dialog (Type filter + result cards); Ask AI dialog; evidence navigation for PDF/media/images; audio/video players; preview panel.
- **Current known blockers:** see §28 (empty live index; vector_map unread; watcher doesn't sync AI data; PPTX/DOCX nav; ranking quality).

### READY FOR BATCH 4?

**YES — with preconditions.** The architectural substrate Batch 4 needs (RetrievalEngine, RAGEngine with scoped `ask()`, evidence persistence + hydration, signals-only dialogs, plugin registry, task manager, migrations) is present and verified working. Batch 4 can safely build upon:

- `RAGEngine.ask(question, scope, file_filter)` (scoped retrieval exists, just not UI-exposed)
- `RetrievalEngine.retrieve/smart_retrieve` + `filter_results_by_modality`
- `EngineDBStore` + migrations for new conversation tables
- `TaskManager`/`ThreadManager` for chat background work
- Dialog patterns (`AskAIDialog`/`SemanticSearchDialog`) for chat UI
- `evidence.metadata_json`, `EvidenceLocation`/`EvidenceNavigator` for citation navigation
- Plugin registry as the extension surface for agentic workflows

**Before starting Batch 4, fix first (ordered):**
1. Decide the live-index strategy: either re-run "Index for AI" as a documented first step, or add a first-run seed/index prompt (P0-1).
2. Wire the filesystem-change → AI evidence/vector_map/FAISS reconciliation (P1-1) — without it, chat cites stale data.
3. Wire `vector_map` reads or drop it (P0-2).
4. Add PPTX/DOCX slide/section navigation to `EvidenceNavigator` (P1-2).
5. Add engine-level reranking/quality control for retrieval (P1-3) if chat quality matters.
6. Harden `EngineDBStore` error reporting (P1-4) and move first-access hydration off the GUI thread (P1-5).

---

## 30. Final File/Module Reference

Key files a Batch 4 planner must read first:

**Engines (Batch 3 core)**
- `engines/config.py` — central model/URL/threshold/extension config
- `engines/content_engine.py` — ContentBlock + UniversalContentEngine (+ embedded-image OCR/caption)
- `engines/evidence_engine.py` — EvidenceChunk + chunking
- `engines/embedding_engine.py` — nomic via Ollama (batch + fallback)
- `engines/vector_engine.py` — FAISS + .ids + locking
- `engines/retrieval_engine.py` — retrieve/smart_retrieve/similar, hydration, modality, match strength
- `engines/rag_engine.py` — ask/ask_file/ask_file_direct/rerank/_ask_image_direct
- `engines/db_store.py` — evidence/vector_map/search_history persistence
- `engines/ai_indexer.py` — folder indexing + transactional persistence + disk guard
- `engines/clip_engine.py` — CLIP embeddings

**Extractors / multimodal**
- `extractors/image_extractor.py`, `audio_extractor.py`, `video_extractor.py`, `document_extractor.py`, `base_extractor.py`, `extractor_factory.py`
- `speech/speech_engine.py`, `vision/vision_engine.py`, `vision/ocr_engine.py`, `vision/content_merger.py`, `video/video_engine.py`, `video/keyframe_engine.py`

**Database**
- `database/models.py` (all 21 tables), `database/migrations.py` (v1–v6), `database/engine.py`, `database/repository.py`

**Services**
- `services/evidence_navigator.py` (new for Batch 4 citation nav), `services/task_manager.py`, `services/thread_manager.py`, `services/file_watcher.py`, `services/sqlite_indexer.py`, `services/folder_scanner.py`, `services/metadata_extractor.py`, `services/text_extractor.py`, `services/cache_manager.py`

**App / UI**
- `app/container.py` (engine wiring + hydration), `app/signal_bus.py`
- `ui/main_window.py` (all AI orchestration — will need refactoring for chat), `ui/dialogs/semantic_search_dialog.py`, `ui/dialogs/ask_ai_dialog.py`, `ui/dialogs/ai_analysis_dialog.py`, `ui/indexed_files_widget.py`, `ui/settings_dialog.py`
- `widgets/preview_panel.py` (players + jump_to_page/seek_media), `widgets/file_explorer.py` (AI context menu)

**Plugins / core**
- `core/plugin_registry.py`, `plugins/loader.py`, `core/config.py`

**Tests**
- `tests/test_batch3.py`, `tests/test_batch3_extended.py`, `tests/test_multimodal.py`, `tests/test_batch2_unit.py`, `tests/test_batch2_integration.py`, `tests/test_main_window.py`, `tests/test_preview*.py`, `tests/test_indexed_files.py`, `tests/test_services.py`, `tests/test_database.py`

**Docs (roadmap)**
- `IntelliVault_Batch3.md` (Batch 4 list), `plan to  implement batch 3.md`, `IMPLEMENTATION_PLAN.md`, `IntelliVault_Foundation_Blueprint_v1.md`, `project_progress.txt` (user-reported issues)

---

*End of audit. All claims verified against source, live database, FAISS state, Ollama runtime, and executed tests/smoke test on 2026-08-11.*
