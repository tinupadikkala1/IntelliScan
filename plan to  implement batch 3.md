# IntelliVault — Batch 3 Complete Implementation Plan

**Scope:** All 16 remaining user-facing Batch 3 features  
**Baseline:** Current IntelliVault codebase audited on 2026-08-11  
**Implementation target:** Existing Python + PySide6 + SQLite/SQLAlchemy + Ollama + FAISS architecture  
**Primary constraint:** Intel Core i3-N305, 6.9 GiB RAM, no GPU, ~4.8 GiB free disk  
**Status before implementation:** Foundation + Batch 1 + Batch 2 stable; Batch 3 document retrieval and multimodal extraction engines exist, but persistence, UI integration, evidence navigation, and several multimodal workflows require completion.

---

# 1. Executive Summary

The current IntelliVault codebase already contains most of the low-level Batch 3 building blocks:

- `ContentBlock` and `EvidenceChunk`
- document/image/audio/video extractors
- OCR
- Vision captioning through Moondream
- Whisper transcription
- video keyframe extraction
- `nomic-embed-text`
- FAISS
- `RetrievalEngine`
- `RAGEngine`
- `AIFolderIndexer`
- Semantic Search UI
- Ask AI about this File UI
- a database model for `evidence`, `vector_map`, and `search_history`
- `EngineDBStore`, currently implemented but not wired into runtime

Therefore, Batch 3 should **not** be implemented as a replacement architecture.

The correct strategy is:

> **Stabilize and complete the existing architecture, connect persistence, unify multimodal evidence, expose the missing user-facing workflows, and add evidence-aware result navigation.**

The central architecture remains:

```text
Documents ─┐
Images ────┤
Audio ─────┤
Video ─────┘
       │
       ▼
Universal Content Extraction
       │
       ▼
ContentBlocks
       │
       ▼
EvidenceEngine
       │
       ▼
EmbeddingEngine
       │
       ▼
FAISS VectorEngine
       │
       ▼
RetrievalEngine
       │
   ┌───┴───────────────┐
   ▼                   ▼
Semantic Search       RAG
                       │
                       ▼
                  Ask AI
```

The major architectural correction is:

```text
Current:
FAISS → in-memory EvidenceChunk map

Target:
FAISS → persistent vector_map → persistent evidence → evidence-aware UI
```

This makes semantic retrieval survive application restarts and enables exact evidence navigation.

---

# 2. Batch 3 Feature Scope

This plan covers exactly the following **16 user-facing features**.

| ID | Feature | User-visible outcome |
|---|---|---|
| B3-01 | Image Intelligence | IntelliVault understands image files |
| B3-02 | OCR Search | Text inside images/scanned pages becomes searchable |
| B3-03 | Vision Understanding | Diagrams, screenshots, charts and visual content receive semantic descriptions |
| B3-04 | Ask AI About Image | User can ask questions about an image |
| B3-05 | Audio Intelligence | Audio becomes transcribed and searchable |
| B3-06 | Audio Semantic Search | User can search spoken content by meaning |
| B3-07 | Ask AI About Audio | User can ask questions about recordings |
| B3-08 | Audio Timestamp Navigation | Search results open the relevant audio timestamp |
| B3-09 | Video Intelligence | Video speech and keyframes become indexed |
| B3-10 | Video Semantic Search | User can search spoken/visual video content |
| B3-11 | Ask AI About Video | User can ask questions about videos |
| B3-12 | Video Timestamp Navigation | Search results open the relevant video timestamp |
| B3-13 | Evidence Navigation | User can open the exact page/image/evidence associated with a result |
| B3-14 | Unified Multimodal Search | One search works across documents, images, audio and video |
| B3-15 | Unified Evidence Results | Results expose modality-specific source information |
| B3-16 | Confidence / Match Explanation | Results explain similarity/match strength |

**Excluded:** Batch 4+ capabilities such as persistent conversations, Folder Chat, Workspace Chat, Knowledge Graphs, agents and other future scope.

**Also excluded from this plan:** Similar Documents/Similar Files as a separate feature. The existing code has `retrieve_similar()`, but the 16-feature scope requested here does not include it.

---

# 3. Current-System Constraints That Must Drive Implementation

## 3.1 Hardware

Current audited hardware:

- Intel Core i3-N305
- 8 CPU threads
- 6.9 GiB RAM
- no GPU
- CPU-only PyTorch
- approximately 4.8 GiB free disk

Therefore:

1. Do not run Whisper + CLIP + Ollama concurrently unless unavoidable.
2. Avoid loading large vision/speech models permanently.
3. Use lazy loading.
4. Release model memory after heavy operations when practical.
5. Process media sequentially by default.
6. Never duplicate large media into database blobs.
7. Store extracted text/metadata, not raw images/audio/video.
8. Make long-running work cancellable.
9. Avoid unnecessary re-embedding.
10. Avoid persistent cache growth without cleanup.

---

# 4. Critical Pre-Batch-3 Fixes

These are mandatory prerequisites, not optional cleanup.

## P0-01 — Wire EngineDBStore

Current problem:

- `EngineDBStore` exists.
- Unit tests cover it.
- Runtime code does not use it.
- `evidence` has zero live rows.
- `vector_map` has zero live rows.
- `search_history` has zero live rows.

### Target

```text
Indexer
  ↓
EvidenceEngine
  ↓
EngineDBStore.save_evidence()
  ↓
EmbeddingEngine
  ↓
VectorEngine
  ↓
EngineDBStore.save_vector_map()
```

