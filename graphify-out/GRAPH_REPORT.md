# Graph Report - /home/user/Desktop/mini_project/IntelliScan  (2026-08-02)

## Corpus Check
- cluster-only mode — file stats not available

## Summary
- 1671 nodes · 3643 edges · 87 communities (68 shown, 19 thin omitted)
- Extraction: 80% EXTRACTED · 20% INFERRED · 0% AMBIGUOUS · INFERRED: 745 edges (avg confidence: 0.5)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `34a754d1`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- [[_COMMUNITY_Community 0|Community 0]]
- [[_COMMUNITY_Community 1|Community 1]]
- [[_COMMUNITY_Community 2|Community 2]]
- [[_COMMUNITY_Community 3|Community 3]]
- [[_COMMUNITY_Community 4|Community 4]]
- [[_COMMUNITY_Community 5|Community 5]]
- [[_COMMUNITY_Community 6|Community 6]]
- [[_COMMUNITY_Community 7|Community 7]]
- [[_COMMUNITY_Community 8|Community 8]]
- [[_COMMUNITY_Community 9|Community 9]]
- [[_COMMUNITY_Community 10|Community 10]]
- [[_COMMUNITY_Community 11|Community 11]]
- [[_COMMUNITY_Community 12|Community 12]]
- [[_COMMUNITY_Community 13|Community 13]]
- [[_COMMUNITY_Community 14|Community 14]]
- [[_COMMUNITY_Community 15|Community 15]]
- [[_COMMUNITY_Community 16|Community 16]]
- [[_COMMUNITY_Community 17|Community 17]]
- [[_COMMUNITY_Community 18|Community 18]]
- [[_COMMUNITY_Community 19|Community 19]]
- [[_COMMUNITY_Community 20|Community 20]]
- [[_COMMUNITY_Community 21|Community 21]]
- [[_COMMUNITY_Community 22|Community 22]]
- [[_COMMUNITY_Community 23|Community 23]]
- [[_COMMUNITY_Community 24|Community 24]]
- [[_COMMUNITY_Community 25|Community 25]]
- [[_COMMUNITY_Community 26|Community 26]]
- [[_COMMUNITY_Community 27|Community 27]]
- [[_COMMUNITY_Community 28|Community 28]]
- [[_COMMUNITY_Community 29|Community 29]]
- [[_COMMUNITY_Community 30|Community 30]]
- [[_COMMUNITY_Community 31|Community 31]]
- [[_COMMUNITY_Community 32|Community 32]]
- [[_COMMUNITY_Community 33|Community 33]]
- [[_COMMUNITY_Community 34|Community 34]]
- [[_COMMUNITY_Community 35|Community 35]]
- [[_COMMUNITY_Community 36|Community 36]]
- [[_COMMUNITY_Community 37|Community 37]]
- [[_COMMUNITY_Community 38|Community 38]]
- [[_COMMUNITY_Community 39|Community 39]]
- [[_COMMUNITY_Community 40|Community 40]]
- [[_COMMUNITY_Community 41|Community 41]]
- [[_COMMUNITY_Community 42|Community 42]]
- [[_COMMUNITY_Community 43|Community 43]]
- [[_COMMUNITY_Community 44|Community 44]]
- [[_COMMUNITY_Community 45|Community 45]]
- [[_COMMUNITY_Community 46|Community 46]]
- [[_COMMUNITY_Community 47|Community 47]]
- [[_COMMUNITY_Community 48|Community 48]]
- [[_COMMUNITY_Community 49|Community 49]]
- [[_COMMUNITY_Community 50|Community 50]]
- [[_COMMUNITY_Community 51|Community 51]]
- [[_COMMUNITY_Community 52|Community 52]]
- [[_COMMUNITY_Community 53|Community 53]]
- [[_COMMUNITY_Community 54|Community 54]]
- [[_COMMUNITY_Community 55|Community 55]]
- [[_COMMUNITY_Community 56|Community 56]]
- [[_COMMUNITY_Community 58|Community 58]]
- [[_COMMUNITY_Community 59|Community 59]]
- [[_COMMUNITY_Community 60|Community 60]]
- [[_COMMUNITY_Community 61|Community 61]]
- [[_COMMUNITY_Community 62|Community 62]]
- [[_COMMUNITY_Community 63|Community 63]]
- [[_COMMUNITY_Community 64|Community 64]]
- [[_COMMUNITY_Community 65|Community 65]]
- [[_COMMUNITY_Community 66|Community 66]]
- [[_COMMUNITY_Community 67|Community 67]]
- [[_COMMUNITY_Community 68|Community 68]]
- [[_COMMUNITY_Community 69|Community 69]]
- [[_COMMUNITY_Community 82|Community 82]]
- [[_COMMUNITY_Community 89|Community 89]]
- [[_COMMUNITY_Community 90|Community 90]]
- [[_COMMUNITY_Community 91|Community 91]]
- [[_COMMUNITY_Community 92|Community 92]]
- [[_COMMUNITY_Community 93|Community 93]]
- [[_COMMUNITY_Community 94|Community 94]]
- [[_COMMUNITY_Community 95|Community 95]]
- [[_COMMUNITY_Community 96|Community 96]]
- [[_COMMUNITY_Community 97|Community 97]]
- [[_COMMUNITY_Community 98|Community 98]]

