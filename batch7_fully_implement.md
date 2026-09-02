# IntelliVault — Batch 7 Complete Implementation Plan

**Basis:** Post-Batch-6 Comprehensive Audit (`batch7_audit_report.md`)  
**Current baseline:** Batch 6 complete, schema v9, 392 tests passing  
**Scope:** 10 NOT IMPLEMENTED features + completion of 1 PARTIAL feature

## 1. Executive Summary

The audit establishes:

- 20/31 features fully implemented
- 1/31 feature partial: **Folder Intelligence (Folder Metadata)**
- 10/31 features not implemented
- 0 broken
- 0 unverified
- 392 tests passed, 0 failed, 0 skipped, 0 errors
- Batch 6 completed all five assigned partial features

The earlier assumption that Batch 7 contained seven features is not supported by the current codebase. The correct Batch 7 scope is:

1. Reverse Image Search
2. Object Detection
3. Metadata Export (JSON/CSV)
4. Image Quality Analysis
5. Document Comparison
6. Metadata Editor
7. File Timeline View
8. AI-Powered Folder Summary
9. Automatic File Renaming
10. AI Image Filtering
11. Completion of Folder Intelligence (Folder Metadata)

Batch 7 should extend the existing architecture rather than replace Batch 1–6 infrastructure.

---

## 2. Non-Negotiable Rules

### Preserve existing infrastructure

Reuse and extend:

- ContentEngine
- EvidenceEngine
- EmbeddingEngine
- VectorEngine
- RetrievalEngine
- RAGEngine
- CLIPEngine
- VisionEngine
- ClassificationEngine
- TaggingEngine
- CollectionEngine
- SuggestionEngine
- FileMover
- FileCleanup
- FolderClassificationService
- ConversationService
- DashboardService
- AIResourceManager
- TaskManager
- SignalBus

Do not create duplicate engines/services when an existing component can safely be extended.

### Preserve file identity

SHA-256 remains the canonical file identity.

### Safe filesystem operations

Any rename must:

- require explicit approval
- show a preview
- validate the target name
- prevent overwrite
- handle collisions
- preserve SHA-256
- synchronize indexed paths, evidence, vectors, relationships, collections and suggestions

Reuse `file_mover.py`.

### Local AI only

No cloud AI/API calls. Use existing Ollama, CLIP and RAG infrastructure. New models must be local and suitable for the hardware target.

### GUI responsiveness

Heavy operations must use the existing task/thread/resource-management infrastructure and never block the Qt GUI thread.

---

# 3. Pre-Batch-7 Preparation

## 3.1 Dependency/package cleanup

The audit identified optional/undeclared dependencies including:

- FAISS
- sentence-transformers
- torch
- transformers/CLIP
- openai-whisper
- pytesseract
- OpenCV
- ffmpeg
- tesseract
- requests

Do not blindly make every optional AI dependency mandatory. Organize dependencies into appropriate optional extras where practical.

## 3.2 Fix package discovery

The audit found that `pyproject.toml` does not include newer packages such as:

- conversation
- graph
- agent
- vision
- speech
- video
- extractors

Fix package discovery before treating the project as distribution-ready.

## 3.3 Task-table hygiene

The live `tasks` table contains 6,626 rows.

Introduce safe pruning/archiving of old completed task records while retaining active/recent tasks. Do not break existing task functionality.

## 3.4 Migration preparation

Prepare migration v10 only for schema changes actually required by implementation.

Potential fields:

- `ai_analysis.objects_json`
- `ai_analysis.quality_score`
- `ai_analysis.quality_json`
- folder-summary fields on `folder_classifications`

Potential table:

- `timeline_events`

Do not add speculative schema.

---

# 4. Recommended Batch 7 Architecture

Group the work into:

### Group A — Metadata / Documents
- Metadata Export
- Metadata Editor
- Document Comparison

### Group B — File Management
- File Timeline
- Automatic File Renaming

### Group C — Image Intelligence
- Image Quality Analysis
- Object Detection
- AI Image Filtering
- Reverse Image Search

### Group D — Folder Intelligence
- Folder Intelligence completion
- AI-Powered Folder Summary

Recommended implementation order:

```text
Metadata Export
      ↓
Metadata Editor
      ↓
File Timeline
      ↓
Image Quality Analysis
      ↓
Object Detection
      ↓
AI Image Filtering
      ↓
Reverse Image Search
      ↓
Document Comparison
      ↓
Folder Intelligence completion
      ↓
AI-Powered Folder Summary
      ↓
Automatic File Renaming
      ↓
Full Batch-7 Audit
```

