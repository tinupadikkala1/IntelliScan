"""Configuration constants for the engines module.

Single authoritative place for model names, URLs, chunking parameters,
search defaults and media-processing limits used across the engines,
extractors, speech, video and vision modules.
"""

import logging

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------- #
# Chunking parameters (modern: larger chunks = fewer embeds, faster, better QA)
# ---------------------------------------------------------------------- #
CHUNK_SIZE = 800  # characters per evidence chunk (was 400 — caused fracture)
CHUNK_OVERLAP = 150  # overlap between adjacent chunks (was 50)

# ---------------------------------------------------------------------- #
# Embedding model configuration
# ---------------------------------------------------------------------- #
EMBEDDING_MODEL = 'nomic-embed-text'
EMBEDDING_DIM = 768  # nomic-embed-text dimension
# Prefixes required by nomic-embed-text for query / document embeddings.
EMBED_QUERY_PREFIX = 'search_query: '
EMBED_DOCUMENT_PREFIX = 'search_document: '

# ---------------------------------------------------------------------- #
# Ollama connection
# ---------------------------------------------------------------------- #
OLLAMA_BASE_URL = 'http://localhost:11434'

# ---------------------------------------------------------------------- #
# Models (all configurable from here — no hardcoded model names elsewhere)
# Modern backend port: 8B excluded, reasoning lane = 1.5B (user choice).
# ---------------------------------------------------------------------- #
LLM_MODEL = 'qwen-local:latest'          # Default RAG / direct-answer model (fast lane)
LLM_MAIN_MODEL = 'qwen3:latest'          # Main QA lane (4B, higher quality, non-8B)
DEEPSEEK_MODEL = 'deepseek-r1-1.5b:latest' # DeepSeek R1 Distill 1.5B reasoning model (replaces 8B)
VISION_MODEL = 'moondream:latest'        # image captioning / vision model
LIGHT_MODEL = 'qwen-local:latest'        # rewrite/HyDE lane (fallback to fast lane)
RERANK_MODEL = 'ExpedientFalcon/qwen3-reranker:0.6b-q4_k_m'  # reranker (0.6B, CPU-safe)
WHISPER_MODEL = 'base'                   # speech transcription model size (legacy openai-whisper)
WHISPER_BACKEND = 'faster-whisper'       # preferred STT backend (uses cached small model)
WHISPER_SMALL_MODEL = 'small'            # faster-whisper size (tiny|base|small|medium)

SUPPORTED_REASONING_MODELS = [
    {
        "id": "qwen-local:latest",
        "name": "Qwen Local (Fast & Lightweight)",
        "badge": "⚡ Fast",
        "description": "Quick direct answers, low memory footprint",
    },
    {
        "id": "qwen3:latest",
        "name": "Qwen3 4B (Balanced QA)",
        "badge": "⭐ Balanced",
        "description": "Higher-quality answers, non-8B, fits 6.9GB RAM",
    },
    {
        "id": "deepseek-r1-1.5b:latest",
        "name": "DeepSeek R1 (Deep Reasoning 1.5B)",
        "badge": "🧠 Reasoning",
        "description": "Step-by-step reasoning with <think> chain-of-thought",
    },
]

RAG_TEMPERATURE = 0.4
RAG_TIMEOUT = 300  # seconds
RAG_MAX_CONTEXT = 3000  # max chars of evidence to include in RAG prompt
DIRECT_MAX_CONTEXT = 12000  # max chars of file text sent in direct-ask prompts

# ---------------------------------------------------------------------- #
# Search defaults
# ---------------------------------------------------------------------- #
TOP_K_DEFAULT = 5
SIMILARITY_THRESHOLD = 0.3

# Match-strength classification thresholds (cosine similarity is NOT
# calibrated confidence; we only label match strength, never "% confidence").
SIMILARITY_HIGH = 0.80
SIMILARITY_MEDIUM = 0.60

# Retrieval quality controls (Batch 4, M0-04):
#   MAX_CHUNKS_PER_FILE — cap how many chunks per file can enter the final
#     results so a single large file cannot dominate the evidence context.
#   RETRIEVAL_DIVERSITY — when True, retrieval prefers spreading evidence
#     across files over stacking chunks from one file.
MAX_CHUNKS_PER_FILE = 3
RETRIEVAL_DIVERSITY = True

