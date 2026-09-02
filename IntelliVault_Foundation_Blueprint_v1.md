# IntelliVault Foundation v1.0 - Master Implementation Blueprint

## Goal

Build a **production-quality Ubuntu desktop application** that functions
as a modern file explorer first, and later becomes an AI-powered
intelligent file explorer through modular feature batches.

**Target Platform** - Ubuntu 24.xx - Package formats: - `.deb` -
`.AppImage`

------------------------------------------------------------------------

# Technology Stack

  -----------------------------------------------------------------------
  Layer                               Technology
  ----------------------------------- -----------------------------------
  Language                            Python 3.12+

  GUI                                 PySide6 (Qt6)

  Database                            SQLite + SQLAlchemy

  File Monitoring                     watchdog

  Packaging                           PyInstaller (development),
                                      AppImage, fpm/dpkg-deb for .deb

  Version Control                     Git

  Testing                             pytest

  Logging                             Python logging
  -----------------------------------------------------------------------

------------------------------------------------------------------------

# Development Philosophy

1.  Build the entire desktop software first.
2.  No AI code during the foundation phase.
3.  Every subsystem must expose extension points for future AI modules.
4.  Keep UI responsive using worker threads.
5.  Every module should be independently testable.

------------------------------------------------------------------------

# Repository Structure

``` text
IntelliVault/
    app/
    core/
    ui/
    widgets/
    services/
    database/
    plugins/
    ai/
    resources/
    config/
    cache/
    logs/
    tests/
    main.py
```

------------------------------------------------------------------------

# Foundation Milestones

## M1 Project Bootstrap

Deliverables: - Repository - Virtual environment - Dependency
management - Folder structure - Logging - Config loader

------------------------------------------------------------------------

## M2 Main Window

Deliverables:

-   Main window
-   Menu bar
-   Toolbar
-   Status bar
-   Dock widgets
-   Theme engine

------------------------------------------------------------------------

## M3 Navigation

Deliverables

-   Folder tree
-   Favorites
-   Drives
-   Breadcrumb navigation

------------------------------------------------------------------------

## M4 File Explorer

Deliverables

-   List view
-   Grid view
-   Sorting
-   Multi-selection
-   Context menu
-   Drag & drop

------------------------------------------------------------------------

## M5 Preview Panel

Support:

-   Images
-   PDF preview
-   Text preview
-   Audio information
-   Video thumbnail
-   File properties

Reserve placeholders for future AI: - Summary - Keywords - OCR - Related
files

------------------------------------------------------------------------

## M6 Database

Tables:

-   files
-   folders
-   settings
-   favorites
-   recent
-   tasks
-   plugins
-   logs

------------------------------------------------------------------------

## M7 Background Services

Implement:

-   Task manager
-   Thread manager
-   File watcher interface
-   Cache manager

------------------------------------------------------------------------

## M8 Settings

Tabs:

-   General
-   Appearance
-   File Explorer
-   Database
-   Plugins
-   Performance

Reserve: - AI - OCR - Models - Embeddings - LLM

------------------------------------------------------------------------

# UI Layout

``` text
+-----------------------------------------------------------+
| Menu                                                      |
+-----------------------------------------------------------+
| Toolbar                                                   |
+----------+------------------------------+-----------------+
| Sidebar  | File Explorer                | Preview Panel   |
|          |                              |                 |
|          |                              |                 |
+----------+------------------------------+-----------------+
| Status Bar                                                |
+-----------------------------------------------------------+
```

------------------------------------------------------------------------

# Coding Rules

-   MVC-inspired separation.
-   No business logic inside widgets.
-   Services communicate through signals.
-   Long tasks run only in worker threads.
-   Use dependency injection where practical.

------------------------------------------------------------------------

# Future Batch Integration Points

Batch 1: File scanner Batch 2: Document parser Batch 3: OCR Batch 4:
Embeddings Batch 5: Vision Batch 6: Audio/Video Batch 7: LLM Batch 8:
Duplicate engine Batch 9: Organization Batch 10: Analytics

Each batch should register through a plugin interface rather than
modifying the core UI.

------------------------------------------------------------------------

# Ubuntu Deliverables

Development: - python -m venv - pip requirements - editable install

Release: - AppImage - .deb - GitHub Releases

------------------------------------------------------------------------

# AI Coding Workflow

Work in very small prompts.

1.  Bootstrap project.
2.  Build main window.
3.  Build sidebar.
4.  Build explorer.
5.  Build preview.
6.  Build settings.
7.  Build database.
8.  Build services.
9.  Polish UI.
10. Freeze Foundation v1.0.

Do not begin AI batches until Foundation v1.0 is complete.

------------------------------------------------------------------------

# Definition of Done

The application must: - Browse folders - Open files - Rename files -
Copy/move/delete - Search by filename - Show previews - Persist
settings - Remain responsive - Have plugin infrastructure ready - Be
packageable as .deb and .AppImage

Only after this milestone is complete should AI feature batches begin.
