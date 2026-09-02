"""Preview panel.

Renders a preview of the currently selected file based on its type: images,
PDF, text, audio metadata, video thumbnail and generic file properties.
A reserved "AI Insights" section (Summary / Keywords / OCR / Related files)
is shown disabled for future extensions.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile

from PySide6.QtCore import QPointF, QUrl, Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QWidget,
    QHBoxLayout,
    QVBoxLayout,
    QLabel,
    QPlainTextEdit,
    QGroupBox,
    QFormLayout,
    QStackedWidget,
    QListWidget,
    QPushButton,
    QScrollArea,
)

try:  # QtPdf is bundled with PySide6 but guard for minimal installs.
    from PySide6.QtPdf import QPdfDocument
    from PySide6.QtPdfWidgets import QPdfView

    _HAS_PDF = True
except Exception:  # pragma: no cover
    _HAS_PDF = False

try:  # QtMultimedia for audio/video playback with timestamp seeking.
    from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
    from PySide6.QtMultimediaWidgets import QVideoWidget

    _HAS_MEDIA = True
except Exception:  # pragma: no cover
    _HAS_MEDIA = False


_MAX_TEXT_BYTES = 1_000_000
_AUDIO_EXT = {".mp3", ".flac", ".ogg", ".wav", ".m4a", ".aac"}
_VIDEO_EXT = {".mp4", ".mkv", ".mov", ".avi", ".webm", ".m4v"}
_IMAGE_EXT = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".svg", ".webp"}
_TEXT_EXT = {".txt", ".md", ".py", ".json", ".yaml", ".yml", ".csv", ".log", ".xml", ".ini", ".toml"}


class PreviewPanel(QWidget):
    def __init__(self, bus, task_manager=None, cache=None, plugin_registry=None, parent=None, database=None) -> None:
        super().__init__(parent)
        self.bus = bus
        self.task_manager = task_manager
        self.cache = cache
        self.plugin_registry = plugin_registry
        self.current_path = ""
        self.database = database

        self.info_label = QLabel("No selection")
        self.info_label.setWordWrap(True)

        # Content stack ------------------------------------------------- #
        self.image_label = QLabel()
        self.image_label.setAlignment(Qt.AlignCenter)
        self.image_label.setText("")
        self.image_label.setMaximumHeight(300)

        self.text_edit = QPlainTextEdit()
        self.text_edit.setReadOnly(True)

        self.pdf_view = QPdfView() if _HAS_PDF else QLabel("PDF preview unavailable")
        self.pdf_doc: "QPdfDocument | None" = None

        self.info_area = QLabel("")
        self.info_area.setAlignment(Qt.AlignTop)
        self.info_area.setWordWrap(True)

        # Metadata area (used by handlers, shown in stack) --------------- #
        self.metadata_area = QLabel("")
        self.metadata_area.setAlignment(Qt.AlignTop)
        self.metadata_area.setWordWrap(True)
        self.metadata_label = QLabel("Metadata")
        self.metadata_group = QGroupBox("Indexed Metadata")

        # Extracted Text area -------------------------------------------------- #
        self.extracted_text_area = QWidget()
        container_layout = QVBoxLayout(self.extracted_text_area)
        container_layout.setContentsMargins(0, 0, 0, 0)
        container_layout.setSpacing(4)

        header_layout = QHBoxLayout()
        self.copy_text_button = QPushButton("📋 Copy to Clipboard")
        self.copy_text_button.setFixedWidth(150)
        self.copy_text_button.setFixedHeight(24)
        self.copy_text_button.clicked.connect(self._copy_extracted_text)
        header_layout.addWidget(self.copy_text_button)
        header_layout.addStretch(1)
        container_layout.addLayout(header_layout)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        self.extracted_text_content = QLabel("")
        self.extracted_text_content.setWordWrap(True)
        self.extracted_text_content.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.extracted_text_content.setAlignment(Qt.AlignTop)
        scroll.setWidget(self.extracted_text_content)
        container_layout.addWidget(scroll)

        # Media players (lazy — created only when an audio/video is played) #
        self.audio_player_widget = QWidget()
        self.video_player_widget = QWidget()
        self._media_player = None
        self._audio_output = None
        self._media_slider = None
        self._media_time_label = None
        self._media_play_button = None
        self._media_is_video = False
        self._video_widget = None
        self._media_controls_built = False

        # Content stack — shows ONE view at a time ---------------------- #
        self.stack = QStackedWidget()
        self.stack.addWidget(self.image_label)         # 0 - images
        self.stack.addWidget(self.text_edit)           # 1 - text files
        self.stack.addWidget(self.pdf_view)            # 2 - PDF
        self.stack.addWidget(self.info_area)           # 3 - properties/audio
        self.stack.addWidget(self.extracted_text_area) # 4 - extracted text
        self.stack.addWidget(self.metadata_area)       # 5 - metadata
        self.stack.addWidget(self.audio_player_widget) # 6 - audio player
        self.stack.addWidget(self.video_player_widget) # 7 - video player

        # Toolbar with action buttons ----------------------------------- #
        self.toolbar_layout = QHBoxLayout()
        self.toolbar_layout.setContentsMargins(0, 2, 0, 2)
        self.extracted_text_button = QPushButton("Extracted Text")
        self.extracted_text_button.setFixedHeight(26)
        self.extracted_text_button.clicked.connect(self._show_extracted_text_tab_handler)
        self.toolbar_layout.addWidget(self.extracted_text_button)
        self.toolbar_layout.addStretch()

        # File details — fixed section showing basic file info ---------- #
        self.file_details_label = QLabel("")
        self.file_details_label.setWordWrap(True)
        self.file_details_label.setAlignment(Qt.AlignTop)
        self.file_details_label.setFixedHeight(120)
        self.file_details_label.setStyleSheet(
            "QLabel { background: palette(base); border: 1px solid palette(mid); "
            "border-radius: 3px; padding: 4px; font-size: 11px; }"
        )

        # Root layout — clean, fixed, NO splitter, NO duplicate info ---- #
        root = QVBoxLayout(self)
        root.setContentsMargins(4, 4, 4, 4)
        root.setSpacing(4)
        root.addWidget(self.info_label)            # File name (fixed height)
        root.addWidget(self.stack, 1)              # Preview content (fills space)
        root.addWidget(self.file_details_label)    # File details (fixed 60px)
        root.addLayout(self.toolbar_layout)        # Button bar (fixed 26px)

        # AI Insights placeholder (hidden, kept for API compatibility) -- #
        self.ai_group = QGroupBox("AI Insights")
        ai_layout = QVBoxLayout()
        for cap in ("Summary", "Keywords", "OCR", "Related files"):
            label = QLabel(f"• {cap}")
            label.setEnabled(False)
            ai_layout.addWidget(label)
        self.ai_group.setLayout(ai_layout)
        self.ai_group.setEnabled(False)
        self.ai_group.setVisible(False)

    # ------------------------------------------------------------------ #
    def show_file(self, path: str) -> None:
        if not path or not os.path.exists(path):
            self.clear()
            return
        self.current_path = path
        ext = os.path.splitext(path)[1].lower()
        self.info_label.setText(f"<b>{os.path.basename(path)}</b>")

        # Populate fixed file details section
        self.file_details_label.setText(self._file_props(path))

        if os.path.isdir(path):
            self._show_properties(path)
        elif ext in _IMAGE_EXT:
            self._show_image(path)
        elif ext == ".pdf":
            self._show_pdf(path)
        elif ext in _TEXT_EXT:
            self._show_text(path)
        elif ext in _AUDIO_EXT:
            self._show_audio(path)
        elif ext in _VIDEO_EXT:
            self._show_video(path)
        else:
            self._show_properties(path)

        # Extension point: let plugins react to the rendered preview.
        if self.plugin_registry is not None:
            self.plugin_registry.invoke_hook("preview_render", path, self)

    def clear(self) -> None:
        self.current_path = ""
        if self.pdf_doc is not None:
            self.pdf_doc.close()
            self.pdf_doc = None
        self._stop_media()
        self.info_label.setText("No selection")
        self.file_details_label.setText("")
        self.stack.setCurrentWidget(self.info_area)
        self.info_area.setText("")

    # ------------------------------------------------------------------ #
    def _show_image(self, path: str) -> None:
        pixmap = QPixmap(path)
        if pixmap.isNull():
            self._show_properties(path)
            return
        # Cap image to max 300px height, 400px width to prevent overflow
        max_w, max_h = 400, 300
        self.image_label.setPixmap(
            pixmap.scaled(max_w, max_h, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        )
        self.stack.setCurrentWidget(self.image_label)

    def _show_text(self, path: str) -> None:
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as fh:
                data = fh.read(_MAX_TEXT_BYTES)
        except OSError as exc:
            self.info_area.setText(f"Cannot read file: {exc}")
            self.stack.setCurrentWidget(self.info_area)
            return
        self.text_edit.setPlainText(data)
        self.stack.setCurrentWidget(self.text_edit)

    def _show_pdf(self, path: str) -> None:
        info = self._file_props(path)
        self.info_area.setText(
            f"{info}\n\n📄 PDF Document\nDouble-click or click 'Open File' to view in your default PDF application."
        )
        self.stack.setCurrentWidget(self.info_area)


    def _show_audio(self, path: str) -> None:
        info = self._file_props(path)
        tags = {}
        try:
            from mutagen import File as MutagenFile

            audio = MutagenFile(path)
            if audio is not None:
                tags = {k: str(v) for k, v in (audio.tags or {}).items()}
        except Exception:
            tags = {}
        rows = "\n".join(f"{k}: {v}" for k, v in list(tags.items())[:12]) or "(no tags)"
        self.info_area.setText(f"{info}\n\nAudio metadata:\n{rows}")
        self.stack.setCurrentWidget(self.info_area)

    def _show_video(self, path: str) -> None:
        info = self._file_props(path)
        key = f"thumb:{path}:{os.path.getmtime(path)}:{os.path.getsize(path)}"

        # Cache hit ----------------------------------------------------- #
        if self.cache is not None:
            cached = self.cache.get(key)
            if cached:
                self._show_thumb_bytes(cached, info)
                return

        # Off-thread extraction (M7) ------------------------------------ #
        if self.task_manager is not None:
            self.bus.status_message.emit("Generating thumbnail...")

            def _done(result):
                if result:
                    if self.cache is not None:
                        self.cache.set(key, result)
                    self._show_thumb_bytes(result, info)
                else:
                    self.info_area.setText(f"{info}\n\n(thumbnail unavailable)")
                    self.stack.setCurrentWidget(self.info_area)

            self.task_manager.submit(
                self._extract_video_frame_task,
                "thumbnail",
                path=path,
                on_finished=_done,
            )
            return

        # Synchronous fallback (no task manager, e.g. tests) ------------ #
        frame = self._extract_video_frame(path)
        if frame and os.path.exists(frame):
            with open(frame, "rb") as fh:
                data = fh.read()
            try:
                os.unlink(frame)
            except OSError:
                pass
            self._show_thumb_bytes(data, info)
        else:
            self.info_area.setText(f"{info}\n\n(thumbnail unavailable)")
            self.stack.setCurrentWidget(self.info_area)

    def _show_thumb_bytes(self, data: bytes, info: str) -> None:
        import tempfile

        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            out = f.name
            f.write(data)
        pixmap = QPixmap(out)
        try:
            os.unlink(out)
        except OSError:
            pass
        if not pixmap.isNull():
            self.image_label.setPixmap(
                pixmap.scaled(400, 300, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            )
            self.stack.setCurrentWidget(self.image_label)
        else:
            self.info_area.setText(f"{info}\n\n(thumbnail unavailable)")
            self.stack.setCurrentWidget(self.info_area)

    @staticmethod
    def _extract_video_frame_task(progress, cancel, path: str):
        if cancel is not None and cancel.is_set():
            return None
        frame = PreviewPanel._extract_video_frame(path)
        if cancel is not None and cancel.is_set():
            return None
        if frame and os.path.exists(frame):
            with open(frame, "rb") as fh:
                data = fh.read()
            try:
                os.unlink(frame)
            except OSError:
                pass
            return data
        return None

    def _show_properties(self, path: str) -> None:
        self.info_area.setText(self._file_props(path))
        self.stack.setCurrentWidget(self.info_area)

    # ------------------------------------------------------------------ #
    def _file_props(self, path: str) -> str:
        from PySide6.QtCore import QFileInfo

        fi = QFileInfo(path)
        size = fi.size()
        modified = fi.lastModified().toString()
        kind = "Folder" if fi.isDir() else "File"
        return (
            f"Name: {fi.fileName()}\n"
            f"Path: {fi.absoluteFilePath()}\n"
            f"Type: {kind}\n"
            f"Size: {size:,} bytes\n"
            f"Modified: {modified}"
        )

    def _get_metadata_from_index(self, path: str) -> str | None:
        """Get metadata for a file from SQLite index if available."""
        try:
            if self.database is None:
                return None

            # Look up the file in the indexed files
            from services.sqlite_indexer import IndexedFile

            session = self.database.session()
            records = session.query(IndexedFile).all()
            record = None
            for r in records:
                if getattr(r, 'absolute_path', None) == path:
                    record = r
                    break

            if not record:
                return None

            # Format metadata as readable text
            metadata_lines = []
            if getattr(record, 'filename', None):
                metadata_lines.append(f"Filename: {record.filename}")
            if getattr(record, 'absolute_path', None):
                metadata_lines.append(f"Path: {record.absolute_path}")
            if getattr(record, 'mime_type', None):
                metadata_lines.append(f"MIME: {record.mime_type}")
            if getattr(record, 'extension', None):
                metadata_lines.append(f"Extension: {record.extension}")
            if getattr(record, 'size', None) is not None:
                metadata_lines.append(f"Size: {record.size} bytes")
            if getattr(record, 'created_date', None):
                metadata_lines.append(f"Created: {record.created_date}")
            if getattr(record, 'modified_date', None):
                metadata_lines.append(f"Modified: {record.modified_date}")
            if getattr(record, 'checksum', None):
                metadata_lines.append(f"Checksum: {record.checksum}")
            if getattr(record, 'owner', None):
                metadata_lines.append(f"Owner: {record.owner}")

            if metadata_lines:
                return "\n".join(metadata_lines)
            return None
        except Exception:
            # If metadata lookup fails, fallback to standard properties
            return None

    def _get_extracted_text_from_index(self, path: str) -> str | None:
        """Get extracted text for a file from SQLite index if available."""
        try:
            if self.database is None:
                return None

            from services.sqlite_indexer import IndexedFile

            # Look up the file in the indexed files
            session = self.database.session()
            records = session.query(IndexedFile).all()
            record = None
            for r in records:
                if getattr(r, 'absolute_path', None) == path:
                    record = r
                    break

            if not record:
                return None

            # Return extracted text if available
            extracted = getattr(record, 'extracted_text', None)
            if extracted:
                return extracted
            return None
        except Exception:
            # If text extraction fails, fallback to standard text extraction
            return None

    @staticmethod
    def _clean_image_ocr_text(text: str) -> str:
        """Extract only the raw OCR text segment from image content blocks, ignoring AI captions."""
        if not text:
            return ""
        if "[OCR Text]" in text:
            parts = text.split("[Image Caption]")
            return parts[0].replace("[OCR Text]", "").strip()
        if "[Image Caption]" in text:
            return ""
        return text.strip()

    def _show_extracted_text_tab(self, path: str) -> None:
        """Show the extracted text tab from SQLite index, with fallback to on-the-fly extraction."""
        extracted_text = self._get_extracted_text_from_index(path)
        ext = os.path.splitext(path)[1].lower() if path else ""

        if extracted_text:
            if ext in _IMAGE_EXT:
                extracted_text = self._clean_image_ocr_text(extracted_text)
            if extracted_text and extracted_text.strip():
                # Use extracted text area for display
                self.extracted_text_content.setText(extracted_text)
                self.info_label.setText(f"<b>Extracted Text (from SQLite)</b>")
                self.stack.setCurrentWidget(self.extracted_text_area)
                return

        # Try on-the-fly content/text extraction using UniversalContentEngine
        if path and os.path.isfile(path):
            # Run on-the-fly for images, PDFs, audio/video, or documents
            supported_exts = _IMAGE_EXT | {".pdf"} | _TEXT_EXT | _AUDIO_EXT | _VIDEO_EXT | {
                ".docx", ".xlsx", ".pptx", ".csv", ".xml", ".json", ".html"
            }
            if ext in supported_exts:
                self.extracted_text_content.setText("Extracting text via AI / OCR on-the-fly... Please wait...")
                self.info_label.setText("<b>Extracting Text...</b>")
                self.stack.setCurrentWidget(self.extracted_text_area)

                def _do_extract(progress_callback, cancel_event, file_path):
                    try:
                        from engines.content_engine import UniversalContentEngine
                        engine = UniversalContentEngine()
                        return engine.extract_full_text(file_path)
                    except Exception as e:
                        return f"Extraction failed: {e}"

                def _finished(result):
                    # Make sure the user hasn't switched to a different file in the meantime
                    if self.current_path == path:
                        if ext in _IMAGE_EXT and result:
                            result = self._clean_image_ocr_text(result)
                        if result and result.strip():
                            self.extracted_text_content.setText(result)
                            self.info_label.setText("<b>Extracted Text (OCR / On-the-fly)</b>")
                        else:
                            self.extracted_text_content.setText("(No text characters found in this image)")
                            self.info_label.setText("<b>Extracted Text</b>")

                if self.task_manager is not None:
                    self.task_manager.submit(
                        _do_extract,
                        "on_the_fly_ocr",
                        None,
                        path,
                        on_finished=_finished,
                    )
                    return
                else:
                    # Synchronous fallback if no task manager
                    res = _do_extract(None, None, path)
                    _finished(res)
                    return

        # Fallback: for unsupported formats or missing data, show properties
        ext = os.path.splitext(path)[1].lower() if path else ""
        if ext in _TEXT_EXT:
            self._show_text(path)
        elif ext == ".pdf":
            self._show_pdf(path)
        else:
            self._show_properties(path)

    def _show_extracted_text_tab_handler(self) -> None:
        """Handler for the extracted text tab button."""
        if self.current_path:
            extracted_text = self._get_extracted_text_from_index(self.current_path)
            ext = os.path.splitext(self.current_path)[1].lower()
            if extracted_text:
                if ext in _IMAGE_EXT:
                    extracted_text = self._clean_image_ocr_text(extracted_text)
                if extracted_text and extracted_text.strip():
                    self.extracted_text_content.setText(extracted_text)
                    self.info_label.setText(f"<b>Extracted Text (from SQLite)</b>")
                    self.stack.setCurrentWidget(self.extracted_text_area)
                    return
            self._show_extracted_text_tab(self.current_path)

    def _show_metadata_tab(self, path: str) -> None:
        """Show the metadata tab from SQLite index."""
        metadata = self._get_metadata_from_index(path)

        if metadata:
            b5 = self._batch5_summary(path)
            if b5:
                metadata += "\n\n" + b5
            self.metadata_area.setText(metadata)
            self.metadata_label.setText(f"<b>Metadata (from SQLite)</b>")
            self.stack.setCurrentWidget(self.metadata_area)
        else:
            # Fallback to standard properties
            self._show_properties(path)

    # ------------------------------------------------------------------ #
    # Batch 5 — organization summary in the metadata tab (§17)
    # ------------------------------------------------------------------ #
    def _batch5_summary(self, path: str) -> str:
        """Category / tags / duplicate status for a file, if available.

        Returns an empty string when nothing is classified/tagged so the
        metadata tab never shows misleading placeholders. Reads straight
        from SQLite (no engine dependencies) so it stays cheap and safe.
        """
        if not path or self.database is None:
            return ""
        try:
            from services.file_identity import calculate_sha256_safe

            file_hash = calculate_sha256_safe(path)
            if not file_hash:
                return ""
            from database.models import AIAnalysis

            lines: list[str] = []
            with self.database.session() as session:
                row = (
                    session.query(AIAnalysis)
                    .filter(AIAnalysis.file_hash == file_hash)
                    .first()
                )
                if row is not None and row.normalized_category:
                    lines.append(f"Category: {row.normalized_category}")
                if row is not None and row.normalized_tags:
                    try:
                        import json
                        tags = json.loads(row.normalized_tags) or []
                    except Exception:
                        tags = []
                    if tags:
                        lines.append("Tags: " + ", ".join(tags))

            if not lines:
                return ""
            return "\n".join(lines)
        except Exception:
            return ""

    def _show_metadata_tab_handler(self) -> None:
        """Handler for the metadata tab button."""
        if self.current_path:
            metadata = self._get_metadata_from_index(self.current_path)
            if metadata:
                self.metadata_area.setText(metadata)
                self.metadata_label.setText(f"<b>Metadata (from Index)</b>")
                self.stack.setCurrentWidget(self.metadata_area)
            else:
                self._show_metadata_tab(self.current_path)

    def _extract_video_frame(self, path: str) -> str | None:
        if not shutil.which("ffmpeg"):
            return None
        fd, out = tempfile.mkstemp(suffix=".png")
        os.close(fd)
        try:
            subprocess.run(
                ["ffmpeg", "-y", "-ss", "1", "-i", path, "-vframes", "1", "-f", "image2", out],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=15,
                check=False,
            )
        except Exception:
            return None
        return out if os.path.getsize(out) > 0 else None

    # ------------------------------------------------------------------ #
    # Evidence navigation support (Batch 3)
    # ------------------------------------------------------------------ #
    def jump_to_page(self, page: int) -> None:
        """Open the current PDF at a specific 1-based page (evidence nav)."""
        if not self.current_path or not os.path.splitext(self.current_path)[1].lower() == ".pdf":
            return
        if not _HAS_PDF or not hasattr(self.pdf_view, "pageNavigator") or self.pdf_doc is None:
            return
        try:
            total = self.pdf_doc.pageCount()
            page = max(1, min(int(page), total)) if total else int(page)
            self.pdf_view.pageNavigator().jump(page - 1, QPointF(0, 0))
        except Exception:
            # Navigation widget not ready; nothing critical.
            pass

    def show_source_block(self, path: str, source_type: str, source_index: int) -> None:
        """Show the exact extracted content block (slide/section) in the preview.

        Batch 4 M0-05 — evidence navigation for PPTX slides and DOCX sections.
        Renders the targeted block's text (with its source label) in the
        extracted-text area so the user lands on the exact location.
        """
        try:
            from engines.content_engine import UniversalContentEngine
            blocks = UniversalContentEngine().extract(path)
        except Exception:
            blocks = []
        if not blocks:
            self._show_properties(path)
            return

        target = None
        for b in blocks:
            if (b.source_type == source_type and b.source_index == source_index):
                target = b
                break
        if target is None and blocks:
            target = blocks[0]

        label = getattr(target, "source_label", "") or os.path.basename(path)
        self.extracted_text_content.setText(
            f"<b>{label}</b>\n\n{target.text}" if label else target.text
        )
        self.info_label.setText(f"<b>{os.path.basename(path)} — {label}</b>")
        self.stack.setCurrentWidget(self.extracted_text_area)

    def jump_to_slide(self, path: str, slide_index: int) -> None:
        """Open a PPTX and jump to a specific slide (evidence nav)."""
        self.current_path = path
        self.info_label.setText(f"<b>{os.path.basename(path)}</b>")
        self.file_details_label.setText(self._file_props(path))
        self.show_source_block(path, "slide", slide_index)

    def jump_to_section(self, path: str, section_index: int) -> None:
        """Open a DOCX (or section-based document) and jump to a section."""
        self.current_path = path
        self.info_label.setText(f"<b>{os.path.basename(path)}</b>")
        self.file_details_label.setText(self._file_props(path))
        self.show_source_block(path, "section", section_index)

    def seek_media(self, path: str, seconds: float) -> None:
        """Open audio/video evidence and seek to a timestamp."""
        ext = os.path.splitext(path)[1].lower()
        if ext in _VIDEO_EXT:
            self.play_video(path, seconds)
        elif ext in _AUDIO_EXT:
            self.play_audio(path, seconds)
        else:
            self.show_file(path)

    def play_audio(self, path: str, seconds: float = 0.0) -> None:
        """Play an audio file, optionally seeking to a timestamp (seconds)."""
        if not _HAS_MEDIA:
            self.info_area.setText(f"{self._file_props(path)}\n\n(audio player unavailable)")
            self.stack.setCurrentWidget(self.info_area)
            return
        self._build_audio_player(path, seconds)

    def play_video(self, path: str, seconds: float = 0.0) -> None:
        """Play a video file, optionally seeking to a timestamp (seconds)."""
        if not _HAS_MEDIA:
            self._show_video(path)
            return
        self._build_video_player(path, seconds)

    # -- media player internals ---------------------------------------- #
    def _stop_media(self) -> None:
        if self._media_player is not None:
            try:
                self._media_player.stop()
                self._media_player.setSource("")
            except Exception:
                pass
        # The control widgets (slider/buttons/labels) are built once and
        # reused across plays — only the player instance is discarded.
        self._media_player = None
        self._audio_output = None
        self._media_is_video = False

    def _build_media_controls(self, container: QWidget, is_video: bool) -> None:
        """Build the shared play/pause slider layout once, then wire the player.

        Qt forbids replacing a widget's layout; we therefore create the
        controls a single time per container and reuse them across plays,
        re-connecting only the current QMediaPlayer instance.
        """
        from PySide6.QtCore import Qt as QtCore
        from PySide6.QtWidgets import QHBoxLayout, QPushButton, QSlider

        if not self._media_controls_built:
            layout = QVBoxLayout()
            layout.setContentsMargins(4, 4, 4, 4)
            container.setLayout(layout)

            # Video output widget (created once; re-pointed per play).
            self._video_widget = QVideoWidget()
            layout.addWidget(self._video_widget, 1)
            self._video_widget.setVisible(is_video)

            controls = QHBoxLayout()
            self._media_play_button = QPushButton("⏯")
            self._media_play_button.setFixedWidth(48)
            self._media_play_button.clicked.connect(self._toggle_media_play)
            controls.addWidget(self._media_play_button)

            self._media_slider = QSlider(QtCore.Orientation.Horizontal)
            self._media_slider.setRange(0, 1000)
            controls.addWidget(self._media_slider, 1)

            self._media_time_label = QLabel("0:00 / 0:00")
            controls.addWidget(self._media_time_label)
            layout.addLayout(controls)

            self._media_controls_built = True

        # Rewire to the current player instance.
        self._video_widget.setVisible(is_video)
        self._media_player.positionChanged.connect(self._on_media_position)
        self._media_slider.sliderMoved.connect(self._media_player.setPosition)
        self._media_player.durationChanged.connect(self._on_media_duration)
        self._media_player.mediaStatusChanged.connect(self._on_media_status)
        if is_video:
            self._media_player.setVideoOutput(self._video_widget)

    def _on_media_position(self, pos: int) -> None:
        if self._media_slider is not None:
            self._media_slider.setValue(pos)
        if self._media_time_label is not None:
            self._media_time_label.setText(self._media_time_text(pos))

    def _on_media_duration(self, duration: int) -> None:
        if self._media_slider is not None and duration > 0:
            self._media_slider.setRange(0, duration)

    def _on_media_status(self, status) -> None:
        try:
            from PySide6.QtMultimedia import QMediaPlayer
            if status == QMediaPlayer.MediaStatus.EndOfMedia and self._media_play_button:
                self._media_play_button.setText("⏯")
        except Exception:
            pass

    def _toggle_media_play(self) -> None:
        if self._media_player is None:
            return
        if self._media_player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self._media_player.pause()
            self._media_play_button.setText("▶")
        else:
            self._media_player.play()
            self._media_play_button.setText("⏸")

    @staticmethod
    def _media_time_text(pos: int) -> str:
        s = int(pos / 1000)
        m, s = divmod(s, 60)
        return f"{m}:{s:02d}"

    def _build_audio_player(self, path: str, seconds: float) -> None:
        self._stop_media()
        self._media_player = QMediaPlayer(self)
        self._audio_output = QAudioOutput(self)
        self._media_player.setAudioOutput(self._audio_output)
        self._build_media_controls(self.audio_player_widget, is_video=False)
        self._media_is_video = False
        self._media_player.setSource(QUrl.fromLocalFile(path))
        self.info_label.setText(f"<b>🔊 {os.path.basename(path)}</b>")
        self.stack.setCurrentWidget(self.audio_player_widget)
        if seconds > 0:
            self._media_player.setPosition(int(seconds * 1000))
        self._media_player.play()

    def _build_video_player(self, path: str, seconds: float) -> None:
        self._stop_media()
        self._media_player = QMediaPlayer(self)
        self._audio_output = QAudioOutput(self)
        self._media_player.setAudioOutput(self._audio_output)
        self._build_media_controls(self.video_player_widget, is_video=True)
        self._media_is_video = True
        self._media_player.setSource(QUrl.fromLocalFile(path))
        self.info_label.setText(f"<b>🎬 {os.path.basename(path)}</b>")
        self.stack.setCurrentWidget(self.video_player_widget)
        if seconds > 0:
            self._media_player.setPosition(int(seconds * 1000))
        self._media_player.play()

    def _copy_extracted_text(self) -> None:
        """Copy the extracted text to the system clipboard."""
        text = self.extracted_text_content.text()
        if text:
            from PySide6.QtWidgets import QApplication
            clipboard = QApplication.clipboard()
            clipboard.setText(text)
            self.bus.status_message.emit("Extracted text copied to clipboard.")