---

# 5. Feature 1 — Metadata Export (JSON/CSV)

## Objective

Export IntelliVault metadata for the workspace, current folder, or selected files.

## Reuse

- indexed_files
- ai_analysis
- repository queries
- dashboard_service
- classification/tagging metadata

## Backend

Create:

`services/metadata_export_service.py`

Support:

- JSON
- CSV
- workspace scope
- folder scope
- selected-file scope
- UTF-8
- stable columns
- null handling
- safe output names

Suggested export fields:

- path
- filename
- extension
- MIME type
- size
- created/modified times
- SHA-256
- category
- tags
- language
- caption
- relevant metadata

Do not export private/internal fields unnecessarily.

## UI

Add:

`Tools → Export Metadata`

Provide:

- scope
- format
- destination
- progress for large exports
- success/error state

## Tests

Test JSON validity, CSV quoting, UTF-8, empty values, selection/folder/workspace scopes and AI metadata fields.

---

# 6. Feature 2 — Metadata Editor

## Objective

Allow manual editing of supported user-facing metadata.

## Critical rule

Separate user-edited metadata from AI-generated metadata. Manual edits must not silently overwrite AI-generated values.

## Backend

Create:

`services/metadata_editor_service.py`

Reuse existing metadata storage where safe. If schema separation is needed, introduce a controlled v10 migration.

Support fields such as:

- title
- description
- notes
- user tags
- custom metadata

## UI

Add `Edit Metadata` from preview/context actions.

Provide:

- editable fields
- validation
- Save
- Cancel
- clear distinction between user and AI metadata

## Synchronization

Metadata editing must preserve SHA-256, evidence and embeddings unless a deliberately searchable field requires re-indexing.

## Tests

Save, cancel, validation, persistence, restart, rename/move persistence and AI-metadata isolation.

---

# 7. Feature 3 — File Timeline View

## Objective

Provide a chronological view of available file activity.

## Backend

Create:

`services/timeline_service.py`

Use:

- indexed_files dates
- recent
- file watcher data
- filesystem timestamps

If historical event tracking is required, add `timeline_events` through migration v10.

Do not fabricate historical events that were never recorded. Clearly distinguish filesystem dates from recorded IntelliVault events.

## UI

Add:

`Tools → File Timeline`

Support:

- chronological grouping
- date filters
- folder filters
- file-type filters
- event filters
- search
- open/navigate to file

## Tests

Ordering, filters, empty states, duplicate events, rename/move behavior and persistence.

---

# 8. Feature 4 — Image Quality Analysis

## Objective

Provide transparent local image-quality analysis.

Recommended deterministic metrics:

- resolution
- width/height
- aspect ratio
- sharpness/blur
- contrast
- brightness/exposure
- file size
- optional noise estimate

Generate:

- quality score
- quality label
- metric breakdown

## Backend

Create:

`services/image_quality_service.py`

Reuse existing image extraction and local image-processing libraries. Do not require an LLM for basic quality metrics.

## Database

Persist quality data if required using migration v10.

## UI

Add:

`Image → AI → Analyze Image Quality`

Display:

- score
- resolution
- sharpness
- exposure
- contrast
- label

## Tests

Use deterministic fixture images: sharp, blurred, low/high contrast, small and high-resolution, invalid images.

---

# 9. Feature 5 — Object Detection

## Objective

Replace the current `VisionResult.objects == []` stub with genuine object detection.

## Model strategy

Prefer a local detector. Candidate approaches:

- existing Ollama vision model with structured JSON
- dedicated local detector such as a YOLO-family model

Choose based on local operation, hardware, model size, reliability and structured output.

## Backend

Extend `vision/vision_engine.py` or create:

`services/object_detection_service.py`

Return:

- label
- confidence
- bounding box where supported

Example structure:

```json
{
  "label": "person",
  "confidence": 0.94,
  "box": [x1, y1, x2, y2]
}
```

## Persistence

Persist structured object information, e.g. `objects_json`, via migration v10 if required.

## UI

Display:

- detected objects
- confidence
- optional bounding boxes
- object count

## Tests

Valid images, no-object images, multiple objects, malformed output, missing model, thresholding and persistence.

---

# 10. Feature 6 — AI Image Filtering

## Objective

Allow filtering images using AI-derived visual attributes.

Examples:

- images containing dogs
- images with people
- screenshots
- images containing text
- landscapes
- cars
- blurry images
- images with particular visual concepts

## Architecture

