"""Unit tests for IntelliVault Batch 2 - AI Analysis Module.

Tests cover text extraction, AI service components, caching, and analysis pipeline.
"""

import hashlib
import json
import os
import sys
import tempfile
from unittest.mock import MagicMock, patch

import pytest

# Ensure project root is in sys.path
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

from text_extraction.txt_extractor import TxtExtractor
from text_extraction.pdf_extractor import PdfExtractor
from text_extraction.docx_extractor import DocxExtractor
from text_extraction.xlsx_extractor import XlsxExtractor
from text_extraction.pptx_extractor import PptxExtractor
from text_extraction.csv_extractor import CsvExtractor
from text_extraction.json_extractor import JsonExtractor
from text_extraction.xml_extractor import XmlExtractor
from text_extraction.md_extractor import MdExtractor
from text_extraction.extractor_factory import ExtractorFactory
from text_extraction.base_extractor import BaseExtractor, MAX_FILE_SIZE

from ai.prompt_builder import PromptBuilder
from ai.config import MAX_TEXT_CHUNK
from ai.json_parser import JsonParser
from ai.cache_manager import AICacheManager
from ai.ollama_client import OllamaClient
from ai.ai_service import AIService
from ai.analysis_manager import AnalysisManager

from database.engine import Database


# =============================================================================
# 1. TXT Extractor - create temp .txt file, extract, verify text returned
# =============================================================================


def test_txt_extractor(tmp_path):
    """TXT extractor should read and return file content."""
    txt_file = tmp_path / "sample.txt"
    txt_file.write_text("Hello, IntelliVault!", encoding="utf-8")

    extractor = TxtExtractor()
    result = extractor.extract(str(txt_file))

    assert result == "Hello, IntelliVault!"


# =============================================================================
# 2. PDF Extractor - test with a non-existent file returns empty string
# =============================================================================


def test_pdf_extractor_nonexistent_file():
    """PDF extractor should return empty string for non-existent file."""
    extractor = PdfExtractor()
    result = extractor.extract("/nonexistent/path/to/file.pdf")
    assert result == ""


# =============================================================================
# 3. DOCX Extractor - test with a non-existent file returns empty string
# =============================================================================


def test_docx_extractor_nonexistent_file():
    """DOCX extractor should return empty string for non-existent file."""
    extractor = DocxExtractor()
    result = extractor.extract("/nonexistent/path/to/file.docx")
    assert result == ""


# =============================================================================
# 4. XLSX Extractor - test with a non-existent file returns empty string
# =============================================================================


def test_xlsx_extractor_nonexistent_file():
    """XLSX extractor should return empty string for non-existent file."""
    extractor = XlsxExtractor()
    result = extractor.extract("/nonexistent/path/to/file.xlsx")
    assert result == ""


# =============================================================================
# 5. PPTX Extractor - test with a non-existent file returns empty string
# =============================================================================


def test_pptx_extractor_nonexistent_file():
    """PPTX extractor should return empty string for non-existent file."""
    extractor = PptxExtractor()
    result = extractor.extract("/nonexistent/path/to/file.pptx")
    assert result == ""


# =============================================================================
# 6. CSV Extractor - create temp .csv file, extract, verify content
# =============================================================================


def test_csv_extractor(tmp_path):
    """CSV extractor should read rows and join with tabs/newlines."""
    csv_file = tmp_path / "data.csv"
    csv_file.write_text("name,age,city\nAlice,30,NYC\nBob,25,LA\n", encoding="utf-8")

    extractor = CsvExtractor()
    result = extractor.extract(str(csv_file))

    assert "name" in result
    assert "Alice" in result
    assert "Bob" in result
    # Verify tab-separated format
    assert "\t" in result


# =============================================================================
# 7. JSON Extractor - create temp .json file, extract, verify pretty-printed
# =============================================================================


def test_json_extractor(tmp_path):
    """JSON extractor should return pretty-printed JSON content."""
    data = {"name": "IntelliVault", "version": 2, "features": ["AI", "cache"]}
    json_file = tmp_path / "config.json"
    json_file.write_text(json.dumps(data), encoding="utf-8")

    extractor = JsonExtractor()
    result = extractor.extract(str(json_file))

    # Should be pretty-printed (indented)
    assert '"name": "IntelliVault"' in result
    assert '"version": 2' in result
    # Verify it's valid JSON
    parsed = json.loads(result)
    assert parsed == data


# =============================================================================
# 8. XML Extractor - create temp .xml file, extract, verify text nodes
# =============================================================================