# Modern retrieval (ported from New Folder — hybrid RRF + rerank + CRAG).
# Defaults mirror New Folder/default_settings.yaml:rag. UI Batch4 tab still
# overrides top_k/threshold at runtime; these are engine fallbacks.
HYBRID_SEARCH_ENABLED = True
VECTOR_WEIGHT = 0.6
KEYWORD_WEIGHT = 0.4
MAX_PER_FILE = 2
CRAG_ENABLED = True
CRAG_THRESHOLD = 0.25
RERANK_ENABLED = True
RERANK_TOP_N = 5
EMBED_TIMEOUT = 300  # seconds (was 60 — caused 500s on 8MB PDFs, see Copilot logs)
EMBED_BATCH_TIMEOUT = 300
EMBED_MAX_RETRIES = 3

# ---------------------------------------------------------------------- #
# Conversations (Batch 4)
# ---------------------------------------------------------------------- #
CONVERSATION_MAX_HISTORY_CHARS = 6000  # budget for conversation history in prompts
CONVERSATION_MAX_TURNS = 12            # recent turns included in context (user+assistant pairs)
CONVERSATION_DEFAULT_SCOPE = "folder"  # folder | workspace | file

# ---------------------------------------------------------------------- #
# Knowledge graph (Batch 4)
# ---------------------------------------------------------------------- #
GRAPH_EXTRACTION_ENABLED = True
GRAPH_MAX_CHUNKS_PER_FILE = 20   # cap LLM entity-extraction work per file
GRAPH_MIN_CONFIDENCE = 0.5       # relationships below this are dropped
GRAPH_ENTITY_TYPES = [
    "PERSON", "ORGANIZATION", "LOCATION", "PROJECT", "CONCEPT",
    "TECHNOLOGY", "DOCUMENT", "ALGORITHM", "PRODUCT", "TOPIC",
]

# ---------------------------------------------------------------------- #
# Agent (Batch 4) — bounded, read-only by design
# ---------------------------------------------------------------------- #
AGENT_MAX_STEPS = 8
AGENT_TIMEOUT_SECONDS = 300
AGENT_MAX_EVIDENCE = 50
AGENT_READ_ONLY = True

# ---------------------------------------------------------------------- #
# Batch 5 — Intelligent Organization & Knowledge Management
# ---------------------------------------------------------------------- #
# Exact duplicates (B5-04): files whose SHA-256 matches are grouped regardless
# of threshold. ``EMPTY_DUPLICATES_VISIBLE`` controls whether empty-content
# duplicates appear as an explicit "Empty-content duplicates" group.
EMPTY_DUPLICATES_VISIBLE = True

# Near duplicates / similarity (B5-05): cosine similarity thresholds.
# These are starting defaults to be validated against test fixtures — they
# are NOT calibrated probabilities.
NEAR_DUPLICATE_THRESHOLD = 0.90   # score >= this → "very similar"
SIMILAR_FILE_THRESHOLD = 0.75     # score >= this → "similar / related"
MAX_RELATED_RESULTS = 10          # cap for related-file / similarity results
MAX_SIMILARITY_CANDIDATES = 25    # FAISS candidates fetched before aggregation

# File relationships (B5-07): controlled relationship vocabulary.
RELATIONSHIP_TYPES = [
    "related_to",
    "duplicate_of",
    "similar_to",
    "references",
    "derived_from",
    "belongs_to_project",
]

# Classification (B5-01): controlled taxonomy + version for cache invalidation.
CLASSIFICATION_VERSION = '1.0'
CLASSIFICATION_TAXONOMY = [
    "document", "code", "image", "audio", "video",
    "presentation", "spreadsheet", "research", "education",
    "project", "business", "personal", "archive", "other",
]
CLASSIFICATION_BATCH_SIZE = 10   # files classified per LLM batch call

# Auto-tagging (B5-02)
TAGGING_VERSION = '1.0'
TAG_MAX_COUNT = 12               # cap canonical tags per file
TAG_MIN_LENGTH = 2               # drop tags shorter than this