At application startup:

```text
SQLite evidence
      ↓
EngineDBStore.load_evidence()
      ↓
RetrievalEngine.hydrate()
      ↓
FAISS index + evidence map available
```

### Files

Primary:

- `engines/db_store.py`
- `engines/ai_indexer.py`
- `engines/retrieval_engine.py`
- `app/container.py`

Tests:

- `tests/test_batch3.py`
- new persistence integration tests

---

## P0-02 — Startup Hydration

After FAISS is loaded, restore the evidence mapping.

Required invariant:

```text
Every FAISS vector ID that remains in the index
must resolve to a valid EvidenceChunk.
```

If an orphaned vector is detected:

- log it
- remove it from the active index or rebuild safely
- never crash startup

---

## P0-03 — Centralize Configuration

Currently model names, URLs and media settings are duplicated.

Centralize:

```text
Ollama URL
LLM model
Vision model
Embedding model
Whisper model
FAISS path
supported extensions
chunk size
chunk overlap
top-k
threshold
timeouts
media processing limits
```

Recommended location:

```text
engines/config.py
```

or a dedicated shared configuration service if the existing project convention requires it.

Do not create a second incompatible configuration mechanism.

---

## P0-04 — Fix Vision Model Default

`vision/vision_engine.py` currently defaults to `qwen-local:latest`, which is text-only.

Target:

```text
VisionEngine → configured vision model → moondream:latest
```

The model name must come from centralized configuration.

---

## P0-05 — Fix Multimodal Index Staleness

Current watcher updates the normal SQLite index but not the Batch 3 FAISS/evidence layer.

Target:

```text
File created
   ↓
normal index
   ↓
AI evidence index

File modified
   ↓
remove old evidence/vectors
   ↓
extract
   ↓
re-index

File deleted
   ↓
remove DB evidence
   ↓
remove vector mappings
   ↓
remove FAISS vectors

File renamed/moved
   ↓
preserve file hash identity
   ↓
update path references
```

---

# 5. Target Data Model

Do not store large binary media in SQLite.

## 5.1 ContentBlock

Existing structure is retained.

Required conceptual fields:

```python
ContentBlock(
    text,
    source_type,
    source_index,
    source_label,
    file_path,
    modality,
    timestamp_start,
    timestamp_end,
    confidence,
    metadata,
)
```

Examples:

### Document

```text
modality=document
source_type=page
source_label=Page 12
```

### Image

```text
modality=image
source_type=ocr
source_label=Image
```

### Audio

```text
modality=audio
source_type=transcript
source_label=02:14 - 02:31
timestamp_start=134
timestamp_end=151
```

### Video

```text
modality=video
source_type=keyframe/transcript
source_label=07:56
timestamp_start=476
timestamp_end=476
```

---

# 6. Target Evidence Model

Extend the existing evidence representation only where necessary.

Recommended fields:

```text
chunk_id
file_path
file_hash
text
source_type
source_index
source_label
char_start
char_end
timestamp_start
timestamp_end
confidence
metadata_json
indexed_at
```

For image/keyframe evidence, metadata may contain:

```json
{
  "image_index": 2,
  "frame_number": 1153,
  "bbox": null,
  "scene_type": "diagram"
}
```

Do not store image binaries in the evidence table.

---

# 7. Target Vector Mapping

`vector_map` must become the authoritative relationship between FAISS vectors and evidence.

Required conceptual mapping:

```text
FAISS vector ID
      ↓
vector_map
      ↓
chunk_id
      ↓
evidence
      ↓
source/file
```

The FAISS `.ids` file remains a cache/index artifact, not the only source of truth.

---

# 8. Feature B3-01 — Image Intelligence

## User Goal

The user can select an image and IntelliVault can understand its textual and visual content.

## Supported formats

At minimum:

- PNG
- JPG
- JPEG
- BMP
- WEBP
- TIFF
- GIF first frame

## UI

Context menu:

```text
Right Click Image
    ↓
AI
    ├── Analyze Image
    └── Ask AI about this Image
```

Existing `Ask AI about this File` may be reused instead of creating a duplicate action, provided the UI label clearly communicates image support.

## UX flow

```text
User selects image
      ↓
AI action
      ↓
Processing dialog
      ↓
OCR
      ↓
Vision caption
      ↓
Content merge
      ↓
Evidence creation
      ↓
Embedding
      ↓
FAISS
      ↓
Ready
```

Progress stages:

```text
Preparing image...
Extracting text...
Understanding image...
Indexing content...
Completed
```

## Backend

Reuse:

- `ImageExtractor`
- `OCREngine`
- `VisionEngine`
- `ContentMerger`
- `ContentEngine`
- `EvidenceEngine`
- `EmbeddingEngine`
- `VectorEngine`

Do not create a second image-processing pipeline.

## Output

The system should produce:

- OCR text
- visual caption
- semantic description
- confidence where available
- searchable evidence

## Tests

1. PNG OCR extraction.
2. JPG caption extraction.
3. Empty image handling.
4. Corrupt image handling.
5. Unsupported image extension.
6. OCR failure.
7. Vision model unavailable.
8. Successful image indexing.
9. Duplicate image indexing.
10. restart and evidence restoration.

---

# 9. Feature B3-02 — OCR Search

## User Goal

The user can search for text that appears inside an image or scanned document.

Example:

```text
Search:
"ModuleNotFoundError"
```