## God Nodes (most connected - your core abstractions)
1. `MainWindow` - 105 edges
2. `Container` - 80 edges
3. `ContentBlock` - 70 edges
4. `UniversalContentEngine` - 56 edges
5. `Repository` - 51 edges
6. `PreviewPanel` - 50 edges
7. `Database` - 49 edges
8. `IndexedFilesWidget` - 44 edges
9. `RetrievalEngine` - 43 edges
10. `VectorEngine` - 41 edges

## Surprising Connections (you probably didn't know these)
- `AICacheManager` --uses--> `AIAnalysis`  [INFERRED]
  ai/cache_manager.py → database/models.py
- `Container` --uses--> `AICacheManager`  [INFERRED]
  ui/main_window.py → ai/cache_manager.py
- `MainWindow` --uses--> `AICacheManager`  [INFERRED]
  ui/main_window.py → ai/cache_manager.py
- `_DragDropList` --uses--> `AICacheManager`  [INFERRED]
  widgets/file_explorer.py → ai/cache_manager.py
- `_DragDropTable` --uses--> `AICacheManager`  [INFERRED]
  widgets/file_explorer.py → ai/cache_manager.py

## Import Cycles
- 1-file cycle: `database/repository.py -> database/repository.py`
- 2-file cycle: `database/models.py -> database/repository.py -> database/models.py`
- 3-file cycle: `database/engine.py -> database/models.py -> database/repository.py -> database/engine.py`
- 4-file cycle: `database/engine.py -> database/migrations.py -> database/models.py -> database/repository.py -> database/engine.py`
- 4-file cycle: `database/engine.py -> database/migrations.py -> services/sqlite_indexer.py -> database/repository.py -> database/engine.py`
- 5-file cycle: `database/engine.py -> database/migrations.py -> services/sqlite_indexer.py -> database/models.py -> database/repository.py -> database/engine.py`
- 5-file cycle: `database/engine.py -> database/migrations.py -> services/sqlite_indexer.py -> services/folder_scanner.py -> database/repository.py -> database/engine.py`
- 5-file cycle: `database/engine.py -> database/migrations.py -> services/sqlite_indexer.py -> services/metadata_extractor.py -> database/repository.py -> database/engine.py`
- 5-file cycle: `database/engine.py -> database/migrations.py -> services/sqlite_indexer.py -> services/text_extractor.py -> database/repository.py -> database/engine.py`

## Communities (87 total, 19 thin omitted)

### Community 0 - "Community 0"
Cohesion: 0.05
Nodes (55): Base, Database, SQLAlchemy engine and session management.  Creates the SQLite database at the co, add_embedding_table(), add_fts5_index(), get_current_version(), init_database(), Database migration system with FTS5 and vector schema support. (+47 more)