# Organization suggestions (B5-08)
SUGGESTION_MIN_CONFIDENCE = 0.5
SUGGESTION_MAX_TARGETS = 5

# Dashboard (B5-10)
DASHBOARD_REFRESH_AUTO = True

# ---------------------------------------------------------------------- #
# Batch 6 — completing the five partial features
# ---------------------------------------------------------------------- #
# Image caption generation (B6-01): version for cache invalidation.
CAPTION_VERSION = '1.0'

# Folder classification (B6-02): version + how folders are aggregated.
FOLDER_CLASSIFICATION_VERSION = '1.0'
FOLDER_CLASSIFICATION_RECURSIVE = True  # include nested subfolders

# Duplicate removal suggestions (B6-04): minimum confidence to recommend
# removing a copy; near-duplicate similarity floor.
DUPLICATE_REMOVAL_MIN_CONFIDENCE = 0.70
DUPLICATE_REMOVAL_NEAR_MIN_SIMILARITY = 0.90

# Folder organization (B6-05): category-named destination folders considered.
FOLDER_ORGANIZATION_ENABLED = True
FOLDER_ORGANIZATION_MAX_TARGETS = 3

# Reversible trash for approved file operations (B6-04/05).
TRASH_DIR = 'config/trash'

# ---------------------------------------------------------------------- #
# Batch 7 — Intelligent Organization & Knowledge Management (continued)
# ---------------------------------------------------------------------- #
# Reverse image search (B7-1): minimum cosine similarity to consider an
# image a visual match; candidate cap.
REVERSE_IMAGE_MIN_SIMILARITY = 0.55
REVERSE_IMAGE_MAX_RESULTS = 12

# Object detection (B7-2): minimum confidence to keep a detected object;
# version for cache invalidation; the Ollama vision model is reused.
OBJECT_DETECTION_THRESHOLD = 0.40
OBJECT_DETECTION_VERSION = '1.0'

# Metadata export (B7-3)
METADATA_EXPORT_VERSION = '1.0'

# Image quality analysis (B7-4): version for cache invalidation.
IMAGE_QUALITY_VERSION = '1.0'

# Document comparison (B7-5): chunk/snippet budgets.
COMPARE_MAX_TEXT_CHARS = 40000   # bound per-document text fed to the LLM
COMPARE_EVIDENCE_TOP_K = 8

# Metadata editor (B7-6)
METADATA_EDITOR_VERSION = '1.0'

# File timeline (B7-7): event retention for the optional event log.
TIMELINE_MAX_EVENTS = 2000
TIMELINE_DEFAULT_DAYS = 90

# AI-powered folder summary (B7-8): version for cache invalidation.
FOLDER_SUMMARY_VERSION = '1.0'

# Automatic file renaming (B7-9): safety limits.
RENAME_MAX_LENGTH = 120
RENAME_FORBIDDEN_CHARS = '/\\:*?"<>|'

# AI image filtering (B7-10)
IMAGE_FILTER_DEFAULT_THRESHOLD = 0.45


# ---------------------------------------------------------------------- #
# AI resource concurrency (Batch 4, M0-08)
# ---------------------------------------------------------------------- #
AI_LLM_SLOTS = 1
AI_EMBEDDING_SLOTS = 1
AI_VISION_SLOTS = 1
AI_SPEECH_SLOTS = 1
AI_GLOBAL_LIMIT = 2  # max simultaneous heavy AI operations system-wide

# ---------------------------------------------------------------------- #
# Media processing limits (hardware-conscious: i3-N305 / 6.9 GiB RAM)
# ---------------------------------------------------------------------- #
MAX_KEYFRAMES_PER_VIDEO = 5       # max keyframes extracted per video
KEYFRAME_INTERVAL_SECONDS = 60.0  # minimum interval between keyframes
AUDIO_GROUP_DURATION = 30.0       # seconds of audio grouped per transcript block
MIN_FREE_DISK_MB = 500            # refuse AI indexing below this free space

# ---------------------------------------------------------------------- #
# Persistence paths
# ---------------------------------------------------------------------- #
FAISS_INDEX_PATH = 'cache/faiss_index.bin'