def test_xml_extractor(tmp_path):
    """XML extractor should extract text nodes from XML file."""
    xml_content = (
        '<?xml version="1.0"?>\n'
        "<root>\n"
        "  <title>Test Document</title>\n"
        "  <body>This is the body content.</body>\n"
        "</root>"
    )
    xml_file = tmp_path / "doc.xml"
    xml_file.write_text(xml_content, encoding="utf-8")

    extractor = XmlExtractor()
    result = extractor.extract(str(xml_file))

    assert "Test Document" in result
    assert "This is the body content." in result


# =============================================================================
# 9. MD Extractor - create temp .md file, extract, verify content
# =============================================================================


def test_md_extractor(tmp_path):
    """MD extractor should return markdown content as-is."""
    md_content = "# Heading\n\nSome **bold** text and a [link](http://example.com).\n"
    md_file = tmp_path / "readme.md"
    md_file.write_text(md_content, encoding="utf-8")

    extractor = MdExtractor()
    result = extractor.extract(str(md_file))

    assert "# Heading" in result
    assert "**bold**" in result
    assert "link" in result


# =============================================================================
# 10. ExtractorFactory - supported extensions, get_extractor, unsupported
# =============================================================================


def test_extractor_factory_supported_extensions():
    """ExtractorFactory should return a non-empty sorted list of extensions."""
    extensions = ExtractorFactory.supported_extensions()

    assert isinstance(extensions, list)
    assert len(extensions) > 0
    assert ".txt" in extensions
    assert ".pdf" in extensions
    assert ".csv" in extensions
    assert ".json" in extensions
    assert ".xml" in extensions
    # Verify sorted
    assert extensions == sorted(extensions)


def test_extractor_factory_get_extractor_correct_types():
    """ExtractorFactory should return correct extractor types."""
    assert isinstance(ExtractorFactory.get_extractor("file.txt"), TxtExtractor)
    assert isinstance(ExtractorFactory.get_extractor("file.pdf"), PdfExtractor)
    assert isinstance(ExtractorFactory.get_extractor("file.docx"), DocxExtractor)
    assert isinstance(ExtractorFactory.get_extractor("file.xlsx"), XlsxExtractor)
    assert isinstance(ExtractorFactory.get_extractor("file.pptx"), PptxExtractor)
    assert isinstance(ExtractorFactory.get_extractor("file.csv"), CsvExtractor)
    assert isinstance(ExtractorFactory.get_extractor("file.json"), JsonExtractor)
    assert isinstance(ExtractorFactory.get_extractor("file.xml"), XmlExtractor)
    assert isinstance(ExtractorFactory.get_extractor("file.md"), MdExtractor)


def test_extractor_factory_unsupported_returns_none():
    """ExtractorFactory should return None for unsupported file types."""
    assert ExtractorFactory.get_extractor("file.xyz") is None
    assert ExtractorFactory.get_extractor("file.bin") is None
    assert ExtractorFactory.get_extractor("file.exe") is None


# =============================================================================
# 11. PromptBuilder - build_analysis_prompt returns non-empty string
# =============================================================================


def test_prompt_builder_returns_nonempty_string():
    """PromptBuilder should return a non-empty string containing the input text."""
    builder = PromptBuilder()
    text = "This is a sample document about AI technology."

    prompt = builder.build_analysis_prompt(text)

    assert isinstance(prompt, str)
    assert len(prompt) > 0
    assert text in prompt


# =============================================================================
# 12. PromptBuilder - test text truncation at MAX_TEXT_CHUNK
# =============================================================================


def test_prompt_builder_truncation():
    """PromptBuilder should truncate text longer than MAX_TEXT_CHUNK."""
    builder = PromptBuilder()
    # Create text longer than MAX_TEXT_CHUNK
    long_text = "A" * (MAX_TEXT_CHUNK + 1000)

    prompt = builder.build_analysis_prompt(long_text)

    # The full long_text should NOT be in the prompt
    assert long_text not in prompt
    # But the truncated portion (first MAX_TEXT_CHUNK chars) should be
    truncated = "A" * MAX_TEXT_CHUNK
    assert truncated in prompt
    # Verify the excess is cut off
    excess = "A" * (MAX_TEXT_CHUNK + 1)
    assert excess not in prompt


# =============================================================================
# 13. JsonParser - test valid JSON parsing with all 5 fields
# =============================================================================


def test_json_parser_valid_response():
    """JsonParser should successfully parse a valid JSON response with all fields."""
    parser = JsonParser()
    valid_response = json.dumps({
        "summary": "A document about testing.",
        "keywords": ["test", "python", "pytest"],
        "tags": ["testing", "development"],
        "category": "technical",
        "language": "English",
    })

    result = parser.parse(valid_response)

    assert result["summary"] == "A document about testing."
    assert result["keywords"] == ["test", "python", "pytest"]
    assert result["tags"] == ["testing", "development"]
    assert result["category"] == "technical"
    assert result["language"] == "English"


# =============================================================================
# 14. JsonParser - test extraction from markdown code blocks
# =============================================================================


