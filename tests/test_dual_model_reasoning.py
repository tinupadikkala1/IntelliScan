"""Unit tests for dual model selection (Qwen vs DeepSeek R1) and <think> tag handling."""

import json
from unittest.mock import MagicMock, patch

import pytest
from PySide6.QtWidgets import QApplication

from ai.config import DEEPSEEK_MODEL_NAME, MODEL_NAME
from ai.json_parser import JsonParser
from engines.rag_engine import Citation, RAGEngine, format_reasoning_answer
from ui.dialogs.ai_analysis_dialog import AIAnalysisDialog
from ui.dialogs.ask_ai_dialog import AskAIDialog


@pytest.fixture(scope="session")
def qapp():
    """Ensure QApplication instance exists for GUI tests."""
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def test_format_reasoning_answer_with_think():
    raw = "<think>\nThinking step by step about Dijkstra algorithm...\n</think>\nDijkstra finds shortest path."
    formatted = format_reasoning_answer(raw)
    assert "💭 Reasoning Process:" in formatted
    assert "Thinking step by step" in formatted
    assert "🎯 Answer:" in formatted
    assert "Dijkstra finds shortest path." in formatted
    assert "<think>" not in formatted
    assert "</think>" not in formatted


def test_format_reasoning_answer_without_think():
    raw = "Direct answer with no thinking tags."
    formatted = format_reasoning_answer(raw)
    assert formatted == raw


def test_json_parser_strips_think_tags():
    parser = JsonParser()
    raw = (
        "<think>\n"
        "Let's output JSON: { 'fake': 123 }\n"
        "</think>\n"
        "```json\n"
        '{"summary": "A document", "keywords": ["test"], "tags": ["tag1"], "category": "general", "language": "en", "entities": []}\n'
        "```"
    )
    extracted = parser._extract_json_text(raw)
    assert "<think>" not in extracted
    assert "{ 'fake': 123 }" not in extracted
    parsed = parser.parse(raw)
    assert parsed["summary"] == "A document"
    assert parsed["keywords"] == ["test"]
    assert parsed["tags"] == ["tag1"]


def test_ask_ai_dialog_model_selection(qapp):
    dialog = AskAIDialog("/path/to/test_file.txt")
    assert hasattr(dialog, "model_combo")
    assert dialog.model_combo.count() >= 2
    assert dialog.model_combo.currentData() == MODEL_NAME

    # Switch to DeepSeek
    dialog.model_combo.setCurrentIndex(1)
    assert dialog.model_combo.currentData() == DEEPSEEK_MODEL_NAME

    received = []
    dialog.question_submitted.connect(lambda q, fp, m: received.append((q, fp, m)))

    dialog.question_input.setText("What is in this file?")
    dialog._on_ask()

    assert len(received) == 1
    assert received[0][0] == "What is in this file?"
    assert received[0][1] == "/path/to/test_file.txt"
    assert received[0][2] == DEEPSEEK_MODEL_NAME


def test_ai_analysis_dialog_model_selection(qapp):
    dialog = AIAnalysisDialog(analysis=None, file_name="test_file.txt")
    assert hasattr(dialog, "model_combo")
    assert dialog.model_combo.count() >= 2
    assert dialog._get_selected_model() == MODEL_NAME

    # Switch to DeepSeek
    dialog.model_combo.setCurrentIndex(1)
    assert dialog._get_selected_model() == DEEPSEEK_MODEL_NAME

    received = []
    dialog.run_analysis_requested.connect(lambda d, m: received.append((d, m)))

    dialog._on_run_analysis()
    assert len(received) == 1
    assert received[0][1] == DEEPSEEK_MODEL_NAME


def test_rag_engine_ask_file_direct_passes_model(tmp_path):
    dummy_file = tmp_path / "test.txt"
    dummy_file.write_text("Hello file content for testing.")

    retrieval = MagicMock()
    rag = RAGEngine(retrieval_engine=retrieval)

    with patch.object(rag, "_generate", return_value="Deep answer") as mock_gen:
        resp = rag.ask_file_direct("What is this?", str(dummy_file), model=DEEPSEEK_MODEL_NAME)
        mock_gen.assert_called_once()
        _, kwargs = mock_gen.call_args
        assert kwargs.get("model") == DEEPSEEK_MODEL_NAME
        assert resp.model == DEEPSEEK_MODEL_NAME
        assert resp.answer == "Deep answer"


def test_analysis_manager_passes_model(tmp_path):
    dummy_file = tmp_path / "sample_doc.txt"
    dummy_file.write_text("Detailed document content.")

    ai_service = MagicMock()
    ai_service.analyze_text.return_value = {
        "summary": "Sample summary",
        "keywords": ["sample"],
        "tags": ["test"],
        "category": "Documentation",
        "language": "en",
        "model_name": DEEPSEEK_MODEL_NAME,
    }

    from ai.analysis_manager import AnalysisManager
    mgr = AnalysisManager(ai_service=ai_service)

    result = mgr.analyze_file(str(dummy_file), detail_level="high", model=DEEPSEEK_MODEL_NAME)
    ai_service.analyze_text.assert_called_once()
    args, kwargs = ai_service.analyze_text.call_args
    assert kwargs.get("model") == DEEPSEEK_MODEL_NAME
    assert args[1] == "high"
    assert result["model_name"] == DEEPSEEK_MODEL_NAME
    assert result["summary"] == "Sample summary"
