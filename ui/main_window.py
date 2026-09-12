"""Main window (M2).

Assembles the full application shell: menu bar, toolbar, status bar, and
dockable Navigation/Preview panels around a central explorer area (populated
in M4). All wiring goes through the shared signal bus and DI container so no
business logic lives in the widgets.
"""

from __future__ import annotations

import os

from PySide6.QtWidgets import (
    QMainWindow,
    QWidget,
    QLabel,
    QVBoxLayout,
    QHBoxLayout,
    QSplitter,
    QFileSystemModel,
)
from PySide6.QtCore import QTimer, Qt, QFileInfo, Slot


from app.container import Container
from ui.theme_engine import ThemeEngine
from ui.menu_bar import MenuBar
from ui.toolbar import ToolBar
from ui.status_bar import StatusBar
from ui.dock_manager import DockManager
from ui.indexed_files_widget import IndexedFilesWidget
from ui.dialogs.b1_progress_dialog import B1ProgressDialog
from widgets.folder_tree import FolderTree
from widgets.favorites import FavoritesWidget
from widgets.drives import DrivesWidget
from widgets.breadcrumb import Breadcrumb
from widgets.file_explorer import FileExplorer
from widgets.preview_panel import PreviewPanel
from ui.settings_dialog import SettingsDialog
from core.logging_setup import get_logger