def test_json_parser_markdown_code_block():
    """JsonParser should extract JSON from markdown code blocks."""
    parser = JsonParser()
    response = (
        "Here is the analysis:\n"
        "```json\n"
        '{"summary": "Test summary.", "keywords": ["a", "b"], '
        '"tags": ["tag1"], "category": "general", "language": "English"}\n'
        "```\n"
    )

    result = parser.parse(response)

    assert result["summary"] == "Test summary."
    assert result["category"] == "general"


# =============================================================================
# 15. JsonParser - test repair of trailing commas
# =============================================================================


def test_json_parser_trailing_commas():
    """JsonParser should repair trailing commas in JSON."""
    parser = JsonParser()
    # JSON with trailing commas (invalid JSON)
    response = (
        '{"summary": "Summary here.", '
        '"keywords": ["k1", "k2",], '
        '"tags": ["t1",], '
        '"category": "technical", '
        '"language": "English",}'
    )

    result = parser.parse(response)

    assert result["summary"] == "Summary here."
    assert result["keywords"] == ["k1", "k2"]
    assert result["tags"] == ["t1"]


# =============================================================================
# 16. JsonParser - test missing field raises ValueError
# =============================================================================


def test_json_parser_missing_field():
    """JsonParser should raise ValueError when required field is missing."""
    parser = JsonParser()
    # Missing "language" field
    response = json.dumps({
        "summary": "Test.",
        "keywords": ["a"],
        "tags": ["b"],
        "category": "general",
    })

    with pytest.raises(ValueError, match="Missing required fields"):
        parser.parse(response)


# =============================================================================
# 17. JsonParser - test invalid JSON raises ValueError
# =============================================================================


def test_json_parser_invalid_json():
    """JsonParser should raise ValueError for completely invalid JSON."""
    parser = JsonParser()
    response = "This is not JSON at all, just plain text without braces."

    with pytest.raises(ValueError):
        parser.parse(response)


# =============================================================================
# 18. SQLite Cache (AICacheManager) - test store and retrieve
# =============================================================================


@pytest.fixture
def cache_db(tmp_path):
    """Create a temporary database for cache tests."""
    db_path = str(tmp_path / "test_cache.db")
    db = Database(db_path)
    yield db
    db.dispose()


def test_cache_store_and_retrieve(cache_db):
    """AICacheManager should store and retrieve analysis results."""
    cache = AICacheManager(cache_db.Session)
    file_hash = "a" * 64
    analysis = {
        "summary": "Test document summary.",
        "keywords": ["test", "cache"],
        "tags": ["unit-test"],
        "category": "technical",
        "language": "English",
        "prompt_version": "1.0",
        "model_name": "test-model",
    }

    # Store
    success = cache.store_analysis(file_hash, analysis)
    assert success is True

    # Retrieve
    result = cache.get_analysis(file_hash)
    assert result is not None
    assert result["summary"] == "Test document summary."
    assert result["keywords"] == ["test", "cache"]
    assert result["tags"] == ["unit-test"]
    assert result["category"] == "technical"
    assert result["language"] == "English"


# =============================================================================
# 19. SQLite Cache - test has_analysis
# =============================================================================


def test_cache_has_analysis(cache_db):
    """AICacheManager.has_analysis should return True after store."""
    cache = AICacheManager(cache_db.Session)
    file_hash = "b" * 64

    assert cache.has_analysis(file_hash) is False

    cache.store_analysis(file_hash, {
        "summary": "Exists.",
        "keywords": [],
        "tags": [],
        "category": "general",
        "language": "English",
    })

    assert cache.has_analysis(file_hash) is True


# =============================================================================
# 20. SQLite Cache - test delete_analysis
# =============================================================================


def test_cache_delete_analysis(cache_db):
    """AICacheManager.delete_analysis should remove the cached record."""
    cache = AICacheManager(cache_db.Session)
    file_hash = "c" * 64

    cache.store_analysis(file_hash, {
        "summary": "To be deleted.",
        "keywords": [],
        "tags": [],
        "category": "general",
        "language": "English",
    })

    assert cache.has_analysis(file_hash) is True

    deleted = cache.delete_analysis(file_hash)
    assert deleted is True
    assert cache.has_analysis(file_hash) is False


# =============================================================================
# 21. SQLite Cache - test update (store twice with same hash)
# =============================================================================


def test_cache_update_same_hash(cache_db):
    """AICacheManager should update when storing with the same file hash."""
    cache = AICacheManager(cache_db.Session)
    file_hash = "d" * 64

    # First store
    cache.store_analysis(file_hash, {
        "summary": "Original summary.",
        "keywords": ["original"],
        "tags": ["v1"],
        "category": "general",
        "language": "English",
    })

    # Second store (update)
    cache.store_analysis(file_hash, {
        "summary": "Updated summary.",
        "keywords": ["updated"],
        "tags": ["v2"],
        "category": "technical",
        "language": "French",
    })

    result = cache.get_analysis(file_hash)
    assert result is not None
    assert result["summary"] == "Updated summary."
    assert result["keywords"] == ["updated"]
    assert result["tags"] == ["v2"]
    assert result["category"] == "technical"
    assert result["language"] == "French"


