"""Settings dialog.

A tabbed (``QTabWidget``) preferences window. Functional tabs — General,
Appearance, File Explorer, Database, Plugins, Performance — are bound to the
shared ``Config`` (and mirrored into the database ``settings`` table). Reserved
tabs (AI, OCR, Models, Embeddings, LLM) are shown disabled as placeholders for
future AI batches. Applying writes values, applies the theme live and emits
``settings_changed`` on the bus.
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog,
    QTabWidget,
    QWidget,
    QFormLayout,
    QLineEdit,
    QCheckBox,
    QComboBox,
    QSpinBox,
    QPushButton,
    QVBoxLayout,
    QHBoxLayout,
    QGroupBox,
    QLabel,
)
from PySide6.QtCore import Qt


class SettingsDialog(QDialog):
    def __init__(self, config, bus, theme_engine, repository=None, parent=None) -> None:
        super().__init__(parent)
        self.config = config
        self.bus = bus
        self.theme_engine = theme_engine
        self.repository = repository

        self.setWindowTitle("Settings")
        self.resize(520, 420)

        self.tabs = QTabWidget()
        self._build_functional_tabs()
        # Reserved AI tabs hidden for now (AI/OCR/Models/Embeddings/LLM) — user asked to hide.
        # self._build_reserved_tabs()

        buttons = QHBoxLayout()
        self.apply_btn = QPushButton("Apply")
        self.reset_btn = QPushButton("Reset")
        self.cancel_btn = QPushButton("Cancel")
        buttons.addStretch(1)
        buttons.addWidget(self.apply_btn)
        buttons.addWidget(self.reset_btn)
        buttons.addWidget(self.cancel_btn)

        layout = QVBoxLayout(self)
        layout.addWidget(self.tabs, 1)
        layout.addLayout(buttons)

        self.apply_btn.clicked.connect(self.apply_settings)
        self.reset_btn.clicked.connect(self.load_settings)
        self.cancel_btn.clicked.connect(self.reject)

        self.load_settings()

    # ------------------------------------------------------------------ #
    def _build_functional_tabs(self) -> None:
        self._general = self._general_tab()
        self._appearance = self._appearance_tab()
        self._explorer = self._explorer_tab()
        self._database = self._database_tab()
        self._plugins = self._plugins_tab()

        self.tabs.addTab(self._general, "General")
        self.tabs.addTab(self._appearance, "Appearance")
        self.tabs.addTab(self._explorer, "File Explorer")
        self.tabs.addTab(self._database, "Database")
        self.tabs.addTab(self._plugins, "Plugins")
        self.tabs.addTab(self._performance_tab(), "Performance")
        # Batch 4/5/6/7 tabs hidden for now — backend still active, UI hidden per user request.
        # Keep widgets constructed so load/apply still work if re-enabled.
        self._batch4_hidden = self._batch4_tab()
        self._batch5_hidden = self._batch5_tab()
        self._batch6_hidden = self._batch6_tab()
        self._batch7_hidden = self._batch7_tab()
        # self.tabs.addTab(self._batch4_hidden, "Batch 4")
        # self.tabs.addTab(self._batch5_hidden, "Batch 5")
        # self.tabs.addTab(self._batch6_hidden, "Batch 6")
        # self.tabs.addTab(self._batch7_hidden, "Batch 7")

    def _build_reserved_tabs(self) -> None:
        for name in ("AI", "OCR", "Models", "Embeddings", "LLM"):
            box = QGroupBox(f"{name} (reserved)")
            v = QVBoxLayout(box)
            note = QLabel(
                f"The {name} module will be provided by a future AI batch.\n"
                "These controls are placeholders and currently disabled."
            )
            note.setWordWrap(True)
            v.addWidget(note)
            for ctrl_name in ("Enable", "Provider", "Model path"):
                ctrl = QLineEdit(ctrl_name)
                ctrl.setEnabled(False)
                v.addWidget(ctrl)
            tab = QWidget()
            tl = QVBoxLayout(tab)
            tl.addWidget(box)
            tl.addStretch(1)
            self.tabs.addTab(tab, name)

    # ------------------------------------------------------------------ #
    def _general_tab(self) -> QWidget:
        from PySide6.QtWidgets import QFileDialog
        w = QWidget()
        form = QFormLayout(w)
        self.startup_path = QLineEdit()
        self.single_click = QCheckBox("Open files on single click")
        self.confirm_delete = QCheckBox("Confirm before delete")

        # --- Inactivity Reminder Group ---
        self.inactivity_reminder_cb = QCheckBox("Enable inactive file reminders on startup")
        self.inactivity_threshold_spin = QSpinBox()
        self.inactivity_threshold_spin.setRange(1, 365)
        self.inactivity_threshold_spin.setSuffix(" days")

        # Folder picker row
        folder_row = QHBoxLayout()
        self.inactivity_folder_edit = QLineEdit()
        self.inactivity_folder_edit.setPlaceholderText("No folder set — reminder won't fire on startup")
        self.inactivity_folder_edit.setToolTip(
            "Reminders on startup will ONLY check files inside this folder.\n"
            "Leave empty to disable auto-reminder on startup.\n"
            "You can still use Tools → Check Inactive Files to scan everything."
        )
        browse_btn = QPushButton("Browse…")
        browse_btn.setFixedWidth(80)

        def _pick_folder():
            current = self.inactivity_folder_edit.text().strip() or ""
            path = QFileDialog.getExistingDirectory(self, "Select Folder to Watch for Inactive Files", current)
            if path:
                self.inactivity_folder_edit.setText(path)

        browse_btn.clicked.connect(_pick_folder)
        folder_row.addWidget(self.inactivity_folder_edit, 1)
        folder_row.addWidget(browse_btn)

        clear_btn = QPushButton("Clear")
        clear_btn.setFixedWidth(55)
        clear_btn.setToolTip("Remove the watched folder — disables auto-reminder on startup")
        clear_btn.clicked.connect(lambda: self.inactivity_folder_edit.clear())
        folder_row.addWidget(clear_btn)

        form.addRow("Startup path", self.startup_path)
        form.addRow(self.single_click)
        form.addRow(self.confirm_delete)
        form.addRow(self.inactivity_reminder_cb)
        form.addRow("Inactivity alert threshold", self.inactivity_threshold_spin)
        form.addRow("Watched folder for reminders", folder_row)
        return w


    def _appearance_tab(self) -> QWidget:
        w = QWidget()
        form = QFormLayout(w)
        self.theme_combo = QComboBox()
        self.theme_combo.addItems(self.theme_engine.available())
        form.addRow("Theme", self.theme_combo)
        return w

    def _explorer_tab(self) -> QWidget:
        w = QWidget()
        form = QFormLayout(w)
        self.view_combo = QComboBox()
        self.view_combo.addItems(["list", "grid"])
        self.show_hidden = QCheckBox("Show hidden files")
        self.thumbnails = QCheckBox("Generate thumbnails")
        form.addRow("Default view", self.view_combo)
        form.addRow(self.show_hidden)
        form.addRow(self.thumbnails)
        return w

    def _database_tab(self) -> QWidget:
        w = QWidget()
        form = QFormLayout(w)
        self.db_path = QLineEdit()
        self.db_path.setReadOnly(True)
        form.addRow("Database file", self.db_path)
        form.addRow(QLabel("Path is set in config/database.path."))
        return w

    def _plugins_tab(self) -> QWidget:
        w = QWidget()
        form = QFormLayout(w)
        self.plugin_checks: dict[str, QCheckBox] = {}
        plugins = self.repository.list_plugins() if self.repository else []
        if not plugins:
            form.addRow(QLabel("No plugins registered yet."))
        for plugin in plugins:
            cb = QCheckBox(f"{plugin.name} (v{plugin.version})")
            cb.setChecked(plugin.enabled)
            self.plugin_checks[plugin.name] = cb
            form.addRow(cb)
        return w

    def _performance_tab(self) -> QWidget:
        w = QWidget()
        outer = QVBoxLayout(w)
        form_wrap = QWidget()
        form = QFormLayout(form_wrap)
        self.max_threads = QSpinBox()
        self.max_threads.setRange(1, 32)
        self.cache_size = QSpinBox()
        self.cache_size.setRange(16, 8192)
        self.cache_size.setSuffix(" MB")
        form.addRow("Max worker threads", self.max_threads)
        form.addRow("Cache size", self.cache_size)

        # --- Compute acceleration (modern backend, Linux+Windows) ---
        # 0 = auto (all cores). Exposes CPU cores / GPU / iGPU tuning
        # without changing layout or UX flow.
        import os as _os

        self.cpu_threads = QSpinBox()
        self.cpu_threads.setRange(0, max(1, _os.cpu_count() or 8))
        self.cpu_threads.setSpecialValueText("auto")
        self.cpu_threads.setToolTip("Caps indexing + BLAS threads (0=auto). Lower to reduce load.")
        self.embed_batch = QSpinBox()
        self.embed_batch.setRange(8, 128)
        self.embed_batch.setToolTip("Ollama embed batch size (32 default, CPU-safe).")
        self.backend_combo = QComboBox()
        self.backend_combo.addItems(["auto", "cpu", "gpu", "both"])
        self.gpu_enabled = QCheckBox("Enable GPU (CUDA/DirectML if installed, else CPU)")
        self.igpu_enabled = QCheckBox("Allow integrated GPU (low-VRAM / OpenVINO mode)")
        self.low_resource = QCheckBox("Low-resource mode (smaller batches, less RAM)")
        form.addRow("CPU cores (0=auto)", self.cpu_threads)
        form.addRow("Embed batch size", self.embed_batch)
        form.addRow("Compute backend", self.backend_combo)
        form.addRow(self.gpu_enabled)
        form.addRow(self.igpu_enabled)
        form.addRow(self.low_resource)

        # --- Hardware scan + dynamic suggestion (Linux + Windows) ---
        hw_box = QGroupBox("Detected hardware + recommendation")
        hw_lay = QVBoxLayout(hw_box)
        self.hw_info_label = QLabel("Not scanned yet — click Scan hardware.")
        self.hw_info_label.setWordWrap(True)
        self.hw_suggest_label = QLabel("")
        self.hw_suggest_label.setWordWrap(True)
        btn_row = QHBoxLayout()
        self.hw_scan_btn = QPushButton("Scan hardware")
        self.hw_apply_btn = QPushButton("Apply recommended")
        self.hw_apply_btn.setEnabled(False)
        self._hw_recommendation = None
        btn_row.addWidget(self.hw_scan_btn)
        btn_row.addWidget(self.hw_apply_btn)
        btn_row.addStretch(1)
        hw_lay.addWidget(self.hw_info_label)
        hw_lay.addLayout(btn_row)
        hw_lay.addWidget(self.hw_suggest_label)
        self.hw_scan_btn.clicked.connect(self._on_hw_scan)
        self.hw_apply_btn.clicked.connect(self._on_hw_apply)

        outer.addWidget(form_wrap)
        outer.addWidget(hw_box)
        return w

    def _on_hw_scan(self) -> None:
        try:
            from services.compute import recommend_settings, scan_hardware
        except Exception as exc:
            self.hw_info_label.setText(f"Scan failed: {exc}")
            return
        try:
            hw = scan_hardware()
        except Exception as exc:
            self.hw_info_label.setText(f"Scan failed: {exc}")
            return
        try:
            rec = recommend_settings(hw)
        except Exception as exc:
            self.hw_info_label.setText(f"Recommendation failed: {exc}")
            return
        self._hw_recommendation = rec
        try:
            cpu = hw.get("cpu") or {}
            gpus = hw.get("gpus") or []
            lines = [
                f"OS: {hw.get('platform')} | CPU threads: {cpu.get('logical')} "
                f"(physical {cpu.get('physical') or '?'}) | RAM: {hw.get('ram_gb')} GB"
            ]
            if gpus:
                for g in gpus:
                    lines.append(f"GPU: {g.get('name')} — {g.get('vram_gb')} GB ({g.get('kind')}/{g.get('via')})")
            else:
                lines.append("GPU: none detected (CPU-only)")
            self.hw_info_label.setText("\n".join(lines))
            r = rec
            self.hw_suggest_label.setText(
                "Recommended: threads={t}, cache={c}MB, batch={b}, backend={be}, "
                "gpu={g}, igpu={i}, low={l}\n{why}".format(
                    t=r["performance.max_threads"], c=r["performance.cache_size_mb"],
                    b=r["compute.embed_batch"], be=r["compute.backend"],
                    g="on" if r["compute.gpu_enabled"] else "off",
                    i="on" if r["compute.allow_igpu"] else "off",
                    l="on" if r["compute.low_resource_mode"] else "off",
                    why="\n".join("• " + x for x in r.get("_reasons", [])),
                )
            )
            self.hw_apply_btn.setEnabled(True)
        except Exception as exc:
            self.hw_info_label.setText(f"Scan failed: {exc}")

    def _on_hw_apply(self) -> None:
        rec = getattr(self, "_hw_recommendation", None)
        if not rec:
            return
        try:
            self.max_threads.setValue(int(rec["performance.max_threads"]))
            self.cache_size.setValue(int(rec["performance.cache_size_mb"]))
            self.cpu_threads.setValue(0)
            self.embed_batch.setValue(int(rec["compute.embed_batch"]))
            self.backend_combo.setCurrentText(str(rec["compute.backend"]))
            self.gpu_enabled.setChecked(bool(rec["compute.gpu_enabled"]))
            self.igpu_enabled.setChecked(bool(rec["compute.allow_igpu"]))
            self.low_resource.setChecked(bool(rec["compute.low_resource_mode"]))
            self.hw_suggest_label.setText(self.hw_suggest_label.text() + "\nApplied — click Apply to save.")
        except Exception:
            pass

    # ------------------------------------------------------------------ #
    # Batch 4 — Conversations, Retrieval, Knowledge Graph, Agent (§42)
    # ------------------------------------------------------------------ #
    def _batch4_tab(self) -> QWidget:
        w = QWidget()
        outer = QVBoxLayout(w)

        conv = QGroupBox("Conversations")
        conv_form = QFormLayout(conv)
        self.conv_scope = QComboBox()
        self.conv_scope.addItems(["folder", "workspace", "file"])
        self.conv_history_chars = QSpinBox()
        self.conv_history_chars.setRange(500, 20000)
        self.conv_history_chars.setSingleStep(500)
        self.conv_turns = QSpinBox()
        self.conv_turns.setRange(2, 40)
        conv_form.addRow("Default scope", self.conv_scope)
        conv_form.addRow("History budget (chars)", self.conv_history_chars)
        conv_form.addRow("Recent turns in context", self.conv_turns)
        outer.addWidget(conv)

        retr = QGroupBox("Retrieval")
        retr_form = QFormLayout(retr)
        self.top_k = QSpinBox()
        self.top_k.setRange(1, 20)
        self.threshold = QSpinBox()
        self.threshold.setRange(1, 99)
        self.threshold.setSuffix("%")
        retr_form.addRow("Top-k results", self.top_k)
        retr_form.addRow("Similarity threshold", self.threshold)
        outer.addWidget(retr)

        kg = QGroupBox("Knowledge Graph")
        kg_form = QFormLayout(kg)
        self.graph_enabled = QCheckBox("Extract entities + relationships during AI indexing")
        kg_form.addRow(self.graph_enabled)
        outer.addWidget(kg)

        ag = QGroupBox("Agent")
        ag_form = QFormLayout(ag)
        self.agent_max_steps = QSpinBox()
        self.agent_max_steps.setRange(1, 20)
        self.agent_timeout = QSpinBox()
        self.agent_timeout.setRange(10, 600)
        self.agent_timeout.setSuffix(" s")
        self.agent_enabled = QCheckBox("Enable Agent Mode")
        ag_form.addRow("Maximum steps", self.agent_max_steps)
        ag_form.addRow("Timeout", self.agent_timeout)
        ag_form.addRow(self.agent_enabled)
        outer.addWidget(ag)

        outer.addStretch(1)
        return w

    # ------------------------------------------------------------------ #
    # Batch 5 — Organization & Knowledge Management (§3.5)
    # ------------------------------------------------------------------ #
    def _batch5_tab(self) -> QWidget:
        w = QWidget()
        outer = QVBoxLayout(w)

        dup = QGroupBox("Duplicates & Similarity")
        dup_form = QFormLayout(dup)
        self.dup_empty_visible = QCheckBox("Show empty-content duplicate groups")
        self.near_threshold = QSpinBox()
        self.near_threshold.setRange(50, 99)
        self.near_threshold.setSuffix("%")
        self.similar_threshold = QSpinBox()
        self.similar_threshold.setRange(30, 99)
        self.similar_threshold.setSuffix("%")
        self.max_related = QSpinBox()
        self.max_related.setRange(3, 50)
        dup_form.addRow(self.dup_empty_visible)
        dup_form.addRow("Near-duplicate threshold", self.near_threshold)
        dup_form.addRow("Similar-file threshold", self.similar_threshold)
        dup_form.addRow("Max related results", self.max_related)
        outer.addWidget(dup)

        cls = QGroupBox("Classification & Tagging")
        cls_form = QFormLayout(cls)
        self.classify_batch = QSpinBox()
        self.classify_batch.setRange(1, 100)
        self.classify_batch.setSuffix(" files")
        cls_form.addRow("Classification batch size", self.classify_batch)
        outer.addWidget(cls)

        sug = QGroupBox("Organization Suggestions")
        sug_form = QFormLayout(sug)
        self.suggestion_conf = QSpinBox()
        self.suggestion_conf.setRange(0, 99)
        self.suggestion_conf.setSuffix("%")
        sug_form.addRow("Minimum confidence", self.suggestion_conf)
        outer.addWidget(sug)

        dash = QGroupBox("Knowledge Dashboard")
        dash_form = QFormLayout(dash)
        self.dash_auto_refresh = QCheckBox("Auto-refresh dashboard on open")
        dash_form.addRow(self.dash_auto_refresh)
        outer.addWidget(dash)

        outer.addStretch(1)
        return w

    # ------------------------------------------------------------------ #
    # Batch 6 — Captions, Folder Classification, Organization (§13)
    # ------------------------------------------------------------------ #
    def _batch6_tab(self) -> QWidget:
        w = QWidget()
        outer = QVBoxLayout(w)

        cap = QGroupBox("Image Captions")
        cap_form = QFormLayout(cap)
        self.caption_model = QLineEdit()
        self.caption_enabled = QCheckBox("Enable 'Caption Image' action")
        cap_form.addRow("Vision model", self.caption_model)
        cap_form.addRow(self.caption_enabled)
        outer.addWidget(cap)

        dup = QGroupBox("Duplicate Removal Suggestions")
        dup_form = QFormLayout(dup)
        self.removal_conf = QSpinBox()
        self.removal_conf.setRange(40, 99)
        self.removal_conf.setSuffix("%")
        dup_form.addRow("Minimum confidence", self.removal_conf)
        outer.addWidget(dup)

        org = QGroupBox("Folder Organization")
        org_form = QFormLayout(org)
        self.folder_org_enabled = QCheckBox("Suggest folder moves (approval required)")
        self.folder_cls_recursive = QCheckBox("Folder classification includes subfolders")
        org_form.addRow(self.folder_org_enabled)
        org_form.addRow(self.folder_cls_recursive)
        outer.addWidget(org)

        outer.addStretch(1)
        return w

    # ------------------------------------------------------------------ #
    # Batch 7 — Image intelligence, metadata tools, timeline, rename (§18)
    # ------------------------------------------------------------------ #
    def _batch7_tab(self) -> QWidget:
        w = QWidget()
        outer = QVBoxLayout(w)

        img = QGroupBox("Image Intelligence")
        img_form = QFormLayout(img)
        self.quality_enabled = QCheckBox("Enable image quality analysis")
        self.object_enabled = QCheckBox("Enable object detection")
        self.object_model = QLineEdit()
        self.object_threshold = QSpinBox()
        self.object_threshold.setRange(10, 90)
        self.object_threshold.setSuffix("%")
        self.reverse_threshold = QSpinBox()
        self.reverse_threshold.setRange(10, 99)
        self.reverse_threshold.setSuffix("%")
        self.image_filter_threshold = QSpinBox()
        self.image_filter_threshold.setRange(10, 99)
        self.image_filter_threshold.setSuffix("%")
        img_form.addRow(self.quality_enabled)
        img_form.addRow(self.object_enabled)
        img_form.addRow("Object detection model", self.object_model)
        img_form.addRow("Object confidence threshold", self.object_threshold)
        img_form.addRow("Reverse-image min similarity", self.reverse_threshold)
        img_form.addRow("Image-filter semantic threshold", self.image_filter_threshold)
        outer.addWidget(img)

        folder = QGroupBox("Folder Statistics")
        folder_form = QFormLayout(folder)
        self.folder_summary_enabled = QCheckBox("Enable AI folder summary")
        self.folder_summary_model = QLineEdit()
        folder_form.addRow(self.folder_summary_enabled)
        folder_form.addRow("Folder summary model", self.folder_summary_model)
        outer.addWidget(folder)

        rename = QGroupBox("Automatic Renaming")
        rename_form = QFormLayout(rename)
        self.rename_pattern = QLineEdit()
        rename_form.addRow(
            "Name pattern ({category}/{title}/{tag}/{type})", self.rename_pattern
        )
        outer.addWidget(rename)

        outer.addStretch(1)
        return w

    # ------------------------------------------------------------------ #
    def load_settings(self) -> None:
        self.startup_path.setText(self.config.get("general.startup_path", ""))
        self.single_click.setChecked(self.config.get("general.single_click_open", False))
        self.confirm_delete.setChecked(self.config.get("general.confirm_delete", True))
        self.inactivity_reminder_cb.setChecked(self.config.get("general.inactivity_reminder_enabled", False))
        self.inactivity_threshold_spin.setValue(self.config.get("general.inactivity_threshold_days", 14))
        self.inactivity_folder_edit.setText(self.config.get("general.inactivity_reminder_folder", ""))


        self.theme_combo.setCurrentText(self.config.get("appearance.theme", "dark"))
        self.view_combo.setCurrentText(self.config.get("explorer.default_view", "list"))
        self.show_hidden.setChecked(self.config.get("explorer.show_hidden", False))
        self.thumbnails.setChecked(self.config.get("explorer.thumbnails", True))

        self.db_path.setText(self.config.get("database.path", ""))
        self.max_threads.setValue(self.config.get("performance.max_threads", 4))
        self.cache_size.setValue(self.config.get("performance.cache_size_mb", 256))
        self.cpu_threads.setValue(int(self.config.get("compute.cpu_threads", 0) or 0))
        self.embed_batch.setValue(int(self.config.get("compute.embed_batch", 32) or 32))
        self.backend_combo.setCurrentText(self.config.get("compute.backend", "auto"))
        self.gpu_enabled.setChecked(bool(self.config.get("compute.gpu_enabled", True)))
        self.igpu_enabled.setChecked(bool(self.config.get("compute.allow_igpu", True)))
        self.low_resource.setChecked(bool(self.config.get("compute.low_resource_mode", False)))

        self.conv_scope.setCurrentText(self.config.get("batch4.default_scope", "folder"))
        self.conv_history_chars.setValue(self.config.get("batch4.history_chars", 6000))
        self.conv_turns.setValue(self.config.get("batch4.history_turns", 12))
        self.top_k.setValue(self.config.get("batch4.top_k", 5))
        self.threshold.setValue(int(self.config.get("batch4.threshold", 0.3) * 100))
        self.graph_enabled.setChecked(self.config.get("batch4.graph_enabled", True))
        self.agent_max_steps.setValue(self.config.get("batch4.agent_max_steps", 8))
        self.agent_timeout.setValue(self.config.get("batch4.agent_timeout_s", 300))
        self.agent_enabled.setChecked(self.config.get("batch4.agent_enabled", True))

        self.dup_empty_visible.setChecked(self.config.get("batch5.empty_duplicates_visible", True))
        self.near_threshold.setValue(int(self.config.get("batch5.near_duplicate_threshold", 0.90) * 100))
        self.similar_threshold.setValue(int(self.config.get("batch5.similar_file_threshold", 0.75) * 100))
        self.max_related.setValue(self.config.get("batch5.max_related_results", 10))
        self.classify_batch.setValue(self.config.get("batch5.classification_batch_size", 10))
        self.suggestion_conf.setValue(int(self.config.get("batch5.suggestion_min_confidence", 0.5) * 100))
        self.dash_auto_refresh.setChecked(self.config.get("batch5.dashboard_refresh_auto", True))

        self.caption_model.setText(self.config.get("batch6.caption_model", "moondream:latest"))
        self.caption_enabled.setChecked(self.config.get("batch6.caption_enabled", True))
        self.removal_conf.setValue(int(self.config.get("batch6.duplicate_removal_min_confidence", 0.70) * 100))
        self.folder_org_enabled.setChecked(self.config.get("batch6.folder_organization_enabled", True))
        self.folder_cls_recursive.setChecked(self.config.get("batch6.folder_classification_recursive", True))

        self.quality_enabled.setChecked(self.config.get("batch7.image_quality_enabled", True))
        self.object_enabled.setChecked(self.config.get("batch7.object_detection_enabled", True))
        self.object_model.setText(self.config.get("batch7.object_detection_model", "moondream:latest"))
        self.object_threshold.setValue(int(self.config.get("batch7.object_detection_threshold", 0.40) * 100))
        self.reverse_threshold.setValue(int(self.config.get("batch7.reverse_image_min_similarity", 0.55) * 100))
        self.image_filter_threshold.setValue(int(self.config.get("batch7.image_filter_threshold", 0.45) * 100))
        self.folder_summary_enabled.setChecked(self.config.get("batch7.folder_summary_enabled", True))
        self.folder_summary_model.setText(self.config.get("batch7.folder_summary_model", "qwen-local:latest"))
        self.rename_pattern.setText(self.config.get("batch7.rename_pattern", "{category}_{title}"))

        for name, cb in self.plugin_checks.items():
            plugin = next(
                (p for p in self.repository.list_plugins() if p.name == name), None
            )
            if plugin:
                cb.setChecked(plugin.enabled)

    def apply_settings(self) -> None:
        prev_theme = self.config.get("appearance.theme")

        self.config.set("general.startup_path", self.startup_path.text())
        self.config.set("general.single_click_open", self.single_click.isChecked())
        self.config.set("general.confirm_delete", self.confirm_delete.isChecked())
        self.config.set("general.inactivity_reminder_enabled", self.inactivity_reminder_cb.isChecked())
        self.config.set("general.inactivity_threshold_days", self.inactivity_threshold_spin.value())
        self.config.set("general.inactivity_reminder_folder", self.inactivity_folder_edit.text().strip())

        theme = self.theme_combo.currentText()
        self.config.set("appearance.theme", theme)

        self.config.set("explorer.default_view", self.view_combo.currentText())
        self.config.set("explorer.show_hidden", self.show_hidden.isChecked())
        self.config.set("explorer.thumbnails", self.thumbnails.isChecked())

        self.config.set("performance.max_threads", self.max_threads.value())
        self.config.set("performance.cache_size_mb", self.cache_size.value())
        self.config.set("compute.cpu_threads", self.cpu_threads.value())
        self.config.set("compute.embed_batch", self.embed_batch.value())
        self.config.set("compute.backend", self.backend_combo.currentText())
        self.config.set("compute.gpu_enabled", self.gpu_enabled.isChecked())
        self.config.set("compute.allow_igpu", self.igpu_enabled.isChecked())
        self.config.set("compute.low_resource_mode", self.low_resource.isChecked())

        self.config.set("batch4.default_scope", self.conv_scope.currentText())
        self.config.set("batch4.history_chars", self.conv_history_chars.value())
        self.config.set("batch4.history_turns", self.conv_turns.value())
        self.config.set("batch4.top_k", self.top_k.value())
        self.config.set("batch4.threshold", self.threshold.value() / 100.0)
        self.config.set("batch4.graph_enabled", self.graph_enabled.isChecked())
        self.config.set("batch4.agent_max_steps", self.agent_max_steps.value())
        self.config.set("batch4.agent_timeout_s", self.agent_timeout.value())
        self.config.set("batch4.agent_enabled", self.agent_enabled.isChecked())

        self.config.set("batch5.empty_duplicates_visible", self.dup_empty_visible.isChecked())
        self.config.set("batch5.near_duplicate_threshold", self.near_threshold.value() / 100.0)
        self.config.set("batch5.similar_file_threshold", self.similar_threshold.value() / 100.0)
        self.config.set("batch5.max_related_results", self.max_related.value())
        self.config.set("batch5.classification_batch_size", self.classify_batch.value())
        self.config.set("batch5.suggestion_min_confidence", self.suggestion_conf.value() / 100.0)
        self.config.set("batch5.dashboard_refresh_auto", self.dash_auto_refresh.isChecked())

        self.config.set("batch6.caption_model", self.caption_model.text().strip())
        self.config.set("batch6.caption_enabled", self.caption_enabled.isChecked())
        self.config.set("batch6.duplicate_removal_min_confidence", self.removal_conf.value() / 100.0)
        self.config.set("batch6.folder_organization_enabled", self.folder_org_enabled.isChecked())
        self.config.set("batch6.folder_classification_recursive", self.folder_cls_recursive.isChecked())

        self.config.set("batch7.image_quality_enabled", self.quality_enabled.isChecked())
        self.config.set("batch7.object_detection_enabled", self.object_enabled.isChecked())
        self.config.set("batch7.object_detection_model", self.object_model.text().strip())
        self.config.set("batch7.object_detection_threshold", self.object_threshold.value() / 100.0)
        self.config.set("batch7.reverse_image_min_similarity", self.reverse_threshold.value() / 100.0)
        self.config.set("batch7.image_filter_threshold", self.image_filter_threshold.value() / 100.0)
        self.config.set("batch7.folder_summary_enabled", self.folder_summary_enabled.isChecked())
        self.config.set("batch7.folder_summary_model", self.folder_summary_model.text().strip())
        self.config.set("batch7.rename_pattern", self.rename_pattern.text().strip() or "{category}_{title}")

        # Mirror into the database settings table.
        if self.repository is not None:
            for key in (
                "general.startup_path",
                "general.single_click_open",
                "general.confirm_delete",
                "appearance.theme",
                "explorer.default_view",
                "explorer.show_hidden",
                "explorer.thumbnails",
                "performance.max_threads",
                "performance.cache_size_mb",
                "compute.cpu_threads",
                "compute.embed_batch",
                "compute.backend",
                "compute.gpu_enabled",
                "compute.allow_igpu",
                "compute.low_resource_mode",
            ):
                self.repository.set_setting(key, str(self.config.get(key)))

        # Apply theme live if it changed.
        if theme != prev_theme:
            self.theme_engine.apply(theme)

        # Persist plugin enable/disable state.
        if self.repository is not None:
            for name, cb in self.plugin_checks.items():
                self.repository.set_plugin_enabled(name, cb.isChecked())

        # Notify the rest of the app.
        self.bus.settings_changed.emit("appearance.theme")
        self.bus.settings_changed.emit("explorer.default_view")
        self.bus.settings_changed.emit("performance.max_threads")
        self.bus.settings_changed.emit("performance.cache_size_mb")
        self.bus.settings_changed.emit("compute.cpu_threads")
        self.bus.settings_changed.emit("compute.embed_batch")
        self.bus.settings_changed.emit("compute.backend")
        self.bus.settings_changed.emit("compute.gpu_enabled")
        self.bus.settings_changed.emit("compute.allow_igpu")
        self.bus.settings_changed.emit("compute.low_resource_mode")
        self.accept()
