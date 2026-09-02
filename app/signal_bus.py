"""Application-wide signal bus.

All cross-module communication flows through this single hub so widgets stay
free of business logic and subsystems remain decoupled. Long-running work and
background services emit progress/result here; the UI only listens.
"""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal


class SignalBus(QObject):
    # Navigation ------------------------------------------------------- #
    path_changed = Signal(str)            # current folder path changed
    selection_changed = Signal(list)      # list of selected file paths
    files_changed = Signal(str)           # filesystem changed in a path

    # Files ------------------------------------------------------------- #
    file_opened = Signal(str)             # a file was opened
    file_selected = Signal(str)           # a file was selected (e.g. from indexed panel)

    # Settings / theme -------------------------------------------------- #
    settings_changed = Signal(str)        # a settings key changed
    theme_changed = Signal(str)           # theme name changed

    # Tasks (background services) -------------------------------------- #
    task_queued = Signal(object)          # a Task object was queued
    task_progress = Signal(str, int, int) # task_id, current, total
    task_finished = Signal(str, object)   # task_id, result

    # UI feedback ------------------------------------------------------- #
    status_message = Signal(str)          # transient status-bar text

    # Plugins ----------------------------------------------------------- #
    plugin_loaded = Signal(str)           # plugin name
    plugin_unloaded = Signal(str)         # plugin name

    # Batch 5 — organization & knowledge management -------------------- #
    classification_updated = Signal(str)         # file path classified
    tags_updated = Signal(str)                   # file path tagged
    duplicates_updated = Signal()                # duplicate scan completed
    relationships_updated = Signal()             # file relationships rebuilt
    collection_updated = Signal(int)             # collection id changed
    saved_search_updated = Signal(int)           # saved search id changed
    organization_suggestion_updated = Signal(int)  # suggestion id changed
    dashboard_refresh_requested = Signal()       # dashboard should refresh

    # Batch 6 — captioning + folder classification --------------------- #
    caption_updated = Signal(str)                  # image caption generated
    folder_classification_updated = Signal(str)    # folder composition changed

    # Batch 7 — metadata, image intelligence, timeline, folder summary --- #
    metadata_updated = Signal(str)                 # user metadata edited (path)
    image_quality_updated = Signal(str)            # quality analyzed (path)
    objects_updated = Signal(str)                  # objects detected (path)
    timeline_updated = Signal()                    # timeline sources changed
    folder_summary_updated = Signal(str)           # folder summary generated
    rename_completed = Signal(str)                 # a file was renamed (new path)

    def __init__(self) -> None:
        super().__init__()