### Community 1 - "Community 1"
Cohesion: 0.04
Nodes (47): AIFolderIndexer, IndexingProgress, IndexingResult, RetrievalEngine, AI Folder Indexing Engine.  Scans a directory and indexes all supported files fo, Index all supported files in a folder.          Args:             folder_path: P, Index a single file into the retrieval engine.          Args:             file_p, Index a text-based document. (+39 more)

### Community 2 - "Community 2"
Cohesion: 0.05
Nodes (52): KeyframeEngine, Check if Whisper is available.          Returns:             True if whisper can, Transcribes audio using OpenAI Whisper (local, CPU).      Supports configurable, Initialize the speech engine.          Args:             model_size: Whisper mod, SpeechEngine, SpeechEngine, Batch 3 Multimodal Tests — Unit + Integration tests for Image, Audio, Video engi, Tests for ImageExtractor. (+44 more)

### Community 3 - "Community 3"
Cohesion: 0.06
Nodes (41): BaseMultimodalExtractor, ContentBlock, Content engine for structured text extraction with source tracking.  Provides Un, A block of extracted text with source provenance.      Attributes:         text:, AudioExtractor, ContentBlock, Audio extractor — Whisper-based speech-to-text transcription., Format seconds as MM:SS or HH:MM:SS.          Args:             seconds: Time in (+33 more)

### Community 4 - "Community 4"
Cohesion: 0.07
Nodes (42): ABC, BaseExtractor, BaseExtractor, Base extractor module providing abstract base class for all text extractors., Abstract base class for text extractors.      All concrete extractors must inher, Validate that a file exists and is within the size limit.          Args:, Extract text content from a file.          Args:             file_path: Path to, CsvExtractor (+34 more)

### Community 5 - "Community 5"
Cohesion: 0.09
Nodes (37): EmbeddingEngine, Configuration constants for the engines module.  Defines chunk sizes, embedding, EmbeddingEngine, Embedding Engine for generating vector embeddings via Ollama.  Uses nomic-embed-, Generates text embeddings using nomic-embed-text via Ollama.      Converts text, EvidenceChunk, An evidence chunk with full provenance for citation.      Attributes:         ch, Engines module for IntelliVault Batch 3.  Provides structured content extraction (+29 more)

### Community 6 - "Community 6"
Cohesion: 0.05
Nodes (32): Test search and filter functionality., Test file selection and event handling., Test that all required modules can be imported correctly., Test widget UI components., Test model functionality., Test refresh functionality., test_file_selection(), test_import() (+24 more)

### Community 7 - "Community 7"
Cohesion: 0.07
Nodes (34): AIService, AI service module orchestrating text analysis through Ollama., Orchestrates the AI analysis pipeline.      Coordinates between prompt building,, Initialize the AI service.          Args:             ollama_client: Client for, Analyze text and return structured metadata.          Orchestrates the full pipe, Analysis manager providing the public interface for AI-powered file analysis., Configuration constants for the AI module., AI module for IntelliVault.  Provides AI-powered document analysis using Ollama (+26 more)

### Community 8 - "Community 8"
Cohesion: 0.07
Nodes (23): QListView, QStyledItemDelegate, QTableView, _make_tree(), Spin the event loop until QFileSystemModel finishes loading a path., test_explorer_builds(), test_explorer_clear_filter(), test_explorer_context_handlers_no_crash() (+15 more)

### Community 9 - "Community 9"
Cohesion: 0.06
Nodes (27): EngineDBStore, Delete all evidence for a file.          Args:             file_path: Absolute p, Get set of all file hashes that have been indexed.          Returns:, Persistence layer for the retrieval engine.      Stores evidence chunks and vect, Get recent search history.          Args:             limit: Maximum number of r, Initialize with a SQLAlchemy session factory.          Args:             session, _db_session_factory(), Batch 3 Tests — Unit + Integration tests for IntelliVault engines.  All tests ru (+19 more)

