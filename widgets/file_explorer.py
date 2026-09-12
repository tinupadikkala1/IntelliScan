"""File explorer widget.

Provides both a detailed list view and an icon/grid view over a single
``QFileSystemModel``. Supports sorting, extended multi-selection, a context
menu (open / rename / copy / move / delete / properties) and drag & drop
(internal move + external copy). It is pure presentation: opening a file or
changing the directory is reported through signals so the main window owns
the policy.
"""

from __future__ import annotations

import os
import shutil

from PySide6.QtCore import QDir, QFileInfo, QModelIndex, QPoint, QRect, QSize, QUrl, Qt, Signal
from PySide6.QtGui import QFontMetrics, QIcon
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFileDialog,
    QFileSystemModel,
    QInputDialog,
    QListView,
    QMenu,
    QMessageBox,
    QStackedWidget,
    QStyledItemDelegate,
    QStyle,
    QTableView,
    QVBoxLayout,
    QWidget,
)


class _DragDropList(QListView):
    def __init__(self, explorer, parent=None) -> None:
        super().__init__(parent)
        self._explorer = explorer

    def dropEvent(self, event) -> None:
        self._explorer.handle_drop(event, self)


class _DragDropTable(QTableView):
    def __init__(self, explorer, parent=None) -> None:
        super().__init__(parent)
        self._explorer = explorer

    def dropEvent(self, event) -> None:
        self._explorer.handle_drop(event, self)


class GridDelegate(QStyledItemDelegate):
    """Renders grid cells with uniform size, centered icon, and 2-line elided text."""

    CELL_W = 100
    CELL_H = 120
    ICON_SIZE = 64

    def paint(self, painter, option, index):
        painter.save()

        # Selection / hover background
        if option.state & QStyle.State_Selected:
            painter.fillRect(option.rect, option.palette.highlight())
        elif option.state & QStyle.State_MouseOver:
            c = option.palette.highlight().color()
            c.setAlpha(60)
            painter.fillRect(option.rect, c)

        # Icon – centred horizontally at top
        icon = index.data(Qt.DecorationRole)
        if icon:
            icon_rect = QRect(0, 0, self.ICON_SIZE, self.ICON_SIZE)
            cx = option.rect.center().x()
            cy = option.rect.top() + 8 + self.ICON_SIZE // 2
            icon_rect.moveCenter(QPoint(cx, cy))
            icon.paint(painter, icon_rect, Qt.AlignCenter)

        # Text – word-wrapped, elided to 2 lines
        text = index.data(Qt.DisplayRole)
        if text:
            painter.setPen(option.palette.text().color())
            fm = option.fontMetrics
            text_rect = QRect(
                option.rect.left() + 2,
                option.rect.top() + 8 + self.ICON_SIZE + 2,
                option.rect.width() - 4,
                fm.height() * 2,
            )
            line_width = text_rect.width()
            if fm.horizontalAdvance(text) > line_width * 2:
                text = fm.elidedText(text, Qt.ElideRight, line_width * 2 - 4)
            painter.drawText(text_rect, Qt.AlignHCenter | Qt.TextWordWrap, text)

        painter.restore()

    def sizeHint(self, option, index):
        return QSize(self.CELL_W, self.CELL_H)