class MainWindow(QMainWindow):
    def __init__(self, container: Container) -> None:
        super().__init__()
        self.container = container
        self.bus = container.bus
        self.log = get_logger("ui.main_window")
        startup = container.config.get("general.startup_path", "~/Desktop")
        self.current_path = os.path.expanduser(startup)
        if not os.path.exists(self.current_path):
            self.current_path = os.path.expanduser("~")

        self._history: list[str] = []
        self._history_index = -1
        self._debounce_timer = QTimer(self)
        self._debounce_timer.setSingleShot(True)
        self._debounce_timer.setInterval(300)
        self._debounce_timer.timeout.connect(self._on_files_changed_flush)

        self.setWindowTitle("IntelliVault — Foundation v1.0")
        self.resize(1200, 800)

        # Subsystems --------------------------------------------------- #
        self.theme_engine = ThemeEngine(container.config, self.bus)
        self.docks = DockManager(self)
        self.menu = MenuBar(self, container)
        self.toolbar = ToolBar(self)
        self.status = StatusBar(self)

        # Navigation widgets (M3) -------------------------------------- #
        shared_model = container.file_system_model
        self.folder_tree = FolderTree(model=shared_model)
        self.favorites = FavoritesWidget(container.config, container.repository)
        self.drives = DrivesWidget()
        self.breadcrumb = Breadcrumb()

        # File explorer (M4) -------------------------------------------- #
        self.explorer = FileExplorer(plugin_registry=container.plugins, model=shared_model)
        default_view = container.config.get("explorer.default_view", "list")
        self.explorer.set_view(default_view)
        self.explorer.set_show_hidden(container.config.get("explorer.show_hidden", False))
        self.toolbar.view_combo.setCurrentText(default_view.capitalize())

        # Preview panel (M5) -------------------------------------------- #
        self.preview = PreviewPanel(
            self.bus, container.tasks, container.cache, container.plugins, database=container.db
        )

        # Central area: breadcrumb + explorer -------------------------- #
        self.central = QWidget()
        central_layout = QVBoxLayout(self.central)
        central_layout.setContentsMargins(0, 0, 0, 0)
        central_layout.addWidget(self.breadcrumb)
        central_layout.addWidget(self.explorer, 1)

        # Indexed Files — removed (no longer required, per user request).
        self._build_sidebar()
        self.docks.set_preview_widget(self.preview)
        # self.docks.add_indexed_files_widget(self.container)
        # self.docks.indexed_files_widget.setFixedHeight(180)
        # central_layout.addWidget(self.docks.indexed_files_widget)

        self.setCentralWidget(self.central)

        # Assembly ----------------------------------------------------- #
        self._assemble()
        self._wire()
        self.theme_engine.apply()  # apply persisted theme
        self._navigate_to(self.current_path)

        # Batch 4 M0-07 — hydrate AI engines off the GUI thread at startup.
        try:
            self.container.tasks.submit(
                self._warmup_ai,
                "ai_warmup",
                None,
                on_error=lambda err: self.log.debug("AI warmup error: %s", err),
            )
        except Exception as exc:
            self.log.debug("AI warmup not submitted: %s", exc)

        # Batch 7 M0 — task-table hygiene: prune old finished tasks off the
        # GUI thread so the unbounded tasks table never grows without bound.
        try:
            self.container.tasks.submit(
                self._prune_tasks,
                "task_prune",
                None,
                on_error=lambda err: self.log.debug("Task prune error: %s", err),
            )
        except Exception as exc:
            self.log.debug("Task prune not submitted: %s", exc)

        # Automatic Inactive File Check on startup (2 seconds delayed)
        QTimer.singleShot(2000, lambda: self._on_check_inactive_requested(auto_check=True))

        # Automatic background stale database cleanup on startup
        try:
            from services.file_cleanup import cleanup_all_stale_files

            def _auto_db_cleanup(progress_callback, cancel_event):
                return cleanup_all_stale_files(
                    session_factory=self.container.db.session,
                    retrieval=self.container.retrieval_engine,
                    db_store=self.container.db_store,
                    graph_engine=self.container.graph_engine,
                    vector_engine=self.container.vector_engine,
                )

            self.container.tasks.submit(
                _auto_db_cleanup,
                "auto_db_cleanup",
                None,
                on_error=lambda err: self.log.debug("Auto DB cleanup error: %s", err),
            )
        except Exception as exc:
            self.log.debug("Auto DB cleanup submission skipped: %s", exc)


    def _build_sidebar(self) -> None:
        splitter = QSplitter(Qt.Vertical)
        splitter.addWidget(self.folder_tree)
        # Favorites + Drives hidden for now (keep file hierarchy only).
        # splitter.addWidget(self.favorites)
        # splitter.addWidget(self.drives)
        splitter.setStretchFactor(0, 1)
        # splitter.setStretchFactor(1, 1)
        # splitter.setStretchFactor(2, 1)
        self.docks.set_sidebar_widget(splitter)

    def _assemble(self) -> None:
        # MenuBar already attached its menus to self.menuBar() during build.
        self.addToolBar(self.toolbar)
        self.setStatusBar(self.status)

    def _wire(self) -> None:
        self.menu.toggle_sidebar.connect(self.docks.toggle_sidebar)
        self.menu.toggle_preview.connect(self.docks.toggle_preview)
        self.menu.toggle_theme.connect(self.theme_engine.toggle)
        self.menu.refresh.connect(self._on_refresh)
        self.menu.open_settings.connect(self._open_settings)
        self.menu.open_workspace_chat.connect(self._on_workspace_chat_requested)
        self.menu.open_knowledge_graph.connect(self._on_knowledge_graph_requested)
        # self.menu.open_agent_mode.connect(self._on_agent_mode_requested)  # commented out — not in use
        self.menu.open_conversation_history.connect(self._on_conversation_history_requested)
        self.menu.open_duplicates.connect(self._on_duplicates_requested)
        self.menu.open_saved_searches.connect(self._on_saved_searches_requested)
        # self.menu.open_collections.connect(self._on_collections_requested)  # commented out — not in use
        self.menu.open_dashboard.connect(self._on_dashboard_requested)
        self.menu.open_file_relationships.connect(self._on_file_relationships_requested)
        self.menu.open_metadata_export.connect(self._on_metadata_export_requested)
        self.menu.open_file_timeline.connect(self._on_timeline_requested)
        self.menu.open_compare_documents.connect(self._on_compare_documents_requested)
        self.menu.open_image_filter.connect(self._on_image_filter_requested)
        self.menu.open_organize_files.connect(self._on_organize_files_requested)
        self.menu.open_check_inactive.connect(self._on_check_inactive_requested)
        self.menu.open_folder_statistics.connect(self._on_folder_statistics_menu_requested)
        self.menu.open_cleanup_db.connect(self._on_cleanup_db_requested)



        self.toolbar.refresh.connect(self._on_refresh)
        self.toolbar.up.connect(self._on_up)
        self.toolbar.back.connect(self._on_back)
        self.toolbar.forward.connect(self._on_forward)
        self.toolbar.view_changed.connect(self._on_view_changed)
        self.toolbar.search_submitted.connect(self._on_search)
        self.toolbar.scan_requested.connect(self._on_scan_requested)
        self.toolbar.ai_index_requested.connect(self._on_ai_index_requested)

        self.folder_tree.folder_selected.connect(self._navigate_to)
        self.drives.folder_selected.connect(self._navigate_to)
        self.favorites.folder_selected.connect(self._navigate_to)
        self.breadcrumb.path_changed.connect(self._navigate_to)

        self.explorer.file_activated.connect(self._on_file_activated)
        self.explorer.selection_changed.connect(self._on_explorer_selection)
        self.explorer.ai_analyze_requested.connect(self._on_ai_analyze_requested)
        self.explorer.semantic_search_requested.connect(self._on_semantic_search_requested)
        self.explorer.ask_ai_requested.connect(self._on_ask_ai_requested)
        self.explorer.folder_chat_requested.connect(self._on_folder_chat_requested)
        # Batch 5 — organization actions
        self.explorer.classify_requested.connect(self._on_classify_requested)
        self.explorer.auto_tag_requested.connect(self._on_auto_tag_requested)
        self.explorer.find_duplicates_requested.connect(self._on_find_duplicates_requested)
        self.explorer.find_similar_requested.connect(self._on_find_similar_requested)
        self.explorer.find_related_requested.connect(self._on_find_related_requested)
        self.explorer.view_relationships_requested.connect(self._on_view_relationships_requested)
        self.explorer.suggest_organization_requested.connect(self._on_suggest_organization_requested)
        # Batch 6 — captioning + folder intelligence
        self.explorer.caption_requested.connect(self._on_caption_requested)
        self.explorer.folder_intelligence_requested.connect(self._on_folder_intelligence_requested)
        # Batch 7 — image intelligence, metadata tools, safe renaming
        self.explorer.image_quality_requested.connect(self._on_image_quality_requested)
        self.explorer.object_detection_requested.connect(self._on_object_detection_requested)
        self.explorer.reverse_image_requested.connect(self._on_reverse_image_requested)
        self.explorer.edit_metadata_requested.connect(self._on_edit_metadata_requested)
        self.explorer.rename_suggest_requested.connect(self._on_suggest_rename_requested)
        self.explorer.rename_suggest_multi_requested.connect(self._on_suggest_rename_multi_requested)
        self.toolbar.semantic_search_requested.connect(self._on_semantic_search_from_toolbar)
        self.bus.path_changed.connect(self.explorer.set_path)
        self.bus.path_changed.connect(lambda _p: self.preview.clear())
        self.bus.selection_changed.connect(self._on_selection_changed)
        self.bus.status_message.connect(self.status.set_task_status)
        self.bus.task_progress.connect(self._on_task_progress)
        self.bus.settings_changed.connect(self._on_settings_changed)

        self.bus.file_selected.connect(self._on_file_selected_from_index)

        self.container.watcher.changed.connect(self._on_files_changed)

    # ------------------------------------------------------------------ #
    # ------------------------------------------------------------------ #
    def _navigate_to(self, path: str, record: bool = True) -> None:
        if not path or not os.path.isdir(path):
            return
        if record:
            # Drop any "forward" history and append the new location.
            if self._history_index < len(self._history) - 1:
                self._history = self._history[: self._history_index + 1]
            if not self._history or self._history[-1] != path:
                self._history.append(path)
                self._history_index = len(self._history) - 1
        self.current_path = path
        self.container.watcher.watch(path)
        self.breadcrumb.set_path(path)
        self.folder_tree.navigate_to(path)
        self.favorites.set_current_path(path)
        self.status.set_free_space(path)
        self.bus.path_changed.emit(path)
        self.log.info("navigated to %s", path)

        # Update Indexed Files panel to show only files from this folder
        if hasattr(self.docks, 'indexed_files_widget'):
            self.docks.indexed_files_widget.set_current_path(path)

    def _on_back(self) -> None:
        if self._history_index > 0:
            self._history_index -= 1
            self._navigate_to(self._history[self._history_index], record=False)

    def _on_forward(self) -> None:
        if self._history_index < len(self._history) - 1:
            self._history_index += 1
            self._navigate_to(self._history[self._history_index], record=False)

    def _on_up(self) -> None:
        parent = os.path.dirname(self.current_path)
        if parent and parent != self.current_path:
            self._navigate_to(parent)

    def _on_refresh(self) -> None:
        # Re-read the current directory to pick up any external changes.
        self._navigate_to(self.current_path, record=False)
        self.bus.status_message.emit("Refreshed")
        self.log.info("refresh requested")

    def _on_view_changed(self, view: str) -> None:
        self.explorer.set_view(view)
        self.container.config.set("explorer.default_view", view)
        self.bus.status_message.emit(f"View: {view}")

    def _on_search(self, text: str) -> None:
        self.explorer.set_name_filter(text.strip())
        self.log.info("search submitted: %s", text)

    def _on_file_activated(self, path: str) -> None:
        if QFileInfo(path).isDir():
            self._navigate_to(path)
        else:
            from PySide6.QtGui import QDesktopServices
            from PySide6.QtCore import QUrl
            QDesktopServices.openUrl(QUrl.fromLocalFile(path))
            self.bus.file_opened.emit(path)
            self.container.repository.add_recent(path)
            self.container.inactivity_reminder_service.mark_file_opened(path)
            self.container.plugins.invoke_hook("file_opened", path)
            self.log.info("opened file %s", path)


    def _on_explorer_selection(self, paths: list[str]) -> None:
        self.bus.selection_changed.emit(paths)
        self.status.set_item_count(len(paths))

    def _on_selection_changed(self, paths: list[str]) -> None:
        if paths:
            self.preview.show_file(paths[0])
        else:
            self.preview.clear()
        self.container.plugins.invoke_hook("selection_changed", paths)

    def _on_files_changed(self, changed_path: str) -> None:
        # Debounce: reset timer on each change event.
        self._debounce_path = changed_path
        self._debounce_timer.start()

    def _on_files_changed_flush(self) -> None:
        path = getattr(self, "_debounce_path", "")
        if path:
            filename = os.path.basename(path)
            ext = os.path.splitext(path)[1].lower()
            if filename.startswith(".") or ext in (".tmp", ".log", ".lock", ".swp", ".bak", ".db", ".db-journal", ".db-wal", ".db-shm"):
                return

        self.bus.files_changed.emit(path)
        self.bus.status_message.emit("Folder contents changed")

        # Scoped index-to-disk reconciliation check: ensures any renamed/deleted files are instantly pruned.
        if self.current_path:
            try:
                from services.sqlite_indexer import IndexedFile
                with self.container.db.session() as session:
                    records = session.query(IndexedFile).filter(
                        IndexedFile.absolute_path.startswith(self.current_path)
                    ).all()
                    for r in records:
                        if not os.path.exists(r.absolute_path):
                            self.log.info("Watcher sync: cleaning deleted/moved file: %s", r.absolute_path)
                            self._reconcile_deletion(r.absolute_path)
            except Exception as exc:
                self.log.error("Folder deletion reconciliation failed: %s", exc)

        if path and os.path.exists(path):
            # New / modified file: re-index and reconcile AI evidence.
            self._incremental_reindex(path)
            # Batch 4 M0-02 — reconcile AI evidence/vectors with the filesystem.
            self._ai_sync_path(path)
        elif path:
            self._reconcile_deletion(path)


    def _reconcile_deletion(self, changed_path: str) -> None:
        """Submit background cleanup for a confirmed-deleted path."""
        self.container.tasks.submit(
            self._perform_deletion_cleanup,
            "file_cleanup",
            None,
            changed_path,
            on_error=lambda err: self.log.error("File cleanup error: %s", err),
        )

    def _perform_deletion_cleanup(self, progress_callback, cancel_event, changed_path: str):
        """Background worker: full derived-state cleanup for one deleted path."""
        if cancel_event and cancel_event.is_set():
            return None
        try:
            from services.file_cleanup import cleanup_deleted_file
            report = cleanup_deleted_file(
                abs_path=changed_path,
                session_factory=self.container.db.session,
                retrieval=self.container.retrieval_engine,
                db_store=self.container.db_store,
                graph_engine=getattr(self.container, "graph_engine", None),
                vector_engine=self.container.vector_engine,
            )
            self.log.info("Deletion cleanup for %s → %s", changed_path, report)
            if hasattr(self.docks, "indexed_files_widget"):
                self.docks.indexed_files_widget.refresh_data()
        except Exception as exc:
            self.log.error("Deletion cleanup failed for %s: %s", changed_path, exc)
        return None

    def _incremental_reindex(self, changed_path: str) -> None:
        """Submit incremental re-indexing as a background task using the full pipeline."""
        self.container.tasks.submit(
            self._perform_incremental_reindex,
            "incremental_reindex",
            None,
            changed_path,
            on_finished=self._incremental_reindex_complete,
            on_error=lambda err: self.log.error("Incremental reindex error: %s", err),
        )

    def _perform_incremental_reindex(self, progress_callback, cancel_event, changed_path: str):
        """Background worker: full pipeline reindex for new/modified files."""
        from datetime import datetime
        from services.folder_scanner import DiscoveredItem
        from services.metadata_extractor import MetadataExtractor
        from services.text_extractor import TextExtractor
        from services.sqlite_indexer import SQLiteIndexer, IndexedFile

        # Determine file paths to consider
        if os.path.isfile(changed_path):
            file_paths = [changed_path]
        elif os.path.isdir(changed_path):
            file_paths = [
                os.path.join(changed_path, f)
                for f in os.listdir(changed_path)
                if os.path.isfile(os.path.join(changed_path, f))
            ]
        else:
            return []

        if not file_paths:
            return []

        # Check which files are new or modified compared to the index
        session_factory = self.container.db.session
        items_to_index: list[DiscoveredItem] = []

        with session_factory() as session:
            for fp in file_paths:
                if cancel_event and cancel_event.is_set():
                    break
                try:
                    stat = os.stat(fp)
                    mtime = datetime.fromtimestamp(stat.st_mtime)

                    existing = session.query(IndexedFile).filter_by(absolute_path=fp).first()
                    if existing is None:
                        # New file
                        items_to_index.append(DiscoveredItem(
                            path=fp,
                            name=os.path.basename(fp),
                            parent=os.path.dirname(fp),
                            size=stat.st_size,
                            modified=mtime,
                            is_dir=False,
                        ))
                    elif existing.modified_date and mtime > existing.modified_date:
                        # Modified file
                        items_to_index.append(DiscoveredItem(
                            path=fp,
                            name=os.path.basename(fp),
                            parent=os.path.dirname(fp),
                            size=stat.st_size,
                            modified=mtime,
                            is_dir=False,
                        ))
                except OSError:
                    continue

        if not items_to_index:
            return []

        # Full pipeline: metadata → text → index
        metadata_extractor = MetadataExtractor(cancel_event=cancel_event)
        text_extractor = TextExtractor(cancel_event=cancel_event)
        indexer = SQLiteIndexer(session_factory, progress_callback=progress_callback, cancel_event=cancel_event)

        metadata_results = metadata_extractor.process_items(items_to_index)
        text_results = text_extractor.process_items(items_to_index)
        indexed_results = indexer.index_items(items_to_index, metadata_results, text_results)

        return indexed_results

    def _incremental_reindex_complete(self, result) -> None:
        """Handle completion of incremental re-indexing."""
        if result:
            self.log.info("Incremental reindex complete: %d items", len(result))
            # Automatically run AI reindexing in background for new or modified files
            for item in result:
                file_path = item.get("path")
                if file_path and os.path.exists(file_path):
                    self.log.info("Watcher sync: scheduling background AI reindexing for: %s", file_path)
                    self.container.tasks.submit(
                        self._perform_ai_reindex_file,
                        "ai_reindex_file",
                        None,
                        file_path,
                        on_error=lambda err: self.log.error("Background AI reindex failed for %s: %s", file_path, err)
                    )
        # Refresh the indexed files widget if available
        if hasattr(self.docks, 'indexed_files_widget'):
            self.docks.indexed_files_widget.refresh_data()

    def _perform_ai_reindex_file(self, progress_callback, cancel_event, file_path: str):
        """Background worker to extract features/OCR/Whisper and save vector mapping for a file."""
        if cancel_event and cancel_event.is_set():
            return None
        try:
            from engines.ai_indexer import AIFolderIndexer
            indexer = AIFolderIndexer(
                retrieval_engine=self.container.retrieval_engine,
                db_store=self.container.db_store,
                graph_engine=self.container.graph_engine,
                resources=self.container.ai_resources,
            )
            count = indexer.reindex_file(file_path)
            if count > 0:
                self.log.info("Watcher sync: successfully indexed %d vector chunks for %s", count, os.path.basename(file_path))
                # Save FAISS index
                self.container.retrieval_engine._vector.save()
        except Exception as exc:
            self.log.error("Watcher sync: AI reindexing failed for %s: %s", file_path, exc)
        return None

    # ------------------------------------------------------------------ #
    # Batch 4 M0-02 — AI evidence / FAISS filesystem synchronization
    # ------------------------------------------------------------------ #
    def _ai_sync_path(self, changed_path: str) -> None:
        """Reconcile AI evidence for filesystem change (only when auto_sync is explicitly enabled)."""
        if not changed_path:
            return
        if not self.container.config.get("ai.auto_sync", False):
            return

        try:
            retrieval = self.container.retrieval_engine
            if retrieval.indexed_count == 0:
                return  # nothing indexed → nothing to reconcile
        except Exception:
            return
        try:
            self.container.tasks.submit(
                self._perform_ai_sync,
                "ai_sync",
                None,
                changed_path,
                on_finished=self._ai_sync_complete,
                on_error=lambda err: self.log.error("AI sync error: %s", err),
            )
        except Exception as exc:
            self.log.debug("AI sync not submitted: %s", exc)

    def _perform_ai_sync(self, progress_callback, cancel_event, changed_path: str):
        """Background worker: AI-level reconciliation for one changed path."""
        if cancel_event and cancel_event.is_set():
            return None
        try:
            from engines.ai_indexer import AIFolderIndexer
            retrieval = self.container.retrieval_engine
            indexer = AIFolderIndexer(
                retrieval_engine=retrieval,
                db_store=self.container.db_store,
                graph_engine=getattr(self.container, "graph_engine", None),
            )

            abs_path = os.path.abspath(changed_path)
            if os.path.isfile(abs_path):
                ext = os.path.splitext(abs_path)[1].lower()
                from engines.config import SKIP_EXTENSIONS
                if ext in SKIP_EXTENSIONS:
                    return None
                # Reindex (removes stale evidence + vectors first, then re-adds)
                count = indexer.reindex_file(abs_path, cancel_event=cancel_event)
                if count > 0:
                    self.container.vector_engine.save()
            elif not os.path.exists(abs_path):
                # Deleted file: orchestrated cleanup — Batch-1 index row,
                # AI evidence + vectors, graph, relationships, collections,
                # suggestions (Batch 5 §3.1).
                from services.file_cleanup import cleanup_deleted_file
                report = cleanup_deleted_file(
                    abs_path=abs_path,
                    session_factory=self.container.db.session,
                    retrieval=retrieval,
                    db_store=self.container.db_store,
                    graph_engine=getattr(self.container, "graph_engine", None),
                    vector_engine=self.container.vector_engine,
                )
                self.log.info("AI sync: cleaned deleted %s → %s", abs_path, report)
        except Exception as exc:
            self.log.error("AI sync failed for %s: %s", changed_path, exc)
        return None

    def _ai_sync_complete(self, result) -> None:
        """Handle completion of the AI sync task."""
        self.log.debug("AI sync complete")

    def _warmup_ai(self, progress_callback, cancel_event):
        """Lightweight startup check — lazy loads AI engines only when requested by user."""
        if cancel_event and cancel_event.is_set():
            return None
        import gc
        gc.collect()
        return None


    def _prune_tasks(self, progress_callback, cancel_event):
        """Background: prune old finished task rows (Batch 7 task hygiene)."""
        if cancel_event and cancel_event.is_set():
            return 0
        try:
            removed = self.container.tasks.prune()
            self.log.info("Task prune: removed %d stale rows", removed)
            return removed
        except Exception as exc:
            self.log.debug("Task prune failed: %s", exc)
            return 0

    def _on_file_selected_from_index(self, path: str) -> None:
        """Handle file selection from the Indexed Files panel."""
        if path and os.path.exists(path):
            self.preview.show_file(path)

    def _on_task_progress(self, task_id: str, current: int, total: int) -> None:
        if total:
            self.status.set_task_status(f"Task {int(current / total * 100)}%")
        else:
            self.status.set_task_status("Working...")

    def _on_settings_changed(self, key: str) -> None:
        if key == "explorer.default_view":
            view = self.container.config.get("explorer.default_view", "list")
            self.explorer.set_view(view)
            self.toolbar.view_combo.setCurrentText(view.capitalize())
        elif key == "explorer.show_hidden":
            self.explorer.set_show_hidden(
                self.container.config.get("explorer.show_hidden", False)
            )
        elif key.startswith("performance.") or key.startswith("compute."):
            try:
                self.container.apply_performance_settings()
            except Exception as exc:
                self.log.debug("Performance live-apply skipped: %s", exc)

    def _on_scan_requested(self) -> None:
        """Handle Scan Folder toolbar action - M1"""
        path = self.current_path
        if not path or not os.path.isdir(path):
            self.bus.status_message.emit("No valid folder to scan")
            return

        self.bus.status_message.emit(f"Starting batch 1 scan of {path}...")
        self.log.info("Batch 1 scan requested for %s", path)

        # Show progress dialog
        self.b1_dialog = B1ProgressDialog(self)
        self.b1_scan_task_id = self.container.tasks.submit(
            self._perform_batch1_scan,
            "batch_1_scan",
            None,
            path,
            on_finished=self._batch1_scan_complete,
            on_progress=self._update_batch1_progress,
            on_error=self._batch1_scan_error,
        )
        self.b1_dialog.set_cancel_button_enabled(True)
        self.b1_dialog.rejected.connect(self._cancel_batch1_scan)
        self.b1_dialog.show()

    def _cancel_batch1_scan(self) -> None:
        """Cancel the running Batch 1 scan task."""
        if hasattr(self, 'b1_scan_task_id'):
            self.container.tasks.cancel(self.b1_scan_task_id)
            self.bus.status_message.emit("Batch 1 scan cancelled")
            self.status.set_task_status("Cancelled")
            self.log.info("Batch 1 scan cancelled by user")

    def _perform_batch1_scan(self, progress_callback, cancel_event, root_path: str):
        """Perform a complete Batch 1 scan using all services."""
        from services.folder_scanner import FolderScanner
        from services.metadata_extractor import MetadataExtractor
        from services.text_extractor import TextExtractor
        from services.sqlite_indexer import SQLiteIndexer

        self._current_scan_items = []

        def _scan_progress(current, total):
            """Wrap progress to also track current file."""
            progress_callback(current, total)
            # Update current file label via items list
            if self._current_scan_items and current <= len(self._current_scan_items):
                item = self._current_scan_items[current - 1]
                self._last_scanned_file = item.path

        folder_scanner = FolderScanner(
            progress_callback=_scan_progress,
            cancel_event=cancel_event,
        )
        metadata_extractor = MetadataExtractor(cancel_event=cancel_event)
        text_extractor = TextExtractor(cancel_event=cancel_event)
        indexer = SQLiteIndexer(self.container.db.session)

        # Scan directory tree
        scan_results = folder_scanner.scan(root_path)
        self._current_scan_items = scan_results.items

        # Extract metadata and text for all items
        metadata_results = metadata_extractor.process_items(scan_results.items)
        text_results = text_extractor.process_items(scan_results.items)

        # Index all items into SQLite (indexer has its own progress callback)
        def _index_progress(current, total):
            progress_callback(current, total)
            if current <= len(scan_results.items):
                item = scan_results.items[current - 1]
                self._last_scanned_file = item.path

        indexer.progress_callback = _index_progress
        indexed_results = indexer.index_items(scan_results.items, metadata_results, text_results)

        return indexed_results

    def _update_batch1_progress(self, current: int, total: int) -> None:
        """Update progress for Batch 1 scan."""
        if hasattr(self, 'b1_dialog'):
            self.b1_dialog.update_progress(current, total)
            # Update current file label
            last_file = getattr(self, '_last_scanned_file', None)
            if last_file:
                self.b1_dialog.set_current_file(last_file)
            if current > 0:
                self.status.set_task_status(f"Scanning: {current}/{total} files")
                self.bus.status_message.emit(f"Scanning: {current}/{total} files")

    def _update_batch1_current_file(self, task_id: str, current_file: str) -> None:
        """Update current file being processed."""
        if hasattr(self, 'b1_dialog'):
            self.b1_dialog.set_current_file(current_file)

    def _batch1_scan_complete(self, result) -> None:
        """Handle completion of Batch 1 scan."""
        if hasattr(self, 'b1_dialog'):
            try:
                self.b1_dialog.rejected.disconnect(self._cancel_batch1_scan)
            except Exception:
                pass
            self.b1_dialog.accept()


        if isinstance(result, Exception):
            self.bus.status_message.emit(f"Batch 1 scan failed: {result}")
            self.status.set_task_status("Scan failed")
            self.log.error("Batch 1 scan failed: %s", result)
        else:
            count = len(result) if result else 0
            self.bus.status_message.emit(
                f"Batch 1 scan complete: {count} items indexed"
            )
            self.status.set_task_status("Ready")
            self.log.info("Batch 1 scan completed successfully")

        # Always refresh the Indexed Files widget after scan attempt
        if hasattr(self.docks, 'indexed_files_widget'):
            self.docks.indexed_files_widget.refresh_data()

    def _batch1_scan_error(self, error) -> None:
        """Handle error in Batch 1 scan."""
        if hasattr(self, 'b1_dialog'):
            self.b1_dialog.set_current_file(f"Error: {error}")
            self.b1_dialog.close()

        self.bus.status_message.emit(f"Batch 1 error: {error}")
        self.status.set_task_status("Scan error")
        self.log.error("Batch 1 scan error: %s", error)

        # Still refresh in case partial data was indexed
        if hasattr(self.docks, 'indexed_files_widget'):
            self.docks.indexed_files_widget.refresh_data()

    def _open_settings(self) -> None:
        dialog = SettingsDialog(
            self.container.config,
            self.bus,
            self.theme_engine,
            self.container.repository,
            self,
        )
        dialog.exec()

    # ------------------------------------------------------------------ #
    # AI Analysis (Batch 2)
    # ------------------------------------------------------------------ #
    def _on_ai_analyze_requested(self, file_path: str) -> None:
        """Handle AI Analyze File request from context menu."""
        if not file_path or not os.path.isfile(file_path):
            self.bus.status_message.emit("Cannot analyze: invalid file")
            return

        # Compute file hash to check cache
        from services.file_identity import calculate_sha256_safe
        file_hash = calculate_sha256_safe(file_path)
        if not file_hash:
            self.bus.status_message.emit(f"Cannot read file: {file_path}")
            return

        # Check if we already have cached analysis
        from ai.cache_manager import AICacheManager
        cache = AICacheManager(self.container.db.session)
        cached = cache.get_analysis(file_hash)

        # Store context for the worker
        self._ai_file_path = file_path
        self._ai_file_hash = file_hash

        # Show dual-state dialog immediately
        from ui.dialogs.ai_analysis_dialog import AIAnalysisDialog
        dialog = AIAnalysisDialog(cached, os.path.basename(file_path), parent=self)
        self._active_ai_dialog = dialog

        dialog.run_analysis_requested.connect(
            lambda level, model: self._run_ai_analysis(file_path, file_hash, level, model)
        )
        dialog.regenerate_requested.connect(
            lambda level, model: self._on_ai_regenerate(level, model)
        )
        dialog.finished.connect(lambda _: setattr(self, "_active_ai_dialog", None))
        dialog.exec()

    def _run_ai_analysis(self, file_path: str, file_hash: str, detail_level: str = "medium", model: str = "qwen-local:latest") -> None:
        """Run AI analysis in a background worker with progress dialog."""
        from PySide6.QtWidgets import QProgressDialog
        from PySide6.QtCore import Qt

        model_display = "DeepSeek R1" if "deepseek" in (model or "").lower() else "Qwen Local"
        # Create progress dialog
        self._ai_progress = QProgressDialog(
            f"Starting AI analysis with {model_display}...", "Cancel", 0, 5, self
        )
        self._ai_progress.setWindowTitle(f"AI Analysis — {model_display}")
        self._ai_progress.setWindowModality(Qt.WindowModal)
        self._ai_progress.setMinimumDuration(0)
        self._ai_progress.setValue(0)
        self._ai_progress.show()

        # Submit background task
        self._ai_task_id = self.container.tasks.submit(
            self._perform_ai_analysis,
            "ai_analysis",
            None,
            file_path,
            file_hash,
            detail_level,
            model,
            on_finished=self._ai_analysis_complete,
            on_progress=self._ai_analysis_progress,
            on_error=self._ai_analysis_error,
        )

        # Wire cancel button
        self._ai_progress.canceled.connect(self._cancel_ai_analysis)

    def _perform_ai_analysis(self, progress_callback, cancel_event, file_path: str, file_hash: str, detail_level: str = "medium", model: str = "qwen-local:latest"):
        """Background worker: full AI analysis pipeline delegated to AnalysisManager."""
        from ai import AIService, AICacheManager
        from ai.analysis_manager import AnalysisManager

        ai_service = self.container.ai_service
        cache_manager = AICacheManager(self.container.db.session)

        manager = AnalysisManager(ai_service=ai_service, cache_manager=cache_manager)
        return manager.analyze_file(
            file_path=file_path,
            detail_level=detail_level,
            progress_callback=progress_callback,
            cancel_event=cancel_event,
            model=model,
        )

    def _ai_analysis_progress(self, current: int, total: int) -> None:
        """Update AI analysis progress dialog."""
        if hasattr(self, '_ai_progress') and self._ai_progress:
            steps = ["Extracting Text...", "Building Prompt...", "Generating AI...", "Parsing Response...", "Saving..."]
            if 0 < current <= len(steps):
                self._ai_progress.setLabelText(steps[current - 1])
            self._ai_progress.setValue(current)

    def _ai_analysis_complete(self, result) -> None:
        """Handle AI analysis completion."""
        if hasattr(self, '_ai_progress') and self._ai_progress:
            self._ai_progress.close()
            self._ai_progress = None

        if result is None:
            self.bus.status_message.emit("AI analysis cancelled")
            return

        if isinstance(result, dict) and "error" in result:
            self._ai_analysis_error(result["error"])
            return

        file_name = os.path.basename(getattr(self, '_ai_file_path', ''))
        self.bus.status_message.emit(f"AI analysis complete: {file_name}")
        
        # Update dialog in-place if still open
        if hasattr(self, "_active_ai_dialog") and self._active_ai_dialog:
            self._active_ai_dialog.update_analysis(result)

    def _ai_analysis_error(self, error) -> None:
        """Handle AI analysis error."""
        if hasattr(self, '_ai_progress') and self._ai_progress:
            self._ai_progress.close()
            self._ai_progress = None

        from PySide6.QtWidgets import QMessageBox
        error_msg = str(error)
        self.log.error("AI analysis error: %s", error_msg)
        self.bus.status_message.emit(f"AI analysis failed: {error_msg}")
        QMessageBox.warning(self, "AI Analysis Error", f"Analysis failed:\n\n{error_msg}")

        # Update active dialog with error state if open
        if hasattr(self, "_active_ai_dialog") and self._active_ai_dialog:
            self._active_ai_dialog.update_analysis({"error": error_msg})

    def _cancel_ai_analysis(self) -> None:
        """Cancel the running AI analysis task."""
        if hasattr(self, '_ai_task_id'):
            self.container.tasks.cancel(self._ai_task_id)
            self.bus.status_message.emit("AI analysis cancelled")

    def _on_ai_regenerate(self, detail_level: str, model: str = "qwen-local:latest") -> None:
        """Handle regenerate request from AI dialog."""
        file_path = getattr(self, '_ai_file_path', '')
        file_hash = getattr(self, '_ai_file_hash', '')
        if file_path and file_hash:
            try:
                # Delete cached analysis and re-run
                from ai.cache_manager import AICacheManager
                cache = AICacheManager(self.container.db.session)
                cache.delete_analysis(file_hash)
                self._run_ai_analysis(file_path, file_hash, detail_level, model)
            except Exception as e:
                self.log.error("Error regenerating analysis: %s", e)

    # ------------------------------------------------------------------ #
    # Semantic Search & Ask AI (Batch 3)
    # ------------------------------------------------------------------ #
    def _on_semantic_search_requested(self) -> None:
        """Handle Semantic Search request from context menu."""
        if not self._ensure_ai_index():
            return
        self._open_semantic_search_dialog()

    def _on_semantic_search_from_toolbar(self, query: str) -> None:
        """Handle semantic search from toolbar search box."""
        query = query.strip()
        if not query:
            return
        if not self._ensure_ai_index():
            return
        dialog = self._open_semantic_search_dialog()
        dialog.search_input.setText(query)
        # Trigger search immediately
        dialog._on_search()

    def _ensure_ai_index(self) -> bool:
        """Batch 4 M0-01 — never present a searchable UI with an empty index.

        Returns True when semantic search / chat can proceed. If no AI index
        exists, offers the user to run "Index for AI" right away.
        """
        try:
            indexed = self.container.retrieval_engine.indexed_count
        except Exception:
            indexed = 0
        if indexed > 0:
            return True

        from PySide6.QtWidgets import QMessageBox
        reply = QMessageBox.question(
            self,
            "No AI Index",
            "No AI index is available for this workspace.\n\n"
            "Index your files to enable AI search and chat.",
            QMessageBox.Yes | QMessageBox.Cancel,
            QMessageBox.Yes,
        )
        if reply != QMessageBox.Yes:
            return False
        self._on_ai_index_requested()
        return False

    def _open_semantic_search_dialog(self):
        """Open the Semantic Search dialog and wire it up."""
        from ui.dialogs.semantic_search_dialog import SemanticSearchDialog

        dialog = SemanticSearchDialog(parent=self)
        dialog.search_requested.connect(
            lambda q, m: self._perform_semantic_search(q, m, dialog)
        )
        dialog.file_open_requested.connect(self._on_file_activated)
        dialog.evidence_open_requested.connect(self._on_evidence_location_requested)
        # Batch 5 §13 — attach the saved-search manager for Save/Run/Delete.
        try:
            dialog.set_saved_search_manager(self.container.saved_search_manager)
            dialog.set_on_saved_changed(
                lambda: self.bus.saved_search_updated.emit(0)
            )
        except Exception as exc:
            self.log.debug("Saved search manager unavailable: %s", exc)
        dialog.show()
        return dialog

    def _perform_semantic_search(self, query: str, modality: str, dialog) -> None:
        """Run smart semantic search in a background thread and feed results to dialog.

        Args:
            query: The user's search query.
            modality: Explicit modality filter ('all', 'document', 'image',
                'audio', 'video') from the dialog's Type combo.
            dialog: The SemanticSearchDialog to feed results to.
        """
        self.log.info("Semantic search: '%s' (modality=%s)", query[:50], modality)
        self.bus.status_message.emit(f"Semantic search: {query[:30]}...")
        modality = modality or "all"
        # Batch 6 — natural-language filters (B6-03). Parsed here so the
        # semantic embedding uses only the remaining text and the results are
        # narrowed by the structured constraints. Scope "in this folder"
        # resolves against the folder currently open in the explorer.
        folder_scope_path = self.current_path
        nl_filters = bool(getattr(dialog, "nl_filters_enabled", lambda: True)())

        def _do_search(progress_callback, cancel_event, q, m):
            import time
            start_time = time.time()
            retrieval = self.container.retrieval_engine
            if retrieval.indexed_count == 0:
                return "NO_INDEX"

            # Parse NL filters (if enabled); the remaining text becomes the
            # semantic query.
            parsed = None
            effective_query = q
            if nl_filters:
                try:
                    from services.nl_filter_parser import parse_query
                    parsed = parse_query(q)
                    if parsed.semantic_query and parsed.semantic_query != q:
                        effective_query = parsed.semantic_query
                except Exception:
                    parsed = None

            # When a modality filter or parsed filters are active, over-fetch
            # candidates so the filter (applied after dedup) does not starve.
            has_parsed = bool(parsed and parsed.has_filters)
            top_k = 50
            response = retrieval.smart_retrieve(query=effective_query, top_k=top_k)

            scope_filter = getattr(dialog, "scope_filter", "folder")
            if scope_filter == "folder" and folder_scope_path:
                clean_folder = os.path.abspath(folder_scope_path).rstrip(os.sep)
                clean_folder_slash = clean_folder + os.sep
                response.results = [
                    r for r in response.results
                    if os.path.abspath(r.file_path).startswith(clean_folder_slash)
                    or os.path.abspath(r.file_path) == clean_folder
                ]

            # Explicit modality filter from the UI (All/Documents/Images/Audio/Video)
            if m and m != "all":
                filtered = retrieval.filter_results_by_modality(response.results, m)
                if not filtered:
                    return []
                response.results = filtered[:50]

            # Batch 6 — apply parsed metadata filters (extension / date /
            # size / folder scope) against the Batch-1 index.
            if parsed is not None and parsed.has_filters:
                filtered = self._apply_search_metadata_filters(
                    response.results, parsed, folder_scope_path
                )
                if not filtered:
                    return []
                response.results = filtered[:50]

            # Results are already ranked by relevance score from
            # smart_retrieve; do NOT re-sort by modality here.



            # Convert results to dicts, carrying full evidence provenance
            # so the UI can navigate to the exact page / timestamp.
            result_dicts = []
            for r in response.results:
                result_dicts.append({
                    "score": r.score,
                    "text": r.text,
                    "source_label": r.source_label,
                    "source_type": r.source_type,
                    "source_index": r.source_index,
                    "file_path": r.file_path,
                    "modality": r.modality,
                    "timestamp_start": r.timestamp_start,
                    "timestamp_end": r.timestamp_end,
                    "match_strength": r.match_strength,
                })

            # Record search history with the real elapsed time.
            try:
                self.container.db_store.record_search(
                    query=q,
                    scope=m or "all",
                    results_count=len(result_dicts),
                    elapsed_ms=int((time.time() - start_time) * 1000),
                )
            except Exception as exc:
                self.log.debug("Failed to record search history: %s", exc)

            # Return vector-ranked results directly sorted by cosine similarity
            return result_dicts


        def _on_complete(response):
            if response is None:
                dialog.set_error("Search returned no response")
                return
            if response == "NO_INDEX":
                dialog.set_error(
                    "No files indexed yet. Click 'Index for AI' to index "
                    "files in the current folder for semantic search."
                )
                return
            # Handle RetrievalResponse (when embedding fails)
            if hasattr(response, 'embedding_available'):
                if not response.embedding_available:
                    dialog.set_error(
                        "Embedding service unavailable. "
                        "Please ensure Ollama is running with nomic-embed-text model."
                    )
                    return
                if not response.results:
                    dialog.set_results([])
                    return

            # response is a list of dicts (after reranking)
            if isinstance(response, list):
                dialog.set_results(response)
                self.bus.status_message.emit(
                    f"Semantic search: {len(response)} result(s)"
                )
            else:
                dialog.set_results([])

        def _on_error(error):
            self.log.error("Semantic search error: %s", error)
            dialog.set_error(str(error))
            self.bus.status_message.emit("Semantic search failed")

        self.container.tasks.submit(
            _do_search,
            "semantic_search",
            None,
            query,
            modality,
            on_finished=_on_complete,
            on_error=_on_error,
        )

    def _apply_search_metadata_filters(self, results, parsed, folder_scope_path: str) -> list:
        """Narrow retrieval results by parsed NL constraints (B6-03).

        Constraints are validated against the Batch-1 index (extension, size,
        modified date) and the folder scope. Files whose metadata is unknown
        are excluded when a filter requires that metadata (conservative).
        """
        import os as _os
        from datetime import datetime as _dt

        try:
            from services.sqlite_indexer import IndexedFile

            paths = [r.file_path for r in results]
            meta: dict = {}
            with self.container.db.session() as session:
                rows = (
                    session.query(IndexedFile.absolute_path, IndexedFile.extension,
                                 IndexedFile.size, IndexedFile.modified_date)
                    .filter(IndexedFile.absolute_path.in_(paths))
                    .all()
                )
                for p, ext, size, mtime in rows:
                    meta[p] = {"ext": (ext or _os.path.splitext(p)[1].lower()).lower(),
                               "size": size, "mtime": mtime}
            for p in paths:
                if p not in meta:
                    ext = _os.path.splitext(p)[1].lower()
                    meta[p] = {"ext": ext, "size": None, "mtime": None}
        except Exception as exc:
            self.log.debug("Metadata filter lookup failed: %s", exc)
            return list(results)

        if parsed.extensions:
            allowed = set(parsed.extensions)
        else:
            allowed = None
        out = []
        for r in results:
            p = r.file_path
            m = meta.get(p, {})
            ext = m.get("ext") or _os.path.splitext(p)[1].lower()
            size = m.get("size")
            mtime = m.get("mtime")

            if parsed.scope == "folder" and folder_scope_path:
                if not (p == folder_scope_path or p.startswith(folder_scope_path.rstrip("/") + "/")):
                    continue
            if allowed is not None and ext not in allowed:
                continue
            if parsed.modified_after is not None:
                if mtime is None:
                    continue
                mtime_dt = mtime if isinstance(mtime, _dt) else _dt.fromisoformat(str(mtime))
                if mtime_dt.replace(tzinfo=None) < parsed.modified_after.replace(tzinfo=None):
                    continue
            if parsed.modified_before is not None:
                if mtime is None:
                    continue
                mtime_dt = mtime if isinstance(mtime, _dt) else _dt.fromisoformat(str(mtime))
                if mtime_dt.replace(tzinfo=None) > parsed.modified_before.replace(tzinfo=None):
                    continue
            if parsed.size_min is not None:
                if size is None or size < parsed.size_min:
                    continue
            if parsed.size_max is not None:
                if size is None or size > parsed.size_max:
                    continue
            out.append(r)
        return out

    def _on_evidence_location_requested(self, result: dict) -> None:
        """Navigate to the exact evidence location of a search result.

        Uses the EvidenceNavigator to route modality-aware navigation:
        PDF page jump, audio/video seek, image preview or plain open.
        """
        from services.evidence_navigator import EvidenceLocation, EvidenceNavigator

        file_path = result.get("file_path", "")
        if not file_path or not os.path.exists(file_path):
            self.bus.status_message.emit("Evidence source file no longer exists")
            return

        location = EvidenceLocation(
            file_path=file_path,
            modality=result.get("modality", "document"),
            source_type=result.get("source_type", ""),
            source_index=result.get("source_index", 0) or 0,
            source_label=result.get("source_label", ""),
            timestamp_start=result.get("timestamp_start", 0.0) or 0.0,
            timestamp_end=result.get("timestamp_end", 0.0) or 0.0,
            page=(result.get("source_index", 0) or 0) + 1
            if result.get("source_type") == "page" else 0,
            score=result.get("score", 0.0) or 0.0,
        )

        navigator = EvidenceNavigator(
            open_file=self._on_file_activated,
            jump_pdf=self._preview_jump_pdf,
            jump_slide=self._preview_jump_slide,
            jump_section=self._preview_jump_section,
            play_media=self.preview.seek_media,
            preview_file=self.preview.show_file,
        )
        navigator.navigate(location)

    def _preview_jump_pdf(self, file_path: str, page: int) -> None:
        """Open PDF in default external PDF reader application."""
        if not file_path or not os.path.exists(file_path):
            return
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices
        QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.abspath(file_path)))


    def _preview_jump_slide(self, file_path: str, slide_index: int) -> None:
        """Show a PPTX and jump to a specific slide (evidence nav)."""
        if not file_path or not os.path.exists(file_path):
            return
        self.preview.jump_to_slide(file_path, int(slide_index or 0))

    def _preview_jump_section(self, file_path: str, section_index: int) -> None:
        """Show a DOCX/section-based document and jump to a section."""
        if not file_path or not os.path.exists(file_path):
            return
        self.preview.jump_to_section(file_path, int(section_index or 0))

    def _on_ask_ai_requested(self, file_path: str) -> None:
        """Handle Ask AI about this File from context menu."""
        if not file_path or not os.path.isfile(file_path):
            self.bus.status_message.emit("Cannot ask AI: invalid file")
            return

        from ui.dialogs.ask_ai_dialog import AskAIDialog

        dialog = AskAIDialog(file_path, parent=self)
        dialog.question_submitted.connect(
            lambda question, fp, model: self._perform_ask_ai(question, fp, dialog, model)
        )
        dialog.citation_activated.connect(self._on_file_activated)
        dialog.show()

    def _perform_ask_ai(self, question: str, file_path: str, dialog, model: str = "qwen-local:latest") -> None:
        """Run direct full-file AI query (Tier 1) in a background thread."""
        self.log.info("Ask AI (direct): '%s' about '%s' [model=%s]", question[:50], file_path, model)
        self.bus.status_message.emit(f"Ask AI: reading file & thinking ({model})...")

        def _do_ask(progress_callback, cancel_event, q, fp, m):
            rag = self.container.rag_engine
            response = rag.ask_file_direct(question=q, file_path=fp, model=m)
            return response

        def _on_complete(response):
            if response is None:
                dialog.set_error("AI engine returned no response")
                return
            if not response.grounded:
                # Still show the answer (it contains a helpful message)
                dialog.set_answer(response.answer, [])
                self.bus.status_message.emit("Ask AI: could not process file")
                return
            # Convert Citation objects to dicts for the dialog
            citations = []
            for c in response.citations:
                citations.append({
                    "source_label": c.source_label,
                    "file_path": c.file_path,
                    "score": c.score,
                    "snippet": c.text_snippet,
                })
            dialog.set_answer(response.answer, citations)
            elapsed_s = response.elapsed_ms / 1000
            self.bus.status_message.emit(
                f"Ask AI: answered in {elapsed_s:.1f}s"
            )

        def _on_error(error):
            self.log.error("Ask AI error: %s", error)
            dialog.set_error(str(error))
            self.bus.status_message.emit("Ask AI failed")

        self.container.tasks.submit(
            _do_ask,
            "ask_ai",
            None,
            question,
            file_path,
            model,
            on_finished=_on_complete,
            on_error=_on_error,
        )

    # ------------------------------------------------------------------ #
    # Index Folder for AI (Batch 3)
    # ------------------------------------------------------------------ #
    def _on_ai_index_requested(self) -> None:
        """Handle 'Index for AI' toolbar button."""
        if getattr(self, "_ai_indexing_in_progress", False):
            if hasattr(self, "_ai_index_progress") and self._ai_index_progress:
                self._ai_index_progress.activateWindow()
                self._ai_index_progress.raise_()
            self.bus.status_message.emit("AI indexing is already in progress...")
            return

        path = self.current_path
        if not path or not os.path.isdir(path):
            self.bus.status_message.emit("No valid folder to index")
            return

        self._ai_indexing_in_progress = True
        self.log.info("AI Index requested for: %s", path)
        self.bus.status_message.emit(f"AI Indexing: {path}...")

        # Show progress dialog
        from PySide6.QtWidgets import QProgressDialog
        from PySide6.QtCore import Qt

        self._ai_index_progress = QProgressDialog(
            "Preparing to index files...", "Cancel", 0, 100, self
        )
        self._ai_index_progress.setWindowTitle("Index Folder for AI")
        self._ai_index_progress.setWindowModality(Qt.ApplicationModal)
        self._ai_index_progress.setMinimumDuration(0)
        self._ai_index_progress.setMinimumWidth(400)
        self._ai_index_progress.setValue(0)
        self._ai_index_progress.show()

        # Submit background task
        self._ai_index_task_id = self.container.tasks.submit(
            self._perform_ai_index,
            "ai_index",
            None,
            path,
            on_finished=self._ai_index_complete,
            on_progress=self._ai_index_progress_update,
            on_error=self._ai_index_error,
        )

        self._ai_index_progress.canceled.connect(self._cancel_ai_index)

    def _perform_ai_index(self, progress_callback, cancel_event, folder_path: str):
        """Background worker: index all files in folder."""
        from engines.ai_indexer import AIFolderIndexer, IndexingProgress

        retrieval = self.container.retrieval_engine

        def _on_progress(prog: IndexingProgress):
            if prog.total > 0:
                try:
                    from PySide6.QtCore import QMetaObject, Qt, Q_ARG
                    QMetaObject.invokeMethod(
                        self,
                        "_ai_index_progress_update",
                        Qt.QueuedConnection,
                        Q_ARG(int, prog.current),
                        Q_ARG(int, prog.total),
                    )
                except Exception:
                    pass

        indexer = AIFolderIndexer(
            retrieval_engine=retrieval,
            progress_callback=_on_progress,
            db_store=self.container.db_store,
            graph_engine=self.container.graph_engine,
        )

        result = indexer.index_folder(
            folder_path,
            recursive=True,
            cancel_event=cancel_event,
        )

        # Save FAISS index to disk
        self.container.vector_engine.save()

        return result


    @Slot(int, int)
    def _ai_index_progress_update(self, current: int, total: int) -> None:
        """Update AI indexing progress dialog safely on Main GUI Thread."""
        dialog = getattr(self, "_ai_index_progress", None)
        if dialog is not None:
            try:
                if total == 0:
                    dialog.setValue(100)
                    dialog.setLabelText("All files are already indexed and up to date!")
                else:
                    percent = int((current / total) * 100)
                    dialog.setValue(percent)
                    dialog.setLabelText(f"Indexing new/modified files... ({current}/{total})")
            except Exception:
                pass

    def _ai_index_complete(self, result) -> None:
        """Handle AI indexing completion."""
        self._ai_indexing_in_progress = False
        dialog = getattr(self, "_ai_index_progress", None)
        if dialog is not None:
            try:
                dialog.canceled.disconnect(self._cancel_ai_index)
            except Exception:
                pass
            try:
                dialog.close()
            except Exception:
                pass
            self._ai_index_progress = None

        if result is None:
            self.bus.status_message.emit("AI indexing cancelled")
            return

        unchanged = getattr(result, "unchanged_skipped", 0)
        no_content = getattr(result, "no_content_skipped", 0)

        if result.indexed_files == 0 and unchanged > 0:
            msg = f"All {unchanged} files are already indexed and up to date."
        else:
            msg = (
                f"AI Index complete: {result.indexed_files} newly indexed, "
                f"{result.total_chunks} chunks, "
                f"{unchanged} already up to date"
            )
        if result.errors:
            msg += f", {len(result.errors)} errors"
        self.bus.status_message.emit(msg)
        self.log.info(msg)

        # Show summary
        from PySide6.QtWidgets import QMessageBox
        if result.indexed_files == 0 and unchanged > 0:
            QMessageBox.information(
                self, "AI Index Up to Date",
                f"All {unchanged} files in this folder are already indexed and up to date in the database.\n\n"
                f"No new or modified files found to process."
            )
        else:
            QMessageBox.information(
                self, "AI Indexing Complete",
                f"Processed {result.total_files} files in total:\n\n"
                f"• Newly Indexed / Modified: {result.indexed_files} files ({result.total_chunks} text chunks)\n"
                f"• Already Indexed (Skipped): {unchanged} files\n"
                f"• No extractable content: {no_content} files\n"
                f"• Errors: {len(result.errors)}\n\n"
                "All files in the folder are indexed and ready for Semantic Search & Workspace Chat."
            )

    def _ai_index_error(self, error) -> None:
        """Handle AI indexing error."""
        self._ai_indexing_in_progress = False
        if hasattr(self, '_ai_index_progress') and self._ai_index_progress:
            try:
                self._ai_index_progress.canceled.disconnect(self._cancel_ai_index)
            except Exception:
                pass
            self._ai_index_progress.close()
            self._ai_index_progress = None

        self.log.error("AI indexing error: %s", error)
        self.bus.status_message.emit(f"AI indexing failed: {error}")

        from PySide6.QtWidgets import QMessageBox
        QMessageBox.warning(self, "AI Indexing Error", f"Indexing failed:\n\n{error}")

    def _cancel_ai_index(self) -> None:
        """Cancel the running AI index task."""
        self._ai_indexing_in_progress = False
        if hasattr(self, '_ai_index_task_id'):
            self.container.tasks.cancel(self._ai_index_task_id)
            self.bus.status_message.emit("AI indexing cancelled")


    # ------------------------------------------------------------------ #
    # Batch 4 — Chat (Folder / Workspace)
    # ------------------------------------------------------------------ #
    def _on_folder_chat_requested(self, folder_path: str) -> None:
        """Open a Folder Chat scoped to the selected folder."""
        if not folder_path or not os.path.isdir(folder_path):
            self.bus.status_message.emit("Folder chat: invalid folder")
            return
        self._open_chat_dialog("folder", os.path.abspath(folder_path))

    def _on_workspace_chat_requested(self) -> None:
        """Open a Workspace Chat across the entire indexed workspace."""
        self._open_chat_dialog("workspace", "")


    def _on_conversation_history_requested(self) -> None:
        """Open the conversation history dialog (Batch 4 §44)."""
        from ui.dialogs.conversation_history_dialog import ConversationHistoryDialog

        manager = getattr(self.container, "conversation_manager", None)
        if manager is None:
            self.bus.status_message.emit("Conversations are not available")
            return
        convs = manager.list_conversations(limit=100)
        if not convs:
            self.bus.status_message.emit("No saved conversations yet")
            return
        data = [
            {
                "id": c.id,
                "title": c.title,
                "scope_type": c.scope_type,
                "scope_path": c.scope_path,
                "message_count": c.message_count,
                "updated_at": str(c.updated_at)[:16] if c.updated_at else "",
            }
            for c in convs
        ]
        dialog = ConversationHistoryDialog(
            data,
            parent=self,
            on_resume=self._resume_conversation,
            on_delete=self._delete_conversation,
        )
        dialog.show()

    def _resume_conversation(self, conversation_id: int) -> None:
        """Reopen a chat dialog bound to an existing conversation."""
        try:
            manager = self.container.conversation_manager
            conv = manager.get_conversation(conversation_id)
            if conv is None:
                self.bus.status_message.emit("Conversation no longer exists")
                return
            self._open_chat_dialog(
                conv.scope_type or "workspace",
                conv.scope_path or "",
                conversation_id=conversation_id,
            )
        except Exception as exc:
            self.log.error("Failed to resume conversation %s: %s", conversation_id, exc)
            self.bus.status_message.emit(f"Could not resume conversation: {exc}")

    def _delete_conversation(self, conversation_id: int) -> None:
        """Delete a saved conversation."""
        try:
            self.container.conversation_manager.delete(conversation_id)
            self.bus.status_message.emit("Conversation deleted")
        except Exception as exc:
            self.log.error("Failed to delete conversation %s: %s", conversation_id, exc)
            self.bus.status_message.emit(f"Could not delete conversation: {exc}")

    def _open_chat_dialog(self, scope_type: str, scope_path: str,
                          conversation_id: int | None = None) -> None:
        """Open a chat dialog for a scope, resuming a conversation if given."""
        from ui.dialogs.chat_dialog import ChatDialog

        if scope_type == "folder" and not scope_path:
            active_folder = getattr(self, "current_path", None) or getattr(self, "current_folder", None)
            if active_folder and os.path.isdir(active_folder):
                scope_path = os.path.abspath(active_folder)
            else:
                scope_type = "workspace"
                scope_path = ""

        dialog = ChatDialog(scope_type=scope_type, scope_path=scope_path, parent=self)
        dialog.send_requested.connect(
            lambda q, d=dialog: self._perform_chat(q, d)
        )
        dialog.stop_requested.connect(lambda d=dialog: self._cancel_chat(d))
        dialog.citation_activated.connect(self._on_chat_citation)
        dialog.show()

        try:
            manager = self.container.conversation_manager
            if conversation_id is None:
                conversation_id = manager.start(scope_type=scope_type, scope_path=scope_path)
            dialog._conversation_id = conversation_id
            history = manager.messages(conversation_id)
            dialog.load_history(history)
        except Exception as exc:
            self.log.error("Failed to start conversation: %s", exc)
            dialog.append_error(f"Could not start conversation: {exc}")
            dialog._conversation_id = None

    def _perform_chat(self, question: str, dialog) -> None:
        """Run a chat turn in a background worker."""
        conversation_id = getattr(dialog, "_conversation_id", None)
        if conversation_id is None:
            dialog.append_error("No active conversation. Restart the chat window.")
            return

        dialog.append_user(question)
        dialog.set_busy_state("retrieving")

        from conversation.conversation_service import run_chat

        def _do_chat(progress_callback, cancel_event, cid, q):
            return run_chat(
                progress_callback, cancel_event,
                self.container.conversation_manager, cid, q,
                top_k=self.container.config.get("batch4.top_k", 5),
                threshold=self.container.config.get("batch4.threshold", 0.3),
            )

        def _on_complete(result):
            if result is None:
                dialog.set_busy_state("failed")
                dialog.append_error("Chat engine returned no response.")
                return
            if getattr(result, "error", None) == "cancelled":
                dialog.set_busy_state("cancelled")
                return
            if not getattr(result, "grounded", False) or not getattr(result, "answer", ""):
                dialog.set_busy_state("failed")
                err = getattr(result, "error", None)
                if err == "embedding_unavailable":
                    dialog.append_error(
                        "Embedding service unavailable. Ensure Ollama is running with nomic-embed-text."
                    )
                elif err:
                    dialog.append_error(f"Chat failed: {err}")
                else:
                    dialog.append_error(
                        "I could not generate an answer. Ensure Ollama is running."
                    )
                return
            citations = getattr(result, "citations", []) or []
            dialog.append_assistant(
                result.answer, citations=[c.to_dict() for c in citations]
            )
            dialog.set_busy_state("completed")
            elapsed_s = (getattr(result, "elapsed_ms", 0) or 0) / 1000
            self.bus.status_message.emit(f"Chat answered in {elapsed_s:.1f}s")

        def _on_error(error):
            self.log.error("Chat error: %s", error)
            dialog.set_busy_state("failed")
            dialog.append_error(str(error))

        def _on_progress(cur, tot):
            if cur > 1:
                dialog.set_busy_state("generating")

        import uuid
        task_id = f"chat_{uuid.uuid4().hex}"
        dialog._current_task_id = task_id
        self.container.tasks.submit(
            _do_chat, "chat", task_id, conversation_id, question,
            on_finished=_on_complete,
            on_error=_on_error,
            on_progress=_on_progress,
        )


    def _cancel_chat(self, dialog) -> None:
        """Cancel the running chat turn."""
        task_id = getattr(dialog, "_current_task_id", None)
        if task_id:
            self.container.tasks.cancel(task_id)
        dialog.set_busy_state("cancelled")
        self.bus.status_message.emit("Chat cancelled")


    def _on_chat_citation(self, citation: dict) -> None:
        """Open a chat citation through the evidence navigator."""
        self._on_evidence_location_requested(citation)

    def _on_knowledge_graph_requested(self) -> None:
        """Open the Knowledge Graph dialog (Batch 4 M8)."""
        from graph.graph_query_service import GraphQueryService
        from ui.dialogs.graph_dialog import GraphDialog

        graph_engine = getattr(self.container, "graph_engine", None)
        if graph_engine is None:
            self.bus.status_message.emit("Knowledge graph is not available")
            return
        active_folder = getattr(self, "current_path", None) or getattr(self, "current_folder", None) or ""
        retrieval = getattr(self.container, "retrieval_engine", None)
        query_service = GraphQueryService(graph_engine.store)
        dialog = GraphDialog(
            query_service=query_service,
            folder_path=active_folder,
            retrieval=retrieval,
            on_evidence_navigate=self._on_graph_evidence_navigate,
            parent=self,
        )
        dialog.show()


    def _on_graph_evidence_navigate(self, file_path: str, evidence: dict) -> None:
        """Navigate to graph evidence through the evidence navigator."""
        self._on_evidence_location_requested({
            "file_path": file_path,
            "modality": "document",
            "source_type": evidence.get("source_type", "") or "",
            "source_index": evidence.get("source_index", 0) or 0,
            "source_label": evidence.get("source_label", "") or "",
            "timestamp_start": evidence.get("timestamp_start", 0.0) or 0.0,
            "timestamp_end": evidence.get("timestamp_end", 0.0) or 0.0,
        })

    def _on_agent_mode_requested(self) -> None:
        """Open Agent Mode dialog (Batch 4 M11)."""
        from ui.dialogs.agent_dialog import AgentDialog

        dialog = AgentDialog(parent=self)
        dialog.send_requested.connect(
            lambda q, d=dialog: self._perform_agent(q, d)
        )
        dialog.stop_requested.connect(lambda d=dialog: self._cancel_agent(d))
        dialog.citation_activated.connect(self._on_evidence_location_requested)
        self._agent_dialog = dialog
        dialog.show()

    def _perform_agent(self, request: str, dialog) -> None:
        """Run one agent turn in a background worker with live action status."""
        agent_engine = getattr(self.container, "agent_engine", None)
        if agent_engine is None:
            dialog.append_error("Agent engine is not available.")
            return

        dialog.append_user(request)
        dialog.set_state("generating")
        dialog.set_action("Planning…")

        # Bridge worker-thread callbacks to the GUI thread via Qt signals.
        from PySide6.QtCore import QObject, Signal as QtSignal

        class _Bridge(QObject):
            step = QtSignal(object)
            status = QtSignal(str)

        def _on_step(step) -> None:
            label = getattr(step, "summary", "") or ""
            icon = "✓" if getattr(step, "ok", False) else "✗"
            dialog.add_action_line(f"{icon} {label}")

        def _on_status(text: str) -> None:
            dialog.set_action("· " + text.replace("tool:", "executing "))

        bridge.step.connect(_on_step)
        bridge.status.connect(_on_status)

        def _do_agent(progress_callback, cancel_event, req):
            return agent_engine.run(
                req,
                cancel_event=cancel_event,
                on_step=bridge.step.emit,
                on_status=bridge.status.emit,
            )

        def _on_complete(state):
            if state is None:
                dialog.set_state("failed")
                dialog.append_error("Agent returned no state.")
                return
            status = getattr(state, "status", "error")
            if status == "cancelled":
                dialog.set_state("cancelled")
                dialog.set_action("Cancelled.")
                return
            if status == "timeout":
                dialog.set_state("failed")
                dialog.append_error("Agent timed out.")
                return
            if status == "max_steps":
                dialog.set_action("Reached maximum steps.")
            if status == "error":
                dialog.set_state("failed")
                dialog.append_error("Agent failed — see log.")
                return
            answer = ""
            for step in getattr(state, "steps", []) or []:
                if getattr(step, "tool", "") == "__synthesis__":
                    answer = getattr(step, "summary", "") or ""
            if not answer:
                answer = "I could not produce an answer. Try rephrasing or indexing more files."
            dialog.append_assistant(answer)
            dialog.set_state("completed")
            dialog.set_action(f"Completed in {state.elapsed():.1f}s")
            self.bus.status_message.emit(
                f"Agent finished: {len(state.steps)} steps"
            )

        def _on_error(error):
            self.log.error("Agent error: %s", error)
            dialog.set_state("failed")
            dialog.append_error(str(error))

        self._agent_task_id = self.container.tasks.submit(
            _do_agent, "agent", None, request,
            on_finished=_on_complete,
            on_error=_on_error,
        )

    def _cancel_agent(self, dialog) -> None:
        """Cancel the running agent turn."""
        if hasattr(self, "_agent_task_id"):
            self.container.tasks.cancel(self._agent_task_id)
        dialog.set_state("cancelled")
        dialog.set_action("Cancelled.")

    # ================================================================ #
    # Batch 5 — Intelligent Organization & Knowledge Management
    # ================================================================ #
    def _indexed_paths(self) -> list:
        """All indexed file paths from the Batch-1 index."""
        try:
            from services.sqlite_indexer import IndexedFile

            with self.container.db.session() as session:
                rows = session.query(IndexedFile.absolute_path).all()
                return [r[0] for r in rows]
        except Exception as exc:
            self.log.error("Failed to load indexed paths: %s", exc)
            return []

    # ------------------------------------------------------------------ #
    # B5-04 — Duplicate Files
    # ------------------------------------------------------------------ #
    def _on_duplicates_requested(self) -> None:
        """Tools → Duplicate Files — duplicate scan scoped to current folder."""
        from ui.dialogs.duplicate_dialog import DuplicateDialog

        folder_path = (
            self.current_path
            if hasattr(self, "current_path") and self.current_path and os.path.exists(self.current_path)
            else None
        )

        status_msg = (
            f"Scanning for duplicate files in {os.path.basename(folder_path)}..."
            if folder_path
            else "Scanning for duplicate files..."
        )
        # Open the Duplicate Files dialog IMMEDIATELY in loading state so user sees progress
        dialog = DuplicateDialog(
            groups=[],
            is_loading=True,
            on_open=self._on_file_activated,
            on_compare=self._open_file_comparison,
            on_removal_accept=self._accept_duplicate_removal,
            on_removal_dismiss=self._dismiss_duplicate_removal,
            parent=self,
        )
        dialog.compare_requested.connect(self._open_file_comparison)
        dialog.refresh_requested.connect(lambda: self._scan_duplicates(dialog, folder_path))
        dialog.clear_requested.connect(self._on_duplicate_clear_requested)
        dialog.show()
        self._scan_duplicates(dialog, folder_path)

    def _on_duplicate_clear_requested(self) -> None:
        """Clear all stored duplicate suggestions and notify user."""
        try:
            self.container.suggestion_engine.clear_all_duplicate_suggestions()
        except Exception as exc:
            self.log.debug("Failed to clear duplicate suggestions from store: %s", exc)
        self.bus.status_message.emit("Old duplicate scan results deleted. Ready to scan again.")

    def _scan_duplicates(self, dialog, folder_path: Optional[str] = None) -> None:
        """Run exact and near-duplicate scan in background task."""
        dialog.set_loading(True)

        def _do_scan(progress_callback, cancel_event):
            exact_groups = self.container.duplicate_engine.find_exact_duplicates(folder_path=folder_path)
            near_groups = []
            try:
                near_groups = self.container.duplicate_engine.find_near_duplicates(
                    similarity_service=self.container.similarity_service,
                    folder_path=folder_path,
                    threshold=0.80,
                )
            except Exception as exc:
                self.log.debug("Near duplicate scan skipped: %s", exc)

            groups = exact_groups + near_groups

            # Also refresh relationship edges for duplicate_of.
            try:
                rel_engine = self.container.relationship_engine
                rel_engine.rebuild_all(paths=[p for g in groups for p in g.files])
            except Exception as exc:
                self.log.debug("Relationship rebuild skipped: %s", exc)
            # Batch 6 §9 — safe removal recommendations (persisted, advisory).
            suggestions = []
            try:
                suggestions = self.container.suggestion_engine.suggest_duplicate_removals(groups)
            except Exception as exc:
                self.log.debug("Removal suggestions skipped: %s", exc)
            return groups, suggestions

        def _on_complete(pair):
            groups, suggestions = pair or ([], [])
            if not groups:
                self.bus.status_message.emit("No duplicate or similar files found")
            else:
                self.bus.status_message.emit(
                    f"Found {len(groups)} duplicate group(s) · "
                    f"{len(suggestions)} removal suggestion(s)"
                )
            self.bus.duplicates_updated.emit()
            self.bus.relationships_updated.emit()
            if dialog and dialog.isVisible():
                dialog.set_results(groups, suggestions)

        self.container.tasks.submit(
            _do_scan, "duplicate_scan", None,
            on_finished=_on_complete,
            on_error=lambda err: self.bus.status_message.emit(f"Duplicate scan failed: {err}"),
        )

    def _on_find_duplicates_requested(self, file_path: str) -> None:
        """File → AI → Find Duplicates for a selected file."""
        from ui.dialogs.duplicate_dialog import DuplicateDialog

        # Open dialog immediately in loading state, then run scan in background
        dialog = DuplicateDialog(
            groups=[],
            is_loading=True,
            file_path=file_path,
            on_open=self._on_file_activated,
            on_compare=self._open_file_comparison,
            on_removal_accept=self._accept_duplicate_removal,
            on_removal_dismiss=self._dismiss_duplicate_removal,
            parent=self,
        )
        dialog.compare_requested.connect(self._open_file_comparison)
        dialog.refresh_requested.connect(lambda: self._scan_duplicates_for_file(dialog, file_path))
        dialog.clear_requested.connect(self._on_duplicate_clear_requested)
        dialog.show()
        self._scan_duplicates_for_file(dialog, file_path)

    def _scan_duplicates_for_file(self, dialog, file_path: str) -> None:
        """Run exact and near-duplicate scan for a single file in background and update existing dialog."""
        if not dialog or not dialog.isVisible():
            return

        dialog.set_loading(True)

        def _do_scan(progress_callback, cancel_event):
            group = self.container.duplicate_engine.find_exact_duplicates_for_file(file_path)
            groups = [group] if group else []
            try:
                similars = self.container.similarity_service.near_duplicates(file_path)
                for s in similars:
                    if s.file_path and os.path.exists(s.file_path) and s.file_path != file_path:
                        sim_pct = int(round(s.score * 100))
                        g = DuplicateGroup(
                            checksum=f"near_{sim_pct}_{file_path}",
                            files=[file_path, s.file_path],
                            total_size=(
                                os.path.getsize(file_path)
                                + (os.path.getsize(s.file_path) if os.path.isfile(s.file_path) else 0)
                            ),
                        )
                        groups.append(g)
            except Exception as exc:
                self.log.debug("Near duplicate check for file skipped: %s", exc)

            suggestions = []
            if groups:
                try:
                    suggestions = self.container.suggestion_engine.suggest_duplicate_removals(groups)
                except Exception as exc:
                    self.log.debug("Removal suggestions skipped: %s", exc)
            return groups, suggestions

        def _on_complete(pair):
            groups, suggestions = pair or ([], [])
            if not groups:
                self.bus.status_message.emit("No duplicate or similar files found")
            else:
                self.bus.status_message.emit(
                    f"Found {len(groups)} duplicate group(s) · "
                    f"{len(suggestions)} removal suggestion(s)"
                )
            if dialog and dialog.isVisible():
                dialog.set_results(groups, suggestions)

        def _on_error(err):
            if dialog and dialog.isVisible():
                dialog.set_loading(False)
            self.bus.status_message.emit(f"Duplicate scan failed: {err}")

        self.container.tasks.submit(
            _do_scan, "duplicate_scan_file", None,
            on_finished=_on_complete,
            on_error=_on_error,
        )

    # ------------------------------------------------------------------ #
    # B6-04 — duplicate removal execution (approved, reversible)
    # ------------------------------------------------------------------ #
    def _accept_duplicate_removal(self, suggestion_id: int) -> dict:
        """Execute an approved removal → reversible trash + index sync."""
        try:
            result = self.container.suggestion_engine.accept_duplicate_removal(suggestion_id)
            if result.get("ok"):
                self.bus.status_message.emit(
                    f"Duplicate moved to trash: {os.path.basename(result['trash_path'])}"
                )
                self.bus.duplicates_updated.emit()
                self.bus.relationships_updated.emit()
                if hasattr(self.docks, "indexed_files_widget"):
                    self.docks.indexed_files_widget.refresh_data()
            else:
                self.bus.status_message.emit(f"Removal failed: {result.get('error', '')}")
            return result
        except Exception as exc:
            self.log.error("Duplicate removal failed: %s", exc)
            return {"ok": False, "error": str(exc)}

    def _dismiss_duplicate_removal(self, suggestion_id: int) -> bool:
        try:
            ok = self.container.suggestion_engine.dismiss_duplicate_removal(suggestion_id)
            if ok:
                self.bus.duplicates_updated.emit()
            return ok
        except Exception as exc:
            self.log.error("Duplicate removal dismiss failed: %s", exc)
            return False

    # ------------------------------------------------------------------ #
    # B5-05 / B5-06 — Similar + Related files
    # ------------------------------------------------------------------ #
    def _on_find_similar_requested(self, file_path: str) -> None:
        """File → AI → Find Similar Files (near duplicates)."""
        from ui.dialogs.similar_files_dialog import SimilarFilesDialog

        self.bus.status_message.emit(f"Finding similar files for {os.path.basename(file_path)}...")

        def _do(progress_callback, cancel_event, fp):
            if self.container.similarity_service.has_index:
                return self.container.similarity_service.similar_files(fp)
            return []

        def _on_complete(results):
            dialog = SimilarFilesDialog(
                file_path,
                similar=results or [],
                related=[],
                on_open=self._on_file_activated,
                on_compare=self._open_file_comparison,
                on_trash=self._trash_file,
                parent=self,
            )
            dialog.show()

        self.container.tasks.submit(
            _do, "similar_files", None, file_path,
            on_finished=_on_complete,
            on_error=lambda err: self.bus.status_message.emit(f"Similar-files failed: {err}"),
        )

    def _on_find_related_requested(self, file_path: str) -> None:
        """File → AI → Find Related Files (combined discovery)."""
        from ui.dialogs.similar_files_dialog import SimilarFilesDialog

        self.bus.status_message.emit(f"Discovering related files for {os.path.basename(file_path)}...")

        def _do(progress_callback, cancel_event, fp):
            similar = []
            related = []
            if self.container.similarity_service.has_index:
                similar = self.container.similarity_service.similar_files(fp)
                related = self.container.related_file_service.related_files(fp)
            return similar, related

        def _on_complete(pair):
            similar, related = pair or ([], [])
            dialog = SimilarFilesDialog(
                file_path,
                similar=similar or [],
                related=related or [],
                on_open=self._on_file_activated,
                on_compare=self._open_file_comparison,
                on_trash=self._trash_file,
                parent=self,
            )
            dialog.show()


        self.container.tasks.submit(
            _do, "related_files", None, file_path,
            on_finished=_on_complete,
            on_error=lambda err: self.bus.status_message.emit(f"Related-files failed: {err}"),
        )

    # ------------------------------------------------------------------ #
    # B5-07 — File relationships
    # ------------------------------------------------------------------ #
    def _on_file_relationships_requested(self) -> None:
        """Tools → File Relationships — browse all relationships."""
        from ui.dialogs.file_relationships_dialog import FileRelationshipsDialog

        rels = self.container.relationship_engine._store.all_relationships(limit=200)
        if not rels:
            self.bus.status_message.emit(
                "No file relationships yet. Use 'Find Similar Files' or 'Find Related Files' to build them."
            )
        dialog = FileRelationshipsDialog(
            source_path=self.current_path,
            relationships=rels,
            on_open=self._on_file_activated,
            parent=self,
        )
        dialog.show()

    def _on_view_relationships_requested(self, file_path: str) -> None:
        """File → AI → View Relationships for a selected file."""
        from ui.dialogs.file_relationships_dialog import FileRelationshipsDialog

        rels = self.container.relationship_engine.relationships_for_file(file_path)
        dialog = FileRelationshipsDialog(
            source_path=file_path,
            relationships=rels,
            on_open=self._on_file_activated,
            parent=self,
        )
        dialog.show()

    # ------------------------------------------------------------------ #
    # B5-01 / B5-02 — Classification + Auto-tagging
    # ------------------------------------------------------------------ #
    def _on_classify_requested(self, file_path: str) -> None:
        """File → AI → Classify File."""
        self.bus.status_message.emit(f"Classifying {os.path.basename(file_path)}...")

        def _do(progress_callback, cancel_event, fp):
            return self.container.classification_engine.classify_file(fp)

        def _on_complete(category):
            if category:
                self.bus.status_message.emit(f"Classified as: {category}")
                self.bus.classification_updated.emit(file_path)
            else:
                self.bus.status_message.emit("Classification failed")

        self.container.tasks.submit(
            _do, "classify", None, file_path,
            on_finished=_on_complete,
            on_error=lambda err: self.bus.status_message.emit(f"Classification failed: {err}"),
        )

    def _on_auto_tag_requested(self, file_path: str) -> None:
        """File → AI → Auto-Tag File."""
        self.bus.status_message.emit(f"Tagging {os.path.basename(file_path)}...")

        def _do(progress_callback, cancel_event, fp):
            tags = self.container.tagging_engine.generate_tags(fp)
            return tags

        def _on_complete(tags):
            if tags:
                self.bus.status_message.emit(f"Tagged: {', '.join(tags)}")
                self.bus.tags_updated.emit(file_path)
            else:
                self.bus.status_message.emit("No tags generated (try 'Analyze File' first)")

        self.container.tasks.submit(
            _do, "auto_tag", None, file_path,
            on_finished=_on_complete,
            on_error=lambda err: self.bus.status_message.emit(f"Auto-tag failed: {err}"),
        )

    def _classify_folder(self, folder_path: str) -> None:
        """Classify every indexed file under a folder (background task)."""
        paths = [p for p in self._indexed_paths() if p.startswith(folder_path)]
        self._batch_classify(paths)

    def _batch_classify(self, paths: list) -> None:
        if not paths:
            self.bus.status_message.emit("No files to classify")
            return
        self.bus.status_message.emit(f"Classifying {len(paths)} file(s)...")

        def _do(progress_callback, cancel_event, plist):
            return self.container.classification_engine.classify_batch(
                plist, progress_callback=progress_callback, cancel_event=cancel_event,
            )

        def _on_complete(result):
            self.bus.status_message.emit(
                f"Classification done: {result.get('classified', 0)} classified, "
                f"{result.get('skipped', 0)} up-to-date, {result.get('errors', 0)} errors"
            )
            if result.get('classified', 0):
                self.bus.classification_updated.emit(paths[0] if paths else "")

        self.container.tasks.submit(
            _do, "classify_batch", None, paths,
            on_finished=_on_complete,
            on_error=lambda err: self.bus.status_message.emit(f"Classification failed: {err}"),
        )

    # ------------------------------------------------------------------ #
    # B5-09 — Saved searches
    # ------------------------------------------------------------------ #
    def _on_saved_searches_requested(self) -> None:
        """Tools → Saved Searches."""
        from ui.dialogs.saved_searches_dialog import SavedSearchesDialog

        dialog = SavedSearchesDialog(
            self.container.saved_search_manager,
            on_run=self._on_run_saved_search,
            on_changed=lambda: self.bus.saved_search_updated.emit(0),
            parent=self,
        )
        dialog.show()

    def _on_run_saved_search(self, saved) -> None:
        """Run a saved search against the current index and show results."""
        self.bus.status_message.emit(f"Running saved search '{saved.name}'...")

        def _do(progress_callback, cancel_event, sid):
            return self.container.saved_search_manager.execute(sid, top_k=10, threshold=0.3)

        def _on_complete(result):
            self.bus.saved_search_updated.emit(saved.id)
            if not result or not result.get("results"):
                self.bus.status_message.emit("Saved search returned no results")
                return
            dialog = self._open_semantic_search_dialog()
            dialog.search_input.setText(result["query"])
            dialog.set_modality_filter(result.get("modality", "all"))
            dialog.set_results(result["results"])

        self.container.tasks.submit(
            _do, "saved_search_run", None, saved.id,
            on_finished=_on_complete,
            on_error=lambda err: self.bus.status_message.emit(f"Saved search failed: {err}"),
        )

    # ------------------------------------------------------------------ #
    # B5-03 — Collections
    # ------------------------------------------------------------------ #
    def _on_collections_requested(self) -> None:
        """Tools → Collections."""
        from ui.dialogs.collections_dialog import CollectionsDialog

        dialog = CollectionsDialog(
            self.container.collection_engine,
            on_open=self._on_file_activated,
            on_changed=lambda: self.bus.collection_updated.emit(0),
            parent=self,
        )
        dialog.show()

    # ------------------------------------------------------------------ #
    # B5-08 — Organization suggestions
    # ------------------------------------------------------------------ #
    def _on_suggest_organization_requested(self, file_path: str) -> None:
        """File → AI → Suggest Organization."""
        from ui.dialogs.suggestion_dialog import SuggestionDialog

        self.bus.status_message.emit(f"Generating organization suggestions for {os.path.basename(file_path)}...")

        def _do(progress_callback, cancel_event, fp):
            return self.container.suggestion_engine.suggest_for_file(fp, reason_depth="short")

        def _on_complete(suggestions):
            if not suggestions:
                self.bus.status_message.emit(
                    "No suggestions — create collections first and index the folder for AI."
                )
                return
            def _accept(sid):
                ok = self.container.suggestion_engine.accept(sid)
                if ok:
                    self.bus.organization_suggestion_updated.emit(sid)
                return ok
            def _dismiss(sid):
                ok = self.container.suggestion_engine.dismiss(sid)
                if ok:
                    self.bus.organization_suggestion_updated.emit(sid)
                return ok
            dialog = SuggestionDialog(
                engine=self.container.suggestion_engine,
                file_path=file_path,
                suggestions=suggestions,
                on_accept=_accept,
                on_dismiss=_dismiss,
                parent=self,
            )
            # Batch 6 §10 — approved folder move from a folder-type suggestion.
            dialog.move_requested.connect(self._on_suggestion_move)
            dialog.show()

        self.container.tasks.submit(
            _do, "suggest_organization", None, file_path,
            on_finished=_on_complete,
            on_error=lambda err: self.bus.status_message.emit(f"Suggestions failed: {err}"),
        )

    # ------------------------------------------------------------------ #
    # B5-10 — Knowledge Dashboard
    # ------------------------------------------------------------------ #
    def _on_dashboard_requested(self) -> None:
        """Tools → Knowledge Dashboard.

        The dashboard subscribes to every Batch-5 organization signal so it
        refreshes live while classification, tags, duplicates, relationships,
        collections, saved searches or suggestions change (Batch 5 §19).
        """
        from ui.dialogs.dashboard_dialog import DashboardDialog

        dialog = DashboardDialog(
            self.container.dashboard_service,
            folder_path=self.current_path if hasattr(self, "current_path") else None,
            on_open=self._on_file_activated,
            parent=self,
        )
        # Auto-refresh on organization-data changes (payloads are ignored;
        # the dashboard re-aggregates from scratch each refresh).
        for sig in (
            self.bus.classification_updated,
            self.bus.tags_updated,
            self.bus.duplicates_updated,
            self.bus.relationships_updated,
            self.bus.collection_updated,
            self.bus.saved_search_updated,
            self.bus.organization_suggestion_updated,
            self.bus.dashboard_refresh_requested,
            self.bus.caption_updated,
            self.bus.folder_classification_updated,
            self.bus.metadata_updated,
            self.bus.rename_completed,
        ):
            sig.connect(dialog.refresh)
        dialog.show()

    # ================================================================ #
    # Batch 6 — completing the five partial features
    # ================================================================ #
    # ------------------------------------------------------------------ #
    # B6-01 — Image Caption Generation
    # ------------------------------------------------------------------ #
    def _on_caption_requested(self, file_path: str) -> None:
        """File → AI → Caption Image.

        Shows any persisted caption immediately, then (re)generates in the
        background. Errors surface in the dialog; existing metadata is never
        touched on failure.
        """
        from ui.dialogs.caption_dialog import CaptionDialog

        if not file_path or not os.path.isfile(file_path):
            self.bus.status_message.emit("Caption: invalid image file")
            return
        service = self.container.caption_service
        if not service.is_supported(file_path):
            self.bus.status_message.emit("Caption: unsupported image type")
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.information(
                self, "Caption Image",
                "This file type is not a supported image. Supported: "
                "png, jpg, jpeg, webp, bmp, tiff, gif.",
            )
            return

        dialog = CaptionDialog(file_path, parent=self)
        dialog.regenerate_requested.connect(
            lambda: self._run_caption(file_path, dialog, regenerate=True)
        )
        dialog.set_loading()
        dialog.show()

        # Show a persisted caption immediately (identity preserved by hash).
        cached = None
        try:
            cached = service.get_caption(file_path)
        except Exception as exc:
            self.log.debug("Caption lookup failed: %s", exc)
        if cached:
            dialog.set_caption(cached, stale=True)
        else:
            self._run_caption(file_path, dialog, regenerate=False)

    def _run_caption(self, file_path: str, dialog, regenerate: bool) -> None:
        """Generate (or regenerate) a caption in a background worker."""
        self.bus.status_message.emit(
            f"Generating caption for {os.path.basename(file_path)}..."
        )
        dialog.set_loading()

        def _do(progress_callback, cancel_event, fp):
            return self.container.caption_service.generate_caption(fp)

        def _on_complete(caption):
            if not caption:
                dialog.set_error("The vision model returned no caption.")
                self.bus.status_message.emit("Caption generation returned nothing")
                return
            dialog.set_caption(caption, model=self.container.vision_engine._model)
            self.bus.status_message.emit("Caption ready")
            self.bus.caption_updated.emit(file_path)

        def _on_error(error):
            self.log.error("Caption error: %s", error)
            dialog.set_error(str(error))
            self.bus.status_message.emit("Caption generation failed")

        self.container.tasks.submit(
            _do, "caption", None, file_path,
            on_finished=_on_complete,
            on_error=_on_error,
        )

    # ------------------------------------------------------------------ #
    # B6-02 — AI Folder Classification & Statistics
    # ------------------------------------------------------------------ #
    def _on_folder_statistics_menu_requested(self) -> None:
        """Open Folder Statistics for selected folder, current path, or prompt."""
        folder = None
        if hasattr(self, "explorer"):
            selected = self.explorer._selected_paths()
            if selected:
                sel = selected[0]
                if os.path.isdir(sel):
                    folder = sel
                elif os.path.isfile(sel):
                    folder = os.path.dirname(sel)
        if not folder and hasattr(self, "current_path") and self.current_path and os.path.isdir(self.current_path):
            folder = self.current_path
        if not folder or not os.path.isdir(folder):
            from PySide6.QtWidgets import QFileDialog
            folder = QFileDialog.getExistingDirectory(self, "Select Folder for Statistics", os.path.expanduser("~"))
        if folder and os.path.isdir(folder):
            self._on_folder_intelligence_requested(folder)

    def _on_folder_intelligence_requested(self, folder_path: str) -> None:
        """Right-click folder → Folder Intelligence… (B6-02 + B7 completion)."""
        from ui.dialogs.folder_intelligence_dialog import FolderIntelligenceDialog

        if not folder_path or not os.path.isdir(folder_path):
            self.bus.status_message.emit("Folder statistics: invalid folder")
            return
        dialog = FolderIntelligenceDialog(
            folder_path,
            service=self.container.folder_classification_service,
            parent=self,
        )
        # Batch 7 (#31 completion + B7-8): attach general statistics and the
        # AI folder summary so the dialog shows the full folder picture.
        try:
            dialog.set_intelligence_service(self.container.folder_intelligence_service)
            dialog.set_summary_service(self.container.folder_summary_service)
        except Exception as exc:
            self.log.debug("Folder intelligence services unavailable: %s", exc)
        dialog.refresh()
        dialog.show()
        self._folder_intelligence_dialog = dialog
        self.bus.folder_classification_updated.emit(folder_path)

    # ------------------------------------------------------------------ #
    # B6-05 — Automatic Folder Organization (approved moves)
    # ------------------------------------------------------------------ #
    def _on_suggestion_move(self, suggestion) -> None:
        """Preview + execute an approved move for a folder-type suggestion.

        target resolution: the suggestion stores the destination folder name;
        the only valid target is an existing sibling folder of the file.
        """
        from ui.dialogs.organization_preview_dialog import OrganizationPreviewDialog
        from PySide6.QtWidgets import QMessageBox

        file_path = getattr(suggestion, "file_path", "")
        target_name = getattr(suggestion, "suggested_target", "")
        if not file_path or not os.path.isfile(file_path):
            QMessageBox.information(self, "Organization", "The file no longer exists.")
            return
        target_dir = os.path.join(os.path.dirname(file_path), target_name)
        if not os.path.isdir(target_dir):
            QMessageBox.information(
                self, "Organization",
                f"The target folder '{target_name}' no longer exists. "
                "The file was not moved.",
            )
            return

        def _execute(src: str, dst_dir: str) -> str:
            try:
                from services.file_mover import move_file, MoveError

                result = move_file(
                    src=src,
                    dst_dir=dst_dir,
                    session_factory=self.container.db.session,
                    retrieval=self.container.retrieval_engine,
                    vector_engine=self.container.vector_engine,
                )
                if not result.ok:
                    return result.error or "Move failed."
                # Mark the suggestion approved+done after a successful move.
                try:
                    self.container.suggestion_engine.accept(suggestion.id)
                except Exception as exc:
                    self.log.debug("Suggestion status update failed: %s", exc)
                self.bus.organization_suggestion_updated.emit(suggestion.id)
                self.bus.relationships_updated.emit()
                self.bus.folder_classification_updated.emit(os.path.dirname(src))
                if hasattr(self.docks, "indexed_files_widget"):
                    self.docks.indexed_files_widget.refresh_data()
                return ""
            except MoveError as exc:
                self.log.error("Move failed for %s: %s", src, exc)
                return str(exc)
            except Exception as exc:
                self.log.error("Move failed for %s: %s", src, exc)
                return str(exc)

        dialog = OrganizationPreviewDialog(
            moves=[(file_path, target_dir)],
            on_execute=_execute,
            parent=self,
        )
        dialog.exec()

    # ================================================================ #
    # Batch 7 — image intelligence, metadata tools, timeline, comparison,
    #           folder intelligence completion, safe renaming
    # ================================================================ #
    # ------------------------------------------------------------------ #
    # B7-3 — Metadata Export
    # ------------------------------------------------------------------ #
    def _on_metadata_export_requested(self) -> None:
        """Tools → Export Metadata."""
        from ui.dialogs.metadata_export_dialog import MetadataExportDialog

        dialog = MetadataExportDialog(
            self.container.metadata_export_service,
            current_folder=self.current_path,
            selected_files=[],
            parent=self,
        )
        dialog.show()

    # ------------------------------------------------------------------ #
    # B7-7 — File Timeline
    # ------------------------------------------------------------------ #
    def _on_timeline_requested(self) -> None:
        """Tools → File Timeline."""
        from ui.dialogs.timeline_dialog import TimelineDialog

        dialog = TimelineDialog(
            self.container.timeline_service,
            folder=self.current_path if hasattr(self, "current_path") else None,
            open_file=self._on_file_activated,
            parent=self,
        )
        dialog.show()

    # ------------------------------------------------------------------ #
    # B7-5 — Document Comparison
    # ------------------------------------------------------------------ #
    def _on_compare_documents_requested(self) -> None:
        """Tools → Compare Documents."""
        from ui.dialogs.document_comparison_dialog import DocumentComparisonDialog

        dialog = DocumentComparisonDialog(
            self.container.document_comparison_service,
            parent=self,
        )
        dialog.show()

    # ------------------------------------------------------------------ #
    # B7-10 — AI Image Filter
    # ------------------------------------------------------------------ #
    def _on_image_filter_requested(self) -> None:
        """Tools → AI Image Filter."""
        from ui.dialogs.image_filter_dialog import ImageFilterDialog

        dialog = ImageFilterDialog(
            self.container.image_filter_service,
            current_folder=self.current_path,
            open_file=self._on_file_activated,
            parent=self,
        )
        dialog.show()

    def _on_organize_files_requested(self) -> None:
        """Tools → Organize Files into Folder."""
        from ui.dialogs.organize_dialog import OrganizeDialog

        dialog = OrganizeDialog(
            organizer_service=self.container.file_organizer_service,
            current_dir=self.current_path,
            open_file_callback=self._on_file_activated,
            retrieval_engine=self.container.retrieval_engine,
            parent=self,
        )
        dialog.organization_completed.connect(lambda res: self._on_refresh())
        dialog.show()


    def _on_check_inactive_requested(self, auto_check: bool = False) -> None:
        """Tools → Check Inactive Files... (or auto-check on startup)."""
        from ui.dialogs.inactive_files_dialog import InactiveFilesDialog

        enabled = self.container.config.get("general.inactivity_reminder_enabled", False)
        if auto_check and not enabled:
            return

        # For auto-check, a watched folder MUST be configured.
        # If none is set, skip silently — user has not opted into folder-specific reminders.
        watched_folder = self.container.config.get("general.inactivity_reminder_folder", "").strip()
        if auto_check and not watched_folder:
            return

        threshold_days = self.container.config.get("general.inactivity_threshold_days", 14)
        service = self.container.inactivity_reminder_service

        # Auto-check: scope to the watched folder only.
        # Manual menu trigger: scan all indexed files (no folder restriction).
        folder_scope = watched_folder if auto_check else None

        def _do_check(progress_callback, cancel_event):
            return service.find_inactive_files(
                threshold_days=threshold_days,
                max_results=100,
                watched_folder=folder_scope,
            )

        def _on_complete(inactive_files):
            if not inactive_files:
                if not auto_check:
                    self.bus.status_message.emit(f"No inactive files (>{threshold_days} days) found")
                return

            scope_label = f" in '{os.path.basename(watched_folder)}'" if folder_scope else ""
            self.bus.status_message.emit(
                f"🔔 Inactive file alert: {len(inactive_files)} file(s){scope_label} unopened for >{threshold_days} days"
            )
            dialog = InactiveFilesDialog(
                inactive_files=inactive_files,
                threshold_days=threshold_days,
                on_open=self._on_file_activated,
                parent=self,
            )
            dialog.organize_requested.connect(self._on_organize_inactive_requested)
            dialog.show()

        self.container.tasks.submit(
            _do_check, "inactivity_check", None,
            on_finished=_on_complete,
            on_error=lambda err: self.log.debug("Inactivity check failed: %s", err),
        )

    def _on_organize_inactive_requested(self, file_paths: list[str]) -> None:
        """Open OrganizeDialog populated for inactive files."""
        from ui.dialogs.organize_dialog import OrganizeDialog

        dialog = OrganizeDialog(
            organizer_service=self.container.file_organizer_service,
            current_dir=self.current_path,
            open_file_callback=self._on_file_activated,
            retrieval_engine=self.container.retrieval_engine,
            parent=self,
        )
        dialog.folder_name_edit.setText("Inactive Files Archive")
        dialog.organization_completed.connect(lambda res: self._on_refresh())
        dialog.show()


    def _on_cleanup_db_requested(self) -> None:
        """Tools → Clean Database — purge stale records for non-existent files."""
        from PySide6.QtWidgets import QMessageBox
        from services.file_cleanup import cleanup_all_stale_files

        reply = QMessageBox.question(
            self,
            "Clean Database",
            "Scan database and purge stale records for files that no longer exist on disk?\n\n"
            "This will remove ghost records, synchronize vector search, and update statistics. "
            "No existing files will be touched.",
            QMessageBox.Yes | QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return

        self.bus.status_message.emit("Cleaning database (scanning for stale records)...")

        def _do_cleanup(progress_callback, cancel_event):
            return cleanup_all_stale_files(
                session_factory=self.container.db.session,
                retrieval=self.container.retrieval_engine,
                db_store=self.container.db_store,
                graph_engine=self.container.graph_engine,
                vector_engine=self.container.vector_engine,
                progress_callback=progress_callback,
            )

        def _on_complete(result):
            stale = result.get("stale_files", 0)
            cleaned = result.get("cleaned_files", 0)
            chunks = result.get("evidence_chunks_removed", 0)
            rels = result.get("relationships_removed", 0)

            msg = f"Database cleanup completed: Purged {cleaned} stale file record(s) ({chunks} vector chunks)."
            self.bus.status_message.emit(msg)
            self.bus.duplicates_updated.emit()
            self.bus.relationships_updated.emit()
            self.bus.dashboard_refresh_requested.emit()

            QMessageBox.information(
                self,
                "Database Cleanup Complete",
                f"<b>🧹 Database Maintenance Summary:</b><br><br>"
                f"• Stale File Records Purged: <b>{cleaned}</b> (of {stale} non-existent paths found)<br>"
                f"• Evidence / Vector Chunks Cleared: <b>{chunks}</b><br>"
                f"• Derived File Relationships Cleared: <b>{rels}</b><br><br>"
                f"Your search index and FAISS database are now 100% synchronized with disk.",
            )

        self.container.tasks.submit(
            _do_cleanup,
            "db_cleanup",
            None,
            on_finished=_on_complete,
            on_error=lambda err: self.bus.status_message.emit(f"Database cleanup failed: {err}"),
        )


    def _open_file_comparison(self, path_a: str, path_b: str) -> None:
        """Open Document Comparison Dialog pre-populated with two files."""
        from ui.dialogs.document_comparison_dialog import DocumentComparisonDialog

        dialog = DocumentComparisonDialog(
            self.container.document_comparison_service,
            parent=self,
        )
        # Pre-select files if dialog supports setting file paths
        if hasattr(dialog, "set_files"):
            dialog.set_files(path_a, path_b)
        dialog.show()

    def _trash_file(self, file_path: str) -> dict:
        """Move a redundant copy to safe app trash."""
        from services.safe_file_ops import move_to_trash

        try:
            res = move_to_trash(
                path=file_path,
                session_factory=self.container.db.session,
                retrieval=self.container.retrieval_engine,
                db_store=self.container.db_store,
                vector_engine=self.container.vector_engine,
            )
            if res.ok:
                self.bus.status_message.emit(f"Moved to trash: {os.path.basename(file_path)}")
                self._on_refresh()
                return {"ok": True, "trash_path": res.target}
            else:
                self.bus.status_message.emit(f"Move to trash failed: {res.error}")
                return {"ok": False, "error": res.error}
        except Exception as exc:
            self.log.error("Trash move failed for %s: %s", file_path, exc)
            return {"ok": False, "error": str(exc)}


    # ------------------------------------------------------------------ #
    # B7-4 — Image Quality Analysis
    # ------------------------------------------------------------------ #
    def _on_image_quality_requested(self, file_path: str) -> None:
        """File → AI → Analyze Image Quality."""
        from ui.dialogs.image_quality_dialog import ImageQualityDialog

        if not file_path or not os.path.isfile(file_path):
            self.bus.status_message.emit("Quality: invalid image file")
            return
        service = self.container.image_quality_service
        if not service.is_supported(file_path):
            self.bus.status_message.emit("Quality: unsupported image type")
            return

        dialog = ImageQualityDialog(file_path, parent=self)
        dialog.show()

        # Show persisted result instantly, else analyze in background.
        cached = None
        try:
            cached = service.get(file_path)
        except Exception:
            cached = None
        if cached is not None:
            dialog.set_result(cached)
        else:
            def _do(progress_callback, cancel_event, fp):
                result = service.analyze(fp)
                if result is not None:
                    service.persist(fp, result)
                return result

            def _on_complete(result):
                dialog.set_result(result)
                if result is not None:
                    self.bus.image_quality_updated.emit(file_path)

            self.container.tasks.submit(
                _do, "image_quality", None, file_path,
                on_finished=_on_complete,
                on_error=lambda err: dialog.set_error(str(err)),
            )

    # ------------------------------------------------------------------ #
    # B7-2 — Object Detection
    # ------------------------------------------------------------------ #
    def _on_object_detection_requested(self, file_path: str) -> None:
        """File → AI → Detect Objects."""
        from ui.dialogs.object_detection_dialog import ObjectDetectionDialog

        if not file_path or not os.path.isfile(file_path):
            self.bus.status_message.emit("Objects: invalid image file")
            return
        service = self.container.object_detection_service
        if not service.is_supported(file_path):
            self.bus.status_message.emit("Objects: unsupported image type")
            return

        dialog = ObjectDetectionDialog(file_path, parent=self)
        dialog.regenerate_requested.connect(
            lambda: self._run_object_detection(file_path, dialog)
        )
        dialog.show()

        cached = []
        try:
            cached = service.get(file_path)
        except Exception:
            cached = []
        if cached:
            dialog.set_objects(cached)
        else:
            self._run_object_detection(file_path, dialog)

    def _run_object_detection(self, file_path: str, dialog) -> None:
        """Run object detection in a background worker."""
        service = self.container.object_detection_service
        self.bus.status_message.emit(f"Detecting objects in {os.path.basename(file_path)}...")

        def _do(progress_callback, cancel_event, fp):
            objects = service.detect(fp)
            if objects:
                service.persist(fp, objects)
            return objects

        def _on_complete(objects):
            dialog.set_objects(objects or [])
            if objects:
                self.bus.objects_updated.emit(file_path)

        def _on_error(error):
            self.log.error("Object detection error: %s", error)
            dialog.set_error(str(error))

        self.container.tasks.submit(
            _do, "object_detection", None, file_path,
            on_finished=_on_complete,
            on_error=_on_error,
        )

    # ------------------------------------------------------------------ #
    # B7-1 — Reverse Image Search
    # ------------------------------------------------------------------ #
    def _on_reverse_image_requested(self, file_path: str) -> None:
        """File → AI → Search by Image."""
        from ui.dialogs.reverse_image_dialog import ReverseImageDialog

        if not file_path or not os.path.isfile(file_path):
            self.bus.status_message.emit("Reverse search: invalid image file")
            return
        service = self.container.reverse_image_service
        dialog = ReverseImageDialog(
            service,
            query_image=file_path,
            open_file=self._on_file_activated,
            parent=self,
        )
        dialog.search_requested.connect(
            lambda q: self._run_reverse_image_search(q, dialog)
        )
        dialog.show()

    def _run_reverse_image_search(self, query_path: str, dialog) -> None:
        """Run image→image search in a background worker."""
        service = self.container.reverse_image_service

        def _do(progress_callback, cancel_event, qp):
            if not service.is_available():
                return None
            return service.search_by_image(qp)

        def _on_complete(results):
            if results is None:
                dialog.set_results([], service_available=False)
            else:
                dialog.set_results(results)

        def _on_error(error):
            dialog.set_error(str(error))

        self.container.tasks.submit(
            _do, "reverse_image", None, query_path,
            on_finished=_on_complete,
            on_error=_on_error,
        )

    # ------------------------------------------------------------------ #
    # B7-6 — Metadata Editor
    # ------------------------------------------------------------------ #
    def _on_edit_metadata_requested(self, file_path: str) -> None:
        """File → AI → Edit Metadata."""
        from ui.dialogs.metadata_editor_dialog import MetadataEditorDialog

        if not file_path or not os.path.isfile(file_path):
            self.bus.status_message.emit("Metadata: invalid file")
            return
        dialog = MetadataEditorDialog(
            file_path,
            self.container.metadata_editor_service,
            parent=self,
        )
        dialog.exec()
        self.bus.metadata_updated.emit(file_path)

    # ------------------------------------------------------------------ #
    # B7-9 — Automatic File Renaming (approved)
    # ------------------------------------------------------------------ #
    def _on_suggest_rename_requested(self, file_paths: List[str] | str) -> None:
        """File(s) → AI → Rename from Content (AI)."""
        from ui.dialogs.rename_preview_dialog import RenamePreviewDialog

        # Normalize to list of paths
        if isinstance(file_paths, str):
            paths = [file_paths]
        else:
            paths = list(file_paths)

        paths = [p for p in paths if p and os.path.isfile(p)]
        if not paths:
            self.bus.status_message.emit("Rename: no valid files selected")
            return

        if len(paths) == 1:
            self.bus.status_message.emit(f"Analyzing content to suggest AI rename for {os.path.basename(paths[0])}...")
        else:
            self.bus.status_message.emit(f"Analyzing content to suggest AI renames for {len(paths)} files...")

        def _do(progress_callback, cancel_event, fps):
            from concurrent.futures import ThreadPoolExecutor, as_completed
            service = self.container.rename_suggestion_service
            suggestions = [None] * len(fps)
            max_workers = min(8, len(fps))
            completed = 0
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                future_to_idx = {
                    executor.submit(service.suggest_from_content, fp): i
                    for i, fp in enumerate(fps)
                }
                for future in as_completed(future_to_idx):
                    if cancel_event and cancel_event.is_set():
                        for f in future_to_idx:
                            f.cancel()
                        break
                    idx = future_to_idx[future]
                    try:
                        sug = future.result()
                        if sug:
                            suggestions[idx] = sug
                    except Exception as exc:
                        self.log.debug("Rename suggestion failed for %s: %s", fps[idx], exc)
                    completed += 1
                    if progress_callback:
                        progress_callback(completed, len(fps))
            return [s for s in suggestions if s is not None]

        def _approve(src: str, new_name: str) -> dict:
            try:
                from services.file_mover import rename_file, MoveError

                result = rename_file(
                    src=src,
                    new_name=new_name,
                    session_factory=self.container.db.session,
                    retrieval=self.container.retrieval_engine,
                    vector_engine=self.container.vector_engine,
                )
                if result.ok:
                    self.bus.rename_completed.emit(result.destination)
                    self.bus.relationships_updated.emit()
                    if hasattr(self.docks, "indexed_files_widget"):
                        self.docks.indexed_files_widget.refresh_data()
                    self.bus.files_changed.emit(os.path.dirname(result.destination))
                return result.__dict__ if hasattr(result, "__dict__") else {"ok": result.ok}
            except MoveError as exc:
                return {"ok": False, "error": str(exc)}
            except Exception as exc:
                return {"ok": False, "error": str(exc)}

        def _on_complete(suggestions):
            if not suggestions:
                self.bus.status_message.emit("Rename suggestions failed.")
                return
            self.bus.status_message.emit(f"Generated {len(suggestions)} AI rename suggestion(s).")
            dialog = RenamePreviewDialog(suggestions, approve=_approve, parent=self)
            dialog.show()

        self.container.tasks.submit(
            _do, "ai_rename_suggestions", None, paths,
            on_finished=_on_complete,
            on_error=lambda err: self.bus.status_message.emit(f"AI rename failed: {err}"),
        )

    def _on_suggest_rename_multi_requested(self, folder_path: str) -> None:
        """Folder -> AI -> Rename Selected Files (Multiple Selection)."""
        from PySide6.QtWidgets import QDialog
        from ui.dialogs.multi_rename_selection_dialog import MultiRenameSelectionDialog

        if not folder_path or not os.path.isdir(folder_path):
            self.bus.status_message.emit("Rename: invalid folder path")
            return

        dialog = MultiRenameSelectionDialog(folder_path, container=self.container, parent=self)
        dialog.exec()