### Community 10 - "Community 10"
Cohesion: 0.08
Nodes (25): _make_correlated_vector(), _make_evidence_chunk(), _make_fake_embedding(), Tests for VectorEngine., Add 5 vectors, search, verify results ordered by score., Add then remove, verify size decreases., Save to tmp file, load in new instance, verify same size., Tests for RetrievalEngine. (+17 more)

### Community 11 - "Community 11"
Cohesion: 0.09
Nodes (19): RAGEngine, RAGResponse, Ask a question about a specific file.          Convenience method that sets scop, Ask a question about a file using full-file context (Tier 1).          Extracts, Build prompt for direct full-file context approach.          This prompt encoura, Use LLM to re-rank search results by relevance to the query.          Sends the, Extract transcription from audio file using Whisper.          Args:, Response from the RAG engine. (+11 more)

### Community 12 - "Community 12"
Cohesion: 0.10
Nodes (19): QTreeView, QWidget, test_breadcrumb_renders_segments(), test_drives_lists_root(), test_favorites_add_remove(), test_folder_tree_emits_on_navigate(), test_main_window_navigation_updates_path(), test_main_window_up_goes_to_parent() (+11 more)

### Community 13 - "Community 13"
Cohesion: 0.07
Nodes (26): AICacheManager, AI Analysis cache manager for SQLite persistence.  Provides CRUD operations for, Delete cached analysis by file hash.          Args:             file_hash: SHA-2, Check if analysis exists for a file hash.          Args:             file_hash:, Convert an AIAnalysis ORM record to a dictionary.          Args:             rec, Manages SQLite caching of AI analysis results.      All lookups are by file cont, Initialize with a SQLAlchemy session factory.          Args:             session, Retrieve cached analysis by file content hash.          Args:             file_h (+18 more)

### Community 14 - "Community 14"
Cohesion: 0.08
Nodes (17): QMainWindow, test_menu_toggle_docks(), test_navigation_history_back_forward(), test_navigation_history_drops_forward_on_new_nav(), test_status_bar_updates(), test_theme_applied_on_startup(), test_toggle_theme_changes_config(), test_window_builds() (+9 more)

### Community 15 - "Community 15"
Cohesion: 0.13
Nodes (11): _settings(), test_main_window_opens_settings(), test_reserved_tabs_present_but_disabled(), test_settings_apply_writes_config(), test_settings_has_all_tabs(), test_settings_persist_to_db(), test_settings_theme_apply(), QWidget (+3 more)

### Community 16 - "Community 16"
Cohesion: 0.12
Nodes (18): Minimal dependency-injection container with lazy service initialization.  Wires, Cache manager.  A simple two-tier cache (in-memory + disk) with TTL and size-bas, File watcher.  A thin wrapper around ``watchdog`` that watches a directory and e, Any, Exception, ThreadManager, Task manager.  High-level scheduling on top of :class:`ThreadManager`. Each task, TaskManager (+10 more)

