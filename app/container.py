"""Minimal dependency-injection container with lazy service initialization.

Wires shared services (config, signal bus, and later database / background
managers) so they can be injected into widgets instead of being imported as
globals. Keeping references here also gives a single place to shut things
down on exit.
"""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING, Any

logger = logging.getLogger(__name__)

from core.config import Config
from app.signal_bus import SignalBus
from core.plugin_registry import PluginRegistry
from database.engine import Database
from database.repository import Repository
from services.folder_scanner import FolderScanner
from services.thread_manager import ThreadManager
from services.task_manager import TaskManager
from services.file_watcher import FileWatcher
from services.cache_manager import CacheManager
from plugins.loader import load_all

if TYPE_CHECKING:
    from ui.indexed_files_widget import IndexedFilesWidget


class Container:
    def __init__(self) -> None:
        # Core services created eagerly (lightweight)
        self._config = Config()
        self._bus = SignalBus()

        # Lazy-initialized services (heavy or optional)
        self._db: Database | None = None
        self._repository: Repository | None = None
        self._threads: ThreadManager | None = None
        self._tasks: TaskManager | None = None
        self._watcher: FileWatcher | None = None
        self._cache: CacheManager | None = None
        self._plugins: PluginRegistry | None = None
        self._folder_scanner: FolderScanner | None = None
        self._file_system_model = None

        # Batch 3: AI Knowledge & Retrieval engines (lazy)
        self._embedding_engine = None
        self._vector_engine = None
        self._retrieval_engine = None
        self._rag_engine = None
        self._db_store = None

        # Batch 4: conversations, graph, agent, resource control (lazy)
        self._ai_resources = None
        self._conversation_store = None
        self._conversation_manager = None
        self._graph_engine = None
        self._agent_engine = None

        # Batch 5: organization & knowledge management (lazy)
        self._ai_service = None
        self._ai_cache = None
        self._batch5_store = None
        self._duplicate_engine = None
        self._similarity_service = None
        self._related_file_service = None
        self._relationship_engine = None
        self._classification_engine = None
        self._tagging_engine = None
        self._saved_search_manager = None
        self._collection_engine = None
        self._suggestion_engine = None
        self._dashboard_service = None

        # Batch 6: captioning, folder classification (lazy)
        self._vision_engine = None
        self._caption_service = None
        self._folder_classification_service = None

        # Batch 7: image intelligence, metadata tools, timeline, folder
        # intelligence, comparison, safe renaming, image filtering (lazy)
        self._metadata_export_service = None
        self._metadata_editor_service = None
        self._timeline_service = None
        self._image_quality_service = None
        self._object_detection_service = None
        self._folder_intelligence_service = None
        self._folder_summary_service = None
        self._reverse_image_service = None
        self._image_filter_service = None
        self._document_comparison_service = None
        self._rename_suggestion_service = None
        self._file_organizer_service = None
        self._inactivity_reminder_service = None

        self._services: dict[str, Any] = {}



    # ------------------------------------------------------------------ #
    # Core services (eager)
    # ------------------------------------------------------------------ #
    @property
    def config(self) -> Config:
        return self._config

    @property
    def bus(self) -> SignalBus:
        return self._bus

    # ------------------------------------------------------------------ #
    # Lazy services
    # ------------------------------------------------------------------ #
    @property
    def db(self) -> Database:
        if self._db is None:
            db_path = self.config.get("database.path", "config/intellivault.db")
            if not os.path.isabs(db_path):
                db_path = os.path.join(os.path.dirname(__file__), "..", db_path)
            self._db = Database(db_path)
        return self._db

    @property
    def repository(self) -> Repository:
        if self._repository is None:
            self._repository = Repository(self.db)
        return self._repository

    @property
    def threads(self) -> ThreadManager:
        if self._threads is None:
            max_threads = self.config.get("performance.max_threads", 4)
            self._threads = ThreadManager(max_threads)
        return self._threads

    @property
    def tasks(self) -> TaskManager:
        if self._tasks is None:
            self._tasks = TaskManager(self.threads, self.repository, self.bus)
        return self._tasks

    @property
    def watcher(self) -> FileWatcher:
        if self._watcher is None:
            self._watcher = FileWatcher()
        return self._watcher

    @property
    def cache(self) -> CacheManager:
        if self._cache is None:
            cache_dir = os.path.join(os.path.dirname(__file__), "..", "cache")
            self._cache = CacheManager(cache_dir)
        return self._cache

    @property
    def folder_scanner(self) -> FolderScanner:
        if self._folder_scanner is None:
            self._folder_scanner = FolderScanner()
        return self._folder_scanner

    @property
    def plugins(self) -> PluginRegistry:
        if self._plugins is None:
            self._plugins = PluginRegistry(self.bus)
            load_all(self._plugins)
        return self._plugins

    @property
    def file_system_model(self):
        """Shared QFileSystemModel instance for FolderTree and FileExplorer."""
        from PySide6.QtCore import QDir
        from PySide6.QtWidgets import QFileSystemModel

        if self._file_system_model is None:
            self._file_system_model = QFileSystemModel()
            self._file_system_model.setFilter(QDir.AllEntries | QDir.NoDotAndDotDot)
            self._file_system_model.setReadOnly(False)
            self._file_system_model.setNameFilterDisables(False)
        return self._file_system_model

    # ------------------------------------------------------------------ #
    # Batch 3: AI Knowledge & Retrieval Engines (lazy)
    # ------------------------------------------------------------------ #
    @property
    def embedding_engine(self):
        """Lazy-initialized EmbeddingEngine (uses Ollama nomic-embed-text)."""
        if self._embedding_engine is None:
            from engines import EmbeddingEngine
            self._embedding_engine = EmbeddingEngine(resources=self.ai_resources)
        return self._embedding_engine

    @property
    def vector_engine(self):
        """Lazy-initialized VectorEngine (FAISS index)."""
        if self._vector_engine is None:
            from engines import VectorEngine
            from engines.config import EMBEDDING_DIM
            index_path = os.path.join(
                os.path.dirname(__file__), "..", "cache", "faiss_index.bin"
            )
            os.makedirs(os.path.dirname(index_path), exist_ok=True)
            self._vector_engine = VectorEngine(
                dimension=EMBEDDING_DIM, index_path=index_path
            )
        return self._vector_engine

    @property
    def db_store(self):
        """Lazy-initialized EngineDBStore for evidence/vector persistence."""
        if self._db_store is None:
            from engines.db_store import EngineDBStore
            self._db_store = EngineDBStore(self.db.session)
        return self._db_store

    @property
    def retrieval_engine(self):
        """Lazy-initialized RetrievalEngine, hydrated from persisted evidence.

        Hydration restores the in-memory evidence map from SQLite so semantic
        search survives application restarts (FAISS vectors + evidence are
        kept consistent; orphaned vectors are cleaned up).
        """
        if self._retrieval_engine is None:
            from engines import RetrievalEngine
            self._retrieval_engine = RetrievalEngine(
                embedding_engine=self.embedding_engine,
                vector_engine=self.vector_engine,
            )
            try:
                hydrated = self._retrieval_engine.hydrate_from_store(self.db_store)
                # Persist any orphan-vector cleanup so the on-disk FAISS
                # index stays consistent with the database across restarts.
                if hydrated is not None:
                    self.vector_engine.save()
            except Exception as exc:
                logger.error("Failed to hydrate retrieval engine: %s", exc)
        return self._retrieval_engine

    @property
    def rag_engine(self):
        """Lazy-initialized RAGEngine."""
        if self._rag_engine is None:
            from engines import RAGEngine
            self._rag_engine = RAGEngine(
                retrieval_engine=self.retrieval_engine,
                resources=self.ai_resources,
            )
        return self._rag_engine

    # ------------------------------------------------------------------ #
    # Batch 4 services (lazy)
    # ------------------------------------------------------------------ #
    @property
    def ai_resources(self):
        """AIResourceManager — bounded concurrency for heavy AI workloads."""
        if self._ai_resources is None:
            from services.ai_resource_manager import AIResourceManager
            self._ai_resources = AIResourceManager()
        return self._ai_resources

    @property
    def conversation_store(self):
        """ConversationStore — SQLite persistence for conversations."""
        if self._conversation_store is None:
            from conversation.conversation_store import ConversationStore
            self._conversation_store = ConversationStore(self.db.session)
        return self._conversation_store

    @property
    def conversation_manager(self):
        """ConversationManager — chat orchestration over retrieval + RAG."""
        if self._conversation_manager is None:
            from conversation.conversation_manager import ConversationManager
            self._conversation_manager = ConversationManager(
                store=self.conversation_store,
                retrieval=self.retrieval_engine,
                rag=self.rag_engine,
                graph=self.graph_engine,
            )
        return self._conversation_manager

    @property
    def graph_engine(self):
        """GraphEngine — knowledge graph extraction/query (Batch 4 M7)."""
        if self._graph_engine is None:
            from graph.graph_engine import GraphEngine
            self._graph_engine = GraphEngine(
                session_factory=self.db.session,
                rag=self.rag_engine,
                resources=self.ai_resources,
                enabled=self.config.get("batch4.graph_enabled", True),
            )
        return self._graph_engine

    @property
    def agent_engine(self):
        """AgentEngine — bounded read-only agent (Batch 4 M10)."""
        if self._agent_engine is None:
            from agent.agent_engine import AgentEngine
            from agent.policies import AgentPolicy
            self._agent_engine = AgentEngine(
                retrieval=self.retrieval_engine,
                rag=self.rag_engine,
                graph_engine=self.graph_engine,
                resources=self.ai_resources,
                policy=AgentPolicy(
                    max_steps=self.config.get("batch4.agent_max_steps", 8),
                    max_time_seconds=self.config.get("batch4.agent_timeout_s", 300),
                ),
            )
        return self._agent_engine

    # ------------------------------------------------------------------ #
    # Batch 5 services (lazy)
    # ------------------------------------------------------------------ #
    @property
    def ai_service(self):
        """AIService — LLM analysis (summary/keywords/tags/category)."""
        if self._ai_service is None:
            from ai import AIService, JsonParser, OllamaClient, PromptBuilder
            self._ai_service = AIService(
                ollama_client=OllamaClient(),
                prompt_builder=PromptBuilder(),
                json_parser=JsonParser(),
            )
        return self._ai_service

    @property
    def ai_cache(self):
        """AICacheManager — AI analysis persistence keyed by content hash."""
        if self._ai_cache is None:
            from ai.cache_manager import AICacheManager
            self._ai_cache = AICacheManager(self.db.session)
        return self._ai_cache

    @property
    def batch5_store(self):
        """Batch5Store — collections, saved searches, relationships, suggestions."""
        if self._batch5_store is None:
            from services.batch5_store import Batch5Store
            self._batch5_store = Batch5Store(self.db.session)
        return self._batch5_store

    @property
    def duplicate_engine(self):
        """DuplicateEngine — exact duplicate detection (B5-04)."""
        if self._duplicate_engine is None:
            from engines.duplicate_engine import DuplicateEngine
            self._duplicate_engine = DuplicateEngine(
                self.db.session,
                empty_visible=self.config.get("batch5.empty_duplicates_visible", True),
            )
        return self._duplicate_engine

    @property
    def similarity_service(self):
        """FileSimilarityService — near-duplicate / file similarity (B5-05)."""
        if self._similarity_service is None:
            from services.file_similarity import FileSimilarityService
            self._similarity_service = FileSimilarityService(
                retrieval=self.retrieval_engine,
                near_threshold=self.config.get("batch5.near_duplicate_threshold", 0.90),
                similar_threshold=self.config.get("batch5.similar_file_threshold", 0.75),
                max_results=self.config.get("batch5.max_related_results", 10),
            )
        return self._similarity_service

    @property
    def related_file_service(self):
        """RelatedFileService — combined related-file discovery (B5-06)."""
        if self._related_file_service is None:
            from services.related_file_service import RelatedFileService
            self._related_file_service = RelatedFileService(
                retrieval=self.retrieval_engine,
                similarity=self.similarity_service,
                graph_store=self.graph_engine.store if self.graph_engine is not None else None,
                max_results=self.config.get("batch5.max_related_results", 10),
            )
        return self._related_file_service

    @property
    def relationship_engine(self):
        """RelationshipEngine — FILE→FILE relationships (B5-07)."""
        if self._relationship_engine is None:
            from services.relationship_engine import RelationshipEngine
            self._relationship_engine = RelationshipEngine(
                store=self.batch5_store,
                duplicates=self.duplicate_engine,
                similarity=self.similarity_service,
                graph_store=self.graph_engine.store if self.graph_engine is not None else None,
            )
        return self._relationship_engine

    @property
    def classification_engine(self):
        """ClassificationEngine — controlled taxonomy (B5-01)."""
        if self._classification_engine is None:
            from services.classification_engine import ClassificationEngine
            self._classification_engine = ClassificationEngine(
                session_factory=self.db.session,
                analysis_cache=self.ai_cache,
                ai_service=self.ai_service,
                batch_size=self.config.get("batch5.classification_batch_size", 10),
            )
        return self._classification_engine

    @property
    def tagging_engine(self):
        """TaggingEngine — canonical tag generation (B5-02)."""
        if self._tagging_engine is None:
            from services.tagging_engine import TaggingEngine
            self._tagging_engine = TaggingEngine(
                session_factory=self.db.session,
                analysis_cache=self.ai_cache,
                ai_service=self.ai_service,
            )
        return self._tagging_engine

    @property
    def saved_search_manager(self):
        """SavedSearchManager — persisted re-runnable searches (B5-09)."""
        if self._saved_search_manager is None:
            from services.saved_search_manager import SavedSearchManager
            self._saved_search_manager = SavedSearchManager(
                store=self.batch5_store,
                retrieval=self.retrieval_engine,
            )
        return self._saved_search_manager

    @property
    def collection_engine(self):
        """CollectionEngine — virtual collections (B5-03)."""
        if self._collection_engine is None:
            from services.collection_engine import CollectionEngine
            self._collection_engine = CollectionEngine(
                store=self.batch5_store,
                retrieval=self.retrieval_engine,
                classifier=self.classification_engine,
                tagger=self.tagging_engine,
            )
        return self._collection_engine

    @property
    def suggestion_engine(self):
        """SuggestionEngine — organization suggestions (B5-08) + Batch-6
        duplicate-removal recommendations and folder targets."""
        if self._suggestion_engine is None:
            from services.suggestion_engine import SuggestionEngine
            self._suggestion_engine = SuggestionEngine(
                store=self.batch5_store,
                related=self.related_file_service,
                classifier=self.classification_engine,
                tagger=self.tagging_engine,
                collection_engine=self.collection_engine,
                rag=self.rag_engine,
                min_confidence=self.config.get("batch5.suggestion_min_confidence", 0.5),
                session_factory=self.db.session,
                retrieval=self.retrieval_engine,
                db_store=self.db_store,
                vector_engine=self.vector_engine,
                folder_org_enabled=self.config.get("batch6.folder_organization_enabled", True),
                removal_min_confidence=self.config.get(
                    "batch6.duplicate_removal_min_confidence", 0.70
                ),
            )
        return self._suggestion_engine

    # ------------------------------------------------------------------ #
    # Batch 6 services (lazy)
    # ------------------------------------------------------------------ #
    @property
    def vision_engine(self):
        """VisionEngine — Ollama vision captioning (reused by B6-01)."""
        if self._vision_engine is None:
            from vision.vision_engine import VisionEngine
            self._vision_engine = VisionEngine(
                model=self.config.get("batch6.caption_model", "moondream:latest")
            )
        return self._vision_engine

    @property
    def caption_service(self):
        """CaptionService — standalone image captioning (B6-01)."""
        if self._caption_service is None:
            from services.caption_service import CaptionService
            self._caption_service = CaptionService(
                session_factory=self.db.session,
                vision_engine=self.vision_engine,
                resources=self.ai_resources,
                model=self.config.get("batch6.caption_model", "moondream:latest"),
            )
        return self._caption_service

    @property
    def folder_classification_service(self):
        """FolderClassificationService — folder-level aggregation (B6-02)."""
        if self._folder_classification_service is None:
            from services.folder_classification import FolderClassificationService
            self._folder_classification_service = FolderClassificationService(
                session_factory=self.db.session,
                classifier=self.classification_engine,
                recursive=self.config.get("batch6.folder_classification_recursive", True),
            )
        return self._folder_classification_service

    @property
    def dashboard_service(self):
        """DashboardService — workspace knowledge dashboard (B5-10)."""
        if self._dashboard_service is None:
            from services.dashboard_service import DashboardService
            self._dashboard_service = DashboardService(
                session_factory=self.db.session,
                duplicates=self.duplicate_engine,
                relationship_engine=self.relationship_engine,
                collection_engine=self.collection_engine,
                classifier=self.classification_engine,
                tagger=self.tagging_engine,
                graph_store=self.graph_engine.store if self.graph_engine is not None else None,
                db_store=self.db_store,
                retrieval=self.retrieval_engine,
            )
        return self._dashboard_service

    # ------------------------------------------------------------------ #
    # Batch 7 services (lazy)
    # ------------------------------------------------------------------ #
    @property
    def metadata_export_service(self):
        """MetadataExportService — JSON/CSV metadata export (B7-3)."""
        if self._metadata_export_service is None:
            from services.metadata_export_service import MetadataExportService
            self._metadata_export_service = MetadataExportService(self.db.session)
        return self._metadata_export_service

    @property
    def metadata_editor_service(self):
        """MetadataEditorService — user metadata editing (B7-6)."""
        if self._metadata_editor_service is None:
            from services.metadata_editor_service import MetadataEditorService
            self._metadata_editor_service = MetadataEditorService(self.db.session)
        return self._metadata_editor_service

    @property
    def timeline_service(self):
        """TimelineService — chronological file activity (B7-7)."""
        if self._timeline_service is None:
            from services.timeline_service import TimelineService
            self._timeline_service = TimelineService(self.db.session)
        return self._timeline_service

    @property
    def image_quality_service(self):
        """ImageQualityService — deterministic quality metrics (B7-4)."""
        if self._image_quality_service is None:
            from services.image_quality_service import ImageQualityService
            self._image_quality_service = ImageQualityService(
                session_factory=self.db.session,
            )
        return self._image_quality_service

    @property
    def object_detection_service(self):
        """ObjectDetectionService — vision-model object detection (B7-2)."""
        if self._object_detection_service is None:
            from services.object_detection_service import ObjectDetectionService
            self._object_detection_service = ObjectDetectionService(
                session_factory=self.db.session,
                vision_engine=self.vision_engine,
                model=self.config.get("batch7.object_detection_model", "moondream:latest"),
                threshold=self.config.get("batch7.object_detection_threshold", 0.40),
                resources=self.ai_resources,
            )
        return self._object_detection_service

    @property
    def folder_intelligence_service(self):
        """FolderIntelligenceService — general folder statistics (B7-31)."""
        if self._folder_intelligence_service is None:
            from services.folder_intelligence_service import FolderIntelligenceService
            self._folder_intelligence_service = FolderIntelligenceService(
                session_factory=self.db.session,
                folder_classification_service=self.folder_classification_service,
            )
        return self._folder_intelligence_service

    @property
    def folder_summary_service(self):
        """FolderSummaryService — AI folder summary (B7-8)."""
        if self._folder_summary_service is None:
            from services.folder_summary_service import FolderSummaryService
            self._folder_summary_service = FolderSummaryService(
                session_factory=self.db.session,
                folder_classification_service=self.folder_classification_service,
                folder_intelligence_service=self.folder_intelligence_service,
                rag_engine=self.rag_engine,
                model=self.config.get("batch7.folder_summary_model", "qwen-local:latest"),
            )
        return self._folder_summary_service

    @property
    def reverse_image_service(self):
        """ReverseImageService — image→image CLIP search (B7-1)."""
        if self._reverse_image_service is None:
            from services.reverse_image_service import ReverseImageService
            from engines.clip_engine import CLIPEngine
            self._reverse_image_service = ReverseImageService(
                retrieval=self.retrieval_engine,
                clip_engine=CLIPEngine(),
                min_similarity=self.config.get("batch7.reverse_image_min_similarity", 0.55),
                max_results=12,
            )
        return self._reverse_image_service

    @property
    def image_filter_service(self):
        """ImageFilterService — AI image filtering (B7-10)."""
        if self._image_filter_service is None:
            from services.image_filter_service import ImageFilterService
            self._image_filter_service = ImageFilterService(
                session_factory=self.db.session,
                reverse_image_service=self.reverse_image_service,
            )
        return self._image_filter_service

    @property
    def document_comparison_service(self):
        """DocumentComparisonService — structural/textual/semantic (B7-5)."""
        if self._document_comparison_service is None:
            from services.document_comparison_service import DocumentComparisonService
            self._document_comparison_service = DocumentComparisonService(
                rag_engine=self.rag_engine,
                retrieval_engine=self.retrieval_engine,
                session_factory=self.db.session,
            )
        return self._document_comparison_service

    @property
    def rename_suggestion_service(self):
        """RenameSuggestionService — approved file renames (B7-9)."""
        if self._rename_suggestion_service is None:
            from services.rename_suggestion_service import RenameSuggestionService
            self._rename_suggestion_service = RenameSuggestionService(
                session_factory=self.db.session,
                pattern=self.config.get("batch7.rename_pattern", "{category}_{title}"),
                rag_engine=self.rag_engine,
            )
        return self._rename_suggestion_service


    @property
    def file_organizer_service(self):
        """FileOrganizerService — user-directed content/type folder organization."""
        if self._file_organizer_service is None:
            from services.file_organizer_service import FileOrganizerService
            self._file_organizer_service = FileOrganizerService(
                retrieval=self.retrieval_engine,
                reverse_image_service=self.reverse_image_service,
                classifier=self.classification_engine,
                session_factory=self.db.session,
                db_store=self.db_store,
            )
        return self._file_organizer_service

    @property
    def inactivity_reminder_service(self):
        """InactivityReminderService — tracks access and monitors inactive files."""
        if self._inactivity_reminder_service is None:
            from services.inactivity_reminder_service import InactivityReminderService
            self._inactivity_reminder_service = InactivityReminderService(
                session_factory=self.db.session,
                classifier=self.classification_engine,
            )
        return self._inactivity_reminder_service



    # ------------------------------------------------------------------ #
    # Ad-hoc service registry
    # ------------------------------------------------------------------ #
    def register(self, name: str, instance: Any) -> None:
        self._services[name] = instance

    def get(self, name: str, default: Any = None) -> Any:
        return self._services.get(name, default)

    def shutdown(self) -> None:
        for service in self._services.values():
            stop = getattr(service, "stop", None) or getattr(service, "shutdown", None)
            if callable(stop):
                try:
                    stop()
                except Exception:
                    pass
        try:
            self.watcher.shutdown()
        except Exception:
            pass
        try:
            self.threads.shutdown()
        except Exception:
            pass
        try:
            self.db.dispose()
        except Exception:
            pass

