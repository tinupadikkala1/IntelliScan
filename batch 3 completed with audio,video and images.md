# IntelliVault Batch 3 Completion Implementation Plan

## Objective

Complete Batch 3 by extending the existing Retrieval-Augmented
Generation architecture into a **multimodal retrieval platform** while
preserving the current stable document pipeline.

Current completed baseline: - ContentEngine - EvidenceEngine -
EmbeddingEngine (`nomic-embed-text`) - VectorEngine (FAISS) -
RetrievalEngine - RAGEngine (`qwen-local`) - Semantic Search - Ask AI
about this File

The goal is to add first-class support for **Images, Audio and Video**
without modifying downstream retrieval logic.

------------------------------------------------------------------------

# Guiding Principles

-   Preserve existing document functionality.
-   Do not redesign existing UI layouts.
-   Keep all business logic outside UI classes.
-   Every modality must produce `ContentBlock` objects.
-   No duplicate retrieval pipelines.
-   Backward compatible SQLite schema migrations.
-   Background workers for all long-running operations.
-   Every milestone must compile and pass tests before the next begins.

------------------------------------------------------------------------

# Milestone 1 -- Extractor Framework

Create:

    extractors/
        base_extractor.py
        extractor_factory.py
        document_extractor.py
        image_extractor.py
        audio_extractor.py
        video_extractor.py

All implement:

``` python
extract(path)->list[ContentBlock]
```

Acceptance: - Existing document extraction unchanged. - Factory
dispatches correctly.

------------------------------------------------------------------------

# Milestone 2 -- Image Intelligence

Supported: PNG JPG JPEG WEBP BMP TIFF GIF(first frame)

Modules

    vision/
        ocr_engine.py
        vision_engine.py
        content_merger.py

Pipeline

Image → OCR → Vision Caption → Merge → ContentBlocks

Recommended: - PaddleOCR - SmolVLM or Qwen2.5-VL

Capabilities

-   OCR text
-   Caption generation
-   Object labels
-   Diagram recognition
-   Screenshot understanding
-   Table recognition (OCR)
-   Search
-   Ask AI

------------------------------------------------------------------------

# Milestone 3 -- Audio Intelligence

Supported

MP3 WAV FLAC OGG AAC M4A

Modules

    speech/
        speech_engine.py

Pipeline

Audio → Whisper → Timestamp blocks → ContentBlocks

Capabilities

-   transcription
-   timestamps
-   semantic search
-   Ask AI

------------------------------------------------------------------------

# Milestone 4 -- Video Intelligence

Supported

MP4 MKV MOV AVI WEBM

Modules

    video/
        video_engine.py
        keyframe_engine.py

Pipeline

Video → Extract audio → Whisper → Transcript

-   

Keyframes → Vision

↓

Merge

↓

ContentBlocks

Capabilities

-   transcript search
-   timestamp citations
-   frame captions
-   Ask AI
-   semantic search

------------------------------------------------------------------------

# Milestone 5 -- Unified Content Model

Extend ContentBlock

-   id
-   text
-   modality
-   source_type
-   source_label
-   page
-   timestamp_start
-   timestamp_end
-   confidence
-   metadata

Downstream engines must remain unchanged.

------------------------------------------------------------------------

# Milestone 6 -- UI/UX

Do NOT redesign Explorer.

Maintain:

-   Context menu
-   Ask AI
-   Semantic Search

Add only:

-   Image preview AI button
-   Audio player with timestamp jump
-   Video player with timestamp jump
-   Search result icons per modality
-   Progress dialogs
-   Non-blocking notifications

UI rules

-   No new permanent dock widgets.
-   Preserve Preview Panel.
-   Preserve existing shortcuts.
-   Maintain responsive UI.

------------------------------------------------------------------------

# Milestone 7 -- Background Processing

Every modality runs in worker threads.

Stages:

Loading Extracting OCR/Transcribing Vision Chunking Embedding Indexing
Completed

Support cancellation and recovery.

------------------------------------------------------------------------

# Milestone 8 -- Database

Add migration only if needed.

Persist

-   modality
-   timestamps
-   frame ids
-   OCR confidence
-   captions
-   object labels

Do not break previous data.

------------------------------------------------------------------------

# Milestone 9 -- Testing

## Unit Tests

-   ExtractorFactory
-   ImageExtractor
-   AudioExtractor
-   VideoExtractor
-   OCREngine
-   VisionEngine (mock)
-   SpeechEngine (mock)
-   KeyframeEngine
-   ContentMerger
-   ContentBlock serialization
-   Database migrations
-   Embedding generation
-   Retrieval ranking
-   Citation mapping
-   Timestamp generation

## Integration Tests

-   Image → Ask AI
-   Image → Semantic Search
-   Audio → Ask AI
-   Audio → Semantic Search
-   Video → Ask AI
-   Video → Semantic Search
-   Mixed-modality search
-   PDF + embedded image
-   Rename preservation
-   Move preservation
-   Incremental re-index
-   Corrupted media
-   Missing Ollama
-   Missing ffmpeg
-   Invalid OCR output
-   Empty audio
-   Large video

## Regression Tests

Verify existing document features remain unchanged.

-   PDF indexing
-   DOCX indexing
-   Semantic Search
-   Ask AI
-   AI dialog
-   Existing SQLite data
-   Background indexing

## Performance Tests

-   1000+ documents
-   500 images
-   100 audio files
-   50 videos
-   Memory usage
-   Index build time
-   Search latency

## UI Tests

-   No freezes
-   Progress dialogs appear
-   Dialog sizing
-   Theme compatibility
-   Keyboard navigation
-   Context menus
-   Accessibility labels

## User Acceptance Tests

-   Search diagrams
-   Search screenshots
-   Ask about scanned notes
-   Ask about lecture audio
-   Ask about lecture videos
-   Mixed search across all modalities

------------------------------------------------------------------------

# Completion Criteria

Batch 3 is complete only when:

-   Documents, Images, Audio and Video are processed through one unified
    ContentBlock pipeline.
-   Ask AI works for every supported modality.
-   Semantic Search returns unified ranked evidence with page numbers,
    timestamps or image references.
-   Existing document workflow remains unchanged.
-   All unit, integration, regression, performance and UI tests pass.
-   No UI regressions.
-   No breaking database changes.
-   Modular architecture preserved.

Future batches can then focus on higher-level knowledge features instead
of ingestion.
