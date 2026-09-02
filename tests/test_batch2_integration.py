"""Integration tests for IntelliVault Batch 2 - AI Analysis Pipeline.

Tests end-to-end scenarios: index → analyze → store → retrieve,
file rename/move preservation, content change detection,
graceful offline handling, and JSON parser repair.

All tests work WITHOUT Ollama running (mocked).
"""

import hashlib
import json
import os
import shutil
import sys
import tempfile
from unittest.mock import MagicMock, patch

import pytest

# Ensure project root is in sys.path
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

from text_extraction import ExtractorFactory
from ai.prompt_builder import PromptBuilder
from ai.json_parser import JsonParser
from ai.cache_manager import AICacheManager
from ai.ollama_client import OllamaClient
from ai.config import PROMPT_VERSION
from database.engine import Database


def _compute_sha256(file_path: str) -> str:
    """Compute SHA-256 hash of a file's content."""
    h = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def _make_temp_db(tmp_path):
    """Create a temporary Database and return (db, session_factory)."""
    db_path = str(tmp_path / "test_integration.db")
    db = Database(db_path)
    return db, db.Session


# --- Fixtures ---


@pytest.fixture
def temp_db(tmp_path):
    """Provide a temporary database and session factory."""
    db, session_factory = _make_temp_db(tmp_path)
    yield db, session_factory
    db.dispose()


# --- Test 1: Full pipeline index → analyze → store → retrieve ---


def test_scenario_index_analyze_store_retrieve(tmp_path, temp_db):
    """End-to-end: extract text → build prompt → mock AI → parse → store → retrieve."""
    db, session_factory = temp_db

    # Step 1: Create a temp .txt file with meaningful content
    content = (
        "Artificial intelligence is transforming the software industry. "
        "Machine learning models are being used for code generation, "
        "document analysis, and automated testing. This document explores "
        "the impact of large language models on developer productivity."
    )
    txt_file = tmp_path / "research_paper.txt"
    txt_file.write_text(content, encoding="utf-8")

    # Step 2: Use ExtractorFactory to extract text
    extractor = ExtractorFactory.get_extractor(str(txt_file))
    assert extractor is not None, "TxtExtractor should be returned for .txt files"
    extracted_text = extractor.extract(str(txt_file))
    assert content in extracted_text

    # Step 3: Use PromptBuilder to build prompt
    builder = PromptBuilder()
    prompt = builder.build_analysis_prompt(extracted_text)
    assert len(prompt) > 0
    assert "Document Analysis Task" in prompt
    assert extracted_text in prompt

    # Step 4: Mock OllamaClient.generate to return valid JSON
    mock_ai_response = json.dumps({
        "summary": "This document discusses the impact of AI on software development.",
        "keywords": ["artificial intelligence", "machine learning", "code generation"],
        "tags": ["technology", "AI", "software"],
        "category": "technical",
        "language": "English"
    })

    with patch.object(OllamaClient, "generate", return_value=mock_ai_response):
        client = OllamaClient()
        raw_response = client.generate(prompt)

    # Step 5: Use JsonParser to parse
    parser = JsonParser()
    parsed = parser.parse(raw_response)
    assert parsed["summary"] == "This document discusses the impact of AI on software development."
    assert "artificial intelligence" in parsed["keywords"]
    assert parsed["category"] == "technical"
    assert parsed["language"] == "English"

    # Step 6: Store in AICacheManager
    file_hash = _compute_sha256(str(txt_file))
    cache = AICacheManager(session_factory)

    store_result = cache.store_analysis(file_hash, parsed)
    assert store_result is True

    # Step 7: Retrieve and verify all fields match
    retrieved = cache.get_analysis(file_hash)
    assert retrieved is not None
    assert retrieved["summary"] == parsed["summary"]
    assert retrieved["keywords"] == parsed["keywords"]
    assert retrieved["tags"] == parsed["tags"]
    assert retrieved["category"] == parsed["category"]
    assert retrieved["language"] == parsed["language"]
    assert retrieved["file_hash"] == file_hash
    assert retrieved["ai_generated"] is True


# --- Test 2: Rename preserves analysis ---


def test_scenario_rename_preserves_analysis(tmp_path, temp_db):
    """Renaming a file does not change its content hash → analysis preserved."""
    db, session_factory = temp_db

    # Step 1: Create temp file and compute SHA-256
    content = "This is a document about quantum computing breakthroughs in 2025."
    original_file = tmp_path / "original_document.txt"
    original_file.write_text(content, encoding="utf-8")

    original_hash = _compute_sha256(str(original_file))

    # Step 2: Store mock analysis
    mock_analysis = {
        "summary": "Document about quantum computing breakthroughs.",
        "keywords": ["quantum", "computing", "breakthroughs"],
        "tags": ["science", "technology"],
        "category": "academic",
        "language": "English",
    }

    cache = AICacheManager(session_factory)
    assert cache.store_analysis(original_hash, mock_analysis) is True

    # Step 3: Rename the file
    renamed_file = tmp_path / "renamed_document.txt"
    os.rename(str(original_file), str(renamed_file))

    # Step 4: Recompute hash (content unchanged = same hash)
    new_hash = _compute_sha256(str(renamed_file))
    assert new_hash == original_hash, "Hash should be identical after rename"

    # Step 5: Retrieve from cache - verify analysis preserved
    retrieved = cache.get_analysis(new_hash)
    assert retrieved is not None
    assert retrieved["summary"] == mock_analysis["summary"]
    assert retrieved["keywords"] == mock_analysis["keywords"]
    assert retrieved["tags"] == mock_analysis["tags"]
    assert retrieved["category"] == mock_analysis["category"]
    assert retrieved["language"] == mock_analysis["language"]


# --- Test 3: Move preserves analysis ---


