# IntelliVault Foundation v1.0 — Implementation Plan

This plan translates `IntelliVault_Foundation_Blueprint_v1.md` into an
ordered, actionable sequence of work. It is intentionally granular so each
item can be executed as a small, testable prompt (per the AI Coding
Workflow in the blueprint).

## Conventions (apply to every step)

- Python 3.12+, PySide6 (Qt6), SQLAlchemy + SQLite, watchdog, pytest.
- MVC separation: no business logic inside widgets; services talk via Qt
  signals; long tasks run in worker threads (QThread / QRunnable).
- Every module independently testable; extension points for future AI
  batches (Batch 1–10) via a plugin interface.
- Default paths under project root: `cache/`, `logs/`, `config/`.

## Repository Structure (create once, M1)

```
IntelliVault/
    app/            # app bootstrap, signal bus, DI container
    core/           # models, config, logging, plugin registry
    ui/             # main window, menus, docks
    widgets/        # reusable UI widgets (tree, list, grid, preview)
    services/       # task/thread managers, file watcher, cache
    database/       # SQLAlchemy engine, models, migrations, session
    plugins/        # plugin interface + loader (AI batches register here)
    ai/             # placeholder package (reserved, no logic in v1)
    resources/      # icons, themes, qss
    config/         # default config files
    cache/          # runtime cache (gitignored)
    logs/           # runtime logs (gitignored)
    tests/          # pytest suites per module
    main.py         # entry point
    requirements.txt
    pyproject.toml  # editable install + tooling config
```

---

## M1 — Project Bootstrap

1. `pyproject.toml`: project metadata, editable install (`pip install -e .`),
   pytest config, package layout.
2. `requirements.txt`: pyside6, sqlalchemy, watchdog, pytest, pytest-qt.
3. Create full folder tree above + `.gitignore` (cache/, logs/, venv/).
4. `core/logging_setup.py`: structured logging to `logs/intellivault.log`
   + console handler; level from config.
5. `core/config.py`: load/save settings from `config/settings.toml`
   (or JSON); typed accessors; watcher for external change.
6. `app/signal_bus.py`: central Qt signal hub for cross-module events
   (file opened, selection changed, settings changed, task queued).
7. `app/container.py`: minimal dependency-injection container wiring
   services/config/logging.
8. `main.py`: initialize logging, config, container; launch `MainWindow`.
9. `tests/test_config.py`, `tests/test_logging.py`.

**Done when:** `python main.py` launches a minimal window; config + logging
work; tests pass.

---

## M2 — Main Window

10. `ui/main_window.py`: QMainWindow with menu bar, toolbar, status bar,
    central layout split into Sidebar | Explorer | Preview (per UI Layout).
11. `ui/menu_bar.py`: File, Edit, View, Tools, Help menus (wired to no-op
    actions reserved for future features).
12. `ui/toolbar.py`: back/forward, up, refresh, view-toggle, search box.
13. `ui/status_bar.py`: item count, free space, async task indicator.
14. `ui/theme_engine.py`: load QSS from `resources/themes/`, light/dark,
    runtime switch via signal.
15. `ui/dock_manager.py`: dockable sidebar + preview panel (toggleable).
16. `tests/test_main_window.py` (smoke + theme switch).

**Done when:** Window shows all regions, menus/toolbar/status bar functional,
theme switch works.

---

## M3 — Navigation

17. `widgets/folder_tree.py`: recursive QFileSystemModel tree view.
18. `widgets/favorites.py`: user favorites list (add/remove, persisted).
19. `widgets/drives.py`: mounted volumes / bookmarks pane.
20. `widgets/breadcrumb.py`: path breadcrumb with click + editable path.
21. Wire navigation selection → emits `pathChanged` on signal bus →
    Explorer + Preview react.
22. `tests/test_navigation.py`.

**Done when:** Clicking tree/drives updates breadcrumb + explorer; favorites
persist.

---

## M4 — File Explorer

23. `widgets/file_list.py`: QListView-based list view (columns: name, size,
    type, modified).