# =============================================================================
# 22. SHA-256 Identity - compute hash of a temp file, verify 64-char hex
# =============================================================================


def test_sha256_file_hash(tmp_path):
    """AnalysisManager._compute_file_hash should return a 64-char hex string."""
    test_file = tmp_path / "hashtest.txt"
    test_file.write_text("Content for hashing.", encoding="utf-8")

    manager = AnalysisManager(ai_service=MagicMock())
    file_hash = manager._compute_file_hash(str(test_file))

    assert isinstance(file_hash, str)
    assert len(file_hash) == 64
    # Verify it's valid hex
    int(file_hash, 16)

    # Verify correctness against known hashlib result
    expected = hashlib.sha256(b"Content for hashing.").hexdigest()
    assert file_hash == expected


# =============================================================================
# 23. OllamaClient (Mock) - mock requests.post, test generate returns response
# =============================================================================


@patch("ai.ollama_client.requests.post")
def test_ollama_client_generate(mock_post):
    """OllamaClient.generate should return response text from Ollama API."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"response": "Generated text output."}
    mock_post.return_value = mock_response

    client = OllamaClient()
    result = client.generate("Test prompt")

    assert result == "Generated text output."
    mock_post.assert_called_once()


# =============================================================================
# 24. OllamaClient (Mock) - mock requests.get offline, is_available returns False
# =============================================================================


@patch("ai.ollama_client.requests.get")
def test_ollama_client_is_available_offline(mock_get):
    """OllamaClient.is_available should return False when server is offline."""
    import requests

    mock_get.side_effect = requests.exceptions.ConnectionError("Connection refused")

    client = OllamaClient()
    result = client.is_available()

    assert result is False


# =============================================================================
# 25. AIService (Mock) - mock OllamaClient.generate, test analyze_text
# =============================================================================


def test_ai_service_analyze_text():
    """AIService.analyze_text should return parsed dict from mocked Ollama."""
    mock_client = MagicMock()
    mock_client.generate.return_value = json.dumps({
        "summary": "Document about testing.",
        "keywords": ["testing", "mock"],
        "tags": ["development"],
        "category": "technical",
        "language": "English",
    })

    service = AIService(
        ollama_client=mock_client,
        prompt_builder=PromptBuilder(),
        json_parser=JsonParser(),
    )

    result = service.analyze_text("Some document text about testing.")

    assert isinstance(result, dict)
    assert "error" not in result
    assert result["summary"] == "Document about testing."
    assert result["keywords"] == ["testing", "mock"]
    assert result["category"] == "technical"
    mock_client.generate.assert_called_once()


# =============================================================================
# 26. AnalysisManager - test unsupported file returns error
# =============================================================================


def test_analysis_manager_unsupported_file(tmp_path):
    """AnalysisManager should return error dict for unsupported file types."""
    unsupported_file = tmp_path / "data.xyz"
    unsupported_file.write_text("some data", encoding="utf-8")

    manager = AnalysisManager(ai_service=MagicMock())
    result = manager.analyze_file(str(unsupported_file))

    assert isinstance(result, dict)
    assert "error" in result
    assert "Unsupported file type" in result["error"]


# =============================================================================
# 27. BaseExtractor - test validate_file rejects non-existent file
# =============================================================================


def test_base_extractor_validate_nonexistent():
    """BaseExtractor.validate_file should return False for non-existent file."""
    # Create a concrete subclass for testing
    class ConcreteExtractor(BaseExtractor):
        def extract(self, file_path: str) -> str:
            return ""

    extractor = ConcreteExtractor()
    result = extractor.validate_file("/nonexistent/path/to/file.txt")
    assert result is False


# =============================================================================
# 28. BaseExtractor - test validate_file rejects oversized file
# =============================================================================


def test_base_extractor_validate_oversized(tmp_path):
    """BaseExtractor.validate_file should return False for oversized files."""

    class ConcreteExtractor(BaseExtractor):
        def extract(self, file_path: str) -> str:
            return ""

    extractor = ConcreteExtractor()
    oversized_file = tmp_path / "big.txt"
    oversized_file.write_text("x", encoding="utf-8")

    # Mock os.path.getsize to report oversized file
    with patch("text_extraction.base_extractor.os.path.getsize") as mock_size:
        mock_size.return_value = MAX_FILE_SIZE + 1
        result = extractor.validate_file(str(oversized_file))

    assert result is False