Result:

```text
error_screenshot.png
OCR
"ModuleNotFoundError: No module named..."
```

## Backend

For image:

```text
Image
 ↓
OCR
 ↓
ContentBlock(source_type="ocr")
 ↓
EvidenceChunk
 ↓
Embedding
 ↓
FAISS
```

For scanned PDF:

```text
PDF page
 ↓
detect no useful digital text
 ↓
render page
 ↓
OCR
 ↓
ContentBlock(source_type="ocr")
 ↓
Evidence
 ↓
Embedding
```

## Critical requirement

OCR must not replace valid digital text.

The pipeline should merge:

```text
digital text
+
OCR text
+
vision description
```

without creating unnecessary duplicate evidence.

## Tests

- searchable text inside PNG
- searchable text inside JPG
- scanned PDF page
- OCR mixed with digital text
- OCR-only PDF
- OCR failure
- multilingual text if currently supported
- search after restart

---

# 10. Feature B3-03 — Vision Understanding

## User Goal

The system understands visual information beyond raw OCR.

Examples:

- UML diagram
- ER diagram
- architecture diagram
- flowchart
- screenshot
- chart
- infographic
- table image

## Vision output

Example:

```json
{
  "caption": "ER diagram showing Student, Course and Enrollment entities.",
  "scene_type": "diagram",
  "objects": [
    "entity",
    "relationship",
    "database"
  ]
}
```

## Backend

```text
Image
 ↓
VisionEngine
 ↓
structured description
 ↓
ContentBlock(source_type="caption")
 ↓
EvidenceEngine
 ↓
EmbeddingEngine
```

## UI

The Preview Panel may show:

```text
AI Image Understanding

Type: ER Diagram

Description:
ER diagram showing Student, Course and Enrollment entities.
```

Do not add a permanent dock.

Prefer an expandable section or existing preview/AI dialog.

## Tests

- diagram
- screenshot
- chart
- plain photograph
- vision model unavailable
- malformed response
- empty caption
- caption indexing
- semantic retrieval through caption

---

# 11. Feature B3-04 — Ask AI About Image

## User Goal

Questions such as:

```text
What does this diagram represent?
What error is shown?
Explain this architecture.
What entities are present?
```

## UI

Reuse `AskAIDialog`.

Context:

```text
Right click image
→ AI
→ Ask AI about this File
```

Dialog title can dynamically become:

```text
Ask AI about Image
```

## Backend

Preferred context:

```text
OCR text
+
vision caption
+
metadata
```

Do not send the raw image to Qwen text-only model.

The VisionEngine produces the visual understanding first.

## Tests

- image with OCR
- image without OCR
- diagram question
- screenshot question
- vision unavailable
- LLM unavailable
- empty answer
- answer citation
- UI responsiveness

---

# 12. Feature B3-05 — Audio Intelligence

## User Goal

Audio files become searchable through their spoken content.

Supported formats should follow the current extractor:

- MP3
- WAV
- M4A
- FLAC
- OGG
- AAC
- WMA
- OPUS

## Pipeline

```text
Audio
 ↓
FFmpeg/preprocessing if required
 ↓
Whisper Base
 ↓
timestamped transcript
 ↓
ContentBlocks
 ↓
Evidence chunks
 ↓
nomic embeddings
 ↓
FAISS
```

## UX

Show progress:

```text
Preparing audio...
Transcribing...
Creating evidence...
Indexing...
Completed
```

## Resource constraint

Because the machine has 6.9 GiB RAM:

- Whisper must load lazily.
- Avoid simultaneous CLIP/Vision/Ollama workloads.
- Do not start multiple heavy audio jobs by default.

## Tests

- MP3 transcription
- WAV transcription
- empty audio
- corrupted audio
- FFmpeg unavailable
- Whisper unavailable
- cancellation
- timestamps
- indexing
- restart persistence

---

# 13. Feature B3-06 — Audio Semantic Search

## User Goal

Search spoken content by meaning.

Example:

```text
Query:
"third normal form"

Result:
lecture.mp3
02:14 - 02:31
"...third normal form eliminates..."
```

## Backend

Use transcript text embeddings.

Do not use raw audio embeddings.

```text
Query
 ↓
nomic embedding
 ↓
FAISS
 ↓
EvidenceChunk
 ↓
audio timestamp
```

## UI

Search result:

```text
🎵 lecture.mp3
02:14 - 02:31
Score: 0.84

"...third normal form eliminates transitive dependency..."
```

## Tests

- exact transcript query
- semantic query
- unrelated query
- timestamp returned
- audio result mixed with documents
- search after restart

---

# 14. Feature B3-07 — Ask AI About Audio

## User Goal

Questions such as:

```text
What is discussed in this recording?
What did the speaker say about normalization?
Summarize the lecture.
```

## Backend

Use:

```text
Whisper transcript
+
timestamps
→ RAG/direct context
→ Qwen
```

Prefer bounded transcript chunks rather than blindly loading huge recordings into the prompt.

## UX

The dialog should show citations such as:

```text
Source:
02:14 - 02:31
```

## Tests

- short audio
- long audio
- timestamped answer
- no transcript
- Whisper error
- Ollama error
- cancellation

---

# 15. Feature B3-08 — Audio Timestamp Navigation

## User Goal

Click a search result and jump directly to the relevant audio location.

## UI

Search result:

```text
lecture.mp3
02:14 - 02:31
```

Double-click:

```text
PreviewPanel
   ↓
Audio player
   ↓
seek(134 seconds)
```

## Backend

The result must carry:

```text
timestamp_start
timestamp_end
```

No timestamp may be reconstructed from the displayed text.

## Tests

- click timestamp result
- correct seek position
- missing timestamp
- invalid timestamp
- audio unavailable
- player closed/reopened

---

# 16. Feature B3-09 — Video Intelligence

## User Goal

Video becomes searchable through:

1. speech
2. keyframes
3. OCR/visual descriptions

## Pipeline

```text
Video
 ├──────────────► Audio track → Whisper → transcript
 │
 └──────────────► Keyframes → OCR + Vision → visual evidence
                         │
                         ▼
                    Content Merger
                         │
                         ▼
                    EvidenceEngine
                         │
                         ▼
                   EmbeddingEngine
                         │
                         ▼
                       FAISS
```

## Keyframe strategy

Retain the existing interval-based extraction.

Do not extract every frame.

Resource-conscious default:

- configurable interval
- cancellation
- maximum keyframes per video
- skip visually redundant frames where practical

## Tests

- MP4
- video with speech
- video without speech
- keyframe extraction
- OCR keyframe
- Vision caption
- cancellation
- corrupted video
- FFmpeg failure
- restart persistence

---

# 17. Feature B3-10 — Video Semantic Search

## User Goal

Search either spoken or visual information.

Examples:

```text
"convolution layer"
```

or:

```text
"architecture diagram"
```

Result:

```text
lecture5.mp4
07:56

Frame:
CNN architecture diagram

Transcript:
"...this convolution layer..."
```

## Backend

Both evidence streams enter the same retrieval layer:

```text
Transcript Evidence
+
Keyframe/Vision Evidence
        ↓
same ContentBlock model
        ↓
same EvidenceEngine
        ↓
same EmbeddingEngine
        ↓
same FAISS
```

## Tests

- transcript query
- visual query
- mixed query
- timestamp
- keyframe source
- unrelated query
- restart persistence

---

# 18. Feature B3-11 — Ask AI About Video

## User Goal

Ask:

```text
What is this video about?
Explain the architecture shown.
What was said about CNN?
```

## Context

Use:

```text
transcript evidence
+
relevant keyframe captions
+
OCR where available
```

Do not send the entire raw video to Qwen.

## Retrieval-first design

For long videos:

```text
Question
 ↓
retrieve relevant transcript/keyframe evidence
 ↓
build bounded context
 ↓
Qwen
 ↓
answer + citations
```

This is preferable to whole-video direct prompting.

## Tests

- transcript question
- visual question
- mixed question
- long video
- no matching evidence
- Ollama unavailable
- timestamp citations

---

# 19. Feature B3-12 — Video Timestamp Navigation

## User Goal

Click a result and jump to the exact relevant video time.

## Result

```text
lecture5.mp4
07:56
CNN Architecture
```

## Preview behavior

```text
Video Preview
   ↓
setPosition(476000 ms)
   ↓
play
```

Use milliseconds internally where the Qt player API expects them.

## Tests

- valid timestamp
- timestamp precision
- missing timestamp
- video unavailable
- multiple results
- click/double-click behavior

---

# 20. Feature B3-13 — Evidence Navigation

## User Goal

The user should reach the exact source of the match instead of merely opening the file.

## Document

```text
Result
 ↓
Page 43
 ↓
open PDF
 ↓
jump to page 43
```

## Image

```text
Result
 ↓
image
 ↓
open image in Preview
```

## Audio

```text
Result
 ↓
02:14
 ↓
seek audio
```

## Video

```text
Result
 ↓
07:56
 ↓
seek video
```

## Architecture

Add a generic evidence navigation object:

```python
EvidenceLocation(
    file_path,
    modality,
    source_type,
    source_index,
    page,
    timestamp_start,
    timestamp_end,
    metadata,
)
```

Do not hard-code PDF-specific behavior into the retrieval engine.

The retrieval engine returns evidence.

The UI navigation layer interprets it.

## Tests

- PDF page navigation
- PPTX slide navigation
- image preview
- audio seek
- video seek
- missing evidence
- deleted source
- invalid page
- invalid timestamp

---

# 21. Feature B3-14 — Unified Multimodal Search

## User Goal

A single query searches:

```text
documents
images
audio
video
```

Example:

```text
"database architecture"
```

Possible results:

```text
📄 database_notes.pdf
Page 32

🖼 architecture.png
Diagram

🎵 database_lecture.mp3
12:43

🎬 database_video.mp4
07:56
```

## UI

Existing semantic search UI should be extended.

Do not create four independent search dialogs.

Recommended:

```text
AI Search: [ database architecture              ]

Filters:
[All] [Documents] [Images] [Audio] [Video]
```

Default:

```text
All
```

## Backend

```text
query
 ↓
query embedding
 ↓
FAISS
 ↓
persistent evidence
 ↓
scope
 ↓
modality filter
 ↓
ranking
 ↓
Unified RetrievalResult
```

The modality filter should be an explicit UI filter.

Do not rely exclusively on keyword-based `_detect_modality`.

## Tests

- document-only query
- image-only query
- audio-only query
- video-only query
- mixed results
- All filter
- modality filters
- empty query
- no results
- restart
- large result set

---

# 22. Feature B3-15 — Unified Evidence Results

## User Goal

Every result should expose the information necessary to understand why it matched.

Recommended result card:

```text
┌─────────────────────────────────────────────┐
│ 📄 MCA_Syllabus.pdf                         │
│ Page 43 · Semester III Curriculum           │
│                                             │
│ "...Machine Learning, Data Mining..."       │
│                                             │
│ Similarity: 0.91                            │
│                                             │
│ [Open Evidence]                             │
└─────────────────────────────────────────────┘
```

Audio:

```text
🎵 Database_Lecture.mp3
02:14 - 02:31
"...third normal form..."
Similarity: 0.84
[Jump to Evidence]
```

Video:

```text
🎬 Lecture5.mp4
07:56
CNN Architecture
Similarity: 0.88
[Jump to Evidence]
```

## Data contract

Every result should expose:

```text
file_path
file_hash
modality
source_type
source_label
text_snippet
score
timestamp_start
timestamp_end
source_index
```

## Tests

- all modalities render correctly
- missing optional fields
- long snippets
- long filenames
- zero score
- score formatting
- invalid paths
- keyboard navigation

---

# 23. Feature B3-16 — Confidence / Match Explanation

## Important distinction

FAISS similarity score is **not calibrated confidence**.

Therefore, do not display:

```text
Confidence: 96%
```

unless an actual calibrated confidence model is implemented.

Use:

```text
Similarity: 0.91
```

or:

```text
Match strength: High
```

derived from documented thresholds.

## Recommended initial display

```text
Similarity: 0.91
Match strength: High
```

Thresholds should be configurable.

Example:

```text
>= 0.80 → High
0.60–0.79 → Medium
< 0.60 → Low
```

These values must be validated against actual retrieval behavior before being treated as final.

## Explanation

Where available:

```text
Matched because:
- semantic similarity
- OCR text
- visual description
- transcript
```

Do not claim an explanation that was not actually produced by the system.

## Tests

- score formatting
- threshold classification
- missing score
- zero score
- score outside expected range
- modality explanation
- no explanation available

---

# 24. Embedded Images Inside Documents

This is a critical part of Batch 3.

Current:

```text
PDF/DOCX/PPTX
 ↓
digital text only
```

Target:

```text
Document
 ├── Digital text
 └── Embedded images
       ├── OCR
       └── Vision
```

## PDF

Use PyMuPDF to identify/extract page images.

## PPTX

Use python-pptx to inspect image shapes.

## DOCX

Inspect inline/anchored images.

## Output

Embedded image evidence should retain parent document information:

```text
file_path = report.pdf
source_type = embedded_image
source_index = image/page-specific index
source_label = Page 28 · Image 3
```

## Tests

- PDF embedded image
- PPTX embedded image
- DOCX embedded image
- document with no images
- image extraction failure
- OCR failure
- vision failure
- page provenance preserved
- Ask AI uses embedded visual content

---

# 25. Persistence Architecture

## Indexing transaction

A file should be treated as a single logical indexing unit.

Recommended sequence:

```text
Start
 ↓
extract ContentBlocks
 ↓
build EvidenceChunks
 ↓
persist evidence
 ↓
generate embeddings
 ↓
add vectors
 ↓
persist vector_map
 ↓
save FAISS
 ↓
commit success
```

If indexing fails:

```text
rollback/remove partial evidence
remove partial vectors
restore previous state where possible
```

Do not leave half-indexed files.

---

# 26. Incremental Update Architecture

For each file:

```text
hash_old != hash_new
```

then:

```text
remove old evidence
remove old vector mappings
remove old FAISS vectors
extract again
index again
```

If hash unchanged:

```text
do not re-run expensive AI processing
```

For rename/move:

```text
same hash
new path
update path references
```

---

# 27. FAISS Concurrency

Current architecture has locking but save/search races are still possible.

Implement one controlled mutation boundary.

Recommended:

```text
search → read lock
add/remove/save → write lock
```

If a read/write lock is unnecessarily complex for the project, use a single `RLock` around all FAISS operations consistently.

Required invariant:

> FAISS index and vector ID mapping must always represent the same logical state.

Tests must deliberately perform:

- search during indexing
- search during save
- delete during search
- multiple indexing workers

---

# 28. UI/UX Design Rules

## Preserve existing UI

Do not redesign:

- File Explorer
- Preview Panel
- Indexed Files layout
- navigation system
- existing Batch 2 analysis dialog

## Extend existing AI menu

Recommended:

```text
AI
├── Analyze File
├── View Analysis
├── Regenerate Analysis
├── ─────────────────
├── Ask AI about this File
├── Semantic Search
└── ─────────────────
   Multimodal Search
```

If context-specific actions are useful:

```text
Image:
AI → Ask AI about Image

Audio:
AI → Ask AI about Audio

Video:
AI → Ask AI about Video
```

Avoid duplicate actions when the generic action can adapt to modality.

---

# 29. Search UI

Extend the current Semantic Search dialog.

Recommended layout:

```text
┌───────────────────────────────────────────────┐
│ Search                                        │
│ [ database architecture              ] [🔍]  │
│                                               │
│ Type: [All ▼]                                 │
│ Scope: [Current Folder ▼]                     │
│                                               │
│ Results                                       │
│                                               │
│ 📄 result 1                                   │
│ Page 43                                        │
│ snippet...                                     │
│ Similarity: 0.91                              │
│ [Open Evidence]                               │
│                                               │
│ 🎬 result 2                                   │
│ 07:56                                          │
│ snippet...                                     │
│ Similarity: 0.88                              │
└───────────────────────────────────────────────┘
```