### Community 17 - "Community 17"
Cohesion: 0.12
Nodes (17): PluginRegistry, PluginRegistry, Plugin registry and interface.  Defines the contract future AI batches (Batch 1-, Manually subscribe a plugin to additional events., Manually unsubscribe a plugin from events., load_all(), PluginRegistry, Plugin loader.  Discovers plugin modules inside the ``plugins`` package and call (+9 more)

### Community 18 - "Community 18"
Cohesion: 0.10
Nodes (17): DiscoveredItem, ExtractionResult, MetadataResult, Get or create extracted text result for a discovered item., Index a single item and persist to SQLite., Perform a complete scan and indexing operation., Update an indexed record., Delete an indexed record. (+9 more)

### Community 19 - "Community 19"
Cohesion: 0.11
Nodes (16): attach_db_handler(), _DBLogHandler, get_logger(), Centralised logging configuration for IntelliVault.  Logs are written both to ``, Attach a database-backed handler to the intellivault logger., setup_logging(), Logger, LogRecord (+8 more)

### Community 20 - "Community 20"
Cohesion: 0.12
Nodes (15): Path, Process a Folder Scanner ScanResults and extract text., Extract text from a single discovered item., Detect the format of a file based on extension., Extract text from PDF., Extract text from DOCX., Extract text from Excel., Extract text from PPTX. (+7 more)

### Community 21 - "Community 21"
Cohesion: 0.12
Nodes (18): OCRResult, ContentMerger produces blocks from OCR and vision results., ContentMerger, ContentBlock, Content Merger for combining OCR and vision results into ContentBlocks., Merges OCR text and vision captions into unified ContentBlocks.      Combines ou, Merge OCR and vision results into ContentBlocks.          Args:             file, Vision module for image intelligence (OCR, captioning, content merging). (+10 more)

### Community 22 - "Community 22"
Cohesion: 0.15
Nodes (7): PreviewPanel, Get metadata for a file from SQLite index if available., Get extracted text for a file from SQLite index if available., Show the extracted text tab from SQLite index., Handler for the extracted text tab button., Show the metadata tab from SQLite index., Handler for the metadata tab button.

### Community 23 - "Community 23"
Cohesion: 0.10
Nodes (14): ndarray, Add a batch of vectors to the index.          Args:             chunk_ids: List, Search for similar vectors.          Args:             query_vector: Query vecto, Remove vectors by chunk IDs (rebuilds index).          Args:             chunk_i, Save index to disk.          Returns:             True if saved successfully, Fa, Load index from disk., Clear the entire index., Manages FAISS vector index for semantic similarity search.      Uses an inner-pr (+6 more)

### Community 24 - "Community 24"
Cohesion: 0.12
Nodes (16): Container, Shared QFileSystemModel instance for FolderTree and FileExplorer., Lazy-initialized EmbeddingEngine (uses Ollama nomic-embed-text)., Lazy-initialized VectorEngine (FAISS index)., Lazy-initialized RetrievalEngine., Lazy-initialized RAGEngine., QFileSystemModel, test_main_window_preview_wired() (+8 more)

### Community 25 - "Community 25"
Cohesion: 0.15
Nodes (14): MetadataExtractor, MetadataResult, Path, Calculate SHA256 checksum of a file., Get file owner information based on platform., Get owner on Windows using win32security., Extract metadata for a list of file paths directly., Extract metadata for a single path. (+6 more)

### Community 26 - "Community 26"
Cohesion: 0.16
Nodes (12): Config, Any, Application-wide configuration with typed accessors and persistence.  Settings a, Holds settings and persists them to disk., _new_config(), Config, test_change_signal_emitted(), test_deep_update_preserves_other_keys() (+4 more)

### Community 27 - "Community 27"
Cohesion: 0.09
Nodes (12): B1ProgressDialog, Batch 1 Progress Dialog.  Progress dialog for the Batch 1 File Scan with detaile, Set up timers for updating statistics., Update statistics labels., Update progress information., Set the current file being processed., Update the status label., Enable or disable the cancel button. (+4 more)

### Community 28 - "Community 28"
Cohesion: 0.11
Nodes (8): FileSystemEventHandler, FileWatcher, FolderScanner, Repository, FileWatcher, _Handler, Signal, TaskManager

### Community 29 - "Community 29"
Cohesion: 0.20
Nodes (16): Container, Enum, ScanResults, DiscoveredItem, Folder Scanner.  Discovers files and folders in a directory tree with progress r, ScanResults, Metadata Extraction Service.  Extracts metadata from discovered files using the, IndexedFile (+8 more)

### Community 30 - "Community 30"
Cohesion: 0.10
Nodes (11): VideoExtractor supports standard video formats., Tests for the extractors/ module., Factory reports all supported extensions., Factory selects ImageExtractor for image files., Factory selects AudioExtractor for audio files., Factory selects VideoExtractor for video files., Factory selects DocumentExtractor for text files., Factory returns None for unsupported extensions. (+3 more)

### Community 31 - "Community 31"
Cohesion: 0.12
Nodes (11): Semantic Search Dialog.  A standalone dialog for performing semantic (AI-powered, Populate the results list with search results.          Each result dict should, Display an error message in the status label.          Args:             error_m, Handle double-click on a result item to open the file.          Args:, Dialog for semantic search across indexed documents.      Signals:         file_, Initialize the Semantic Search Dialog.          Args:             parent: Parent, Set up the dialog UI layout., Handle search button click or Enter key press. (+3 more)

### Community 32 - "Community 32"
Cohesion: 0.14
Nodes (10): Initialize the audio extractor.          Args:             model_size: Whisper m, ContentBlock, Extract audio track from video using ffmpeg.          Args:             file_pat, Extract keyframes from video and generate captions.          Uses OpenCV to extr, Extracts content from video files.      Pipeline:     1. Extract audio track → W, Generate a caption for a video frame using vision model.          Args:, Extract content from a video file.          Extracts the audio track, transcribe, Extract audio from video and transcribe with Whisper.          Args: (+2 more)

### Community 33 - "Community 33"
Cohesion: 0.13
Nodes (8): PluginInterface, Any, Return plugins subscribed to the given event., Dispatch hook only to plugins subscribed to this event., Events this plugin wants to receive. Override to declare subscriptions., Called when the plugin is registered. Override to initialise., Called when the plugin is removed. Override to clean up., Called for every hook event the plugin subscribed to.

### Community 34 - "Community 34"
Cohesion: 0.12
Nodes (16): Test fallback to standard text extraction when no extracted text exists., Test extracted text handling for unsupported formats., Test PreviewPanel initialization with database., Test that extracted text supports scrolling., Test integration with MainWindow components., Test that all PreviewPanel extracted text components are properly set up., Test extracted text functionality., Test extracted text tab button handler. (+8 more)

### Community 35 - "Community 35"
Cohesion: 0.15
Nodes (8): Any, Database, ThreadManager, Application-wide signal bus.  All cross-module communication flows through this, SignalBus, CacheManager, Config, SignalBus

### Community 36 - "Community 36"
Cohesion: 0.13
Nodes (9): AskAIDialog, Ask AI Dialog.  A dialog for asking questions about a selected file using AI-pow, Handle Ask button click or Enter key press., Return the file path this dialog is querying about.          Returns:, Display the AI answer and associated citations.          Args:             answe, Display an error message in the status label.          Args:             error_m, Dialog for asking AI questions about a specific file.      Signals:         ques, Initialize the Ask AI Dialog.          Args:             file_path: Absolute pat (+1 more)

### Community 37 - "Community 37"
Cohesion: 0.16
Nodes (9): AIAnalysisDialog, AI Analysis Dialog.  Displays the AI-generated analysis results for a file inclu, Populate the dialog with analysis data.          Args:             analysis: Dic, Handle regenerate button click. Closes dialog and triggers re-analysis., Update the displayed analysis with new data.          Args:             analysis, Dialog for displaying AI-generated file analysis.      Shows summary, category,, Initialize the AI Analysis Dialog.          Args:             analysis: Dict wit, Set up the dialog UI layout. (+1 more)

### Community 38 - "Community 38"
Cohesion: 0.19
Nodes (7): CacheManager, Any, Retrieve a pickled Python object from cache., Store a Python object in cache via pickle., test_cache_set_get(), test_cache_ttl_expiry(), _tmp_cache_dir()

### Community 39 - "Community 39"
Cohesion: 0.20
Nodes (9): FolderScanner, Event, Path, Count total files + folders for progress denominator., Check if the path should be ignored based on ignore patterns., Walk directory tree, yielding Path objects.          Tracks real paths of visite, Scans a directory tree and reports discovered files/folders., Scan the directory tree starting at root_path. (+1 more)

### Community 40 - "Community 40"
Cohesion: 0.13
Nodes (13): Test fallback to standard properties when no metadata exists., Test integration with MainWindow components., Test that all PreviewPanel components are properly serialized., Test PreviewPanel initialization with database., Test metadata tab functionality., Test metadata tab button handler., test_integration_with_main_window(), test_metadata_fallback() (+5 more)

### Community 41 - "Community 41"
Cohesion: 0.15
Nodes (7): Element, XML extractor should extract text nodes from XML file., test_xml_extractor(), Extract text from a CSV file.          Args:             file_path: Path to the, Extractor for XML files.      Uses ElementTree to extract all text content recur, Recursively extract text from an XML element and its children.          Args:, XmlExtractor

### Community 42 - "Community 42"
Cohesion: 0.15
Nodes (7): Handle AI Analyze File request from context menu., Run AI analysis in a background worker with progress dialog., Handle AI analysis completion., Show the AI Analysis dialog with results., Handle regenerate request from AI dialog., Handle View Analysis from context menu — show cached analysis., Handle Regenerate Analysis from context menu.

### Community 43 - "Community 43"
Cohesion: 0.17
Nodes (10): AnalysisManager, Compute SHA-256 hash of a file.          Args:             file_path: Path to th, Public interface for AI-powered document analysis.      Manages the end-to-end w, Initialize the analysis manager.          Args:             ai_service: The AI s, Analyze a file and return structured metadata.          Extracts text from the f, AIService, AnalysisManager._compute_file_hash should return a 64-char hex string., AnalysisManager should return error dict for unsupported file types. (+2 more)

### Community 44 - "Community 44"
Cohesion: 0.17
Nodes (7): Tests for extended ContentBlock fields., ContentBlock has modality field with default 'document'., ContentBlock supports image modality., ContentBlock supports audio modality with timestamps., ContentBlock metadata defaults to empty dict., Existing code using ContentBlock without new fields still works., TestContentBlockExtended

### Community 45 - "Community 45"
Cohesion: 0.15
Nodes (7): QListWidgetItem, Handle updates to the indexed files list., Add an indexed file to the list display., Create a list widget item for an indexed file., Format file size in human readable format., Update status label with item count., Handle file selection.

### Community 46 - "Community 46"
Cohesion: 0.17
Nodes (6): Remove trailing commas before closing braces/brackets.          Args:, Replace single quotes with double quotes for JSON compatibility.          Only p, Validate that all required fields exist with correct types.          Args:, Parse a raw model response into a validated dictionary.          Extracts JSON f, Extract JSON text from a raw response.          Handles markdown code blocks and, Attempt to parse JSON text, with repair for common issues.          Args:

### Community 47 - "Community 47"
Cohesion: 0.18
Nodes (8): Speech module for audio intelligence (Whisper transcription)., Speech Engine for audio transcription using OpenAI Whisper.  Provides transcript, A single segment of transcribed speech., Complete transcription result., Lazy-load the Whisper model., Transcribe an audio file.          Args:             audio_path: Path to the aud, TranscriptionResult, TranscriptSegment

### Community 48 - "Community 48"
Cohesion: 0.20
Nodes (7): QObject, QRunnable, Any, Event, Exception, Worker, WorkerSignals

### Community 49 - "Community 49"
Cohesion: 0.20
Nodes (3): DockManager, QWidget, Create indexed files widget (embedded in central layout, not a dock).

### Community 50 - "Community 50"
Cohesion: 0.22
Nodes (3): QToolBar, Main toolbar.  Provides navigation controls (back/forward/up/refresh), a view sw, ToolBar

### Community 52 - "Community 52"
Cohesion: 0.22
Nodes (4): Handle Semantic Search request from context menu., Handle semantic search from toolbar search box., Open the Semantic Search dialog and wire it up., Run smart semantic search in a background thread and feed results to dialog.

### Community 53 - "Community 53"
Cohesion: 0.14
Nodes (4): Check if the embedding model is available in Ollama.          Returns:, Initialize the embedding engine.          Args:             model: Name of the e, Remove all indexed chunks for a file.          Args:             file_path: Path, Clear the entire index and evidence store.

### Community 54 - "Community 54"
Cohesion: 0.25
Nodes (3): QStatusBar, Status bar.  Shows the current item count, free disk space for the active volume, StatusBar

### Community 55 - "Community 55"
Cohesion: 0.25
Nodes (4): Look up indexed record by absolute path., Look up indexed records by filename., List all indexed records., Convert IndexedFile record to dictionary.

### Community 56 - "Community 56"
Cohesion: 0.33
Nodes (5): _load_clip(), ndarray, Lazy-load CLIP model (cached globally)., Generate CLIP embedding for an image file.          Args:             image_path, Generate CLIP embedding for a text query.          This allows searching images

### Community 60 - "Community 60"
Cohesion: 0.50
Nodes (3): ndarray, Generate embeddings for a batch of texts.          Args:             texts: List, Generate embedding vector for a single text string.          Args:             t

### Community 61 - "Community 61"
Cohesion: 0.40
Nodes (3): IndexedFile, Convert IndexedFile record to dictionary., Load indexed files from SQLite for the current folder.

### Community 63 - "Community 63"
Cohesion: 0.50
Nodes (4): _make_temp_db(), Create a temporary Database and return (db, session_factory)., Provide a temporary database and session factory., temp_db()

### Community 64 - "Community 64"
Cohesion: 0.05
Nodes (44): Unit tests for IntelliVault Batch 2 - AI Analysis Module.  Tests cover text extr, PPTX extractor should return empty string for non-existent file., CSV extractor should read rows and join with tabs/newlines., JSON extractor should return pretty-printed JSON content., MD extractor should return markdown content as-is., ExtractorFactory should return a non-empty sorted list of extensions., ExtractorFactory should return correct extractor types., ExtractorFactory should return None for unsupported file types. (+36 more)

### Community 66 - "Community 66"
Cohesion: 0.50
Nodes (3): Keyframe, A representative frame extracted from video., Extract keyframes from a video file.          Args:             video_path: Path

## Knowledge Gaps
- **6 isolated node(s):** `LogRecord`, `Signal`, `Event`, `Any`, `Exception` (+1 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **19 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `MainWindow` connect `Community 14` to `Community 1`, `Community 6`, `Community 7`, `Community 8`, `Community 12`, `Community 13`, `Community 15`, `Community 18`, `Community 19`, `Community 20`, `Community 22`, `Community 24`, `Community 25`, `Community 27`, `Community 29`, `Community 31`, `Community 34`, `Community 36`, `Community 37`, `Community 39`, `Community 40`, `Community 42`, `Community 49`, `Community 50`, `Community 51`, `Community 52`, `Community 54`, `Community 57`, `Community 58`, `Community 65`, `Community 67`, `Community 89`, `Community 90`, `Community 91`, `Community 92`, `Community 93`, `Community 94`, `Community 95`, `Community 96`, `Community 97`, `Community 98`?**
  _High betweenness centrality (0.186) - this node is a cross-community bridge._
- **Why does `ContentBlock` connect `Community 3` to `Community 32`, `Community 1`, `Community 2`, `Community 5`, `Community 9`, `Community 44`, `Community 21`, `Community 30`?**
  _High betweenness centrality (0.106) - this node is a cross-community bridge._
- **Why does `AIFolderIndexer` connect `Community 1` to `Community 3`, `Community 5`, `Community 12`, `Community 14`, `Community 23`, `Community 29`?**
  _High betweenness centrality (0.105) - this node is a cross-community bridge._
- **Are the 27 inferred relationships involving `MainWindow` (e.g. with `AICacheManager` and `Container`) actually correct?**
  _`MainWindow` has 27 INFERRED edges - model-reasoned connections that need verification._
- **Are the 15 inferred relationships involving `Container` (e.g. with `SignalBus` and `Config`) actually correct?**
  _`Container` has 15 INFERRED edges - model-reasoned connections that need verification._
- **Are the 37 inferred relationships involving `ContentBlock` (e.g. with `AIFolderIndexer` and `IndexingProgress`) actually correct?**
  _`ContentBlock` has 37 INFERRED edges - model-reasoned connections that need verification._
- **Are the 27 inferred relationships involving `UniversalContentEngine` (e.g. with `AIFolderIndexer` and `IndexingProgress`) actually correct?**
  _`UniversalContentEngine` has 27 INFERRED edges - model-reasoned connections that need verification._