```text
User Query
   ↓
Filter Parsing
   ↓
Existing AI Metadata
   ↓
Object / Caption / CLIP / Quality Data
   ↓
Candidate Filtering
   ↓
Semantic Ranking
   ↓
Results
```

Prefer existing indexed AI metadata over running expensive inference during every search.

## Reuse

- CLIP
- VisionEngine
- captions
- object detection
- quality analysis
- semantic retrieval
- smart collections

## UI

Extend Semantic Search/image search with AI image filters.

Support where data is available:

- objects
- scenes
- captions
- quality
- text presence
- semantic concepts

## Tests

Object filters, caption filters, semantic filters, quality filters, combined filters, folder scope and no-result behavior.

---

# 11. Feature 7 — Reverse Image Search

## Objective

Find visually similar indexed images from a query image.

This is distinct from Natural Language Image Search:

```text
Reverse Image Search:
image → image

Natural Language Image Search:
text → image
```

## Reuse

The audit confirms `CLIPEngine.embed_image()` already exists and is currently used for indexing. Add the missing query path.

## Backend

Extend retrieval with something equivalent to:

`search_by_image(image_path)`

Pipeline:

```text
Query Image
    ↓
CLIP embed_image()
    ↓
FAISS
    ↓
Image vectors
    ↓
Rank results
    ↓
Evidence/file results
    ↓
UI
```

Do not create a second vector database.

## UI

Add a reverse-image-search action with:

- image picker
- preview
- similarity threshold
- result limit
- folder scope
- similarity scores

## Tests

Identical, resized, similar and unrelated images; empty index; missing CLIP; ranking and scope.

---

# 12. Feature 8 — Document Comparison

## Objective

Turn the existing agent comparison capability into a complete user-facing document comparison feature.

## Reuse

- RAGEngine
- RetrievalEngine
- EvidenceEngine
- citation builder
- existing agent comparison tool
- document extractors

## Backend

Create:

`services/document_comparison_service.py`

Provide:

### Structural comparison
- format
- page/section counts
- word counts
- headings
- available table information

### Textual comparison
- added text
- removed text
- changed text
- common text

### Semantic comparison
Use the existing local LLM/RAG to explain meaningful changes.

Clearly distinguish deterministic differences from AI interpretation.

## UI

Create:

`Document Comparison Dialog`

Workflow:

```text
Select Document A
Select Document B
        ↓
Compare
        ↓
Structural Results
Textual Differences
Semantic Summary
        ↓
Evidence/page references
```

Start with PDF/DOCX/TXT according to current extraction support.

## Tests

Identical docs, additions, removals, changed sections, reordered content, unsupported formats and missing evidence.

---

# 13. Feature 9 — Complete Folder Intelligence (Partial Feature)

## Current gap

The existing Folder Intelligence dialog provides classification composition but lacks general folder metadata.

Add:

- total files
- total size
- file-type distribution
- extension distribution
- oldest file
- newest file
- date range
- top keywords
- top categories
- classified/unclassified counts
- major topics where available

## Backend

Prefer a dedicated:

`services/folder_intelligence_service.py`

if `folder_classification.py` would otherwise become too broad.

Reuse folder classification data and indexed file metadata.

## UI

Expand Folder Intelligence into sections:

```text
Overview
Statistics
File Types
AI Classification
Keywords
Date Range
Topics
```

Basic statistics must work even without an LLM.

## Tests

Empty folder, mixed files, nested folders, missing files, classification data, refresh and persistence.

---

# 14. Feature 10 — AI-Powered Folder Summary

## Objective

Generate a grounded natural-language summary of a folder.

## Reuse

- folder classification
- folder intelligence statistics
- classification/tagging
- ConversationService
- RAGEngine
- EvidenceEngine
- existing local LLM

## Architecture

```text
Folder
 ↓
Folder Statistics
 ↓
Classifications / Tags
 ↓
Indexed Evidence
 ↓
RAG
 ↓
LLM
 ↓
Grounded Summary
 ↓
Persistence
 ↓
UI
```

Summary may cover:

- folder contents
- dominant topics
- major categories
- file types
- approximate size
- notable patterns
- optional observations

Do not allow unsupported claims.

## UI

Extend Folder Intelligence:

`Generate AI Summary`

Provide:

- summary
- generated time
- model
- regenerate
- copy

If the folder has not been indexed for AI, explain the prerequisite instead of generating unsupported content.

## Persistence

Potential v10 fields:

- summary
- summary_model
- summary_version
- summarized_at

## Tests

