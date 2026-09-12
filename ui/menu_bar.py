"""Menu bar.

Defines the application menus (File, Edit, View, Tools, Help). Actions are
exposed as signals so the main window can wire them to subsystems without the
menu knowing about business logic.
"""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QMessageBox


class MenuBar(QObject):
    toggle_sidebar = Signal()
    toggle_preview = Signal()
    toggle_theme = Signal()
    refresh = Signal()
    open_settings = Signal()
    # Batch 4 entries
    open_workspace_chat = Signal()
    open_knowledge_graph = Signal()
    # open_agent_mode = Signal()  # commented out — not in use
    open_conversation_history = Signal()
    # Batch 5 entries
    open_duplicates = Signal()
    open_saved_searches = Signal()
    # open_collections = Signal()  # commented out — not in use
    open_dashboard = Signal()
    open_file_relationships = Signal()
    # Batch 7 entries
    open_metadata_export = Signal()
    open_file_timeline = Signal()
    open_compare_documents = Signal()
    open_image_filter = Signal()
    open_organize_files = Signal()
    open_check_inactive = Signal()
    open_cleanup_db = Signal()
    open_folder_statistics = Signal()

    def __init__(self, window, container) -> None:
        super().__init__()
        self.window = window
        self.container = container
        self._build()

    def _build(self) -> None:
        menubar = self.window.menuBar()

        file_menu = menubar.addMenu("&File")
        quit_act = file_menu.addAction("&Quit")
        quit_act.triggered.connect(self.window.close)

        edit_menu = menubar.addMenu("&Edit")
        edit_menu.addAction("&Copy")  # placeholder (wired in M4)
        edit_menu.addAction("&Move")  # placeholder
        edit_menu.addAction("&Delete")  # placeholder

        view_menu = menubar.addMenu("&View")
        self.act_toggle_sidebar = view_menu.addAction("Toggle &Sidebar")
        self.act_toggle_preview = view_menu.addAction("Toggle &Preview")
        view_menu.addSeparator()
        self.act_toggle_theme = view_menu.addAction("Toggle &Theme")
        self.act_refresh = view_menu.addAction("&Refresh")

        tools_menu = menubar.addMenu("&Tools")
        self.act_workspace_chat = tools_menu.addAction("Workspace Chat...")
        self.act_knowledge_graph = tools_menu.addAction("Knowledge Graph...")
        self.act_conversation_history = tools_menu.addAction("Conversation History...")
        tools_menu.addSeparator()
        # self.act_agent_mode = tools_menu.addAction("Agent Mode...")  # commented out — not in use
        # tools_menu.addSeparator()
        # Intelligent Organization & Inactivity Reminders
        self.act_organize_files = tools_menu.addAction("📁 Organize Files into Folder...")
        self.act_check_inactive = tools_menu.addAction("🔔 Check Inactive Files...")
        self.act_folder_statistics = tools_menu.addAction("📊 Folder Statistics...")
        self.act_duplicates = tools_menu.addAction("Duplicate Files...")
        self.act_file_relationships = tools_menu.addAction("File Relationships...")
        self.act_saved_searches = tools_menu.addAction("Saved Searches...")
        # self.act_collections = tools_menu.addAction("Collections...")  # commented out — not in use
        self.act_dashboard = tools_menu.addAction("Knowledge Dashboard...")
        tools_menu.addSeparator()
        # Batch 7 — Metadata tools, timeline, comparison, image filtering
        self.act_metadata_export = tools_menu.addAction("Export Metadata...")
        self.act_file_timeline = tools_menu.addAction("File Timeline...")
        self.act_compare_documents = tools_menu.addAction("Compare Documents...")
        self.act_image_filter = tools_menu.addAction("AI Image Filter...")
        self.act_image_filter.setVisible(False)  # Hidden temporarily from Tools menu (set to True to revert)
        self.act_cleanup_db = tools_menu.addAction("🧹 Clean Database (Purge Stale Records)...")
        tools_menu.addSeparator()
        self.act_settings = tools_menu.addAction("&Settings...")

        help_menu = menubar.addMenu("&Help")
        about_act = help_menu.addAction("&About")
        about_act.triggered.connect(self._about)

        self.act_toggle_sidebar.triggered.connect(self.toggle_sidebar)
        self.act_toggle_preview.triggered.connect(self.toggle_preview)
        self.act_toggle_theme.triggered.connect(self.toggle_theme)
        self.act_refresh.triggered.connect(self.refresh)
        self.act_workspace_chat.triggered.connect(self.open_workspace_chat)
        self.act_knowledge_graph.triggered.connect(self.open_knowledge_graph)
        self.act_conversation_history.triggered.connect(self.open_conversation_history)
        # self.act_agent_mode.triggered.connect(self.open_agent_mode)  # commented out — not in use
        self.act_organize_files.triggered.connect(self.open_organize_files)
        self.act_check_inactive.triggered.connect(self.open_check_inactive)
        self.act_folder_statistics.triggered.connect(self.open_folder_statistics)
        self.act_cleanup_db.triggered.connect(self.open_cleanup_db)
        self.act_duplicates.triggered.connect(self.open_duplicates)
        self.act_file_relationships.triggered.connect(self.open_file_relationships)
        self.act_saved_searches.triggered.connect(self.open_saved_searches)
        # self.act_collections.triggered.connect(self.open_collections)  # commented out — not in use
        self.act_dashboard.triggered.connect(self.open_dashboard)
        self.act_metadata_export.triggered.connect(self.open_metadata_export)
        self.act_file_timeline.triggered.connect(self.open_file_timeline)
        self.act_compare_documents.triggered.connect(self.open_compare_documents)
        self.act_image_filter.triggered.connect(self.open_image_filter)
        self.act_settings.triggered.connect(self.open_settings)



    def _about(self) -> None:
        QMessageBox.about(
            self.window,
            "About IntelliVault",
            "IntelliVault Foundation v1.0\n\nA modern, extensible file explorer.",
        )