Do not add excessive UI controls.

---

# 30. Processing UX

Every heavy operation must provide:

- current stage
- progress where meaningful
- cancel
- success
- failure
- retry where safe

Example:

```text
Indexing lecture.mp4

✓ Extracting audio
✓ Transcribing
→ Processing keyframes
○ Creating embeddings
○ Saving index

[Cancel]
```

For operations where percentage is impossible to estimate, use an indeterminate progress indicator plus stage text.

---

# 31. Cancellation Requirements

Cancellation must be cooperative.

Every long-running operation should periodically check:

```python
if cancel_event.is_set():
    return
```

Required for:

- OCR batches
- Whisper
- video frame extraction
- vision calls
- embedding batches
- FAISS indexing
- multimodal folder indexing

Tests must confirm:

1. cancellation request returns
2. UI remains responsive
3. worker terminates
4. partial database state is cleaned up
5. partial vectors do not remain orphaned

---

# 32. Resource Management

Given the hardware:

## Model loading

Use lazy loading.

## Model reuse

Reuse a loaded model during one batch operation.

## Model release

Release large models after long operations where practical.

## Concurrency

Default multimodal heavy processing to one heavy media task at a time.

Do not launch six simultaneous Whisper processes simply because `max_threads=6`.

The thread pool is general-purpose; heavy-model concurrency must be separately controlled.

---

# 33. Test Strategy

The current baseline is:

```text
180 tests
180 passed
0 failed
```

This must remain true after every milestone.

---

# 34. Unit Test Matrix

## OCR

- valid image
- empty image
- corrupt image
- OCR unavailable
- confidence extraction
- Unicode text
- multiline text

## Vision

- valid image
- diagram
- screenshot
- chart
- empty response
- invalid response
- model unavailable
- timeout

## Audio

- valid MP3
- valid WAV
- empty audio
- corrupted audio
- timestamp generation
- Whisper failure
- cancellation

## Video

- valid MP4
- audio extraction
- keyframe extraction
- frame caption
- OCR
- no audio
- corrupted video
- cancellation

## ContentEngine

- document blocks
- image blocks
- audio blocks
- video blocks
- embedded images
- provenance
- modality
- timestamps

## EvidenceEngine

- chunking
- overlap
- source tracking
- timestamp preservation
- hash preservation

## EmbeddingEngine

- single embedding
- batch embedding
- fallback
- Ollama unavailable
- dimension mismatch

## VectorEngine

- add
- batch add
- search
- threshold
- delete
- persistence
- reload
- concurrent access

## EngineDBStore

- evidence insert
- evidence retrieval
- vector mapping insert
- vector mapping retrieval
- search history
- duplicate prevention
- transaction rollback

## RetrievalEngine

- single modality
- multimodal
- scope
- file filter
- ranking
- evidence hydration
- restart retrieval
- stale vector handling

---

# 35. Integration Test Matrix

## IT-01 — Image indexing

```text
Image
→ OCR
→ Vision
→ ContentBlock
→ Evidence
→ Embedding
→ FAISS
→ DB
→ Search
```

Expected: image appears in semantic search.

## IT-02 — Scanned PDF

```text
Scanned PDF
→ page rendering
→ OCR
→ evidence
→ search
```

Expected: OCR text is searchable with correct page.

## IT-03 — Embedded PPTX image

Expected:

```text
PPTX
→ Slide text
+
embedded image OCR/vision
→ evidence
```

Search should return slide/image evidence.

## IT-04 — Audio

```text
Audio
→ Whisper
→ timestamps
→ evidence
→ search
```

Expected: result contains timestamp.

## IT-05 — Video

```text
Video
→ transcript
+
keyframes
→ evidence
→ search
```

Expected: transcript or visual result returned.

## IT-06 — Ask AI Image

Expected grounded answer using OCR/vision context.

## IT-07 — Ask AI Audio

Expected answer using transcript.

## IT-08 — Ask AI Video

Expected answer using transcript + visual evidence.

## IT-09 — Unified Search

Query returns mixed:

```text
PDF
PNG
MP3
MP4
```

in one ranked list.

## IT-10 — Restart Persistence

```text
Index
→ close application
→ reopen
→ search
```

Expected: results still available.

## IT-11 — Modify File

```text
Index
→ modify
→ watcher
→ old evidence removed
→ new evidence indexed
```

## IT-12 — Delete File

Expected no stale search result.

## IT-13 — Rename File

Expected evidence path updates while hash identity remains.

## IT-14 — Move File

Expected evidence path updates.

## IT-15 — Ollama unavailable

Expected graceful UI error.

## IT-16 — Whisper unavailable

Expected graceful error and no corrupt index.

## IT-17 — Vision unavailable

OCR-only fallback where possible.

## IT-18 — Cancellation

Cancel large video indexing.

Expected:

- worker stops
- UI remains responsive
- no partial orphan vectors

---

# 36. Regression Test Matrix

After every Batch 3 milestone run:

```bash
venv/bin/python3 -m pytest tests/ -q
```

Mandatory existing functionality:

- folder browsing
- navigation
- rename
- copy
- move
- delete
- preview
- metadata
- extracted text
- scan folder
- watcher
- Batch 2 analysis
- Semantic Search
- Ask AI

No regression is acceptable.

---

# 37. UI Test Matrix

Using pytest-qt where applicable:

### Search

- open search
- submit query
- filter All
- filter Documents
- filter Images
- filter Audio
- filter Video
- empty query
- no results