class FileExplorer(QWidget):
    file_activated = Signal(str)      # double-clicked file or folder
    selection_changed = Signal(list)  # selected absolute paths
    ai_analyze_requested = Signal(str)  # AI analysis requested for file path
    semantic_search_requested = Signal()   # Open semantic search dialog
    ask_ai_requested = Signal(str)         # Ask AI about a specific file path
    folder_chat_requested = Signal(str)    # Batch 4: Chat with this Folder
    # Batch 5 — organization actions
    classify_requested = Signal(str)          # Classify a single file
    auto_tag_requested = Signal(str)          # Auto-tag a single file
    find_duplicates_requested = Signal(str)   # Find exact duplicates for a file
    find_similar_requested = Signal(str)      # Find near-duplicate files
    find_related_requested = Signal(str)      # Find related files
    view_relationships_requested = Signal(str)  # View FILE→FILE relationships
    suggest_organization_requested = Signal(str)  # AI organization suggestion
    # Batch 6 — captioning + folder intelligence
    caption_requested = Signal(str)                 # Caption an image (B6-01)
    folder_intelligence_requested = Signal(str)     # Folder classification (B6-02)
    # Batch 7 — image intelligence, metadata tools, safe renaming
    image_quality_requested = Signal(str)           # Analyze image quality (B7-4)
    object_detection_requested = Signal(str)        # Detect objects (B7-2)
    reverse_image_requested = Signal(str)           # Search by image (B7-1)
    edit_metadata_requested = Signal(str)           # Edit metadata (B7-6)
    rename_suggest_requested = Signal(list)          # Suggest rename (B7-9)
    rename_suggest_multi_requested = Signal(str)    # Suggest rename multi-selection (Custom)

    def __init__(self, parent=None, plugin_registry=None, model=None) -> None:
        super().__init__(parent)
        self.current_path = ""
        self.plugin_registry = plugin_registry

        self.model = model or QFileSystemModel()
        if model is None:
            self.model.setFilter(QDir.AllEntries | QDir.NoDotAndDotDot)
            self.model.setReadOnly(False)
            self.model.setNameFilterDisables(False)

        # List view --------------------------------------------------- #
        self.list_view = _DragDropTable(self)
        self.list_view.setModel(self.model)
        self.list_view.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.list_view.setSortingEnabled(True)
        self.list_view.setDragEnabled(True)
        self.list_view.setAcceptDrops(True)
        self.list_view.setDropIndicatorShown(True)
        self.list_view.setDragDropMode(QAbstractItemView.DragDrop)
        self.list_view.doubleClicked.connect(self._on_activated)
        self.list_view.clicked.connect(self._on_selection)
        self.list_view.setContextMenuPolicy(Qt.CustomContextMenu)
        self.list_view.customContextMenuRequested.connect(self._on_context_menu)
        self.list_view.selectionModel().selectionChanged.connect(self._on_selection)

        # Grid view --------------------------------------------------- #
        self.grid_view = _DragDropList(self)
        self.grid_view.setModel(self.model)
        self.grid_view.setViewMode(QListView.IconMode)
        self.grid_view.setResizeMode(QListView.Adjust)
        self.grid_view.setIconSize(QSize(64, 64))
        self.grid_view.setGridSize(QSize(100, 120))
        self.grid_view.setUniformItemSizes(True)
        self.grid_view.setWordWrap(True)
        self.grid_view.setSpacing(0)
        self.grid_view.setItemDelegate(GridDelegate(self))
        self.grid_view.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.grid_view.setDragEnabled(True)
        self.grid_view.setAcceptDrops(True)
        self.grid_view.setDropIndicatorShown(True)
        self.grid_view.setDragDropMode(QAbstractItemView.DragDrop)
        self.grid_view.doubleClicked.connect(self._on_activated)
        self.grid_view.clicked.connect(self._on_selection)
        self.grid_view.setContextMenuPolicy(Qt.CustomContextMenu)
        self.grid_view.customContextMenuRequested.connect(self._on_context_menu)
        self.grid_view.selectionModel().selectionChanged.connect(self._on_selection)

        self.stack = QStackedWidget()
        self.stack.addWidget(self.list_view)
        self.stack.addWidget(self.grid_view)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.stack)

    # ------------------------------------------------------------------ #
    def set_path(self, path: str) -> None:
        if not path or not os.path.isdir(path):
            return
        self.current_path = path
        self.model.setRootPath(path)
        index = self.model.index(path)
        self.list_view.setRootIndex(index)
        self.grid_view.setRootIndex(index)
        # Clear selection when navigating to a new folder
        self.list_view.clearSelection()
        self.grid_view.clearSelection()

    def set_view(self, view: str) -> None:
        self.stack.setCurrentIndex(0 if view == "list" else 1)

    def set_show_hidden(self, show: bool) -> None:
        base = QDir.AllEntries | QDir.NoDotAndDotDot
        if show:
            base |= QDir.Hidden
        self.model.setFilter(base)

    def set_name_filter(self, text: str) -> None:
        if text:
            import glob
            from fnmatch import fnmatch
            escaped = glob.escape(text).replace("*", "[*]").replace("?", "[?]").replace("[", "[[]")
            pattern = f"*{escaped}*"
            self.model.setNameFilters([pattern])
        else:
            self.model.setNameFilters([])

    # ------------------------------------------------------------------ #
    def _on_activated(self, index: QModelIndex) -> None:
        path = self.model.filePath(index)
        if path:
            self.file_activated.emit(path)

    def _selected_paths(self) -> list[str]:
        view = self.stack.currentWidget()
        paths = []
        for index in view.selectionModel().selectedIndexes():
            if index.column() == 0:  # avoid duplicates from multi-column
                path = self.model.filePath(index)
                if path:
                    paths.append(path)
        return paths

    def _on_selection(self, *_args) -> None:
        self.selection_changed.emit(self._selected_paths())

    # ------------------------------------------------------------------ #
    def _on_context_menu(self, pos) -> None:
        view = self.stack.currentWidget()
        index = view.indexAt(pos)
        targets = [self.model.filePath(index)] if index.isValid() else self._selected_paths()
        menu = QMenu(self)
        act_open = menu.addAction("Open")
        act_rename = menu.addAction("Rename")
        act_copy = menu.addAction("Copy to...")
        act_move = menu.addAction("Move to...")
        act_delete = menu.addAction("Delete")
        menu.addSeparator()
        act_props = menu.addAction("Properties")

        # AI submenu (Batch 2)
        menu.addSeparator()
        ai_menu = menu.addMenu("AI")
        act_ai_analyze = ai_menu.addAction("Analyze File")

        # Enable/disable AI actions based on file selection
        if not targets or len(targets) != 1 or not os.path.isfile(targets[0] if targets else ""):
            act_ai_analyze.setEnabled(False)
        else:
            act_ai_analyze.setEnabled(True)

        # Batch 3 – Semantic Search & Ask AI
        ai_menu.addSeparator()
        act_semantic_search = ai_menu.addAction("Semantic Search")
        act_ask_ai = ai_menu.addAction("Ask AI about this File")
        # Batch 4 – Folder Chat
        # act_folder_chat = ai_menu.addAction("Chat with this Folder")  # commented out — not in use
        # Batch 6 – Caption Image (single image file only)
        act_caption = ai_menu.addAction("Caption Image")
        act_caption.setVisible(False)  # Hidden temporarily (set to True to revert)
        # Batch 7 – image intelligence (single image file only)
        act_image_quality = ai_menu.addAction("Analyze Image Quality")
        act_image_quality.setVisible(False)  # Hidden temporarily (set to True to revert)
        act_detect_objects = ai_menu.addAction("Detect Objects")
        act_detect_objects.setVisible(False)  # Hidden temporarily (set to True to revert)
        act_reverse_image = ai_menu.addAction("Search by Image…")
        # Batch 7 – metadata tools + safe renaming (single file)
        act_edit_metadata = ai_menu.addAction("Edit Metadata…")
        act_suggest_rename = ai_menu.addAction("✏️ Rename from Content (AI)…")
        act_suggest_rename_multi = ai_menu.addAction("✏️ Rename Selected Files (Multiple Selection)…")

        # Batch 5 – Intelligent Organization (single file only) — all commented out — not in use
        # ai_menu.addSeparator()
        # act_classify = ai_menu.addAction("Classify File")  # commented out — not in use
        # act_auto_tag = ai_menu.addAction("Auto-Tag File")  # commented out — not in use
        # act_find_dups = ai_menu.addAction("Find Duplicates")  # commented out — not in use
        # act_find_similar = ai_menu.addAction("Find Similar Files")  # commented out — not in use
        # act_find_related = ai_menu.addAction("Find Related Files")  # commented out — not in use
        # act_view_rels = ai_menu.addAction("View Relationships")  # commented out — not in use
        # act_suggest_org = ai_menu.addAction("Suggest Organization")  # commented out — not in use

        # Semantic search is always enabled; Ask AI only for single file;
        # Folder chat only for a single folder.
        act_semantic_search.setEnabled(True)
        has_single_file = bool(
            targets
            and len(targets) == 1
            and os.path.isfile(targets[0])
        )
        act_ask_ai.setEnabled(has_single_file)
        # has_single_folder = bool(
        #     (targets and len(targets) == 1 and os.path.isdir(targets[0]))
        #     or (not targets and self.current_path and os.path.isdir(self.current_path))
        # )
        # act_folder_chat.setEnabled(has_single_folder)  # commented out — not in use
        # Batch 6 — Caption Image: only for a single supported image file.
        _IMAGE_EXTS = {'.png', '.jpg', '.jpeg', '.webp', '.bmp', '.tiff', '.tif', '.gif', '.svg'}
        act_caption.setEnabled(
            has_single_file
            and os.path.splitext(targets[0])[1].lower() in _IMAGE_EXTS
        )
        # Batch 7 — image intelligence actions (single image only)
        for act_img in (act_image_quality, act_detect_objects, act_reverse_image):
            act_img.setEnabled(
                has_single_file
                and os.path.splitext(targets[0])[1].lower() in _IMAGE_EXTS
            )
        # Batch 7 — metadata editor + rename suggestions
        act_edit_metadata.setEnabled(has_single_file)
        selected_files = [t for t in targets if os.path.isfile(t)]
        has_any_selected_file = len(selected_files) > 0
        has_files_in_current_folder = False
        if not targets and self.current_path and os.path.isdir(self.current_path):
            try:
                has_files_in_current_folder = any(
                    os.path.isfile(os.path.join(self.current_path, f))
                    for f in os.listdir(self.current_path)
                )
            except Exception:
                has_files_in_current_folder = False
        act_suggest_rename.setEnabled(has_any_selected_file or (not targets and has_files_in_current_folder))
        folder_to_use = ""
        if targets and len(targets) == 1 and os.path.isdir(targets[0]):
            folder_to_use = targets[0]
        elif self.current_path and os.path.isdir(self.current_path):
            folder_to_use = self.current_path
        act_suggest_rename_multi.setEnabled(bool(folder_to_use))
        # for act_b5 in (act_classify, act_auto_tag, act_find_dups, act_find_similar):  # commented out — not in use
        #     act_b5.setEnabled(has_single_file)

        # Batch 6 — Folder Intelligence / Statistics
        folder_target = ""
        if targets:
            if os.path.isdir(targets[0]):
                folder_target = targets[0]
            elif os.path.isfile(targets[0]):
                folder_target = os.path.dirname(targets[0])
        elif self.current_path and os.path.isdir(self.current_path):
            folder_target = self.current_path

        act_folder_intel = menu.addAction("Folder Statistics…")
        act_folder_intel.setEnabled(bool(folder_target and os.path.isdir(folder_target)))

        # Extension point: plugins may add their own context-menu actions.
        if False and self.plugin_registry is not None and targets:
            self.plugin_registry.invoke_hook("context_menu", menu, targets)

        action = menu.exec(view.viewport().mapToGlobal(pos))
        if action is None:
            return

        # Handle global / background-clickable actions first (do not require targets)
        if action is act_semantic_search:
            self.semantic_search_requested.emit()
            return
        elif action is act_folder_intel:
            path = folder_target or (targets[0] if targets else self.current_path)
            if path and os.path.isfile(path):
                path = os.path.dirname(path)
            if path and os.path.isdir(path):
                self.folder_intelligence_requested.emit(path)
            return
        # elif action is act_folder_chat:  # commented out — not in use
        #     path = targets[0] if targets else self.current_path
        #     if path:
        #         self.folder_chat_requested.emit(path)
        #     return
        elif action is act_suggest_rename_multi:
            folder = ""
            if targets and len(targets) == 1 and os.path.isdir(targets[0]):
                folder = targets[0]
            elif self.current_path:
                folder = self.current_path
            if folder:
                self.rename_suggest_multi_requested.emit(folder)
            return

        # Other actions require selected file/folder targets
        if not targets:
            return

        if action is act_open:
            for path in targets:
                self.file_activated.emit(path)
        elif action is act_rename:
            if len(targets) == 1:
                self._rename(targets[0])
        elif action is act_copy:
            self._copy(targets)
        elif action is act_move:
            self._move(targets)
        elif action is act_delete:
            self._delete(targets)
        elif action is act_props:
            self._properties(targets[0] if targets else None)
        elif action is act_ai_analyze:
            if targets:
                self.ai_analyze_requested.emit(targets[0])
        elif action is act_ask_ai:
            if targets:
                self.ask_ai_requested.emit(targets[0])
        elif action is act_caption:
            if targets:
                self.caption_requested.emit(targets[0])
        elif action is act_image_quality:
            if targets:
                self.image_quality_requested.emit(targets[0])
        elif action is act_detect_objects:
            if targets:
                self.object_detection_requested.emit(targets[0])
        elif action is act_reverse_image:
            if targets:
                self.reverse_image_requested.emit(targets[0])
        elif action is act_edit_metadata:
            if targets:
                self.edit_metadata_requested.emit(targets[0])
        elif action is act_suggest_rename:
            if targets:
                files = [t for t in targets if os.path.isfile(t)]
                if files:
                    self.rename_suggest_requested.emit(files)
            elif self.current_path:
                try:
                    files = [
                        os.path.join(self.current_path, f)
                        for f in os.listdir(self.current_path)
                        if os.path.isfile(os.path.join(self.current_path, f))
                    ]
                    if files:
                        self.rename_suggest_requested.emit(files)
                except Exception:
                    pass
        # elif action is act_classify:  # commented out — not in use
        #     self.classify_requested.emit(targets[0])
        # elif action is act_auto_tag:  # commented out — not in use
        #     self.auto_tag_requested.emit(targets[0])
        # elif action is act_find_dups:  # commented out — not in use
        #     self.find_duplicates_requested.emit(targets[0])
        # elif action is act_find_similar:  # commented out — not in use
        #     self.find_similar_requested.emit(targets[0])
        # elif action is act_find_related:  # commented out — not in use
        #     self.find_related_requested.emit(targets[0])
        # elif action is act_view_rels:  # commented out — not in use
        #     self.view_relationships_requested.emit(targets[0])
        # elif action is act_suggest_org:  # commented out — not in use
        #     self.suggest_organization_requested.emit(targets[0])

    def _check_ai_analysis_exists(self, file_path: str) -> bool:
        """Check if AI analysis exists for a file by computing its hash."""
        from services.file_identity import calculate_sha256_safe
        file_hash = calculate_sha256_safe(file_path)
        if not file_hash:
            return False
        try:
            from ai.cache_manager import AICacheManager
            from database.engine import Database

            # Access DB through the container if available, else check directly
            db_path = os.path.join(os.path.dirname(__file__), "..", "config", "intellivault.db")
            if os.path.exists(db_path):
                db = Database(db_path)
                cache = AICacheManager(db.session)
                result = cache.has_analysis(file_hash)
                db.dispose()
                return result
        except Exception:
            pass
        return False

    # ------------------------------------------------------------------ #
    def handle_drop(self, event, source_view) -> None:
        urls = event.mimeData().urls()
        if not urls:
            return
        internal = event.source() in (self.list_view, self.grid_view)
        if internal:
            # Let QFileSystemModel perform the move between folders.
            super(type(source_view), source_view).dropEvent(event)
            return
        for url in urls:
            src = url.toLocalFile()
            if not src:
                continue
            dest = os.path.join(self.current_path, os.path.basename(src.rstrip("/")))
            try:
                if os.path.isdir(src):
                    shutil.copytree(src, dest, dirs_exist_ok=True)
                elif os.path.isfile(src):
                    shutil.copy2(src, dest)
            except OSError as exc:
                QMessageBox.warning(self, "Drop failed", str(exc))
        event.acceptProposedAction()

    # ------------------------------------------------------------------ #
    def _rename(self, path: str) -> None:
        base = os.path.basename(path)
        new_name, ok = QInputDialog.getText(self, "Rename", "New name:", text=base)
        if ok and new_name and new_name != base:
            try:
                os.rename(path, os.path.join(os.path.dirname(path), new_name))
            except OSError as exc:
                QMessageBox.warning(self, "Rename failed", str(exc))

    def _copy(self, paths: list[str]) -> None:
        dest = QFileDialog.getExistingDirectory(self, "Copy to", self.current_path)
        if not dest:
            return
        for src in paths:
            target = os.path.join(dest, os.path.basename(src.rstrip("/")))
            try:
                if os.path.isdir(src):
                    shutil.copytree(src, target, dirs_exist_ok=True)
                else:
                    shutil.copy2(src, target)
            except OSError as exc:
                QMessageBox.warning(self, "Copy failed", str(exc))

    def _move(self, paths: list[str]) -> None:
        dest = QFileDialog.getExistingDirectory(self, "Move to", self.current_path)
        if not dest:
            return
        for src in paths:
            target = os.path.join(dest, os.path.basename(src.rstrip("/")))
            try:
                shutil.move(src, target)
            except OSError as exc:
                QMessageBox.warning(self, "Move failed", str(exc))

    def _delete(self, paths: list[str]) -> None:
        reply = QMessageBox.question(
            self,
            "Delete",
            f"Delete {len(paths)} item(s)? This cannot be undone.",
            QMessageBox.Yes | QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        for src in paths:
            try:
                if os.path.isdir(src):
                    shutil.rmtree(src)
                else:
                    os.remove(src)
            except OSError as exc:
                QMessageBox.warning(self, "Delete failed", str(exc))

    def _properties(self, path: str | None) -> None:
        if not path or not os.path.exists(path):
            return
        from core.file_stat_util import format_file_size
        fi = QFileInfo(path)
        size = fi.size()
        modified = fi.lastModified().toString()
        is_dir = fi.isDir()
        size_str = format_file_size(size, include_exact=True) if not is_dir else "-"
        text = (
            f"Name: {fi.fileName()}\n"
            f"Path: {fi.absoluteFilePath()}\n"
            f"Type: {'Folder' if is_dir else 'File'}\n"
            f"Size: {size_str}\n"
            f"Modified: {modified}"
        )
        QMessageBox.information(self, "Properties", text)
