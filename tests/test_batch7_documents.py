"""Batch 7 tests — document comparison (B7-5)."""

import os
import sys
import tempfile

import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)


class _FakeRag:
    def __init__(self, answer="Changes are meaningful."):
        self._answer = answer
        self.calls = 0

    def _generate(self, prompt):
        self.calls += 1
        return self._answer


class TestDocumentComparison:
    def _svc(self, rag=None, retrieval=None):
        from services.document_comparison_service import DocumentComparisonService

        return DocumentComparisonService(rag_engine=rag, retrieval_engine=retrieval)

    def _write(self, tmp_path, name, text):
        p = tmp_path / name
        p.write_text(text, encoding="utf-8")
        return str(p)

    def test_identical_docs(self, tmp_path):
        a = self._write(tmp_path, "a.txt", "hello world\nsecond line\n")
        b = self._write(tmp_path, "b.txt", "hello world\nsecond line\n")
        result = self._svc(rag=_FakeRag()).compare(a, b)
        assert result.error == ""
        assert result.textual.unchanged_ratio > 0.99
        assert result.structural_a.word_count == result.structural_b.word_count

    def test_addition_detected(self, tmp_path):
        a = self._write(tmp_path, "a.txt", "line one\nline two\n")
        b = self._write(tmp_path, "b.txt", "line one\nline two\nbrand new line\n")
        result = self._svc(rag=_FakeRag()).compare(a, b)
        assert result.textual.added_chars > 0
        assert any("brand new line" in l for l in result.textual.added_lines)

    def test_removal_detected(self, tmp_path):
        a = self._write(tmp_path, "a.txt", "keep me\ndelete me\n")
        b = self._write(tmp_path, "b.txt", "keep me\n")
        result = self._svc(rag=_FakeRag()).compare(a, b)
        assert result.textual.removed_chars > 0
        assert any("delete me" in l for l in result.textual.removed_lines)

    def test_reordered_content(self, tmp_path):
        a = self._write(tmp_path, "a.txt", "first part\nsecond part\n")
        b = self._write(tmp_path, "b.txt", "second part\nfirst part\n")
        result = self._svc(rag=_FakeRag()).compare(a, b)
        # Same words → unchanged ratio still high.
        assert result.textual.unchanged_ratio >= 0.5
        assert result.error == ""

    def test_unsupported_format(self, tmp_path):
        from services.document_comparison_service import DocumentComparisonService

        a = self._write(tmp_path, "a.bin", "x")
        b = self._write(tmp_path, "b.txt", "y")
        svc = DocumentComparisonService()
        result = svc.compare(a, b)
        assert result.error

    def test_cross_format_comparison(self, tmp_path):
        from services.document_comparison_service import DocumentComparisonService
        a = self._write(tmp_path, "chart.png", "Image OCR Text: Quarterly Sales Chart 2024")
        b = self._write(tmp_path, "report.pdf", "Executive Summary: Fiscal Year 2024 Sales Performance")
        svc = self._svc(rag=_FakeRag())
        result = svc.compare(a, b)
        assert result.error == ""
        assert result.structural_a.format == "png"
        assert result.structural_b.format == "pdf"
        assert result.semantic_summary != ""

    def test_structural_pdf_pages(self):
        # PDF page counts come from form feeds in the extracted text.
        svc = self._svc()
        stats_a = svc._structural("x.pdf", "page one\fpage two\fpage three")
        stats_b = svc._structural("x.pdf", "page one\fpage two")
        assert stats_a.page_or_section_count == 3
        assert stats_b.page_or_section_count == 2
        assert stats_a.format == "pdf"

    def test_semantic_summary_generated(self, tmp_path):
        rag = _FakeRag()
        a = self._write(tmp_path, "a.txt", "version one content\n")
        b = self._write(tmp_path, "b.txt", "version two content\n")
        result = self._svc(rag=rag).compare(a, b)
        assert "Content Verdict:" in result.semantic_summary
        assert result.semantic_summary.endswith("Changes are meaningful.")
        assert rag.calls >= 1

    def test_missing_file(self, tmp_path):
        a = self._write(tmp_path, "a.txt", "content")
        result = self._svc().compare(a, str(tmp_path / "missing.txt"))
        assert result.error

    def test_same_file(self, tmp_path):
        a = self._write(tmp_path, "a.txt", "content")
        result = self._svc().compare(a, a)
        assert result.textual.unchanged_ratio > 0.99

    def test_structural_headings(self, tmp_path):
        a = self._write(tmp_path, "a.md", "# Heading One\nbody\n## Sub\nmore\n")
        result = self._svc().compare(a, a)
        assert result.structural_a.headings  # markdown headings detected


class TestDocumentComparisonDialog:
    def test_dialog_constructs(self, qapp, tmp_path):
        from services.document_comparison_service import DocumentComparisonService
        from ui.dialogs.document_comparison_dialog import DocumentComparisonDialog

        p = tmp_path / "a.txt"
        p.write_text("hello")
        dlg = DocumentComparisonDialog(DocumentComparisonService(), file_a=str(p))
        assert dlg._file_a == str(p)
        dlg.close()

    def test_same_file_rejected(self, qapp, tmp_path):
        from services.document_comparison_service import DocumentComparisonService
        from ui.dialogs.document_comparison_dialog import DocumentComparisonDialog

        p = tmp_path / "a.txt"
        p.write_text("hello")
        dlg = DocumentComparisonDialog(DocumentComparisonService(),
                                       file_a=str(p), file_b=str(p))
        dlg._on_compare()
        assert "same file" in dlg.status_label.text().lower()
        dlg.close()
