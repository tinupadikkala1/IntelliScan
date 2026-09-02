# IntelliVault Project Performance and Architectural Analysis

A detailed analysis of the **IntelliVault/IntelliScan** codebase has been completed. This report highlights the project's strengths and identifies key performance bottlenecks, architectural issues, and logical bugs affecting the system's responsiveness, scalability, and AI search accuracy.

---

## 🏗️ Project Strengths

1. **Extensive Modality Support:** The project is well-designed to parse and index diverse file types including text documents, PDFs, images (via OCR and captioning), and audio/video files (via transcription and keyframes).
2. **Decoupled Architecture:** Clean separation of concerns between:
   - Database schemas/models ([models.py](file:///home/user/Desktop/mini_project/IntelliScan/database/models.py)) and CRUD operations ([repository.py](file:///home/user/Desktop/mini_project/IntelliScan/database/repository.py)).
   - AI Indexing, Retrieval, and RAG ([engines/](file:///home/user/Desktop/mini_project/IntelliScan/engines/)).
   - Qt-based User Interface ([ui/](file:///home/user/Desktop/mini_project/IntelliScan/ui/)) and custom components ([widgets/](file:///home/user/Desktop/mini_project/IntelliScan/widgets/)).
3. **Asynchronous Task Management:** Long-running folder scans and indexing are executed off the GUI thread using a custom [ThreadManager](file:///home/user/Desktop/mini_project/IntelliScan/services/thread_manager.py) wrapping `QThreadPool` and `QRunnable`. This prevents interface freezes and keeps the UI responsive.
4. **Signal-Bus Pattern:** Uses a central [SignalBus](file:///home/user/Desktop/mini_project/IntelliScan/app/signal_bus.py) for decoupled event propagation (e.g., selection changes, progress updates), avoiding tight couplings.

---

## ⚠️ Performance Bottlenecks & Architectural Issues

### 1. Inefficient Database Lookups in UI Preview Panel
* **File:** [preview_panel.py](file:///home/user/Desktop/mini_project/IntelliScan/widgets/preview_panel.py) (Lines 344–350 and 391–399)
* **Problem:** In `_get_metadata_from_index` and `_get_extracted_text_from_index`, the code calls `session.query(IndexedFile).all()` to load *all* indexed records from SQLite into memory and loops through them in Python to find the one matching the selected file path:
  ```python
  session = self.database.session()
  records = session.query(IndexedFile).all()
  record = None
  for r in records:
      if getattr(r, 'absolute_path', None) == path:
          record = r
          break
  ```
* **Impact:** As the index database grows (e.g., thousands of files), clicking a file in the UI loads the entire table into memory and generates thousands of SQLAlchemy objects. This causes severe UI stutters.
* **Solution:** Replace with a direct database query: `session.query(IndexedFile).filter_by(absolute_path=path).first()`.

---

### 2. Quadratic Complexity $O(N^2)$ in Folder Indexer
* **File:** [sqlite_indexer.py](file:///home/user/Desktop/mini_project/IntelliScan/services/sqlite_indexer.py) (Lines 89–131)
* **Problem:** During folder indexing, `_get_metadata_for_item` and `_get_text_for_item` perform a linear search over `metadata_results` and `text_results` lists for each `DiscoveredItem`:
  ```python
  def _get_metadata_for_item(self, item: DiscoveredItem, metadata_results: List[MetadataResult]):
      for meta in metadata_results:
          if meta.absolute_path == item.path:
              return meta
  ```
* **Impact:** For $N$ files, this results in $O(N^2)$ comparisons. Indexing 5,000 files requires up to 25 million iterations, causing severe CPU spikes and freezing the indexing thread.
* **Solution:** Convert `metadata_results` and `text_results` to dictionaries keyed by `absolute_path` before processing, reducing complexity to $O(N)$.

---

### 3. Whisper Model Reloading Overhead
* **Files:** [content_engine.py](file:///home/user/Desktop/mini_project/IntelliScan/engines/content_engine.py) (Line 403) & [video_extractor.py](file:///home/user/Desktop/mini_project/IntelliScan/extractors/video_extractor.py) (Line 93)
* **Problem:** `AudioExtractor` is designed to lazy-load Whisper:
  ```python
  def _load_model(self):
      if self._model is None:
          self._model = whisper.load_model(self._model_size)
  ```
  However, both `UniversalContentEngine` and `VideoExtractor` instantiate `AudioExtractor` anew for *each* audio/video file processed.
* **Impact:** Because a new instance is created for every file, `self._model` is always `None`, forcing Whisper to reload from disk/memory for every audio/video file. Loading Whisper takes several seconds and consumes significant RAM and CPU.
* **Solution:** Make `AudioExtractor` a singleton, or cache the loaded model at the module level.

---

### 4. Redundant Disk I/O (Double Hashing)
* **Files:** [content_engine.py](file:///home/user/Desktop/mini_project/IntelliScan/engines/content_engine.py) (Lines 81, 165–178) & [evidence_engine.py](file:///home/user/Desktop/mini_project/IntelliScan/engines/evidence_engine.py) (Lines 94, 190–203)
* **Problem:** During indexing, `UniversalContentEngine` reads the entire file to calculate its SHA-256 hash. Immediately afterward, `EvidenceEngine` does the same.
* **Impact:** Reads the entire file from disk twice. For large files (like movies or podcasts), this creates a major disk I/O bottleneck.
* **Solution:** Pass the already computed `file_hash` from the Content Engine to the Evidence Engine, or compute it once at the start of the indexing pipeline.

---

### 5. N+1 Queries during Batch Database Writing
* **File:** [sqlite_indexer.py](file:///home/user/Desktop/mini_project/IntelliScan/services/sqlite_indexer.py) (Lines 67–87 and 151–153)
* **Problem:** In `index_items`, `_index_single` executes a database check for each item individually inside the loop:
  ```python
  existing = session.query(IndexedFile).filter_by(absolute_path=metadata.absolute_path).first()
  ```
* **Impact:** Causes row-by-row N+1 database roundtrips. Indexing 1,000 files generates 1,000 separate SQLite SELECT queries sequentially.
* **Solution:** Batch fetch existing records in a single query: `session.query(IndexedFile).filter(IndexedFile.absolute_path.in_(list_of_paths)).all()`.

---

### 6. Missing Batching in Ollama Embeddings
* **File:** [embedding_engine.py](file:///home/user/Desktop/mini_project/IntelliScan/engines/embedding_engine.py) (Lines 116–143)
* **Problem:** `embed_batch` loops through text chunks and sends a separate HTTP POST request for each one:
  ```python
  for i, text in enumerate(texts):
      vector = self.embed_text(text)
      results.append(vector)
  ```
* **Impact:** Ollama's `/api/embed` endpoint supports arrays of strings in the `input` field. Making sequential HTTP requests for thousands of chunks introduces severe network overhead and sequential execution delay.
* **Solution:** Send the list of chunks directly as a batch array to Ollama in a single request.

---

### 7. Thread-Safety Risks in VectorEngine (FAISS)
* **File:** [vector_engine.py](file:///home/user/Desktop/mini_project/IntelliScan/engines/vector_engine.py)
* **Problem:** `VectorEngine` manages a FAISS index and a Python list of `chunk_ids`. None of its methods (`add`, `search`, `save`, `remove_by_chunk_ids`) are thread-safe.
* **Impact:** Since indexing runs in a background thread and calls `vector_engine.save()`, and the main thread or other search features concurrently call `search()`, this can trigger race conditions, corrupt index states, or cause segmentation faults in the FAISS C++ library.
* **Solution:** Implement a thread lock (e.g., `threading.Lock`) to serialize access to the vector index.

---

### 8. Double Directory Walks in Folder Scanner
* **File:** [folder_scanner.py](file:///home/user/Desktop/mini_project/IntelliScan/services/folder_scanner.py) (Lines 59 & 65)
* **Problem:** To show a progress denominator, `scan` first calls `_count_entries` which traverses the entire directory tree using `root.rglob("*")`. Then, it traverses the directory tree a second time to perform the scan.
* **Impact:** Doubles filesystem traversal overhead. On slow hard drives, or deep folders, this can double scanning time.
* **Solution:** Run the walk once, store the paths in a list, and iterate over that list to process.

---

### 9. Hardcoded Ollama URLs
* **Files:** [video_extractor.py](file:///home/user/Desktop/mini_project/IntelliScan/extractors/video_extractor.py) (Line 253) & [image_extractor.py](file:///home/user/Desktop/mini_project/IntelliScan/extractors/image_extractor.py) (Line 127)
* **Problem:** HTTP requests are hardcoded to `"http://localhost:11434/api/generate"`.
* **Impact:** Ignores the user's custom `OLLAMA_BASE_URL` configuration in `engines/config.py`, breaking cases where Ollama is run on a remote server or custom port.
* **Solution:** Retrieve the base URL from the global configuration.

---

## 🎯 Accuracy and Reasoning Issues in Semantic Search

### 1. Missing nomic-embed-text Query/Document Prefixes
* **Files:** [embedding_engine.py](file:///home/user/Desktop/mini_project/IntelliScan/engines/embedding_engine.py) & [retrieval_engine.py](file:///home/user/Desktop/mini_project/IntelliScan/engines/retrieval_engine.py)
* **Problem:** The `nomic-embed-text` model requires text to be prefixed with `search_query: ` for queries, and `search_document: ` for documents when indexing. The code does not prepend these prefixes.
* **Impact:** Dramatically degrades similarity search quality, causing irrelevant results to match and accurate ones to be missed.
* **Solution:** Prepend the correct prefixes to texts before calling the embedding API.

### 2. Loss of Context from File Deduplication
* **File:** [retrieval_engine.py](file:///home/user/Desktop/mini_project/IntelliScan/engines/retrieval_engine.py) (Lines 275 & 390–408)
* **Problem:** `smart_retrieve` calls `_deduplicate_by_file`, which discards all but the single highest-scoring chunk for each file.
* **Impact:** If a question requires information from multiple pages/slides of the same file (e.g., slide 2 has names, slide 5 has stats), the system discards the other slides.
* **Solution:** Keep multiple high-scoring chunks from the same file, grouping them by document before sending them to the LLM.

### 3. Non-Multimodal Model Used on Image Frames
* **File:** [video_extractor.py](file:///home/user/Desktop/mini_project/IntelliScan/extractors/video_extractor.py) (Line 256)
* **Problem:** Captions for video keyframes are sent to `qwen-local:latest` (a text-only model) with image data in the payload:
  ```python
  "model": "qwen-local:latest",
  "images": [image_b64]
  ```
* **Impact:** The standard text-only model cannot process the image, causing Ollama API errors or useless caption text.
* **Solution:** Query the dedicated vision model `moondream:latest`.

---

## 🖥️ UI Gaps

### 1. Unminimizable Progress Dialog
* **File:** [main_window.py](file:///home/user/Desktop/mini_project/IntelliScan/ui/main_window.py) (Line 993)
* **Problem:** The progress dialog for indexing folder is created with `setWindowFlags(self._ai_index_progress.windowFlags() | Qt.WindowMinimizeButtonHint)`.
* **Impact:** On Linux/GNOME, a modal or parented dialog ignores this hint unless the `Qt.Window` flag is explicitly added.
* **Solution:** Create the dialog with `Qt.Window | Qt.CustomizeWindowHint | Qt.WindowTitleHint | Qt.WindowMinimizeButtonHint`.
