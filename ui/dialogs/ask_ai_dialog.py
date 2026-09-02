"""Ask AI Dialog.

A dialog for asking questions about a selected file using AI-powered
retrieval-augmented generation. Displays the AI answer along with
source citations. The dialog is purely presentational — it does not
import or call any engine directly. Data flows via signals.
"""

from __future__ import annotations

import time
from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
)


class AskAIDialog(QDialog):
    """Dialog for asking AI questions about a specific file.

    Signals:
        question_submitted: Emitted when the user submits a question.
            Carries (question, file_path).
    """

    question_submitted = Signal(str, str)  # question, file_path
    citation_activated = Signal(str)  # file_path of a clicked citation

    def __init__(self, file_path: str, parent=None) -> None:
        """Initialize the Ask AI Dialog.

        Args:
            file_path: Absolute path to the file being queried.
            parent: Parent widget.
        """
        super().__init__(parent)
        self._file_path = file_path
        self._start_time: Optional[float] = None

        self.setWindowTitle(f"Ask AI — {file_path.split('/')[-1] if '/' in file_path else file_path}")
        self.setMinimumSize(650, 550)
        self.setModal(False)

        self._setup_ui()

    def _setup_ui(self) -> None:
        """Set up the dialog UI layout."""
        layout = QVBoxLayout(self)

        # File info header
        file_label = QLabel(f"<b>File:</b> {self._file_path}")
        file_label.setWordWrap(True)
        file_label.setStyleSheet("padding: 4px;")
        layout.addWidget(file_label)

        # Question input row
        question_layout = QHBoxLayout()
        self.question_input = QLineEdit()
        self.question_input.setPlaceholderText("Ask a question about this file...")
        self.question_input.returnPressed.connect(self._on_ask)
        question_layout.addWidget(self.question_input)

        self.ask_button = QPushButton("Ask")
        self.ask_button.clicked.connect(self._on_ask)
        question_layout.addWidget(self.ask_button)

        layout.addLayout(question_layout)

        # Status label
        self.status_label = QLabel("Enter a question to ask AI.")
        self.status_label.setStyleSheet("color: gray; padding: 4px;")
        layout.addWidget(self.status_label)

        # Answer display
        answer_group = QGroupBox("Answer")
        answer_layout = QVBoxLayout(answer_group)
        self.answer_display = QTextEdit()
        self.answer_display.setReadOnly(True)
        self.answer_display.setPlaceholderText("AI response will appear here...")
        answer_layout.addWidget(self.answer_display)
        layout.addWidget(answer_group)

        # Citations list
        citations_group = QGroupBox("Citations")
        citations_layout = QVBoxLayout(citations_group)
        self.citations_list = QListWidget()
        self.citations_list.setAlternatingRowColors(True)
        self.citations_list.setMaximumHeight(150)
        self.citations_list.itemDoubleClicked.connect(self._on_citation_activated)
        citations_layout.addWidget(self.citations_list)
        layout.addWidget(citations_group)

    def _on_ask(self) -> None:
        """Handle Ask button click or Enter key press."""
        question = self.question_input.text().strip()
        if not question:
            return
        self._start_time = time.time()
        self.status_label.setText("Thinking...")
        self.status_label.setStyleSheet("color: gray; padding: 4px;")
        self.answer_display.clear()
        self.citations_list.clear()
        self.ask_button.setEnabled(False)
        self.question_submitted.emit(question, self._file_path)

    @property
    def file_path(self) -> str:
        """Return the file path this dialog is querying about.

        Returns:
            The file path string.
        """
        return self._file_path

    def set_answer(self, answer: str, citations: list[dict]) -> None:
        """Display the AI answer and associated citations.

        Args:
            answer: The AI-generated answer text.
            citations: List of citation dicts, each containing:
                - source_label (str): Human-friendly source label
                - file_path (str): Path to the source file
                - score (float): Relevance score
                - snippet (str): Text snippet from the source
        """
        self.ask_button.setEnabled(True)

        elapsed = 0.0
        if self._start_time is not None:
            elapsed = time.time() - self._start_time

        self.answer_display.setPlainText(answer)
        self.status_label.setText(f"Completed in {elapsed:.2f}s")
        self.status_label.setStyleSheet("color: green; padding: 4px;")

        # Populate citations
        self.citations_list.clear()
        for citation in citations:
            source_label = citation.get("source_label", "")
            file_path = citation.get("file_path", "")
            score = citation.get("score", 0.0)
            snippet = citation.get("snippet", "")

            # Truncate snippet for display
            short_snippet = snippet[:100].replace("\n", " ")
            if len(snippet) > 100:
                short_snippet += "..."

            display_text = (
                f"[{score:.3f}] {source_label}\n"
                f"  {short_snippet}\n"
                f"  📄 {file_path}"
            )

            item = QListWidgetItem(display_text)
            item.setData(Qt.UserRole, citation)
            self.citations_list.addItem(item)

    def _on_citation_activated(self, item: QListWidgetItem) -> None:
        """Emit the source file path when a citation is double-clicked."""
        citation = item.data(Qt.UserRole) or {}
        file_path = citation.get("file_path", "")
        if file_path:
            self.citation_activated.emit(file_path)

    def set_error(self, error_message: str) -> None:
        """Display an error message in the status label.

        Args:
            error_message: The error description to display.
        """
        self.ask_button.setEnabled(True)
        self.status_label.setText(f"Error: {error_message}")
        self.status_label.setStyleSheet("color: red; padding: 4px;")
        self.answer_display.clear()