Mocked LLM generation, no evidence, Ollama unavailable, regeneration, persistence, restart and folder changes.

---

# 15. Feature 11 — Automatic File Renaming

## Objective

Generate meaningful filenames from existing metadata and let the user approve them safely.

## Reuse

- ClassificationEngine
- TaggingEngine
- captions
- document metadata
- FileMover
- FileIdentity

## Backend

Create:

`services/rename_suggestion_service.py`

Use:

- category
- tags
- title
- caption
- date
- file type
- existing filename

Generate a proposed name but never rename automatically without approval.

## Validation

Reject:

- empty names
- invalid filesystem characters
- path traversal
- collisions
- dangerous names
- unintended extension changes
- excessive lengths

## UI

Create a Rename Preview dialog:

| Current Name | Proposed Name | Status |
|---|---|---|

Actions:

- Approve Selected
- Approve All
- Cancel

## Execution

Reuse `file_mover.py`.

The rename must preserve and synchronize:

- SHA-256
- indexed_files
- evidence
- vector mappings
- relationships
- collections
- organization suggestions
- duplicate suggestions

## Tests

Valid rename, collision, invalid name, same name, batch rename, cancel, restart, synchronization and SHA-256 preservation.

---

# 16. Database Migration v10

Use one controlled migration for Batch 7 schema changes.

Potential additions:

```text
ai_analysis.objects_json
ai_analysis.quality_score
ai_analysis.quality_json

folder_classifications.summary
folder_classifications.summary_model
folder_classifications.summary_version
folder_classifications.summarized_at
```

Potential table:

```text
timeline_events
```

Only create fields/tables actually used by the final implementation.

Migration requirements:

- v9 → v10 works
- existing rows remain valid
- safe defaults/nullability
- fresh DB reaches the same schema
- restart persistence works
- Batch 1–6 tables remain intact

---

# 17. Signal Bus Integration

Add signals only when needed for actual UI synchronization.

Possible signals:

- metadata_updated
- image_quality_updated
- objects_updated
- timeline_updated
- folder_summary_updated
- rename_completed

Every new signal must have a real consumer. Avoid signal proliferation.

---

# 18. Configuration

Add only useful user-facing settings.

Potential settings:

```text
batch7.image_quality_enabled
batch7.object_detection_enabled
batch7.object_detection_model
batch7.object_detection_threshold
batch7.reverse_image_similarity_threshold
batch7.image_filter_threshold
batch7.folder_summary_enabled
batch7.rename_pattern
batch7.timeline_event_retention
```

Optional AI features must fail gracefully when their dependencies/models are unavailable.

---

# 19. Testing Strategy

Every Batch 7 feature must have:

### Unit tests
- parsing
- serialization
- validation
- scoring
- service logic

### Integration tests
- database
- migration
- FAISS
- RAG
- synchronization
- persistence

### UI tests
- dialogs
- actions
- validation
- empty states
- error states

### Regression tests

All existing Batch 1–6 tests must continue to pass.

Baseline:

```text
392 existing tests
+
Batch 7 tests
=
all passing
```

No skipped tests may be used to hide incomplete features.

---

# 20. Performance Requirements

Avoid unnecessary AI inference.

### Image filtering

```text
Existing metadata
      ↓
Cheap filtering
      ↓
CLIP/Vision only if required
```

### Folder summary

```text
Existing statistics
      ↓
Existing classifications/tags
      ↓
Existing evidence
      ↓
LLM
```

### Reverse image search

```text
One query image embedding
      ↓
FAISS search
```

Do not regenerate indexed image embeddings.

---

# 21. Error Handling

Every Batch 7 feature must gracefully handle:

- missing model
- Ollama unavailable
- missing optional dependency
- corrupted image
- unsupported document
- empty folder
- empty FAISS index
- no AI evidence
- invalid export path
- permission errors
- filename collision
- invalid rename
- malformed LLM output
- cancellation
- timeouts

No GUI crash.

---

# 22. Security and Privacy

All processing remains local.

Do not introduce:

- cloud image APIs
- cloud OCR
- cloud LLMs
- telemetry
- external file uploads

Filesystem-changing operations require explicit approval.

---

# 23. Milestones

## Milestone 0 — Preparation

- dependency/package cleanup
- task-table hygiene
- migration design

Acceptance: application boots and all existing tests pass.

## Milestone 1 — Metadata

- Metadata Export
- Metadata Editor

## Milestone 2 — File History

- File Timeline

## Milestone 3 — Image Quality

- Image Quality Analysis

## Milestone 4 — Object Intelligence

- Object Detection