def test_scenario_move_preserves_analysis(tmp_path, temp_db):
    """Moving a file to a different directory preserves analysis (same content hash)."""
    db, session_factory = temp_db

    # Step 1: Create temp file and compute SHA-256
    content = "Climate change research data analysis report for fiscal year 2025."
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    source_file = source_dir / "report.txt"
    source_file.write_text(content, encoding="utf-8")

    original_hash = _compute_sha256(str(source_file))

    # Step 2: Store mock analysis
    mock_analysis = {
        "summary": "Climate change research report.",
        "keywords": ["climate", "research", "data"],
        "tags": ["environment", "science"],
        "category": "academic",
        "language": "English",
    }

    cache = AICacheManager(session_factory)
    assert cache.store_analysis(original_hash, mock_analysis) is True

    # Step 3: Move file to different directory
    dest_dir = tmp_path / "destination"
    dest_dir.mkdir()
    dest_file = dest_dir / "report.txt"
    shutil.move(str(source_file), str(dest_file))

    # Step 4: Recompute hash - same hash
    new_hash = _compute_sha256(str(dest_file))
    assert new_hash == original_hash, "Hash should be identical after move"

    # Step 5: Retrieve - analysis preserved
    retrieved = cache.get_analysis(new_hash)
    assert retrieved is not None
    assert retrieved["summary"] == mock_analysis["summary"]
    assert retrieved["keywords"] == mock_analysis["keywords"]
    assert retrieved["tags"] == mock_analysis["tags"]
    assert retrieved["category"] == mock_analysis["category"]
    assert retrieved["language"] == mock_analysis["language"]


# --- Test 4: Content change detection ---


def test_scenario_content_change_detection(tmp_path, temp_db):
    """Modifying file content changes the hash → old analysis not found."""
    db, session_factory = temp_db

    # Step 1: Create temp file and compute SHA-256
    original_content = "Original document content about neural networks."
    file_path = tmp_path / "evolving_document.txt"
    file_path.write_text(original_content, encoding="utf-8")

    original_hash = _compute_sha256(str(file_path))

    # Step 2: Store mock analysis
    mock_analysis = {
        "summary": "Document about neural networks.",
        "keywords": ["neural networks", "AI"],
        "tags": ["technology"],
        "category": "technical",
        "language": "English",
    }

    cache = AICacheManager(session_factory)
    assert cache.store_analysis(original_hash, mock_analysis) is True

    # Verify stored correctly
    assert cache.has_analysis(original_hash) is True

    # Step 3: Modify file content (write different text)
    modified_content = "Completely different content about blockchain technology."
    file_path.write_text(modified_content, encoding="utf-8")

    # Step 4: Recompute SHA-256 - different hash
    new_hash = _compute_sha256(str(file_path))
    assert new_hash != original_hash, "Hash must differ after content change"

    # Step 5: Lookup with new hash - returns None (needs regeneration)
    retrieved = cache.get_analysis(new_hash)
    assert retrieved is None, "New hash should have no cached analysis"

    # Old hash still has the analysis
    old_retrieved = cache.get_analysis(original_hash)
    assert old_retrieved is not None


# --- Test 5: Ollama offline graceful error ---


def test_scenario_ollama_offline_graceful_error():
    """When Ollama is offline, client handles errors gracefully."""
    import requests

    # Mock requests.post to raise ConnectionError
    with patch("ai.ollama_client.requests.post") as mock_post:
        mock_post.side_effect = requests.exceptions.ConnectionError(
            "Connection refused"
        )

        client = OllamaClient(base_url="http://localhost:11434")

        # Call generate() - should not crash, should raise descriptive error
        with pytest.raises(ConnectionError) as exc_info:
            client.generate("Test prompt")

        # Verify descriptive error message
        assert "Cannot connect to Ollama" in str(exc_info.value)
        assert "Ensure Ollama is running" in str(exc_info.value)

    # Verify is_available() returns False when offline
    with patch("ai.ollama_client.requests.get") as mock_get:
        mock_get.side_effect = requests.exceptions.ConnectionError(
            "Connection refused"
        )

        client = OllamaClient(base_url="http://localhost:11434")
        assert client.is_available() is False


# --- Test 6: Invalid JSON parser repair ---


def test_scenario_invalid_json_parser_repair():
    """JsonParser handles trailing commas, markdown blocks, and invalid JSON."""
    parser = JsonParser()

    # Case 1: Response with trailing commas - should repair and return valid dict
    response_trailing_commas = '''{
        "summary": "A document about data science",
        "keywords": ["data", "science", "analysis",],
        "tags": ["technical", "research",],
        "category": "technical",
        "language": "English",
    }'''
    result = parser.parse(response_trailing_commas)
    assert isinstance(result, dict)
    assert result["summary"] == "A document about data science"
    assert result["keywords"] == ["data", "science", "analysis"]
    assert result["tags"] == ["technical", "research"]
    assert result["category"] == "technical"
    assert result["language"] == "English"

    # Case 2: JSON inside markdown code block - should extract and return valid dict
    response_markdown = '''Here is the analysis result:

```json
{
    "summary": "Financial report for Q4 2025",
    "keywords": ["finance", "quarterly", "report"],
    "tags": ["business", "financial"],
    "category": "financial",
    "language": "English"
}
```

Hope this helps!'''
    result2 = parser.parse(response_markdown)
    assert isinstance(result2, dict)
    assert result2["summary"] == "Financial report for Q4 2025"
    assert result2["keywords"] == ["finance", "quarterly", "report"]
    assert result2["category"] == "financial"

    # Case 3: Completely invalid response - should raise ValueError
    response_invalid = "This is not JSON at all, just plain text with no structure."
    with pytest.raises(ValueError):
        parser.parse(response_invalid)