# ---------------------------------------------------------------------- #
# Supported extension sets (single authoritative registry)
# ---------------------------------------------------------------------- #
IMAGE_EXTENSIONS = {'.png', '.jpg', '.jpeg', '.webp', '.bmp', '.tiff', '.tif', '.gif'}
AUDIO_EXTENSIONS = {'.mp3', '.wav', '.flac', '.ogg', '.aac', '.m4a', '.wma', '.opus'}
VIDEO_EXTENSIONS = {'.mp4', '.mkv', '.mov', '.avi', '.webm', '.m4v', '.flv', '.wmv'}
DOCUMENT_EXTENSIONS = {
    '.txt', '.text', '.log', '.md', '.markdown', '.mdown',
    '.json', '.xml', '.xhtml', '.svg',
    '.pdf', '.docx', '.pptx', '.ppt', '.xlsx', '.xls', '.csv', '.tsv',
    '.py', '.js', '.ts', '.java', '.cpp', '.c', '.h', '.rs', '.go',
    '.html', '.css', '.yaml', '.yml', '.toml', '.ini', '.cfg', '.conf',
    '.sh', '.bash', '.rb', '.php', '.sql',
}

# Extensions never indexed by the AI pipeline
SKIP_EXTENSIONS = {
    '.zip', '.tar', '.gz', '.bz2', '.7z', '.rar', '.xz',
    '.exe', '.dll', '.so', '.bin', '.o', '.a',
    '.pyc', '.pyo', '.class',
    '.db', '.sqlite', '.sqlite3',
    '.faiss', '.ids', '.pkl', '.pickle',
}

# Modality -> extension sets used for modality-aware filtering
MODALITY_EXTENSIONS = {
    'image': IMAGE_EXTENSIONS,
    'audio': AUDIO_EXTENSIONS,
    'video': VIDEO_EXTENSIONS,
    'document': DOCUMENT_EXTENSIONS,
}

def detect_modality_and_ext(file_path: str) -> tuple[str, str]:
    """Detect modality (image, media, document) and normalized extension using magic bytes.
    
    Ensures that files renamed without extensions (e.g. 'bla_bla_bla' which is actually a jpeg)
    are correctly routed to image/OCR/captioning or document pipelines.
    """
    import os
    ext = os.path.splitext(file_path)[1].lower()
    
    # Check file size. If empty or missing, skip magic check but fall back to extension lookup
    try:
        if not os.path.exists(file_path) or os.path.getsize(file_path) == 0:
            if ext in IMAGE_EXTENSIONS:
                return "image", ext
            if ext in AUDIO_EXTENSIONS:
                return "audio", ext
            if ext in VIDEO_EXTENSIONS:
                return "video", ext
            return "document", ext
    except OSError:
        if ext in IMAGE_EXTENSIONS:
            return "image", ext
        if ext in AUDIO_EXTENSIONS:
            return "audio", ext
        if ext in VIDEO_EXTENSIONS:
            return "video", ext
        return "document", ext

    # Try reading first 16 bytes for magic signatures
    try:
        with open(file_path, "rb") as f:
            header = f.read(16)
    except Exception:
        header = b""

    # Detect images by magic bytes
    if header.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image", ".png"
    if header.startswith(b"\xff\xd8\xff"):
        return "image", ".jpg"
    if header.startswith(b"RIFF") and b"WEBP" in header[8:16]:
        return "image", ".webp"
    if header.startswith(b"GIF8"):
        return "image", ".gif"
    if header.startswith(b"BM"):
        return "image", ".bmp"
        
    # Detect PDF by magic bytes
    if header.startswith(b"%PDF"):
        return "document", ".pdf"

    # Detect ZIP / Office docs by magic bytes
    if header.startswith(b"PK\x03\x04"):
        # Could be docx, pptx, xlsx. Treat as document
        if ext in (".docx", ".pptx", ".xlsx"):
            return "document", ext
        return "document", ".docx"

    # Fall back to extension-based modality mapping
    if ext in IMAGE_EXTENSIONS:
        return "image", ext
    if ext in AUDIO_EXTENSIONS:
        return "audio", ext
    if ext in VIDEO_EXTENSIONS:
        return "video", ext
        
    return "document", ext