## Milestone 5 — Image Retrieval

- AI Image Filtering
- Reverse Image Search

## Milestone 6 — Document Intelligence

- Document Comparison

## Milestone 7 — Folder Intelligence

- complete Folder Intelligence
- AI-Powered Folder Summary

## Milestone 8 — Safe File Management

- Automatic File Renaming

## Milestone 9 — Full Integration

Verify:

- UI
- database
- FAISS
- synchronization
- dashboard
- restart
- watcher
- TaskManager
- AIResourceManager

## Milestone 10 — Final Audit

Run:

- complete test suite
- headless boot
- migration verification
- persistence checks
- regression audit
- full 31-feature audit

---

# 24. Acceptance Criteria

A feature is COMPLETE only when:

```text
Backend
+
UI
+
Persistence
+
Integration
+
Runtime behavior
+
Error handling
+
Tests
```

are sufficiently complete.

A class, database table, or UI button alone does not constitute implementation.

---

# 25. Final Feature Matrix

| # | Feature | Group | Primary Reuse | Main New Work |
|---|---|---|---|---|
| 6 | Reverse Image Search | Image | CLIP + FAISS | image query path + UI |
| 8 | Object Detection | Image | VisionEngine | detector + persistence + UI |
| 15 | Metadata Export | Metadata | Repository + Dashboard | export service + UI |
| 20 | Image Quality Analysis | Image | Image extractor | quality service + persistence |
| 21 | Document Comparison | Document | RAG + Evidence | comparison service + UI |
| 23 | Metadata Editor | Metadata | Preview + DB | edit service + UI |
| 26 | File Timeline View | File Management | indexed_files + watcher | timeline service + UI |
| 27 | AI-Powered Folder Summary | Folder | Folder Intelligence + RAG | summary service + persistence |
| 28 | Automatic File Renaming | File Management | FileMover + classification/tagging | rename suggestions + preview |
| 30 | AI Image Filtering | Image | CLIP + collections + vision | filter pipeline + UI |
| 31 | Folder Intelligence Metadata | Folder | Folder Classification | general folder statistics |

---

# 26. Final Definition of Done

Batch 7 is complete only when these are all complete:

- [ ] Reverse Image Search
- [ ] Object Detection
- [ ] Metadata Export
- [ ] Image Quality Analysis
- [ ] Document Comparison
- [ ] Metadata Editor
- [ ] File Timeline View
- [ ] AI-Powered Folder Summary
- [ ] Automatic File Renaming
- [ ] AI Image Filtering
- [ ] Folder Intelligence Metadata

And:

- [ ] schema migration verified
- [ ] restart persistence verified
- [ ] synchronization verified
- [ ] UI integration verified
- [ ] all tests pass
- [ ] no Batch 1–6 regression
- [ ] local/offline processing preserved
- [ ] destructive actions remain approval-based
- [ ] optional dependencies fail gracefully
- [ ] final 31-feature audit reports 31/31 complete

---

# 27. Final Development Flow

```text
Post-Batch-6 Audit
        ↓
Preparation
        ↓
Metadata Export
        ↓
Metadata Editor
        ↓
File Timeline
        ↓
Image Quality Analysis
        ↓
Object Detection
        ↓
AI Image Filtering
        ↓
Reverse Image Search
        ↓
Document Comparison
        ↓
Folder Intelligence Completion
        ↓
AI Folder Summary
        ↓
Automatic File Renaming
        ↓
Full Integration
        ↓
Full Test Suite
        ↓
Post-Batch-7 Comprehensive Audit
        ↓
31 / 31 Features Complete
```

## Final Scope Decision

The audit explicitly disproves the earlier assumption of seven remaining features.

The verified state is:

```text
20 COMPLETE
1 PARTIAL
10 NOT IMPLEMENTED
```

Therefore Batch 7 should complete the actual remaining inventory:

```text
10 new features
+
1 partial feature completion
=
11 feature completions
```

Do not artificially remove features merely to preserve the old seven-feature assumption.

## Final instruction to the implementing AI

Implement incrementally by milestone.

After every milestone:

1. run relevant tests
2. run regression tests
3. verify persistence
4. verify UI integration
5. inspect logs
6. verify synchronization

Do not rewrite working Batch 1–6 engines.

Do not create duplicate infrastructure.

Do not mark a feature complete until the end-to-end workflow is verified.

At the end, generate a comprehensive Post-Batch-7 audit covering all 31 features.

Target:

**31/31 features fully implemented, tested, integrated, persistent, safe, and user-accessible.**