24. `widgets/file_grid.py`: QListView icon/grid view with thumbnails.
25. View toggle (list/grid) in toolbar wired to theme + signal.
26. Sorting + multi-column sort; multi-selection (ctrl/shift).
27. `widgets/file_context_menu.py`: open, rename, copy, move, delete,
    properties (delegates to services).
28. Drag & drop: internal move + external file import.
29. `tests/test_explorer.py` (model correctness, sorting).

**Done when:** Files list/grid, sort, multi-select, context actions, DnD work.

---

## M5 — Preview Panel

30. `widgets/preview_panel.py`: dispatcher by mime type.
31. Image preview (QPixmap scaled), PDF preview (pdfium/poppler via
    PySide6 QPdf), text preview (QPlainTextEdit read-only), audio metadata
    (mutagen/taglib), video thumbnail (ffmpeg frame grab), file properties
    (size, dates, hashes).
32. Reserve placeholders: Summary, Keywords, OCR, Related files (disabled
    AI panels with TODO hooks into `ai/` + plugin registry).
33. `tests/test_preview.py` (mock files per type).

**Done when:** Selecting a file shows correct preview; placeholders visible
but inert.

---

## M6 — Database

34. `database/engine.py`: SQLAlchemy engine + session factory (SQLite at
    `config/intellivault.db`).
35. `database/models.py`: tables `files`, `folders`, `settings`,
    `favorites`, `recent`, `tasks`, `plugins`, `logs` (per blueprint).
36. `database/repository.py`: CRUD helpers per table; typed queries.
37. Migrations: lightweight schema version table + init script.
38. Persist favorites, recent, settings, logs into DB.
39. `tests/test_database.py` (round-trip CRUD per table).

**Done when:** All 8 tables exist; persistence verified by tests.

---

## M7 — Background Services

40. `services/thread_manager.py`: QThreadPool wrapper + worker base
    (QRunnable) with signals for progress/result/error.
41. `services/task_manager.py`: queue, priorities, cancellation, status
    emitted to status bar.
42. `services/file_watcher.py`: watchdog wrapper → emits `filesChanged`
    signal (extension point for Batch 1 scanner).
43. `services/cache_manager.py`: disk + memory cache with TTL/eviction.
44. Integrate cache into thumbnail/preview generation (off main thread).
45. `tests/test_services.py` (thread, task, watcher, cache).

**Done when:** Long ops run off-UI; watcher updates explorer; cache hits
reduce reloads.

---

## M8 — Settings

46. `ui/settings_dialog.py`: tabbed (QTabWidget).
47. Tabs: General, Appearance, File Explorer, Database, Plugins,
    Performance (functional controls bound to config + DB).
48. Reserved tabs: AI, OCR, Models, Embeddings, LLM (disabled placeholders
    bound to plugin registry).
49. Apply/reset; emits `settingsChanged` to reload theme/cache/explorer.
50. `tests/test_settings.py`.

**Done when:** Settings persist + apply live; reserved tabs present but inert.

---

## Plugin Infrastructure (cross-cutting, finalize in M7/M8)

51. `core/plugin_registry.py`: `PluginInterface` ABC with
    `name`, `version`, `hooks`, `register()`, `unregister()`.
52. `plugins/loader.py`: discover + load entry points (future Batch 1–10).
53. Hook points wired: file scanned, preview render, settings panel,
    context menu, task types.
54. `tests/test_plugin_registry.py` (dummy plugin load/unload).

---

## Definition of Done (verification before freezing v1.0)

- [ ] Browse folders (M3/M4)
- [ ] Open files (M4/M5)
- [ ] Rename / copy / move / delete (M4)
- [ ] Search by filename (toolbar + DB `files` index)
- [ ] Show previews (M5)
- [ ] Persist settings (M6/M8)
- [ ] Remain responsive (M7 worker threads)
- [ ] Plugin infrastructure ready (registry + hooks)
- [ ] Packageable: `requirements.txt`, editable install, plus packaging
      scripts for `.deb` (fpm/dpkg-deb) and `.AppImage` (PyInstaller)

---

## Suggested Execution Order (small prompts)

M1 → M2 → M3 → M4 → M5 → M6 → M7 → M8 → Plugin infra → Polish → Freeze v1.0

Do **not** begin AI batches (Batch 1–10) until the Definition of Done is met.