### Result interaction

- select result
- double click
- Open Evidence
- keyboard navigation
- close dialog

### Image

- Ask AI
- processing dialog
- success
- failure

### Audio

- seek timestamp
- invalid timestamp
- missing file

### Video

- seek timestamp
- play from evidence
- missing video

### Cancellation

- cancel OCR
- cancel Whisper
- cancel video indexing

---

# 38. Error / Recovery Acceptance Tests

Every failure must satisfy:

```text
No crash
+
No frozen UI
+
Useful user message
+
Logged technical error
+
No corrupted persistent state
```

Specific cases:

- Ollama server stopped
- wrong LLM model
- wrong vision model
- Whisper unavailable
- FFmpeg unavailable
- corrupt image
- corrupt audio
- corrupt video
- corrupt PDF
- permission denied
- deleted file during indexing
- disk becomes full
- FAISS file corrupted
- database unavailable

---

# 39. Disk-Space Safety

Current free disk is approximately 4.8 GiB.

Implement safeguards:

Before expensive indexing:

```text
check available disk
```

If insufficient:

```text
Do not start
Show:
"Insufficient disk space for indexing."
```

Do not automatically download models.

Do not create duplicate copies of media.

Temporary media files must be deleted in `finally`.

Tests should simulate low-disk conditions using a mocked disk-space provider.

---

# 40. Configuration Tests

Verify that changing:

- model name
- Ollama URL
- Whisper model
- chunk size
- overlap
- top-k
- threshold

actually changes runtime behavior.

No hard-coded duplicate configuration should remain in the multimodal path.

---

# 41. Performance Tests

Formal performance baseline currently does not exist.

Create a small controlled benchmark suite.

Test:

1. 10 text documents
2. 10 images
3. 3 short audio files
4. 2 short videos
5. mixed repository

Measure:

- extraction time
- OCR time
- transcription time
- vision time
- embedding time
- FAISS indexing time
- search latency
- memory before/after
- database size
- FAISS index size

Do not define unrealistic hard performance requirements before measuring.

Record baseline numbers after implementation.

---

# 42. Implementation Milestones

## Milestone 0 — Regression Baseline

Tasks:

- run existing 180 tests
- confirm 180/180
- confirm clean working tree
- record current database counts
- record current FAISS size

Gate:

> Existing application passes all tests.

---

## Milestone 1 — Persistence Foundation

Implement:

- EngineDBStore wiring
- evidence persistence
- vector_map persistence
- startup hydration
- search history
- atomic index state
- stale-vector cleanup foundation

Tests:

- persistence
- restart
- deletion
- modification
- rename

Gate:

> Semantic search survives application restart.

---

## Milestone 2 — Configuration and Index Consistency

Implement:

- central model configuration
- central Ollama URL
- extension registry
- Whisper configuration
- Vision configuration
- FAISS locking
- duplicate prevention

Gate:

> One authoritative configuration path and consistent FAISS/evidence state.

---

## Milestone 3 — Embedded Document Images

Implement:

- PDF image extraction
- PPTX image extraction
- DOCX image extraction
- OCR
- Vision
- provenance
- indexing

Gate:

> Text and embedded images from documents are searchable.

---

## Milestone 4 — Image Intelligence

Complete:

- B3-01
- B3-02
- B3-03
- B3-04

Gate:

> A user can select an image, ask questions about it, and retrieve it through semantic search.

---

## Milestone 5 — Audio Intelligence

Complete:

- B3-05
- B3-06
- B3-07
- B3-08

Gate:

> Audio can be transcribed, searched, questioned and navigated by timestamp.

---

## Milestone 6 — Video Intelligence

Complete:

- B3-09
- B3-10
- B3-11
- B3-12

Gate:

> Video can be searched and questioned using both speech and visual evidence.

---

## Milestone 7 — Unified Evidence UI

Complete:

- B3-13
- B3-15
- B3-16

Gate:

> Every search result exposes useful modality-specific evidence and navigation.

---

## Milestone 8 — Unified Multimodal Search

Complete:

- B3-14

Gate:

> One search interface returns ranked results from all supported modalities.

---

## Milestone 9 — Full Regression

Run:

- all existing tests
- all new unit tests
- integration tests
- UI tests
- persistence tests
- cancellation tests
- failure tests
- performance benchmarks

Gate:

> No regression + all Batch 3 acceptance tests pass.

---

# 43. Final Batch 3 Acceptance Criteria

Batch 3 is complete only when all of the following are true.

## User-facing

- [ ] Image intelligence works
- [ ] OCR search works
- [ ] Vision understanding works
- [ ] Ask AI about Image works
- [ ] Audio intelligence works
- [ ] Audio semantic search works
- [ ] Ask AI about Audio works
- [ ] Audio timestamp navigation works
- [ ] Video intelligence works
- [ ] Video semantic search works
- [ ] Ask AI about Video works
- [ ] Video timestamp navigation works
- [ ] Evidence navigation works
- [ ] Unified multimodal search works
- [ ] Unified evidence results work
- [ ] Match strength/similarity explanation works

## Backend

- [ ] Evidence is persisted
- [ ] Vector mappings are persisted
- [ ] Evidence hydrates on startup
- [ ] FAISS and DB remain consistent
- [ ] File modification removes stale vectors
- [ ] File deletion removes stale vectors
- [ ] Rename/move updates paths
- [ ] Embedded document images are processed
- [ ] OCR is integrated
- [ ] Vision is integrated
- [ ] Whisper is integrated
- [ ] video keyframes are integrated
- [ ] all modalities use the common ContentBlock model
- [ ] all modalities use the common retrieval pipeline

## UI/UX

- [ ] Existing Explorer remains intact
- [ ] Existing Preview remains intact
- [ ] Existing Batch 2 UI remains intact
- [ ] search supports All/Documents/Images/Audio/Video
- [ ] result cards show modality
- [ ] result cards show source location
- [ ] result cards show similarity
- [ ] evidence navigation works
- [ ] processing is cancellable
- [ ] errors are understandable
- [ ] UI remains responsive

## Testing

- [ ] Existing 180 tests remain passing
- [ ] all new unit tests pass
- [ ] all integration tests pass
- [ ] all persistence tests pass
- [ ] UI tests pass
- [ ] cancellation tests pass
- [ ] failure/recovery tests pass
- [ ] multimodal search tests pass
- [ ] restart tests pass
- [ ] performance baseline recorded

---

# 44. Definition of Done

Batch 3 must NOT be considered complete merely because:

- OCR works
- Whisper works
- Vision works
- FAISS works
- the engines have unit tests

The actual completion condition is:

> **A user can place documents, images, audio and video into an indexed folder, search them using natural language, receive a ranked unified result list, understand why each result matched, navigate directly to the relevant page/image/timestamp, and ask AI questions about the selected content — with the indexed knowledge surviving application restart.**

The application must also remain responsive and must not lose or corrupt existing Batch 1/Batch 2 functionality.

---

# 45. Recommended Implementation Order Summary

```text
                    BATCH 3
                       │
                       ▼
             ┌──────────────────┐
             │ 0. Baseline      │
             └────────┬─────────┘
                      ▼
             ┌──────────────────┐
             │ 1. Persistence   │
             └────────┬─────────┘
                      ▼
             ┌──────────────────┐
             │ 2. Consistency   │
             └────────┬─────────┘
                      ▼
             ┌──────────────────┐
             │ 3. Embedded      │
             │    Images        │
             └────────┬─────────┘
                      ▼
             ┌──────────────────┐
             │ 4. Images        │
             └────────┬─────────┘
                      ▼
             ┌──────────────────┐
             │ 5. Audio         │
             └────────┬─────────┘
                      ▼
             ┌──────────────────┐
             │ 6. Video         │
             └────────┬─────────┘
                      ▼
             ┌──────────────────┐
             │ 7. Evidence UI   │
             └────────┬─────────┘
                      ▼
             ┌──────────────────┐
             │ 8. Unified       │
             │    Search        │
             └────────┬─────────┘
                      ▼
             ┌──────────────────┐
             │ 9. Full Audit    │
             └──────────────────┘
```

This order intentionally fixes persistence and indexing consistency **before** exposing more multimodal functionality. Otherwise, the new image/audio/video features would be built on top of an evidence layer that currently disappears after restart.

---

# 46. Final Engineering Principles

1. **Extend existing engines before creating replacements.**
2. **One ContentBlock model for every modality.**
3. **One Evidence model for every modality.**
4. **One EmbeddingEngine for textual evidence.**
5. **One RetrievalEngine for semantic retrieval.**
6. **FAISS is the retrieval accelerator, not the permanent evidence database.**
7. **SQLite is the persistent source of evidence metadata.**
8. **Do not store raw media in SQLite.**
9. **Keep UI orchestration in MainWindow only where consistent with the existing architecture; heavy business logic remains in services/engines.**
10. **Never block the PySide6 GUI thread.**
11. **All expensive operations must be cancellable.**
12. **Do not claim calibrated confidence from raw cosine similarity.**
13. **Every result must retain provenance.**
14. **Every file change must synchronize the retrieval index.**
15. **Every Batch 3 milestone must pass the complete existing regression suite.**
16. **Do not start Batch 4/future-scope features until this Batch 3 definition of done is satisfied.**

---

# 47. Primary Files / Areas Expected to Change

### High priority

```text
engines/db_store.py
engines/ai_indexer.py
engines/retrieval_engine.py
engines/content_engine.py
engines/config.py
app/container.py
ui/main_window.py
widgets/file_explorer.py
ui/dialogs/semantic_search_dialog.py
ui/dialogs/ask_ai_dialog.py
```

### Multimodal

```text
extractors/image_extractor.py
extractors/audio_extractor.py
extractors/video_extractor.py
vision/ocr_engine.py
vision/vision_engine.py
vision/content_merger.py
speech/speech_engine.py
video/video_engine.py
video/keyframe_engine.py
```

### Potential new UI/service components

Only create these if the existing classes cannot cleanly support the functionality:

```text
ui/dialogs/evidence_viewer_dialog.py
ui/widgets/search_result_widget.py
services/evidence_navigator.py
```

Do not create duplicate retrieval, embedding, OCR, or media pipelines.

---

# 48. Final Implementation Rule

Before modifying any file:

1. Read its current implementation.
2. Identify existing tests.
3. Make the smallest architectural change required.
4. Implement the feature.
5. Run focused tests.
6. Run the full regression suite.
7. Verify UI behavior.
8. Verify persistence/restart behavior.
9. Only then proceed to the next milestone.

The objective is not merely to add 16 features.

The objective is to finish Batch 3 as a **stable, persistent, multimodal, evidence-aware retrieval layer integrated into the existing IntelliVault application without regression.**
